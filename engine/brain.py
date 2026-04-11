"""
Brain Engine — LLM Orchestration.

Core pipeline for every user message:
  1. Build prompt (system prompt + file profiles + history + user message)
  2. Stream response from LLM
  3. Extract any ```python code blocks
  4. Execute code in sandbox (with up to 3 retries on failure)
  5. Stream explanation of results back to user
  6. Attach confidence indicator to each response
  7. Save to chat history + auto-save session

Confidence levels:
  "computed"      — answer came from real pandas execution  ✓
  "fallback"      — code failed all retries, using text summary  ⚠
  "conversational"— no data question, no code needed  (no badge)
"""

from __future__ import annotations

import logging
import os
import re
import time
from typing import Generator

from engine.sandbox import Sandbox
from engine.session import SessionManager
from engine.state import StateManager

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Regex to extract ```python ... ``` blocks
# ---------------------------------------------------------------------------
_CODE_RE = re.compile(r"```python\s*\n(.*?)```", re.DOTALL | re.IGNORECASE)
_CODE_GENERIC_RE = re.compile(r"```\s*\n(.*?)```", re.DOTALL)

# Heuristics to detect if a response is data-related
_DATA_KEYWORDS = re.compile(
    r"\b(calculate|compute|analys|average|mean|sum|count|total|revenue|sales|"
    r"chart|plot|graph|visuali|compar|percent|trend|distribution|correlation|"
    r"top|highest|lowest|maximum|minimum|filter|group|pivot|clean|duplicate|"
    r"null|missing|column|row|dataframe|df\.)\b",
    re.IGNORECASE,
)


# ---------------------------------------------------------------------------
# BrainEngine
# ---------------------------------------------------------------------------

