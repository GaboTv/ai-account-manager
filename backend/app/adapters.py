"""Provider adapters. ALL provider-CLI-specific knowledge lives here.

Terminal output parsing is brittle by nature: CLI versions change their
wording. Every regex here is best-effort and versioned against the CLI
releases current as of writing. When parsing fails, the raw output is still
streamed to the user, so the flow degrades to "user reads terminal" rather
than breaking.
"""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LoginHint:
    """What we managed to parse out of the login flow output."""
    login_url: str | None = None
    user_code: str | None = None
    method: str = "browser"  # browser | device_code
    wants_code_input: bool = False


class AIProviderAdapter(ABC):
    provider: str
    image: str
    # Where the CLI's local OAuth callback server listens during browser
    # login, if the provider has one. Used to validate pasted callback URLs.
    callback_port: int | None = None
    callback_path: str | None = None

    @abstractmethod
    def login_command(self, method: str | None = None) -> list[str]: ...

    @abstractmethod
    def auth_status_command(self) -> list[str]: ...

    @abstractmethod
    def logout_command(self) -> list[str]: ...

    @abstractmethod
    def interactive_command(self, initial_prompt: str | None = None) -> list[str]: ...

    def setup_command(self) -> list[str]:
        """Command launched in the guided setup wizard's terminal, where the
        user drives onboarding + login by hand. Defaults to the interactive
        CLI (Claude: theme/account/login onboarding). Overridden where the
        login has its own command (Codex browser login)."""
        return self.interactive_command()

    # Does this provider's browser login redirect to a localhost callback the
    # backend must forward into the container? (Codex yes, Claude no — Claude
    # uses paste-back code, done directly in the terminal.)
    needs_callback_field: bool = False

    @abstractmethod
    def exec_command(self, prompt: str) -> list[str]: ...

    @abstractmethod
    def usage_slash_command(self) -> str: ...

    @abstractmethod
    def status_slash_command(self) -> str: ...

    @abstractmethod
    def parse_login_output(self, text: str) -> LoginHint: ...

    def is_logged_in(self, status_output: str, exit_code: int) -> bool:
        """Default heuristic: trust exit code, fall back to text sniffing."""
        if exit_code == 0 and not re.search(r"not\s+logged\s+in", status_output, re.I):
            return True
        return False

    def parse_auth_status(self, output: str, exit_code: int) -> dict:
        """Best-effort structured fields (email, plan, …) from auth status
        output. Empty dict when parsing fails — raw output is still shown."""
        return {}

    # First-run TUI prompts to auto-answer during headless capture
    # (trust-folder dialogs, theme pickers). (regex, keystrokes) pairs,
    # applied only while waiting for the TUI to become ready.
    capture_responders: list[tuple[str, bytes]] = []

    def usage_capture_command(self) -> str:
        """Slash command whose TUI output carries limits/reset info."""
        return self.usage_slash_command()

    def parse_usage(self, text: str) -> dict:
        """Extract limit gauges from TUI output.

        Handles both layouts seen in the wild:
          one-line:   "5h limit [██░░] 38% used (resets 14:32)"
          multi-line: "Current session" / "████░░  69%used" / "Resets 2:29pm (UTC)"
        TUI output is unstable by definition — tolerant parsing, last redraw
        wins, and callers always keep the raw text as fallback.
        """
        limits: dict[str, dict] = {}
        pending: str | None = None  # bare label line waiting for its % line
        last_key: str | None = None
        for raw_line in strip_ansi(text).splitlines():
            line = raw_line.strip(" \t│|╭╰╮╯─")
            if not line:
                continue
            pct_m = _PCT_RE.search(line)
            if pct_m and int(pct_m.group(1)) <= 100:
                label_m = _LABEL_RE.match(line[: pct_m.start()].strip())
                label = (label_m.group(0).strip() if label_m else "") or (pending or "")
                if len(label) >= 2:
                    pct = int(pct_m.group(1))
                    # codex says "99% left", claude says "69%used" — normalize
                    if re.match(r"\s*(left|remaining)", line[pct_m.end():], re.I):
                        pct = 100 - pct
                    entry = {"label": label, "used_percent": pct}
                    if r := _RESET_RE.search(line[pct_m.end():]):
                        entry["resets"] = _clean_when(r["when"])
                    last_key = label.lower()
                    limits[last_key] = entry
                pending = None
            elif r := _RESET_RE.search(line):
                if last_key and "resets" not in limits[last_key]:
                    limits[last_key]["resets"] = _clean_when(r["when"])
                pending = None
            elif re.match(r"[A-Za-z]", line) and len(line) <= 60:
                pending = line  # possible label for the next gauge line
            else:
                pending = None
        out = {"limits": list(limits.values())}
        # Session-level stats (the only thing token-billed proxies like
        # aiprimetech report via /usage): cost + token counts. TUI strips
        # spaces, so allow "Totalcost:$0" and "Usage: 0 input, 0 output".
        clean = strip_ansi(text)
        session = {}
        if m := re.search(r"Total\s*cost:\s*\$([\d.]+)", clean):
            session["cost_usd"] = float(m.group(1))
        if m := re.search(r"Usage:\s*([\d,]+)\s*input,\s*([\d,]+)\s*output", clean):
            session["input_tokens"] = int(m.group(1).replace(",", ""))
            session["output_tokens"] = int(m.group(2).replace(",", ""))
        if session:
            out["session"] = session
        return out


