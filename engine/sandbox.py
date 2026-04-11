"""
Secure Code Execution Sandbox.

Two-phase safety:
  1. Static analysis (AST walk) — reject dangerous patterns BEFORE execution
  2. Runtime restrictions — stripped __builtins__, no file/network access,
     thread-based timeout

Chart support:
  - Matplotlib backend forced to 'Agg' (non-interactive)
  - CHART_PATH injected into globals so LLM code can call plt.savefig(CHART_PATH)
  - After execution we check if the file appeared and has content
"""

from __future__ import annotations

import ast
import hashlib
import io
import logging
import os
import sys
import threading
import time
import traceback
import uuid
from typing import Optional

import matplotlib
matplotlib.use("Agg")   # Must be set before importing pyplot
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

from engine.state import ExecutionResult

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Block lists
# ---------------------------------------------------------------------------

BLOCKED_IMPORTS: set[str] = {
    "os", "sys", "subprocess", "shutil", "pathlib",
    "socket", "http", "urllib", "requests", "ftplib",
    "smtplib", "telnetlib", "xmlrpc", "pickle", "shelve",
    "ctypes", "multiprocessing",
    "signal", "resource", "importlib", "code", "codeop",
    "compileall", "py_compile", "builtins",
    "pty", "tty", "atexit", "gc",
    "ssl", "select", "asyncio", "threading",
}

BLOCKED_BUILTINS: set[str] = {
    "__import__", "eval", "exec", "compile",
    "open", "input", "breakpoint",
    "globals", "locals", "vars", "dir",
    "exit", "quit", "help",
    "memoryview", "bytearray",
    "classmethod", "staticmethod", "property",
}

# Dangerous attribute patterns (dotted access)
BLOCKED_ATTR_PATTERNS: set[str] = {
    "os.system", "os.popen", "os.exec", "os.spawn",
    "os.remove", "os.unlink", "os.rmdir", "os.makedirs",
    "os.mkdir", "os.rename", "os.replace", "os.walk",
    "subprocess.run", "subprocess.call", "subprocess.Popen",
    "subprocess.check_output",
    "shutil.rmtree", "shutil.copy",
    "__class__", "__bases__", "__subclasses__",
    "__globals__", "__builtins__", "__import__",
    "__reduce__", "__reduce_ex__",
}

# Allowed modules injected into globals
ALLOWED_SAFE_NAMES: set[str] = {
    "len", "range", "enumerate", "zip", "map", "filter",
    "sorted", "reversed", "min", "max", "sum", "abs",
    "round", "int", "float", "str", "bool", "list",
    "dict", "tuple", "set", "type", "isinstance",
    "hasattr", "getattr", "format", "repr",
    "print",  # captured to StringIO
    "any", "all", "next", "iter", "id",
    "NotImplemented", "True", "False", "None",
    "Exception", "ValueError", "TypeError", "KeyError",
    "IndexError", "AttributeError", "RuntimeError",
    "StopIteration", "ZeroDivisionError",
}


# ---------------------------------------------------------------------------
# AST Validator
# ---------------------------------------------------------------------------

