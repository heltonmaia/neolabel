from app.core.security import (
    create_access_token,
    decode_token,
    hash_password,
    verify_password,
)


def test_hash_is_not_plaintext():
    h = hash_password("secret")
    assert h != "secret"
    assert h.startswith("$2")  # bcrypt prefix


def test_hash_is_salted_differently_each_time():
    assert hash_password("secret") != hash_password("secret")


def test_verify_accepts_correct_password():
    assert verify_password("secret", hash_password("secret"))


def test_verify_rejects_wrong_password():
    assert not verify_password("wrong", hash_password("secret"))


def test_verify_handles_malformed_hash():
    assert not verify_password("secret", "not-a-hash")


def test_token_roundtrip():
    token = create_access_token("42")
    assert decode_token(token) == "42"


def test_decode_invalid_token_returns_none():
    assert decode_token("garbage.token.value") is None


def test_decode_wrong_signature_returns_none():
    # Tamper: flip last char
    token = create_access_token("42")
    tampered = token[:-1] + ("A" if token[-1] != "A" else "B")
    assert decode_token(tampered) is None
