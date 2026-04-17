from slowapi import Limiter
from starlette.requests import Request


def _client_ip(request: Request) -> str:
    # Trust X-Forwarded-For from our own nginx: backend only listens on
    # the compose network (no ports: mapping), so external clients cannot
    # set this header directly.
    forwarded = request.headers.get("X-Forwarded-For")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


limiter = Limiter(key_func=_client_ip)
