#!/usr/bin/env python3
"""Neo-Label dev runner — interactive menu (Docker-based).

Run: python run.py

Config via env:
    BACKEND_PORT    (default 8000)
    FRONTEND_PORT   (default 5173)
"""
from __future__ import annotations

import os
import subprocess
import urllib.error
import urllib.request
import webbrowser
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BACKEND_PORT = int(os.environ.get("BACKEND_PORT", "8000"))
FRONTEND_PORT = int(os.environ.get("FRONTEND_PORT", "5173"))


def _compose(*args: str) -> int:
    return subprocess.run(["docker", "compose", *args], cwd=ROOT, check=False).returncode


def _http_ok(url: str, timeout: float = 1.0) -> bool:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return 200 <= r.status < 500
    except (urllib.error.URLError, urllib.error.HTTPError, TimeoutError, ConnectionError):
        return False


def up() -> None:
    if _compose("up", "--build", "-d") != 0:
        return
    _compose("ps")
    print()
    print(f"  API:  http://localhost:{BACKEND_PORT}/docs")
    print(f"  UI:   http://localhost:{FRONTEND_PORT}/")


def down() -> None:
    _compose("down")


def logs() -> None:
    print("Following logs — Ctrl-C to return.")
    try:
        _compose("logs", "-f", "--tail=50")
    except KeyboardInterrupt:
        pass


def status() -> None:
    _compose("ps")
    api = "ok" if _http_ok(f"http://localhost:{BACKEND_PORT}/health") else "—"
    ui = "ok" if _http_ok(f"http://localhost:{FRONTEND_PORT}/") else "—"
    print()
    print(f"  API {api}   http://localhost:{BACKEND_PORT}/docs")
    print(f"  UI  {ui}   http://localhost:{FRONTEND_PORT}/")


def open_ui() -> None:
    url = f"http://localhost:{FRONTEND_PORT}/"
    if not _http_ok(url):
        print(f"  UI not responding at {url}. Run 'Up' first.")
        return
    print(f"  opening {url}")
    webbrowser.open(url)


def tests() -> None:
    print("Running backend tests inside container...\n")
    rc = _compose("exec", "-T", "backend", "pytest", "-v", "--tb=short")
    print()
    print("═" * 50)
    print("  ✓ ALL TESTS PASSED" if rc == 0 else f"  ✗ TESTS FAILED (exit {rc})")
    print("═" * 50)
    try:
        input("\nPress Enter to return... ")
    except (EOFError, KeyboardInterrupt):
        print()


MENU = [
    ("Up (build + start)",          up),
    ("Down (stop)",                 down),
    ("Logs (follow)",               logs),
    ("Status",                      status),
    ("Open UI in browser",          open_ui),
    ("Run backend tests",           tests),
]


def main() -> None:
    while True:
        print("\n" + "═" * 50)
        print("  Neo-Label — dev runner (docker compose)")
        print("═" * 50)
        for i, (label, _) in enumerate(MENU, 1):
            print(f"  {i}. {label}")
        print("  0. Quit")
        print("─" * 50)
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
        try:
            MENU[int(choice) - 1][1]()
        except KeyboardInterrupt:
            print()


if __name__ == "__main__":
    main()
