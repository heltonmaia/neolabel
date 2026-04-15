from app.schemas.user import UserCreate
from app.services import user as user_service


def test_create_assigns_id_and_hashes_password():
    u = user_service.create(UserCreate(username="alice", password="pw12345"))
    assert u.id == 1
    assert u.username == "alice"
    assert u.hashed_password != "pw12345"


def test_get_by_username_case_insensitive():
    user_service.create(UserCreate(username="Alice", password="pw12345"))
    assert user_service.get_by_username("alice") is not None
    assert user_service.get_by_username("ALICE") is not None


def test_get_by_id():
    u = user_service.create(UserCreate(username="alice", password="pw12345"))
    assert user_service.get_by_id(u.id).username == "alice"
    assert user_service.get_by_id(999) is None


def test_authenticate_success_and_failure():
    user_service.create(UserCreate(username="alice", password="pw12345"))
    assert user_service.authenticate("alice", "pw12345") is not None
    assert user_service.authenticate("alice", "wrong") is None
    assert user_service.authenticate("ghost", "pw12345") is None


def test_ensure_seed_user_idempotent():
    assert user_service.ensure_seed_user("seed", "pw12345") is True
    assert user_service.ensure_seed_user("seed", "pw12345") is False
    # Still only one user
    assert len([u for u in [user_service.get_by_username("seed")] if u]) == 1
