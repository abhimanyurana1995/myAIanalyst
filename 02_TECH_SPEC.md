# TECHNICAL SPECIFICATION DOCUMENT
## Project Codename: [UNNAMED]
### Local AI Data Analyst — System Architecture & Implementation Guide

**Author:** Abhimanyu Rana  
**Version:** 1.0  
**Date:** April 11, 2026  
**Status:** Pre-Development  
**Companion Document:** 01_PRD.md (Product Requirements Document)

---

## 1. SYSTEM ARCHITECTURE OVERVIEW

### 1.1 High-Level Architecture

```
┌──────────────────────────────────────────────────────────┐
│                    BROWSER (Client)                       │
│  ┌────────────┐  ┌──────────────┐  ┌──────────────────┐ │
│  │  File Drop  │  │  Chat Panel  │  │  File Cards +    │ │
│  │  Zone       │  │  (SSE stream)│  │  Profiles        │ │
│  └─────┬──────┘  └──────┬───────┘  └────────┬─────────┘ │
│        │                │                     │           │
│        │    HTTP/SSE    │                     │           │
└────────┼────────────────┼─────────────────────┼───────────┘
         │                │                     │
         ▼                ▼                     ▼
┌──────────────────────────────────────────────────────────┐
│                 FLASK SERVER (localhost:5000)             │
│                                                          │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  /upload      │  │  /chat       │  │  /files       │  │
│  │  /download    │  │  /chat/stream│  │  /chart/<id>  │  │
│  └──────┬───────┘  └──────┬───────┘  └───────────────┘  │
│         │                 │                               │
│         ▼                 ▼                               │
│  ┌──────────────┐  ┌──────────────┐  ┌───────────────┐  │
│  │  INGESTION   │  │  BRAIN       │  │  SANDBOX      │  │
│  │  ENGINE      │  │  ENGINE      │  │  (Code Exec)  │  │
│  │              │  │              │  │               │  │
│  │  - pandas    │  │  - prompt    │  │  - restricted │  │
│  │  - pdfplumber│  │    builder   │  │    globals    │  │
│  │  - chardet   │  │  - context   │  │  - pandas     │  │
│  │  - profiler  │  │    manager   │  │  - numpy      │  │
│  │              │  │  - response  │  │  - matplotlib │  │
│  │              │  │    parser    │  │  - timeout    │  │
│  └──────────────┘  └──────┬───────┘  └───────────────┘  │
│                           │                               │
│            ┌──────────────┼──────────────┐               │
│            ▼              ▼              ▼               │
│     ┌────────────┐ ┌──────────┐ ┌──────────────┐       │
│     │  SESSION   │ │  STATE   │ │  FILE STORE  │       │
│     │  MANAGER   │ │  MANAGER │ │              │       │
│     │            │ │          │ │  uploads/    │       │
│     │  session/  │ │ DataFrames│ │  charts/     │       │
│     │  *.json    │ │ in memory│ │  session/    │       │
│     └────────────┘ └──────────┘ └──────────────┘       │
│                           │                               │
└───────────────────────────┼───────────────────────────────┘
                            │
                            ▼
┌──────────────────────────────────────────────────────────┐
│              LLM BACKEND (swappable)                     │
│                                                          │
│  ┌─────────────────────┐  ┌────────────────────────┐    │
│  │  OLLAMA (local)      │  │  API (cloud demo)      │    │
│  │  localhost:11434     │  │  Gemini / Groq         │    │
│  │  Model: gemma4:e4b   │  │  Model: gemma-2-9b-it  │    │
│  │  Context: 128K       │  │  or llama-3.1-8b       │    │
│  │  Streaming: yes      │  │  Streaming: yes        │    │
│  └─────────────────────┘  └────────────────────────┘    │
│                                                          │
└──────────────────────────────────────────────────────────┘
```

### 1.2 File Structure

```
project-root/
│
├── app.py                  # Flask application entry point, all route definitions
├── config.py               # Configuration loader (yaml + env vars)
├── requirements.txt        # Python dependencies
├── config.yaml             # Default configuration
├── README.md               # Setup instructions
│
├── engine/
│   ├── __init__.py
│   ├── ingestion.py        # File parsing, profiling, health checks
│   ├── brain.py            # LLM communication, prompt building, response parsing
│   ├── sandbox.py          # Safe code execution environment
│   ├── session.py          # Session persistence (save/load/clear)
│   ├── state.py            # In-memory state manager (DataFrames, profiles, chat history)
│   └── backends/
│       ├── __init__.py
│       ├── ollama.py       # Ollama API client
│       └── cloud_api.py    # Gemini/Groq API client
│
├── static/
│   ├── index.html          # Single-page application
│   ├── style.css           # All styles
│   └── app.js              # Frontend logic (upload, chat, SSE, charts)
│
├── uploads/                # User-uploaded files (gitignored)
├── charts/                 # Generated chart images (gitignored)
├── session/                # Session persistence files (gitignored)
│
├── prompts/
│   ├── system.md           # Default system prompt
│   ├── code_generation.md  # Prompt template for code generation requests
│   ├── code_explanation.md # Prompt template for explaining results to user
│   ├── cleaning.md         # Prompt template for data cleaning operations
│   └── templates/          # Industry-specific prompt templates
│       ├── retail.md
│       ├── finance.md
│       ├── services.md
│       └── manufacturing.md
│
├── tests/
│   ├── test_ingestion.py
│   ├── test_sandbox.py
│   ├── test_brain.py
│   └── test_data/          # Sample CSV, XLSX, PDF files for testing
│       ├── sales_sample.csv
│       ├── expenses_sample.xlsx
│       └── contract_sample.pdf
│
└── .gitignore              # uploads/, charts/, session/, *.pyc, __pycache__
```

---

## 2. COMPONENT SPECIFICATIONS

