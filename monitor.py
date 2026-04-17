#!/usr/bin/env python3
"""Neo-Label prod monitoring menu (runs on the VPS).

Wraps the production compose stack (-p neo-label-prod, .env.prod,
docker-compose.prod.yml) so you can watch logs, restart, redeploy,
and sanity-check the app without memorizing the full compose flags.

Run on the VPS:
    python3 monitor.py
"""
from __future__ import annotations

import os
import shutil
import subprocess
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
PROJECT = "neo-label-prod"
ENV_FILE = ".env.prod"
COMPOSE_FILE = "docker-compose.prod.yml"
DEFAULT_URL = "https://neolabel.heltonmaia.com"


def _compose(*args: str, check: bool = False) -> int:
    cmd = ["docker", "compose", "-p", PROJECT, "--env-file", ENV_FILE, "-f", COMPOSE_FILE, *args]
    return subprocess.run(cmd, cwd=ROOT, check=check).returncode


def _env(key: str, default: str = "") -> str:
    path = ROOT / ENV_FILE
    if not path.exists():
        return default
    for line in path.read_text().splitlines():
        if line.startswith(f"{key}="):
            return line.split("=", 1)[1].strip()
    return default


def _http(url: str, timeout: float = 3.0) -> tuple[int | None, str]:
    try:
        with urllib.request.urlopen(url, timeout=timeout) as r:
            return r.status, ""
    except urllib.error.HTTPError as e:
        return e.code, ""
    except (urllib.error.URLError, TimeoutError, ConnectionError) as e:
        return None, str(e)


def status() -> None:
    _compose("ps")
    print()
    local_port = _env("FRONTEND_PORT", "8080")
    code, err = _http(f"http://127.0.0.1:{local_port}/")
    print(f"  local nginx (127.0.0.1:{local_port})  {code if code else 'down (' + err + ')'}")
    code, err = _http(f"{DEFAULT_URL}/")
    print(f"  public https                         {code if code else 'down (' + err + ')'}")
    code, err = _http(f"{DEFAULT_URL}/api/v1/auth/me")
    print(f"  api /auth/me                          {code if code else 'down (' + err + ')'} (401 expected)")


def logs_all() -> None:
    print("Following logs — Ctrl-C to return.")
    try:
        _compose("logs", "-f", "--tail=100")
    except KeyboardInterrupt:
        pass


def logs_backend() -> None:
    print("Following backend logs — Ctrl-C to return.")
    try:
        _compose("logs", "-f", "--tail=100", "backend")
    except KeyboardInterrupt:
        pass


def logs_frontend() -> None:
    print("Following frontend logs — Ctrl-C to return.")
    try:
        _compose("logs", "-f", "--tail=100", "frontend")
    except KeyboardInterrupt:
        pass


def recent_errors() -> None:
    print("Last ERROR/traceback lines in the backend (last 1000 log lines)...\n")
    cmd = (
        "docker compose -p {p} --env-file {e} -f {f} logs --tail=1000 backend "
        "| grep -E -i 'error|traceback|exception|permission' | tail -40"
    ).format(p=PROJECT, e=ENV_FILE, f=COMPOSE_FILE)
    subprocess.run(cmd, cwd=ROOT, shell=True)
    input("\nPress Enter to return... ")


def restart_all() -> None:
    _compose("restart")


def restart_backend() -> None:
    _compose("restart", "backend")


def redeploy() -> None:
    script = ROOT / "deploy.sh"
    if not script.exists():
        print(f"  deploy.sh not found at {script}")
        return
    subprocess.run(["bash", str(script)], cwd=ROOT, check=False)
    try:
        input("\nPress Enter to return... ")
    except (EOFError, KeyboardInterrupt):
        print()


def backend_shell() -> None:
    print("Opening a shell inside the backend container. Type 'exit' to leave.")
    _compose("exec", "backend", "bash")


def disk_usage() -> None:
    data_dir = _env("DATA_DIR", "/root/work/neo-label-data")
    print(f"  DATA_DIR = {data_dir}")
    if Path(data_dir).exists():
        subprocess.run(["du", "-sh", data_dir], check=False)
    else:
        print(f"  (does not exist)")
    print()
    print("  docker system df:")
    subprocess.run(["docker", "system", "df"], check=False)
    input("\nPress Enter to return... ")


MENU = [
    ("Status (ps + HTTP health)",   status),
    ("Logs — all services (follow)", logs_all),
    ("Logs — backend only",          logs_backend),
    ("Logs — frontend only",         logs_frontend),
    ("Recent errors (grep backend)", recent_errors),
    ("Restart both services",        restart_all),
    ("Restart backend only",         restart_backend),
    ("Redeploy (git pull + build)",  redeploy),
    ("Backend shell (bash)",         backend_shell),
    ("Disk usage (data + docker)",   disk_usage),
]


def main() -> None:
    if shutil.which("docker") is None:
        print("docker not on PATH"); return
    if not (ROOT / ENV_FILE).exists():
        print(f"missing {ENV_FILE} — run this on the VPS inside the repo")
        return
    while True:
        print("\n" + "═" * 50)
        print("  Neo-Label — prod monitor")
        print("═" * 50)
        for i, (label, _) in enumerate(MENU, 1):
            print(f"  {i:>2}. {label}")
        print("   0. Quit")
        print("─" * 50)
        try:
            choice = input("Choose: ").strip()
        except (EOFError, KeyboardInterrupt):
            print(); return
        if choice in {"0", "q", "quit", "exit"}:
            return
        if not choice.isdigit() or not (1 <= int(choice) <= len(MENU)):
            print(f"  invalid choice: {choice!r}"); continue
        try:
            MENU[int(choice) - 1][1]()
        except KeyboardInterrupt:
            print()


if __name__ == "__main__":
    main()
