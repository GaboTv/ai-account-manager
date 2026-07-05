"""App-level authentication: a single admin credential + signed bearer token.

Deliberately minimal — this is a self-hosted single-operator control plane, not
a multi-tenant service. One username/password (from env), HMAC-signed tokens with
an expiry (via itsdangerous). No user table, no roles.
"""
import hmac
import os
import secrets

from itsdangerous import BadSignature, SignatureExpired, URLSafeTimedSerializer

APP_USERNAME = os.environ.get("APP_USERNAME", "admin")
APP_PASSWORD = os.environ.get("APP_PASSWORD", "admin")
# If unset, generate a per-process secret: tokens then invalidate on restart
# (everyone re-logs in) but no signing key is ever committed/shipped.
APP_SECRET = os.environ.get("APP_SECRET") or secrets.token_urlsafe(32)
TOKEN_MAX_AGE = int(os.environ.get("APP_TOKEN_HOURS", "12")) * 3600

_serializer = URLSafeTimedSerializer(APP_SECRET, salt="app-auth")


def check_credentials(username: str, password: str) -> bool:
    # constant-time compares to avoid leaking length/timing
    return hmac.compare_digest(username or "", APP_USERNAME) and hmac.compare_digest(
        password or "", APP_PASSWORD
    )


def issue_token(username: str) -> str:
    return _serializer.dumps({"u": username})


def valid_token(token: str | None) -> bool:
    if not token:
        return False
    try:
        _serializer.loads(token, max_age=TOKEN_MAX_AGE)
        return True
    except (BadSignature, SignatureExpired):
        return False