### 2.1 Component: File Ingestion Engine (`engine/ingestion.py`)

#### Purpose
Parse uploaded files into pandas DataFrames and generate comprehensive text profiles for LLM context.

#### Interface

```python
class FileIngestionEngine:
    """Handles all file parsing, profiling, and health checking."""

    def ingest(self, filepath: str) -> IngestedFile:
        """
        Main entry point. Reads a file, returns structured result.
        
        Args:
            filepath: Absolute path to uploaded file
            
        Returns:
            IngestedFile object containing:
            - filename: str
            - file_type: "csv" | "xlsx" | "pdf"
            - dataframes: dict[str, pd.DataFrame]  # sheet_name -> df (for excel, "default" for csv)
            - profile: FileProfile
            - health: DataHealthReport
            - raw_text: str | None  # Only for PDFs
            
        Raises:
            UnsupportedFileError: File type not in allowed list
            FileParsingError: File is corrupt or unreadable
            FileTooLargeError: File exceeds max_size_mb config
        """
        pass

    def _parse_csv(self, filepath: str) -> pd.DataFrame:
        """
        Parse CSV with auto-detection of:
        - Delimiter (comma, tab, semicolon, pipe) via csv.Sniffer
        - Encoding (UTF-8, Latin-1, CP1252) via chardet
        - Header presence (has_header heuristic)
        
        Strategy:
        1. Read first 8KB with chardet to detect encoding
        2. Read first 5 lines with csv.Sniffer to detect delimiter
        3. Try pd.read_csv with detected params
        4. If fails, try common fallbacks: utf-8+comma, latin1+comma, utf-8+tab
        5. If all fail, raise FileParsingError with specifics
        """
        pass

    def _parse_excel(self, filepath: str) -> dict[str, pd.DataFrame]:
        """
        Parse Excel file.
        
        Strategy:
        1. Read sheet names via openpyxl
        2. If single sheet: parse and return as {"default": df}
        3. If multiple sheets: parse all, return as {sheet_name: df}
        4. Skip empty sheets
        5. Handle merged cells (unmerge and forward-fill)
        """
        pass

    def _parse_pdf(self, filepath: str) -> tuple[str, list[pd.DataFrame]]:
        """
        Parse PDF for text and tables.
        
        Strategy:
        1. Extract text page-by-page via pdfplumber
        2. Detect tables via pdfplumber.extract_tables()
        3. Convert detected tables to DataFrames
        4. Return (full_text, [table_dataframes])
        
        For PDFs with no extractable text (scanned images):
        - Return empty text with note: "This PDF appears to be scanned. 
          Text extraction is not available. Consider using OCR."
        """
        pass

    def _generate_profile(self, df: pd.DataFrame, filename: str) -> FileProfile:
        """
        Generate comprehensive text profile for LLM context.
        
        Profile structure (as text, ~1500-3000 tokens):
        
        FILE: {filename}
        TYPE: CSV | Excel (Sheet: {name}) | PDF Table
        DIMENSIONS: {rows} rows × {columns} columns
        
        COLUMNS:
        1. {col_name} (type: {dtype})
           - For numeric: min={}, max={}, mean={:.2f}, median={:.2f}, 
             std={:.2f}, nulls={}, zeros={}
           - For text: unique={}, top_values=[{val}: {count}, ...], 
             nulls={}, avg_length={:.0f}
           - For datetime: range={earliest} to {latest}, 
             nulls={}, gaps_detected={bool}
           - For boolean: true={}, false={}, nulls={}
        
        SAMPLE (first 5 rows):
        | col1 | col2 | col3 |
        |------|------|------|
        | ...  | ...  | ...  |
        
        DATA HEALTH:
        - Duplicates: {count} ({percentage}%)
        - Total nulls: {count} across {n} columns
        - Issues detected: [list of issues]
        """
        pass

    def _check_health(self, df: pd.DataFrame) -> DataHealthReport:
        """
        Automated data quality assessment.
        
        Checks:
        1. Duplicate rows: count, percentage, severity
        2. Null values: per-column count and percentage
        3. Mixed types: columns where dtype is 'object' but values 
           contain mixed numbers/strings
        4. Whitespace issues: leading/trailing spaces in string columns
        5. Date format inconsistency: columns that look like dates 
           but have mixed formats
        6. Constant columns: columns with only 1 unique value (useless)
        7. High cardinality text: text columns where almost every value 
           is unique (might be an ID, not a category)
        
        Returns:
            DataHealthReport with:
            - overall_score: float (0-100, percentage of "clean" cells)
            - issues: list[DataIssue] each with:
                - column: str
                - issue_type: str
                - severity: "critical" | "warning" | "info"
                - count: int
                - description: str
                - suggested_fix: str
        """
        pass
```

#### Data Classes

```python
from dataclasses import dataclass, field
from typing import Optional

@dataclass
class FileProfile:
    filename: str
    file_type: str
    row_count: int
    column_count: int
    columns: list[ColumnProfile]
    sample_rows: list[dict]  # First 5 rows as dicts
    profile_text: str  # The full text representation for LLM context
    token_estimate: int  # Approximate token count of profile_text

@dataclass
class ColumnProfile:
    name: str
    dtype: str  # "numeric", "text", "datetime", "boolean"
    null_count: int
    null_percentage: float
    unique_count: int
    # Numeric-specific
    min_val: Optional[float] = None
    max_val: Optional[float] = None
    mean_val: Optional[float] = None
    median_val: Optional[float] = None
    std_val: Optional[float] = None
    zero_count: Optional[int] = None
    # Text-specific
    top_values: Optional[list[tuple[str, int]]] = None  # [(value, count), ...]
    avg_length: Optional[float] = None
    # Date-specific
    date_min: Optional[str] = None
    date_max: Optional[str] = None
    date_gaps: Optional[bool] = None

@dataclass
class DataHealthReport:
    overall_score: float  # 0-100
    issues: list['DataIssue'] = field(default_factory=list)
    duplicate_count: int = 0
    duplicate_percentage: float = 0.0
    total_null_count: int = 0

@dataclass
class DataIssue:
    column: str  # "N/A" for row-level issues like duplicates
    issue_type: str
    severity: str  # "critical", "warning", "info"
    count: int
    description: str
    suggested_fix: str

@dataclass
class IngestedFile:
    filename: str
    file_type: str
    dataframes: dict  # {name: pd.DataFrame}
    profile: FileProfile
    health: DataHealthReport
    raw_text: Optional[str] = None  # PDF text
```

