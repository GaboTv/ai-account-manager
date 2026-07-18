from app.adapters import AiPrimeTechAdapter, ClaudeAdapter, CodexAdapter, get_adapter, strip_ansi
import pytest


def test_aiprimetech_adapter():
    a = AiPrimeTechAdapter()
    assert a.provider == "aiprimetech"
    assert a.image == "ai-runner-claude:latest"  # reuses Claude CLI image
    assert a.uses_api_key is True
    # claude is wrapped in a shell that sources the env file first
    ic = a.interactive_command()
    assert ic[0] == "bash" and "source" in ic[2] and "exec claude" in ic[2]
    assert a.exec_command("hi")[-2:] == ["-p", "hi"]
    assert a.is_logged_in("LOGGED_IN\n", 0)
    assert not a.is_logged_in("NOT\n", 0)
    assert a.parse_auth_status("LOGGED_IN", 0) == {"method": "api-key", "base_url": "https://aiprimetech.io"}
    assert a.parse_auth_status("NOT", 0) == {}
    assert get_adapter("aiprimetech") is not None


def test_other_providers_not_api_key():
    assert ClaudeAdapter().uses_api_key is False
    assert CodexAdapter().uses_api_key is False


def test_claude_commands():
    a = ClaudeAdapter()
    assert a.login_command() == ["claude", "auth", "login"]
    assert a.auth_status_command() == ["claude", "auth", "status"]
    assert a.exec_command("hi") == ["claude", "-p", "hi"]
    assert a.interactive_command() == ["claude"]
    assert a.usage_slash_command() == "/usage"


def test_codex_commands():
    a = CodexAdapter()
    assert a.login_command() == ["codex", "login"]  # browser flow default
    assert a.login_command("device") == ["codex", "login", "--device-auth"]
    assert a.auth_status_command() == ["codex", "login", "status"]
    assert a.exec_command("hi") == ["codex", "exec", "hi"]
    assert a.status_slash_command() == "/status"


def test_setup_command_and_callback_flag():
    # Claude: interactive onboarding, no callback field (paste-back code).
    assert ClaudeAdapter().setup_command() == ["claude"]
    assert ClaudeAdapter().needs_callback_field is False
    # Codex: browser login serving localhost callback, needs the URL field.
    assert CodexAdapter().setup_command() == ["codex", "login"]
    assert CodexAdapter().needs_callback_field is True


def test_unsupported_provider():
    from app.errors import ApiError
    with pytest.raises(ApiError):
        get_adapter("gemini")


def test_claude_login_url_parse():
    out = "Open this URL to log in:\n  https://claude.ai/oauth/authorize?client_id=abc\nPaste the code here:"
    hint = ClaudeAdapter().parse_login_output(out)
    assert hint.login_url.startswith("https://claude.ai/oauth")
    assert hint.wants_code_input


def test_codex_device_code_parse():
    out = "\x1b[1mGo to https://auth.openai.com/device and enter code ABCD-EFGH\x1b[0m"
    hint = CodexAdapter().parse_login_output(out)
    assert hint.login_url == "https://auth.openai.com/device"
    assert hint.user_code == "ABCD-EFGH"
    assert hint.method == "device_code"


def test_strip_ansi():
    assert strip_ansi("\x1b[31mred\x1b[0m") == "red"


def test_claude_auth_status_parse():
    out = '{\n  "loggedIn": true,\n  "authMethod": "claude.ai",\n  "email": "x@y.com",\n  "orgName": "X Org",\n  "subscriptionType": "pro"\n}'
    info = ClaudeAdapter().parse_auth_status(out, 0)
    assert info == {"email": "x@y.com", "plan": "pro", "method": "claude.ai", "org": "X Org"}
    assert ClaudeAdapter().parse_auth_status("garbage", 0) == {}


def test_codex_auth_status_parse():
    assert CodexAdapter().parse_auth_status("Logged in using ChatGPT\n", 0) == {"method": "ChatGPT"}
    assert CodexAdapter().parse_auth_status("Not logged in", 1) == {}


def test_claude_usage_parse():
    out = (
        "\x1b[1m/usage\x1b[0m\n"
        "Current session   ████████░░░░░░░░ 47% used\n"
        "  Resets 11pm (America/La_Paz)\n"
        "Current week (all models)  ██░░░░░░ 12% used · Resets Jul 9, 10am\n"
    )
    limits = {l["label"]: l for l in ClaudeAdapter().parse_usage(out)["limits"]}
    assert limits["Current session"]["used_percent"] == 47
    week = limits["Current week (all models)"]
    assert week["used_percent"] == 12
    assert week["resets"].startswith("Jul 9")


