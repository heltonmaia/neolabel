# Google Sign-In with email allowlist — design

**Date:** 2026-07-04
**Status:** approved (design), pending implementation
**Scope:** replace username/password authentication with **Google Sign-In**
(Google Identity Services, ID-token flow) gated by a **server-side email
allowlist**, plus one **break-glass local admin** for emergencies. The
session layer (our own JWT) is unchanged — only the *login step* changes.

## 1. Problem

Current auth is username/password:

- `UserCreate.password` has `min_length=4` — weak passwords are accepted.
- Access is a static `seed_users.json` of usernames + plaintext passwords
  (hashed on first seed). Onboarding = edit that file; there is no
  identity delegation and no meaningful password policy.

This is the "fragile access" being replaced. We delegate identity to
Google (no passwords to store, guess, or leak), restrict entry to an
**approved email allowlist**, and keep exactly **one** emergency password
admin so an OAuth/allowlist misconfiguration — or a Google outage — can
never lock everyone (including the owner) out of a live research tool.

**Unchanged by design:** the session JWT (`sub = user.id`, HS256, 60 min),
the axios Bearer interceptor, `CurrentUser`, the role gates
(`AdminUser`), `401 → auto-logout`, and every `owner_id` / `assigned_to` /
annotation reference (all keyed by numeric user `id`, never username).

## 2. Decisions (settled during brainstorming)

| Decision | Choice | Rationale |
|---|---|---|
| **Login model** | Google for all regular users **+ 1 break-glass local admin** (strong password). | Eliminates annotator passwords without risking a full lockout if OAuth misconfigures or Google is down. |
| **Access control** | **Server-side email allowlist** mapping `email → role`. | Tightest control; mirrors the current closed model; enables instant revocation. |
| **Allowlist management** | A **file on the server**, read fresh at login and provisioned at startup. Editing = edit file (+ restart to (de)provision records). | Smallest change, matches current ops. A runtime admin UI is explicit future work. |
| **Google integration** | **GIS + ID-token verification** — the browser gets a signed ID token, the backend verifies it and mints *our* session JWT. | Reuses 100% of the session layer; **needs no client secret** (only the public Client ID) — ideal for a public + mirrored repo. |
| **Existing users** | **Start the allowlist from scratch.** No `username → email` migration. Leave the current `users.json` records dormant (no email → cannot log in). | User confirmed no current assignments need preserving. Nothing is destroyed: any admin still sees all existing projects, and annotation files stay on disk (read via the `find_any_annotation_for_item` fallback). |

**Rejected:**

- *Full password removal (no break-glass)* — a single OAuth/allowlist
  mistake would lock everyone out of a live deploy.
- *Domain-only (`@ufrn.br`) or open self-registration* — too broad for
  neonatal data; external collaborators use gmail anyway.
- *OAuth2 Authorization Code flow* — needs a **client secret**, which
  would have to live only in `.env.prod` and never reach the public
  mirror; more moving parts (redirect URIs, state/CSRF, callback route)
  for a pure SPA.
- *Managed provider (Auth0/Firebase/Clerk)* — external dependency, cost,
  lock-in, and ships user identities to a third party.
- *Wiping `users.json`* — a needless data-loss event; dormant records are
  harmless and the `id` counter never reuses ids.

## 3. Architecture

Login data flow:

```
Browser (GIS button) → Google returns a signed ID token (JWT) to the SPA
  → POST /auth/google { credential }
      → verify_oauth2_token(credential, GOOGLE_CLIENT_ID)   # sig, iss, aud, exp
      → require idinfo["email_verified"] is True
      → email (lowercased) in allowlist.json (read FRESH)?  no → 403
      → get_or_provision_google_user(email, name, sub, role)   # find or create
      → mint our session JWT (sub = user.id)  → { access_token, token_type }
  → frontend stores token (unchanged) → everything downstream is identical
```

