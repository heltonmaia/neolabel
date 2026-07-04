# Google Sign-In with email allowlist — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace username/password login with Google Sign-In gated by a server-side email allowlist, keeping one break-glass password admin, without changing the session/JWT layer.

**Architecture:** The browser uses Google Identity Services to obtain a signed ID token; a new `POST /auth/google` verifies it, checks the email against an allowlist file, provisions/looks-up the user, and mints the **existing** session JWT. `POST /auth/login` stays but only works for accounts that have a password (the env-seeded break-glass admin). Users are keyed by numeric `id` everywhere, so nothing downstream changes.

**Tech Stack:** Python 3.12 · FastAPI · Pydantic v2 · `google-auth` (backend token verification) · React 18 + TypeScript + Vite · `@react-oauth/google` (frontend button) · filesystem JSON storage.

**Design spec:** `docs/superpowers/specs/2026-07-04-google-auth-design.md`

## Global Constraints

- **No client secret anywhere** — GIS ID-token flow uses only the public `GOOGLE_CLIENT_ID`.
- **Preserve user `id`s** — never renumber existing users; `owner_id`/`assigned_to`/annotation files depend on them.
- **Fail-closed authorization** — if the allowlist file is missing/unreadable, deny all Google logins (return `{}`); the break-glass admin (seeded from env) must still work.
- **Commit messages:** scoped Conventional Commits (`feat(auth):`, `test(auth):`, `chore:`, `docs:`). **Do NOT add a `Co-Authored-By` trailer** (repo preference).
- **`CLAUDE.md` and `CLAUDE.local.md` are git-ignored** — edit them locally but never `git add` them. `SPEC.md`, `README.md`, and everything under `docs/` and `backend/`/`frontend/` ARE tracked.
- **`allowlist.json`, `.env`, `seed_users.json` stay git-ignored.** Only `*.example.*` files are committed.
- **Backend lint:** `ruff` with `line-length = 100`. Run `ruff format backend && ruff check backend` before each backend commit.
- **Tests run inside the backend container** (per CLAUDE.md). Start the stack with the non-colliding port: `BACKEND_PORT=8010 docker compose up -d`, then `docker compose exec backend pytest ...`. (Native fallback: activate `/mnt/hd3/uv-common/uv-neo-label` and run `pytest` from `backend/`.)
- **Frontend has no test suite** — the only gate is `cd frontend && npx tsc -b --noEmit` (must be clean). Do not run `npm run lint` (broken in this checkout).
- **Rebuilds:** changing `pyproject.toml` requires `docker compose up -d --build backend`; changing `frontend/package.json` requires `npm install` (for local typecheck) and a frontend container rebuild for runtime.

---

## File Structure

**Backend — create:**
- `backend/app/services/allowlist.py` — load + look up the email allowlist (fresh read per call).
- `backend/app/services/google_auth.py` — thin, mockable wrapper around Google ID-token verification.
- `backend/scripts/reconcile_users.py` — prune users no longer in the allowlist (replaces `reconcile_seed_users.py`).
- `backend/tests/test_allowlist.py`, `test_google_auth_service.py`, `test_user_provisioning.py`, `test_google_auth_api.py`, `test_startup_seed.py`.

**Backend — modify:**
- `backend/pyproject.toml` — add `google-auth`.
- `backend/app/core/config.py` — new settings; remove `SEED_USERS_FILE`.
- `backend/app/schemas/user.py` — `email`/`google_sub`, optional `hashed_password`, `GoogleLogin`.
- `backend/app/services/user.py` — `get_by_email`, `get_or_provision_google_user` (passwordless, via a private `_new_record` helper), `upsert_password_admin`, email-or-username `authenticate` (existing `create`/`ensure_seed_user`/`upsert_seed_user` untouched — conftest fixtures still rely on them).
- `backend/app/api/v1/auth.py` — `POST /auth/google`.
- `backend/app/main.py` — rewrite the startup seeder.

**Backend — delete:**
- `backend/scripts/reconcile_seed_users.py`.

**Frontend — modify:**
- `frontend/package.json` — add `@react-oauth/google`.
- `frontend/src/lib/env.ts` — export `GOOGLE_CLIENT_ID`.
- `frontend/src/main.tsx` — wrap in `GoogleOAuthProvider`.
- `frontend/src/api/auth.ts` — `loginWithGoogle`; `email` on `User`.
- `frontend/src/pages/LoginPage.tsx` — Google button + break-glass toggle.

**Repo root — modify/create:**
- `.gitignore` — add `allowlist.json`.
- `.env.example`, `.env.prod.example` — new vars.
- `allowlist.example.json` — new (committed); `seed_users.example.json` deleted.

**Docs:** `SPEC.md`, `README.md` (tracked); `CLAUDE.md`, `CLAUDE.local.md` (local-only).

---

## Task 1: Config + `google-auth` dependency

**Files:**
- Modify: `backend/pyproject.toml:6-15`
- Modify: `backend/app/core/config.py:4-16`
- Test: `backend/tests/test_config_settings.py` (create)

**Interfaces:**
- Produces: `settings.GOOGLE_CLIENT_ID`, `settings.ACCESS_ALLOWLIST_FILE`, `settings.BREAKGLASS_ADMIN_EMAIL`, `settings.BREAKGLASS_ADMIN_PASSWORD` (all `str`, default `""` except the allowlist path default `"../allowlist.json"`). `SEED_USERS_FILE` is intentionally **kept** for now — its only consumer (`main.py`) is rewritten in Task 7, which removes the field then. Removing it here would `AttributeError` on container startup.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_config_settings.py`:

```python
from app.core.config import settings


def test_new_auth_settings_exist():
    assert hasattr(settings, "GOOGLE_CLIENT_ID")
    assert hasattr(settings, "BREAKGLASS_ADMIN_EMAIL")
    assert hasattr(settings, "BREAKGLASS_ADMIN_PASSWORD")
    assert settings.ACCESS_ALLOWLIST_FILE.endswith("allowlist.json")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest tests/test_config_settings.py -v`
Expected: FAIL (new attrs missing).

- [ ] **Step 3: Add the dependency**

In `backend/pyproject.toml`, add to `dependencies` (after `"slowapi>=0.1.9",`):

```toml
    "google-auth>=2.35",
