"""
File Ingestion Engine.

Handles:
  - CSV  (auto-detect encoding + delimiter)
  - Excel (.xlsx / .xls, multi-sheet)
  - PDF  (text + table extraction via pdfplumber)

Produces a FileProfile (for LLM context) and a DataHealthReport for
every DataFrame it ingests.
"""

from __future__ import annotations

import csv
import io
import logging
import os
import re
import warnings
from typing import Optional

import chardet
import numpy as np
import pandas as pd
import pdfplumber

from engine.state import (
    ColumnProfile,
    DataHealthReport,
    DataIssue,
    FileProfile,
    IngestedFile,
    sanitize_name,
)

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Custom exceptions
# ---------------------------------------------------------------------------

class UnsupportedFileError(ValueError):
    pass

class FileParsingError(RuntimeError):
    pass

class FileTooLargeError(RuntimeError):
    pass


# ---------------------------------------------------------------------------
# Engine
# ---------------------------------------------------------------------------

ALLOWED_EXTENSIONS = {"csv", "xlsx", "xls", "pdf"}


class FileIngestionEngine:
    """Parse uploaded files into DataFrames and generate LLM-ready profiles."""

    def __init__(self, max_size_mb: float = 100):
        self.max_size_mb = max_size_mb

    # -----------------------------------------------------------------------
    # Public entry point
    # -----------------------------------------------------------------------

    def ingest(self, filepath: str) -> IngestedFile:
        """
        Main entry point.  Returns an IngestedFile containing DataFrames,
        profile text, and health report.
        """
        if not os.path.exists(filepath):
            raise FileNotFoundError(f"File not found: {filepath}")

        # Size check
        size_mb = os.path.getsize(filepath) / (1024 * 1024)
        if size_mb > self.max_size_mb:
            raise FileTooLargeError(
                f"File is {size_mb:.1f} MB. Maximum allowed is {self.max_size_mb} MB."
            )

        filename = os.path.basename(filepath)
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""

        if ext not in ALLOWED_EXTENSIONS:
            raise UnsupportedFileError(
                f"Unsupported file type '.{ext}'. "
                f"Allowed types: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
            )

        try:
            if ext == "csv":
                return self._ingest_csv(filepath, filename)
            elif ext in ("xlsx", "xls"):
                return self._ingest_excel(filepath, filename)
            elif ext == "pdf":
                return self._ingest_pdf(filepath, filename)
        except (UnsupportedFileError, FileTooLargeError):
            raise
        except Exception as exc:
            raise FileParsingError(
                f"Could not read '{filename}': {exc}"
            ) from exc

    # -----------------------------------------------------------------------
    # CSV
    # -----------------------------------------------------------------------

    def _ingest_csv(self, filepath: str, filename: str) -> IngestedFile:
        encoding = self._detect_encoding(filepath)
        delimiter = self._detect_delimiter(filepath, encoding)

        # Detect if the real header is buried below metadata rows
        header_row = self._detect_header_row(filepath, encoding, delimiter)
        if header_row > 0:
            logger.info(
                "'%s': skipping %d metadata row(s) — header detected at row %d",
                filename, header_row, header_row,
            )
            # Re-sniff delimiter starting from the real header for better accuracy
            delimiter = self._detect_delimiter(filepath, encoding, skip_lines=header_row)

        df = None
        errors_tried = []
        # Try C engine first (fast), fall back to Python engine (handles complex/large files)
        _engines = [("c", {"low_memory": False}), ("python", {})]

        for engine_name, engine_kw in _engines:
            for enc in [encoding, "utf-8", "latin-1", "cp1252"]:
                for sep in [delimiter, ",", "\t", ";", "|"]:
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            df = pd.read_csv(
                                filepath,
                                encoding=enc,
                                sep=sep,
                                skiprows=header_row,
                                on_bad_lines="skip",
                                engine=engine_name,
                                **engine_kw,
                            )
                        if len(df.columns) > 1 or len(df) > 0:
                            logger.debug(
                                "'%s': parsed with engine=%s enc=%s sep=%r",
                                filename, engine_name, enc, sep,
                            )
                            break
                        df = None
                    except Exception as e:
                        errors_tried.append(f"{engine_name}/{enc}: {e}")
                        df = None
                        continue
                if df is not None and (len(df.columns) > 1 or len(df) > 0):
                    break
            if df is not None and (len(df.columns) > 1 or len(df) > 0):
                break

        if df is None or df.empty:
            # Last resort: try without a header row, both engines
            for engine_name, engine_kw in _engines:
                try:
                    df = pd.read_csv(
                        filepath,
                        encoding=encoding,
                        sep=delimiter,
                        header=None,
                        on_bad_lines="skip",
                        engine=engine_name,
                        **engine_kw,
                    )
                    df.columns = [f"col_{i}" for i in range(len(df.columns))]
                    if not df.empty:
                        break
                    df = None
                except Exception as e:
                    errors_tried.append(str(e))
                    df = None

            if df is None:
                raise FileParsingError(
                    f"Could not parse CSV '{filename}'. Tried multiple encodings and delimiters."
                )

        var_name = sanitize_name(filename)
        df = self._optimize_dtypes(df)
        profile = self._generate_profile(df, filename, "csv", var_name)
        health = self._check_health(df)

        return IngestedFile(
            filename=filename,
            file_type="csv",
            dataframes={var_name: df},
            profile=profile,
            health=health,
        )

    def _detect_encoding(self, filepath: str) -> str:
        with open(filepath, "rb") as f:
            raw = f.read(65536)  # 64 KB — catches non-ASCII chars buried deeper in files
        result = chardet.detect(raw)
        if result["confidence"] and result["confidence"] > 0.7:
            return result["encoding"] or "utf-8"
        return "utf-8"

    def _detect_delimiter(self, filepath: str, encoding: str, skip_lines: int = 0) -> str:
        try:
            with open(filepath, "r", encoding=encoding, errors="replace") as f:
                for _ in range(skip_lines):
                    f.readline()
                sample = "".join(f.readline() for _ in range(5))
            dialect = csv.Sniffer().sniff(sample, delimiters=",\t;|")
            return dialect.delimiter
        except Exception:
            return ","

    def _detect_header_row(self, filepath: str, encoding: str, delimiter: str) -> int:
        """
        Find the 0-indexed row number of the actual column header.

        Many real-world CSVs exported from Excel, accounting tools, or BI systems
        include metadata rows before the actual data (report title, date range, filters).
        This method finds the first row where the field count stabilises — that row
        is the real header.  Returns 0 if the first row is already the header.
        """
        try:
            with open(filepath, "r", encoding=encoding, errors="replace") as f:
                raw_lines = [f.readline() for _ in range(40)]

            from collections import Counter

            # Build (line_text, field_count) pairs preserving actual row indices
            line_field_counts: list[tuple[str, int]] = []
            for ln in raw_lines:
                if not ln.strip():
                    line_field_counts.append(("", 0))   # blank — preserve index
                else:
                    count = len([p for p in ln.split(delimiter) if p.strip()])
                    line_field_counts.append((ln, count))

            non_zero = [c for _, c in line_field_counts if c > 0]
            if len(non_zero) < 2:
                return 0

            # Mode field count = expected column width of the real data
            mode_count = Counter(non_zero).most_common(1)[0][0]
            if mode_count <= 1:
                return 0   # single-column or indeterminate — leave untouched

            # First row (by actual file index) whose count is within 1 of the mode
            for i, (_, count) in enumerate(line_field_counts):
                if count >= mode_count - 1:
                    return i

            return 0
        except Exception:
            return 0

    # -----------------------------------------------------------------------
    # Excel
    # -----------------------------------------------------------------------

    def _ingest_excel(self, filepath: str, filename: str) -> IngestedFile:
        try:
            xl = pd.ExcelFile(filepath, engine="openpyxl")
        except Exception:
            xl = pd.ExcelFile(filepath)   # fallback for .xls

        sheet_names = xl.sheet_names
        dataframes: dict[str, pd.DataFrame] = {}
        existing_names: set = set()

        # Use a combined profile across all sheets
        all_profile_texts: list[str] = []
        all_issues: list[DataIssue] = []
        combined_health_score = 0.0
        sheets_loaded = 0

        for sheet in sheet_names:
            try:
                df = xl.parse(sheet, na_values=["", "NA", "N/A", "na", "n/a", "null", "NULL"])
            except Exception as e:
                logger.warning("Could not parse sheet '%s': %s", sheet, e)
                continue

            if df.empty:
                continue

            # Unmerge / forward-fill merged cells
            df = df.ffill(axis=0)
            df = self._optimize_dtypes(df)

            var_name = sanitize_name(
                filename,
                sheet=(sheet if len(sheet_names) > 1 else None),
                existing=existing_names,
            )
            profile = self._generate_profile(
                df,
                f"{filename} [Sheet: {sheet}]",
                "xlsx",
                var_name,
            )
            health = self._check_health(df)

            dataframes[var_name] = df
            all_profile_texts.append(profile.profile_text)
            all_issues.extend(health.issues)
            combined_health_score += health.overall_score
            sheets_loaded += 1

        if not dataframes:
            raise FileParsingError(f"No readable sheets found in '{filename}'.")

        # Build a combined profile object for the overall file
        first_var = next(iter(dataframes))
        first_df = dataframes[first_var]
        combined_text = "\n\n".join(all_profile_texts)
        combined_profile = FileProfile(
            filename=filename,
            file_type="xlsx",
            row_count=sum(len(d) for d in dataframes.values()),
            column_count=len(first_df.columns),
            columns=[],
            sample_rows=[],
            profile_text=combined_text,
            token_estimate=len(combined_text) // 4,
        )
        combined_health = DataHealthReport(
            overall_score=combined_health_score / max(sheets_loaded, 1),
            issues=all_issues,
        )

        return IngestedFile(
            filename=filename,
            file_type="xlsx",
            dataframes=dataframes,
            profile=combined_profile,
            health=combined_health,
        )

    # -----------------------------------------------------------------------
    # PDF
    # -----------------------------------------------------------------------

    def _ingest_pdf(self, filepath: str, filename: str) -> IngestedFile:
        full_text_parts: list[str] = []
        table_dfs: list[pd.DataFrame] = []

        with warnings.catch_warnings():
            warnings.simplefilter("ignore")  # suppress pdfplumber font descriptor noise
            with pdfplumber.open(filepath) as pdf:
                for i, page in enumerate(pdf.pages, 1):
                    text = page.extract_text() or ""
                    if text.strip():
                        full_text_parts.append(f"[Page {i}]\n{text.strip()}")

                    tables = page.extract_tables()
                    for tbl in (tables or []):
                        if not tbl or len(tbl) < 2:
                            continue
                        headers = [str(h).strip() if h else f"col_{j}"
                                   for j, h in enumerate(tbl[0])]
                        rows = tbl[1:]
                        try:
                            df = pd.DataFrame(rows, columns=headers)
                            df = self._optimize_dtypes(df)
                            if not df.empty:
                                table_dfs.append(df)
                        except Exception as e:
                            logger.warning("Could not convert PDF table to DataFrame: %s", e)

        full_text = "\n\n".join(full_text_parts)

        if not full_text.strip() and not table_dfs:
            full_text = (
                "This PDF appears to be a scanned image. "
                "Text extraction is not available. "
                "Consider converting it with an OCR tool before uploading."
            )

        dataframes: dict[str, pd.DataFrame] = {}
        existing: set = set()

        for idx, df in enumerate(table_dfs, 1):
            sheet_label = f"table{idx}" if len(table_dfs) > 1 else None
            var_name = sanitize_name(filename, sheet=sheet_label, existing=existing)
            dataframes[var_name] = df

        # If only text (no tables), create a one-column "text" DataFrame
        if not dataframes and full_text.strip():
            var_name = sanitize_name(filename, existing=existing)
            lines = [ln.strip() for ln in full_text.split("\n") if ln.strip()]
            df = pd.DataFrame({"text": lines})
            dataframes[var_name] = df

        first_var = next(iter(dataframes))
        first_df = dataframes[first_var]
        profile = self._generate_profile(first_df, filename, "pdf", first_var,
                                         extra_text=full_text[:2000] if full_text else None)
        health = self._check_health(first_df)

        return IngestedFile(
            filename=filename,
            file_type="pdf",
            dataframes=dataframes,
            profile=profile,
            health=health,
            raw_text=full_text,
        )

    # -----------------------------------------------------------------------
    # dtype optimisation
    # -----------------------------------------------------------------------

    def _optimize_dtypes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Try to parse object columns as numeric or datetime."""
        df = df.copy()
        for col in df.columns:
            if df[col].dtype != object:
                continue
            # Try numeric
            numeric = pd.to_numeric(df[col], errors="coerce")
            if numeric.notna().sum() / max(len(df), 1) > 0.7:
                df[col] = numeric
                continue
            # Try datetime
            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                try:
                    dt = pd.to_datetime(df[col], errors="coerce")
                    if dt.notna().sum() / max(len(df), 1) > 0.7:
                        df[col] = dt
                except Exception:
                    pass
        return df

    # -----------------------------------------------------------------------
    # Profile generation
    # -----------------------------------------------------------------------

    def _generate_profile(
        self,
        df: pd.DataFrame,
        display_name: str,
        file_type: str,
        var_name: str,
        extra_text: str = None,
    ) -> FileProfile:
        MAX_COLUMNS_IN_PROFILE = 50
        columns = list(df.columns)
        truncated = len(columns) > MAX_COLUMNS_IN_PROFILE
        show_cols = columns[:MAX_COLUMNS_IN_PROFILE]

        col_profiles: list[ColumnProfile] = []
        schema_lines: list[str] = []

        for col in show_cols:
            series = df[col]
            cp = self._profile_column(col, series)
            col_profiles.append(cp)
            schema_lines.append(self._format_column_line(cp))

        if truncated:
            schema_lines.append(
                f"  ... and {len(columns) - MAX_COLUMNS_IN_PROFILE} more columns"
            )

        health = self._check_health(df)

        # Sample rows (first 3, at most)
        sample_df = df.head(3)[show_cols[:8]]   # cap at 8 cols for readability
        sample_rows = sample_df.fillna("").astype(str).to_dict("records")
        sample_text = self._format_sample_table(sample_df)

        # Health summary lines
        health_lines: list[str] = [f"DATA HEALTH: Score {health.overall_score:.0f}/100"]
        for issue in health.issues[:10]:
            icon = {"critical": "🔴", "warning": "⚠", "info": "ℹ"}.get(issue.severity, "•")
            health_lines.append(f"  {icon} {issue.description}")

        profile_text = (
            f"=== FILE: {display_name} ===\n"
            f"TYPE: {file_type.upper()} | ROWS: {len(df):,} | COLUMNS: {len(columns)}\n"
            f"VARIABLE NAME: {var_name}\n"
            f"\nSCHEMA:\n" + "\n".join(schema_lines) +
            f"\n\nSAMPLE (first 3 rows):\n{sample_text}\n\n" +
            "\n".join(health_lines)
        )

        if extra_text:
            profile_text += f"\n\nEXTRACTED TEXT (first 2000 chars):\n{extra_text}"

        return FileProfile(
            filename=display_name,
            file_type=file_type,
            row_count=len(df),
            column_count=len(columns),
            columns=col_profiles,
            sample_rows=sample_rows,
            profile_text=profile_text,
            token_estimate=len(profile_text) // 4,
        )

    def _profile_column(self, col: str, series: pd.Series) -> ColumnProfile:
        null_count = int(series.isna().sum())
        null_pct = round(null_count / max(len(series), 1) * 100, 1)
        unique_count = int(series.nunique(dropna=True))

        if pd.api.types.is_numeric_dtype(series):
            clean = series.dropna()
            return ColumnProfile(
                name=col, dtype="numeric",
                null_count=null_count, null_percentage=null_pct,
                unique_count=unique_count,
                min_val=_safe_float(clean.min()),
                max_val=_safe_float(clean.max()),
                mean_val=_safe_float(clean.mean()),
                median_val=_safe_float(clean.median()),
                std_val=_safe_float(clean.std()),
                zero_count=int((clean == 0).sum()),
            )

        if pd.api.types.is_datetime64_any_dtype(series):
            clean = series.dropna()
            # Clamp out-of-bounds timestamps (e.g. corrupt Excel serial numbers)
            try:
                clean = clean[
                    (clean >= pd.Timestamp("1900-01-01")) &
                    (clean <= pd.Timestamp("2100-12-31"))
                ]
            except Exception:
                clean = pd.Series([], dtype="datetime64[ns]")
            dmin = str(clean.min().date()) if len(clean) > 0 else None
            dmax = str(clean.max().date()) if len(clean) > 0 else None
            # Simple gap detection: check if expected range has holes
            gaps = False
            if len(clean) > 1:
                try:
                    day_range = (clean.max() - clean.min()).days + 1
                    gaps = day_range > len(clean) * 2
                except Exception:
                    gaps = False
            return ColumnProfile(
                name=col, dtype="datetime",
                null_count=null_count, null_percentage=null_pct,
                unique_count=unique_count,
                date_min=dmin, date_max=dmax, date_gaps=gaps,
            )

        if pd.api.types.is_bool_dtype(series):
            clean = series.dropna()
            return ColumnProfile(
                name=col, dtype="boolean",
                null_count=null_count, null_percentage=null_pct,
                unique_count=unique_count,
            )

        # Text
        clean = series.dropna().astype(str)
        vc = series.value_counts().head(5)
        top = [(str(k), int(v)) for k, v in vc.items()]
        avg_len = float(clean.str.len().mean()) if len(clean) > 0 else 0.0
        return ColumnProfile(
            name=col, dtype="text",
            null_count=null_count, null_percentage=null_pct,
            unique_count=unique_count,
            top_values=top, avg_length=round(avg_len, 1),
        )

    def _format_column_line(self, cp: ColumnProfile) -> str:
        name_pad = cp.name[:30].ljust(12)
        dtype_pad = cp.dtype.ljust(10)
        line = f"  {name_pad} → {dtype_pad} | nulls: {cp.null_count}"
        if cp.dtype == "numeric":
            line += (
                f" | min: {_fmt(cp.min_val)} | max: {_fmt(cp.max_val)}"
                f" | mean: {_fmt(cp.mean_val)} | median: {_fmt(cp.median_val)}"
            )
        elif cp.dtype == "text":
            if cp.unique_count <= 20 and cp.top_values:
                vals = ", ".join(f'"{v}": {c}' for v, c in cp.top_values[:3])
                line += f" | unique: {cp.unique_count} | top: [{vals}]"
            else:
                line += f" | unique: {cp.unique_count}"
        elif cp.dtype == "datetime":
            line += f" | range: {cp.date_min} to {cp.date_max}"
            if cp.date_gaps:
                line += " | ⚠ gaps detected"
        return line

    def _format_sample_table(self, df: pd.DataFrame) -> str:
        if df.empty:
            return "(no data)"
        try:
            cols = list(df.columns)
            header = " | ".join(str(c)[:12] for c in cols)
            sep = "-+-".join("-" * min(len(str(c)), 12) for c in cols)
            rows = []
            for _, row in df.iterrows():
                rows.append(" | ".join(str(v)[:12] for v in row.values))
            return "\n".join([header, sep] + rows)
        except Exception:
            return "(sample unavailable)"

    # -----------------------------------------------------------------------
    # Health checks
    # -----------------------------------------------------------------------

    def _check_health(self, df: pd.DataFrame) -> DataHealthReport:
        issues: list[DataIssue] = []

        # 1. Duplicate rows
        dup_count = int(df.duplicated().sum())
        dup_pct = round(dup_count / max(len(df), 1) * 100, 1)
        if dup_count > 0:
            severity = "critical" if dup_pct > 20 else ("warning" if dup_pct > 5 else "info")
            issues.append(DataIssue(
                column="N/A", issue_type="duplicates", severity=severity,
                count=dup_count,
                description=f"{dup_count} duplicate rows ({dup_pct}%)",
                suggested_fix='Ask me to "remove duplicates"',
            ))

        total_nulls = 0
        for col in df.columns:
            series = df[col]
            null_count = int(series.isna().sum())
            if null_count == 0:
                continue
            total_nulls += null_count
            null_pct = round(null_count / max(len(df), 1) * 100, 1)
            severity = "critical" if null_pct > 20 else ("warning" if null_pct > 5 else "info")
            issues.append(DataIssue(
                column=col, issue_type="nulls", severity=severity,
                count=null_count,
                description=f"'{col}': {null_count} missing values ({null_pct}%)",
                suggested_fix=f'Ask me to "fill missing values in {col}"',
            ))

        # 3. Mixed types in object columns
        for col in df.select_dtypes(include="object").columns:
            series = df[col].dropna()
            if len(series) == 0:
                continue
            numeric_count = pd.to_numeric(series, errors="coerce").notna().sum()
            mix_pct = numeric_count / len(series)
            if 0.05 < mix_pct < 0.95:
                issues.append(DataIssue(
                    column=col, issue_type="mixed_types", severity="warning",
                    count=int(numeric_count),
                    description=f"'{col}': mixed text and numbers ({int(mix_pct*100)}% numeric)",
                    suggested_fix=f'Ask me to "fix the types in {col}"',
                ))

        # 4. Whitespace issues
        for col in df.select_dtypes(include="object").columns:
            series = df[col].dropna().astype(str)
            ws_count = int((series != series.str.strip()).sum())
            if ws_count > 0:
                issues.append(DataIssue(
                    column=col, issue_type="whitespace", severity="info",
                    count=ws_count,
                    description=f"'{col}': {ws_count} values with leading/trailing spaces",
                    suggested_fix=f'Ask me to "trim whitespace in {col}"',
                ))

        # 5. Constant columns
        for col in df.columns:
            if df[col].nunique(dropna=True) <= 1 and len(df) > 1:
                issues.append(DataIssue(
                    column=col, issue_type="constant", severity="info",
                    count=len(df),
                    description=f"'{col}': only 1 unique value — column may be useless",
                    suggested_fix=f'Ask me to "drop the {col} column"',
                ))

        # Overall score: penalise for each issue proportionally
        score = 100.0
        for issue in issues:
            penalty = {"critical": 15, "warning": 8, "info": 2}.get(issue.severity, 2)
            score -= penalty
        score = max(0.0, min(100.0, score))

        return DataHealthReport(
            overall_score=round(score, 1),
            issues=issues,
            duplicate_count=dup_count,
            duplicate_percentage=dup_pct,
            total_null_count=total_nulls,
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _safe_float(val) -> Optional[float]:
    try:
        v = float(val)
        if np.isnan(v) or np.isinf(v):
            return None
        return round(v, 2)
    except Exception:
        return None


def _fmt(val: Optional[float]) -> str:
    if val is None:
        return "N/A"
    if abs(val) >= 1_000_000:
        return f"{val:,.0f}"
    if abs(val) >= 1000:
        return f"{val:,.1f}"
    if isinstance(val, float):
        return f"{val:.2f}"
    return str(val)
