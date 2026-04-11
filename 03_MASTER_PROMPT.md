# MASTER PROMPT — PROJECT BLUEPRINT
## For AI Coding Agents (Claude Code, Cursor, Windsurf, etc.)

**Purpose:** This document is the single source of truth for any AI coding agent tasked with building this project. Read this ENTIRE document before writing any code. Every architectural decision, every edge case, every file path is specified here.

**Companion Documents:**
- `01_PRD.md` — Product requirements, user stories, business context
- `02_TECH_SPEC.md` — Detailed technical specifications, data classes, interfaces

---

## PROJECT IDENTITY

**What:** A locally-hosted, browser-based AI data analyst. Users upload CSV, Excel, or PDF files and chat with an AI that performs real computations on their data using pandas, generates visualizations, cleans data quality issues, and explains everything in plain English.

**Core Principle:** The LLM is the TRANSLATOR, not the CALCULATOR. It translates natural language questions into pandas code, the code executes against real data, and the LLM explains the results. The LLM never guesses numbers.

**Tech Stack:**
- Python 3.10+ (backend)
- Flask (web server)
- pandas + openpyxl (data handling)
- pdfplumber (PDF parsing)
- matplotlib (chart generation)
- Ollama API (local LLM — Gemma4 E4B)
- Gemini/Groq API (cloud demo mode)
- Vanilla HTML + CSS + JS (frontend — NO React, NO npm, NO build tools)
- Server-Sent Events (streaming)

**Hardware Context:** This runs on the developer's laptop — Lenovo Legion 5, 24GB RAM, RTX 4060 8GB VRAM, Windows 11 with WSL2. The primary LLM is Gemma4 E4B running through Ollama locally.

---

## COMPLETE FILE STRUCTURE

Create exactly this structure. Do not add extra files, frameworks, or build tools.

```
project-root/
│
├── app.py                      # Flask application — all routes
├── config.py                   # Configuration loader
├── requirements.txt            # Python dependencies (8 packages only)
├── config.yaml                 # Default configuration
├── README.md                   # Setup and usage instructions
├── .gitignore                  # Standard Python + project-specific ignores
│
├── engine/
│   ├── __init__.py             # Empty
│   ├── ingestion.py            # File parsing + profiling + health checks
│   ├── brain.py                # LLM orchestration + prompt building + code loop
│   ├── sandbox.py              # Restricted code execution
│   ├── session.py              # Session persistence
│   ├── state.py                # In-memory state (DataFrames, history, profiles)
│   └── backends/
│       ├── __init__.py         # Empty
│       ├── ollama.py           # Ollama API client (local)
│       └── cloud_api.py        # Gemini/Groq API client (demo)
│
├── static/
│   ├── index.html              # Single-page app
│   ├── style.css               # All styling
│   └── app.js                  # All frontend logic
│
├── prompts/
│   ├── system.md               # Main system prompt template
│   ├── code_generation.md      # Code generation prompt
│   ├── code_explanation.md     # Result explanation prompt
│   └── cleaning.md             # Data cleaning prompt
│
├── uploads/                    # User files (gitignored, created at runtime)
├── charts/                     # Generated charts (gitignored, created at runtime)
└── session/                    # Session files (gitignored, created at runtime)
```

**requirements.txt — EXACTLY these, nothing more:**
```
flask>=3.0.0
pandas>=2.0.0
openpyxl>=3.1.0
pdfplumber>=0.10.0
matplotlib>=3.8.0
numpy>=1.24.0
requests>=2.31.0
chardet>=5.0.0
pyyaml>=6.0.0
```

---

## BUILD ORDER

Build and test each component in this exact order. Do not skip ahead. Each component must work independently before integrating with the next.

### STEP 1: Configuration (`config.py` + `config.yaml`)

Build the configuration system first. Everything else depends on it.