Break-glass path (unchanged endpoint): `POST /auth/login` still exists but
now only succeeds for accounts that **have** a `hashed_password` — i.e. the
env-seeded emergency admin. Google users have `hashed_password = None`, so
`verify_password` fails and they get 401 there; their only door is
`/auth/google`.

### 3.1 Identity model — `schemas/user.py`

| Field | Change |
|---|---|
| `id` | **Unchanged** — the anchor that preserves assignments/annotations. |
| `email` | **New** `str` — Google-verified, stored lowercased; the login key for Google users. |
| `google_sub` | **New** `str \| None = None` — Google's stable subject id; set on first Google login. Survives an email change. |
| `hashed_password` | Now **optional** (`str \| None = None`) — only the break-glass admin has a hash. |
| `username` | Retained as a **display label** (from Google `name`, else email local-part). No longer the login key. |
| `role`, `created_at` | Unchanged. |

- `UserRead` (and the frontend `User` interface) gain `email`.
- `UserCreate` is retained **only** for break-glass password seeding; its
  `username` pattern (`^[A-Za-z0-9_.-]+$`) forbids `@`, so **Google
  provisioning does not go through `UserCreate`** — it builds the record
  dict directly.
- Reads are tolerant (`dict.get`) so legacy records without
  `email`/`google_sub` load fine (they stay dormant until an email is
  attached).

### 3.2 Allowlist — new file + loader

New file **`allowlist.json`** (gitignored, next to today's
`seed_users.json`), a list of `email → role`:

```json
[
  { "email": "helton.maia@ufrn.br", "role": "admin", "name": "Helton Maia" },
  { "email": "annotador1@gmail.com", "role": "annotator" }
]
```

`role` defaults to `annotator`; `name` optional. **No passwords.** A
committed `allowlist.example.json` documents the shape.

New module **`services/allowlist.py`**:

- `load_allowlist() -> dict[str, dict]` — map keyed by lowercased email.
  Missing or unparseable file → returns `{}` and logs an error
  (**fail-closed**: no email can authorize, but the break-glass admin,
  seeded from env, still gets in).
- `lookup(email: str) -> dict | None` — case-insensitive membership +
  role. Read fresh from disk each call (the file is tiny), which is what
  gives **instant revocation** — remove an email and the next
  `/auth/google` is denied without any provisioning change.

### 3.3 Auth service + endpoint

**`services/user.py`**

- `create(...)`: `hashed_password` becomes optional; Google users are
  created with `None`.
- `get_by_email(email) -> UserRecord | None` (case-insensitive).
- `get_or_provision_google_user(email, name, google_sub, role) -> UserRecord`
  — find by email; if missing, build the record directly (new id from
  `next_id("users")`, no password); on an existing record, sync `role`
  from the allowlist and set/refresh `google_sub` and display `username`.
- `authenticate(login, password)` — match by **username or email** so the
  emergency admin can type either; still requires a `hashed_password`.

**`services/google_auth.py`** (thin, mockable in tests)

- `verify_google_id_token(credential: str) -> dict` — wraps
  `google.oauth2.id_token.verify_oauth2_token(credential,
  google.auth.transport.requests.Request(), settings.GOOGLE_CLIENT_ID)`.
  Returns the verified `idinfo` (email, email_verified, sub, name, …).
  Raises `ValueError` on any invalid token (bad signature, wrong `aud`,
  expired).

**`api/v1/auth.py`**

- `POST /auth/google` — rate-limited `5/minute` (takes `request: Request`
  like `login`). Body `GoogleLogin { credential: str }`. Steps:
  verify → require `email_verified` (else 403) → `allowlist.lookup`
  (absent → 403) → `get_or_provision_google_user` → return
  `Token(create_access_token(str(user.id)))`.
- `POST /auth/login` — **unchanged code**; effectively break-glass-only
  now (Google users have no hash).
- `GET /auth/me` — unchanged (now also returns `email`).

### 3.4 Startup provisioning — `main.py`

Rewrite `seed_default_users()`:

