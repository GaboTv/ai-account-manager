"""Login-flow orchestration.

Flow: start login PTY in the account's container -> wait for the CLI to print
a login URL / device code -> return it to the frontend -> stream further
output over /ws/auth/{id} -> accept pasted codes via auth/input.

We never touch browser cookies, never intercept OAuth redirects ourselves,
and never extract tokens: the provider CLI completes its own flow and writes
its own auth files into the account's home volume. Device-code login is
preferred (Codex) because it needs no localhost callback at all.
"""
from __future__ import annotations

from dataclasses import dataclass, field

from .adapters import get_adapter, LoginHint
from .errors import ApiError


@dataclass
class AuthSession:
    pty_session_id: str
    account_id: str
    provider: str
    status: str = "starting"  # starting|waiting_for_user|success|failed|timeout
    hint: LoginHint = field(default_factory=LoginHint)


class AuthFlowService:
    def __init__(self, pty_manager):
        self.pty = pty_manager
        self.flows: dict[str, AuthSession] = {}  # keyed by pty session id

    async def start_login(self, account, method: str | None = None) -> dict:
        adapter = get_adapter(account.provider)
        session = self.pty.start(account, adapter.login_command(method), mode="login")
        flow = AuthSession(
            pty_session_id=session.id,
            account_id=str(account.id),
            provider=account.provider,
        )
        self.flows[session.id] = flow

        def has_hint(text: str) -> bool:
            return adapter.parse_login_output(text).login_url is not None

        try:
            text = await self.pty.wait_for(
                session.id, has_hint, timeout=90,
                responders=adapter.capture_responders,  # skip first-run onboarding
            )
        except ApiError as e:
            flow.status = "failed" if session.status != "active" else "timeout"
            # Surface what the CLI actually said (e.g. "429 Too Many
            # Requests") instead of a bare crash/timeout message.
            from .adapters import strip_ansi
            from .redact import redact

            tail = redact(strip_ansi(session.buffer.decode(errors="replace")))[-500:].strip()
            code = "LOGIN_FAILED" if e.code == "PTY_CRASHED" else e.code
            raise ApiError(
                code,
                f"Login command failed: {tail}" if tail else e.message,
                e.status,
                {"cli_output": tail},
            )
        flow.hint = adapter.parse_login_output(text)
        flow.status = "waiting_for_user"
        return {
            "status": flow.status,
            "provider": flow.provider,
            "method": flow.hint.method,
            "login_url": flow.hint.login_url,
            "user_code": flow.hint.user_code,
            "session_id": session.id,
        }

    def submit_input(self, auth_session_id: str, value: str, account=None):
        """User pasted an auth code — or, for browser flows, the full
        localhost callback URL their browser dead-ended on."""
        flow = self._get(auth_session_id)
        value = value.strip()
        if value.startswith(("http://localhost", "http://127.0.0.1")):
            self.forward_callback(account, value)
        else:
            self.pty.send_line(auth_session_id, value)
        flow.status = "verifying"

    def forward_callback(self, account, url: str):
        """Deliver a pasted OAuth callback URL to the CLI's own callback
        server inside the container.

        Only the exact host/port/path the provider CLI is known to listen on
        is accepted, and only for a login session this app started. The URL
        (which contains the auth code) is never logged; the CLI validates
        `state` itself and rejects codes from other sessions.
        """
        from urllib.parse import urlsplit

        adapter = get_adapter(account.provider)
        if not adapter.callback_port:
            raise ApiError("LOGIN_FAILED",
                           f"{account.provider} login has no callback server", 422)
        parts = urlsplit(url)
        if (
            parts.hostname not in ("localhost", "127.0.0.1")
            or (parts.port or 80) != adapter.callback_port
            or parts.path != adapter.callback_path
            or not parts.query
        ):
            raise ApiError(
                "LOGIN_FAILED",
                f"Not a recognized {account.provider} login callback URL "
                f"(expected localhost:{adapter.callback_port}{adapter.callback_path}?...)",
                422,
            )
        target = f"http://127.0.0.1:{adapter.callback_port}{parts.path}?{parts.query}"
        exit_code, output = self.pty.docker.exec_run(
            account.container_name, ["curl", "-fsS", "--max-time", "15", target]
        )
        if exit_code != 0:
            from .adapters import strip_ansi
            from .redact import redact

            raise ApiError(
                "LOGIN_FAILED",
                f"Callback delivery failed: {redact(strip_ansi(output))[:300]}",
                502,
            )

    async def check_result(self, auth_session_id: str, timeout: float = 120) -> str:
        """Wait for the login process to exit, then report success/failure."""
        flow = self._get(auth_session_id)
        session = self.pty.get(auth_session_id)

        def done(_: str) -> bool:
            return session.status != "active"

        try:
            await self.pty.wait_for(auth_session_id, done, timeout=timeout)
        except ApiError as e:
            if e.code == "PTY_CRASHED":
                pass  # process exited — inspect exit state below
            else:
                flow.status = "timeout"
                raise
        info = self.pty.docker.exec_inspect(session.exec_id)
        flow.status = "success" if info.get("ExitCode") == 0 else "failed"
        return flow.status

    def _get(self, auth_session_id: str) -> AuthSession:
        flow = self.flows.get(auth_session_id)
        if not flow:
            raise ApiError("SESSION_NOT_FOUND", f"No auth session {auth_session_id}", 404)
        return flow