```yaml
# config.yaml — default values
app:
  name: "Local Data Analyst"
  host: "127.0.0.1"
  port: 5000
  debug: false

llm:
  backend: "ollama"
  ollama:
    host: "http://localhost:11434"
    model: "gemma4:e4b"
    temperature_analytical: 0.3
    temperature_conversational: 0.7
    max_tokens: 8192
    context_window: 128000
  api:
    provider: "gemini"
    model: "gemma-2-9b-it"
    api_key: "${GEMINI_API_KEY}"

files:
  max_size_mb: 100
  upload_dir: "uploads"
  chart_dir: "charts"
  allowed_types: ["csv", "xlsx", "xls", "pdf"]

session:
  dir: "session"
  auto_save: true

sandbox:
  timeout_seconds: 30
  max_retries: 3

ui:
  chart_palette: ["#1E40AF", "#059669", "#D97706", "#DC2626", "#7C3AED", "#DB2777"]
```

`config.py` loads config.yaml, then overrides with environment variables. Pattern: `LLM_BACKEND` env var overrides `llm.backend` in yaml.

**Test:** Run `python config.py` — should print loaded config without errors.

---

### STEP 2: File Ingestion Engine (`engine/ingestion.py`)

Build the complete file parsing and profiling system.

**Detailed behavior for CSV parsing:**
1. Read first 8192 bytes with `chardet.detect()` to determine encoding
2. If confidence > 0.7, use detected encoding; else try UTF-8, then Latin-1
3. Read first 5 lines with `csv.Sniffer().sniff()` to detect delimiter
4. If Sniffer fails, default to comma
5. `pd.read_csv(filepath, encoding=encoding, sep=delimiter, on_bad_lines='skip')`
6. If header detection is ambiguous (first row looks like data), try `header=None`

**Detailed behavior for Excel parsing:**
1. `pd.ExcelFile(filepath, engine='openpyxl')`
2. Get sheet names
3. Parse each non-empty sheet
4. Return dict of {sheet_name: DataFrame}

**Detailed behavior for PDF parsing:**
1. `pdfplumber.open(filepath)`
2. For each page: extract text, detect and extract tables
3. Concatenate all text with page markers
4. Convert detected tables to DataFrames
5. Return (full_text, [table_DataFrames])

**Profile generation — THIS IS CRITICAL for LLM quality:**

The profile text is what the LLM uses to understand the data. A bad profile = bad answers. The profile must be:
- Concise (1500-3000 tokens max per file)
- Structured (consistent format the LLM can parse)
- Complete (enough info for the LLM to write correct pandas code)

Generate profile text in exactly this format:

```
=== FILE: sales_2024.csv ===
TYPE: CSV | ROWS: 1,200 | COLUMNS: 8
VARIABLE NAME: sales_2024

SCHEMA:
  date        → datetime  | nulls: 0 | range: 2024-01-01 to 2024-12-31
  customer    → text      | nulls: 3 | unique: 89 | top: ["Acme Corp": 145, "Beta Inc": 98, "Gamma Ltd": 67]
  product     → text      | nulls: 0 | unique: 12 | top: ["Widget A": 340, "Widget B": 289, "Service X": 201]
  revenue     → numeric   | nulls: 0 | min: 1,200 | max: 98,500 | mean: 15,432 | median: 12,100
  quantity    → numeric   | nulls: 5 | min: 1 | max: 500 | mean: 45 | median: 32
  region      → text      | nulls: 0 | unique: 4 | values: ["North", "South", "East", "West"]
  channel     → text      | nulls: 12 | unique: 3 | values: ["Online", "Store", "Partner"]
  margin_pct  → numeric   | nulls: 0 | min: 5.2 | max: 72.1 | mean: 34.5 | median: 33.8

SAMPLE (first 3 rows):
  date        | customer   | product   | revenue | quantity | region | channel | margin_pct
  2024-01-03  | Acme Corp  | Widget A  | 15,400  | 50       | North  | Online  | 35.2
  2024-01-05  | Beta Inc   | Service X | 8,900   | 12       | South  | Store   | 41.8
  2024-01-07  | Gamma Ltd  | Widget B  | 22,100  | 75       | East   | Partner | 28.9

DATA HEALTH: Score 94/100
  ⚠ 5 null values in 'quantity' column
  ⚠ 12 null values in 'channel' column
  ℹ 3 null values in 'customer' column
```

**Test:** Create sample CSV, Excel, and PDF files. Run ingestion on each. Print profiles. Verify accuracy manually.

