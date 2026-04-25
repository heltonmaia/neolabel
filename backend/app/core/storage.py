"""Filesystem-backed storage.

Layout under DATA_DIR:

    users.json                         -> list[UserRecord]
    _counters.json                     -> {users, projects, items, annotations}
    projects/<pid>/project.json        -> ProjectRecord (includes labels)
    projects/<pid>/items/<iid>.json    -> ItemRecord
    projects/<pid>/annotations/
        <iid>__<uid>.json              -> AnnotationRecord

Single-process safety only. Good enough for dev / small deployments.
"""
from __future__ import annotations

import json
import os
import threading
import uuid
from pathlib import Path
from typing import Any

from app.core.config import settings

_LOCK = threading.Lock()


def _root() -> Path:
    p = Path(settings.DATA_DIR)
    p.mkdir(parents=True, exist_ok=True)
    return p


def _projects_dir() -> Path:
    d = _root() / "projects"
    d.mkdir(exist_ok=True)
    return d


def project_dir(pid: int) -> Path:
    return _projects_dir() / str(pid)


def _read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    # Per-call unique suffix so concurrent writes to the same target don't
    # race on the tmp file — each thread renames its own sibling into place.
    tmp = path.with_suffix(f"{path.suffix}.{uuid.uuid4().hex}.tmp")
    tmp.write_text(json.dumps(data, ensure_ascii=False, default=str, indent=2), encoding="utf-8")
    os.replace(tmp, path)


# ---------- counters ----------

_COUNTERS_FILE = lambda: _root() / "_counters.json"  # noqa: E731


def next_id(kind: str) -> int:
    with _LOCK:
        data = _read_json(_COUNTERS_FILE(), {})
        data[kind] = int(data.get(kind, 0)) + 1
        _write_json(_COUNTERS_FILE(), data)
        return data[kind]


# ---------- users ----------

_USERS_FILE = lambda: _root() / "users.json"  # noqa: E731


def load_users() -> list[dict]:
    return _read_json(_USERS_FILE(), [])


def save_users(users: list[dict]) -> None:
    _write_json(_USERS_FILE(), users)


# ---------- projects ----------

def load_project(pid: int) -> dict | None:
    f = project_dir(pid) / "project.json"
    return _read_json(f, None)


def save_project(project: dict) -> None:
    pid = project["id"]
    d = project_dir(pid)
    (d / "items").mkdir(parents=True, exist_ok=True)
    (d / "annotations").mkdir(parents=True, exist_ok=True)
    _write_json(d / "project.json", project)


def delete_project(pid: int) -> None:
    import shutil

    d = project_dir(pid)
    if d.exists():
        shutil.rmtree(d)


def list_projects() -> list[dict]:
    projects = []
    if not _projects_dir().exists():
        return []
    for d in _projects_dir().iterdir():
        if d.is_dir():
            p = _read_json(d / "project.json", None)
            if p:
                projects.append(p)
    projects.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return projects


# ---------- items ----------

def _items_dir(pid: int) -> Path:
    d = project_dir(pid) / "items"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_item(item: dict) -> None:
    _write_json(_items_dir(item["project_id"]) / f"{item['id']}.json", item)


def load_item(pid: int, iid: int) -> dict | None:
    return _read_json(_items_dir(pid) / f"{iid}.json", None)


def find_item(iid: int) -> dict | None:
    for d in _projects_dir().iterdir():
        if d.is_dir():
            f = d / "items" / f"{iid}.json"
            if f.exists():
                return _read_json(f, None)
    return None


def delete_item(pid: int, iid: int) -> bool:
    """Remove item JSON, any per-user annotation files, and the on-disk frame if present."""
    removed = False
    f = _items_dir(pid) / f"{iid}.json"
    item = _read_json(f, None)
    if f.exists():
        f.unlink()
        removed = True
    # Wipe associated annotations
    ann_dir = _annotations_dir(pid)
    for a in ann_dir.glob(f"{iid}__*.json"):
        a.unlink()
    # Wipe the frame file if it lives under DATA_DIR
    if item:
        url = (item.get("payload") or {}).get("image_url")
        if url and url.startswith("/files/"):
            frame = _root() / url[len("/files/"):]
            try:
                if frame.is_file() and _root() in frame.parents:
                    frame.unlink()
            except OSError:
                pass
    return removed


def list_items(pid: int) -> list[dict]:
    d = _items_dir(pid)
    items = [_read_json(f, None) for f in d.glob("*.json")]
    items = [i for i in items if i]
    items.sort(key=lambda i: i["id"])
    return items


# ---------- annotations ----------

def _annotations_dir(pid: int) -> Path:
    d = project_dir(pid) / "annotations"
    d.mkdir(parents=True, exist_ok=True)
    return d


def _ann_path(pid: int, iid: int, uid: int) -> Path:
    return _annotations_dir(pid) / f"{iid}__{uid}.json"


def load_annotation(pid: int, iid: int, uid: int) -> dict | None:
    return _read_json(_ann_path(pid, iid, uid), None)


def find_any_annotation_for_item(pid: int, iid: int) -> dict | None:
    """Return any annotation file that exists for this item, regardless of
    which user it's saved under. If multiple files exist (e.g. legacy data
    from before the assignee-canonicalization, or an item that was
    reassigned after being annotated), return the most recently updated.
    """
    d = _annotations_dir(pid)
    if not d.exists():
        return None
    candidates = [_read_json(p, None) for p in d.glob(f"{iid}__*.json")]
    candidates = [c for c in candidates if c]
    if not candidates:
        return None
    candidates.sort(key=lambda a: a.get("updated_at", ""), reverse=True)
    return candidates[0]


def save_annotation(pid: int, annotation: dict) -> None:
    _write_json(_ann_path(pid, annotation["item_id"], annotation["annotator_id"]), annotation)


def delete_annotations_for_item(pid: int, iid: int) -> int:
    d = _annotations_dir(pid)
    count = 0
    for a in d.glob(f"{iid}__*.json"):
        a.unlink()
        count += 1
    return count


def list_annotations_for_project(pid: int) -> list[dict]:
    d = _annotations_dir(pid)
    anns = [_read_json(f, None) for f in d.glob("*.json")]
    return [a for a in anns if a]
