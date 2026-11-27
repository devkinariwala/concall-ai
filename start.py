import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_DIR = ROOT / "backend"
FRONTEND_DIR = ROOT / "frontend"


def find_python() -> str:
    """Prefer the project's .venv Python if present, else current interpreter."""
    candidates = [
        ROOT / ".venv" / "Scripts" / "python.exe",  # Windows
        ROOT / ".venv" / "bin" / "python",          # macOS / Linux
    ]
    for candidate in candidates:
        if candidate.exists():
            return str(candidate)
    return sys.executable


def main() -> None:
    python_exe = find_python()
    npm_exe = shutil.which("npm")
    if not npm_exe:
        print("Error: 'npm' was not found in PATH. Please install Node.js.", file=sys.stderr)
        sys.exit(1)

    env = os.environ.copy()
    existing_py_path = env.get("PYTHONPATH", "")
    env["PYTHONPATH"] = (
        f"{BACKEND_DIR}{os.pathsep}{existing_py_path}"
        if existing_py_path
        else str(BACKEND_DIR)
    )

    print("Starting ConcallAI backend (FastAPI + Background Watcher + WebSocket) on http://localhost:8000 ...")
    backend_proc = subprocess.Popen(
        [
            python_exe,
            "-m",
            "uvicorn",
            "app.main:app",
            "--app-dir",
            str(BACKEND_DIR),
            "--port",
            "8000",
        ],
        cwd=str(ROOT),
        env=env,
    )

    frontend_proc = None
    try:
        time.sleep(2)
        print("Starting ConcallAI frontend (Vite) on http://localhost:5173 ...")
        frontend_proc = subprocess.Popen(
            [npm_exe, "run", "dev"],
            cwd=str(FRONTEND_DIR),
            env=env,
        )
        frontend_proc.wait()
    except KeyboardInterrupt:
        print("\nShutting down ConcallAI...")
    finally:
        for proc in (frontend_proc, backend_proc):
            if proc and proc.poll() is None:
                proc.terminate()
                try:
                    proc.wait(timeout=5)
                except subprocess.TimeoutExpired:
                    proc.kill()


if __name__ == "__main__":
    main()