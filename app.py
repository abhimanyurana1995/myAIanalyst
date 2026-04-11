"""
MyAnalyst — Flask Application
All routes defined here.

Run with:
    python app.py
"""

from __future__ import annotations

import json
import logging
import os
import io
import sys
import time
import uuid
import webbrowser
from threading import Timer

from flask import (
    Flask,
    Response,
    jsonify,
    request,
    send_file,
    send_from_directory,
    stream_with_context,
)
from werkzeug.utils import secure_filename

# ---------------------------------------------------------------------------
# Logging setup — nice format for the terminal
# ---------------------------------------------------------------------------
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
    datefmt="%H:%M:%S",
    handlers=[logging.StreamHandler(sys.stdout)],
)
logger = logging.getLogger("datasense")

# ---------------------------------------------------------------------------
# Load config
# ---------------------------------------------------------------------------
from config import load_config
cfg = load_config()

APP_NAME    = cfg["app"]["name"]
PORT        = int(cfg["app"]["port"])
DEBUG       = bool(cfg["app"]["debug"])
# On Railway (or any cloud host), APP_HOST or PORT env var is set → bind to 0.0.0.0
_is_cloud = os.environ.get("PORT") or os.environ.get("APP_HOST")
HOST        = cfg["app"]["host"] if not _is_cloud else "0.0.0.0"
UPLOAD_DIR  = cfg["files"]["upload_dir"]
CHART_DIR   = cfg["files"]["chart_dir"]
SESSION_DIR = cfg["session"]["dir"]
MAX_MB      = float(cfg["files"]["max_size_mb"])
ALLOWED_EXT = set(cfg["files"]["allowed_types"])

for d in (UPLOAD_DIR, CHART_DIR, SESSION_DIR):
    os.makedirs(d, exist_ok=True)

# ---------------------------------------------------------------------------
# Initialise engine components
# ---------------------------------------------------------------------------
from engine.ingestion import FileIngestionEngine, UnsupportedFileError, FileParsingError, FileTooLargeError
from engine.sandbox import Sandbox
from engine.state import StateManager
from engine.session import SessionManager
from engine.brain import BrainEngine
from engine.backends.cloud_api import create_backend

ingestion = FileIngestionEngine(max_size_mb=MAX_MB)
sandbox   = Sandbox(
    timeout=cfg["sandbox"]["timeout_seconds"],
    chart_dir=CHART_DIR,
)
state   = StateManager()
session = SessionManager(SESSION_DIR)
backend = create_backend(cfg)
brain   = BrainEngine(backend, state, sandbox, session, cfg)

# Attempt to restore previous session
try:
    restored = session.load(state, ingestion, upload_dir=UPLOAD_DIR)
    if restored:
        logger.info("Previous session restored. Files: %s", list(state.dataframes.keys()))
except Exception as e:
    logger.warning("Session restore error: %s", e)

# ---------------------------------------------------------------------------
# Flask app
# ---------------------------------------------------------------------------
app = Flask(
    __name__,
    static_folder="static",
    static_url_path="",
)
app.config["MAX_CONTENT_LENGTH"] = int(MAX_MB * 1024 * 1024)


# ---------------------------------------------------------------------------
# Routes — Static files
# ---------------------------------------------------------------------------

@app.route("/")
def index():
    return send_from_directory("static", "index.html")


# ---------------------------------------------------------------------------
# Routes — File upload
# ---------------------------------------------------------------------------

@app.route("/upload", methods=["POST"])
def upload():
    if "file" not in request.files:
        return jsonify({"success": False, "error": "No file provided."}), 400

    file = request.files["file"]
    if not file or file.filename == "":
        return jsonify({"success": False, "error": "Empty filename."}), 400

    original_name = secure_filename(file.filename)
    ext = original_name.rsplit(".", 1)[-1].lower() if "." in original_name else ""

    if ext not in ALLOWED_EXT:
        return jsonify({
            "success": False,
            "error": f"File type '.{ext}' not supported. Allowed: {', '.join(sorted(ALLOWED_EXT))}",
        }), 400

    # Build destination path
    save_path = os.path.join(UPLOAD_DIR, original_name)

    # Warn if replacing
    replacing = original_name in state.filenames.values()

    try:
        file.save(save_path)
    except OSError as e:
        return jsonify({"success": False, "error": f"Could not save file: {e}"}), 500

    # Ingest
    try:
        ingested = ingestion.ingest(save_path)
    except FileTooLargeError as e:
        return jsonify({"success": False, "error": str(e)}), 413
    except UnsupportedFileError as e:
        return jsonify({"success": False, "error": str(e)}), 400
    except FileParsingError as e:
        return jsonify({"success": False, "error": str(e)}), 422
    except Exception as e:
        logger.exception("Unexpected error ingesting '%s'", original_name)
        return jsonify({"success": False, "error": f"Failed to process file: {e}"}), 500

    # Register DataFrames in state
    from engine.state import sanitize_name
    existing_names = set(state.dataframes.keys())

    for var_name, df in ingested.dataframes.items():
        # If replacing, remove old
        if replacing:
            old_var = next(
                (k for k, v in state.filenames.items() if v == original_name), None
            )
            if old_var:
                state.remove_dataframe(old_var)

        state.add_dataframe(
            var_name=var_name,
            df=df,
            profile=ingested.profile,
            health=ingested.health,
            original_filename=original_name,
        )

    # Build response payload
    response_data = _build_file_card(original_name, ingested)
    response_data["replacing"] = replacing
    session.save(state)

    return jsonify({"success": True, "file": response_data})


