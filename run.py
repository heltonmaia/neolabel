#!/usr/bin/env python3
"""Neo-Label dev runner — interactive menu.

Run: python run.py

Config via env:
    UV_VENV         path to uv virtualenv   (default /mnt/hd3/uv-common/uv-neo-label)
    UV_CACHE_DIR    uv cache                (default /mnt/hd3/uv-cache)
    BACKEND_PORT    (default 8000)
    FRONTEND_PORT   (default 5173)
"""
from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / "backend"
FRONTEND = ROOT / "frontend"
RUN_DIR = ROOT / ".run"
LOG_DIR = RUN_DIR / "logs"

UV_VENV = Path(os.environ.get("UV_VENV", "/mnt/hd3/uv-common/uv-neo-label"))
UV_CACHE = os.environ.get("UV_CACHE_DIR", "/mnt/hd3/uv-cache")
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "5173"))


def _venv_env() -> dict[str, str]:
    env = os.environ.copy()
    env["VIRTUAL_ENV"] = str(UV_VENV)
    env["UV_CACHE_DIR"] = UV_CACHE
    env["PATH"] = f"{UV_VENV / 'bin'}{os.pathsep}{env.get('PATH', '')}"
    env.pop("PYTHONHOME", None)
    return env


SERVICES = {
    "backend": {
        "cwd": BACKEND,
        "cmd": [
            str(UV_VENV / "bin" / "uvicorn"),
            "app.main:app",
            "--host", "0.0.0.0",
            "--port", str(BACKEND_PORT),
            "--reload",
        ],
        "env": _venv_env,
        "port": BACKEND_PORT,
        "health": f"http://localhost:{BACKEND_PORT}/health",
    },
    "frontend": {
        "cwd": FRONTEND,
        "cmd": ["npm", "run", "dev", "--", "--port", str(FRONTEND_PORT)],
        "env": lambda: os.environ.copy(),
        "port": FRONTEND_PORT,
        "health": f"http://localhost:{FRONTEND_PORT}/",
    },
}


# ---------- helpers ----------

def _pid_file(name: str) -> Path:
    return RUN_DIR / f"{name}.pid"


def _log_file(name: str) -> Path:
    LOG_DIR.mkdir(parents=True, exist_ok=True)
    return LOG_DIR / f"{name}.log"


def _read_pid(name: str) -> int | None:
    f = _pid_file(name)
    if not f.exists():
        return None
    try:
        return int(f.read_text().strip())
    except ValueError:
        return None


def _alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError):
        return False


def _check_venv() -> bool:
    uvicorn = UV_VENV / "bin" / "uvicorn"
    if not uvicorn.exists():
        print(f"\n⚠  uv venv not found at {UV_VENV}")
        print(f"   Create it with:")
        print(f"   UV_CACHE_DIR={UV_CACHE} uv venv {UV_VENV} --python 3.12")
        print(
            f"   cd backend && VIRTUAL_ENV={UV_VENV} UV_CACHE_DIR={UV_CACHE} uv pip install -e ."
        )
        return False
    return True


def _start(name: str, svc: dict) -> None:
    existing = _read_pid(name)
    if existing and _alive(existing):
        print(f"  {name}: already running (pid {existing})")
        return
    log = _log_file(name)
    log_fd = open(log, "ab")
    proc = subprocess.Popen(
        svc["cmd"],
        cwd=svc["cwd"],
        env=svc["env"](),
        stdout=log_fd,
        stderr=subprocess.STDOUT,
        start_new_session=True,
    )
    RUN_DIR.mkdir(exist_ok=True)
    _pid_file(name).write_text(str(proc.pid))
    print(f"  {name}: started (pid {proc.pid}) -> {log.relative_to(ROOT)}")


def _stop(name: str) -> None:
    pid = _read_pid(name)
    if not pid:
        print(f"  {name}: not running")
        return
    if not _alive(pid):
        _pid_file(name).unlink(missing_ok=True)
        print(f"  {name}: stale pid cleaned")
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        pass
    for _ in range(20):
        if not _alive(pid):
            break
        time.sleep(0.1)
    if _alive(pid):
        os.killpg(os.getpgid(pid), signal.SIGKILL)
    _pid_file(name).unlink(missing_ok=True)
    print(f"  {name}: stopped (pid {pid})")


# ---------- actions ----------

def start_backend() -> None:
    if not _check_venv():
        return
    _start("backend", SERVICES["backend"])


def _ensure_frontend_deps() -> bool:
    if (FRONTEND / "node_modules" / ".bin" / "vite").exists():
        return True
    print("  frontend: node_modules missing, running `npm install`...")
    r = subprocess.run(["npm", "install"], cwd=FRONTEND)
    if r.returncode != 0:
        print("  npm install failed")
        return False
    return True


def start_frontend() -> None:
    if not _ensure_frontend_deps():
        return
    _start("frontend", SERVICES["frontend"])


def start_both() -> None:
    if not _check_venv():
        return
    if not _ensure_frontend_deps():
        return
    print("Starting backend + frontend...")
    _start("backend", SERVICES["backend"])
    _start("frontend", SERVICES["frontend"])
    _wait_for_health(timeout=15)
    show_status()


