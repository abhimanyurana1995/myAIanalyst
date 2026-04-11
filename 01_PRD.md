# PRODUCT REQUIREMENTS DOCUMENT (PRD)
## Project Codename: [UNNAMED — Abhimanyu will name it]
### Local AI Data Analyst for Small Businesses

**Author:** Abhimanyu Rana  
**Version:** 1.0  
**Date:** April 11, 2026  
**Status:** Pre-Development  

---

## 1. EXECUTIVE SUMMARY

### 1.1 What Are We Building?

A locally-hosted, browser-based AI data analyst that allows small business owners, freelancers, and professionals to upload their data files (CSV, Excel, PDF), have a natural language conversation about their data, receive real analysis backed by actual computations, get auto-generated visualizations, and download cleaned versions of their data — all without any data ever leaving their machine.

### 1.2 Why Does This Need to Exist?

The current landscape forces a false choice:

- **Option A: ChatGPT/Gemini** — Upload your sensitive business data to a cloud AI. Fast, capable, but your revenue numbers, client lists, and financial data now sit on someone else's server. Compliance risk. Privacy risk. Ongoing subscription cost ($20-240/month).
- **Option B: Hire an analyst** — Expensive (₹5-25L/year or $50-150/hr freelance). Scheduling overhead. Communication overhead. Still need to share sensitive data with a human.
- **Option C: Learn pandas/SQL yourself** — Months of learning. Most business owners don't have time or interest.
- **Option D: This tool** — Drop your files. Ask questions in English. Get real answers computed from your actual data. Private. Free after setup. No technical knowledge required.

### 1.3 Who Is This For?

**Primary users (the people who will use this daily):**

| User Persona | Description | Pain Point | What They'd Pay |
|---|---|---|---|
| **Small Agency Owner** | 5-20 person team, runs on spreadsheets | Can't afford a data analyst, doesn't trust cloud AI with client data | ₹5,000-15,000/month for a managed setup |
| **Freelance Consultant** | Solo operator, multiple client projects | Needs quick data insights across multiple client datasets without co-mingling data | ₹2,000-5,000/month or one-time setup fee |
| **CA/Tax Practitioner** | Handles sensitive financial data for clients | Cannot legally upload client financials to cloud AI | ₹10,000-25,000/month — compliance is non-negotiable |
| **HR Manager** | Manages recruitment pipelines, employee data | Employee salary data + candidate PII cannot go to ChatGPT | Setup fee + training |
| **Small E-commerce Seller** | Sells on Amazon/Flipkart/Shopify, downloads CSV reports | Needs to understand sales trends but doesn't know Excel formulas | ₹3,000-8,000/month |

**Secondary users (the people who will see this and want it built for them):**

- Startup founders who want data dashboards without hiring
- Ops managers at mid-size companies who need quick ad-hoc analysis
- Anyone who currently emails spreadsheets to someone else for analysis

### 1.4 Business Model (How This Makes Money)

This is not a SaaS product with monthly subscriptions. This is a **consulting + setup service:**

| Revenue Stream | Price Range | Frequency |
|---|---|---|
| **Setup & Installation** — Install Ollama + tool on client's machine, configure for their data types | ₹10,000-25,000 | One-time |
| **Customization** — Custom system prompts for their industry, pre-built analysis templates, branded UI | ₹15,000-50,000 | One-time |
| **Training** — Teach the client and their team how to use it effectively | ₹5,000-10,000 | One-time |
| **Maintenance Retainer** — Monthly check-ins, model updates, feature additions | ₹3,000-8,000/month | Recurring |
| **Enterprise Setup** — Multi-user, network-accessible deployment for teams | ₹50,000-2,00,000 | One-time + retainer |

**The free demo hosted online serves as the sales funnel.** People try it → see the value → ask "can you set this up for my business?" → Abhimanyu charges for the setup, customization, and training.

---

## 2. PRODUCT VISION

### 2.1 The One-Line Vision

"Your private data analyst that runs on your laptop — no cloud, no subscription, no compromises."

### 2.2 Design Philosophy

1. **Privacy is not a feature, it's the foundation.** Every architectural decision defaults to local-first. No telemetry. No analytics. No "phone home." The tool works with WiFi turned off after initial setup.