```

- [ ] **Step 4: Update the settings**

Replace the body of `Settings` in `backend/app/core/config.py` (keep the `model_config` line) so it reads:

```python
class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    DATA_DIR: str = "./data"
    SECRET_KEY: str = "dev-secret-change-me"
    ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60
    FRONTEND_URL: str = "http://localhost:5173"
    API_V1_PREFIX: str = "/api/v1"
    SEED_USERS_FILE: str = "../seed_users.json"  # removed in Task 7 with its consumer

    # Google Sign-In (public Client ID — no secret needed for the ID-token flow)
    GOOGLE_CLIENT_ID: str = ""
    # Email allowlist mapping email -> role (relative to backend CWD)
    ACCESS_ALLOWLIST_FILE: str = "../allowlist.json"
    # Break-glass local admin (empty -> not seeded)
    BREAKGLASS_ADMIN_EMAIL: str = ""
    BREAKGLASS_ADMIN_PASSWORD: str = ""
```

- [ ] **Step 5: Rebuild the backend image (new dependency) and run the test**

Run: `BACKEND_PORT=8010 docker compose up -d --build backend`
Then: `docker compose exec backend pytest tests/test_config_settings.py -v`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add backend/pyproject.toml backend/app/core/config.py backend/tests/test_config_settings.py
git commit -m "feat(auth): add Google/allowlist/break-glass settings and google-auth dep"
```

---

## Task 2: Identity model — `schemas/user.py`

**Files:**
- Modify: `backend/app/schemas/user.py`
- Test: `backend/tests/test_user_schema.py` (create)

**Interfaces:**
- Produces: `UserRecord` fields `email: str | None`, `google_sub: str | None`, `hashed_password: str | None` (all default `None`). `UserRead` gains `email: str | None`. New `GoogleLogin(BaseModel)` with `credential: str`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_user_schema.py`:

```python
from datetime import datetime, timezone

from app.schemas.user import GoogleLogin, UserRecord, UserRole


def test_user_record_allows_passwordless_google_user():
    u = UserRecord(
        id=1,
        username="Ann",
        email="ann@x.com",
        google_sub="sub-1",
        role=UserRole.annotator,
        created_at=datetime.now(timezone.utc),
    )
    assert u.hashed_password is None
    assert u.email == "ann@x.com"


def test_user_record_still_allows_password_user():
    u = UserRecord(
        id=2,
        username="admin",
        hashed_password="$2b$hash",
        role=UserRole.admin,
        created_at=datetime.now(timezone.utc),
    )
    assert u.email is None
    assert u.google_sub is None


def test_google_login_schema():
    assert GoogleLogin(credential="abc").credential == "abc"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest tests/test_user_schema.py -v`
Expected: FAIL (`hashed_password` required; `GoogleLogin`/`email`/`google_sub` undefined).

- [ ] **Step 3: Update the schemas**

In `backend/app/schemas/user.py`, replace `UserRecord`, `UserRead`, and add `GoogleLogin`:

```python
class UserRecord(BaseModel):
    """Full user record as stored on disk (may include a password hash)."""

    id: int
    username: str
    email: str | None = None
    google_sub: str | None = None
    hashed_password: str | None = None
    role: UserRole = UserRole.annotator
    created_at: datetime


class UserRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    username: str
    email: str | None = None
    role: UserRole
    created_at: datetime


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"


class GoogleLogin(BaseModel):
    credential: str
```

(Leave `UserCreate` unchanged — it still requires `username`+`password` and is used only for password accounts.)

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend pytest tests/test_user_schema.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Lint + commit**

```bash
ruff format backend && ruff check backend
git add backend/app/schemas/user.py backend/tests/test_user_schema.py
git commit -m "feat(auth): add email/google_sub, optional password, GoogleLogin schema"
```

---

## Task 3: User service — email lookup, provisioning, email-or-username auth

**Files:**
- Modify: `backend/app/services/user.py`
- Test: `backend/tests/test_user_provisioning.py` (create)

**Interfaces:**
- Consumes: `UserRecord`, `UserRole` (Task 2); `storage.load_users/save_users/next_id`; `security.hash_password/verify_password`.
- Produces:
  - `get_by_email(email: str) -> UserRecord | None`
  - `get_or_provision_google_user(email: str, name: str | None, google_sub: str | None, role: UserRole) -> UserRecord`
  - `upsert_password_admin(email: str, password: str) -> str` (`"created"|"updated"|"unchanged"`)
  - `authenticate(login: str, password: str) -> UserRecord | None` (matches username **or** email; requires a hash)

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_user_provisioning.py`:

```python
from app.schemas.user import UserRole
from app.services import user as user_service


def test_provision_creates_passwordless_user():
    u = user_service.get_or_provision_google_user(
        email="Ann@X.com", name="Ann Smith", google_sub="sub-1", role=UserRole.annotator
    )
    assert u.email == "ann@x.com"          # stored lowercase
    assert u.username == "Ann Smith"        # display name from Google
    assert u.hashed_password is None
    assert u.google_sub == "sub-1"
    assert user_service.get_by_email("ann@x.com").id == u.id


def test_provision_is_idempotent_and_syncs_role():
    a = user_service.get_or_provision_google_user(
        email="ann@x.com", name=None, google_sub="sub-1", role=UserRole.annotator
    )
    b = user_service.get_or_provision_google_user(
        email="ann@x.com", name=None, google_sub="sub-1", role=UserRole.admin
    )
    assert a.id == b.id                     # same record, id preserved
    assert b.role == UserRole.admin         # role synced from allowlist
    assert b.username == "ann"              # fallback display name = local part


def test_upsert_password_admin_and_authenticate_by_email():
    status = user_service.upsert_password_admin("boss@x.com", "StrongPass!")
    assert status == "created"
    assert user_service.upsert_password_admin("boss@x.com", "StrongPass!") == "unchanged"
    u = user_service.authenticate("boss@x.com", "StrongPass!")
    assert u is not None and u.role == UserRole.admin


def test_google_user_cannot_authenticate_without_password():
    user_service.get_or_provision_google_user(
        email="ann@x.com", name=None, google_sub="s", role=UserRole.annotator
    )
    assert user_service.authenticate("ann@x.com", "whatever") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest tests/test_user_provisioning.py -v`
