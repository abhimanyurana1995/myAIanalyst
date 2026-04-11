# MyAnalyst — Local AI Data Analyst

A locally-hosted, browser-based AI data analyst. Upload CSV, Excel, or PDF files and chat with an AI that performs real computations on your data. Everything runs on your machine — no data leaves your computer.

---

## Quick Start

### Prerequisites
- Python 3.10 or higher
- [Ollama](https://ollama.ai) installed and running

### 1. Install dependencies
```bash
pip install -r requirements.txt
```

### 2. Pull the AI model
```bash
ollama pull gemma4:e4b
```

### 3. Start Ollama (if not running)
```bash
ollama serve
```

### 4. Run the app
```bash
python app.py
```

The browser will open automatically at `http://localhost:5000`.

---

## Demo Mode (Cloud API)

To run without Ollama, using Gemini or Groq:

```bash
# Gemini
export LLM_BACKEND=api
export GEMINI_API_KEY=your_api_key_here
python app.py

# Groq
export LLM_BACKEND=api
export API_PROVIDER=groq
export GROQ_API_KEY=your_api_key_here
python app.py
```

---

## Configuration

Edit `config.yaml` to customise the app. Key settings:

| Setting | Default | Description |
|---|---|---|
| `app.name` | `MyAnalyst` | App name shown in the UI |
| `app.port` | `5000` | Port to run on |
| `llm.backend` | `ollama` | `ollama` (local) or `api` (cloud) |
| `llm.ollama.model` | `gemma4:e4b` | Ollama model to use |
| `files.max_size_mb` | `100` | Max upload size in MB |

---

## Supported File Types

| Type | Notes |
|---|---|
| CSV | Auto-detects delimiter (`,`, `\t`, `;`, `\|`) and encoding |
| Excel (`.xlsx`, `.xls`) | Multi-sheet support |
| PDF | Text and table extraction |

---

## Features

- **Natural language queries** — Ask questions in plain English
- **Real computation** — Answers come from pandas executing code against your data, not AI guessing
- **Auto data profiling** — Upload a file and instantly see row counts, column types, min/max/mean, sample data
- **Health checks** — Automatic detection of duplicates, missing values, mixed types, whitespace issues
- **Charts** — Ask for a chart and get matplotlib visualisations inline
- **Data cleaning** — Ask to "remove duplicates" or "fill missing values" and it's done
- **Download cleaned data** — Export processed data as CSV or Excel
- **Session persistence** — Close the browser and come back — your files and conversation are still there
- **Confidence indicators** — Every answer shows whether it was computed from real data or estimated

---

## Security

- Runs on `localhost` only — not exposed to the network by default
- Code execution sandbox with AST-level security validation
- Blocked: `os`, `sys`, `subprocess`, `socket`, all network libraries
- No telemetry, no analytics, no external calls
- Original uploaded files are never modified

---

## Hardware Requirements

| | Minimum | Recommended |
|---|---|---|
| RAM | 16 GB | 24 GB |
| GPU | None (CPU-only works) | 8 GB VRAM |
| Disk | 10 GB free | 20 GB free |
| Python | 3.10+ | 3.11+ |
| Ollama | 0.6+ | latest |

---

## Troubleshooting

**"Ollama is not running"**
→ Run `ollama serve` in a terminal and try again.

**"Model not found"**
→ Run `ollama pull gemma4:e4b` to download the model.

**File upload fails with encoding error**
→ The app auto-detects encoding. If it still fails, try saving the file as UTF-8 from Excel.

**Charts not showing**
→ Make sure `charts/` directory exists (created automatically on startup).

**Session not restoring**
→ Check that `uploads/` and `session/` directories exist and are readable.

---

## Project Structure

```
datasense/
├── app.py              # Flask application, all routes
├── config.py           # Configuration loader
├── config.yaml         # Default configuration
├── requirements.txt    # Dependencies (9 packages)
├── engine/
│   ├── ingestion.py    # File parsing + profiling
│   ├── brain.py        # LLM orchestration
│   ├── sandbox.py      # Secure code execution
│   ├── session.py      # Session persistence
│   ├── state.py        # In-memory state
│   └── backends/
│       ├── ollama.py   # Ollama client
│       └── cloud_api.py # Gemini/Groq client
├── static/
│   ├── index.html      # Single-page app
│   ├── style.css       # Styles
│   └── app.js          # Frontend logic
└── prompts/
    ├── system.md       # Main system prompt
    └── ...
```
