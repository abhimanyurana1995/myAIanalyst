"""
In-memory state manager.

Holds everything that lives for the duration of one session:
- Uploaded DataFrames (keyed by their sanitized variable name)
- File metadata / profiles
- Chat history
- Cleaning action log
- DataFrame undo stacks (last 5 states per frame)
"""

from __future__ import annotations

import re
import time
import hashlib
import logging
from dataclasses import dataclass, field
from typing import Optional

import pandas as pd

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Data classes — shared across the whole engine
# ---------------------------------------------------------------------------

@dataclass
class ColumnProfile:
    name: str
    dtype: str              # "numeric" | "text" | "datetime" | "boolean" | "unknown"
    null_count: int
    null_percentage: float
    unique_count: int
    # Numeric
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    mean_val: Optional[float] = None
    median_val: Optional[float] = None
    std_val: Optional[float] = None
    zero_count: Optional[int] = None
    # Text
    top_values: Optional[list] = None   # [(value, count), ...]
    avg_length: Optional[float] = None
    # Datetime
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    date_gaps: Optional[bool] = None


@dataclass
class DataIssue:
    column: str             # "N/A" for row-level issues
    issue_type: str
    severity: str           # "critical" | "warning" | "info"
    count: int
    description: str
    suggested_fix: str


@dataclass
class DataHealthReport:
    overall_score: float    # 0–100
    issues: list = field(default_factory=list)   # list[DataIssue]
    duplicate_count: int = 0
    duplicate_percentage: float = 0.0
    total_null_count: int = 0


@dataclass
class FileProfile:
    filename: str
    file_type: str
    row_count: int
    column_count: int
    columns: list           # list[ColumnProfile]
    sample_rows: list       # first 5 rows as list-of-dicts
    profile_text: str       # LLM context text
    token_estimate: int


@dataclass
class IngestedFile:
    filename: str
    file_type: str
    dataframes: dict        # {var_name: pd.DataFrame}
    profile: FileProfile
    health: DataHealthReport
    raw_text: Optional[str] = None


@dataclass
class ChatMessage:
    role: str               # "user" | "assistant" | "system"
    content: str
    timestamp: float = field(default_factory=time.time)
    confidence: Optional[str] = None   # "computed" | "fallback" | None


@dataclass
class CleaningAction:
    timestamp: float
    var_name: str
    description: str
    rows_before: int
    rows_after: int


@dataclass
class ExecutionResult:
    success: bool
    output: str
    return_value: object = None
    error: str = None
    error_type: str = None  # "syntax" | "runtime" | "timeout" | "security"
    chart_path: str = None
    modified_dataframes: dict = None
    execution_time: float = 0.0


# ---------------------------------------------------------------------------
# StateManager
# ---------------------------------------------------------------------------