Expected: FAIL (`get_or_provision_google_user` / `get_by_email` / `upsert_password_admin` undefined).

- [ ] **Step 3: Implement the service changes**

In `backend/app/services/user.py`, add imports at top (already imports `datetime, timezone`, `storage`, `hash_password, verify_password`, `UserCreate, UserRecord, UserRole`). Add these functions and update `authenticate`:

```python
def get_by_email(email: str) -> UserRecord | None:
    target = email.strip().lower()
    for u in storage.load_users():
        if (u.get("email") or "").lower() == target:
            return _to_record(u)
    return None


def _display_name(name: str | None, email: str) -> str:
    if name and name.strip():
        return name.strip()
    return email.split("@", 1)[0]


def _new_record(
    username: str,
    email: str | None,
    role: UserRole,
    google_sub: str | None = None,
    hashed_password: str | None = None,
) -> dict:
    return {
        "id": storage.next_id("users"),
        "username": username,
        "email": email.lower() if email else None,
        "google_sub": google_sub,
        "hashed_password": hashed_password,
        "role": role.value,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }


def get_or_provision_google_user(
    email: str, name: str | None, google_sub: str | None, role: UserRole
) -> UserRecord:
    """Find a user by email or create a passwordless one. Syncs role and
    google_sub from the caller (the allowlist / Google claims)."""
    users = storage.load_users()
    target = email.strip().lower()
    for u in users:
        if (u.get("email") or "").lower() != target:
            continue
        changed = False
        if u.get("role") != role.value:
            u["role"] = role.value
            changed = True
        if google_sub and u.get("google_sub") != google_sub:
            u["google_sub"] = google_sub
            changed = True
        if changed:
            storage.save_users(users)
        return _to_record(u)
    record = _new_record(_display_name(name, target), target, role, google_sub=google_sub)
    users.append(record)
    storage.save_users(users)
    return _to_record(record)


def upsert_password_admin(email: str, password: str) -> str:
    """Create or reconcile the break-glass admin (password account, keyed by
    email). Returns 'created' | 'updated' | 'unchanged'."""
    users = storage.load_users()
    target = email.strip().lower()
    for u in users:
        if (u.get("email") or "").lower() != target:
            continue
        changed = False
        if not u.get("hashed_password") or not verify_password(password, u["hashed_password"]):
            u["hashed_password"] = hash_password(password)
            changed = True
        if u.get("role") != "admin":
            u["role"] = "admin"
            changed = True
        if changed:
            storage.save_users(users)
            return "updated"
        return "unchanged"
    record = _new_record(
        _display_name(None, target), target, UserRole.admin,
        hashed_password=hash_password(password),
    )
    users.append(record)
    storage.save_users(users)
    return "created"
```

Then replace `authenticate` with:

```python
def authenticate(login: str, password: str) -> UserRecord | None:
    user = get_by_username(login) or get_by_email(login)
    if not user or not user.hashed_password:
        return None
    if not verify_password(password, user.hashed_password):
        return None
    return user
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend pytest tests/test_user_provisioning.py -v`
Expected: PASS (4 passed).

- [ ] **Step 5: Guard against regressions in the existing suite**

Run: `docker compose exec backend pytest tests/test_user_service.py tests/test_auth_api.py -v`
Expected: PASS (existing username/password fixtures still work — `authenticate` accepts username).

- [ ] **Step 6: Lint + commit**

```bash
ruff format backend && ruff check backend
git add backend/app/services/user.py backend/tests/test_user_provisioning.py
git commit -m "feat(auth): email lookup, Google provisioning, break-glass admin upsert"
```

---

## Task 4: Allowlist service — `services/allowlist.py`

**Files:**
- Create: `backend/app/services/allowlist.py`
- Test: `backend/tests/test_allowlist.py` (create)

**Interfaces:**
- Produces:
  - `load_allowlist() -> dict[str, dict]` — keyed by lowercased email; each value `{"email", "role", "name"}`. Missing/unreadable file → `{}` (fail-closed).
  - `lookup(email: str) -> dict | None`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_allowlist.py`:

```python
import json

from app.core.config import settings
from app.services import allowlist as allowlist_service


def _write(tmp_path, monkeypatch, data):
    f = tmp_path / "allowlist.json"
    f.write_text(json.dumps(data), encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(f))


def test_lookup_is_case_insensitive(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [{"email": "Ann@X.com", "role": "admin", "name": "Ann"}])
    entry = allowlist_service.lookup("ann@x.COM")
    assert entry is not None
    assert entry["role"] == "admin"
    assert entry["name"] == "Ann"


def test_lookup_absent_returns_none(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [{"email": "ann@x.com", "role": "annotator"}])
    assert allowlist_service.lookup("intruder@x.com") is None


def test_missing_file_is_fail_closed(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(tmp_path / "nope.json"))
    assert allowlist_service.load_allowlist() == {}


def test_malformed_file_is_fail_closed(tmp_path, monkeypatch):
    f = tmp_path / "allowlist.json"
    f.write_text("{not json", encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(f))
    assert allowlist_service.load_allowlist() == {}


