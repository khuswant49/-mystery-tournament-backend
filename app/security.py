from itsdangerous import BadSignature, URLSafeTimedSerializer
from fastapi import Cookie, HTTPException, status

from app.config import ADMIN_PIN, COOKIE_SECRET

COOKIE_NAME = "mt_admin_session"
_MAX_AGE_SECONDS = 12 * 60 * 60  # 12 hours -- long enough to cover one event day

_serializer = URLSafeTimedSerializer(COOKIE_SECRET, salt="mt-admin")


def check_pin(pin: str) -> bool:
    return pin == ADMIN_PIN


def make_session_cookie() -> str:
    return _serializer.dumps({"admin": True})


def verify_session_cookie(value: str) -> bool:
    try:
        data = _serializer.loads(value, max_age=_MAX_AGE_SECONDS)
    except BadSignature:
        return False
    return bool(data.get("admin"))


def require_admin(mt_admin_session: str = Cookie(default=None)):
    """FastAPI dependency: raises 401 unless a valid admin session cookie is present."""
    if not mt_admin_session or not verify_session_cookie(mt_admin_session):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="admin login required")
    return True
