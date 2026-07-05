# Emergency Email-Code Access Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the password break-glass with a Google-independent, email one-time-code emergency admin login.

**Architecture:** A new `services/emergency.py` owns the code lifecycle (generate → store hashed → verify → mint the normal admin JWT), delivering the code through a thin, mockable `services/email.py` that POSTs to the Resend HTTPS API. Two new endpoints under `/auth/emergency/*`, a new `/emergency` frontend page, and removal of the old password path. Codes live in one JSON file under `DATA_DIR`.

**Tech Stack:** FastAPI, Pydantic v2, filesystem JSON storage, `requests` (runtime dep) for Resend, slowapi rate limiting, React 18 + TypeScript + Vite.

**Spec:** `docs/superpowers/specs/2026-07-05-emergency-access-design.md`.

## Global Constraints

- Code format: **6-digit numeric**, zero-padded, generated with `secrets.randbelow(10**6)`.
- **Single-use**, TTL **10 min**, max **5** verify attempts, request **cooldown 60s** per email — all from settings (`EMERGENCY_CODE_TTL_MINUTES=10`, `EMERGENCY_CODE_MAX_ATTEMPTS=5`, `EMERGENCY_CODE_COOLDOWN_SECONDS=60`).
- Code stored **hashed** as `hmac_sha256(code, SECRET_KEY)` hex; verify uses `hmac.compare_digest`.
- **Only** `settings.EMERGENCY_ADMIN_EMAIL` (case-insensitive) is eligible; independent of `allowlist.json`.
- **No user enumeration:** `POST /auth/emergency/request` always returns `200 {"detail": "If that email is registered, a code has been sent."}`. Verify failures return `400 {"detail": "Invalid or expired code."}`.
- Delivery via **Resend** (`https://api.resend.com/emails`) using **`requests`** (already a runtime dep — do NOT add `httpx`, which is dev-only). `services/email.send_emergency_code` is monkeypatched in tests; **no test makes a network call**.
- Session on success = the existing JWT via `create_access_token(str(user.id))` (unchanged, 60 min).
- Frontend route **`/emergency`**, NOT linked from `/login`. Copy is active-voice, errors generic, matching the `neolabel-login-design` memory.
- The password break-glass is **fully removed** (`/auth/login`, `authenticate`, `upsert_password_admin`, `BREAKGLASS_ADMIN_EMAIL`, `BREAKGLASS_ADMIN_PASSWORD`, frontend admin form).
- ruff line-length 100. Run `ruff check backend` on changed files only; **do NOT run `ruff format`** (it reformats unrelated functions in the same file).
- Backend tests: `docker compose exec -T backend python -m pytest <path> -v`. If the dev container lacks pytest, once: `docker compose exec -T backend uv pip install --system pytest pytest-asyncio httpx requests google-auth`. Every test isolates `DATA_DIR` (autouse `_isolated_data_dir`) and rate limiting is disabled (autouse `_disable_rate_limit`).
- Frontend gate: `docker compose exec -T frontend npx tsc -b --noEmit` (no frontend test suite).

## File Structure

**Create (backend):**
- `backend/app/services/email.py` — `send_emergency_code(to, code)` → Resend. Mockable.
- `backend/app/services/emergency.py` — `request_code(email)`, `verify_code(email, code)`.
- `backend/tests/test_email_service.py`, `backend/tests/test_emergency_service.py`, `backend/tests/test_emergency_api.py`.

**Create (frontend):**
- `frontend/src/pages/EmergencyAccessPage.tsx`.

**Modify (backend):**
- `app/core/config.py` (add EMERGENCY_* settings; later remove BREAKGLASS_*).
- `app/core/storage.py` (emergency-code load/save/delete).
- `app/core/security.py` (`hash_emergency_code`).
- `app/schemas/user.py` (`EmergencyCodeRequest`, `EmergencyCodeVerify`).
- `app/api/v1/auth.py` (add `/emergency/*`; later remove `/login`).
- `app/services/user.py` (later remove `authenticate`, `upsert_password_admin`, simplify `get_or_provision_google_user`).
- `app/main.py` (later remove break-glass seeding).

**Modify (frontend):**
- `src/api/auth.ts`, `src/App.tsx`, `src/pages/LoginPage.tsx`.

**Modify (tests, Task 7):** `test_auth_api.py`, `test_user_service.py`, `test_startup_seed.py`, `test_config_settings.py`, `test_user_provisioning.py`.