def _build_file_card(filename: str, ingested) -> dict:
    """Build the JSON payload sent to the frontend file card."""
    health = ingested.health
    # Health color: green ≥85, yellow ≥60, red <60
    score = health.overall_score
    health_color = "green" if score >= 85 else ("yellow" if score >= 60 else "red")

    issues_summary = []
    for issue in health.issues[:5]:
        issues_summary.append({
            "severity": issue.severity,
            "description": issue.description,
            "fix": issue.suggested_fix,
        })

    var_names = list(ingested.dataframes.keys())

    return {
        "filename": filename,
        "file_type": ingested.file_type,
        "var_names": var_names,
        "row_count": ingested.profile.row_count,
        "column_count": ingested.profile.column_count,
        "health_score": score,
        "health_color": health_color,
        "issues": issues_summary,
        "profile_text": ingested.profile.profile_text,
    }


# ---------------------------------------------------------------------------
# Routes — Files list / status
# ---------------------------------------------------------------------------

@app.route("/files", methods=["GET"])
def list_files():
    files = []
    for var_name, df in state.dataframes.items():
        original = state.filenames.get(var_name, var_name)
        profile = state.profiles.get(var_name)
        health = state.health_reports.get(var_name)
        files.append({
            "var_name": var_name,
            "filename": original,
            "rows": len(df),
            "columns": len(df.columns),
            "column_names": list(df.columns[:20]),
            "health_score": health.overall_score if health else 100,
            "profile_text": profile.profile_text if profile else "",
        })
    total_rows = sum(len(df) for df in state.dataframes.values())
    return jsonify({
        "files": files,
        "total_files": len(files),
        "total_rows": total_rows,
    })


@app.route("/files/<var_name>", methods=["DELETE"])
def delete_file(var_name: str):
    if var_name not in state.dataframes:
        return jsonify({"success": False, "error": "File not found."}), 404
    state.remove_dataframe(var_name)
    session.save(state)
    return jsonify({"success": True})


# ---------------------------------------------------------------------------
# Routes — Chat
# ---------------------------------------------------------------------------

@app.route("/chat/stream")
def chat_stream():
    message = request.args.get("message", "").strip()
    if not message:
        return jsonify({"error": "No message provided."}), 400

    def generate():
        try:
            for event in brain.chat(message):
                yield f"data: {json.dumps(event, ensure_ascii=False)}\n\n"
        except Exception as e:
            logger.exception("Error in chat_stream generate()")
            yield f"data: {json.dumps({'type': 'error', 'content': str(e)})}\n\n"
            yield f"data: {json.dumps({'type': 'done'})}\n\n"

    return Response(
        stream_with_context(generate()),
        mimetype="text/event-stream",
        headers={
            "Cache-Control": "no-cache, no-store",
            "X-Accel-Buffering": "no",
            "Connection": "keep-alive",
        },
    )


@app.route("/chat/history", methods=["GET"])
def chat_history():
    history = [
        {
            "role": m.role,
            "content": m.content,
            "timestamp": m.timestamp,
            "confidence": m.confidence,
        }
        for m in state.chat_history
    ]
    return jsonify({"history": history})


# ---------------------------------------------------------------------------
# Routes — Charts
# ---------------------------------------------------------------------------

@app.route("/chart/<chart_id>")
def serve_chart(chart_id: str):
    safe_id = secure_filename(chart_id)
    # Security: ensure we're serving only from chart_dir
    chart_path = os.path.realpath(os.path.join(CHART_DIR, safe_id))
    chart_dir_real = os.path.realpath(CHART_DIR)
    if not chart_path.startswith(chart_dir_real):
        return jsonify({"error": "Invalid chart path."}), 400

    if not os.path.exists(chart_path):
        return jsonify({"error": "Chart not found."}), 404

    return send_from_directory(CHART_DIR, safe_id, mimetype="image/png")


# ---------------------------------------------------------------------------
# Routes — Download cleaned/processed data
# ---------------------------------------------------------------------------

