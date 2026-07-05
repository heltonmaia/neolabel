def test_send_emergency_code_posts_to_resend(monkeypatch):
    from app.core.config import settings

    monkeypatch.setattr(settings, "RESEND_API_KEY", "re_test")
    monkeypatch.setattr(settings, "EMAIL_FROM", "NeoLabel <x@y.com>")

    captured = {}

    class FakeResp:
        def raise_for_status(self):
            return None

    def fake_post(url, headers=None, json=None, timeout=None):
        captured.update(url=url, headers=headers, json=json, timeout=timeout)
        return FakeResp()

    monkeypatch.setattr("app.services.email.requests.post", fake_post)

    from app.services.email import send_emergency_code

    send_emergency_code("owner@example.com", "123456")

    assert captured["url"] == "https://api.resend.com/emails"
    assert captured["headers"]["Authorization"] == "Bearer re_test"
    assert captured["json"]["from"] == "NeoLabel <x@y.com>"
    assert captured["json"]["to"] == ["owner@example.com"]
    assert "123456" in captured["json"]["text"]
    assert str(settings.EMERGENCY_CODE_TTL_MINUTES) in captured["json"]["text"]