---

### 2.2 Component: Brain Engine (`engine/brain.py`)

#### Purpose
Manage all LLM interactions: prompt construction, context management, response parsing, and the code generation → execution → explanation loop.

#### Interface

```python
class BrainEngine:
    """Orchestrates LLM interactions and the analysis pipeline."""

    def __init__(self, backend: LLMBackend, state: StateManager):
        self.backend = backend  # Ollama or CloudAPI
        self.state = state
        self.system_prompt = self._load_system_prompt()

    def chat(self, user_message: str) -> Generator[str, None, None]:
        """
        Main entry point for user messages. Returns a generator 
        that yields response chunks (for SSE streaming).
        
        Pipeline:
        1. Add user message to chat history
        2. Build prompt (system + profiles + history + message)
        3. Send to LLM, stream response
        4. Check response for code blocks
        5. If code found:
           a. Extract code
           b. Execute in sandbox
           c. If error: send error back to LLM for retry (up to 3)
           d. If success: send result to LLM for explanation
           e. Stream explanation to user
        6. If no code: stream response directly to user
        7. Save assistant response to chat history
        8. Auto-save session
        
        Yields:
            str: chunks of response text for streaming
            Special chunks:
            - "{{CHART:chart_id}}" — frontend replaces with chart image
            - "{{CODE_START}}" / "{{CODE_END}}" — frontend wraps in collapsible
            - "{{CLEANING_REPORT:json}}" — frontend renders as structured card
        """
        pass

    def _build_prompt(self, user_message: str) -> list[dict]:
        """
        Construct the messages array for the LLM.
        
        Structure:
        [
            {"role": "system", "content": system_prompt + file_profiles},
            {"role": "user", "content": msg_1},
            {"role": "assistant", "content": reply_1},
            ... (last N messages, managed by context budget)
            {"role": "user", "content": user_message}
        ]
        
        Context budget management:
        - System prompt + profiles: ~3,000-10,000 tokens (depends on file count)
        - Reserved for response: 8,192 tokens (Gemma4 max output)
        - Reserved for code execution context: 5,000 tokens
        - Remaining budget: for chat history
        - If history exceeds budget: drop oldest messages first,
          but always keep the first message (establishes user's intent)
        
        Token estimation: len(text) / 4 (rough approximation)
        """
        pass

    def _build_system_prompt(self) -> str:
        """
        Construct the system prompt with current file context.
        
        Template loaded from prompts/system.md, then appended with:
        - List of loaded files and their profiles
        - Available DataFrame names (for code generation reference)
        - Current date/time
        - Session context (what cleaning has been done, etc.)
        """
        pass

    def _parse_response(self, full_response: str) -> ParsedResponse:
        """
        Parse LLM response to detect code blocks, chart requests, etc.
        
        Detection patterns:
        - Python code: ```python ... ``` blocks
        - Chart indication: matplotlib/plotly imports in code
        - Cleaning indication: df operations that modify data
        - Direct answer: no code blocks present
        
        Returns:
            ParsedResponse with:
            - response_type: "direct" | "code" | "chart" | "cleaning"
            - text_parts: list[str]  # Text before/after code
            - code_blocks: list[str]  # Extracted code
            - has_chart: bool
            - modifies_data: bool
        """
        pass

    def _handle_code_response(
        self, parsed: ParsedResponse, user_message: str
    ) -> Generator[str, None, None]:
        """
        Execute code and get LLM to explain results.
        
        Flow:
        1. Yield text before code block
        2. Yield "{{CODE_START}}" + code + "{{CODE_END}}"
        3. Execute code in sandbox
        4. If chart generated: yield "{{CHART:chart_id}}"
        5. If error: 
           - Build retry prompt with error message
           - Send to LLM for corrected code
           - Repeat (max 3 retries)
        6. If success:
           - Build explanation prompt with result
           - Stream LLM's explanation
        7. If data modified (cleaning):
           - Update DataFrame in state
           - Yield "{{CLEANING_REPORT:json}}"
        """
        pass

    def _estimate_tokens(self, text: str) -> int:
        """Rough token estimation: len(text) / 4"""
        return len(text) // 4
```

#### System Prompt (`prompts/system.md`)

```markdown
You are a data analyst assistant running locally on the user's machine. All data stays private — nothing is sent to any external server.

## Your Capabilities
- Analyze CSV, Excel, and PDF files the user has uploaded
- Answer questions about the data using real computations
- Generate charts and visualizations
- Clean and fix data quality issues
- Compare data across multiple files

## Rules for Answering

### When the user asks a question about data:
1. ALWAYS write Python pandas code to compute the answer. NEVER guess, estimate, or make up numbers.
2. Wrap your code in ```python blocks.
3. The user's DataFrames are available as variables. Use the exact names shown below.
4. After the code runs, you will receive the output. Then explain the result in clear, simple language.
5. Reference specific numbers from the output in your explanation.

