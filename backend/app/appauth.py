"""App-level authentication: per-user accounts + signed cookie token.

Users live in the DB (bcrypt-hashed passwords). Login issues an HMAC-signed,
expiring token (itsdangerous) delivered as an httpOnly cookie so browser JS —
and thus XSS — can't read it. In-memory per-IP lockout throttles brute force.
Bootstrap: the env APP_USERNAME/APP_PASSWORD seeds the first user if the table
is empty.
"""
import os
import secrets
import time

import bcrypt
from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

APP_USERNAME = os.environ.get("APP_USERNAME", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "admin")
# If unset, generate a per-process secret: tokens then invalidate on restart
# (everyone re-logs in) but no signing key is ever committed/shipped.
APP_SECRET = os.environ.get("APP_SECRET") or secrets.token_urlsafe(32)
TOKEN_MAX_AGE = int(os.environ.get("APP_TOKEN_HOURS", "12")) * 3600
COOKIE_NAME = "aam_token"
COOKIE_SECURE = os.environ.get("APP_COOKIE_SECURE", "0") == "1"  # set behind TLS

# brute-force lockout
_MAX_FAILS = int(os.environ.get("APP_LOGIN_MAX_FAILS", "5"))
_WINDOW = int(os.environ.get("APP_LOGIN_LOCK_SECONDS", "900"))  # 15 min

_serializer = URLSafeTimedSerializer(APP_SECRET, salt="app-auth")
_fails: dict[str, list[float]] = {}


# ---- password hashing ------------------------------------------------

def hash_password(password: str) -> str:
    return bcrypt.hashpw(password.encode(), bcrypt.gensalt()).decode()


def verify_password(password: str, password_hash: str) -> bool:
    try:
        return bcrypt.checkpw(password.encode(), password_hash.encode())
    except (ValueError, TypeError):
        return False


# ---- tokens ----------------------------------------------------------

def issue_token(username: str) -> str:
    return _serializer.dumps({"u": username})


def token_user(token: str | None) -> str | None:
    """Return the username if the token is valid and unexpired, else None."""
    if not token:
        return None
    try:
        data = _serializer.loads(token, max_age=TOKEN_MAX_AGE)
        return data.get("u")
    except (BadSignature, SignatureExpired):
        return None


def valid_token(token: str | None) -> bool:
    return token_user(token) is not None


# ---- brute-force lockout --------------------------------------------

def is_locked(ip: str) -> bool:
    now = time.monotonic()
    recent = [t for t in _fails.get(ip, []) if now - t < _WINDOW]
    _fails[ip] = recent
    return len(recent) >= _MAX_FAILS


def record_failure(ip: str) -> None:
    _fails.setdefault(ip, []).append(time.monotonic())


def clear_failures(ip: str) -> None:
    _fails.pop(ip, None)