**Modify (docs, Task 8):** `SPEC.md`, `CLAUDE.md`, `CLAUDE.local.md`, memory.

---

### Task 1: Config — emergency settings

**Files:**
- Modify: `backend/app/core/config.py`
- Test: `backend/tests/test_config_settings.py`

**Interfaces:**
- Produces: `settings.RESEND_API_KEY: str`, `settings.EMAIL_FROM: str`, `settings.EMERGENCY_ADMIN_EMAIL: str`, `settings.EMERGENCY_CODE_TTL_MINUTES: int`, `settings.EMERGENCY_CODE_MAX_ATTEMPTS: int`, `settings.EMERGENCY_CODE_COOLDOWN_SECONDS: int`.

- [ ] **Step 1: Write the failing test** — append to `test_config_settings.py`:

```python
def test_emergency_settings_defaults():
    from app.core.config import Settings

    s = Settings()
    assert s.EMERGENCY_ADMIN_EMAIL == ""
    assert s.RESEND_API_KEY == ""
    assert s.EMAIL_FROM == ""
    assert s.EMERGENCY_CODE_TTL_MINUTES == 10
    assert s.EMERGENCY_CODE_MAX_ATTEMPTS == 5
    assert s.EMERGENCY_CODE_COOLDOWN_SECONDS == 60
```

- [ ] **Step 2: Run it — expect FAIL** (AttributeError on the new fields)

Run: `docker compose exec -T backend python -m pytest tests/test_config_settings.py::test_emergency_settings_defaults -v`

- [ ] **Step 3: Add the settings** — in `config.py`, after the `BREAKGLASS_*` lines (line 20), add:

```python
    # Emergency email-code access (break-glass v2). BREAKGLASS_* above are
    # removed in a later task once the password path is gone.
    RESEND_API_KEY: str = ""
    EMAIL_FROM: str = ""
    EMERGENCY_ADMIN_EMAIL: str = ""
    EMERGENCY_CODE_TTL_MINUTES: int = 10
    EMERGENCY_CODE_MAX_ATTEMPTS: int = 5
    EMERGENCY_CODE_COOLDOWN_SECONDS: int = 60
```

- [ ] **Step 4: Run it — expect PASS**

Run: `docker compose exec -T backend python -m pytest tests/test_config_settings.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/config.py backend/tests/test_config_settings.py
git commit -m "feat(config): add emergency email-code settings"
```

---

### Task 2: Storage — emergency-code file

**Files:**
- Modify: `backend/app/core/storage.py`
- Test: `backend/tests/test_storage.py`

**Interfaces:**
- Produces: `storage.load_emergency_code() -> dict | None`, `storage.save_emergency_code(data: dict) -> None`, `storage.delete_emergency_code() -> None`. File: `<DATA_DIR>/emergency_code.json`.

- [ ] **Step 1: Write the failing test** — append to `test_storage.py`:

```python
def test_emergency_code_roundtrip_and_delete():
    from app.core import storage

    assert storage.load_emergency_code() is None
    storage.save_emergency_code({"email": "a@b.com", "attempts": 0})
    assert storage.load_emergency_code() == {"email": "a@b.com", "attempts": 0}
    storage.delete_emergency_code()
    assert storage.load_emergency_code() is None
    storage.delete_emergency_code()  # idempotent, no error
```

- [ ] **Step 2: Run it — expect FAIL**

Run: `docker compose exec -T backend python -m pytest tests/test_storage.py::test_emergency_code_roundtrip_and_delete -v`

- [ ] **Step 3: Implement** — in `storage.py`, after the users section (after line 83), add:

```python
# ---------- emergency code ----------

_EMERGENCY_CODE_FILE = lambda: _root() / "emergency_code.json"  # noqa: E731


def load_emergency_code() -> dict | None:
    return _read_json(_EMERGENCY_CODE_FILE(), None)


def save_emergency_code(data: dict) -> None:
    _write_json(_EMERGENCY_CODE_FILE(), data)


def delete_emergency_code() -> None:
    f = _EMERGENCY_CODE_FILE()
    if f.exists():
        f.unlink()
```

- [ ] **Step 4: Run it — expect PASS**

Run: `docker compose exec -T backend python -m pytest tests/test_storage.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/storage.py backend/tests/test_storage.py
git commit -m "feat(storage): emergency-code load/save/delete"
```

---

### Task 3: Email service — Resend delivery