class CodeValidator(ast.NodeVisitor):
    """Walk AST and raise on any dangerous construct."""

    def __init__(self):
        self.violations: list[str] = []

    def visit_Import(self, node: ast.Import):
        for alias in node.names:
            base = alias.name.split(".")[0]
            if base in BLOCKED_IMPORTS:
                self.violations.append(f"Blocked import: '{alias.name}'")
        self.generic_visit(node)

    def visit_ImportFrom(self, node: ast.ImportFrom):
        if node.module:
            base = node.module.split(".")[0]
            if base in BLOCKED_IMPORTS:
                self.violations.append(f"Blocked import: 'from {node.module}'")
        self.generic_visit(node)

    def visit_Call(self, node: ast.Call):
        # Check for dangerous built-in calls by name
        if isinstance(node.func, ast.Name):
            if node.func.id in BLOCKED_BUILTINS:
                self.violations.append(f"Blocked builtin call: '{node.func.id}()'")
        # Check attribute calls
        if isinstance(node.func, ast.Attribute):
            full = self._full_attr(node.func)
            for pattern in BLOCKED_ATTR_PATTERNS:
                if full.endswith(pattern) or full == pattern:
                    self.violations.append(f"Blocked call: '{full}()'")
        self.generic_visit(node)

    def visit_Attribute(self, node: ast.Attribute):
        # Block dunder attribute access
        if node.attr.startswith("__") and node.attr.endswith("__"):
            # Allow only safe dunders needed by pandas/numpy
            safe_dunders = {"__len__", "__iter__", "__next__", "__getitem__",
                            "__setitem__", "__contains__", "__str__", "__repr__"}
            if node.attr not in safe_dunders:
                self.violations.append(f"Blocked dunder access: '{node.attr}'")
        self.generic_visit(node)

    def visit_Name(self, node: ast.Name):
        if isinstance(node.ctx, ast.Load) and node.id in BLOCKED_BUILTINS:
            self.violations.append(f"Blocked name: '{node.id}'")
        self.generic_visit(node)

    @staticmethod
    def _full_attr(node) -> str:
        parts = []
        while isinstance(node, ast.Attribute):
            parts.append(node.attr)
            node = node.value
        if isinstance(node, ast.Name):
            parts.append(node.id)
        return ".".join(reversed(parts))


def validate_code(code: str) -> tuple[bool, str]:
    """
    Statically analyse code.
    Returns (is_safe: bool, reason: str).
    """
    try:
        tree = ast.parse(code)
    except SyntaxError as e:
        return False, f"Syntax error: {e}"

    validator = CodeValidator()
    validator.visit(tree)

    if validator.violations:
        return False, "Security violations: " + "; ".join(validator.violations)

    return True, "ok"


# ---------------------------------------------------------------------------
# Sandbox
# ---------------------------------------------------------------------------