def test_default_role_is_annotator(tmp_path, monkeypatch):
    _write(tmp_path, monkeypatch, [{"email": "ann@x.com"}])
    assert allowlist_service.lookup("ann@x.com")["role"] == "annotator"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest tests/test_allowlist.py -v`
Expected: FAIL (module `app.services.allowlist` does not exist).

- [ ] **Step 3: Implement the allowlist service**

Create `backend/app/services/allowlist.py`:

```python
"""Email allowlist: who may sign in via Google, and with what role.

Read fresh from disk on every call (the file is tiny) so that removing an
email revokes access on the next login without a restart. Missing or
unreadable file -> empty allowlist (fail-closed: nobody is authorized).
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
    except (OSError, json.JSONDecodeError) as e:
        log.error("Failed to read allowlist %s: %s — denying all Google logins.", path, e)
        return {}
    result: dict[str, dict] = {}
    for entry in entries:
        email = (entry.get("email") or "").strip().lower()
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
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend pytest tests/test_allowlist.py -v`
Expected: PASS (5 passed).

- [ ] **Step 5: Lint + commit**

```bash
ruff format backend && ruff check backend
git add backend/app/services/allowlist.py backend/tests/test_allowlist.py
git commit -m "feat(auth): email allowlist service (fresh read, fail-closed)"
```

---

## Task 5: Google token verification — `services/google_auth.py`

**Files:**
- Create: `backend/app/services/google_auth.py`
- Test: `backend/tests/test_google_auth_service.py` (create)

**Interfaces:**
- Produces: `verify_google_id_token(credential: str) -> dict` — returns verified claims (`email`, `email_verified`, `sub`, `name`, …); raises `ValueError` on any invalid token.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_google_auth_service.py`:

```python
from app.services import google_auth


def test_verify_delegates_to_google_with_client_id(monkeypatch):
    captured = {}

    def fake_verify(credential, request, audience):
        captured["credential"] = credential
        captured["audience"] = audience
        return {"email": "x@y.com", "email_verified": True}

    monkeypatch.setattr(google_auth.id_token, "verify_oauth2_token", fake_verify)
    monkeypatch.setattr(google_auth.settings, "GOOGLE_CLIENT_ID", "cid-123")

    out = google_auth.verify_google_id_token("thecred")
    assert out["email"] == "x@y.com"
    assert captured == {"credential": "thecred", "audience": "cid-123"}
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest tests/test_google_auth_service.py -v`
Expected: FAIL (module does not exist).

- [ ] **Step 3: Implement the wrapper**

Create `backend/app/services/google_auth.py`:

```python
"""Google ID-token verification (GIS ID-token flow).