**Files:**
- Create: `backend/app/services/email.py`
- Test: `backend/tests/test_email_service.py`

**Interfaces:**
- Produces: `email.send_emergency_code(to: str, code: str) -> None` (raises on transport error).

- [ ] **Step 1: Write the failing test** — new file `tests/test_email_service.py`:

```python
def test_send_emergency_code_posts_to_resend(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(settings, "EMAIL_FROM", "NeoLabel <x@y.com>")

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            return None

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return FakeResp()

    monkeypatch.setattr("app.services.email.requests.post", fake_post)

    from app.services.email import send_emergency_code

    send_emergency_code("owner@example.com", "123456")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer re_test"
    assert captured["json"]["from"] == "NeoLabel <x@y.com>"
    assert captured["json"]["to"] == ["owner@example.com"]
    assert "123456" in captured["json"]["text"]
```

- [ ] **Step 2: Run it — expect FAIL** (module does not exist)

Run: `docker compose exec -T backend python -m pytest tests/test_email_service.py -v`

- [ ] **Step 3: Implement** — new file `app/services/email.py`:

```python
"""Transactional email via Resend (HTTPS API).

Thin + mockable: tests monkeypatch `send_emergency_code`, so no network call
happens in the suite. Resend (not SMTP) because the Contabo VPS blocks
outbound SMTP ports.
"""
from __future__ import annotations

import logging

import requests

from app.core.config import settings

log = logging.getLogger("neolabel")

_RESEND_ENDPOINT = "https://api.resend.com/emails"


def send_emergency_code(to: str, code: str) -> None:
    """Email a one-time access code. Raises on transport failure; the caller
    decides whether to surface or swallow it."""
    resp = requests.post(
        _RESEND_ENDPOINT,
        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        json={
            "from": settings.EMAIL_FROM,
            "to": [to],
            "subject": "Your NeoLabel access code",
            "text": (
                f"Your one-time NeoLabel access code is {code}.\n"
                f"It expires in {settings.EMERGENCY_CODE_TTL_MINUTES} minutes.\n"
                "If you didn't request this, you can ignore this email."
            ),
        },
        timeout=10,
    )
    resp.raise_for_status()
```

- [ ] **Step 4: Run it — expect PASS**

Run: `docker compose exec -T backend python -m pytest tests/test_email_service.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/services/email.py backend/tests/test_email_service.py
git commit -m "feat(email): Resend transactional email service"
```

---

### Task 4: Emergency service — code lifecycle

**Files:**
- Modify: `backend/app/core/security.py` (add `hash_emergency_code`)
- Create: `backend/app/services/emergency.py`
- Test: `backend/tests/test_emergency_service.py`

**Interfaces:**
- Consumes: `storage.load/save/delete_emergency_code`, `security.hash_emergency_code`, `email.send_emergency_code`, `user_service.get_or_provision_google_user(email, name, google_sub, role)`, `settings.EMERGENCY_*`.
- Produces: `security.hash_emergency_code(code: str) -> str`; `emergency.request_code(email: str) -> None`; `emergency.verify_code(email: str, code: str) -> UserRecord | None`.

- [ ] **Step 1: Write the failing tests** — new file `tests/test_emergency_service.py`:

