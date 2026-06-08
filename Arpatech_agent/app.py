import asyncio
import json
import re
from datetime import datetime, timedelta, timezone
from logging.handlers import RotatingFileHandler
import os
import uuid
import logging
from os import environ
from dotenv import load_dotenv
from flask import Flask, g, jsonify, render_template, request, session
from werkzeug.middleware.proxy_fix import ProxyFix

from copilot_service import CopilotService
from service import copilot_client

load_dotenv()

app = Flask(__name__)
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1)

app.secret_key = environ.get("FLASK_SECRET_KEY")
if not app.secret_key:
    raise ValueError("FLASK_SECRET_KEY is required")

SESSION_TIMEOUT = timedelta(minutes=10)
LOG_DIR = environ.get("LOG_DIR", "logs")
CHAT_DIR = environ.get("CHAT_DIR", "chats")
os.makedirs(LOG_DIR, exist_ok=True)
os.makedirs(CHAT_DIR, exist_ok=True)

DEBUG_MODE = environ.get("FLASK_DEBUG", "false").lower() in ("1", "true", "yes")
app.config["DEBUG"] = DEBUG_MODE

SESSION_SECURE = environ.get(
    "SESSION_COOKIE_SECURE",
    "false" if DEBUG_MODE else "true"
).lower() in ("1", "true", "yes")
app.config.update(
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=SESSION_SECURE,
    SESSION_COOKIE_HTTPONLY=True,
    PERMANENT_SESSION_LIFETIME=86400,
    PREFERRED_URL_SCHEME="https",
)

USER_COOKIE_NAME = "user_id"
USER_COOKIE_MAX_AGE = 30 * 24 * 60 * 60  # 30 days

LOG_LEVEL = environ.get("LOG_LEVEL", "INFO").upper()
LOG_FILE = os.path.join(LOG_DIR, environ.get("LOG_FILE", "app.log"))

copilot_service = CopilotService(copilot_client)
logger = logging.getLogger(__name__)