### When writing code:
- Use pandas for all data operations
- Use matplotlib.pyplot for charts (import as plt)
- Always include: plt.tight_layout() and plt.savefig('/tmp/chart.png', dpi=150, bbox_inches='tight')
- Set figure size: plt.figure(figsize=(10, 6))
- Use the provided color palette: {chart_palette}
- Always add titles, axis labels, and legends where appropriate
- For date operations: always use pd.to_datetime() with errors='coerce'
- Print the result at the end of your code so it gets captured

### When cleaning data:
- Always report what you changed: how many rows affected, what was fixed
- Never modify the original file on disk
- Store cleaned results back in the same DataFrame variable

### When you DON'T know the answer:
- Say "I don't have enough information in the loaded files to answer that."
- Suggest what additional data would help

### Formatting:
- Use plain language. The user is a business owner, not a programmer.
- Don't show raw DataFrames unless asked. Summarize findings conversationally.
- Use specific numbers: "Revenue was ₹12.4L in March" not "Revenue was high in March"
- When showing comparisons, use percentages: "up 23% from February"

## Currently Loaded Files:
{file_profiles}

## Available DataFrames:
{dataframe_names}
```

#### Code Generation Prompt (`prompts/code_generation.md`)

```markdown
The user asked: "{user_question}"

Based on the loaded files, write Python pandas code to answer this question.

Available DataFrames:
{dataframe_vars}

Requirements:
- Print the final result using print()
- If creating a chart, save to: /tmp/chart_{timestamp}.png
- Handle potential errors (missing columns, wrong types) gracefully
- Use .head(20) when displaying DataFrames to limit output
- For monetary values, format with commas: f"₹{value:,.0f}"
```

#### Code Explanation Prompt (`prompts/code_explanation.md`)

```markdown
The code executed successfully and produced this output:

{code_output}

Now explain this result to the user in plain, conversational language. 
- Reference specific numbers from the output
- Use percentages for comparisons
- If there are insights or patterns, mention them
- Keep it concise — 2-4 sentences for simple answers, a short paragraph for complex ones
- Don't mention the code or technical implementation
```

---

### 2.3 Component: Sandbox (`engine/sandbox.py`)

#### Purpose
Execute LLM-generated Python code safely with access to user's DataFrames but no access to the file system, network, or dangerous operations.

#### Interface

```python
class Sandbox:
    """Restricted Python execution environment."""

    def __init__(self, timeout: int = 30):
        self.timeout = timeout
        self.chart_dir = "charts"

    def execute(
        self,
        code: str,
        dataframes: dict[str, pd.DataFrame],
        chart_id: str = None
    ) -> ExecutionResult:
        """
        Execute Python code in restricted environment.
        
        Args:
            code: Python code string from LLM
            dataframes: {name: DataFrame} available to the code
            chart_id: unique ID for any charts generated
            
        Returns:
            ExecutionResult with:
            - success: bool
            - output: str (captured stdout)
            - return_value: any (last expression value)
            - error: str | None (exception message if failed)
            - chart_path: str | None (path to generated chart PNG)
            - modified_dataframes: dict | None 
              (if code modified any DFs, return the new versions)
            - execution_time: float (seconds)
            
        Security measures:
        - Custom __builtins__ with dangerous functions removed
        - No import of os, sys, subprocess, shutil, socket, etc.
        - No eval(), exec(), compile(), __import__() in code
        - No file operations except matplotlib savefig to chart_dir
        - Execution in separate thread with timeout
        - Memory limit: 2GB (via resource module on Linux)
        """
        pass

    def _build_restricted_globals(
        self, dataframes: dict, chart_id: str
    ) -> dict:
        """
        Build the globals dict for exec().
        
        Allowed:
        - pandas (as pd)
        - numpy (as np)
        - matplotlib.pyplot (as plt)
        - matplotlib.dates (as mdates)
        - datetime, timedelta
        - math, statistics
        - json, re
        - collections (Counter, defaultdict)
        - All user DataFrames by name
        - print (captured to StringIO)
        - len, range, enumerate, zip, map, filter, sorted, 
          min, max, sum, abs, round, int, float, str, bool,
          list, dict, tuple, set, type, isinstance, hasattr,
          getattr, format
        
        Blocked (explicitly removed from builtins):
        - __import__
        - eval, exec, compile
        - open, input
        - globals, locals (prevent introspection)
        - exit, quit
        
        Pre-configured:
        - plt.style.use('seaborn-v0_8-whitegrid')
        - plt.rcParams with consistent font and sizes
        - CHART_PATH variable pointing to save location
        """
        pass

    def _validate_code(self, code: str) -> tuple[bool, str]:
        """
        Static analysis of code before execution.
        
        Checks (using ast module):
        - No import of blocked modules
        - No use of blocked builtins
        - No file path strings outside of chart_dir
        - No network-related function calls
        - No subprocess or os.system patterns
        - No dunder method access (__class__, __bases__, etc.)
        
        Returns:
            (is_safe: bool, reason: str)
        """
        pass

    def _execute_with_timeout(
        self, code: str, globals_dict: dict
    ) -> tuple[any, str]:
        """
        Execute code in a thread with timeout.
        
        Implementation:
        - Redirect stdout to StringIO for capture
        - Run exec() in a daemon thread
        - Join with timeout
        - If timeout exceeded: raise TimeoutError
        - Return (last_expression_value, captured_stdout)
        """
        pass
```

#### Execution Result Data Class

```python
@dataclass
class ExecutionResult:
    success: bool
    output: str  # Captured stdout
    return_value: any = None
    error: str = None
    error_type: str = None  # "syntax", "runtime", "timeout", "security"
    chart_path: str = None
    modified_dataframes: dict = None
    execution_time: float = 0.0
```

---

### 2.4 Component: LLM Backends (`engine/backends/`)

#### Purpose
Abstract LLM communication so Ollama (local) and cloud APIs (Gemini/Groq) are interchangeable.

#### Interface (Base Class)

```python
from abc import ABC, abstractmethod
from typing import Generator

