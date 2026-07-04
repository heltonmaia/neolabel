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
