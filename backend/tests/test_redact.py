from app.redact import redact, REDACTED


def test_redacts_anthropic_key():
    assert "sk-ant" not in redact("token: sk-ant-api03-abcdefghijklmnop")


def test_redacts_oauth_code_in_url():
    out = redact("https://localhost:8000/cb?code=SECRET123&state=x")
    assert "SECRET123" not in out
    assert "code=" in out  # prefix kept for readability


def test_redacts_bearer():
    assert "abc.def" not in redact("Authorization: Bearer abc.def")


def test_redacts_jwt():
    jwt = "eyJhbGciOiJIUzI1NiIs.eyJzdWIiOiIxMjM0NTY3ODkwIn0.dozjgNryP4J3jVmNHl0w5N"
    assert REDACTED in redact(f"got {jwt}")


def test_plain_text_untouched():
    assert redact("hello world") == "hello world"
    assert redact(None) is None
