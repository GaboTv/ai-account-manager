"""PTY session manager.

One PtySession per interactive docker-exec (login flows, `claude`, `codex`).
A background thread reads the raw exec socket and fans chunks out to asyncio
subscriber queues (WebSocket clients, the auth-flow parser). A rolling buffer
lets late subscribers and parsers see recent output.

Kept out of HTTP controllers on purpose: routes only call start/write/
resize/close/subscribe.
"""
from __future__ import annotations

import asyncio
import re
import threading
import time
import uuid
from dataclasses import dataclass, field

from .errors import ApiError

BUFFER_MAX = 256 * 1024  # rolling output buffer per session


@dataclass
class PtySession:
    id: str
    account_id: str
    mode: str  # interactive | login
    exec_id: str
    sock: object
    loop: asyncio.AbstractEventLoop
    status: str = "active"  # active | closed | crashed
    buffer: bytes = b""
    subscribers: list[asyncio.Queue] = field(default_factory=list)
    created_at: float = field(default_factory=time.time)
    lock: threading.Lock = field(default_factory=threading.Lock)

    def _publish(self, chunk: bytes | None):
        """Called from reader thread. None = EOF."""
        with self.lock:
            if chunk is not None:
                self.buffer = (self.buffer + chunk)[-BUFFER_MAX:]
            queues = list(self.subscribers)
        for q in queues:
            self.loop.call_soon_threadsafe(q.put_nowait, chunk)

    def subscribe(self) -> asyncio.Queue:
        q: asyncio.Queue = asyncio.Queue()
        with self.lock:
            self.subscribers.append(q)
            snapshot = self.buffer
        if snapshot:
            q.put_nowait(snapshot)  # replay history so late joiners see context
        return q

    def unsubscribe(self, q: asyncio.Queue):
        with self.lock:
            if q in self.subscribers:
                self.subscribers.remove(q)

    def write(self, data: bytes):
        if self.status != "active":
            raise ApiError("PTY_CRASHED", "Session is no longer active", 409)
        self._raw_sock().sendall(data)

    def _raw_sock(self):
        # docker-py returns a SocketIO wrapper on Linux; unwrap to the real
        # socket for sendall/recv. ponytail: relies on docker-py internals —
        # pin docker-py version; revisit if upgrading.
        return getattr(self.sock, "_sock", self.sock)

    def close(self):
        self.status = "closed"
        try:
            self.sock.close()
        except OSError:
            pass