class BrainEngine:

    # Token budget constants
    TOTAL_BUDGET = 128_000
    RESPONSE_RESERVE = 8_192
    CODE_RESERVE = 5_000

    def __init__(
        self,
        backend,          # OllamaBackend or CloudAPIBackend
        state: StateManager,
        sandbox: Sandbox,
        session: SessionManager,
        config: dict = None,
    ):
        self.backend = backend
        self.state = state
        self.sandbox = sandbox
        self.session = session
        self.config = config or {}
        self.max_retries: int = self.config.get("sandbox", {}).get("max_retries", 3)
        self._prompt_dir = os.path.join(
            os.path.dirname(os.path.dirname(__file__)), "prompts"
        )
        self._system_template = self._load_prompt("system.md")
        self._explain_template = self._load_prompt("code_explanation.md")
        self._retry_note = (
            "The previous code raised an error. "
            "Error message:\n{error}\n\n"
            "Please fix the code and try again. "
            "Make sure to reference only columns that actually exist in the DataFrame."
        )

    # -----------------------------------------------------------------------
    # Public interface
    # -----------------------------------------------------------------------

    def chat(self, user_message: str) -> Generator[dict, None, None]:
        """
        Main entry point.  Yields SSE-style event dicts:

          {"type": "text",       "content": "chunk..."}
          {"type": "code",       "content": "python code..."}
          {"type": "chart",      "chart_id": "chart_xxx.png"}
          {"type": "cleaning",   "report": {...}}
          {"type": "confidence", "level": "computed"|"fallback"|"conversational",
                                 "label": "human-readable string"}
          {"type": "error",      "content": "error message"}
          {"type": "done"}
        """
        user_message = user_message.strip()
        if not user_message:
            yield {"type": "error", "content": "Empty message received."}
            yield {"type": "done"}
            return

        self.state.add_chat_message("user", user_message)

        try:
            yield from self._process(user_message)
        except (ConnectionError, TimeoutError) as e:
            yield {"type": "error", "content": str(e)}
            yield {"type": "done"}
        except Exception as e:
            logger.exception("Unhandled error in brain.chat()")
            yield {
                "type": "error",
                "content": (
                    "Something went wrong on my end. "
                    f"Details: {type(e).__name__}: {e}"
                ),
            }
            yield {"type": "done"}

    # -----------------------------------------------------------------------
    # Internal pipeline
    # -----------------------------------------------------------------------

    def _process(self, user_message: str) -> Generator[dict, None, None]:
        # No files loaded — short-circuit with helpful message
        if not self.state.dataframes and _DATA_KEYWORDS.search(user_message):
            msg = (
                "Please upload a CSV, Excel, or PDF file first "
                "so I can analyse your data. "
                "You can drag and drop files into the upload area above."
            )
            yield {"type": "text", "content": msg}
            self.state.add_chat_message("assistant", msg, confidence="conversational")
            self._autosave()
            yield {"type": "done"}
            return

        # Build initial prompt
        messages = self._build_prompt(user_message)

        # Stream first LLM response
        full_response = ""
        for chunk in self.backend.chat_stream(messages, temperature=self.backend.temp_analytical):
            full_response += chunk
            yield {"type": "text", "content": chunk}

        # Extract code blocks
        code_blocks = self._extract_code_blocks(full_response)

        if not code_blocks:
            # Pure conversational answer
            self.state.add_chat_message("assistant", full_response, confidence="conversational")
            self._autosave()
            yield {"type": "done"}
            return

        # ---- We have code to execute ----
        code = code_blocks[0]   # Use the first code block
        yield {"type": "code", "content": code}

        chart_prefix = f"chart_{int(time.time())}"
        success = False
        final_output = ""
        final_confidence = "fallback"

        for attempt in range(self.max_retries):
            chart_id = f"{chart_prefix}_a{attempt}"
            result = self.sandbox.execute(
                code=code,
                dataframes=self.state.dataframes,
                chart_id=chart_id,
            )

            if result.success:
                success = True
                final_output = result.output
                final_confidence = "computed"

                # Chart generated?
                if result.chart_path:
                    chart_filename = os.path.basename(result.chart_path)
                    yield {"type": "chart", "chart_id": chart_filename}

                # DataFrames modified? (data cleaning)
                if result.modified_dataframes:
                    cleaning_report = self._build_cleaning_report(
                        result.modified_dataframes
                    )
                    for name, new_df in result.modified_dataframes.items():
                        rows_before = len(self.state.dataframes[name])
                        self.state.update_dataframe(name, new_df)
                        self.state.log_cleaning(
                            var_name=name,
                            description=cleaning_report.get("summary", "Data cleaned"),
                            rows_before=rows_before,
                            rows_after=len(new_df),
                        )
                    yield {"type": "cleaning", "report": cleaning_report}

                # Stream the explanation
                explanation = yield from self._explain_result(
                    user_message, code, result.output
                )
                break   # Done — no more retries

            else:
                # Execution failed
                logger.warning(
                    "Sandbox error (attempt %d/%d): %s",
                    attempt + 1, self.max_retries, result.error
                )

                if attempt < self.max_retries - 1:
                    # Inform user we're retrying (subtle)
                    yield {
                        "type": "retry",
                        "attempt": attempt + 1,
                        "max": self.max_retries,
                    }
                    # Build retry prompt with error context
                    retry_note = self._retry_note.format(error=result.error)
                    retry_messages = self._build_retry_prompt(
                        user_message, code, result.error
                    )
                    # Get corrected code
                    corrected_response = ""
                    for chunk in self.backend.chat_stream(
                        retry_messages,
                        temperature=self.backend.temp_analytical,
                    ):
                        corrected_response += chunk

                    new_blocks = self._extract_code_blocks(corrected_response)
                    if new_blocks:
                        code = new_blocks[0]
                        yield {"type": "code", "content": code}
                    else:
                        # LLM gave up on code, stream text response instead
                        yield {"type": "text", "content": "\n\n" + corrected_response}
                        self.state.add_chat_message(
                            "assistant", corrected_response, confidence="fallback"
                        )
                        self._autosave()
                        yield {
                            "type": "confidence",
                            "level": "fallback",
                            "label": "⚠ Could not compute — answer based on data summary",
                        }
                        yield {"type": "done"}
                        return
                else:
                    # All retries exhausted
                    fallback_text = (
                        "\n\nI wasn't able to compute that precisely due to an error "
                        f"(`{result.error_type}: {(result.error or '')[:120]}`). "
                        "Here's what I can tell you based on the data profile:\n\n"
                    )
                    yield {"type": "text", "content": fallback_text}
                    fallback_messages = self._build_fallback_prompt(user_message)
                    fallback_response = ""
                    for chunk in self.backend.chat_stream(
                        fallback_messages,
                        temperature=self.backend.temp_conversational,
                    ):
                        fallback_response += chunk
                        yield {"type": "text", "content": chunk}
                    self.state.add_chat_message(
                        "assistant",
                        fallback_text + fallback_response,
                        confidence="fallback",
                    )
                    self._autosave()
                    yield {
                        "type": "confidence",
                        "level": "fallback",
                        "label": "⚠ Could not compute — answer based on data summary",
                    }
                    yield {"type": "done"}
                    return

        # Emit confidence badge
        yield {
            "type": "confidence",
            "level": final_confidence,
            "label": (
                "✓ Computed directly from your data"
                if final_confidence == "computed"
                else "⚠ Could not compute — answer based on data summary"
            ),
        }

        # Save final assistant message
        self.state.add_chat_message(
            "assistant", full_response, confidence=final_confidence
        )
        self._autosave()
        yield {"type": "done"}

    def _explain_result(
        self,
        user_message: str,
        code: str,
        output: str,
    ) -> Generator[dict, None, None]:
        """Ask the LLM to explain the execution result in plain English."""
        explain_messages = [
            {
                "role": "system",
                "content": self._build_system_text(),
            },
            {
                "role": "user",
                "content": (
                    f"Original question: {user_message}\n\n"
                    f"The code executed successfully. Here is the output:\n\n"
                    f"```\n{output[:3000]}\n```\n\n"
                    f"Please explain this result to the user in plain English. "
                    f"Reference specific numbers. Be concise (2-5 sentences). "
                    f"Do not show the code or mention technical details."
                ),
            },
        ]
        for chunk in self.backend.chat_stream(
            explain_messages,
            temperature=self.backend.temp_conversational,
        ):
            yield {"type": "text", "content": chunk}

    # -----------------------------------------------------------------------
    # Prompt builders
    # -----------------------------------------------------------------------

    def _build_prompt(self, user_message: str) -> list[dict]:
        available = (
            self.TOTAL_BUDGET
            - self.RESPONSE_RESERVE
            - self.CODE_RESERVE
        )

        system_content = self._build_system_text()
        available -= self._token_est(system_content)
        available -= self._token_est(user_message)

        history = self.state.get_recent_history(max_tokens=max(0, available))

        messages = [{"role": "system", "content": system_content}]
        messages.extend(history)
        messages.append({"role": "user", "content": user_message})
        return messages

    def _build_system_text(self) -> str:
        """Render the system prompt with current file profiles."""
        if not self.state.dataframes:
            file_profiles = "No files loaded yet."
            df_names = "None"
        else:
            profiles = []
            for var_name, profile in self.state.profiles.items():
                profiles.append(profile.profile_text)
            file_profiles = "\n\n".join(profiles)

            df_lines = []
            for var_name, df in self.state.dataframes.items():
                df_lines.append(
                    f"  {var_name}  ({len(df):,} rows × {len(df.columns)} cols)"
                )
            df_names = "\n".join(df_lines)

        from datetime import datetime
        now = datetime.now().strftime("%Y-%m-%d %H:%M")

        return self._system_template.replace("{file_profiles}", file_profiles) \
                                    .replace("{dataframe_names}", df_names) \
                                    .replace("{current_datetime}", now)

    def _build_retry_prompt(
        self, user_message: str, failed_code: str, error: str
    ) -> list[dict]:
        return [
            {"role": "system", "content": self._build_system_text()},
            {"role": "user", "content": user_message},
            {"role": "assistant", "content": f"```python\n{failed_code}\n```"},
            {
                "role": "user",
                "content": (
                    f"That code raised an error:\n\n```\n{error}\n```\n\n"
                    "Please fix it. Common causes:\n"
                    "- Column name typo (check the exact names in the schema above)\n"
                    "- Wrong data type assumption (check the dtype in the schema)\n"
                    "- Missing .dropna() before aggregation\n\n"
                    "Write corrected code only."
                ),
            },
        ]

    def _build_fallback_prompt(self, user_message: str) -> list[dict]:
        return [
            {
                "role": "system",
                "content": (
                    self._build_system_text()
                    + "\n\nNote: Code execution failed. "
                    "Answer based only on the data profiles above. "
                    "Clearly state that you could not compute the exact answer."
                ),
            },
            {"role": "user", "content": user_message},
        ]

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def _extract_code_blocks(self, text: str) -> list[str]:
        blocks = _CODE_RE.findall(text)
        if not blocks:
            blocks = _CODE_GENERIC_RE.findall(text)
        return [b.strip() for b in blocks if b.strip()]

    def _build_cleaning_report(self, modified_dfs: dict) -> dict:
        lines = []
        total_rows_changed = 0
        for name, new_df in modified_dfs.items():
            old_df = self.state.dataframes.get(name)
            if old_df is not None:
                diff = len(old_df) - len(new_df)
                if diff != 0:
                    lines.append(f"'{name}': {abs(diff)} rows {'removed' if diff > 0 else 'added'}")
                    total_rows_changed += abs(diff)
        summary = "; ".join(lines) if lines else "DataFrame modified"
        return {
            "summary": summary,
            "modified_tables": list(modified_dfs.keys()),
            "rows_changed": total_rows_changed,
        }

    def _autosave(self):
        try:
            self.session.save(self.state)
        except Exception as e:
            logger.warning("Session auto-save failed: %s", e)

    def _token_est(self, text: str) -> int:
        return len(text) // 4

    def _load_prompt(self, filename: str) -> str:
        path = os.path.join(self._prompt_dir, filename)
        try:
            with open(path, "r", encoding="utf-8") as f:
                return f.read()
        except FileNotFoundError:
            logger.warning("Prompt file not found: %s — using built-in default", path)
            return _DEFAULT_SYSTEM_PROMPT


# ---------------------------------------------------------------------------
# Fallback system prompt (used if prompts/system.md is missing)
# ---------------------------------------------------------------------------
_DEFAULT_SYSTEM_PROMPT = """You are a private data analyst. All data stays on the user's machine.

RULES:
1. For ANY question about data values — write Python pandas code. NEVER guess numbers.
2. Wrap code in ```python blocks. The backend executes it and returns the output.
3. User DataFrames are pre-loaded as variables. Use exact names listed below.
4. After code executes, explain the result in plain language using specific numbers.
5. For charts: use matplotlib, save to CHART_PATH, set figsize=(10,6), add title and labels.
6. If you cannot answer from available data, say so honestly.

Currently loaded files:
{file_profiles}

Available DataFrames:
{dataframe_names}

Current date/time: {current_datetime}
"""