class LLMBackend(ABC):
    """Abstract base for LLM communication."""

    @abstractmethod
    def chat_stream(
        self, messages: list[dict], temperature: float = 0.3
    ) -> Generator[str, None, None]:
        """
        Send messages to LLM and yield response chunks.
        
        Args:
            messages: [{"role": "system"|"user"|"assistant", "content": str}]
            temperature: 0.0-1.0
            
        Yields:
            str: response text chunks
        """
        pass

    @abstractmethod
    def chat_complete(
        self, messages: list[dict], temperature: float = 0.3
    ) -> str:
        """
        Send messages and return complete response (non-streaming).
        Used for code explanation step where we need the full response
        before processing.
        """
        pass

    @abstractmethod
    def health_check(self) -> bool:
        """Check if the backend is available and responsive."""
        pass
```

#### Ollama Backend (`engine/backends/ollama.py`)

```python
class OllamaBackend(LLMBackend):
    """Local Ollama API client."""

    def __init__(self, host: str, model: str):
        self.host = host  # "http://localhost:11434"
        self.model = model  # "gemma4:e4b"
        self.api_url = f"{host}/api/chat"

    def chat_stream(self, messages, temperature=0.3):
        """
        POST to /api/chat with stream=true.
        
        Request body:
        {
            "model": "gemma4:e4b",
            "messages": [...],
            "stream": true,
            "options": {
                "temperature": temperature,
                "top_p": 0.95,
                "top_k": 64,
                "num_predict": 8192,
                "num_ctx": 128000
            }
        }
        
        Response: newline-delimited JSON objects, each with:
        {"message": {"content": "chunk"}, "done": false}
        ...
        {"message": {"content": ""}, "done": true}
        
        Yield message.content from each chunk until done=true.
        """
        pass

    def chat_complete(self, messages, temperature=0.3):
        """Same as stream but with stream=false. Returns full response."""
        pass

    def health_check(self):
        """GET /api/tags — if 200, Ollama is running."""
        pass
```

#### Cloud API Backend (`engine/backends/cloud_api.py`)

```python
class CloudAPIBackend(LLMBackend):
    """Gemini or Groq API client for demo mode."""

    def __init__(self, provider: str, model: str, api_key: str):
        self.provider = provider  # "gemini" or "groq"
        self.model = model
        self.api_key = api_key

        if provider == "gemini":
            self.api_url = "https://generativelanguage.googleapis.com/v1beta/models"
            # Uses Gemini's generateContent endpoint with streaming
        elif provider == "groq":
            self.api_url = "https://api.groq.com/openai/v1/chat/completions"
            # Uses OpenAI-compatible endpoint

    def chat_stream(self, messages, temperature=0.3):
        """
        For Gemini: 
            POST /v1beta/models/{model}:streamGenerateContent
            Convert messages format to Gemini's content array
            
        For Groq:
            POST /v1/chat/completions with stream=true
            Standard OpenAI streaming format (SSE with data: prefixes)
        """
        pass
```

---

### 2.5 Component: State Manager (`engine/state.py`)

#### Purpose
Centralized in-memory state for all loaded DataFrames, file profiles, chat history, and cleaning log.

```python
class StateManager:
    """Single source of truth for application state."""

    def __init__(self):
        self.files: dict[str, IngestedFile] = {}  # filename -> IngestedFile
        self.dataframes: dict[str, pd.DataFrame] = {}  # df_name -> DataFrame
        self.dataframe_history: dict[str, list[pd.DataFrame]] = {}  # For undo (last 5)
        self.chat_history: list[dict] = []  # [{"role": "...", "content": "...", "timestamp": "..."}]
        self.cleaning_log: list[dict] = []  # [{"action": "...", "details": "...", "timestamp": "..."}]

    def add_file(self, ingested: IngestedFile) -> list[str]:
        """
        Add an ingested file to state.
        
        Returns list of DataFrame variable names created.
        
        Naming convention:
        - CSV: variable name = sanitized filename (e.g., "sales_2024")
        - Excel single sheet: same as CSV
        - Excel multi-sheet: "{filename}_{sheet_name}" (e.g., "report_q1", "report_q2")
        - PDF tables: "{filename}_table_{n}" (e.g., "contract_table_1")
        
        Sanitization: lowercase, replace spaces/hyphens with underscores,
        remove special characters, ensure valid Python identifier.
        """
        pass

    def get_all_profiles_text(self) -> str:
        """Concatenate all file profile texts for system prompt."""
        pass

    def get_dataframe_names(self) -> str:
        """Return formatted list of available DataFrame variables and their shapes."""
        pass

    def update_dataframe(self, name: str, new_df: pd.DataFrame):
        """
        Replace a DataFrame (after cleaning).
        Saves previous version to history for undo.
        Max 5 history entries per DataFrame.
        """
        pass

    def undo_dataframe(self, name: str) -> bool:
        """Restore previous version of DataFrame. Returns success."""
        pass

    def add_chat_message(self, role: str, content: str):
        """Add message to chat history with timestamp."""
        pass

    def get_recent_history(self, max_tokens: int) -> list[dict]:
        """
        Return recent chat history that fits within token budget.
        Always includes the first user message.
        Drops oldest messages first.
        """
        pass

    def clear(self):
        """Reset all state for new session."""
        pass
