from app.core import storage


def test_next_id_monotonic_per_kind():
    assert storage.next_id("users") == 1
    assert storage.next_id("users") == 2
    assert storage.next_id("projects") == 1
    assert storage.next_id("users") == 3


def test_users_persist_roundtrip():
    assert storage.load_users() == []
    storage.save_users([{"id": 1, "username": "a"}])
    assert storage.load_users() == [{"id": 1, "username": "a"}]


def test_project_save_load_delete():
    storage.save_project({"id": 1, "name": "p1", "owner_id": 7})
    assert storage.load_project(1) == {"id": 1, "name": "p1", "owner_id": 7}
    storage.delete_project(1)
    assert storage.load_project(1) is None


def test_list_projects_empty_and_populated():
    assert storage.list_projects() == []
    storage.save_project({"id": 1, "name": "a", "created_at": "2026-01-01"})
    storage.save_project({"id": 2, "name": "b", "created_at": "2026-02-01"})
    listed = storage.list_projects()
    # Newest first
    assert [p["id"] for p in listed] == [2, 1]


def test_items_save_load_and_list_sorted():
    storage.save_project({"id": 1, "name": "p"})
    storage.save_item({"id": 10, "project_id": 1, "payload": {"text": "a"}})
    storage.save_item({"id": 5, "project_id": 1, "payload": {"text": "b"}})
    assert storage.load_item(1, 10)["payload"] == {"text": "a"}
    ids = [i["id"] for i in storage.list_items(1)]
    assert ids == [5, 10]


def test_find_item_searches_across_projects():
    storage.save_project({"id": 1})
    storage.save_project({"id": 2})
    storage.save_item({"id": 99, "project_id": 2, "payload": {}})
    found = storage.find_item(99)
    assert found and found["project_id"] == 2
    assert storage.find_item(12345) is None


def test_annotation_roundtrip():
    storage.save_project({"id": 1})
    storage.save_annotation(
        1, {"item_id": 5, "annotator_id": 3, "value": {"label": "cat"}}
    )
    got = storage.load_annotation(1, 5, 3)
    assert got["value"] == {"label": "cat"}
    assert storage.load_annotation(1, 5, 999) is None


def test_list_annotations_for_project():
    storage.save_project({"id": 1})
    storage.save_annotation(1, {"item_id": 1, "annotator_id": 1, "value": {}})
    storage.save_annotation(1, {"item_id": 2, "annotator_id": 1, "value": {}})
    assert len(storage.list_annotations_for_project(1)) == 2


def test_atomic_write_no_tmp_leftover(tmp_path):
    # After a successful save, no .tmp file should remain
    storage.save_project({"id": 1, "name": "x"})
    leftovers = list(tmp_path.rglob("*.tmp"))
    assert leftovers == []
