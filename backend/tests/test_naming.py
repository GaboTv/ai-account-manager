import re
from app.main import NAME_RE


def naming(name):  # mirrors create_account naming logic
    return f"ai-{name}", f"ai-{name}-home", f"ai-{name}-workspace"


def test_names():
    assert naming("claude-main") == (
        "ai-claude-main", "ai-claude-main-home", "ai-claude-main-workspace"
    )


def test_name_validation():
    assert NAME_RE.match("claude-main")
    assert not NAME_RE.match("Claude Main")
    assert not NAME_RE.match("-bad")
    assert not NAME_RE.match("a" * 60)
    assert not NAME_RE.match("x; rm -rf /")