Thin wrapper so the endpoint stays simple and tests can monkeypatch this
module without touching the network.
"""
from __future__ import annotations

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import settings


def verify_google_id_token(credential: str) -> dict:
    """Verify a Google ID token; return its claims.

    Validates signature, issuer, audience (== GOOGLE_CLIENT_ID) and
    expiry. Raises ValueError on any invalid token.
    """
    return id_token.verify_oauth2_token(
        credential,
        google_requests.Request(),
        settings.GOOGLE_CLIENT_ID,
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend pytest tests/test_google_auth_service.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Lint + commit**

```bash
ruff format backend && ruff check backend
git add backend/app/services/google_auth.py backend/tests/test_google_auth_service.py
git commit -m "feat(auth): Google ID-token verification wrapper"
```

---

## Task 6: `POST /auth/google` endpoint

**Files:**
- Modify: `backend/app/api/v1/auth.py`
- Test: `backend/tests/test_google_auth_api.py` (create)

**Interfaces:**
- Consumes: `google_auth.verify_google_id_token` (Task 5), `allowlist_service.lookup` (Task 4), `user_service.get_or_provision_google_user` (Task 3), `GoogleLogin` (Task 2), `create_access_token`, `limiter`.
- Produces: `POST {API_V1_PREFIX}/auth/google` accepting `{"credential": "..."}` → `200 {access_token, token_type}` | `401` (bad token) | `403` (unverified email / not allowlisted).

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_google_auth_api.py`:

```python
import json

from app.core.config import settings


def _set_allowlist(tmp_path, monkeypatch, entries):
    f = tmp_path / "allowlist.json"
    f.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(f))


def _fake_google(monkeypatch, email, name="Test User", verified=True, sub="sub-1"):
    from app.services import google_auth

    def fake(credential):
        return {"email": email, "email_verified": verified, "name": name, "sub": sub}

    monkeypatch.setattr(google_auth, "verify_google_id_token", fake)


def test_allowlisted_email_gets_token_and_is_provisioned(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "annotator"}])
    _fake_google(monkeypatch, "a@x.com")
    r = client.post("/api/v1/auth/google", json={"credential": "tok"})
    assert r.status_code == 200
    assert r.json()["access_token"]
    from app.services import user as user_service
    u = user_service.get_by_email("a@x.com")
    assert u is not None and u.role.value == "annotator" and u.google_sub == "sub-1"


def test_non_allowlisted_email_forbidden(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "annotator"}])
    _fake_google(monkeypatch, "intruder@x.com")
    r = client.post("/api/v1/auth/google", json={"credential": "tok"})
    assert r.status_code == 403


def test_unverified_email_forbidden(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "admin"}])
    _fake_google(monkeypatch, "a@x.com", verified=False)
    r = client.post("/api/v1/auth/google", json={"credential": "tok"})
    assert r.status_code == 403


def test_invalid_token_unauthorized(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "admin"}])
    from app.services import google_auth

    def boom(credential):
        raise ValueError("bad token")

    monkeypatch.setattr(google_auth, "verify_google_id_token", boom)
    r = client.post("/api/v1/auth/google", json={"credential": "tok"})
    assert r.status_code == 401


def test_role_sync_on_relogin(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "annotator"}])
    _fake_google(monkeypatch, "a@x.com")
    client.post("/api/v1/auth/google", json={"credential": "t"})
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "admin"}])
    client.post("/api/v1/auth/google", json={"credential": "t"})
    from app.services import user as user_service
    assert user_service.get_by_email("a@x.com").role.value == "admin"


def test_revocation_after_removal(client, tmp_path, monkeypatch):
    _set_allowlist(tmp_path, monkeypatch, [{"email": "a@x.com", "role": "annotator"}])
    _fake_google(monkeypatch, "a@x.com")
    assert client.post("/api/v1/auth/google", json={"credential": "t"}).status_code == 200
    _set_allowlist(tmp_path, monkeypatch, [])
    assert client.post("/api/v1/auth/google", json={"credential": "t"}).status_code == 403
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest tests/test_google_auth_api.py -v`
Expected: FAIL (404 — route not defined).

- [ ] **Step 3: Implement the endpoint**

In `backend/app/api/v1/auth.py`, update the imports and add the route. The header imports become:

```python
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.security import OAuth2PasswordRequestForm

from app.core.deps import CurrentUser
from app.core.ratelimit import limiter
from app.core.security import create_access_token
from app.schemas.user import GoogleLogin, Token, UserRead, UserRole
from app.services import allowlist as allowlist_service
from app.services import google_auth
from app.services import user as user_service
```

Add this route (after `login`, before `me`):

```python
@router.post("/google", response_model=Token)
@limiter.limit("5/minute")
def google_login(request: Request, body: GoogleLogin) -> Token:
    try:
        idinfo = google_auth.verify_google_id_token(body.credential)
    except ValueError:
        raise HTTPException(
            status.HTTP_401_UNAUTHORIZED,
            "Invalid Google credential",
            headers={"WWW-Authenticate": "Bearer"},
        )
    if not idinfo.get("email_verified"):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Google e-mail is not verified")
    email = (idinfo.get("email") or "").lower()
    entry = allowlist_service.lookup(email)
    if not entry:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not authorized")
    role = UserRole(entry.get("role", "annotator"))
    user = user_service.get_or_provision_google_user(
        email=email,
        name=idinfo.get("name"),
        google_sub=idinfo.get("sub"),
        role=role,
    )
    return Token(access_token=create_access_token(str(user.id)))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend pytest tests/test_google_auth_api.py -v`
Expected: PASS (6 passed).

> Note: a live `429` rate-limit test is intentionally omitted — the suite disables rate limiting globally (`conftest._disable_rate_limit`), and `@limiter.limit("5/minute")` is applied identically to the proven `POST /auth/login`.

- [ ] **Step 5: Lint + commit**

```bash
ruff format backend && ruff check backend
git add backend/app/api/v1/auth.py backend/tests/test_google_auth_api.py
git commit -m "feat(auth): POST /auth/google — verify, allowlist-gate, provision, mint JWT"
```

---

## Task 7: Startup seeding — break-glass admin + allowlist provisioning

**Files:**
- Modify: `backend/app/main.py:24-53`
- Modify: `backend/app/core/config.py` (remove `SEED_USERS_FILE`)
- Test: `backend/tests/test_startup_seed.py` (create)

**Interfaces:**
- Consumes: `settings.BREAKGLASS_ADMIN_EMAIL/PASSWORD`, `allowlist_service.load_allowlist`, `user_service.upsert_password_admin`, `user_service.get_or_provision_google_user`.
- Produces: `seed_users()` (renamed from `seed_default_users`) — importable and callable directly.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_startup_seed.py`:

```python
from app.core.config import settings


def _configure(tmp_path, monkeypatch, allowlist):
    (tmp_path / "allowlist.json").write_text(__import__("json").dumps(allowlist), encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(tmp_path / "allowlist.json"))
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_EMAIL", "boss@x.com")
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_PASSWORD", "StrongPass!")


def test_seed_creates_breakglass_and_allowlist_users(tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, [{"email": "ann@x.com", "role": "annotator", "name": "Ann"}])
    from app.main import seed_users
    seed_users()
    from app.services import user as user_service
    boss = user_service.get_by_email("boss@x.com")
    assert boss is not None and boss.role.value == "admin" and boss.hashed_password
    ann = user_service.get_by_email("ann@x.com")
    assert ann is not None and ann.role.value == "annotator" and ann.hashed_password is None


def test_breakglass_can_password_login_google_user_cannot(client, tmp_path, monkeypatch):
    _configure(tmp_path, monkeypatch, [{"email": "ann@x.com", "role": "annotator"}])
    from app.main import seed_users
    seed_users()
    ok = client.post("/api/v1/auth/login", data={"username": "boss@x.com", "password": "StrongPass!"})
    assert ok.status_code == 200
    no = client.post("/api/v1/auth/login", data={"username": "ann@x.com", "password": "anything"})
    assert no.status_code == 401


def test_no_breakglass_when_env_unset(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(tmp_path / "none.json"))
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_EMAIL", "")
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_PASSWORD", "")
    from app.main import seed_users
    seed_users()
    from app.services import user as user_service
    assert user_service.get_by_email("boss@x.com") is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest tests/test_startup_seed.py -v`
Expected: FAIL (`seed_users` does not exist — current name is `seed_default_users`, and it reads `SEED_USERS_FILE`).

- [ ] **Step 3: Rewrite the seeder**

In `backend/app/main.py`: update imports (add allowlist service) — the import block near the top becomes:

```python
from app.api.v1 import api_router
from app.core.config import settings
from app.core.ratelimit import limiter
from app.schemas.user import UserRole
from app.services import allowlist as allowlist_service
from app.services import user as user_service
```

Replace the whole `@app.on_event("startup")` function (currently `seed_default_users`, lines ~24-53) with:

```python
@app.on_event("startup")
def seed_users() -> None:
    """Seed the break-glass admin (from env) and provision allowlist users.

    Additive: existing records (incl. legacy password users) are left in
    place. Passwordless allowlist users are pre-created so admins can
    assign work to them before their first Google login.
    """
    if settings.BREAKGLASS_ADMIN_EMAIL and settings.BREAKGLASS_ADMIN_PASSWORD:
        status = user_service.upsert_password_admin(
            settings.BREAKGLASS_ADMIN_EMAIL, settings.BREAKGLASS_ADMIN_PASSWORD
        )
        if status != "unchanged":
            log.warning("break-glass admin: %s (%s)", status, settings.BREAKGLASS_ADMIN_EMAIL)

    for email, entry in allowlist_service.load_allowlist().items():
        try:
            role = UserRole(entry.get("role", "annotator"))
        except ValueError:
            log.error("Skipping allowlist entry with invalid role: %r", entry)
            continue
        user_service.get_or_provision_google_user(
            email=email, name=entry.get("name"), google_sub=None, role=role
        )
```

Now that the last consumer is gone, delete the `SEED_USERS_FILE` line from `backend/app/core/config.py` (the one added in Task 1 with the `# removed in Task 7` comment).

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend pytest tests/test_startup_seed.py -v`
Expected: PASS (3 passed).

- [ ] **Step 5: Run the full backend suite**

Run: `docker compose exec backend pytest -q`
Expected: all pass (no reference to the removed `seed_default_users`/`SEED_USERS_FILE` remains).

- [ ] **Step 6: Lint + commit**

```bash
ruff format backend && ruff check backend
git add backend/app/main.py backend/app/core/config.py backend/tests/test_startup_seed.py
git commit -m "feat(auth): seed break-glass admin from env, provision allowlist users"
```

---

## Task 8: Retire seed files, add allowlist example, reconcile script, env/gitignore

**Files:**
- Create: `backend/scripts/reconcile_users.py`
- Delete: `backend/scripts/reconcile_seed_users.py`, `seed_users.example.json`
- Create: `allowlist.example.json`
- Modify: `.gitignore`, `.env.example`, `.env.prod.example`
- Test: `backend/tests/test_reconcile_users.py` (create)

**Interfaces:**
- Produces: `scripts/reconcile_users.py` with `reconcile(apply: bool) -> list[dict]` returning the users it removed (emails not in the allowlist and not the break-glass admin); dry-run unless `apply`.

- [ ] **Step 1: Write the failing test**

Create `backend/tests/test_reconcile_users.py`:

```python
import json

from app.core.config import settings
from app.schemas.user import UserRole
from app.services import user as user_service


def _allowlist(tmp_path, monkeypatch, entries):
    f = tmp_path / "allowlist.json"
    f.write_text(json.dumps(entries), encoding="utf-8")
    monkeypatch.setattr(settings, "ACCESS_ALLOWLIST_FILE", str(f))


def test_reconcile_removes_only_unlisted_non_breakglass(tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "BREAKGLASS_ADMIN_EMAIL", "boss@x.com")
    _allowlist(tmp_path, monkeypatch, [{"email": "keep@x.com", "role": "annotator"}])
    user_service.upsert_password_admin("boss@x.com", "StrongPass!")
    user_service.get_or_provision_google_user("keep@x.com", None, None, UserRole.annotator)
    user_service.get_or_provision_google_user("drop@x.com", None, None, UserRole.annotator)

    from scripts.reconcile_users import reconcile

    preview = reconcile(apply=False)
    assert {u["email"] for u in preview} == {"drop@x.com"}
    assert user_service.get_by_email("drop@x.com") is not None  # dry-run kept it

    removed = reconcile(apply=True)
    assert {u["email"] for u in removed} == {"drop@x.com"}
    assert user_service.get_by_email("drop@x.com") is None
    assert user_service.get_by_email("keep@x.com") is not None
    assert user_service.get_by_email("boss@x.com") is not None  # break-glass preserved
```

- [ ] **Step 2: Run test to verify it fails**

Run: `docker compose exec backend pytest tests/test_reconcile_users.py -v`
Expected: FAIL (`scripts.reconcile_users` does not exist).

- [ ] **Step 3: Implement the reconcile script**

Create `backend/scripts/reconcile_users.py` (mirror the style of `reconcile_seed_users.py`):

```python
"""Prune users no longer authorized.

