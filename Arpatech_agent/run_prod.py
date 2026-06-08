"""
Run the API with a production-grade WSGI server:
- Windows  -> waitress
- Linux/macOS -> gunicorn (falls back to waitress if gunicorn missing)

Usage:
    python run_prod.py
Optional env:
    WORKERS=2
    THREADS=8
    HOST=0.0.0.0
    PORT=5000
"""
import os
import sys
import platform
import subprocess
from pathlib import Path

HERE = Path(__file__).resolve().parent
APP_PATH = HERE / "app.py"
MODULE_APP = "app:app"

HOST = os.getenv("HOST", "127.0.0.1")
PORT = os.getenv("PORT", "5000")
WORKERS = os.getenv("WORKERS", "2")
THREADS = os.getenv("THREADS", "8")

def run_waitress():
    # waitress is pure Python and works on Windows/macOS/Linux
    cmd = [
        sys.executable, "-m", "waitress",
        f"--listen={HOST}:{PORT}",
        MODULE_APP
    ]
    print(f"[run_prod] Starting waitress: {' '.join(cmd)}")
    os.execv(sys.executable, cmd)  # replace current process

def run_gunicorn():
    cmd = [
        "gunicorn",
        "-w", WORKERS,
        "-k", "gthread",
        "--threads", THREADS,
        "-b", f"{HOST}:{PORT}",
        "--timeout", "60",
        MODULE_APP
    ]
    print(f"[run_prod] Starting gunicorn: {' '.join(cmd)}")
    os.execvp("gunicorn", cmd)  # replace current process

def main():
    system = platform.system().lower()
    print(f"[run_prod] Detected OS: {system}")

    if system == "windows":
        # Always use waitress on Windows
        run_waitress()
    else:
        # Try gunicorn; fall back to waitress if not installed
        try:
            subprocess.run(["gunicorn", "--version"], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            run_gunicorn()
        except Exception:
            print("[run_prod] gunicorn not found or failed; falling back to waitress.")
            run_waitress()

if __name__ == "__main__":
    main()