```

---

### 2.6 Component: Session Manager (`engine/session.py`)

#### Purpose
Persist and restore application state across browser/app restarts.

```python
class SessionManager:
    """Handles saving and loading session state to/from disk."""

    def __init__(self, session_dir: str = "session"):
        self.session_dir = session_dir
        self.session_file = os.path.join(session_dir, "session.json")

    def save(self, state: StateManager):
        """
        Save current state to disk.
        
        Saved data:
        {
            "version": "1.0",
            "timestamp": "2026-04-11T...",
            "files": {
                "filename": {
                    "filepath": "uploads/...",
                    "file_type": "csv",
                    "profile_text": "...",
                    "cleaning_log": [...]
                }
            },
            "chat_history": [...],
            "cleaning_log": [...]
        }
        
        NOTE: DataFrames are NOT serialized. They are rebuilt
        from the uploaded files on session restore. This keeps
        session files small and avoids pickle security issues.
        """
        pass

    def load(self, state: StateManager, ingestion: FileIngestionEngine) -> bool:
        """
        Restore state from disk.
        
        Process:
        1. Read session.json
        2. For each file: re-ingest from uploads/ directory
        3. Restore chat history
        4. Restore cleaning log
        5. Re-apply cleaning operations (stored as pandas code strings)
        
        Returns True if session loaded, False if no session found.
        """
        pass

    def clear(self):
        """Delete session files and uploaded files."""
        pass
```

---

### 2.7 Component: Flask Application (`app.py`)

#### Route Definitions

```python
"""
Flask routes:

GET  /                  → Serve index.html
POST /upload            → Accept file upload, run ingestion, return file profile
GET  /files             → Return list of loaded files with profiles
GET  /chat/stream       → SSE endpoint for streaming chat (query param: message)
POST /chat              → Non-streaming chat fallback
GET  /download/<name>   → Download DataFrame as CSV/XLSX
GET  /chart/<id>        → Serve generated chart image
POST /session/clear     → Clear session and start fresh
GET  /health            → Health check (is Ollama running?)
"""
```

#### Detailed Route Specs

```python
# POST /upload
# Content-Type: multipart/form-data
# Body: file (binary)
# Response: {
#     "success": true,
#     "file": {
#         "filename": "sales_2024.csv",
#         "file_type": "csv",
#         "row_count": 1200,
#         "column_count": 8,
#         "columns": [...],
#         "health_score": 87.3,
#         "health_issues": [...],
#         "dataframe_names": ["sales_2024"],
#         "profile_preview": "first 200 chars of profile text"
#     }
# }
# Error Response: {"success": false, "error": "...", "error_type": "..."}

# GET /chat/stream?message=What+was+my+best+month
# Response: Server-Sent Events (SSE)
# Content-Type: text/event-stream
# 
# data: {"type": "text", "content": "Based on "}
# data: {"type": "text", "content": "your sales data"}
# data: {"type": "code", "content": "df.groupby(...)", "visible": false}
# data: {"type": "chart", "chart_id": "chart_1712845200_bar"}
# data: {"type": "text", "content": "Your best month was September..."}
# data: {"type": "done"}
#
# SSE event types:
# - "text": regular response text chunk
# - "code": code being executed (hidden by default, expandable)
# - "chart": chart generated (frontend renders image)
# - "cleaning": data cleaning report (frontend renders card)
# - "error": error message
# - "retry": code retry attempt (shows retry count)
# - "done": stream complete

# GET /download/sales_2024?format=csv
# Response: File download (Content-Disposition: attachment)
# Supported formats: csv, xlsx

# GET /health
# Response: {
#     "status": "ok" | "error",
#     "ollama": true | false,
#     "model_loaded": true | false,
#     "model_name": "gemma4:e4b",
#     "files_loaded": 3,
#     "session_active": true
# }
```

---

## 3. FRONTEND SPECIFICATION

### 3.1 HTML Structure (`static/index.html`)

```
Single-page app, no framework. Vanilla HTML + CSS + JS.

<body>
  <header id="top-bar">
    <div class="logo">[Project Name]</div>
    <div class="file-indicator">No files loaded</div>
    <div class="actions">
      <button id="new-session">New Session</button>
      <button id="settings-toggle">⚙</button>
    </div>
  </header>

  <section id="file-area">
    <div id="drop-zone">
      <!-- Visual drop zone with icon and text -->
      <!-- Highlights on dragover -->
    </div>
    <div id="file-cards">
      <!-- Dynamically populated file cards -->
    </div>
  </section>

  <section id="chat-area">
    <div id="messages">
      <!-- Dynamically populated messages -->
      <!-- Empty state: suggested question cards -->
    </div>
    <div id="input-area">
      <textarea id="message-input" placeholder="Ask about your data..."></textarea>
      <button id="send-btn">Send</button>
    </div>
  </section>

  <div id="settings-panel" class="hidden">
    <!-- Backend selector, theme, export options -->
  </div>
</body>
```

### 3.2 JavaScript Architecture (`static/app.js`)

```javascript
/**
 * Frontend application structure:
 * 
 * State:
 * - loadedFiles: Map<filename, fileProfile>
 * - isStreaming: boolean
 * - currentEventSource: EventSource | null
 * 
 * Core Functions:
 * 
 * File Handling:
 * - initDropZone() → set up drag/drop events on #drop-zone
 * - uploadFile(file) → POST to /upload, update UI with result
 * - renderFileCard(fileProfile) → create and append file card element
 * - updateFileIndicator() → update top bar file count
 * 
 * Chat:
 * - sendMessage(text) → start SSE connection to /chat/stream
 * - handleSSE(event) → process each SSE event by type
 * - renderUserMessage(text) → append user message bubble
 * - renderAssistantMessage() → create assistant bubble, update incrementally
 * - renderChart(chartId) → insert chart image into message
 * - renderCleaningReport(data) → insert structured cleaning card
 * - renderCodeBlock(code) → insert collapsible code block
 * 
 * Session:
 * - loadSession() → GET /files, populate UI if session exists
 * - clearSession() → POST /session/clear, reset UI
 * 
 * SSE Handling:
 * - connectSSE(message) → new EventSource('/chat/stream?message=...')
 * - Event listeners for: text, code, chart, cleaning, error, done
 * - On 'done': close EventSource, re-enable input
 * - On error: show error message, re-enable input
 * 
 * Utilities:
 * - escapeHtml(text) → prevent XSS in rendered messages
 * - formatNumber(n) → Indian number formatting (₹12,34,567)
 * - autoResizeTextarea() → grow input box with content
 * - scrollToBottom() → keep chat scrolled to latest message
 */
