import importlib
import os


def _fresh(secret="test-secret", max_fails="3", lock="900"):
    os.environ["APP_SECRET"] = secret
    os.environ["APP_LOGIN_MAX_FAILS"] = max_fails
    os.environ["APP_LOGIN_LOCK_SECONDS"] = lock
    import app.appauth as appauth
    return importlib.reload(appauth)


def test_password_hash_roundtrip():
    a = _fresh()
    h = a.hash_password("s3cret")
    assert h != "s3cret" and h.startswith("$2")  # bcrypt hash, not plaintext
    assert a.verify_password("s3cret", h)
    assert not a.verify_password("wrong", h)
    assert not a.verify_password("s3cret", "not-a-hash")


def test_token_roundtrip_and_user():
    a = _fresh()
    tok = a.issue_token("alice")
    assert a.valid_token(tok)
    assert a.token_user(tok) == "alice"
    assert a.token_user(None) is None
    assert a.token_user("garbage") is None
    assert not a.valid_token(tok + "x")  # tampered


def test_token_rejected_by_different_secret():
    a = _fresh(secret="one")
    tok = a.issue_token("alice")
    b = _fresh(secret="two")
    assert not b.valid_token(tok)


def test_lockout_after_max_fails():
    a = _fresh(max_fails="3")
    ip = "1.2.3.4"
    assert not a.is_locked(ip)
    for _ in range(3):
        a.record_failure(ip)
    assert a.is_locked(ip)
    a.clear_failures(ip)  # success resets
    assert not a.is_locked(ip)
    # a different IP is unaffected
    a.record_failure(ip)
    assert not a.is_locked("9.9.9.9")
