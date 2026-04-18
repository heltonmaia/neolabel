"""Remove users from DATA_DIR/users.json that are not in seed_users.json.

The startup seeder (`main.py::seed_default_users`) is additive — users left
in the running store when an entry disappears from `seed_users.json` stay
around forever and pollute admin pickers. Run this after editing the seed
file to reconcile.

Usage (inside the backend container):

    docker compose exec backend python -m scripts.reconcile_seed_users
    docker compose exec backend python -m scripts.reconcile_seed_users --apply

Without `--apply` it's a dry run. `admin` is always preserved even if the
seed file drops it — it's too easy to lock yourself out otherwise.

Any items still referencing a removed user (via `assigned_to`) are
automatically unassigned — which is a valid state. Projects that had a
removed user as `owner_id` are printed; fix them by hand or delete the
project.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

# Allow running with `python backend/scripts/reconcile_seed_users.py` too.
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from app.core import storage  # noqa: E402
from app.core.config import settings  # noqa: E402


ALWAYS_KEEP = frozenset({"admin"})


def _seed_usernames(seed_path: Path) -> set[str]:
    entries = json.loads(seed_path.read_text(encoding="utf-8"))
    return {e["username"].lower() for e in entries}


def _orphaned_assignments(removed_ids: set[int]) -> list[tuple[int, int]]:
    """(project_id, item_id) pairs whose assigned_to is in removed_ids."""
    out: list[tuple[int, int]] = []
    for p in storage.list_projects():
        for item in storage.list_items(p["id"]):
            if item.get("assigned_to") in removed_ids:
                out.append((p["id"], item["id"]))
    return out


def _orphaned_projects(removed_ids: set[int]) -> list[tuple[int, int]]:
    """(project_id, owner_id) for projects whose owner is in removed_ids."""
    return [
        (p["id"], p["owner_id"])
        for p in storage.list_projects()
        if p.get("owner_id") in removed_ids
    ]


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument(
        "--seed-file",
        default=settings.SEED_USERS_FILE,
        help="Path to seed_users.json (default: from settings)",
    )
    ap.add_argument(
        "--apply", action="store_true", help="Actually write changes (default: dry run)"
    )
    args = ap.parse_args()

    seed_path = Path(args.seed_file)
    if not seed_path.is_absolute():
        seed_path = Path.cwd() / seed_path
    if not seed_path.exists():
        print(f"Seed file not found: {seed_path}", file=sys.stderr)
        return 2

    seed_names = _seed_usernames(seed_path) | ALWAYS_KEEP
    users = storage.load_users()
    keep = [u for u in users if u["username"].lower() in seed_names]
    removed = [u for u in users if u["username"].lower() not in seed_names]

    if not removed:
        print("Nothing to reconcile — users.json matches seed.")
        return 0

    removed_ids = {u["id"] for u in removed}
    orphan_items = _orphaned_assignments(removed_ids)
    orphan_projects = _orphaned_projects(removed_ids)

    print(f"Seed file: {seed_path}")
    print(f"Users to remove ({len(removed)}): {[u['username'] for u in removed]}")
    if orphan_items:
        print(
            f"  → {len(orphan_items)} item(s) will become unassigned "
            f"(assigned_to → null). Sample: {orphan_items[:5]}"
        )
    if orphan_projects:
        print(
            f"  ⚠ {len(orphan_projects)} project(s) have an orphan owner_id. "
            f"These aren't changed here — fix by hand:"
        )
        for pid, oid in orphan_projects:
            print(f"    project {pid}  owner_id={oid}")

    if not args.apply:
        print("\nDry run — re-run with --apply to commit.")
        return 0

    for pid, iid in orphan_items:
        item = storage.find_item(iid)
        if item:
            item["assigned_to"] = None
            storage.save_item(item)
    storage.save_users(keep)
    print(f"\nApplied. users.json now has {len(keep)} user(s).")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
