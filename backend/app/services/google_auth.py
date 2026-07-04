"""Google ID-token verification (GIS ID-token flow).

Thin wrapper so the endpoint stays simple and tests can monkeypatch this
module without touching the network.
"""

from __future__ import annotations

from google.auth.transport import requests as google_requests
from google.oauth2 import id_token

from app.core.config import settings


def verify_google_id_token(credential: str) -> dict:
    """Verify a Google ID token; return its claims.

    Validates signature, issuer, audience (== GOOGLE_CLIENT_ID) and
    expiry. Raises ValueError on any invalid token.
    """
    return id_token.verify_oauth2_token(
        credential,
        google_requests.Request(),
        settings.GOOGLE_CLIENT_ID,
    )
