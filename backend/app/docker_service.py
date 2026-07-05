"""Docker orchestration: containers + volumes for AI accounts.

The only component allowed to touch the Docker API. Runner containers never
see the socket. Swap `DockerService` for a Portainer-backed implementation
later if multi-host is needed — the rest of the app only calls these methods.
"""
from __future__ import annotations

import os

import docker
import docker.errors

from .errors import ApiError

LABEL = "ai-account-manager"
# Timezone the CLIs render times in (usage resets etc.). tzdata ships in the
# runner images; applied per-exec so existing containers pick it up too.
RUNNER_TZ = os.environ.get("RUNNER_TZ", "UTC")
_EXEC_ENV = {"HOME": "/home/agent", "TZ": RUNNER_TZ}


class DockerService:
    def __init__(self, base_url: str | None = None):
        try:
            self.client = (
                docker.DockerClient(base_url=base_url) if base_url else docker.from_env()
            )
            self.client.ping()
        except docker.errors.DockerException as e:
            raise ApiError("DOCKER_UNAVAILABLE", f"Cannot reach Docker daemon: {e}", 503)
        self.api = self.client.api  # low-level client, needed for exec sockets

    # ---- volumes -----------------------------------------------------

    def ensure_volumes(self, account) -> None:
        for vol in (account.auth_volume, account.workspace_volume):
            try:
                self.client.volumes.get(vol)
            except docker.errors.NotFound:
                self.client.volumes.create(
                    vol, labels={LABEL: "true", "account": str(account.id)}
                )

    def remove_volumes(self, account) -> None:
        for vol in (account.auth_volume, account.workspace_volume):
            try:
                self.client.volumes.get(vol).remove(force=True)
            except docker.errors.NotFound:
                pass

    # ---- container lifecycle -----------------------------------------

    def create_container(self, account) -> str:
        try:
            self.client.images.get(account.image)
        except docker.errors.ImageNotFound:
            raise ApiError(
                "IMAGE_MISSING",
                f"Runner image {account.image} not built. Run: "
                f"docker build -f docker/{account.provider}.Dockerfile "
                f"-t {account.image} docker/",
                409,
            )
        try:
            container = self.client.containers.create(
                account.image,
                name=account.container_name,
                command=["sleep", "infinity"],  # kept alive; work happens via exec
                user="agent",
                volumes={
                    account.auth_volume: {"bind": "/home/agent", "mode": "rw"},
                    account.workspace_volume: {"bind": "/workspace", "mode": "rw"},
                },
                working_dir="/workspace",
                environment={"HOME": "/home/agent", "TZ": RUNNER_TZ},
                mem_limit=f"{account.memory_limit_mb}m",
                nano_cpus=int(account.cpu_limit * 1_000_000_000),
                pids_limit=256,
                security_opt=["no-new-privileges:true"],
                cap_drop=["ALL"],
                network_mode="bridge",  # outbound only; no ports published
                labels={
                    LABEL: "true",
                    "provider": account.provider,
                    "account": str(account.id),
                },
                detach=True,
            )
            return container.id
        except docker.errors.APIError as e:
            if e.status_code == 409:
                raise ApiError(
                    "CONTAINER_EXISTS", f"Container {account.container_name} already exists", 409
                )
            raise ApiError("DOCKER_UNAVAILABLE", str(e), 502)

    def _get(self, container_name: str):
        try:
            return self.client.containers.get(container_name)
        except docker.errors.NotFound:
            raise ApiError("CONTAINER_NOT_FOUND", f"No container {container_name}", 404)

    def start(self, container_name: str):
        self._get(container_name).start()

    def stop(self, container_name: str):
        self._get(container_name).stop(timeout=10)

    def restart(self, container_name: str):
        self._get(container_name).restart(timeout=10)

    def remove(self, container_name: str):
        try:
            self.client.containers.get(container_name).remove(force=True)
        except docker.errors.NotFound:
            pass

    def status(self, container_name: str) -> dict:
        c = self._get(container_name)
        return {
            "status": c.status,
            "id": c.short_id,
            "image": c.image.tags[0] if c.image.tags else c.image.short_id,
            "started_at": c.attrs["State"].get("StartedAt"),
        }

    def logs(self, container_name: str, tail: int = 200) -> str:
        return self._get(container_name).logs(tail=tail).decode(errors="replace")

    # ---- exec --------------------------------------------------------

    def exec_run(self, container_name: str, cmd: list[str], timeout: int = 60) -> tuple[int, str]:
        """Non-interactive exec for status checks / `claude -p` / `codex exec`."""
        c = self._get(container_name)
        if c.status != "running":
            raise ApiError("CONTAINER_NOT_RUNNING", f"{container_name} is not running", 409)
        try:
            result = c.exec_run(cmd, user="agent", demux=False, tty=False,
                                environment=_EXEC_ENV)
        except docker.errors.APIError as e:
            if "executable file not found" in str(e).lower():
                raise ApiError("CLI_MISSING", f"CLI binary not found: {cmd[0]}", 500)
            raise
        return result.exit_code, result.output.decode(errors="replace")

    def write_home_file(self, container_name: str, relpath: str, content: str) -> None:
        """Write a file under the agent's home (the auth volume). Content is
        passed via env, not argv, so a secret won't show in the process list.
        (Docker-daemon access can still read the volume — that's root-level
        access by design.)"""
        c = self._get(container_name)
        if c.status != "running":
            raise ApiError("CONTAINER_NOT_RUNNING", f"{container_name} is not running", 409)
        script = 'mkdir -p "$HOME/$(dirname "$REL")" && printf "%s" "$CONTENT" > "$HOME/$REL"'
        res = c.exec_run(
            ["sh", "-c", script], user="agent",
            environment={"HOME": "/home/agent", "REL": relpath, "CONTENT": content},
        )
        if res.exit_code != 0:
            raise ApiError("VOLUME_PERMISSION", res.output.decode(errors="replace"), 500)

    def exec_pty_create(self, container_name: str, cmd: list[str]) -> tuple[str, object]:
        """Create an interactive exec with TTY; returns (exec_id, raw socket)."""
        c = self._get(container_name)
        if c.status != "running":
            raise ApiError("CONTAINER_NOT_RUNNING", f"{container_name} is not running", 409)
        exec_id = self.api.exec_create(
            c.id, cmd, tty=True, stdin=True, user="agent",
            environment={**_EXEC_ENV, "TERM": "xterm-256color"},
        )["Id"]
        sock = self.api.exec_start(exec_id, tty=True, socket=True)
        return exec_id, sock

    def exec_resize(self, exec_id: str, rows: int, cols: int):
        self.api.exec_resize(exec_id, height=rows, width=cols)

    def exec_inspect(self, exec_id: str) -> dict:
        return self.api.exec_inspect(exec_id)
