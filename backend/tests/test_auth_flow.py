import pytest

from app.auth_flow import AuthFlowService
from app.errors import ApiError


class FakeDocker:
    def __init__(self):
        self.calls = []

    def exec_run(self, container, cmd, timeout=60):
        self.calls.append((container, cmd))
        return 0, "ok"


class FakePty:
    def __init__(self):
        self.docker = FakeDocker()


class Account:
    provider = "codex"
    container_name = "ai-codex-main"


def svc():
    return AuthFlowService(FakePty())


GOOD = "http://localhost:1455/auth/callback?code=abc&state=xyz"


def test_forwards_valid_callback():
    s = svc()
    s.forward_callback(Account(), GOOD)
    (container, cmd), = s.pty.docker.calls
    assert container == "ai-codex-main"
    assert cmd[-1] == "http://127.0.0.1:1455/auth/callback?code=abc&state=xyz"


@pytest.mark.parametrize("bad", [
    "http://evil.com:1455/auth/callback?code=x",          # wrong host
    "http://localhost:9999/auth/callback?code=x",         # wrong port
    "http://localhost:1455/other/path?code=x",            # wrong path
    "http://localhost:1455/auth/callback",                # no query
    "not a url",
])
def test_rejects_bad_callbacks(bad):
    s = svc()
    with pytest.raises(ApiError):
        s.forward_callback(Account(), bad)
    assert s.pty.docker.calls == []


def test_rejects_callback_for_provider_without_server():
    class ClaudeAccount:
        provider = "claude"
        container_name = "ai-claude-main"

    with pytest.raises(ApiError):
        svc().forward_callback(ClaudeAccount(), GOOD)