---

### STEP 3: Sandbox (`engine/sandbox.py`)

Build the code execution sandbox BEFORE the brain engine, because you need to test it independently.

**CRITICAL SECURITY RULES — enforce all of these:**

```python
# Blocked imports (check via AST analysis before exec)
BLOCKED_IMPORTS = {
    'os', 'sys', 'subprocess', 'shutil', 'pathlib', 
    'socket', 'http', 'urllib', 'requests', 'ftplib',
    'smtplib', 'telnetlib', 'xmlrpc', 'pickle', 'shelve',
    'ctypes', 'multiprocessing', 'threading',  # threading OK for internal timeout only
    'signal', 'resource', 'importlib', 'code', 'codeop',
    'compileall', 'py_compile'
}

# Blocked builtins (remove from __builtins__ dict)
BLOCKED_BUILTINS = {
    '__import__', 'eval', 'exec', 'compile', 
    'open', 'input', 'breakpoint',
    'globals', 'locals', 'vars', 'dir',
    'exit', 'quit', 'help',
    'memoryview', 'bytearray'  # prevent raw memory access
}

# Blocked AST patterns
BLOCKED_PATTERNS = [
    'os.system', 'os.popen', 'subprocess.run', 'subprocess.call',
    'subprocess.Popen', 'shutil.rmtree', 'pathlib.Path',
    '__class__', '__bases__', '__subclasses__', '__globals__',
    '__builtins__', '__import__'
]
```

**Code validation flow:**
1. Parse code with `ast.parse()` — catch SyntaxError
2. Walk AST tree checking for:
   - Import nodes: reject if module in BLOCKED_IMPORTS
   - Attribute access: reject if matches BLOCKED_PATTERNS
   - Name nodes: reject if in BLOCKED_BUILTINS
3. If validation passes, execute with restricted globals

**Execution flow:**
1. Build restricted globals dict with allowed modules + user DataFrames
2. Create StringIO for stdout capture
3. Redirect sys.stdout to StringIO
4. Start daemon thread running `exec(code, restricted_globals)`
5. Join thread with timeout
6. Restore sys.stdout
7. Check for matplotlib figures saved to chart_dir
8. Check if any DataFrames were modified (compare hashes before/after)
9. Return ExecutionResult

**Chart handling in sandbox:**
- Pre-set `CHART_PATH` variable in globals pointing to `charts/chart_{uuid}.png`
- matplotlib backend must be set to 'Agg' (non-interactive) via `matplotlib.use('Agg')` at import time
- After execution, check if CHART_PATH file exists → if yes, set chart_path in result

**Test cases (write ALL of these):**
```python
# Should succeed:
- "print(df.shape)"
- "print(df['revenue'].mean())"  
- "df.groupby('month')['revenue'].sum()"
- matplotlib chart code that saves to CHART_PATH
- "df = df.drop_duplicates()" (should capture modified df)

# Should fail safely:
- "import os; os.system('rm -rf /')"
- "import subprocess; subprocess.run(['ls'])"
- "open('/etc/passwd').read()"
- "eval('__import__(\"os\").system(\"whoami\")')"
- "__import__('os').listdir('/')"
- Infinite loop (should timeout)
- "import requests; requests.get('http://evil.com')"
```

---

### STEP 4: LLM Backends (`engine/backends/`)

Build both backends so you can test with either.

**Ollama backend (`ollama.py`):**
- Use `requests` library for HTTP calls
- Streaming: `requests.post(url, json=body, stream=True)` + iterate over `response.iter_lines()`
- Each line is JSON: `{"message": {"content": "chunk"}, "done": false}`
- Parse and yield content until done=true
- Health check: GET to `{host}/api/tags`, check for 200 status

**Important Ollama API details for Gemma4:**
- Endpoint: POST `{host}/api/chat`
- Model: "gemma4:e4b"
- Options: `{"temperature": 0.3, "top_p": 0.95, "top_k": 64, "num_ctx": 128000, "num_predict": 8192}`
- Gemma4 supports native system role (unlike some older models)
- For thinking mode: include `<|think|>` at start of system prompt (OPTIONAL — test with and without)
- Recommended: DISABLE thinking for data analysis (faster, more direct answers). Enable only for complex reasoning.