@app.route("/download/<var_name>")
def download_file(var_name: str):
    fmt = request.args.get("format", "csv").lower()
    if fmt not in ("csv", "xlsx"):
        return jsonify({"error": "Invalid format. Use 'csv' or 'xlsx'."}), 400

    df = state.dataframes.get(var_name)
    if df is None:
        return jsonify({"error": f"DataFrame '{var_name}' not found."}), 404

    original_name = state.filenames.get(var_name, var_name)
    base = original_name.rsplit(".", 1)[0] if "." in original_name else original_name

    try:
        buf = io.BytesIO()
        if fmt == "csv":
            df.to_csv(buf, index=False, encoding="utf-8-sig")  # BOM for Excel compat
            buf.seek(0)
            return send_file(
                buf,
                mimetype="text/csv",
                as_attachment=True,
                download_name=f"{base}_cleaned.csv",
            )
        else:
            df.to_excel(buf, index=False, engine="openpyxl")
            buf.seek(0)
            return send_file(
                buf,
                mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                as_attachment=True,
                download_name=f"{base}_cleaned.xlsx",
            )
    except Exception as e:
        logger.exception("Download error for '%s'", var_name)
        return jsonify({"error": f"Could not export file: {e}"}), 500


# ---------------------------------------------------------------------------
# Routes — Session management
# ---------------------------------------------------------------------------

@app.route("/session/clear", methods=["POST"])
def clear_session():
    session.clear(state)
    return jsonify({"success": True, "message": "Session cleared."})


@app.route("/session/status", methods=["GET"])
def session_status():
    return jsonify({
        "has_session": session.exists(),
        "files_loaded": len(state.dataframes),
        "messages": len(state.chat_history),
    })


# ---------------------------------------------------------------------------
# Routes — Health / status
# ---------------------------------------------------------------------------

@app.route("/api/health", methods=["GET"])
def health():
    llm_ok = False
    llm_message = ""
    try:
        llm_ok = backend.health_check()
        if not llm_ok:
            backend_type = cfg["llm"]["backend"]
            if backend_type == "ollama":
                llm_message = (
                    "Ollama is not running or the model is not available. "
                    "Start Ollama with: ollama serve"
                )
            else:
                llm_message = "Cloud API key not configured."
        else:
            llm_message = "OK"
    except Exception as e:
        llm_message = str(e)

    return jsonify({
        "status": "ok",
        "app_name": APP_NAME,
        "llm_backend": cfg["llm"]["backend"],
        "llm_ok": llm_ok,
        "llm_message": llm_message,
        "files_loaded": len(state.dataframes),
    })


# ---------------------------------------------------------------------------
# Error handlers
# ---------------------------------------------------------------------------

@app.errorhandler(413)
def request_entity_too_large(e):
    return jsonify({
        "success": False,
        "error": f"File too large. Maximum allowed size is {MAX_MB:.0f} MB.",
    }), 413


@app.errorhandler(404)
def not_found(e):
    return jsonify({"error": "Not found."}), 404


@app.errorhandler(500)
def internal_error(e):
    logger.exception("Internal server error")
    return jsonify({"error": "An unexpected error occurred."}), 500


# ---------------------------------------------------------------------------
# Startup
# ---------------------------------------------------------------------------

def _open_browser(url: str):
    webbrowser.open(url)


if __name__ == "__main__":
    url = f"http://{HOST}:{PORT}"
    print()
    print("=" * 60)
    print(f"  {APP_NAME}")
    print("=" * 60)
    print(f"  URL:     {url}")
    print(f"  Backend: {cfg['llm']['backend'].upper()}")
    if cfg["llm"]["backend"] == "ollama":
        print(f"  Model:   {cfg['llm']['ollama']['model']}")
        print(f"  Ollama:  {cfg['llm']['ollama']['host']}")
    print(f"  Max file size: {MAX_MB:.0f} MB")
    print()

    # Health check
    if not backend.health_check():
        if cfg["llm"]["backend"] == "ollama":
            print("  [!] WARNING: Ollama is not running.")
            print("     Start it in another terminal with: ollama serve")
            print("     Then pull the model with:  ollama pull gemma4:e4b")
        else:
            print("  [!] WARNING: Cloud API key not configured.")
            print("     Set GEMINI_API_KEY or GROQ_API_KEY environment variable.")
    else:
        print("  [OK] LLM backend is ready.")

    print()

    # Open browser after a short delay (local only — skipped on cloud)
    if not _is_cloud:
        Timer(1.2, _open_browser, args=[url]).start()

    app.run(
        host=HOST,
        port=PORT,
        debug=DEBUG,
        use_reloader=False,    # Avoid double-startup in debug mode
        threaded=True,
    )