```

### 3.3 SSE (Server-Sent Events) Implementation

```
Client-side SSE is simpler than WebSockets and perfect for
one-way streaming (server → client).

Connection:
  const es = new EventSource(`/chat/stream?message=${encodeURIComponent(text)}`);

Event handling:
  es.addEventListener('message', (e) => {
    const data = JSON.parse(e.data);
    switch(data.type) {
      case 'text': appendToCurrentMessage(data.content); break;
      case 'code': renderCodeBlock(data.content); break;
      case 'chart': renderChart(data.chart_id); break;
      case 'cleaning': renderCleaningReport(data.report); break;
      case 'error': showError(data.content); break;
      case 'done': es.close(); enableInput(); break;
    }
  });

  es.onerror = () => { es.close(); showError('Connection lost'); enableInput(); };

Flask-side SSE:
  @app.route('/chat/stream')
  def chat_stream():
    message = request.args.get('message')
    def generate():
      for chunk in brain.chat(message):
        yield f"data: {json.dumps(chunk)}\n\n"
    return Response(generate(), mimetype='text/event-stream')
```

---

## 4. DATA FLOW DIAGRAMS

### 4.1 File Upload Flow

```
User drops file
    │
    ▼
Browser: FormData POST to /upload
    │
    ▼
Flask: Save file to uploads/
    │
    ▼
Ingestion Engine:
    ├── Detect file type
    ├── Parse (pandas / pdfplumber)
    ├── Generate profile (stats, schema, sample)
    ├── Run health check (duplicates, nulls, types)
    └── Return IngestedFile
    │
    ▼
State Manager:
    ├── Store DataFrame(s) in memory
    ├── Store profile
    └── Generate DataFrame variable name(s)
    │
    ▼
Session Manager: Auto-save
    │
    ▼
Flask: Return JSON response with file card data
    │
    ▼
Browser: Render file card, update indicator
```

### 4.2 Chat Query Flow (with code execution)

```
User types: "What was my best month?"
    │
    ▼
Browser: GET /chat/stream?message=...  (SSE connection opens)
    │
    ▼
Brain Engine:
    ├── Add message to history
    ├── Build prompt:
    │   ├── System prompt
    │   ├── All file profiles (~3K tokens)
    │   ├── Last N chat messages (~5K tokens)
    │   └── Current question
    ├── Send to LLM backend (Ollama/API)
    │
    ▼
LLM responds (streaming):
    "Based on your sales data, let me calculate that.
    ```python
    monthly = sales_2024.groupby(
        pd.to_datetime(sales_2024['date']).dt.to_period('M')
    )['revenue'].sum()
    best = monthly.idxmax()
    print(f"Best month: {best}, Revenue: ₹{monthly[best]:,.0f}")
    ```"
    │
    ▼
Brain Engine detects code block:
    ├── Yields text: "Based on your sales data, let me calculate that."
    ├── Yields code event: {type: "code", content: "..."}
    ├── Extracts code
    ├── Sends to Sandbox
    │
    ▼
Sandbox:
    ├── Validates code (AST check)
    ├── Builds restricted globals (with sales_2024 DataFrame)
    ├── Executes with timeout
    ├── Captures stdout: "Best month: 2024-09, Revenue: ₹12,43,500"
    └── Returns ExecutionResult(success=True, output="...")
    │
    ▼
Brain Engine:
    ├── Builds explanation prompt with result
    ├── Sends to LLM: "Explain this result: Best month: 2024-09, Revenue: ₹12,43,500"
    │
    ▼
LLM responds:
    "Your best performing month was September 2024, with total revenue
     of ₹12,43,500. That's about 23% higher than your monthly average."
    │
    ▼
Brain Engine:
    ├── Yields text chunks (streaming)
    ├── Saves full response to chat history
    ├── Auto-saves session
    └── Yields done event
    │
    ▼
Browser: Displays complete message with expandable code block
```

### 4.3 Chart Generation Flow

```
User types: "Show me a bar chart of monthly revenue"
    │
    ▼
(Same flow as 4.2 until LLM generates code)
    │
    ▼
LLM generates code with matplotlib:
    ```python
    import matplotlib.pyplot as plt
    monthly = sales_2024.groupby(...)['revenue'].sum()
    fig, ax = plt.subplots(figsize=(10, 6))
    monthly.plot(kind='bar', ax=ax, color='#1E40AF')
    ax.set_title('Monthly Revenue — 2024')
    ax.set_ylabel('Revenue (₹)')
    plt.tight_layout()
    plt.savefig(CHART_PATH, dpi=150, bbox_inches='tight')
    print("Chart saved successfully")
    ```
    │
    ▼
Sandbox:
    ├── CHART_PATH set to "charts/chart_1712845200_bar.png"
    ├── Executes code
    ├── matplotlib saves PNG
    └── Returns ExecutionResult(chart_path="charts/...")
    │
    ▼
Brain Engine:
    ├── Yields chart event: {type: "chart", chart_id: "chart_1712845200_bar"}
    ├── Gets LLM to explain the chart
    └── Yields explanation text
    │
    ▼
Browser:
    ├── Receives chart event
    ├── Creates <img src="/chart/chart_1712845200_bar">
    └── Displays chart inline in conversation