**Cloud API backend (`cloud_api.py`):**
- Gemini: POST to `https://generativelanguage.googleapis.com/v1beta/models/{model}:streamGenerateContent?key={api_key}`
  - Convert messages to Gemini format: `{"contents": [{"role": "user"/"model", "parts": [{"text": "..."}]}]}`
- Groq: POST to `https://api.groq.com/openai/v1/chat/completions` (OpenAI-compatible)
  - Standard messages format, `stream: true`, parse SSE lines

**Test:** Send a simple message to both backends. Verify streaming works. Verify health check works.

---

### STEP 5: State Manager (`engine/state.py`)

Centralized state. Simple but important to get right.

**DataFrame naming rules:**
```python
def sanitize_name(filename: str, sheet: str = None) -> str:
    """
    Convert filename to valid Python variable name.
    
    "Sales Report 2024.csv" → "sales_report_2024"
    "Q4 Expenses.xlsx" (sheet "January") → "q4_expenses_january"
    "my-data (1).csv" → "my_data_1"
    
    Rules:
    1. Remove file extension
    2. Lowercase
    3. Replace spaces, hyphens, parentheses with underscores
    4. Remove all non-alphanumeric/underscore characters
    5. Collapse multiple underscores
    6. Prepend 'df_' if starts with digit
    7. If sheet name provided, append _{sheet_name}
    8. If name already exists, append _{n}
    """
```

**Test:** Upload multiple files with weird names. Verify all get valid, unique Python variable names.

---

### STEP 6: Brain Engine (`engine/brain.py`)

This is the most complex component. Build it methodically.

**The core chat() method flow — implement EXACTLY this:**

```python
def chat(self, user_message: str) -> Generator[dict, None, None]:
    # 1. Add user message to state
    self.state.add_chat_message("user", user_message)
    
    # 2. Build messages array for LLM
    messages = self._build_prompt(user_message)
    
    # 3. Stream response from LLM
    full_response = ""
    for chunk in self.backend.chat_stream(messages):
        full_response += chunk
        yield {"type": "text", "content": chunk}
    
    # 4. Check for code blocks in response
    parsed = self._parse_response(full_response)
    
    if parsed.code_blocks:
        # 5a. Execute code
        for attempt in range(self.max_retries):
            code = parsed.code_blocks[0]  # Take first code block
            
            result = self.sandbox.execute(
                code=code,
                dataframes=self.state.dataframes,
                chart_id=f"chart_{int(time.time())}_{attempt}"
            )
            
            if result.success:
                # 5b. Handle chart if generated
                if result.chart_path:
                    yield {"type": "chart", "chart_id": os.path.basename(result.chart_path)}
                
                # 5c. Handle data modification (cleaning)
                if result.modified_dataframes:
                    for name, new_df in result.modified_dataframes.items():
                        self.state.update_dataframe(name, new_df)
                    yield {"type": "cleaning", "report": self._build_cleaning_report(result)}
                
                # 5d. Get LLM to explain the result
                explanation_messages = self._build_explanation_prompt(
                    user_message, code, result.output
                )
                for chunk in self.backend.chat_stream(explanation_messages, temperature=0.7):
                    yield {"type": "text", "content": chunk}
                
                break  # Success, stop retrying
            
            else:
                # 5e. Retry with error context
                if attempt < self.max_retries - 1:
                    yield {"type": "retry", "attempt": attempt + 2}
                    messages = self._build_retry_prompt(
                        user_message, code, result.error
                    )
                    full_response = ""
                    for chunk in self.backend.chat_stream(messages):
                        full_response += chunk
                    parsed = self._parse_response(full_response)
                    if not parsed.code_blocks:
                        # LLM gave up on code, just use text response
                        yield {"type": "text", "content": full_response}
                        break
                else:
                    # All retries failed
                    yield {"type": "text", "content": 
                        "I wasn't able to compute that precisely. "
                        "Based on what I can see in the data profiles: "}
                    # Fall back to conversational answer
                    fallback = self._build_fallback_prompt(user_message)
                    for chunk in self.backend.chat_stream(fallback, temperature=0.7):
                        yield {"type": "text", "content": chunk}
    
    # 6. Save assistant response to history
    self.state.add_chat_message("assistant", full_response)
    
    # 7. Auto-save session
    self.session.save(self.state)
    
    # 8. Signal done
    yield {"type": "done"}
```