def test_codex_status_parse():
    # Real /status layout (v0.142.5): "% left" semantics, plan after email.
    out = (
        "│  Model:                gpt-5.5 (reasoning medium, summaries auto)   │\n"
        "│  Account:              user@example.com (Plus)                      │\n"
        "│  5h limit:             [████████████████████] 99% left (resets 18:01)          │\n"
        "│  Weekly limit:         [████████████████░░░░] 82% left (resets 12:15 on 9 Jul) │\n"
    )
    parsed = CodexAdapter().parse_usage(out)
    limits = {l["label"]: l for l in parsed["limits"]}
    assert limits["5h limit"] == {"label": "5h limit", "used_percent": 1, "resets": "18:01"}
    assert limits["Weekly limit"]["used_percent"] == 18
    assert limits["Weekly limit"]["resets"] == "12:15 on 9 Jul"
    assert parsed["account"]["plan"] == "Plus"
    assert parsed["account"]["email"] == "user@example.com"
    assert parsed["account"]["model"] == "gpt-5.5"


def test_used_variant_not_inverted():
    out = "5h limit [██░░] 38% used (resets 14:32)\n"
    limits = CodexAdapter().parse_usage(out)["limits"]
    assert limits[0]["used_percent"] == 38


def test_claude_usage_parse_multiline_layout():
    # Real layout captured live: label, then bar+pct, then Resets, per gauge.
    out = (
        "Usage:                 0 input, 0 output\n"
        "Current session\n"
        "███████████████░░░░░░░░               69%used\n"
        "Resets 2:29pm (UTC)\n"
        "Current week (all models)\n"
        "██████████░░░░░░░░░░                  52%used\n"
        "Resets Jul 8, 2:59am (UTC)\n"
        "Current week (Fable)\n"
        "████████████████████████████████░░   96%used\n"
        "Resets Jul 8, 2:59am (UTC)\n"
    )
    limits = {l["label"]: l for l in ClaudeAdapter().parse_usage(out)["limits"]}
    assert limits["Current session"] == {
        "label": "Current session", "used_percent": 69, "resets": "2:29pm",
    }
    assert limits["Current week (all models)"]["used_percent"] == 52
    assert limits["Current week (all models)"]["resets"] == "Jul 8, 2:59am"
    assert limits["Current week (Fable)"]["used_percent"] == 96


def test_usage_parse_garbage_is_empty():
    assert ClaudeAdapter().parse_usage("no percentages here")["limits"] == []


def test_logged_in_heuristic():
    a = ClaudeAdapter()
    assert a.is_logged_in("Logged in as x@y.com", 0)
    assert not a.is_logged_in("Not logged in", 1)
    assert not a.is_logged_in("You are not logged in", 0)


def test_grok_adapter():
    from app.adapters import GrokAdapter
    a = GrokAdapter()
    assert a.provider == "grok"
    assert a.image == "ai-runner-grok:latest"
    assert a.login_command() == ["grok", "login", "--device-auth"]
    assert a.setup_command() == ["grok", "login", "--device-auth"]
    assert a.needs_callback_field is False
    assert a.exec_command("hi") == ["grok", "-p", "hi"]
    assert a.interactive_command() == ["grok"]
    assert a.usage_slash_command() == "/usage"
    assert a.is_logged_in("LOGGED_IN user@x.com credentials\n", 0)
    assert not a.is_logged_in("NOT\n", 0)
    assert a.auth_status_command()[0] == "node"
    assert a.parse_auth_status("LOGGED_IN user@x.com credentials", 0) == {
        "email": "user@x.com", "method": "credentials"}
    assert a.parse_auth_status("NOT", 0) == {}
    assert get_adapter("grok") is not None


def test_grok_login_parse():
    # Verbatim `grok login --device-auth` output (grok 0.2.103).
    out = (
        "\nTo sign in, open this URL in your browser:\n\n"
        "  https://accounts.x.ai/oauth2/device?user_code=WW6A-3NFW\n\n"
        "  (Could not open browser automatically — open the URL above manually.)\n\n"
        "Confirm this code in your browser:\n\n  WW6A-3NFW\n\n"
        "Waiting for authorization...\n"
    )
    from app.adapters import GrokAdapter
    hint = GrokAdapter().parse_login_output(out)
    assert hint.login_url == "https://accounts.x.ai/oauth2/device?user_code=WW6A-3NFW"
    assert hint.user_code == "WW6A-3NFW"
    assert hint.method == "device_code"
    assert hint.wants_code_input is False


def test_grok_usage_parse():
    # Panel text as rendered by `/usage show` (grok 0.2.103, real capture).
    from app.adapters import GrokAdapter
    out = "  Weekly limit: 13%\n  Next reset: July 21, 20:16\n"
    parsed = GrokAdapter().parse_usage(out)
    assert parsed["limits"] == [
        {"label": "Weekly limit", "used_percent": 13, "resets": "July 21, 20:16"}
    ]