2. **Real computation, not LLM guessing.** When a user asks "what was my revenue in March?" — the answer comes from pandas executing code against real data, not from the LLM estimating based on what it saw in context. The LLM is the translator (natural language ↔ code), not the calculator.

3. **Honest about limitations.** If the tool can't answer a question, it says so. If the data is too messy to analyze, it explains what's wrong and offers to clean it. No hallucinated numbers. Ever.

4. **Beautiful by default.** The UI should feel professional. Not like a developer's side project. Not like Streamlit's default gray. A business owner should feel comfortable showing this to their accountant.

5. **Two deployment modes, one codebase.** Local mode (Ollama) for production/clients. API mode (Gemini/Groq) for the public demo. The user experience is identical. The backend swaps one function call.

### 2.3 What This Is NOT

- This is NOT a replacement for Excel or Google Sheets (users still need those for data entry and storage)
- This is NOT a BI tool like Power BI or Tableau (no persistent dashboards, no scheduled reports — yet)
- This is NOT a database (it doesn't store data long-term, it analyzes files you give it)
- This is NOT a coding tool (the user never sees or writes code)
- This is NOT trying to compete with ChatGPT (different value proposition — privacy + real computation)

---

## 3. USER STORIES

### 3.1 Core User Stories (Must Have — V1)

**US-01: File Upload**
> As a business owner, I want to drag and drop my CSV, Excel, or PDF files into the tool so that the AI can analyze them.

Acceptance Criteria:
- Supports .csv, .xlsx, .xls, .pdf file types
- Multiple files can be uploaded simultaneously
- Each uploaded file shows a card with: filename, file type icon, row count (for tabular), page count (for PDF), column names (for tabular), and a "health status" indicator
- Files are stored locally in an `uploads/` directory
- Maximum file size: 100MB per file (pandas handles this fine on 24GB RAM)
- Upload progress indicator for large files
- Error handling for corrupt/unreadable files with clear user-facing message

**US-02: Natural Language Chat**
> As a business owner, I want to ask questions about my data in plain English and get accurate answers.

Acceptance Criteria:
- Chat interface with message input and response area
- Responses stream in real-time (token by token) — not a loading spinner followed by a wall of text
- Questions about data trigger pandas code generation + execution behind the scenes
- User never sees the code unless they explicitly ask to
- Conversational context maintained across messages (the AI remembers what was discussed)
- Examples of supported questions:
  - "What was my highest revenue month?"
  - "Compare Q3 and Q4 expenses"
  - "Which customers haven't ordered in the last 90 days?"
  - "What percentage of my sales come from Delhi?"
  - "Is there a correlation between ad spend and revenue?"

**US-03: Data Profiling on Upload**
> As a user, I want to see an automatic summary of my data as soon as I upload it, so I understand what I'm working with before asking questions.

Acceptance Criteria:
- Automatic profiling runs on upload completion
- Profile includes:
  - Row count, column count
  - Column names and inferred types (numeric, text, date, boolean)
  - For numeric columns: min, max, mean, median, std dev, null count, zero count
  - For text columns: unique count, top 5 values with frequencies, null count, average length
  - For date columns: earliest, latest, date range, gaps detected
  - Duplicate row count
  - Overall data quality score (percentage of non-null, non-duplicate cells)
- Profile displayed in the file card (expandable)
- Profile used as context for all subsequent LLM interactions

**US-04: Chart Generation**
> As a business owner, I want to say "show me a chart of monthly revenue" and see an actual chart appear in the conversation.

Acceptance Criteria:
- LLM generates matplotlib code for chart creation
- Backend executes chart code in sandbox
- Chart saved as PNG and displayed inline in chat
- Chart types supported: bar, line, pie, scatter, histogram, box plot
- Charts include proper labels, titles, and legends
- Charts use a consistent, professional color palette
- User can ask for chart modifications ("make it a bar chart instead", "add a trend line")
- Charts are downloadable as PNG

**US-05: Data Cleaning**
> As a user, I want the AI to identify and fix data quality issues in my files so I can work with clean data.

Acceptance Criteria:
- On upload, data health issues are automatically flagged:
  - Duplicate rows (count and percentage)
  - Null/missing values per column
  - Inconsistent date formats
  - Mixed data types in single columns
  - Leading/trailing whitespace in text
  - Inconsistent category names (case differences, typos)
- User can ask "clean this data" for automatic cleaning
- User can ask for specific cleaning: "remove duplicates", "fix the dates", "fill missing values with 0"
- Every cleaning action is reported: "Removed 47 duplicates, standardized 12 date formats, filled 23 null values"
- Cleaned data replaces the in-memory DataFrame
- Original file is NEVER modified on disk
- User can download the cleaned version as CSV or Excel

**US-06: File Download (Cleaned/Processed)**
> As a user, I want to download my cleaned or processed data as a new file.

Acceptance Criteria:
- Download button appears after any data modification
- Supported export formats: CSV, XLSX
- Downloaded file reflects all cleaning and transformations applied
- Filename convention: `{original_name}_cleaned.{ext}`
- Download works via browser's native download mechanism

**US-07: Session Persistence**
> As a user, I want to close the browser and come back later with my files and conversation still intact.

Acceptance Criteria:
- Chat history saved to local JSON file after each message
- File metadata saved (but raw DataFrames reloaded from uploaded files on restart)
- On app restart, previous session auto-loads
- User can explicitly "clear session" to start fresh
- Session data stored in `session/` directory alongside the app

### 3.2 Important User Stories (Should Have — V1.1)

**US-08: Multi-File Analysis**
> As a user, I want to ask questions that span multiple uploaded files.

Acceptance Criteria:
- LLM can reference any uploaded file by name
- Cross-file operations supported: "compare sales.csv with expenses.xlsx"
- LLM generates code that loads multiple DataFrames and joins/compares them
- User can specify join keys if needed ("match them on the 'date' column")

**US-09: Interactive Charts (Plotly)**
> As a user, I want interactive charts I can hover over, zoom into, and filter.

Acceptance Criteria:
- LLM generates Plotly JSON specs for interactive visualizations
- Frontend renders Plotly charts with hover tooltips, zoom, and pan
- Fallback to matplotlib PNG if Plotly rendering fails

**US-10: Export Analysis Report**
> As a user, I want to export the full conversation (including charts) as a PDF report.

Acceptance Criteria:
- "Export Report" button generates a PDF
- PDF includes all chat messages, charts, data summaries
- Professional formatting with the tool's branding
- Date and filename metadata in the report header

**US-11: Custom System Prompts (for consultants)**
> As a consultant setting this up for a client, I want to customize the AI's personality and default analysis patterns for a specific industry.

Acceptance Criteria:
- System prompt configurable via a settings file or UI
- Industry-specific templates available: retail, manufacturing, services, finance
- Custom prompt persists across sessions

### 3.3 Future User Stories (V2+)

**US-12:** Scheduled analysis — "Run this same analysis every Monday on the latest file in this folder"
**US-13:** Multi-user support — different users with separate sessions on the same machine
**US-14:** Database connectors — connect to PostgreSQL, MySQL, SQLite directly instead of files
**US-15:** Voice input — ask questions by speaking (Gemma4 supports audio input)
**US-16:** Image/screenshot analysis — upload a screenshot of a dashboard and ask questions about it (Gemma4 supports vision)
**US-17:** Webhook/API mode — other tools can send data and receive analysis programmatically

---

## 4. FUNCTIONAL REQUIREMENTS

### 4.1 File Ingestion

| Requirement | Details |
|---|---|
| FR-01 | Accept CSV files with any delimiter (auto-detect: comma, tab, semicolon, pipe) |
| FR-02 | Accept Excel files (.xlsx, .xls) with multi-sheet support — user selects sheet or "all sheets" |
| FR-03 | Accept PDF files — extract text and tables separately |
| FR-04 | Handle encoding detection (UTF-8, Latin-1, CP1252, etc.) — never crash on encoding errors |
| FR-05 | Handle files with headers and without headers (auto-detect, user-overridable) |
| FR-06 | Handle large files (>50MB) with progress reporting |
| FR-07 | Reject unsupported file types with clear error message |
| FR-08 | Generate file profile within 5 seconds for files under 10MB |
| FR-09 | Store raw uploaded files in `uploads/` directory |
| FR-10 | Maintain in-memory DataFrames accessible by filename throughout the session |

### 4.2 LLM Integration

| Requirement | Details |
|---|---|
| FR-11 | Connect to Ollama API at configurable host:port (default localhost:11434) |
| FR-12 | Connect to cloud API (Gemini/Groq) as alternative backend |
| FR-13 | Backend selection via environment variable: `LLM_BACKEND=ollama` or `LLM_BACKEND=api` |
| FR-14 | Stream responses using Server-Sent Events (SSE) |
| FR-15 | System prompt includes: role definition, available files and their profiles, rules for code generation, output formatting guidelines |
| FR-16 | Chat history maintained in memory and persisted to disk |
| FR-17 | Context window management: system prompt + file profiles + last N messages + current query must fit within 128K tokens |
| FR-18 | Automatic context pruning: if history exceeds limit, oldest messages are summarized and compressed |
| FR-19 | Temperature set to 0.3 for analytical queries, 0.7 for conversational responses |
| FR-20 | Timeout: 120 seconds maximum per LLM call, with graceful error message |

### 4.3 Code Generation & Execution

| Requirement | Details |
|---|---|
| FR-21 | LLM generates Python pandas code wrapped in markdown code blocks |
| FR-22 | Backend extracts code blocks from LLM response using regex pattern matching |
| FR-23 | Code executed in sandboxed environment with restricted globals |
| FR-24 | Sandbox allows: pandas, numpy, matplotlib, datetime, math, statistics, json, re |
| FR-25 | Sandbox blocks: os, sys, subprocess, shutil, pathlib write operations, network libraries, eval, exec, compile, __import__ |
| FR-26 | DataFrames passed into sandbox by reference (no file I/O inside sandbox) |
| FR-27 | Code execution timeout: 30 seconds maximum |
| FR-28 | On code error: error message sent back to LLM for self-correction, up to 3 retries |
| FR-29 | Execution result (stdout, return value, or error) captured and passed back to LLM |
| FR-30 | LLM then explains the result in natural language to the user |

### 4.4 Visualization

| Requirement | Details |
|---|---|
| FR-31 | matplotlib charts saved as PNG (300 DPI) in `charts/` directory |
| FR-32 | Chart files served via Flask static route |
| FR-33 | Charts displayed inline in chat as images |
| FR-34 | Consistent chart styling: white background, professional font (system default), consistent color palette |
| FR-35 | Chart color palette: defined in config, default is a colorblind-friendly palette |
| FR-36 | Charts include: title, axis labels, legend (when multiple series), grid lines (subtle) |
| FR-37 | Chart filenames: `chart_{timestamp}_{type}.png` |
| FR-38 | Charts downloadable via right-click or download button |

### 4.5 Data Cleaning

| Requirement | Details |
|---|---|
| FR-39 | Auto-detect data quality issues on upload (part of profiling) |
| FR-40 | Quality issues categorized by severity: Critical (>20% data affected), Warning (5-20%), Info (<5%) |
| FR-41 | Cleaning operations performed via pandas code generation (same sandbox) |
| FR-42 | Every cleaning operation logged with before/after counts |
| FR-43 | Cleaned DataFrame replaces original in memory |
| FR-44 | Original file on disk never modified |
| FR-45 | "Undo cleaning" restores previous DataFrame state (keep last 5 states in memory) |
| FR-46 | Download cleaned file as CSV (.csv) or Excel (.xlsx) |

### 4.6 Session Management

| Requirement | Details |
|---|---|
| FR-47 | Session auto-saves after each interaction |
| FR-48 | Session file: `session/session.json` containing chat history, file metadata, cleaning log |
| FR-49 | On app start: check for existing session, auto-load if found |
| FR-50 | "New Session" button clears all state and starts fresh |
| FR-51 | Session includes: timestamp, uploaded filenames, chat messages, cleaning actions performed |
| FR-52 | File metadata in session includes profiles but NOT raw data (DataFrames rebuilt from uploaded files on reload) |

---

## 5. NON-FUNCTIONAL REQUIREMENTS

### 5.1 Performance

| Requirement | Target |
|---|---|
| NFR-01: File upload processing | <5 seconds for files under 10MB |
| NFR-02: File profiling | <3 seconds for files under 50,000 rows |
| NFR-03: LLM response start | <3 seconds for first token (Ollama, warm model) |
| NFR-04: Code execution | <30 seconds for any single operation |
| NFR-05: Chart generation | <10 seconds including rendering |
| NFR-06: UI responsiveness | No frame drops during streaming |
| NFR-07: Memory usage | <4GB RAM for the application (excluding Ollama/model) |

### 5.2 Security

| Requirement | Details |
|---|---|
| NFR-08 | No network calls in local mode (after initial page load) |
| NFR-09 | Sandbox prevents all file system access outside designated directories |
| NFR-10 | No data logged, no telemetry, no analytics |
| NFR-11 | Flask runs on localhost only — not exposed to network by default |
| NFR-12 | Code sandbox prevents execution of arbitrary system commands |
| NFR-13 | Uploaded files accessible only through the application |

### 5.3 Compatibility

| Requirement | Details |
|---|---|
| NFR-14 | Runs on Windows 10/11, macOS 12+, Ubuntu 22.04+ |
| NFR-15 | Works in Chrome, Firefox, Edge, Safari (latest 2 versions) |
| NFR-16 | Python 3.10+ required |
| NFR-17 | Ollama 0.6+ required (for Gemma4 support) |
| NFR-18 | Works on machines with no GPU (CPU-only inference supported by Ollama) |
| NFR-19 | Minimum hardware: 16GB RAM, 10GB free disk space |
| NFR-20 | Recommended hardware: 24GB RAM, 8GB VRAM GPU, 20GB free disk space |

### 5.4 Reliability

| Requirement | Details |
|---|---|
| NFR-21 | Application recovers gracefully from Ollama connection failures |
| NFR-22 | Corrupt file upload doesn't crash the application |
| NFR-23 | LLM timeout doesn't lose conversation history |
| NFR-24 | Session file corruption triggers fresh start (not crash) |
| NFR-25 | All user-facing errors displayed as friendly messages, not stack traces |

---

## 6. UI/UX REQUIREMENTS

### 6.1 Layout

The interface is a single-page application with three zones:

**Zone 1: Top Bar (fixed)**
- Application name/logo (left)
- Loaded files indicator: "[3 files loaded | 14,200 total rows]" (center)
- Settings gear icon (right) — opens config panel
- "New Session" button (right)

**Zone 2: File Area (collapsible)**
- Drag-and-drop zone with visual feedback (border highlight on hover)
- Uploaded file cards displayed horizontally (scrollable if many files)
- Each card shows: file icon (CSV/Excel/PDF), filename (truncated), row × column count or page count, data health indicator (green/yellow/red dot), expand arrow for full profile
- "Upload Files" button as alternative to drag-and-drop

**Zone 3: Chat Area (main, fills remaining space)**
- Message history (scrollable)
- User messages: right-aligned, subtle background
- AI messages: left-aligned, clean typography
- Charts: displayed inline within AI messages
- Code blocks: hidden by default, expandable "Show code" toggle
- Streaming indicator: subtle typing animation during response
- Input area at bottom: text input + send button
- Suggested questions on empty state: "Try asking: 'What does my data look like?'"

### 6.2 Design Specifications

| Element | Specification |
|---|---|
| Background | White (#FFFFFF) or very light gray (#FAFAFA) |
| Primary accent | Deep blue (#1E40AF) — professional, trustworthy |
| Secondary accent | Emerald (#059669) — for positive indicators/charts |
| Warning | Amber (#D97706) — for data quality warnings |
| Error | Red (#DC2626) — for errors and critical issues |
| Text | Near-black (#111827) — high readability |
| Muted text | Gray (#6B7280) — for metadata, timestamps |
| Font | System font stack: -apple-system, BlinkMacSystemFont, 'Segoe UI', sans-serif |
| Font size (body) | 15px |
| Font size (file cards) | 13px |
| Font size (chat) | 15px |
| Border radius | 8px for cards, 12px for chat bubbles |
| Shadows | Subtle: 0 1px 3px rgba(0,0,0,0.1) |
| Animations | Fade-in for new messages, slide-up for file cards |

### 6.3 Responsive Behavior

- Desktop (>1024px): full three-zone layout as described
- Tablet (768-1024px): file area collapses to a single row of mini-cards
- Mobile (<768px): file area becomes a toggle panel, chat takes full screen
- Not a priority for V1, but don't make decisions that prevent it later

### 6.4 Empty States

- No files uploaded: Large drop zone with illustration + text "Drop your CSV, Excel, or PDF files here"
- Files uploaded, no chat: Suggested question cards ("What does my data look like?", "Are there any data quality issues?", "Show me a summary of key metrics")
- Error state: Friendly message + "Try again" button + specific guidance

### 6.5 Accessibility

- All interactive elements keyboard-accessible
- Sufficient color contrast (WCAG AA minimum)
- Screen reader labels on all buttons and inputs
- No information conveyed by color alone (icons + text alongside colored indicators)

---

## 7. DEPLOYMENT REQUIREMENTS

### 7.1 Local Mode (Production — Client Installations)

**Prerequisites:**
- Python 3.10+ installed
- Ollama installed with Gemma4 E4B model pulled
- 16GB RAM minimum (24GB recommended)

**Installation:**
```bash
git clone [repo-url]
cd analyst
pip install -r requirements.txt
python app.py
# Opens browser to localhost:5000
```

**Requirements.txt:**
```
flask>=3.0
pandas>=2.0
pdfplumber>=0.10
matplotlib>=3.8
requests>=2.31
openpyxl>=3.1
chardet>=5.0
```

No Docker required. No npm. No build step. `pip install` + `python app.py` = running.

### 7.2 Demo Mode (Public — Hosted Online)

**Infrastructure:**
- Railway, Render, or Oracle Cloud free tier VM
- Python runtime (same requirements.txt)
- No Ollama needed — uses Gemini API (free tier: 1,500 requests/day) or Groq API (free tier)

**Differences from local mode:**
- `LLM_BACKEND=api` environment variable
- API key stored in environment variable (not in code)
- File uploads stored in temp directory, auto-deleted after session
- Session timeout: 30 minutes of inactivity
- File size limit: 10MB (lower than local to manage server resources)
- Rate limiting: 20 queries per session

**Domain:**
- Custom domain: `analyst.abhimanyurana.com` or similar
- SSL certificate (auto via Railway/Render)

### 7.3 Configuration

All configuration via environment variables or `config.yaml`:

```yaml
# config.yaml
app:
  name: "[Project Name]"
  host: "127.0.0.1"
  port: 5000
  debug: false

llm:
  backend: "ollama"  # or "api"
  ollama:
    host: "http://localhost:11434"
    model: "gemma4:e4b"
    temperature_analytical: 0.3
    temperature_conversational: 0.7
    max_tokens: 8192
    context_window: 128000
  api:
    provider: "gemini"  # or "groq"
    model: "gemma-2-9b-it"
    api_key: "${GEMINI_API_KEY}"

files:
  max_size_mb: 100  # 10 for demo mode
  upload_dir: "uploads"
  chart_dir: "charts"
  allowed_types: ["csv", "xlsx", "xls", "pdf"]

session:
  dir: "session"
  auto_save: true
  timeout_minutes: 0  # 0 = no timeout (local), 30 for demo

sandbox:
  timeout_seconds: 30
  max_retries: 3

ui:
  theme: "light"
  chart_palette: ["#1E40AF", "#059669", "#D97706", "#DC2626", "#7C3AED", "#DB2777"]
```

---

## 8. SUCCESS METRICS

### 8.1 For the Demo (Marketing)

| Metric | Target (Month 1) |
|---|---|
| Demo URL visitors | 500+ |
| Unique sessions (someone actually uploads a file) | 100+ |
| Average questions per session | 5+ |
| LinkedIn post engagement on launch post | 1,000+ impressions, 50+ reactions |
| Inbound inquiries ("can you set this up for me?") | 3-5 |

### 8.2 For Client Installations (Revenue)

| Metric | Target (Month 1-3) |
|---|---|
| Paid installations | 2-3 |
| Average setup fee collected | ₹15,000-25,000 |
| Client retention (still using after 30 days) | 80%+ |
| Client referrals | 1+ per client |

### 8.3 For Abhimanyu's Career (The Real Goal)

| Metric | Target |
|---|---|
| Profile views from LinkedIn posts about this project | 50+ per post |
| Interview calls where this project is discussed | 3+ |
| Job offers where this project was a deciding factor | 1 (that's all you need) |

---

## 9. RISKS AND MITIGATIONS

| Risk | Severity | Mitigation |
|---|---|---|
| Gemma4 E4B generates incorrect pandas code | High | Sandbox catches errors, retry mechanism (3 attempts), error context sent back to LLM for self-correction |
| Gemma4 E4B hallucates numbers instead of generating code | Critical | System prompt explicitly forbids guessing numbers; response validation checks for code blocks on data questions |
| Large files crash the application | Medium | File size validation on upload, chunked reading for >50MB files, memory monitoring |
| User uploads sensitive data to demo mode | High | Clear disclaimers on demo, session auto-delete after 30 min, no server-side logging |
| Ollama not running when user starts app | Medium | Startup health check with clear error message: "Ollama is not running. Start it with: ollama serve" |
| LLM generates harmful code in sandbox | Low | Restricted globals in sandbox, no file write access, no network access, no system calls |
| User expects ChatGPT-level conversation quality | Medium | Manage expectations in onboarding: "I'm optimized for data analysis, not general conversation" |

---

## 10. TIMELINE

### Phase 1: Core Engine (Week 1-2)
- File ingestion (CSV, Excel, PDF)
- Data profiling
- LLM connection (Ollama)
- Basic chat with code generation + execution
- Sandbox

### Phase 2: UI + Visualization (Week 3)
- Flask web UI
- Drag-and-drop upload
- Streaming chat
- Chart generation (matplotlib)
- File cards with profiles

### Phase 3: Data Cleaning + Polish (Week 4)
- Auto-detect data issues
- Cleaning operations
- Download cleaned files
- Session persistence
- Error handling hardening

### Phase 4: Demo Deployment + Launch (Week 5)
- API backend mode (Gemini/Groq)
- Deploy to Railway/Render
- Custom domain
- LinkedIn launch post + animated walkthrough
- Da Vinci anatomy illustration of the system

### Phase 5: Client-Ready (Week 6-8)
- Configuration system for client customization
- Industry-specific system prompt templates
- Installation documentation
- First paid client installation

---

## 11. OPEN QUESTIONS

1. **Project name** — Abhimanyu to decide. Should feel professional, not playful. Suggestions to consider: something that implies intelligence + privacy + simplicity.

2. **Multi-language support** — Should the AI respond in Hindi if the user asks in Hindi? Gemma4 supports multilingual. Could be a differentiator for Indian market.

3. **Which cloud API for demo mode?** — Gemini free tier (1,500 req/day, native Gemma models) vs Groq free tier (faster inference, Llama/Gemma models). Need to test both.

4. **Should charts be interactive from V1?** — Plotly adds complexity but significantly more impressive in demos. Decision: start with matplotlib, add Plotly in Phase 3 if time allows.

5. **Should the tool suggest analyses proactively?** — After upload, instead of waiting for the user to ask, the AI says "I noticed your data has strong seasonal patterns. Want me to show you the trend?" This is impressive but requires more sophisticated prompting.

---

## APPENDIX A: COMPETITIVE LANDSCAPE

| Product | Price | Privacy | Local? | Data Analysis? |
|---|---|---|---|---|
| ChatGPT Plus | $20/mo | Cloud (OpenAI sees data) | No | Yes (Code Interpreter) |
| Google NotebookLM | Free | Cloud (Google sees data) | No | Limited (summarization, not computation) |
| Julius AI | $20-50/mo | Cloud | No | Yes |
| PandasAI | Free (open source) | Local | Yes | Yes (but requires Python knowledge) |
| **This Tool** | Free (self-hosted) or paid setup | Fully local | Yes | Yes (no technical knowledge needed) |

The closest competitor is PandasAI, but it requires users to write Python code and has no UI. This tool wraps the same capability in a consumer-friendly interface.

---

## APPENDIX B: USER FLOW DIAGRAMS

### B.1 First-Time User Flow
```
Open browser → See empty state with drop zone
→ Drop files → See file cards appear with profiles
→ See suggested questions → Click one or type own
→ See streaming response with real data
→ Ask follow-up → Continue conversation
→ Ask for chart → See visualization inline
→ Ask to clean data → See cleaning report
→ Download cleaned file → Close browser
→ Come back later → Session restored
```

### B.2 Returning User Flow
```
Open browser → Previous session auto-loaded
→ See previous files + chat history
→ Continue asking questions OR
→ Upload new files → New profiles added
→ Ask questions across old + new files
```

### B.3 Consultant Setup Flow
```
Install Ollama on client machine
→ Pull Gemma4 E4B model
→ Clone tool repository
→ pip install requirements
→ Customize config.yaml (client name, industry prompt, theme colors)
→ Run app.py
→ Train client on usage (30-60 min session)
→ Hand over → Monthly check-in retainer
```