_URL_RE = re.compile(r"https://[^\s\x1b\"'<>]+")
_PCT_RE = re.compile(r"(\d{1,3})\s*%")
_LABEL_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9 ()\-]*")
_RESET_RE = re.compile(r"[Rr]esets?\s*:?\s*(?P<when>[^)\n│]+)")


def _clean_when(s: str) -> str:
    # drop an unbalanced trailing "(UTC" / "(America/…" fragment
    return re.sub(r"\s*\([^)]*$", "", s.strip(" .│|"))
# ANSI escape sequences pollute PTY output before parsing.
_ANSI_RE = re.compile(r"\x1b\[[0-9;?]*[a-zA-Z]|\x1b\][^\x07]*\x07")


def strip_ansi(text: str) -> str:
    return _ANSI_RE.sub("", text)


class ClaudeAdapter(AIProviderAdapter):
    provider = "claude"
    image = "ai-runner-claude:latest"

    def login_command(self, method=None):
        return ["claude", "auth", "login"]

    def auth_status_command(self):
        return ["claude", "auth", "status"]

    def logout_command(self):
        return ["claude", "auth", "logout"]

    def interactive_command(self, initial_prompt=None):
        return ["claude", initial_prompt] if initial_prompt else ["claude"]

    def exec_command(self, prompt):
        return ["claude", "-p", prompt]

    def usage_slash_command(self):
        return "/usage"

    def status_slash_command(self):
        return "/status"

    # First-run onboarding answers: dark mode theme, subscription login.
    # Pickers confirm on the digit alone — no \r, or the stray Enter lands
    # in the next prompt (observed: empty submit at "Paste code here").
    capture_responders = [
        (r"choose the text style|text style that looks best", b"2"),  # dark mode
        (r"select login method", b"1"),  # Claude subscription account
        (r"trust the files|do you trust", b"\r"),
        (r"press enter to continue", b"\r"),
    ]

    def parse_auth_status(self, output, exit_code):
        # `claude auth status` prints JSON: loggedIn, authMethod, email,
        # orgName, subscriptionType.
        import json

        m = re.search(r"\{.*\}", strip_ansi(output), re.S)
        if not m:
            return {}
        try:
            data = json.loads(m.group(0))
        except ValueError:
            return {}
        fields = {
            "email": data.get("email"),
            "plan": data.get("subscriptionType"),
            "method": data.get("authMethod"),
            "org": data.get("orgName"),
        }
        return {k: v for k, v in fields.items() if v}

    # UNCERTAIN: exact wording of `claude auth login` output varies by
    # version. In a headless container the CLI prints an OAuth URL and then
    # prompts for a paste-back authorization code.
    _CODE_PROMPT_RE = re.compile(r"paste (the )?code|authorization code", re.I)

    def parse_login_output(self, text: str) -> LoginHint:
        text = strip_ansi(text)
        hint = LoginHint(method="browser")
        urls = [
            u for u in _URL_RE.findall(text)
            if "anthropic" in u or "claude.ai" in u or "claude.com" in u
        ]
        if urls:
            hint.login_url = urls[0].rstrip(".,)")
        if self._CODE_PROMPT_RE.search(text):
            hint.wants_code_input = True
        return hint