class PtyManager:
    def __init__(self, docker_service):
        self.docker = docker_service
        self.sessions: dict[str, PtySession] = {}

    def start(self, account, cmd: list[str], mode: str) -> PtySession:
        exec_id, sock = self.docker.exec_pty_create(account.container_name, cmd)
        session = PtySession(
            id=str(uuid.uuid4()),
            account_id=str(account.id),
            mode=mode,
            exec_id=exec_id,
            sock=sock,
            loop=asyncio.get_running_loop(),
        )
        self.sessions[session.id] = session
        threading.Thread(target=self._reader, args=(session,), daemon=True).start()
        return session

    def _reader(self, session: PtySession):
        raw = session._raw_sock()
        try:
            while True:
                chunk = raw.recv(4096)
                if not chunk:
                    break
                session._publish(chunk)
        except OSError:
            pass
        finally:
            info = {}
            try:
                info = self.docker.exec_inspect(session.exec_id)
            except Exception:
                pass
            exit_code = info.get("ExitCode")
            session.status = "closed" if exit_code in (0, None) else "crashed"
            session._publish(None)  # EOF marker to subscribers

    def get(self, session_id: str) -> PtySession:
        s = self.sessions.get(session_id)
        if not s:
            raise ApiError("SESSION_NOT_FOUND", f"No session {session_id}", 404)
        return s

    def send_line(self, session_id: str, text: str):
        """Send a message or slash command followed by Enter (CR for TUIs)."""
        self.get(session_id).write(text.encode() + b"\r")

    def resize(self, session_id: str, rows: int, cols: int):
        s = self.get(session_id)
        self.docker.exec_resize(s.exec_id, rows, cols)

    def close(self, session_id: str):
        s = self.get(session_id)
        s.close()

    async def run_slash_capture(
        self,
        account,
        cmd: list[str],
        slash_text: str,
        responders: tuple = (),
        quiet: float = 2.5,
        timeout: float = 90,
        post_wait: float = 0,
    ) -> str:
        """Headless TUI scrape: boot the CLI, auto-answer first-run prompts,
        type a slash command, wait for output to settle, return what was
        drawn after the command. Brittle by nature — callers must treat the
        result as best-effort and keep the raw text.
        """
        session = self.start(account, cmd, mode="capture")
        try:
            try:
                self.docker.exec_resize(session.exec_id, 40, 120)  # stable layout
            except Exception:
                pass
            await self._settle(session, responders, quiet=quiet, timeout=45)
            mark = len(session.buffer)
            session.write(slash_text.encode())
            await asyncio.sleep(0.6)  # let the command palette react before Enter
            session.write(b"\r")
            if post_wait:
                # Some panels fetch data from a server after opening (e.g.
                # aiprimetech /usage) — hold before settling so it can load.
                await asyncio.sleep(post_wait)
            await self._settle(session, (), quiet=quiet, timeout=timeout)
            return session.buffer[mark:].decode(errors="replace")
        finally:
            try:
                session.write(b"\x03\x03")  # double Ctrl+C exits both TUIs
            except Exception:
                pass
            session.close()

    async def _settle(self, session: PtySession, responders, quiet: float, timeout: float):
        """Wait until output has been quiet for `quiet` seconds. While
        waiting, answer any first-run prompt matching a responder (each fires
        once), which restarts the quiet clock."""
        from .adapters import strip_ansi

        q = session.subscribe()
        fired: set[str] = set()
        deadline = time.monotonic() + timeout
        try:
            while time.monotonic() < deadline:
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=quiet)
                except asyncio.TimeoutError:
                    text = strip_ansi(session.buffer.decode(errors="replace"))
                    answered = False
                    for pattern, keys in responders:
                        if pattern not in fired and re.search(pattern, text, re.I):
                            session.write(keys)
                            fired.add(pattern)
                            answered = True
                    if not answered:
                        return
                    continue
                if chunk is None:
                    return
        finally:
            session.unsubscribe(q)

    async def wait_for(self, session_id: str, predicate, timeout: float = 60,
                       responders: tuple = ()) -> str:
        """Wait until predicate(decoded_buffer) is truthy; returns the buffer.

        Used by the auth flow to wait for a login URL to appear. Any
        first-run prompt matching a responder is auto-answered (once each)
        so onboarding screens can't stall the wait.
        """
        from .adapters import strip_ansi

        s = self.get(session_id)
        q = s.subscribe()
        fired: set[str] = set()
        deadline = time.monotonic() + timeout
        try:
            while True:
                text = s.buffer.decode(errors="replace")
                for pattern, keys in responders:
                    if pattern not in fired and re.search(pattern, strip_ansi(text), re.I):
                        s.write(keys)
                        fired.add(pattern)
                if predicate(text):
                    return text
                if s.status != "active":
                    raise ApiError("PTY_CRASHED", "Process exited during wait", 409)
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise ApiError("AUTH_TIMEOUT", "Timed out waiting for CLI output", 408)
                try:
                    chunk = await asyncio.wait_for(q.get(), timeout=remaining)
                except asyncio.TimeoutError:
                    raise ApiError("AUTH_TIMEOUT", "Timed out waiting for CLI output", 408)
                if chunk is None and s.status != "active":
                    # EOF — evaluate one last time then fail
                    text = s.buffer.decode(errors="replace")
                    if predicate(text):
                        return text
                    raise ApiError("PTY_CRASHED", "Process exited during wait", 409)
        finally:
            s.unsubscribe(q)