**Code block extraction regex:**
```python
import re
CODE_PATTERN = re.compile(r'```python\s*\n(.*?)```', re.DOTALL)

def _extract_code_blocks(self, text: str) -> list[str]:
    return CODE_PATTERN.findall(text)
```

**Context budget management:**
```python
def _build_prompt(self, user_message: str) -> list[dict]:
    TOTAL_BUDGET = 128000  # Gemma4 E4B context window
    RESPONSE_RESERVE = 8192  # Max tokens for response
    CODE_RESERVE = 5000  # Reserve for code execution context
    
    available = TOTAL_BUDGET - RESPONSE_RESERVE - CODE_RESERVE
    
    # System prompt + profiles (always included)
    system_content = self._build_system_prompt()
    system_tokens = self._estimate_tokens(system_content)
    available -= system_tokens
    
    # Current message (always included)
    current_tokens = self._estimate_tokens(user_message)
    available -= current_tokens
    
    # Fill remaining with history (newest first)
    history = self.state.get_recent_history(max_tokens=available)
    
    messages = [{"role": "system", "content": system_content}]
    messages.extend(history)
    messages.append({"role": "user", "content": user_message})
    
    return messages
```

**Test:** Send test questions with sample data loaded. Verify:
- Simple question → direct answer (no code)
- Data question → code generated → executed → explained
- Chart request → code generated → chart saved → chart event yielded
- Bad code → retry → success on retry
- All retries fail → graceful fallback

---

### STEP 7: Session Manager (`engine/session.py`)

Simple JSON persistence. Build after all other engine components.

Key rule: NEVER serialize DataFrames. Only save file paths + metadata. Rebuild DataFrames from uploaded files on load. This keeps session files small (<100KB) and avoids pickle security issues.

**Test:** Upload files → chat → save session → restart app → verify session restores correctly.

---

### STEP 8: Flask Application (`app.py`)

Wire everything together. All routes defined in one file.

**Key implementation details:**

```python
# SSE streaming for /chat/stream
@app.route('/chat/stream')
def chat_stream():
    message = request.args.get('message', '')
    if not message:
        return jsonify({"error": "No message provided"}), 400
    
    def generate():
        try:
            for event in brain.chat(message):
                yield f"data: {json.dumps(event)}\n\n"
        except Exception as e:
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"
    
    return Response(
        stream_with_context(generate()),
        mimetype='text/event-stream',
        headers={
            'Cache-Control': 'no-cache',
            'X-Accel-Buffering': 'no'  # Disable nginx buffering
        }
    )

# File upload
@app.route('/upload', methods=['POST'])
def upload():
    if 'file' not in request.files:
        return jsonify({"success": False, "error": "No file provided"}), 400
    
    file = request.files['file']
    # Save to uploads/
    # Run ingestion
    # Add to state
    # Return profile JSON

# File download
@app.route('/download/<name>')
def download(name):
    format = request.args.get('format', 'csv')
    df = state.dataframes.get(name)
    if df is None:
        return jsonify({"error": "File not found"}), 404
    
    # Convert to CSV/XLSX
    # Return as file download with proper headers

# Chart serving
@app.route('/chart/<chart_id>')
def serve_chart(chart_id):
    # Serve from charts/ directory
    # Validate chart_id to prevent path traversal
    safe_id = secure_filename(chart_id)
    return send_from_directory('charts', safe_id)

# Startup
if __name__ == '__main__':
    # Create directories if needed
    os.makedirs('uploads', exist_ok=True)
    os.makedirs('charts', exist_ok=True)
    os.makedirs('session', exist_ok=True)
    
    # Initialize components
    config = load_config()
    backend = create_backend(config)
    state = StateManager()
    sandbox = Sandbox(timeout=config['sandbox']['timeout_seconds'])
    session = SessionManager(config['session']['dir'])
    brain = BrainEngine(backend, state, sandbox, session)
    
    # Try to restore session
    session.load(state, ingestion_engine)
    
    # Health check
    if not backend.health_check():
        print("⚠ WARNING: LLM backend not available.")
        print("  For Ollama: run 'ollama serve' in another terminal")
    
    app.run(
        host=config['app']['host'],
        port=config['app']['port'],
        debug=config['app']['debug']
    )
```