Removes users whose email is not in the allowlist, except the break-glass
admin (settings.BREAKGLASS_ADMIN_EMAIL). Legacy records without an email
are left untouched. Dry-run by default.

    python -m scripts.reconcile_users           # preview
    python -m scripts.reconcile_users --apply    # commit
"""
from __future__ import annotations

import sys

from app.core.config import settings
from app.core import storage
from app.services import allowlist as allowlist_service


def reconcile(apply: bool) -> list[dict]:
    allow = allowlist_service.load_allowlist()
    breakglass = (settings.BREAKGLASS_ADMIN_EMAIL or "").strip().lower()
    users = storage.load_users()

    def keep(u: dict) -> bool:
        email = (u.get("email") or "").strip().lower()
        if not email:
            return True  # legacy / dormant record — leave alone
        if email == breakglass:
            return True
        return email in allow

    removed = [u for u in users if not keep(u)]
    if apply and removed:
        storage.save_users([u for u in users if keep(u)])
    return removed


def main() -> None:
    apply = "--apply" in sys.argv
    removed = reconcile(apply=apply)
    verb = "Removed" if apply else "Would remove"
    print(f"{verb} {len(removed)} user(s):")
    for u in removed:
        print(f"  - {u.get('email')} (id={u.get('id')}, role={u.get('role')})")
    if not apply and removed:
        print("\nDry run. Re-run with --apply to commit.")


if __name__ == "__main__":
    main()
```

- [ ] **Step 4: Run test to verify it passes**

Run: `docker compose exec backend pytest tests/test_reconcile_users.py -v`
Expected: PASS (1 passed).

- [ ] **Step 5: Delete the old script + seed example, add the allowlist example**

```bash
git rm backend/scripts/reconcile_seed_users.py seed_users.example.json
```

Create `allowlist.example.json`:

```json
[
  { "email": "you@example.com", "role": "admin", "name": "Your Name" },
  { "email": "annotator1@gmail.com", "role": "annotator" }
]
```

- [ ] **Step 6: Update `.gitignore`, `.env.example`, `.env.prod.example`**

In `.gitignore`, add under the existing ignores (near `seed_users.json` if listed; otherwise at the end):

```gitignore
allowlist.json
```

Append to `.env.example`:

```bash

# Google Sign-In (public OAuth 2.0 Web client ID — no secret)
GOOGLE_CLIENT_ID=
VITE_GOOGLE_CLIENT_ID=

# Break-glass local admin (emergency access if OAuth is misconfigured)
BREAKGLASS_ADMIN_EMAIL=admin@example.com
BREAKGLASS_ADMIN_PASSWORD=change-me-to-a-strong-password
```

Append to `.env.prod.example`:

```bash

# Google Sign-In — public OAuth 2.0 Web client ID (no secret needed).
# VITE_GOOGLE_CLIENT_ID is embedded at BUILD time, so it must be set when
# the frontend image is built (deploy.sh rebuilds).
GOOGLE_CLIENT_ID=
VITE_GOOGLE_CLIENT_ID=

# Break-glass local admin — the only password account. Use a strong value.
BREAKGLASS_ADMIN_EMAIL=
BREAKGLASS_ADMIN_PASSWORD=
```

- [ ] **Step 7: Confirm nothing references the removed seed path**

Run: `docker compose exec backend pytest -q` and `grep -rn "SEED_USERS_FILE\|seed_default_users\|reconcile_seed_users" backend`
Expected: tests pass; grep returns nothing.

- [ ] **Step 8: Commit**

```bash
git add backend/scripts/reconcile_users.py backend/tests/test_reconcile_users.py allowlist.example.json .gitignore .env.example .env.prod.example
git commit -m "chore(auth): retire seed_users for allowlist.json; add reconcile_users + examples"
```

---

## Task 9: Frontend — env var, dependency, provider

**Files:**
- Modify: `frontend/package.json`
- Modify: `frontend/src/lib/env.ts`
- Modify: `frontend/src/main.tsx`

**Interfaces:**
- Produces: `GOOGLE_CLIENT_ID` export from `lib/env.ts`; app tree wrapped in `<GoogleOAuthProvider>`.

- [ ] **Step 1: Add the dependency**

In `frontend/package.json`, add to `dependencies` (alphabetical, before `axios`):

```json
    "@react-oauth/google": "^0.12.1",
```

Run: `cd frontend && npm install`
Expected: lockfile updates, `@react-oauth/google` installed.

- [ ] **Step 2: Export the client id**

Replace `frontend/src/lib/env.ts` with:

```ts
export const API_URL = import.meta.env.VITE_API_URL ?? 'http://localhost:8000/api/v1';
// API_URL is like http://host/api/v1 — strip trailing /api/v1 for serving /files
export const FILES_BASE = API_URL.replace(/\/api\/v1\/?$/, '');

export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID ?? '';
```

- [ ] **Step 3: Wrap the app in the provider**

Replace `frontend/src/main.tsx` with:

```tsx
import React from 'react';
import ReactDOM from 'react-dom/client';
import { QueryClient, QueryClientProvider } from '@tanstack/react-query';
import { GoogleOAuthProvider } from '@react-oauth/google';
import { BrowserRouter } from 'react-router-dom';
import App from './App';
import { GOOGLE_CLIENT_ID } from './lib/env';
import './index.css';

const queryClient = new QueryClient({
  defaultOptions: { queries: { retry: 1, refetchOnWindowFocus: false } },
});

ReactDOM.createRoot(document.getElementById('root')!).render(
  <React.StrictMode>
    <GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>
      <QueryClientProvider client={queryClient}>
        <BrowserRouter>
          <App />
        </BrowserRouter>
      </QueryClientProvider>
    </GoogleOAuthProvider>
  </React.StrictMode>,
);
```

- [ ] **Step 4: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: clean (no errors).

- [ ] **Step 5: Commit**

```bash
git add frontend/package.json frontend/package-lock.json frontend/src/lib/env.ts frontend/src/main.tsx
git commit -m "feat(auth): add @react-oauth/google provider and client-id env"
```

---

## Task 10: Frontend — `loginWithGoogle` API + `email` on `User`

**Files:**
- Modify: `frontend/src/api/auth.ts`

**Interfaces:**
- Consumes: `api` client.
- Produces: `loginWithGoogle(credential: string): Promise<{ access_token: string; token_type: string }>`; `User.email?: string`.

- [ ] **Step 1: Update the auth API module**

Replace `frontend/src/api/auth.ts` with:

```ts
import { api } from './client';

export interface User {
  id: number;
  username: string;
  email?: string | null;
  role: 'admin' | 'annotator' | 'reviewer';
  created_at: string;
}

export async function login(email: string, password: string) {
  const form = new URLSearchParams();
  form.append('username', email);
  form.append('password', password);
  const { data } = await api.post<{ access_token: string; token_type: string }>(
    '/auth/login',
    form,
    { headers: { 'Content-Type': 'application/x-www-form-urlencoded' } },
  );
  return data;
}

export async function loginWithGoogle(credential: string) {
  const { data } = await api.post<{ access_token: string; token_type: string }>(
    '/auth/google',
    { credential },
  );
  return data;
}

export async function me() {
  const { data } = await api.get<User>('/auth/me');
  return data;
}
```

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: clean.

- [ ] **Step 3: Commit**

```bash
git add frontend/src/api/auth.ts
git commit -m "feat(auth): frontend loginWithGoogle + email on User"
```

---

## Task 11: Frontend — `LoginPage` Google button + break-glass toggle

**Files:**
- Modify: `frontend/src/pages/LoginPage.tsx`

**Interfaces:**
- Consumes: `loginWithGoogle`, `login` (Task 10), `useAuth`, `<GoogleLogin>` from `@react-oauth/google`.

- [ ] **Step 1: Replace the login form**

In `frontend/src/pages/LoginPage.tsx`, replace the top imports and the `<main>…</main>` block (the right-hand column) so Google Sign-In is primary and the password form is behind a toggle. Change the import lines at the top of the file to:

```tsx
import { useState } from 'react';
import { useForm } from 'react-hook-form';
import { useNavigate } from 'react-router-dom';
import { GoogleLogin } from '@react-oauth/google';
import { login, loginWithGoogle } from '@/api/auth';
import { useAuth } from '@/stores/auth';
```

Replace the `onSubmit` function with both handlers:

```tsx
  async function onGoogle(credential: string | undefined) {
    setError(null);
    if (!credential) {
      setError('Google sign-in failed. Please try again.');
      return;
    }
    setLoading(true);
    try {
      const { access_token } = await loginWithGoogle(credential);
      setToken(access_token);
      navigate('/projects');
    } catch {
      setError('This Google account is not authorized.');
    } finally {
      setLoading(false);
    }
  }

  async function onSubmit(values: Form) {
    setError(null);
    setLoading(true);
    try {
      const { access_token } = await login(values.username, values.password);
      setToken(access_token);
      navigate('/projects');
    } catch {
      setError('Invalid credentials');
    } finally {
      setLoading(false);
    }
  }
```

Add a `showAdmin` toggle to the component state (next to the existing `useState` hooks):

```tsx
  const [showAdmin, setShowAdmin] = useState(false);
```

Replace the `<form …>` element inside `<main>` with the Google-first block. Keep the surrounding `<main className="flex items-center justify-center p-6 lg:p-10">` wrapper and the mobile logo:

```tsx
        <div className="w-full max-w-sm bg-white p-8 rounded-xl shadow-sm ring-1 ring-slate-200 space-y-5">
          <div className="flex items-center gap-2 lg:hidden">
            <LogoMark />
            <span className="text-lg font-semibold tracking-tight text-sky-900">NeoLabel</span>
          </div>
          <div>
            <h1 className="text-2xl font-semibold text-slate-900">Sign in</h1>
            <p className="mt-1 text-sm text-slate-500">Access your annotation workspace.</p>
          </div>

          <div className="flex justify-center">
            <GoogleLogin
              onSuccess={(cred) => onGoogle(cred.credential)}
              onError={() => setError('Google sign-in failed. Please try again.')}
            />
          </div>

          {error && <p className="text-red-600 text-sm">{error}</p>}

          <button
            type="button"
            onClick={() => setShowAdmin((v) => !v)}
            className="text-xs text-slate-400 hover:text-slate-600 underline underline-offset-2"
          >
            Entrar como admin (emergência)
          </button>

          {showAdmin && (
            <form onSubmit={handleSubmit(onSubmit)} className="space-y-4 border-t border-slate-100 pt-4">
              <label className="block space-y-1">
                <span className="text-xs font-medium text-slate-600 uppercase tracking-wide">Admin e-mail</span>
                <input
                  {...register('username', { required: true })}
                  autoComplete="username"
                  placeholder="admin@example.com"
                  className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm
                             focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                />
              </label>
              <label className="block space-y-1">
                <span className="text-xs font-medium text-slate-600 uppercase tracking-wide">Password</span>
                <input
                  {...register('password', { required: true })}
                  type="password"
                  autoComplete="current-password"
                  placeholder="••••••••"
                  className="w-full border border-slate-300 rounded-md px-3 py-2 text-sm
                             focus:outline-none focus:ring-2 focus:ring-sky-500 focus:border-sky-500"
                />
              </label>
              <button
                disabled={loading}
                className="w-full py-2.5 rounded-md text-white font-medium
                           bg-gradient-to-r from-sky-600 to-sky-700 hover:from-sky-700 hover:to-sky-800
                           disabled:opacity-60 disabled:cursor-not-allowed transition"
              >
                {loading ? 'Signing in…' : 'Sign in as admin'}
              </button>
            </form>
          )}
        </div>
```

(The `Form` interface, `register`, `handleSubmit`, `useAuth`, the decorative aside, and the `Chip`/`LogoMark`/`PoseHero`/`RodentHero` helpers all stay as-is.)

- [ ] **Step 2: Typecheck**

Run: `cd frontend && npx tsc -b --noEmit`
Expected: clean.

- [ ] **Step 3: Manual smoke (documented, not automated)**

With a real `VITE_GOOGLE_CLIENT_ID` set and origin `http://localhost:5173` authorized in Google Cloud: the Google button renders, a successful sign-in from an allowlisted email lands on `/projects`, and the "Entrar como admin (emergência)" toggle reveals the password form. (No frontend test suite — this step is a checklist item, not code.)

- [ ] **Step 4: Commit**

```bash
git add frontend/src/pages/LoginPage.tsx
git commit -m "feat(auth): Google Sign-In button with break-glass admin toggle"
```

---

## Task 12: Documentation

**Files:**
- Modify: `SPEC.md` (tracked), `README.md` (tracked)
- Modify: `CLAUDE.md`, `CLAUDE.local.md` (git-ignored — edit, do NOT stage)

- [ ] **Step 1: Update `SPEC.md`**

- §3 (Storage): the user record gains `email` and `google_sub`, `hashed_password` is now optional; `allowlist.json` (email→role) replaces `seed_users.json`.
- §4 (Auth): document `POST /auth/google` (verify ID token → `email_verified` → allowlist → provision → JWT), the allowlist authorization model with instant revocation, the break-glass admin via `POST /auth/login`, and fail-closed behavior. Note `POST /auth/login` now only serves accounts that have a password.

- [ ] **Step 2: Update `README.md`**

In the sign-in description, state that access is via Google Sign-In restricted to an email allowlist, with an emergency admin password account. Update any screenshot caption that references username/password entry.

- [ ] **Step 3: Update `CLAUDE.md` (local only — do not stage)**

- Stack/auth pointers: `security.py` still mints the session JWT; add `services/allowlist.py` (fresh-read, fail-closed) and `services/google_auth.py`; `POST /auth/google` lives in `api/v1/auth.py`; startup seeder is `main.py:seed_users()`.
- Footgun: `VITE_GOOGLE_CLIENT_ID` is embedded at build time (must be present when the frontend image is built); the break-glass admin is the only password account.

- [ ] **Step 4: Update `CLAUDE.local.md` (local only — do not stage)**

- Files NOT in git: replace `seed_users.json` with `allowlist.json`; note `.env.prod` now also holds `GOOGLE_CLIENT_ID`, `VITE_GOOGLE_CLIENT_ID`, `BREAKGLASS_ADMIN_EMAIL`, `BREAKGLASS_ADMIN_PASSWORD`.
- Add a "Google Cloud" note: OAuth 2.0 Web Client ID, authorized JS origins `https://neolabel.heltonmaia.com` + `http://localhost:5173`, consent screen External + `openid email profile`, Testing-mode gotcha, no client secret.
- Deploy workflow: create `allowlist.json` (with at least the owner's admin email) and set the new env vars before `./scripts/deploy.sh`; verify break-glass + own Google login before announcing.

- [ ] **Step 5: Commit (tracked docs only)**

```bash
git add SPEC.md README.md
git commit -m "docs: Google Sign-In + email allowlist auth model"
```

(CLAUDE.md / CLAUDE.local.md are git-ignored — their edits stay local and are intentionally not committed.)

---

## Post-implementation: deploy (operator runbook, not a code task)

Follow §7 of the design spec. Summary: create the Google OAuth Client ID; set `GOOGLE_CLIENT_ID`, `VITE_GOOGLE_CLIENT_ID`, `BREAKGLASS_ADMIN_EMAIL`, `BREAKGLASS_ADMIN_PASSWORD` in `.env.prod`; create `allowlist.json` on the VPS with at least the owner's admin email; run `./scripts/deploy.sh` (rebuilds so Vite picks up the client id); verify break-glass **and** the owner's Google login before announcing to annotators.