```python
import pytest

from app.core.config import settings


@pytest.fixture
def admin_email(monkeypatch):
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_EMAIL", "owner@example.com")
    return "owner@example.com"


@pytest.fixture
def capture_code(monkeypatch):
    """Capture the code the service tries to email."""
    box = {}

    def fake_send(to, code):
        box["to"] = to
        box["code"] = code

    monkeypatch.setattr("app.services.emergency.email_service.send_emergency_code", fake_send)
    return box


def test_request_code_non_admin_is_noop(monkeypatch, capture_code):
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_EMAIL", "owner@example.com")
    from app.core import storage
    from app.services import emergency

    emergency.request_code("intruder@example.com")
    assert storage.load_emergency_code() is None
    assert "code" not in capture_code


def test_request_code_admin_stores_and_sends(admin_email, capture_code):
    from app.core import storage
    from app.services import emergency

    emergency.request_code("Owner@Example.com")  # case-insensitive
    stored = storage.load_emergency_code()
    assert stored is not None and stored["attempts"] == 0
    assert capture_code["to"] == admin_email
    assert len(capture_code["code"]) == 6 and capture_code["code"].isdigit()


def test_request_code_within_cooldown_does_not_resend(admin_email, capture_code):
    from app.services import emergency

    emergency.request_code(admin_email)
    first = capture_code["code"]
    capture_code.clear()
    emergency.request_code(admin_email)  # immediate second call
    assert "code" not in capture_code  # cooldown → no new send


def test_verify_success_returns_admin_and_burns(admin_email, capture_code):
    from app.core import storage
    from app.core.security import decode_token, create_access_token  # noqa: F401
    from app.services import emergency

    emergency.request_code(admin_email)
    user = emergency.verify_code(admin_email, capture_code["code"])
    assert user is not None and user.role.value == "admin"
    assert storage.load_emergency_code() is None  # single-use burned


def test_verify_wrong_code_counts_attempt(admin_email, capture_code):
    from app.core import storage
    from app.services import emergency

    emergency.request_code(admin_email)
    assert emergency.verify_code(admin_email, "000000") is None
    assert storage.load_emergency_code()["attempts"] == 1


def test_verify_burns_after_max_attempts(admin_email, capture_code, monkeypatch):
    monkeypatch.setattr(settings, "EMERGENCY_CODE_MAX_ATTEMPTS", 2)
    from app.core import storage
    from app.services import emergency

    emergency.request_code(admin_email)
    emergency.verify_code(admin_email, "000000")
    emergency.verify_code(admin_email, "000000")  # hits max
    assert storage.load_emergency_code() is None
    # even the real code now fails (burned)
    assert emergency.verify_code(admin_email, capture_code["code"]) is None


def test_verify_expired_code_fails(admin_email, capture_code, monkeypatch):
    monkeypatch.setattr(settings, "EMERGENCY_CODE_TTL_MINUTES", 0)
    from app.core import storage
    from app.services import emergency

    emergency.request_code(admin_email)
    assert emergency.verify_code(admin_email, capture_code["code"]) is None
    assert storage.load_emergency_code() is None
```

- [ ] **Step 2: Run — expect FAIL** (module/function missing)

Run: `docker compose exec -T backend python -m pytest tests/test_emergency_service.py -v`

- [ ] **Step 3a: Add the hash helper** — in `security.py`, add imports `import hashlib`, `import hmac` at the top, then:

```python
def hash_emergency_code(code: str) -> str:
    """HMAC-SHA256 of a one-time code, keyed by SECRET_KEY, hex-encoded. A
    leaked code file can't be brute-forced without the key."""
    return hmac.new(
        settings.SECRET_KEY.encode("utf-8"), code.encode("utf-8"), hashlib.sha256
    ).hexdigest()
```

- [ ] **Step 3b: Implement the service** — new file `app/services/emergency.py`:

```python
"""Emergency email-code access (break-glass v2).

Only settings.EMERGENCY_ADMIN_EMAIL is eligible. A 6-digit, single-use,
short-lived code is emailed (via services.email) and verified here; success
mints a normal admin session. Independent of Google and of allowlist.json.
"""
from __future__ import annotations

import hmac
import logging
import secrets
from datetime import datetime, timedelta, timezone

from app.core import storage
from app.core.config import settings
from app.core.security import hash_emergency_code
from app.schemas.user import UserRecord, UserRole
from app.services import email as email_service
from app.services import user as user_service

log = logging.getLogger("neolabel")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _is_admin_email(email: str) -> bool:
    admin = (settings.EMERGENCY_ADMIN_EMAIL or "").strip().lower()
    return bool(admin) and (email or "").strip().lower() == admin


def request_code(email: str) -> None:
    """If `email` is the emergency admin and no fresh code is within the
    cooldown window, generate + store + email a new 6-digit code. Returns
    nothing so the endpoint responds identically for any email."""
    if not _is_admin_email(email):
        return
    existing = storage.load_emergency_code()
    if existing:
        created = datetime.fromisoformat(existing["created_at"])
        if _now() - created < timedelta(seconds=settings.EMERGENCY_CODE_COOLDOWN_SECONDS):
            return
    admin = settings.EMERGENCY_ADMIN_EMAIL.strip().lower()
    code = f"{secrets.randbelow(10**6):06d}"
    storage.save_emergency_code(
        {
            "email": admin,
            "code_hash": hash_emergency_code(code),
            "expires_at": (
                _now() + timedelta(minutes=settings.EMERGENCY_CODE_TTL_MINUTES)
            ).isoformat(),
            "attempts": 0,
            "created_at": _now().isoformat(),
        }
    )
    try:
        email_service.send_emergency_code(admin, code)
    except Exception:  # noqa: BLE001 - never leak send status to the caller
        log.exception("emergency code: failed to send email")


def verify_code(email: str, code: str) -> UserRecord | None:
    """Validate a submitted code. On success burn it and return the admin
    user (provisioned if needed). On failure count the attempt and burn the
    code once attempts are exhausted. Returns None on any failure."""
    stored = storage.load_emergency_code()
    if not stored or not _is_admin_email(email):
        return None
    if _now() >= datetime.fromisoformat(stored["expires_at"]):
        storage.delete_emergency_code()
        return None
    if stored.get("attempts", 0) >= settings.EMERGENCY_CODE_MAX_ATTEMPTS:
        storage.delete_emergency_code()
        return None
    if hmac.compare_digest(stored["code_hash"], hash_emergency_code(code)):
        storage.delete_emergency_code()
        return user_service.get_or_provision_google_user(
            email=settings.EMERGENCY_ADMIN_EMAIL.strip().lower(),
            name=None,
            google_sub=None,
            role=UserRole.admin,
        )
    stored["attempts"] = stored.get("attempts", 0) + 1
    if stored["attempts"] >= settings.EMERGENCY_CODE_MAX_ATTEMPTS:
        storage.delete_emergency_code()
    else:
        storage.save_emergency_code(stored)
    return None
```

