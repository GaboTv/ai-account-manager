import importlib
import os


def _fresh(username="admin", password="secret", secret="test-secret"):
    os.environ["APP_USERNAME"] = username
    os.environ["APP_PASSWORD"] = password
    os.environ["APP_SECRET"] = secret
    import app.appauth as appauth
    return importlib.reload(appauth)


def test_credentials():
    a = _fresh("admin", "secret")
    assert a.check_credentials("admin", "secret")
    assert not a.check_credentials("admin", "wrong")
    assert not a.check_credentials("root", "secret")
    assert not a.check_credentials("", "")


def test_token_roundtrip():
    a = _fresh()
    tok = a.issue_token("admin")
    assert a.valid_token(tok)
    assert not a.valid_token(None)
    assert not a.valid_token("garbage")
    assert not a.valid_token(tok + "x")  # tampered signature


def test_token_rejected_by_different_secret():
    a = _fresh(secret="secret-one")
    tok = a.issue_token("admin")
    b = _fresh(secret="secret-two")
    assert not b.valid_token(tok)  # signed with a different key