1. **Break-glass admin:** if `BREAKGLASS_ADMIN_EMAIL` **and**
   `BREAKGLASS_ADMIN_PASSWORD` are set, upsert an `admin` user with that
   email and a hashed password (idempotent, preserves id, updates the hash
   if the password changed — same spirit as today's `upsert_seed_user`).
2. **Allowlist:** load `allowlist.json`; upsert a **passwordless** user per
   entry (create with a new id if missing; sync role/display name). This
   **pre-provisions** annotators so admins can assign videos to them
   *before* their first login (preserves current assignment UX).

Additive, like today's seeder. The old `users.json` records are left
untouched (dormant). A companion `scripts/reconcile_users.py` (analogous to
`reconcile_seed_users.py`) can prune users no longer in the allowlist —
never touching the break-glass admin — dry-run by default, `--apply` to
commit.

### 3.5 Config — `core/config.py` + env

Add to `Settings`:

- `GOOGLE_CLIENT_ID: str = ""` — public; used to check the token `aud`.
- `ACCESS_ALLOWLIST_FILE: str = "../allowlist.json"`.
- `BREAKGLASS_ADMIN_EMAIL: str = ""`, `BREAKGLASS_ADMIN_PASSWORD: str = ""`
  (both empty → no break-glass seeded).

Remove `SEED_USERS_FILE`. New backend dependency **`google-auth`** in
`pyproject.toml`. `.env.example` and `.env.prod.example` gain
`GOOGLE_CLIENT_ID`, `VITE_GOOGLE_CLIENT_ID`, `BREAKGLASS_ADMIN_EMAIL`,
`BREAKGLASS_ADMIN_PASSWORD`. `.gitignore` gains `allowlist.json`.

The now-unused **`seed_users.json`**, **`seed_users.example.json`**, and
**`scripts/reconcile_seed_users.py`** are retired — replaced by
`allowlist.json`, `allowlist.example.json`, and `scripts/reconcile_users.py`
respectively. (Leave any real `seed_users.json` on the VPS in place, just
unreferenced, until the deploy is confirmed working.)

### 3.6 Frontend

- New dependency **`@react-oauth/google`** (loads `gsi/client`, provides
  `GoogleOAuthProvider` + `<GoogleLogin>`; default flow returns the ID
  token as `credentialResponse.credential`).
- `lib/env.ts`:
  `export const GOOGLE_CLIENT_ID = import.meta.env.VITE_GOOGLE_CLIENT_ID`.
- `main.tsx`: wrap the app tree in
  `<GoogleOAuthProvider clientId={GOOGLE_CLIENT_ID}>`.
- `api/auth.ts`: add `loginWithGoogle(credential: string)` →
  `POST /auth/google`; keep `login()` for break-glass; add `email` to the
  `User` interface.
- `pages/LoginPage.tsx`: the primary control becomes `<GoogleLogin>`
  (onSuccess → `loginWithGoogle(cred.credential)` → `setToken` →
  `navigate('/projects')`). A discreet **"Entrar como admin (emergência)"**
  toggle reveals the existing password form (unchanged `login()` path).
  The decorative aside stays.
- **CSP note:** there is no CSP today. If one is later added to the prod
  nginx, it must allow `accounts.google.com` / `gstatic.com` in
  `script-src`, `connect-src`, and `frame-src`.

### 3.7 Google Cloud setup (one-time, operational)

- Create an **OAuth 2.0 Client ID**, type *Web application*.
- **Authorized JavaScript origins:** `https://neolabel.heltonmaia.com`
  and `http://localhost:5173`. (GIS ID-token uses *origins*, not redirect
  URIs, and generates **no client secret**.)
- **OAuth consent screen:** *External* user type (gmail annotators),
  scopes `openid email profile`. ⚠️ In *Testing* mode only listed test
  users can sign in — publish the app or add testers.
- Copy the Client ID into `GOOGLE_CLIENT_ID` (backend) and
  `VITE_GOOGLE_CLIENT_ID` (frontend).

## 4. Errors & edge cases

| Case | Result |
|---|---|
| Invalid/expired ID token, wrong `aud` | `401` |
| `email_verified` is false | `403` "e-mail não verificado" |
| Email not in allowlist | `403` "não autorizado" (does not reveal the list) |
| Allowlist file missing/unreadable | Fail-closed: all Google logins denied; break-glass still works |
| Allowlist edited without restart | New email still authorizes (looked up fresh) and is JIT-provisioned |
| Google user tries `POST /auth/login` | `401` (no `hashed_password`) |
| Break-glass env unset | No emergency admin seeded (dev default) |
| Popup closed / GIS script blocked | Friendly frontend error + break-glass link |
| `401` on any request | Auto-logout (unchanged) |

## 5. Testing — `tests/test_google_auth_api.py`

Monkeypatch `services.google_auth.verify_google_id_token` (or the
underlying `verify_oauth2_token`) to return a controlled `idinfo`, and
point `ACCESS_ALLOWLIST_FILE` at a temp file per test (extend
`conftest.py`; consider a `google_auth_headers` helper). Cases:

1. **Allowlisted email** → 200 with a usable JWT; a user is provisioned;
   `role` comes from the allowlist; `google_sub` stored.
2. **Non-allowlisted email** → `403`, no user created.
3. **`email_verified` false** → `403`.
4. **Role sync** — changing the allowlist role updates the record on next
   login.
5. **Revocation** — remove the email from the allowlist → next
   `/auth/google` → `403`.
6. **Break-glass** — password login succeeds for the env-seeded admin; a
   Google user (no hash) fails `/auth/login` with `401`.
7. **Invalid token** — verifier raises → `401`.
8. **Rate limit** — 6th `/auth/google` within a minute → `429`.
9. **Startup provisioning** — allowlist entries appear as assignable users;
   ids stay stable across a re-seed.

Frontend has no test suite (per CLAUDE.md) → `npx tsc -b --noEmit` +
manual verification of the Google button and the break-glass toggle.

## 6. Docs to update (before/with code)

- **SPEC.md** — §3 (user record gains `email`/`google_sub`,
  `hashed_password` optional; `allowlist.json` replaces `seed_users.json`)
  and §4 Auth (`POST /auth/google`, allowlist authorization, break-glass,
  fail-closed behavior).
- **CLAUDE.md** — Stack/auth pointers (`security.py` still mints JWT;
  add allowlist + `services/allowlist.py` + `google_auth.py`), and a
  footgun on the `VITE_GOOGLE_CLIENT_ID` build-time embed + break-glass.
- **CLAUDE.local.md** — VPS: create `allowlist.json`, set the new env
  vars, register the Google Cloud Client ID, break-glass-first rollout.
- **README.md** — sign-in description (Google + emergency admin).

## 7. Rollout / ops (VPS)

1. Create the OAuth Client ID in Google Cloud (§3.7).
2. In `.env.prod`, set `GOOGLE_CLIENT_ID`, `VITE_GOOGLE_CLIENT_ID`,
   `BREAKGLASS_ADMIN_EMAIL`, `BREAKGLASS_ADMIN_PASSWORD`. ⚠️
   `VITE_GOOGLE_CLIENT_ID` is **embedded at build time** — it must be
   present in the production build environment, not just at runtime.
3. Create `allowlist.json` on the VPS **with at least your own admin
   email**.
4. `./scripts/deploy.sh` (rebuilds, so the frontend picks up the Vite var).
5. Verify break-glass login **and** your own Google login work **before**
   announcing to annotators.

## 8. Out of scope (YAGNI)

- Runtime admin UI to manage the allowlist (future "hybrid" phase).
- Domain-based (`hd` claim) auto-provisioning.
- `username → email` migration / linking dormant legacy accounts.
- Refresh tokens / "remember me" / session extension (keep 60 min).
- Additional identity providers (GitHub, Microsoft, …).
- Server-side One Tap / auto-select prompts (a plain button is enough).