- [ ] **Step 4: Run — expect PASS**

Run: `docker compose exec -T backend python -m pytest tests/test_emergency_service.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/core/security.py backend/app/services/emergency.py backend/tests/test_emergency_service.py
git commit -m "feat(emergency): code generate/verify service"
```

---

### Task 5: API — request & verify endpoints

**Files:**
- Modify: `backend/app/schemas/user.py`
- Modify: `backend/app/api/v1/auth.py`
- Test: `backend/tests/test_emergency_api.py`

**Interfaces:**
- Consumes: `emergency.request_code`, `emergency.verify_code`, `create_access_token`, `Token`.
- Produces: `POST /api/v1/auth/emergency/request` `{email}` → `200 {"detail"}`; `POST /api/v1/auth/emergency/verify` `{email, code}` → `200 Token` / `400`. Schemas `EmergencyCodeRequest{email: str}`, `EmergencyCodeVerify{email: str, code: str}`.

- [ ] **Step 1: Write the failing test** — new file `tests/test_emergency_api.py`:

```python
import pytest

from app.core.config import settings
from app.core.security import decode_token


@pytest.fixture
def admin_email(monkeypatch):
    monkeypatch.setattr(settings, "EMERGENCY_ADMIN_EMAIL", "owner@example.com")
    return "owner@example.com"


@pytest.fixture
def capture_code(monkeypatch):
    box = {}
    monkeypatch.setattr(
        "app.services.emergency.email_service.send_emergency_code",
        lambda to, code: box.update(to=to, code=code),
    )
    return box


def test_request_always_generic(client, admin_email, capture_code):
    r1 = client.post("/api/v1/auth/emergency/request", json={"email": admin_email})
    r2 = client.post("/api/v1/auth/emergency/request", json={"email": "nope@example.com"})
    assert r1.status_code == r2.status_code == 200
    assert r1.json() == r2.json() == {"detail": "If that email is registered, a code has been sent."}


def test_full_login_flow(client, admin_email, capture_code):
    client.post("/api/v1/auth/emergency/request", json={"email": admin_email})
    r = client.post(
        "/api/v1/auth/emergency/verify",
        json={"email": admin_email, "code": capture_code["code"]},
    )
    assert r.status_code == 200
    token = r.json()["access_token"]
    assert decode_token(token) is not None  # a valid session

    me = client.get("/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"})
    assert me.status_code == 200 and me.json()["role"] == "admin"


def test_verify_wrong_code_is_400(client, admin_email, capture_code):
    client.post("/api/v1/auth/emergency/request", json={"email": admin_email})
    r = client.post(
        "/api/v1/auth/emergency/verify", json={"email": admin_email, "code": "000000"}
    )
    assert r.status_code == 400


def test_non_admin_cannot_get_code(client, admin_email, capture_code):
    client.post("/api/v1/auth/emergency/request", json={"email": "nope@example.com"})
    assert "code" not in capture_code  # nothing was generated/sent
```