def _wait_for_health(timeout: float = 10) -> None:
    deadline = time.time() + timeout
    while time.time() < deadline:
        if all(_http_ok(s["health"]) for s in SERVICES.values()):
            return
        time.sleep(0.3)


def open_in_browser() -> None:
    url = f"http://localhost:{FRONTEND_PORT}/"
    if not _http_ok(url):
        print(f"  UI not responding at {url} — is the frontend running?")
        return
    print(f"  opening {url}")
    webbrowser.open(url)


def stop_backend() -> None:
    _stop("backend")


def stop_frontend() -> None:
    _stop("frontend")


def stop_all() -> None:
    print("Stopping all...")
    for name in SERVICES:
        _stop(name)


def restart_all() -> None:
    stop_all()
    time.sleep(0.5)
    start_both()


def show_status() -> None:
    print()
    print(f"uv venv: {UV_VENV}  ({'ok' if _check_venv_silent() else 'missing'})")
    print(f"data:    {ROOT / 'backend' / 'data'}")
    print()
    print(f"  {'SERVICE':<10} {'PID':<8} {'PORT':<6} {'PROCESS':<10} HEALTH")
    print("  " + "-" * 50)
    for name, svc in SERVICES.items():
        pid = _read_pid(name)
        proc = "up" if (pid and _alive(pid)) else "down"
        health = "ok" if _http_ok(svc["health"]) else "—"
        print(f"  {name:<10} {str(pid or '-'):<8} {svc['port']:<6} {proc:<10} {health}")
    print()
    print(f"  API:  http://localhost:{BACKEND_PORT}/docs")
    print(f"  UI:   http://localhost:{FRONTEND_PORT}/")
    print()


def _check_venv_silent() -> bool:
    return (UV_VENV / "bin" / "uvicorn").exists()


def tail_logs() -> None:
    files = [_log_file(n) for n in SERVICES]
    existing = [f for f in files if f.exists()]
    if not existing:
        print("No logs yet. Start a service first.")
        return
    print(f"Tailing {len(existing)} log file(s). Ctrl-C to return to menu.")
    try:
        subprocess.run(["tail", "-n", "50", "-F", *map(str, existing)])
    except KeyboardInterrupt:
        pass


def run_backend_tests() -> None:
    if not _check_venv():
        return
    env = _venv_env()
    pytest_bin = UV_VENV / "bin" / "pytest"
    if not pytest_bin.exists():
        print("  pytest not installed — installing test deps...")
        subprocess.run(
            ["uv", "pip", "install", "pytest", "httpx"],
            cwd=BACKEND,
            env=env,
            check=False,
        )
    print("Running backend tests...\n")
    r = subprocess.run(
        [str(UV_VENV / "bin" / "python"), "-m", "pytest", "-v", "--tb=short"],
        cwd=BACKEND,
        env=env,
        check=False,
    )
    print()
    print("═" * 50)
    if r.returncode == 0:
        print("  ✓ ALL TESTS PASSED")
    else:
        print(f"  ✗ TESTS FAILED (exit code {r.returncode})")
    print("═" * 50)
    try:
        input("\nPress Enter to return to menu (Ctrl-C to quit)... ")
    except (EOFError, KeyboardInterrupt):
        print()


def install_backend_deps() -> None:
    if not _check_venv_silent():
        print(f"Creating uv venv at {UV_VENV}...")
        env = os.environ.copy()
        env["UV_CACHE_DIR"] = UV_CACHE
        subprocess.run(
            ["uv", "venv", str(UV_VENV), "--python", "3.12"],
            env=env,
            check=False,
        )
    env = _venv_env()
    print("Installing backend deps...")
    subprocess.run(["uv", "pip", "install", "-e", "."], cwd=BACKEND, env=env, check=False)


def install_frontend_deps() -> None:
    print("Running npm install...")
    subprocess.run(["npm", "install"], cwd=FRONTEND, check=False)


# ---------- menu ----------

MENU = [
    ("Start both (backend + frontend)", start_both),
    ("Start backend only",              start_backend),
    ("Start frontend only",             start_frontend),
    ("Open UI in browser",              open_in_browser),
    ("Stop all",                        stop_all),
    ("Stop backend",                    stop_backend),
    ("Stop frontend",                   stop_frontend),
    ("Restart all",                     restart_all),
    ("Status",                          show_status),
    ("Tail logs (Ctrl-C returns)",      tail_logs),
    ("Run backend tests (pytest)",      run_backend_tests),
    ("Install backend deps (uv)",       install_backend_deps),
    ("Install frontend deps (npm)",     install_frontend_deps),
]


def render_menu() -> None:
    print("\n" + "═" * 50)
    print("  Neo-Label — dev runner")
    print("═" * 50)
    for i, (label, _) in enumerate(MENU, 1):
        print(f"  {i:>2}. {label}")
    print(f"   0. Quit")
    print("─" * 50)


def main() -> None:
    while True:
        render_menu()
        try:
            choice = input("Choose: ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return
        if choice in {"0", "q", "quit", "exit"}:
            return
        if not choice.isdigit() or not (1 <= int(choice) <= len(MENU)):
            print(f"  invalid choice: {choice!r}")
            continue
        _, action = MENU[int(choice) - 1]
        try:
            action()
        except KeyboardInterrupt:
            print()


if __name__ == "__main__":
    main()
