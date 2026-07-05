import asyncio

from app.pty_manager import PtyManager, PtySession


class FakeRawSock:
    def __init__(self):
        self.sent = b""

    def sendall(self, data):
        self.sent += data


class FakeSock:
    def __init__(self):
        self._sock = FakeRawSock()

    def close(self):
        pass


def test_wait_for_answers_onboarding_prompt():
    async def run():
        mgr = PtyManager(docker_service=None)
        session = PtySession(
            id="s1", account_id="a1", mode="login", exec_id="e1",
            sock=FakeSock(), loop=asyncio.get_running_loop(),
        )
        session.buffer = b"Choose the text style that looks best with your terminal"
        mgr.sessions["s1"] = session

        responders = [(r"text style that looks best", b"2\r")]
        # predicate passes once the responder has fired
        text = await mgr.wait_for(
            "s1", lambda t: session.sock._sock.sent == b"2\r",
            timeout=5, responders=responders,
        )
        assert "text style" in text
        assert session.sock._sock.sent == b"2\r"

    asyncio.run(run())