- [ ] **Step 2: Run — expect FAIL** (404 / schema missing)

Run: `docker compose exec -T backend python -m pytest tests/test_emergency_api.py -v`

- [ ] **Step 3a: Add schemas** — in `schemas/user.py`, after `GoogleLogin` (line 46):

```python
class EmergencyCodeRequest(BaseModel):
    email: str


class EmergencyCodeVerify(BaseModel):
    email: str
    code: str = Field(min_length=1, max_length=12)
```

- [ ] **Step 3b: Add endpoints** — in `auth.py`: extend the schemas import to include `EmergencyCodeRequest, EmergencyCodeVerify`, add `from app.services import emergency as emergency_service`, and append:

```python
_GENERIC_REQUEST_MSG = "If that email is registered, a code has been sent."


@router.post("/emergency/request")
@limiter.limit("5/minute")
def emergency_request(request: Request, body: EmergencyCodeRequest) -> dict[str, str]:
    emergency_service.request_code(body.email)
    return {"detail": _GENERIC_REQUEST_MSG}


@router.post("/emergency/verify", response_model=Token)
@limiter.limit("10/minute")
def emergency_verify(request: Request, body: EmergencyCodeVerify) -> Token:
    user = emergency_service.verify_code(body.email, body.code)
    if not user:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "Invalid or expired code.")
    return Token(access_token=create_access_token(str(user.id)))
```

- [ ] **Step 4: Run — expect PASS**

Run: `docker compose exec -T backend python -m pytest tests/test_emergency_api.py -v`

- [ ] **Step 5: Commit**

```bash
git add backend/app/schemas/user.py backend/app/api/v1/auth.py backend/tests/test_emergency_api.py
git commit -m "feat(auth): emergency /request and /verify endpoints"
```

---

### Task 6: Frontend — emergency page + login cleanup

**Files:**
- Modify: `frontend/src/api/auth.ts`
- Create: `frontend/src/pages/EmergencyAccessPage.tsx`
- Modify: `frontend/src/App.tsx`
- Modify: `frontend/src/pages/LoginPage.tsx`

**Interfaces:**
- Consumes: `useAuth.setToken`, `api` client.
- Produces: route `/emergency`; `requestEmergencyCode(email)`, `verifyEmergencyCode(email, code)`. Removes `login()` and the LoginPage admin form.

- [ ] **Step 1: API module** — in `src/api/auth.ts`, delete the `login` function (lines 11-21) and add:

```typescript
export async function requestEmergencyCode(email: string) {
  const { data } = await api.post<{ detail: string }>('/auth/emergency/request', { email });
  return data;
}

export async function verifyEmergencyCode(email: string, code: string) {
  const { data } = await api.post<{ access_token: string; token_type: string }>(
    '/auth/emergency/verify',
    { email, code },
  );
  return data;
}
```

- [ ] **Step 2: Emergency page** — new file `src/pages/EmergencyAccessPage.tsx`:

```tsx
import { useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { requestEmergencyCode, verifyEmergencyCode } from '@/api/auth';
import { useAuth } from '@/stores/auth';

export default function EmergencyAccessPage() {
  const setToken = useAuth((s) => s.setToken);
  const navigate = useNavigate();
  const [step, setStep] = useState<'email' | 'code'>('email');
  const [email, setEmail] = useState('');
  const [code, setCode] = useState('');
  const [notice, setNotice] = useState<string | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [loading, setLoading] = useState(false);

  async function sendCode(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { detail } = await requestEmergencyCode(email);
      setNotice(detail);
      setStep('code');
    } catch {
      setError('Could not send a code. Try again.');
    } finally {
      setLoading(false);
    }
  }

  async function submitCode(e: React.FormEvent) {
    e.preventDefault();
    setError(null);
    setLoading(true);
    try {
      const { access_token } = await verifyEmergencyCode(email, code);
      setToken(access_token);
      navigate('/projects');
    } catch {
      setError('Invalid or expired code.');
    } finally {
      setLoading(false);
    }
  }

  return (
    <main className="flex min-h-full items-center justify-center bg-white px-6 py-10">
      <div className="w-full max-w-[340px]">
        <h1 className="text-xl font-semibold tracking-tight text-slate-900">Emergency access</h1>
        <p className="mt-2 text-sm text-slate-500">
          Enter your admin email and we'll send a one-time code.
        </p>

        {step === 'email' ? (
          <form onSubmit={sendCode} className="mt-7 space-y-3">
            <input
              type="email"
              autoComplete="email"
              required
              value={email}
              onChange={(e) => setEmail(e.target.value)}
              placeholder="you@example.com"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
            />
            <button
              disabled={loading}
              className="w-full rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-800 disabled:opacity-60"
            >
              {loading ? 'Sending…' : 'Send code'}
            </button>
          </form>
        ) : (
          <form onSubmit={submitCode} className="mt-7 space-y-3">
            {notice && <p className="text-sm text-slate-500">{notice}</p>}
            <input
              inputMode="numeric"
              autoComplete="one-time-code"
              required
              value={code}
              onChange={(e) => setCode(e.target.value)}
              placeholder="6-digit code"
              className="w-full rounded-lg border border-slate-300 px-3 py-2 text-sm tracking-widest focus:border-blue-500 focus:outline-none focus:ring-2 focus:ring-blue-500/30"
            />
            <button
              disabled={loading}
              className="w-full rounded-lg bg-slate-900 py-2.5 text-sm font-medium text-white transition-colors hover:bg-slate-800 disabled:opacity-60"
            >
              {loading ? 'Verifying…' : 'Verify'}
            </button>
          </form>
        )}

        {error && (
          <p className="mt-4 text-sm text-red-600" role="alert">
            {error}
          </p>
        )}
      </div>
    </main>
  );
}
```

