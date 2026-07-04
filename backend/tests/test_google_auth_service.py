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
