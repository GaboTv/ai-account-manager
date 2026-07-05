from app.pty_manager import PtyManager, PtySession


class FakeDocker:
    def __init__(self):
        self.calls = []

    def exec_run(self, container, cmd, timeout=60):
        self.calls.append((container, cmd))
        return 0, ""


def _session(mgr, sid, account_id, status):
    s = PtySession(id=sid, account_id=account_id, mode="capture",
                   exec_id="e", sock=None, loop=None, status=status)
    mgr.sessions[sid] = s
    return s


def test_reaps_when_idle():
    mgr = PtyManager(FakeDocker())
    _session(mgr, "s1", "acct-A", "closed")  # a finished capture
    assert mgr.reap_orphans("acct-A", "ai-a") is True
    assert mgr.docker.calls == [("ai-a", ["pkill", "-9", "-f", "claude|codex|node"])]
    # closed session pruned from the map
    assert "s1" not in mgr.sessions


def test_skips_when_sibling_active():
    mgr = PtyManager(FakeDocker())
    _session(mgr, "s1", "acct-A", "active")  # user's live terminal
    assert mgr.reap_orphans("acct-A", "ai-a", exclude_session_id="s2") is False
    assert mgr.docker.calls == []  # never killed the sibling's process


def test_other_account_active_does_not_block():
    mgr = PtyManager(FakeDocker())
    _session(mgr, "s1", "acct-B", "active")  # different account, different container
    assert mgr.reap_orphans("acct-A", "ai-a") is True
    assert len(mgr.docker.calls) == 1