- [ ] **Step 3: Route** — in `src/App.tsx`, add the import `import EmergencyAccessPage from '@/pages/EmergencyAccessPage';` and, after the `/login` route (line 16):

```tsx
      <Route path="/emergency" element={<EmergencyAccessPage />} />
```

- [ ] **Step 4: Strip the admin form from LoginPage** — in `src/pages/LoginPage.tsx`: remove the `useForm` import, the `login` import, the `Form` interface, `register`/`handleSubmit`, `onSubmit`, the `showAdmin`/`loading` state that only served the form, and the entire `{error && …}` admin-toggle-and-form block (the `<button onClick={() => setShowAdmin…}>` through the closing `</form>`) plus the "Admin" divider. Keep the Google button, the `onGoogle` handler, and the `error` display for Google failures. The card ends after the Google button + error line.

- [ ] **Step 5: Typecheck — expect PASS**

Run: `docker compose exec -T frontend npx tsc -b --noEmit`

- [ ] **Step 6: Commit**

```bash
git add frontend/src/api/auth.ts frontend/src/pages/EmergencyAccessPage.tsx frontend/src/App.tsx frontend/src/pages/LoginPage.tsx
git commit -m "feat(login): emergency-access page; drop the admin password form"
```

---

### Task 7: Remove the password break-glass (backend)

**Files:**
- Modify: `backend/app/services/user.py`, `backend/app/api/v1/auth.py`, `backend/app/main.py`, `backend/app/core/config.py`
- Modify tests: `tests/test_auth_api.py`, `tests/test_user_service.py`, `tests/test_startup_seed.py`, `tests/test_config_settings.py`, `tests/test_user_provisioning.py`

**Interfaces:**
- Removes: `user_service.authenticate`, `user_service.upsert_password_admin`, `POST /auth/login`, `settings.BREAKGLASS_ADMIN_EMAIL`, `settings.BREAKGLASS_ADMIN_PASSWORD`. `get_or_provision_google_user` keeps its signature but always syncs role.

- [ ] **Step 1: Delete obsolete tests first** — find and remove every test exercising the password path so they don't false-fail mid-refactor:

Run: `docker compose exec -T backend grep -rln "auth/login\|authenticate\|upsert_password_admin\|BREAKGLASS" tests/`

Delete the test functions that call `/auth/login`, `user_service.authenticate`, `user_service.upsert_password_admin`, or assert on `BREAKGLASS_*` settings / break-glass startup seeding. In `test_config_settings.py` remove only the `BREAKGLASS_*` assertions (keep the file). In `test_user_provisioning.py` remove the test asserting the break-glass role is not downgraded (that behavior is going away).

- [ ] **Step 2: Simplify `get_or_provision_google_user`** — in `user.py`, drop the break-glass carve-out. Replace lines 86-100 so it always syncs role:

