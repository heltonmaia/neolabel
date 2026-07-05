# Emergency Email-Code Access (Break-Glass v2) — Design

**Date:** 2026-07-05
**Status:** Approved for planning
**Supersedes:** the password break-glass (`BREAKGLASS_ADMIN_EMAIL` / `BREAKGLASS_ADMIN_PASSWORD`
+ the `POST /auth/login` password path), which this feature **removes**.

## Goal

Give the single admin (the owner) a **Google-independent** way to obtain an admin
session when Google Sign-In is unavailable (bad OAuth client, consent/allowlist
misconfig, token-verification failure, Google outage). The admin requests a one-time
code by email, enters it, and gets the **normal** admin session JWT. No password is
stored anywhere, and the path is **not advertised** on the login screen.

## Non-goals

- Not a general password/OTP system for annotators — annotators use Google only.
- Not multi-admin — exactly **one** configured emergency email is eligible.
- Not a replacement for Google as the primary login — this is a rarely-used fallback.
- No "remember me" / long-lived emergency sessions — the session is the standard JWT.

## Why this shape (decisions already made)

- **Email one-time code**, not a stored password (the owner's stated principle: a JSON/file
  used for *authorization* is fine; storing a *credential for login* is not). A short-lived,
  single-use code leaves no long-lived secret on the server.
- **Resend (transactional API over HTTPS)** for delivery, because the Contabo VPS blocks
  outbound SMTP ports — SMTP from the server would be an unreliable fallback.
- **No visible entry** on the login page — reached via a dedicated URL. The security is the
  code + rate limits, not URL obscurity.

## Current state (for context)

- Auth today: Google Sign-In (ID token) gated by `allowlist.json`, plus a dormant password
  break-glass. Session = HS256 JWT, `ACCESS_TOKEN_EXPIRE_MINUTES` (60).
- The app sends **no email** today (no SMTP, no email dependency).
- Prod runs Google-only (`BREAKGLASS_ADMIN_*` unset). 8 old password accounts are dormant.

## The flow

**Step 1 — request a code**
1. Admin opens `neolabel.heltonmaia.com/emergency` (not linked from `/login`).
2. Enters an email, submits.
3. Backend `POST /api/v1/auth/emergency/request`:
   - If `email == EMERGENCY_ADMIN_EMAIL` (case-insensitive) **and** no unexpired code is within
     the cooldown window: generate a 6-digit numeric code, store `{email, code_hash,
     expires_at, attempts: 0, created_at}` (overwriting any previous), and send the code via
     Resend.
   - Otherwise: do nothing.
   - **Always** return `200 {"detail": "If that email is registered, a code has been sent."}` —
     identical for admin/non-admin (no user enumeration).
   - Rate-limited (see Security).

**Step 2 — verify the code**
4. Admin enters the 6-digit code, submits.
5. Backend `POST /api/v1/auth/emergency/verify` with `{email, code}`:
   - Load the stored code for that email. Reject (generic 400) if none, expired, or
     `attempts >= max`.
   - Compare `hmac_sha256(code, SECRET_KEY)` to `code_hash` (constant-time).
     - **Match:** delete the stored code (single-use), find-or-provision the admin user by
       `EMERGENCY_ADMIN_EMAIL` as role `admin`, mint the standard JWT, return
       `{access_token, token_type: "bearer"}` (same shape as `/auth/google`).
     - **No match:** increment `attempts`; if it reaches the max, delete the code (burned);
       return generic `400 {"detail": "Invalid or expired code."}`.
   - Rate-limited.

The verify path never calls Google — it is fully independent of the Google integration.

## API contract

| Method | Path | Body | Success | Notes |
|---|---|---|---|---|
| POST | `/api/v1/auth/emergency/request` | `{email: str}` | `200 {detail}` (generic) | Always 200; rate-limited |
| POST | `/api/v1/auth/emergency/verify` | `{email: str, code: str}` | `200 {access_token, token_type}` | 400 generic on failure; rate-limited |

Pydantic request models: `EmergencyCodeRequest{email: EmailStr}`,
`EmergencyCodeVerify{email: EmailStr, code: str}`. Response reuses the existing `Token` schema.

## Data model (on disk)

One JSON file under `DATA_DIR`, e.g. `emergency_code.json` (single admin → at most one active
code), written through `app/core/storage.py` (atomic). Shape:

```json
{
  "email": "owner@example.com",
  "code_hash": "<hmac_sha256(code, SECRET_KEY) hex>",
  "expires_at": "<ISO-8601 UTC>",
  "attempts": 0,
  "created_at": "<ISO-8601 UTC>"
}
```

Absent file = no active code. Success or burn deletes the file.

## Security

- Code: **6 digits**, **single-use**, **10-min TTL** (`EMERGENCY_CODE_TTL_MINUTES`).
- Stored **hashed** (`hmac_sha256(code, SECRET_KEY)`) — a leaked file can't be brute-forced
  without `SECRET_KEY`. Verify uses constant-time compare.
- **Attempt cap** (`EMERGENCY_CODE_MAX_ATTEMPTS`, default 5): after N wrong tries the code is
  burned → the 6-digit space (10^6) cannot be brute-forced within the 10-min window.
- **Rate limits** (reuse `core/ratelimit.py` / `slowapi`, keyed on the real client IP):
  - request: `5/min` per IP, **plus** a per-email cooldown (`EMERGENCY_CODE_COOLDOWN_SECONDS`,
    default 60) enforced via `created_at` — prevents inbox spam even across IPs.
  - verify: `10/min` per IP (defense in depth on top of the attempt cap).
