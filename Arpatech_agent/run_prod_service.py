"""
Run the API with a production-grade WSGI server for Windows Service:
- Windows -> waitress (blocking, doesn't use os.execv)
- Linux/macOS -> gunicorn (falls back to waitress if gunicorn missing)

This version is designed to work with .NET Windows Services and doesn't use os.execv()
which causes process replacement issues in service environments.

Usage: python run_prod_service.py
Optional env: WORKERS=2 THREADS=8 HOST=0.0.0.0 PORT=5000
"""

import os
import sys
import platform
import subprocess

def run_waitress():
    """Run waitress server directly (blocking call, proper for services)"""
    import waitress
    from app import app
    
    host = os.getenv("HOST", "127.0.0.1")
    port = os.getenv("PORT", "5000")
    
    print(f"[run_prod] Starting waitress on {host}:{port}")
    print("[run_prod] Flask app is running")
    
    # This blocks and keeps the process alive
    try:
        waitress.serve(app, host=host, port=port, _quiet=False)
    except KeyboardInterrupt:
        print("[run_prod] Waitress interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"[run_prod] Error running waitress: {e}")
        sys.exit(1)

def run_gunicorn():
    """Run gunicorn server via subprocess"""
    host = os.getenv("HOST", "127.0.0.1")
    port = os.getenv("PORT", "5000")
    workers = os.getenv("WORKERS", "2")
    threads = os.getenv("THREADS", "8")
    
    cmd = [
        "gunicorn",
        "-w", workers,
        "-k", "gthread",
        "--threads", threads,
        "-b", f"{host}:{port}",
        "--timeout", "60",
        "--access-logfile", "-",
        "--error-logfile", "-",
        "app:app"
    ]
    
    print(f"[run_prod] Starting gunicorn: {' '.join(cmd)}")
    
    try:
        result = subprocess.run(cmd, check=False)
        sys.exit(result.returncode)
    except KeyboardInterrupt:
        print("[run_prod] Gunicorn interrupted")
        sys.exit(0)
    except Exception as e:
        print(f"[run_prod] Error running gunicorn: {e}")
        sys.exit(1)

def main():
    system = platform.system().lower()
    print(f"[run_prod] Detected OS: {system}")
    
    try:
        if system == "windows":
            # Always use waitress on Windows - it blocks properly
            print("[run_prod] Using waitress on Windows")
            run_waitress()
        else:
            # Try gunicorn on Unix-like systems
            try:
                subprocess.run(
                    ["gunicorn", "--version"],
                    check=True,
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL
                )
                print("[run_prod] Gunicorn found, using it")
                run_gunicorn()
            except Exception:
                print("[run_prod] Gunicorn not found; falling back to waitress")
                run_waitress()
    except Exception as e:
        print(f"[run_prod] Fatal error: {e}")
        sys.exit(1)

if __name__ == "__main__":
    main()