```

---

## 5. ERROR HANDLING SPECIFICATION

### 5.1 Error Categories and Responses

| Error | Detection | User-Facing Message | Recovery |
|---|---|---|---|
| Ollama not running | health_check() returns False | "The AI engine isn't running. Start Ollama with: `ollama serve`" | Show retry button |
| Model not found | Ollama returns 404 | "The AI model isn't installed. Run: `ollama pull gemma4:e4b`" | Show instructions |
| File too large | Size check before parsing | "This file is {size}MB. Maximum is {max}MB." | Suggest splitting |
| Corrupt file | Parser exception | "This file couldn't be read. It may be corrupted or in an unsupported format." | Suggest re-saving from Excel |
| Encoding error | chardet confidence < 0.5 | "This file has unusual encoding. Try saving it as UTF-8 from Excel." | Suggest fix |
| Code execution error | Sandbox catches exception | Hidden from user; LLM gets error for retry | Auto-retry up to 3x |
| Code timeout | Thread join exceeds limit | "That analysis took too long. Try asking a more specific question." | Continue conversation |
| LLM timeout | Request exceeds 120s | "The AI is taking too long to respond. Try asking a simpler question." | Continue conversation |
| Context overflow | Token estimate exceeds limit | Automatic: prune oldest messages | Transparent to user |
| Session corruption | JSON parse error on load | "Previous session couldn't be restored. Starting fresh." | Fresh start, no crash |

### 5.2 Retry Logic for Code Execution

```
Attempt 1: Execute LLM-generated code
    ├── Success → proceed to explanation
    └── Failure → capture error message
        │
        ▼
Attempt 2: Send to LLM: "Your code produced this error: {error}. 
            Fix the code and try again. The available columns are: {columns}"
    ├── Success → proceed to explanation  
    └── Failure → capture error message
        │
        ▼
Attempt 3: Send to LLM: "Second attempt also failed: {error}. 
            Please write simpler code. Available DataFrames: {df_info}"
    ├── Success → proceed to explanation
    └── Failure → give up
        │
        ▼
Tell user: "I wasn't able to compute that. Here's what I know 
from the data profiles: {conversational answer from profiles}"
```

---

## 6. CONFIGURATION REFERENCE

### 6.1 Environment Variables

```bash
# LLM Backend
LLM_BACKEND=ollama              # "ollama" or "api"
OLLAMA_HOST=http://localhost:11434
OLLAMA_MODEL=gemma4:e4b

# Cloud API (demo mode only)
API_PROVIDER=gemini             # "gemini" or "groq"
GEMINI_API_KEY=your_key_here
GROQ_API_KEY=your_key_here

# Application
APP_HOST=127.0.0.1
APP_PORT=5000
APP_DEBUG=false

# Limits
MAX_FILE_SIZE_MB=100
SANDBOX_TIMEOUT=30
LLM_TIMEOUT=120
SESSION_TIMEOUT_MIN=0           # 0 = no timeout
```

### 6.2 Dependencies (`requirements.txt`)

```
flask>=3.0.0
pandas>=2.0.0
openpyxl>=3.1.0          # Excel support for pandas
pdfplumber>=0.10.0       # PDF text and table extraction
matplotlib>=3.8.0        # Chart generation
numpy>=1.24.0            # Numerical operations (pandas dependency)
requests>=2.31.0         # HTTP client for Ollama API
chardet>=5.0.0           # Encoding detection
pyyaml>=6.0.0            # Config file parsing
```

No additional system dependencies. No npm. No Docker (for the app itself). No build step.

---

## 7. TESTING STRATEGY

### 7.1 Unit Tests

```
tests/
├── test_ingestion.py
│   ├── test_csv_parsing_comma_delimited
│   ├── test_csv_parsing_tab_delimited
│   ├── test_csv_parsing_semicolon_delimited
│   ├── test_csv_encoding_utf8
│   ├── test_csv_encoding_latin1
│   ├── test_excel_single_sheet
│   ├── test_excel_multi_sheet
│   ├── test_pdf_text_extraction
│   ├── test_pdf_table_extraction
│   ├── test_profile_generation_numeric
│   ├── test_profile_generation_text
│   ├── test_profile_generation_dates
│   ├── test_health_check_duplicates
│   ├── test_health_check_nulls
│   ├── test_health_check_mixed_types
│   ├── test_corrupt_file_handling
│   └── test_empty_file_handling
│
├── test_sandbox.py
│   ├── test_basic_execution
│   ├── test_pandas_operations
│   ├── test_matplotlib_chart_generation
│   ├── test_import_blocking (os, sys, subprocess)
│   ├── test_builtin_blocking (eval, exec, open)
│   ├── test_timeout_enforcement
│   ├── test_syntax_error_handling
│   ├── test_runtime_error_handling
│   ├── test_dataframe_access
│   └── test_dataframe_modification_capture
│
├── test_brain.py
│   ├── test_prompt_building
│   ├── test_context_budget_management
│   ├── test_code_block_extraction
│   ├── test_response_type_detection
│   ├── test_retry_on_code_error
│   └── test_history_pruning
│
└── test_data/
    ├── sales_sample.csv          # 100 rows, typical sales data
    ├── expenses_sample.xlsx      # Multi-sheet, Q1-Q4
    ├── messy_data.csv            # Duplicates, nulls, mixed types
    ├── large_sample.csv          # 50,000 rows
    ├── unicode_data.csv          # Hindi text, special characters
    ├── semicolon_delimited.csv   # European-style CSV
    └── contract_sample.pdf       # Text + tables
```

### 7.2 Integration Tests

```
- Full flow: upload CSV → ask question → get answer with real computation
- Full flow: upload Excel → ask for chart → get chart PNG
- Full flow: upload messy CSV → ask to clean → download cleaned file
- Multi-file: upload 2 files → ask cross-file question → get joined answer
- Session: upload + chat → restart server → verify session restored
- Error recovery: Ollama down → start Ollama → verify recovery
- Demo mode: same flows with API backend instead of Ollama
```
