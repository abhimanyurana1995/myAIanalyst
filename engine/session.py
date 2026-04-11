"""
Session Manager — save and restore conversation state to/from disk.

IMPORTANT: DataFrames are NEVER serialized.
On restore, they are rebuilt by re-ingesting the original uploaded files.

Session file: session/session.json
"""

from __future__ import annotations

import json
import logging
import os
import time
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from engine.state import StateManager
    from engine.ingestion import FileIngestionEngine

logger = logging.getLogger(__name__)


class SessionManager:

    def __init__(self, session_dir: str = "session"):
        self.session_dir = session_dir
        self.session_file = os.path.join(session_dir, "session.json")
        os.makedirs(session_dir, exist_ok=True)

    # -----------------------------------------------------------------------
    # Save
    # -----------------------------------------------------------------------

    def save(self, state: "StateManager") -> None:
        """Persist non-DataFrame state to disk."""
        data = state.to_session_dict()
        data["_saved_at"] = time.time()
        data["_version"] = "1.0"

        tmp_path = self.session_file + ".tmp"
        try:
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2, default=str)
            # Atomic replace
            if os.path.exists(self.session_file):
                os.replace(tmp_path, self.session_file)
            else:
                os.rename(tmp_path, self.session_file)
            logger.debug("Session saved to %s", self.session_file)
        except Exception as e:
            logger.warning("Session save failed: %s", e)
            if os.path.exists(tmp_path):
                try:
                    os.remove(tmp_path)
                except OSError:
                    pass

    # -----------------------------------------------------------------------
    # Load
    # -----------------------------------------------------------------------

    def load(
        self,
        state: "StateManager",
        ingestion_engine: "FileIngestionEngine",
        upload_dir: str = "uploads",
    ) -> bool:
        """
        Restore session from disk.
        Re-ingests uploaded files to rebuild DataFrames.
        Returns True if a session was found and loaded.
        """
        if not os.path.exists(self.session_file):
            logger.info("No previous session found.")
            return False

        try:
            with open(self.session_file, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            logger.warning(
                "Session file corrupt or unreadable (%s). Starting fresh.", e
            )
            self._backup_and_reset()
            return False

        # Restore non-DataFrame state
        state.restore_from_session_dict(data)

        # Re-ingest uploaded files to rebuild DataFrames
        filenames = data.get("filenames", {})   # {var_name: original_filename}
        reloaded: list[str] = []
        failed: list[str] = []

        existing_var_names: set = set()
        for var_name, original_filename in filenames.items():
            filepath = os.path.join(upload_dir, original_filename)
            if not os.path.exists(filepath):
                logger.warning(
                    "Session references '%s' but file not found at '%s'",
                    original_filename, filepath
                )
                failed.append(original_filename)
                continue
            try:
                ingested = ingestion_engine.ingest(filepath)
                for df_var, df in ingested.dataframes.items():
                    # Prefer original var_name from session if available
                    actual_var = var_name if var_name in filenames.values() or len(ingested.dataframes) == 1 else df_var
                    state.dataframes[actual_var] = df
                    if actual_var not in state.profiles:
                        state.profiles[actual_var] = ingested.profile
                    if actual_var not in state.health_reports:
                        state.health_reports[actual_var] = ingested.health
                    existing_var_names.add(actual_var)
                reloaded.append(original_filename)
            except Exception as e:
                logger.warning("Failed to reload '%s': %s", original_filename, e)
                failed.append(original_filename)

        if reloaded:
            logger.info("Session restored. Reloaded: %s", reloaded)
        if failed:
            logger.warning("Could not reload: %s", failed)

        return True

    # -----------------------------------------------------------------------
    # Clear
    # -----------------------------------------------------------------------

    def clear(self, state: "StateManager") -> None:
        """Wipe in-memory state and delete session file."""
        state.clear()
        if os.path.exists(self.session_file):
            try:
                os.remove(self.session_file)
                logger.info("Session file deleted.")
            except OSError as e:
                logger.warning("Could not delete session file: %s", e)

    # -----------------------------------------------------------------------
    # Helpers
    # -----------------------------------------------------------------------

    def exists(self) -> bool:
        return os.path.exists(self.session_file)

    def _backup_and_reset(self) -> None:
        backup = self.session_file + f".corrupt.{int(time.time())}"
        try:
            os.rename(self.session_file, backup)
            logger.info("Corrupt session backed up to %s", backup)
        except OSError:
            pass