- **No user enumeration:** identical response and status for any email.
- **Single eligible email:** only `EMERGENCY_ADMIN_EMAIL` produces a code; it is independent of
  `allowlist.json` (works even if the allowlist is the thing that broke).
- Session on success = the standard JWT (`create_access_token`, unchanged), 60-min expiry.

Accepted low-severity residual: a small timing difference between admin/non-admin request
handling (code-gen + email send happen only for the admin). Low risk given single admin +
rate limiting; not mitigated.

## Email delivery

- **`services/email.py`** — a thin, mockable module (mirrors `services/google_auth.py`'s
  testability): `send_emergency_code(to: str, code: str) -> None` that POSTs to the Resend API
  (`https://api.resend.com/emails`) over HTTPS with `RESEND_API_KEY`, `from = EMAIL_FROM`.
  HTTP via `httpx` (add to runtime deps) or stdlib `urllib.request` — plan's choice; `httpx`
  preferred for consistency.
- Tests **monkeypatch** `send_emergency_code` — the suite never makes a network call.
- Failure to send (Resend error/timeout) → the request endpoint still returns the generic 200
  (don't leak send status); log the error server-side.

## Config / settings (`core/config.py`)

**Add:**
- `RESEND_API_KEY: str = ""`
- `EMAIL_FROM: str = ""` (e.g. `"NeoLabel <noreply@neolabel.heltonmaia.com>"`)
- `EMERGENCY_ADMIN_EMAIL: str = ""`
- `EMERGENCY_CODE_TTL_MINUTES: int = 10`
- `EMERGENCY_CODE_MAX_ATTEMPTS: int = 5`
- `EMERGENCY_CODE_COOLDOWN_SECONDS: int = 60`

**Remove:** `BREAKGLASS_ADMIN_PASSWORD`. **Rename** `BREAKGLASS_ADMIN_EMAIL` →
`EMERGENCY_ADMIN_EMAIL` (update local `.env`; prod `.env.prod` currently sets neither).

## Frontend

- New route `/emergency` → `EmergencyAccessPage` (`App.tsx`, `pages/`). Two steps in one page:
  email → "Send code"; then code → "Verify". On success: `useAuth.setToken` → `navigate('/projects')`.
- API module `api/auth.ts`: add `requestEmergencyCode(email)` and `verifyEmergencyCode(email, code)`;
  **remove** `login(username, password)`.
- `LoginPage.tsx`: **remove** the `showAdmin` toggle, the admin username/password form, and the
  `useForm`/`login` imports. The login page becomes Google-only. No link to `/emergency`.
- Copy: register-side "Enter your email and we'll send a one-time code." Errors are generic
  ("Invalid or expired code"), active voice, matching the login design language
  (see the `neolabel-login-design` memory).

## What is removed

- `POST /auth/login`, `services/user.py:authenticate`, `upsert_password_admin`, and the
  password-seeding in `main.py:seed_users()` (the emergency admin needs no stored password).
- `BREAKGLASS_ADMIN_PASSWORD` setting and all references.
- Frontend admin password form + `login` API call.
- Existing tests that exercise `/auth/login` / `authenticate` are replaced by emergency-flow tests.

(The 8 dormant password accounts in prod `users.json` are unaffected — already unable to log in.
Stripping their `hashed_password` is a separate pending cleanup, not part of this feature.)

## Testing (pytest + TestClient; email mocked)

**request:**
- admin email → 200 generic body, code file written, `send_emergency_code` called once.
- non-admin email → 200 generic body, **no** code file, `send_emergency_code` **not** called.
- cooldown: a second immediate admin request does not overwrite/re-send (within cooldown).

**verify:**
- correct code → 200, returns a JWT that decodes to the admin (role admin); code file deleted.
- wrong code → 400 generic, `attempts` incremented.
- expired code → 400 generic.
- attempts exhausted → code burned (file deleted); subsequent correct code → 400.
- single-use: reusing a consumed code → 400.

Frontend: typecheck only (`npx tsc -b --noEmit`; no frontend test suite).

## Deploy / rollout prerequisites

1. **Resend account** + API key. Verify a sending domain (SPF/DKIM DNS at the hello.co panel for
   `heltonmaia.com`) so mail to `@ufrn.br` isn't spam-filtered; interim, Resend's onboarding
   domain can be used for a first smoke test.
2. Set in `.env.prod`: `RESEND_API_KEY`, `EMAIL_FROM`, `EMERGENCY_ADMIN_EMAIL` (the owner's email).
3. Deploy (`./scripts/deploy.sh`). **Verify end-to-end**: request a code at `/emergency`, confirm
   it arrives, verify it logs in — before relying on it as the break-glass.
4. `httpx` (if chosen) is added to backend deps → the prod image rebuild picks it up (deploys
   always rebuild).

## Docs to update during implementation

- **SPEC.md** (product source of truth) — replace the password break-glass section with the
  emergency email-code flow. **Update SPEC.md first**, per repo convention.
- **CLAUDE.md** — auth pointers + footguns (new endpoints, `services/email.py`, removed
  `/auth/login`).
- **CLAUDE.local.md** — VPS: Resend key, `EMAIL_FROM`, sending-domain DNS, `EMERGENCY_ADMIN_EMAIL`.
- Memory: update `neolabel-prod-google-auth-no-breakglass` (the break-glass TODO is now this).

## Open defaults (chosen; easy to change in the plan)

6-digit code · 10-min TTL · 5 attempts · 60s cooldown · 60-min session · URL `/emergency` ·
password break-glass fully removed.
