"""Transactional email via Resend (HTTPS API).

Kept thin so tests can patch the outbound call without touching the network.
Resend (not SMTP) because the Contabo VPS blocks outbound SMTP ports.
"""
from __future__ import annotations

import requests

from app.core.config import settings

_RESEND_ENDPOINT = "https://api.resend.com/emails"


def send_emergency_code(to: str, code: str) -> None:
    """Email a one-time access code. Raises on transport failure; the caller
    decides whether to surface or swallow it."""
    resp = requests.post(
        _RESEND_ENDPOINT,
        headers={"Authorization": f"Bearer {settings.RESEND_API_KEY}"},
        json={
            "from": settings.EMAIL_FROM,
            "to": [to],
            "subject": "Your NeoLabel access code",
            "text": (
                f"Your one-time NeoLabel access code is {code}.\n"
                f"It expires in {settings.EMERGENCY_CODE_TTL_MINUTES} minutes.\n"
                "If you didn't request this, you can ignore this email."
            ),
        },
        timeout=10,
    )
    resp.raise_for_status()