def configure_logging():
    formatter = logging.Formatter(
        "%(asctime)s %(levelname)s [%(name)s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    file_handler = RotatingFileHandler(
        LOG_FILE,
        maxBytes=10 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    file_handler.setFormatter(formatter)
    file_handler.setLevel(LOG_LEVEL)

    console_handler = logging.StreamHandler()
    console_handler.setFormatter(formatter)
    console_handler.setLevel(LOG_LEVEL)

    logging.basicConfig(level=LOG_LEVEL, handlers=[file_handler, console_handler])
    logger.setLevel(LOG_LEVEL)
    logger.propagate = False


configure_logging()


@app.after_request
def apply_security_headers(response):
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["X-Frame-Options"] = "DENY"
    response.headers["Referrer-Policy"] = "no-referrer-when-downgrade"
    response.headers["Permissions-Policy"] = "geolocation=(), microphone=()"
    if SESSION_SECURE:
        response.headers[
            "Strict-Transport-Security"
        ] = "max-age=31536000; includeSubDomains"

    user_id = get_user_id()
    response.set_cookie(
        USER_COOKIE_NAME,
        user_id,
        max_age=USER_COOKIE_MAX_AGE,
        httponly=True,
        secure=SESSION_SECURE,
        samesite="Lax",
    )
    return response

def get_user_id():
    if hasattr(g, "user_id"):
        return g.user_id

    user_id = request.cookies.get(USER_COOKIE_NAME)
    if not user_id:
        user_id = str(uuid.uuid4())

    g.user_id = user_id
    return user_id


def session_history_file(user_id):
    return os.path.join(CHAT_DIR, f"{user_id}.txt")


def append_chat_message(user_id, role, message):
    file_path = session_history_file(user_id)
    payload = {
        "timestamp": datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S"),
        "role": role,
        "message": message,
    }
    with open(file_path, "a", encoding="utf-8") as f:
        f.write(json.dumps(payload, ensure_ascii=False) + "\n")


def load_chat_history(user_id, limit=20, start_after=0):
    file_path = session_history_file(user_id)
    if not os.path.exists(file_path):
        return []

    entries = []
    with open(file_path, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                payload = json.loads(line)
                entries.append({
                    "role": payload.get("role", "agent"),
                    "message": remove_citations(payload.get("message", "")),
                })
            except ValueError:
                # Fallback for legacy line format
                parsed = parse_legacy_log_line(line)
                if parsed:
                    entries.append(parsed)

    entries = entries[start_after:]
    if len(entries) <= limit:
        return entries
    return entries[-limit:]


def count_chat_messages(user_id):
    file_path = session_history_file(user_id)
    if not os.path.exists(file_path):
        return 0
    with open(file_path, "r", encoding="utf-8") as f:
        return sum(1 for _ in f)


def parse_legacy_log_line(line):
    try:
        if line.startswith("["):
            parts = line.split("] ")
            if len(parts) >= 3:
                role_part = parts[1].strip("[] ")
                message_part = "] ".join(parts[2:])
                return {"role": role_part.lower(), "message": remove_citations(message_part)}
    except Exception:
        pass
    return None


def is_session_active():
    last_active = session.get("last_active")
    if last_active is None:
        return False

    now = datetime.now(timezone.utc)
    return now - datetime.fromtimestamp(last_active, tz=timezone.utc) <= SESSION_TIMEOUT


def ensure_session_state():
    session.permanent = True
    if not is_session_active():
        session["last_active"] = None
        session["chat_cleared"] = False
        session["clear_index"] = 0

    session.setdefault("chat_cleared", False)
    session.setdefault("clear_index", 0)
    return is_session_active()
    

@app.route("/", methods=["GET"])
def chat_ui():
    get_user_id()
    return render_template("index.html")

@app.route("/init", methods=["POST"])
def init():
    try:
        user_id = get_user_id()
        active = ensure_session_state()
        cleared = session.get("chat_cleared", False)
        clear_index = session.get("clear_index", 0)

        history = []
        if not cleared:
            history = load_chat_history(
                user_id,
                limit=20,
                start_after=clear_index,
            )

        response = None
        if not history and not cleared:
            response = asyncio.run(copilot_service.get_initial_greeting())
            response = remove_citations(response)
            response = format_as_paragraphs(response)
            append_chat_message(user_id, "agent", response)
            history = [{"role": "agent", "message": response}]

        return jsonify({
            "response": response,
            "user_id": user_id,
            "history": history,
            "cleared": cleared,
            "active_session": active,
        })

    except Exception:
        logger.exception("[Init] Error")
        return jsonify({"error": "Failed"}), 500

def remove_citations(text: str) -> str:
    """Remove citations and citation references from text."""
    if not text:
        return text

    # Remove citation definitions like [1]: cite:1 "Citation-1" or [1]: https://...
    text = re.sub(r'\[\s*\d+\s*\]:.*(?:\r?\n|$)', '', text, flags=re.MULTILINE)
    # Remove inline citation references like [1], [2], [123]
    text = re.sub(r'\[\s*\d+\s*\]', '', text)
    # Collapse extra whitespace left by citation removal.
    text = re.sub(r'\s{2,}', ' ', text)

    return text.strip()

def format_as_paragraphs(text: str) -> str:
    """Format text into proper paragraphs for better readability."""
    if not text:
        return text
    
    # Split by double newlines to identify paragraph boundaries
    paragraphs = re.split(r'\n\s*\n', text)
    
    # Process each paragraph
    formatted_paragraphs = []
    for para in paragraphs:
        # Replace single newlines within a paragraph with spaces
        para = para.replace('\n', ' ')
        # Clean up extra spaces
        para = re.sub(r'\s{2,}', ' ', para).strip()
        if para:
            formatted_paragraphs.append(para)
    
    # Join paragraphs with double newlines for markdown rendering
    return '\n\n'.join(formatted_paragraphs)

@app.route("/chat", methods=["POST"])
def chat():
    data = request.get_json(silent=True)
    user_message = data.get("message") if isinstance(data, dict) else None

    if not user_message:
        return jsonify({"error": "Message is required"}), 400

    try:
        user_id = get_user_id()
        now = datetime.now(timezone.utc)
        session["last_active"] = now.timestamp()

        append_chat_message(user_id, "user", user_message)

        response = asyncio.run(copilot_service.send_message(user_message))
        response = remove_citations(response)
        response = format_as_paragraphs(response)
        append_chat_message(user_id, "agent", response)

        return jsonify({
            "response": response,
            "history": [],
        })

    except Exception:
        logger.exception("[Chat] Error")
        return jsonify({"error": "Failed"}), 500
    

@app.route("/reset", methods=["POST"])
def reset():
    user_id = get_user_id()
    session["chat_cleared"] = True
    session["clear_index"] = count_chat_messages(user_id)
    return jsonify({"message": "Chat history cleared", "cleared": True})

if __name__ == "__main__":
    host = environ.get("HOST", "0.0.0.0")
    port = int(environ.get("PORT", "5000"))
    app.run(host=host, port=port, debug=DEBUG_MODE)