```python
    users = storage.load_users()
    target = email.strip().lower()
    existing = _find_by_email(users, email)
    if existing:
        changed = False
        if existing.get("role") != role.value:
            existing["role"] = role.value
            changed = True
        if google_sub and existing.get("google_sub") != google_sub:
            existing["google_sub"] = google_sub
            changed = True
        if changed:
            storage.save_users(users)
        return _to_record(existing)
```

- [ ] **Step 3: Remove `authenticate` and `upsert_password_admin`** from `user.py` entirely (lines 107-150). Remove the now-unused `verify_password` import if nothing else uses it (`grep -n verify_password app/services/user.py`).

- [ ] **Step 4: Remove `/auth/login`** — in `auth.py`, delete the `login` endpoint (lines 21-31) and the `from fastapi.security import OAuth2PasswordRequestForm` import (and `Annotated` if now unused).

- [ ] **Step 5: Remove break-glass seeding** — in `main.py`, delete the `if settings.BREAKGLASS_ADMIN_EMAIL and settings.BREAKGLASS_ADMIN_PASSWORD:` block (lines 32-37) from `seed_users()`.

- [ ] **Step 6: Remove config fields** — in `config.py`, delete `BREAKGLASS_ADMIN_EMAIL` and `BREAKGLASS_ADMIN_PASSWORD` (lines 18-20) and the comment on line 18.

- [ ] **Step 7: Run the whole suite — expect PASS**

Run: `docker compose exec -T backend python -m pytest -q`
Then: `ruff check backend/app`

If any test references a removed symbol, delete/adjust that test (it was testing removed behavior). Do not re-introduce the password path to satisfy a stale test.

- [ ] **Step 8: Commit**

```bash
git add backend/app/services/user.py backend/app/api/v1/auth.py backend/app/main.py backend/app/core/config.py backend/tests/
git commit -m "refactor(auth): remove the password break-glass (replaced by email code)"
```

---

### Task 8: Docs

**Files:**
- Modify: `SPEC.md`, `CLAUDE.md`, `CLAUDE.local.md`, and memory `neolabel-prod-google-auth-no-breakglass`.

- [ ] **Step 1: SPEC.md** — read it, find the auth section describing the break-glass password, and replace it with the emergency email-code flow: the two endpoints, the on-disk `emergency_code.json` shape, the security properties (6-digit, 10-min, single-use, 5 attempts, 60s cooldown, HMAC-stored, no enumeration, single `EMERGENCY_ADMIN_EMAIL`), Resend delivery, and that `/auth/login` + the password admin are removed. Per repo convention, SPEC is the source of truth — keep it exact.

- [ ] **Step 2: CLAUDE.md** — update the auth pointers: `auth.py` now hosts `/auth/emergency/request` + `/auth/emergency/verify` (no `/auth/login`); new `services/email.py` (Resend, mockable) and `services/emergency.py`; note the removed password break-glass in the footguns section; note `requests` (not httpx) is the runtime HTTP client.

- [ ] **Step 3: CLAUDE.local.md** — under the VPS section, document the emergency-access prod setup: `RESEND_API_KEY`, `EMAIL_FROM`, `EMERGENCY_ADMIN_EMAIL` in `.env.prod`; the Resend sending-domain DNS (SPF/DKIM at the hello.co panel for `heltonmaia.com`); and the smoke test (`/emergency` → receive code → verify) as a post-deploy step. Note `BREAKGLASS_*` are gone.

- [ ] **Step 4: Memory** — update `~/.claude/.../memory/project_prod_google_auth_deploy.md` (`neolabel-prod-google-auth-no-breakglass`): the break-glass is no longer a TODO — it's the email-code flow; note prod still needs the Resend key + domain + `EMERGENCY_ADMIN_EMAIL` set before it's live.

- [ ] **Step 5: Commit**

```bash
git add SPEC.md CLAUDE.md CLAUDE.local.md
git commit -m "docs: emergency email-code access replaces the password break-glass"
```

---

## Deploy (after all tasks, done by the owner)

1. Create a **Resend** account + API key; verify the `heltonmaia.com` sending domain (SPF/DKIM DNS at hello.co).
2. Set `RESEND_API_KEY`, `EMAIL_FROM` (e.g. `NeoLabel <noreply@neolabel.heltonmaia.com>`), `EMERGENCY_ADMIN_EMAIL` in `/root/work/neo-label/.env.prod`.
3. `git push origin main`, then on the VPS `./scripts/deploy.sh`.
4. **Verify end-to-end**: open `/emergency`, request a code, confirm it arrives, log in with it — before relying on it.
```