**Test:** Start the server. Upload a file via curl. Send a chat message via curl. Verify SSE streaming works.

---

### STEP 9: Frontend (`static/index.html`, `style.css`, `app.js`)

Build the UI LAST, after the backend is fully tested.

**Design rules:**
- Clean, professional, minimal
- White/light background
- Deep blue (#1E40AF) primary accent
- System font stack (no Google Fonts dependency for offline use)
- No CSS framework (no Tailwind, no Bootstrap)
- Responsive but desktop-first (mobile is nice-to-have for V1)

**JavaScript rules:**
- Vanilla JS only. No jQuery, No React, No Vue.
- Use `fetch()` for API calls
- Use `EventSource` for SSE
- Use `template literals` for HTML generation
- Use `classList` for show/hide logic
- Maximum one JS file (`app.js`)

**File upload with drag-and-drop:**
```javascript
const dropZone = document.getElementById('drop-zone');
dropZone.addEventListener('dragover', (e) => { e.preventDefault(); dropZone.classList.add('drag-over'); });
dropZone.addEventListener('dragleave', () => { dropZone.classList.remove('drag-over'); });
dropZone.addEventListener('drop', (e) => {
    e.preventDefault();
    dropZone.classList.remove('drag-over');
    [...e.dataTransfer.files].forEach(uploadFile);
});
```

**SSE chat connection:**
```javascript
function sendMessage(text) {
    if (!text.trim()) return;
    renderUserMessage(text);
    disableInput();
    
    const msgBubble = createAssistantBubble();
    const es = new EventSource(`/chat/stream?message=${encodeURIComponent(text)}`);
    
    es.onmessage = (e) => {
        const data = JSON.parse(e.data);
        switch(data.type) {
            case 'text':
                appendText(msgBubble, data.content);
                scrollToBottom();
                break;
            case 'chart':
                appendChart(msgBubble, data.chart_id);
                break;
            case 'code':
                appendCode(msgBubble, data.content);
                break;
            case 'cleaning':
                appendCleaningReport(msgBubble, data.report);
                break;
            case 'error':
                appendError(msgBubble, data.content);
                break;
            case 'done':
                es.close();
                enableInput();
                break;
        }
    };
    
    es.onerror = () => {
        es.close();
        appendError(msgBubble, 'Connection lost. Please try again.');
        enableInput();
    };
}
```

**Test:** Open browser to localhost:5000. Upload file via drag-and-drop. Ask a question. Verify streaming, charts, and cleaning all work end-to-end.

---

## SYSTEM PROMPTS — EXACT TEXT

### Main System Prompt (`prompts/system.md`)

```
You are a private data analyst running entirely on the user's machine. No data is sent externally. You help business owners understand their data through conversation.

RULES:
1. For ANY question about data values, trends, comparisons, or calculations — you MUST write Python pandas code. NEVER estimate or guess numbers.
2. Wrap code in ```python blocks. The backend will execute it and give you the result.
3. Available libraries in your code: pandas (as pd), numpy (as np), matplotlib.pyplot (as plt), datetime, math, statistics, json, re
4. User DataFrames are pre-loaded as variables. Use the exact names listed below.
5. After code executes, you'll receive the output. Explain it clearly to the user.
6. Use specific numbers: "₹12,43,500 in September" not "revenue was high"
7. Use percentages for comparisons: "up 23% from August"
8. If you can't answer from the available data, say so honestly.
9. The user is a business owner, not a programmer. Never show raw DataFrames unless asked.
10. For charts: use matplotlib, set figsize=(10,6), save to CHART_PATH variable, always add title and labels.

CURRENTLY LOADED FILES:
{file_profiles}

AVAILABLE DATAFRAMES:
{dataframe_names}
```

---

## EDGE CASES TO HANDLE

1. **Empty file uploaded** → Profile shows "0 rows" + warning, LLM told "this file is empty"
2. **File with only headers, no data** → Same as empty, but show column names
3. **CSV with no header row** → Auto-detect, generate column names: col_0, col_1, ...
4. **Excel with merged cells** → Unmerge and forward-fill
5. **PDF with no extractable text** → Message: "This appears to be a scanned PDF. Consider OCR."
6. **User asks question with no files loaded** → "Please upload a file first so I can help you analyze it."
7. **User asks non-data question** → Answer conversationally (the LLM knows when code isn't needed)
8. **User asks about a file by wrong name** → Suggest closest match from loaded files
9. **Code references non-existent column** → Sandbox catches error, retry with column list
10. **Chart code runs but produces empty/broken chart** → Detect via file size (<1KB = probably empty), retry
11. **User uploads same filename twice** → Replace previous version, warn user
12. **Unicode/Hindi text in data** → pandas handles this; ensure profile displays correctly
13. **Very wide files (100+ columns)** → Profile truncates to first 20 columns + note "and 80 more"
14. **Date columns stored as strings** → Profile detects this and flags in health report
15. **Mixed numeric + text in same column** → Flag as critical health issue, suggest cleaning

---

## TESTING CHECKLIST

Before considering any component "done", verify:

- [ ] CSV upload with comma delimiter
- [ ] CSV upload with tab delimiter  
- [ ] CSV upload with semicolon delimiter
- [ ] CSV with UTF-8 encoding
- [ ] CSV with Latin-1 encoding
- [ ] Excel single sheet
- [ ] Excel multi-sheet (verify all sheets loaded)
- [ ] PDF with text
- [ ] PDF with tables
- [ ] File profile accuracy (manually verify stats)
- [ ] Data health detection (duplicates, nulls, mixed types)
- [ ] Sandbox blocks os import
- [ ] Sandbox blocks subprocess
- [ ] Sandbox blocks eval/exec
- [ ] Sandbox blocks file open
- [ ] Sandbox allows pandas operations
- [ ] Sandbox allows matplotlib chart generation
- [ ] Sandbox enforces timeout on infinite loop
- [ ] Ollama backend streaming works
- [ ] Ollama health check detects when Ollama is down
- [ ] Simple data question → code → answer
- [ ] Chart request → code → PNG → displayed
- [ ] Data cleaning → code → modified DataFrame → report
- [ ] Code error → retry → success
- [ ] All retries fail → graceful fallback message
- [ ] Session save after each interaction
- [ ] Session restore on restart
- [ ] Session clear works
- [ ] Download cleaned file as CSV
- [ ] Download cleaned file as XLSX
- [ ] Drag-and-drop upload in browser
- [ ] Streaming text display in chat
- [ ] Chart display inline in chat
- [ ] Multiple files loaded simultaneously
- [ ] Cross-file question (referencing two files)
- [ ] "New Session" button resets everything
- [ ] Ollama not running → clear error message

---

## FINAL NOTES FOR THE AI AGENT

1. **DO NOT add extra dependencies.** The requirements.txt has exactly 9 packages. If you think you need something else, you probably don't.

2. **DO NOT use React, Vue, Svelte, or any frontend framework.** Vanilla HTML/CSS/JS only. One file each.

3. **DO NOT use Docker, docker-compose, or containerization for the app itself.** (Ollama may run in Docker separately, but the app is just `python app.py`.)

4. **DO NOT create a database.** All state is in-memory (DataFrames) + JSON files (session). No SQLite, no PostgreSQL, no Redis.

5. **DO NOT over-engineer.** This is a focused tool with a clear purpose. Every line of code should serve one of the user stories in the PRD.

6. **DO test each component independently before integration.** The build order in this document is deliberate.

7. **The system prompt quality determines 80% of the user experience.** Spend time getting it right. Test with real data and real questions.

8. **When in doubt, refer to the PRD (01_PRD.md) for product decisions and the Tech Spec (02_TECH_SPEC.md) for implementation details.**