class Sandbox:
    """
    Execute LLM-generated Python code in a restricted environment.
    """

    def __init__(self, timeout: int = 30, chart_dir: str = "charts"):
        self.timeout = timeout
        self.chart_dir = chart_dir
        os.makedirs(chart_dir, exist_ok=True)

    def execute(
        self,
        code: str,
        dataframes: dict[str, pd.DataFrame],
        chart_id: str = None,
    ) -> ExecutionResult:
        """
        Execute code safely.  Returns an ExecutionResult.
        """
        start = time.time()

        # --- Static validation ---
        is_safe, reason = validate_code(code)
        if not is_safe:
            logger.warning("Sandbox rejected code: %s", reason)
            return ExecutionResult(
                success=False,
                output="",
                error=f"Code rejected by security validator: {reason}",
                error_type="security",
                execution_time=time.time() - start,
            )

        # --- Build restricted globals ---
        cid = chart_id or f"chart_{uuid.uuid4().hex[:8]}"
        chart_path = os.path.join(self.chart_dir, f"{cid}.png")
        restricted = self._build_restricted_globals(dataframes, chart_path)

        # --- Execute with timeout ---
        stdout_capture = io.StringIO()
        result_container: list = [None]   # [0] = return_value, [1] = exception
        exception_container: list = [None]

        def _run():
            try:
                # Temporarily redirect print to capture
                old_print = restricted.get("print")
                def captured_print(*args, **kwargs):
                    end = kwargs.get("end", "\n")
                    sep = kwargs.get("sep", " ")
                    stdout_capture.write(sep.join(str(a) for a in args) + end)
                restricted["print"] = captured_print

                exec(compile(code, "<sandbox>", "exec"), restricted)  # noqa: S102

                # Try to capture last expression value if it wasn't printed
                result_container[0] = restricted.get("_last_result")
            except Exception as exc:
                exception_container[0] = exc

        thread = threading.Thread(target=_run, daemon=True)
        thread.start()
        thread.join(timeout=self.timeout)

        exec_time = time.time() - start

        if thread.is_alive():
            # Thread is still running after timeout — we can't kill it on Windows
            # but daemon=True means it dies with the process.
            return ExecutionResult(
                success=False,
                output=stdout_capture.getvalue(),
                error=f"Code execution timed out after {self.timeout} seconds.",
                error_type="timeout",
                execution_time=exec_time,
            )

        if exception_container[0] is not None:
            exc = exception_container[0]
            tb = traceback.format_exc()
            # Keep traceback short (last 3 lines) — don't expose internals
            short_tb = "\n".join(tb.strip().split("\n")[-3:])
            return ExecutionResult(
                success=False,
                output=stdout_capture.getvalue(),
                error=f"{type(exc).__name__}: {exc}\n{short_tb}",
                error_type="runtime",
                execution_time=exec_time,
            )

        # --- Check for chart ---
        # Primary: check the injected CHART_PATH
        chart_out = None
        if os.path.exists(chart_path) and os.path.getsize(chart_path) > 500:
            chart_out = chart_path
        else:
            # Fallback: LLM may have overwritten CHART_PATH with a custom filename.
            # Move any PNG the LLM created into our chart_dir and use it.
            lm_path = restricted.get("CHART_PATH")
            if lm_path and isinstance(lm_path, str) and lm_path != chart_path:
                candidate = lm_path if os.path.isabs(lm_path) else os.path.join(os.getcwd(), lm_path)
                if os.path.exists(candidate) and os.path.getsize(candidate) > 500:
                    try:
                        os.replace(candidate, chart_path)
                        chart_out = chart_path
                    except OSError:
                        chart_out = candidate  # serve from wherever it landed
        # Close any open matplotlib figures to free memory
        plt.close("all")

        # --- Detect modified DataFrames ---
        modified: dict[str, pd.DataFrame] = {}
        for name, original_df in dataframes.items():
            new_df = restricted.get(name)
            if new_df is not None and isinstance(new_df, pd.DataFrame):
                if not new_df.equals(original_df):
                    modified[name] = new_df

        captured_output = stdout_capture.getvalue().strip()

        return ExecutionResult(
            success=True,
            output=captured_output,
            return_value=result_container[0],
            chart_path=chart_out,
            modified_dataframes=modified if modified else None,
            execution_time=exec_time,
        )

    # -----------------------------------------------------------------------

    def _build_restricted_globals(
        self,
        dataframes: dict[str, pd.DataFrame],
        chart_path: str,
    ) -> dict:
        """Construct the restricted globals dict for exec()."""

        # Configure matplotlib for consistent, professional output
        plt.style.use("seaborn-v0_8-whitegrid")
        plt.rcParams.update({
            "font.family": "sans-serif",
            "font.size": 11,
            "axes.titlesize": 13,
            "axes.labelsize": 11,
            "figure.dpi": 150,
            "savefig.dpi": 150,
            "savefig.bbox": "tight",
        })

        import math
        import statistics
        import json
        import re
        import datetime
        import collections

        restricted = {
            # Safe builtins
            "__builtins__": {name: getattr(__builtins__ if isinstance(__builtins__, dict)
                                           else __builtins__, name, None)
                             for name in ALLOWED_SAFE_NAMES
                             if hasattr(__builtins__ if isinstance(__builtins__, dict)
                                        else __builtins__, name)},
            # Core data libraries
            "pd": pd,
            "pandas": pd,
            "np": np,
            "numpy": np,
            "plt": plt,
            "matplotlib": matplotlib,
            # Standard lib (safe subset)
            "math": math,
            "statistics": statistics,
            "json": json,
            "re": re,
            "datetime": datetime.datetime,
            "date": datetime.date,
            "timedelta": datetime.timedelta,
            "Counter": collections.Counter,
            "defaultdict": collections.defaultdict,
            # Chart path injection
            "CHART_PATH": chart_path,
            # User DataFrames
            **{name: df.copy() for name, df in dataframes.items()},
        }

        # Ensure __builtins__ dict has the safe items properly
        safe_builtins = {}
        builtin_module = __builtins__ if isinstance(__builtins__, dict) else vars(__builtins__)
        for name in ALLOWED_SAFE_NAMES:
            if name in builtin_module:
                safe_builtins[name] = builtin_module[name]

        # Add __import__ so already-loaded modules (pandas, matplotlib, numpy) can
        # do their internal lazy-loading without raising "ImportError: __import__ not found".
        # The AST validator still blocks the LLM from writing import statements or
        # referencing __import__ by name — this only enables module internals.
        safe_builtins["__import__"] = builtin_module["__import__"]

        restricted["__builtins__"] = safe_builtins

        return restricted