class CodexAdapter(AIProviderAdapter):
    provider = "codex"
    image = "ai-runner-codex:latest"
    callback_port = 1455
    callback_path = "/auth/callback"
    needs_callback_field = True

    def setup_command(self):
        # Browser login serves the localhost:1455 callback inside the
        # container; the wizard forwards the pasted callback URL to it.
        return ["codex", "login"]

    def login_command(self, method=None):
        # Device auth is gated by OpenAI (429 unless the workspace enables
        # it), so browser flow is the default: the CLI serves a callback on
        # localhost:1455 inside the container and the user pastes the
        # redirect URL back into the app, which forwards it to that server.
        if method == "device":
            return ["codex", "login", "--device-auth"]
        return ["codex", "login"]

    def auth_status_command(self):
        return ["codex", "login", "status"]

    def logout_command(self):
        return ["codex", "logout"]

    def interactive_command(self, initial_prompt=None):
        return ["codex", initial_prompt] if initial_prompt else ["codex"]

    def exec_command(self, prompt):
        return ["codex", "exec", prompt]

    def usage_slash_command(self):
        return "/usage daily"

    def status_slash_command(self):
        return "/status"

    def parse_auth_status(self, output, exit_code):
        # `codex login status` prints e.g. "Logged in using ChatGPT".
        m = re.search(r"Logged in using (.+)", strip_ansi(output))
        return {"method": m.group(1).strip()} if m else {}

    capture_responders = [
        (r"do you trust|trust this (folder|directory)|without asking", b"\r"),
    ]

    def usage_capture_command(self):
        # /status carries the 5h + weekly limit bars, resets, plan, model.
        return "/status"

    def parse_usage(self, text):
        out = super().parse_usage(text)
        clean = strip_ansi(text)
        account = {}
        # "Account: user@example.com (Plus)"
        if m := re.search(r"Account:\s*\S+\s*\(([^)]+)\)", clean):
            account["plan"] = m.group(1).strip()
        elif m := re.search(r"Plan:\s*([A-Za-z][A-Za-z ]*)", clean):
            account["plan"] = m.group(1).strip()
        if m := re.search(r"[\w.+-]+@[\w-]+\.[\w.-]+", clean):
            account["email"] = m.group(0)
        if m := re.search(r"Model:\s*([^\n│(]+)", clean, re.I):
            account["model"] = m.group(1).strip()
        if account:
            out["account"] = account
        return out

    # UNCERTAIN: device-code format assumed XXXX-XXXX style.
    _USER_CODE_RE = re.compile(r"\b([A-Z0-9]{4,8}-[A-Z0-9]{4,8})\b")

    def parse_login_output(self, text: str) -> LoginHint:
        text = strip_ansi(text)
        hint = LoginHint(method="browser")
        urls = _URL_RE.findall(text)
        if urls:
            hint.login_url = urls[0].rstrip(".,)")
        m = self._USER_CODE_RE.search(text)
        if m:
            hint.user_code = m.group(1)
            hint.method = "device_code"
        return hint