class StateManager:
    """Central in-memory state for one session."""

    MAX_UNDO_DEPTH = 5

    def __init__(self):
        # {var_name: pd.DataFrame}
        self.dataframes: dict[str, pd.DataFrame] = {}
        # {var_name: FileProfile}
        self.profiles: dict[str, FileProfile] = {}
        # {var_name: DataHealthReport}
        self.health_reports: dict[str, DataHealthReport] = {}
        # {var_name: str}  original filename before sanitization
        self.filenames: dict[str, str] = {}
        # {var_name: list[pd.DataFrame]}  undo stacks
        self._undo_stacks: dict[str, list] = {}
        # Ordered chat history
        self.chat_history: list[ChatMessage] = []
        # Cleaning log
        self.cleaning_log: list[CleaningAction] = []

    # ------------------------------------------------------------------
    # DataFrame management
    # ------------------------------------------------------------------

    def add_dataframe(
        self,
        var_name: str,
        df: pd.DataFrame,
        profile: FileProfile,
        health: DataHealthReport,
        original_filename: str,
    ) -> None:
        """Register a newly uploaded DataFrame."""
        self.dataframes[var_name] = df
        self.profiles[var_name] = profile
        self.health_reports[var_name] = health
        self.filenames[var_name] = original_filename
        self._undo_stacks[var_name] = []
        logger.info("Registered DataFrame '%s' (%d rows, %d cols)",
                    var_name, len(df), len(df.columns))

    def update_dataframe(self, var_name: str, new_df: pd.DataFrame) -> None:
        """Replace a DataFrame (e.g., after cleaning). Pushes old version onto undo stack."""
        if var_name not in self.dataframes:
            logger.warning("update_dataframe: '%s' not found in state", var_name)
            return
        old_df = self.dataframes[var_name]
        stack = self._undo_stacks.setdefault(var_name, [])
        stack.append(old_df)
        if len(stack) > self.MAX_UNDO_DEPTH:
            stack.pop(0)
        self.dataframes[var_name] = new_df
        logger.info("Updated DataFrame '%s': %d→%d rows", var_name, len(old_df), len(new_df))

    def undo_dataframe(self, var_name: str) -> bool:
        """Restore previous DataFrame version. Returns True if successful."""
        stack = self._undo_stacks.get(var_name, [])
        if not stack:
            return False
        self.dataframes[var_name] = stack.pop()
        logger.info("Undid last change to '%s'", var_name)
        return True

    def remove_dataframe(self, var_name: str) -> None:
        """Remove a DataFrame and all related state."""
        for store in (self.dataframes, self.profiles, self.health_reports,
                      self.filenames, self._undo_stacks):
            store.pop(var_name, None)

    def get_df_hash(self, var_name: str) -> str:
        """Return a quick hash of a DataFrame for change detection."""
        df = self.dataframes.get(var_name)
        if df is None:
            return ""
        return hashlib.md5(
            pd.util.hash_pandas_object(df, index=True).values.tobytes()
        ).hexdigest()

    # ------------------------------------------------------------------
    # Chat history
    # ------------------------------------------------------------------

    def add_chat_message(
        self,
        role: str,
        content: str,
        confidence: Optional[str] = None,
    ) -> None:
        self.chat_history.append(
            ChatMessage(role=role, content=content, confidence=confidence)
        )

    def get_recent_history(self, max_tokens: int) -> list[dict]:
        """
        Return history messages (oldest-first) that fit within max_tokens budget.
        Always keeps the most-recent messages when truncating.
        Token estimate: len(text) / 4
        """
        budget = max_tokens
        selected = []
        for msg in reversed(self.chat_history):
            cost = len(msg.content) // 4
            if cost > budget:
                break
            selected.append({"role": msg.role, "content": msg.content})
            budget -= cost
        return list(reversed(selected))

    def clear_history(self) -> None:
        self.chat_history.clear()

    # ------------------------------------------------------------------
    # Cleaning log
    # ------------------------------------------------------------------

    def log_cleaning(
        self,
        var_name: str,
        description: str,
        rows_before: int,
        rows_after: int,
    ) -> None:
        self.cleaning_log.append(CleaningAction(
            timestamp=time.time(),
            var_name=var_name,
            description=description,
            rows_before=rows_before,
            rows_after=rows_after,
        ))

    # ------------------------------------------------------------------
    # Serialization helpers (for session persistence)
    # ------------------------------------------------------------------

    def to_session_dict(self) -> dict:
        """Produce a JSON-serializable snapshot. DataFrames are NOT included."""
        return {
            "filenames": self.filenames,
            "profiles": {
                name: {
                    "filename": p.filename,
                    "file_type": p.file_type,
                    "row_count": p.row_count,
                    "column_count": p.column_count,
                    "profile_text": p.profile_text,
                }
                for name, p in self.profiles.items()
            },
            "chat_history": [
                {
                    "role": m.role,
                    "content": m.content,
                    "timestamp": m.timestamp,
                    "confidence": m.confidence,
                }
                for m in self.chat_history
            ],
            "cleaning_log": [
                {
                    "timestamp": a.timestamp,
                    "var_name": a.var_name,
                    "description": a.description,
                    "rows_before": a.rows_before,
                    "rows_after": a.rows_after,
                }
                for a in self.cleaning_log
            ],
        }

    def restore_from_session_dict(self, data: dict) -> None:
        """Restore non-DataFrame state from a session snapshot."""
        self.filenames = data.get("filenames", {})
        self.chat_history = [
            ChatMessage(
                role=m["role"],
                content=m["content"],
                timestamp=m.get("timestamp", 0.0),
                confidence=m.get("confidence"),
            )
            for m in data.get("chat_history", [])
        ]
        self.cleaning_log = [
            CleaningAction(
                timestamp=a["timestamp"],
                var_name=a["var_name"],
                description=a["description"],
                rows_before=a["rows_before"],
                rows_after=a["rows_after"],
            )
            for a in data.get("cleaning_log", [])
        ]
        # Profiles restored as lightweight dicts (DataFrames rebuilt separately)
        for name, p in data.get("profiles", {}).items():
            self.profiles[name] = FileProfile(
                filename=p["filename"],
                file_type=p["file_type"],
                row_count=p["row_count"],
                column_count=p["column_count"],
                columns=[],
                sample_rows=[],
                profile_text=p.get("profile_text", ""),
                token_estimate=len(p.get("profile_text", "")) // 4,
            )

    def clear(self) -> None:
        """Full reset — wipe all state."""
        self.dataframes.clear()
        self.profiles.clear()
        self.health_reports.clear()
        self.filenames.clear()
        self._undo_stacks.clear()
        self.chat_history.clear()
        self.cleaning_log.clear()


# ---------------------------------------------------------------------------
# Variable name sanitizer
# ---------------------------------------------------------------------------

def sanitize_name(filename: str, sheet: str = None, existing: set = None) -> str:
    """
    Convert a filename (and optional sheet name) to a valid Python variable name.

    "Sales Report 2024.csv"          → "sales_report_2024"
    "Q4 Expenses.xlsx" / "January"   → "q4_expenses_january"
    "my-data (1).csv"                → "my_data_1"
    """
    # Strip extension
    base = re.sub(r'\.[^.]+$', '', filename)
    # Append sheet name if given
    if sheet and sheet.lower() not in ("sheet1", "default"):
        base = f"{base}_{sheet}"
    # Lowercase
    base = base.lower()
    # Replace separators and special chars with underscores
    base = re.sub(r'[\s\-\(\)\[\]\{\}]+', '_', base)
    # Remove anything that's not alphanumeric or underscore
    base = re.sub(r'[^\w]', '', base)
    # Collapse multiple underscores
    base = re.sub(r'_+', '_', base).strip('_')
    # Can't start with a digit
    if base and base[0].isdigit():
        base = f"df_{base}"
    if not base:
        base = "df_data"

    # Ensure uniqueness
    if existing is not None:
        original = base
        n = 2
        while base in existing:
            base = f"{original}_{n}"
            n += 1
        existing.add(base)

    return base
