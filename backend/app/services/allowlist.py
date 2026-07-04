"""Email allowlist: who may sign in via Google, and with what role.

Read fresh from disk on every call (the file is tiny) so that removing an
email revokes access on the next login without a restart. Missing,
unreadable, or malformed/wrong-shape file -> empty allowlist (fail-closed:
nobody is authorized). load_allowlist() must never raise: it runs at app
startup and gates every login, so any failure degrades to an empty
allowlist instead of crashing the process.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

from app.core.config import settings

log = logging.getLogger("neolabel")


def _path() -> Path:
    p = Path(settings.ACCESS_ALLOWLIST_FILE)
    if not p.is_absolute():
        p = Path.cwd() / p
    return p


def load_allowlist() -> dict[str, dict]:
    path = _path()
    if not path.exists():
        log.warning("Allowlist not found at %s — denying all Google logins.", path)
        return {}
    try:
        entries = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError) as e:  # ValueError covers JSONDecodeError and UnicodeDecodeError
        log.error("Failed to read allowlist %s: %s — denying all Google logins.", path, e)
        return {}
    if not isinstance(entries, list):
        log.error("Allowlist %s is not a JSON list — denying all Google logins.", path)
        return {}
    result: dict[str, dict] = {}
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        email_raw = entry.get("email")
        if not isinstance(email_raw, str):
            continue
        email = email_raw.strip().lower()
        if not email:
            continue
        result[email] = {
            "email": email,
            "role": entry.get("role", "annotator"),
            "name": entry.get("name"),
        }
    return result


def lookup(email: str) -> dict | None:
    return load_allowlist().get(email.strip().lower())