class GrokAdapter(AIProviderAdapter):
    """Grok Build (xAI), npm `@xai-official/grok`, binary `grok`.

    Login is a pure device-code flow: `grok login --device-auth` prints
    `https://accounts.x.ai/oauth2/device?user_code=XXXX-XXXX` plus the code,
    then polls until the user confirms in the browser — no paste-back and no
    localhost callback. Versioned against grok 0.2.103.
    """
    provider = "grok"
    image = "ai-runner-grok:latest"

    def login_command(self, method=None):
        # The default browser flow needs a local browser; device-auth is the
        # only flow that works from a headless container.
        return ["grok", "login", "--device-auth"]

    def setup_command(self):
        return ["grok", "login", "--device-auth"]

    # grok 0.2.x has no `login status`-style command; ~/.grok/auth.json is
    # the signal (verified against a real login: keyed by issuer::client_id,
    # entries carry email/auth_mode/refresh_token). Print only non-secret
    # fields — node ships in the runner image.
    _STATUS_JS = (
        'try{const a=require(process.env.HOME+"/.grok/auth.json");'
        'const e=Object.values(a)[0]||{};'
        'console.log((e.refresh_token||e.key)?'
        '"LOGGED_IN "+(e.email||"")+" "+(e.auth_mode||""):"NOT")}'
        'catch{console.log("NOT")}'
    )

    def auth_status_command(self):
        return ["node", "-e", self._STATUS_JS]

    def is_logged_in(self, output, exit_code):
        return "LOGGED_IN" in output

    def parse_auth_status(self, output, exit_code):
        m = re.search(r"LOGGED_IN\s*(\S*)\s*(\S*)", strip_ansi(output))
        if not m:
            return {}
        fields = {"email": m.group(1), "method": m.group(2) or "device-oauth"}
        return {k: v for k, v in fields.items() if v}

    def logout_command(self):
        return ["grok", "logout"]

    def interactive_command(self, initial_prompt=None):
        return ["grok", initial_prompt] if initial_prompt else ["grok"]

    def exec_command(self, prompt):
        return ["grok", "-p", prompt]  # single-turn, prints and exits

    def usage_slash_command(self):
        # Bare "/usage" opens a show|manage submenu; "show" renders the panel
        # ("Weekly limit: N%" + "Next reset: <date>").
        return "/usage show"

    def status_slash_command(self):
        # No separate /status in the TUI; the usage panel is the status.
        return "/usage show"

    capture_responders = [
        (r"do you trust|trust this (folder|directory)|without asking", b"\r"),
    ]

    def parse_usage(self, text):
        # Grok's TUI redraws via cursor moves, not newlines, so after ANSI
        # stripping the panel collapses into one long line the generic
        # line-based parser can't segment. Match the panel fields directly:
        # "Weekly limit: 13%" ... "Next reset: July 21, 20:16".
        out = super().parse_usage(text)
        if not out.get("limits"):
            clean = strip_ansi(text)
            if m := re.search(r"Weekly limit:\s*(\d{1,3})\s*%", clean):
                entry = {"label": "Weekly limit", "used_percent": int(m.group(1))}
                if r := re.search(
                        r"Next reset:\s*([A-Za-z]+\s+\d{1,2},\s*\d{1,2}:\d{2})", clean):
                    entry["resets"] = r.group(1)
                out["limits"] = [entry]
        return out

    _USER_CODE_RE = re.compile(r"\b([A-Z0-9]{4,8}-[A-Z0-9]{4,8})\b")

    def parse_login_output(self, text: str) -> LoginHint:
        text = strip_ansi(text)
        hint = LoginHint(method="device_code")
        urls = [u for u in _URL_RE.findall(text) if "x.ai" in u]
        if urls:
            hint.login_url = urls[0].rstrip(".,)")
        if m := self._USER_CODE_RE.search(text):
            hint.user_code = m.group(1)
        return hint


class AiPrimeTechAdapter(ClaudeAdapter):
    """aiprimetech.io — a drop-in Claude API replacement using the same Claude
    Code CLI. No OAuth: auth is env vars (ANTHROPIC_BASE_URL,
    ANTHROPIC_AUTH_TOKEN, plus CLAUDE_CODE_* flags) written to an env file in
    the account's home volume. Every claude invocation is wrapped in a shell
    that sources that file first, so the vars are real environment variables.
    The token lives only in that protected volume, never in the DB.
    """
    provider = "aiprimetech"
    image = "ai-runner-claude:latest"  # same CLI as Claude
    base_url = "https://aiprimetech.io"
    uses_api_key = True
    env_file = ".aiprimetech.env"  # under $HOME

    def _wrap(self, *claude_args: str) -> list[str]:
        inner = 'source "$HOME/' + self.env_file + '" 2>/dev/null; exec claude "$@"'
        return ["bash", "-c", inner, "bash", *claude_args]

    def interactive_command(self, initial_prompt=None):
        return self._wrap(initial_prompt) if initial_prompt else self._wrap()

    def exec_command(self, prompt):
        return self._wrap("-p", prompt)

    def logout_command(self):
        return ["sh", "-c", f'rm -f "$HOME/{self.env_file}" && echo done']

    def auth_status_command(self):
        # "Logged in" == the API key is present in the volume's env file.
        return ["sh", "-c",
                f'grep -q ANTHROPIC_AUTH_TOKEN "$HOME/{self.env_file}" 2>/dev/null '
                '&& echo LOGGED_IN || echo NOT']

    def is_logged_in(self, output, exit_code):
        return "LOGGED_IN" in output

    def parse_auth_status(self, output, exit_code):
        return {"method": "api-key", "base_url": self.base_url} if "LOGGED_IN" in output else {}


# base flag so other adapters report False
AIProviderAdapter.uses_api_key = False


ADAPTERS: dict[str, AIProviderAdapter] = {
    "claude": ClaudeAdapter(),
    "codex": CodexAdapter(),
    "aiprimetech": AiPrimeTechAdapter(),
    "grok": GrokAdapter(),
}


def get_adapter(provider: str) -> AIProviderAdapter:
    try:
        return ADAPTERS[provider]
    except KeyError:
        from .errors import ApiError
        raise ApiError("UNSUPPORTED_PROVIDER", f"Unknown provider: {provider}", 400)
