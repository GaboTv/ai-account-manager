"""FastAPI app: REST + WebSocket wiring. Business logic lives in services."""
from __future__ import annotations

import re
import uuid

from fastapi import Depends, FastAPI, Request, Response, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlmodel import Session, SQLModel, select

from . import appauth
from . import db as dbm
from .adapters import get_adapter
from .auth_flow import AuthFlowService
from .db import AIAccount, AICommandRun, AISession, audit, engine, get_session
from .docker_service import DockerService
from .errors import ApiError, api_error_handler
from .pty_manager import PtyManager
from .redact import redact

app = FastAPI(title="AI Account Manager")
app.add_exception_handler(ApiError, api_error_handler)


ALLOWED_ORIGIN = "http://localhost:3000"


@app.exception_handler(Exception)
async def unhandled_error_handler(request, exc: Exception):
    # Starlette handles the generic Exception in ServerErrorMiddleware, which
    # sits OUTSIDE CORSMiddleware — so we must add CORS headers ourselves or
    # the browser reports an opaque "Failed to fetch" instead of the error.
    import logging

    logging.getLogger("app").exception("unhandled error", exc_info=exc)
    from fastapi.responses import JSONResponse

    origin = request.headers.get("origin")
    headers = {"Access-Control-Allow-Origin": origin} if origin == ALLOWED_ORIGIN else {}
    return JSONResponse(
        status_code=500,
        content={"error": {"code": "INTERNAL", "message": str(exc), "details": {}}},
        headers=headers,
    )



app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- app-level auth ---------------------------------------------------
# Everything except these paths (and CORS preflight) requires a valid bearer
# token. WebSockets aren't HTTP, so they authenticate via a ?token= param in
# their own handlers.
PUBLIC_PATHS = {"/health", "/auth/login", "/auth/logout", "/openapi.json", "/docs", "/redoc"}


def _request_token(request) -> str | None:
    """Token from the httpOnly cookie (browser) or a Bearer header (scripts)."""
    cookie = request.cookies.get(appauth.COOKIE_NAME)
    if cookie:
        return cookie
    auth = request.headers.get("Authorization", "")
    return auth[7:] if auth.startswith("Bearer ") else None


@app.middleware("http")
async def require_auth_mw(request, call_next):
    from fastapi.responses import JSONResponse

    path = request.url.path
    if request.method == "OPTIONS" or path in PUBLIC_PATHS or path.startswith("/docs"):
        return await call_next(request)
    if not appauth.valid_token(_request_token(request)):
        origin = request.headers.get("origin")
        headers = {"Access-Control-Allow-Origin": origin,
                   "Access-Control-Allow-Credentials": "true"} if origin == ALLOWED_ORIGIN else {}
        return JSONResponse(
            status_code=401,
            content={"error": {"code": "UNAUTHORIZED", "message": "Login required", "details": {}}},
            headers=headers,
        )
    return await call_next(request)


class LoginBody(BaseModel):
    username: str
    password: str


class UserCreate(BaseModel):
    username: str
    password: str


def _set_auth_cookie(response, token: str):
    response.set_cookie(
        appauth.COOKIE_NAME, token, max_age=appauth.TOKEN_MAX_AGE,
        httponly=True, samesite="lax", secure=appauth.COOKIE_SECURE, path="/",
    )


@app.post("/auth/login")
def login(body: LoginBody, request: Request, response: Response,
          db: Session = Depends(get_session)):
    ip = (request.headers.get("x-forwarded-for", "").split(",")[0].strip()
          or (request.client.host if request.client else "unknown"))
    # Key by IP+username so brute-forcing one account can't lock out others.
    # (Docker NATs all host traffic to one gateway IP, so IP alone would be
    # effectively global.)
    key = f"{ip}|{body.username}"
    if appauth.is_locked(key):
        raise ApiError("RATE_LIMITED",
                       "Too many failed attempts. Try again later.", 429)
    user = db.exec(select(dbm.User).where(dbm.User.username == body.username)).first()
    if not user or not appauth.verify_password(body.password, user.password_hash):
        appauth.record_failure(key)
        raise ApiError("UNAUTHORIZED", "Invalid username or password", 401)
    appauth.clear_failures(key)
    token = appauth.issue_token(user.username)
    _set_auth_cookie(response, token)
    return {"token": token, "username": user.username}  # token also returned for API/curl clients


@app.post("/auth/logout")
def logout(response: Response):
    response.delete_cookie(appauth.COOKIE_NAME, path="/")
    return {"status": "logged_out"}


@app.get("/auth/me")
def auth_me(request: Request):
    return {"username": appauth.token_user(_request_token(request))}


# ---- user management -------------------------------------------------


@app.get("/users")
def list_users(db: Session = Depends(get_session)):
    return [{"id": str(u.id), "username": u.username, "created_at": u.created_at}
            for u in db.exec(select(dbm.User).order_by(dbm.User.created_at)).all()]


@app.post("/users", status_code=201)
def create_user(body: UserCreate, db: Session = Depends(get_session)):
    if not body.username.strip() or len(body.password) < 6:
        raise ApiError("INVALID_NAME", "Username required; password min 6 chars", 422)
    if db.exec(select(dbm.User).where(dbm.User.username == body.username)).first():
        raise ApiError("NAME_TAKEN", f"User {body.username} already exists", 409)
    user = dbm.User(username=body.username, password_hash=appauth.hash_password(body.password))
    db.add(user); db.commit(); db.refresh(user)
    return {"id": str(user.id), "username": user.username}


@app.delete("/users/{user_id}", status_code=204)
def delete_user(user_id: str, db: Session = Depends(get_session)):
    user = db.get(dbm.User, uuid.UUID(user_id))
    if not user:
        raise ApiError("ACCOUNT_NOT_FOUND", "No such user", 404)
    if len(db.exec(select(dbm.User)).all()) <= 1:
        raise ApiError("LAST_USER", "Cannot delete the only user", 409)
    db.delete(user); db.commit()


docker_svc: DockerService | None = None
pty_mgr: PtyManager | None = None
auth_svc: AuthFlowService | None = None


async def _usage_poller():
    """Auto-refresh usage for running, logged-in accounts every
    USAGE_POLL_MINUTES (0 disables). Sequential on purpose — one TUI boot at
    a time keeps container load negligible."""
    import asyncio
    import logging
    import os

    interval = float(os.environ.get("USAGE_POLL_MINUTES", "60"))
    if interval <= 0:
        return
    log = logging.getLogger("usage-poller")
    while True:
        await asyncio.sleep(interval * 60)
        with Session(engine) as db:
            ids = [a.id for a in db.exec(select(AIAccount)).all()]
        for acct_id in ids:
            try:
                with Session(engine) as db:
                    acct = db.get(AIAccount, acct_id)
                    if not acct or acct.auth_status != "logged_in":
                        continue
                    if docker_svc.status(acct.container_name)["status"] != "running":
                        continue
                    await _capture_usage(acct, db)
                    log.info("usage refreshed for %s", acct.name)
            except Exception:
                log.exception("usage poll failed for account %s", acct_id)


@app.on_event("startup")
def startup():
    global docker_svc, pty_mgr, auth_svc
    SQLModel.metadata.create_all(engine)
    from sqlalchemy import text

    with engine.begin() as conn:  # ponytail: inline migration; alembic when schema churn grows
        conn.execute(text(
            "ALTER TABLE ai_accounts ADD COLUMN IF NOT EXISTS "
            "auth_info JSONB NOT NULL DEFAULT '{}'"
        ))
        conn.execute(text(
            "ALTER TABLE ai_accounts ADD COLUMN IF NOT EXISTS "
            "usage_info JSONB NOT NULL DEFAULT '{}'"
        ))
        # Allow providers added after 001_init.sql (aiprimetech, grok).
        conn.execute(text(
            "ALTER TABLE ai_accounts DROP CONSTRAINT IF EXISTS ai_accounts_provider_check"
        ))
        conn.execute(text(
            "ALTER TABLE ai_accounts ADD CONSTRAINT ai_accounts_provider_check "
            "CHECK (provider IN ('claude','codex','aiprimetech','grok'))"
        ))
        # usage_snapshots is created by create_all without ON DELETE CASCADE,
        # so its rows block account deletion. Swap the FK for a cascading one.
        conn.execute(text(
            "ALTER TABLE usage_snapshots "
            "DROP CONSTRAINT IF EXISTS usage_snapshots_account_id_fkey"
        ))
        conn.execute(text(
            "ALTER TABLE usage_snapshots ADD CONSTRAINT usage_snapshots_account_id_fkey "
            "FOREIGN KEY (account_id) REFERENCES ai_accounts(id) ON DELETE CASCADE"
        ))
    # Bootstrap: seed the first user from env if the users table is empty.
    with Session(engine) as db:
        if not db.exec(select(dbm.User)).first():
            db.add(dbm.User(username=appauth.APP_USERNAME,
                            password_hash=appauth.hash_password(appauth.APP_PASSWORD)))
            db.commit()

    docker_svc = DockerService()
    pty_mgr = PtyManager(docker_svc)
    auth_svc = AuthFlowService(pty_mgr)
    import asyncio

    asyncio.get_running_loop().create_task(_usage_poller())


NAME_RE = re.compile(r"^[a-z0-9][a-z0-9-]{1,30}$")


class AccountCreate(BaseModel):
    provider: str
    name: str
    cpu_limit: float = 1
    memory_limit_mb: int = 1024


class MessageBody(BaseModel):
    message: str


class SlashBody(BaseModel):
    command: str


class AuthInputBody(BaseModel):
    value: str


class SetKeyBody(BaseModel):
    api_key: str
    base_url: str = "https://aiprimetech.io"


def _account(db: Session, account_id: str) -> AIAccount:
    try:
        key = uuid.UUID(account_id)
    except ValueError:
        raise ApiError("ACCOUNT_NOT_FOUND", f"Invalid account id: {account_id}", 404)
    acct = db.get(AIAccount, key)
    if not acct:
        raise ApiError("ACCOUNT_NOT_FOUND", f"No account {account_id}", 404)
    return acct


# ---- accounts ---------------------------------------------------------


@app.post("/accounts", status_code=201)
def create_account(body: AccountCreate, db: Session = Depends(get_session)):
    adapter = get_adapter(body.provider)  # raises UNSUPPORTED_PROVIDER
    if not NAME_RE.match(body.name):
        raise ApiError("INVALID_NAME", "Name must match ^[a-z0-9][a-z0-9-]{1,30}$", 422)
    if db.exec(select(AIAccount).where(AIAccount.name == body.name)).first():
        raise ApiError("NAME_TAKEN", f"Account {body.name} already exists", 409)
    acct = AIAccount(
        provider=body.provider,
        name=body.name,
        container_name=f"ai-{body.name}",
        image=adapter.image,
        auth_volume=f"ai-{body.name}-home",
        workspace_volume=f"ai-{body.name}-workspace",
        cpu_limit=body.cpu_limit,
        memory_limit_mb=body.memory_limit_mb,
    )
    db.add(acct)
    db.commit()
    db.refresh(acct)
    audit(db, "account.create", acct.id, {"name": acct.name, "provider": acct.provider})
    return acct


@app.get("/accounts")
def list_accounts(db: Session = Depends(get_session)):
    return db.exec(select(AIAccount)).all()


@app.get("/accounts/{account_id}")
def get_account(account_id: str, db: Session = Depends(get_session)):
    return _account(db, account_id)


@app.delete("/accounts/{account_id}", status_code=204)
def delete_account(account_id: str, db: Session = Depends(get_session)):
    acct = _account(db, account_id)
    docker_svc.remove(acct.container_name)
    docker_svc.remove_volumes(acct)  # destroys auth state — deliberate on delete
    audit(db, "account.delete", acct.id, {"name": acct.name})
    db.delete(acct)
    db.commit()


# ---- container lifecycle ----------------------------------------------


@app.post("/accounts/{account_id}/container/create")
def container_create(account_id: str, db: Session = Depends(get_session)):
    acct = _account(db, account_id)
    docker_svc.ensure_volumes(acct)
    docker_svc.create_container(acct)
    acct.status = "created"
    db.add(acct); db.commit()
    audit(db, "container.create", acct.id)
    return {"status": "created"}


def _lifecycle(action: str):
    def handler(account_id: str, db: Session = Depends(get_session)):
        acct = _account(db, account_id)
        getattr(docker_svc, action)(acct.container_name)
        acct.status = {"start": "running", "stop": "stopped", "restart": "running"}[action]
        db.add(acct); db.commit()
        audit(db, f"container.{action}", acct.id)
        return {"status": acct.status}
    return handler


app.post("/accounts/{account_id}/container/start")(_lifecycle("start"))
app.post("/accounts/{account_id}/container/stop")(_lifecycle("stop"))
app.post("/accounts/{account_id}/container/restart")(_lifecycle("restart"))


@app.delete("/accounts/{account_id}/container")
def container_delete(account_id: str, db: Session = Depends(get_session)):
    acct = _account(db, account_id)
    docker_svc.remove(acct.container_name)  # volumes survive; account keeps auth
    acct.status = "created"
    db.add(acct); db.commit()
    audit(db, "container.delete", acct.id)
    return {"status": "deleted"}


@app.get("/accounts/{account_id}/container/status")
def container_status(account_id: str, db: Session = Depends(get_session)):
    return docker_svc.status(_account(db, account_id).container_name)


@app.get("/accounts/{account_id}/container/logs")
def container_logs(account_id: str, tail: int = 200, db: Session = Depends(get_session)):
    acct = _account(db, account_id)
    return {"logs": redact(docker_svc.logs(acct.container_name, tail))}


# ---- auth ---------------------------------------------------------------


@app.post("/accounts/{account_id}/auth/start")
async def auth_start(account_id: str, method: str | None = None,
                     db: Session = Depends(get_session)):
    acct = _account(db, account_id)
    status = docker_svc.status(acct.container_name)
    if status["status"] != "running":
        docker_svc.start(acct.container_name)
    result = await auth_svc.start_login(acct, method)
    db.add(AISession(id=uuid.UUID(result["session_id"]), account_id=acct.id,
                     provider=acct.provider, mode="login",
                     pty_process_id=pty_mgr.get(result["session_id"]).exec_id))
    db.commit()
    audit(db, "auth.start", acct.id, {"method": result["method"]})
    return result


@app.post("/accounts/{account_id}/auth/input")
def auth_input(account_id: str, body: AuthInputBody, session_id: str,
               db: Session = Depends(get_session)):
    acct = _account(db, account_id)
    auth_svc.submit_input(session_id, body.value, account=acct)
    audit(db, "auth.input", acct.id)  # code/callback URL is never logged
    return {"status": "submitted"}


@app.get("/accounts/{account_id}/auth/status")
def auth_status(account_id: str, db: Session = Depends(get_session)):
    acct = _account(db, account_id)
    adapter = get_adapter(acct.provider)
    exit_code, output = docker_svc.exec_run(acct.container_name, adapter.auth_status_command())
    logged_in = adapter.is_logged_in(output, exit_code)
    acct.auth_status = "logged_in" if logged_in else "logged_out"
    acct.auth_info = adapter.parse_auth_status(output, exit_code) if logged_in else {}
    db.add(acct); db.commit()
    return {"logged_in": logged_in, "info": acct.auth_info, "raw": redact(output)}


@app.post("/accounts/{account_id}/auth/logout")
def auth_logout(account_id: str, db: Session = Depends(get_session)):
    acct = _account(db, account_id)
    adapter = get_adapter(acct.provider)
    exit_code, output = docker_svc.exec_run(acct.container_name, adapter.logout_command())
    acct.auth_status = "logged_out"
    db.add(acct); db.commit()
    audit(db, "auth.logout", acct.id)
    return {"exit_code": exit_code, "raw": redact(output)}


# ---- sessions ------------------------------------------------------------


@app.post("/accounts/{account_id}/setkey")
def set_key(account_id: str, body: SetKeyBody, db: Session = Depends(get_session)):
    """aiprimetech only: store the API key + base URL as ~/.claude/settings.json
    in the account's home volume. The token is written straight to the volume —
    never to the DB or audit log."""
    acct = _account(db, account_id)
    adapter = get_adapter(acct.provider)
    if not getattr(adapter, "uses_api_key", False):
        raise ApiError("UNSUPPORTED_PROVIDER", "setkey applies only to API-key providers", 400)
    if not body.api_key.strip():
        raise ApiError("INVALID_NAME", "API key is required", 422)
    if docker_svc.status(acct.container_name)["status"] != "running":
        docker_svc.start(acct.container_name)

    def shq(v: str) -> str:  # single-quote for safe sourcing (injection-proof)
        return "'" + v.replace("'", "'\\''") + "'"

    env_file = getattr(adapter, "env_file", ".aiprimetech.env")
    content = "\n".join([
        f"export ANTHROPIC_BASE_URL={shq(body.base_url)}",
        f"export ANTHROPIC_AUTH_TOKEN={shq(body.api_key)}",
        "export CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC=1",
        "export CLAUDE_CODE_ATTRIBUTION_HEADER=0",
    ]) + "\n"
    docker_svc.write_home_file(acct.container_name, env_file, content)
    acct.auth_status = "logged_in"
    acct.auth_info = {"method": "api-key", "base_url": body.base_url}  # NO token
    db.add(acct); db.commit()
    audit(db, "auth.success", acct.id, {"method": "api-key", "base_url": body.base_url})
    return {"status": "saved"}


@app.post("/accounts/{account_id}/setup/session", status_code=201)
async def setup_session(account_id: str, db: Session = Depends(get_session)):
    """Interactive session for the create wizard: launches the provider's
    setup command (Claude onboarding, or Codex browser login) so the user
    drives theme/account/login by hand in the terminal."""
    acct = _account(db, account_id)
    adapter = get_adapter(acct.provider)
    if docker_svc.status(acct.container_name)["status"] != "running":
        docker_svc.start(acct.container_name)
    session = pty_mgr.start(acct, adapter.setup_command(), mode="setup")
    db.add(AISession(id=uuid.UUID(session.id), account_id=acct.id,
                     provider=acct.provider, mode="setup",
                     pty_process_id=session.exec_id))
    db.commit()
    audit(db, "session.start", acct.id, {"mode": "setup"})
    return {"session_id": session.id, "needs_callback_field": adapter.needs_callback_field}


@app.post("/accounts/{account_id}/setup/callback")
def setup_callback(account_id: str, body: AuthInputBody, db: Session = Depends(get_session)):
    """Codex only: forward a pasted localhost callback URL to the CLI's
    callback server inside the container (validated host/port/path)."""
    acct = _account(db, account_id)
    auth_svc.forward_callback(acct, body.value.strip())
    audit(db, "auth.input", acct.id)  # URL (with code) is never logged
    return {"status": "forwarded"}


@app.post("/accounts/{account_id}/sessions", status_code=201)
async def create_session(account_id: str, db: Session = Depends(get_session)):
    # async: PtyManager.start needs the running event loop for output fan-out
    acct = _account(db, account_id)
    adapter = get_adapter(acct.provider)
    session = pty_mgr.start(acct, adapter.interactive_command(), mode="interactive")
    db.add(AISession(id=uuid.UUID(session.id), account_id=acct.id,
                     provider=acct.provider, mode="interactive",
                     pty_process_id=session.exec_id))
    db.commit()
    audit(db, "session.start", acct.id)
    return {"session_id": session.id}


@app.get("/sessions/{session_id}")
def get_session_info(session_id: str):
    s = pty_mgr.get(session_id)
    return {"session_id": s.id, "account_id": s.account_id, "mode": s.mode,
            "status": s.status}


@app.post("/sessions/{session_id}/send")
def session_send(session_id: str, body: MessageBody, db: Session = Depends(get_session)):
    s = pty_mgr.get(session_id)
    pty_mgr.send_line(session_id, body.message)
    audit(db, "session.message", uuid.UUID(s.account_id),
          {"message": body.message[:200]})
    return {"status": "sent"}


@app.post("/sessions/{session_id}/input")
def session_input(session_id: str, body: AuthInputBody, db: Session = Depends(get_session)):
    """Write raw text + Enter (CR) to the session's PTY. For login codes and
    similar sensitive input — the value is never logged (it may be a secret)."""
    s = pty_mgr.get(session_id)
    pty_mgr.send_line(session_id, body.value)  # send_line appends CR
    audit(db, "auth.input", uuid.UUID(s.account_id))  # value intentionally omitted
    return {"status": "sent"}


@app.post("/sessions/{session_id}/slash")
def session_slash(session_id: str, body: SlashBody, db: Session = Depends(get_session)):
    if not body.command.startswith("/"):
        raise ApiError("PARSE_FAILED", "Slash commands must start with /", 422)
    s = pty_mgr.get(session_id)
    pty_mgr.send_line(session_id, body.command)
    audit(db, "session.slash", uuid.UUID(s.account_id), {"command": body.command})
    return {"status": "sent"}


@app.delete("/sessions/{session_id}", status_code=204)
def close_session(session_id: str, db: Session = Depends(get_session)):
    s = pty_mgr.get(session_id)
    account_id = s.account_id
    pty_mgr.close(session_id)
    # Reap the session's CLI process (closing the socket doesn't kill it),
    # unless another session for this account is still active.
    acct = db.get(AIAccount, uuid.UUID(account_id))
    if acct:
        pty_mgr.reap_orphans(account_id, acct.container_name, exclude_session_id=session_id)
    row = db.get(AISession, uuid.UUID(session_id))
    if row:
        row.status = "closed"
        row.ended_at = dbm.utcnow()
        db.add(row); db.commit()
    audit(db, "session.close", uuid.UUID(account_id))


async def _capture_usage(acct: AIAccount, db: Session) -> tuple[dict, str]:
    """Scrape /usage (claude) or /status (codex) from a headless TUI session,
    cache parsed limits on the account, and record a history snapshot.
    Slow (~15-45s): boots the full TUI inside the container."""
    adapter = get_adapter(acct.provider)
    raw = await pty_mgr.run_slash_capture(
        acct,
        adapter.interactive_command(),
        adapter.usage_capture_command(),
        responders=adapter.capture_responders,
        quiet=4,
        post_wait=5,  # let server-fetched usage panels (e.g. aiprimetech) load
    )
    parsed = adapter.parse_usage(raw)
    parsed["checked_at"] = dbm.utcnow().isoformat()
    acct.usage_info = parsed
    # /status is the only place codex exposes plan/email — enrich the card
    extra = parsed.get("account", {})
    if extra:
        acct.auth_info = {**acct.auth_info, **{k: v for k, v in extra.items() if k != "model"}}
    if parsed.get("limits"):
        db.add(dbm.UsageSnapshot(account_id=acct.id, limits=parsed["limits"]))
    db.add(acct); db.commit()
    audit(db, "session.slash", acct.id, {"command": adapter.usage_capture_command()})
    return parsed, raw


@app.post("/accounts/{account_id}/usage/refresh")
async def usage_refresh(account_id: str, db: Session = Depends(get_session)):
    acct = _account(db, account_id)
    parsed, raw = await _capture_usage(acct, db)
    from .adapters import strip_ansi
    return {"usage": parsed, "raw": redact(strip_ansi(raw))[-4000:]}


@app.get("/usage/history")
def usage_history(days: int = 31, db: Session = Depends(get_session)):
    """Flat list of (account, taken_at, label, used_percent) points for the
    last N days — the dashboard aggregates per day client-side."""
    from datetime import timedelta

    since = dbm.utcnow() - timedelta(days=days)
    rows = db.exec(
        select(dbm.UsageSnapshot, AIAccount)
        .join(AIAccount, AIAccount.id == dbm.UsageSnapshot.account_id)
        .where(dbm.UsageSnapshot.taken_at >= since)
        .order_by(dbm.UsageSnapshot.taken_at)
    ).all()
    return [
        {
            "account_id": str(acct.id),
            "name": acct.name,
            "provider": acct.provider,
            "taken_at": snap.taken_at.isoformat(),
            "label": lim.get("label"),
            "used_percent": lim.get("used_percent"),
        }
        for snap, acct in rows
        for lim in snap.limits
        if lim.get("used_percent") is not None
    ]


# ---- non-interactive usage/status ------------------------------------


@app.post("/accounts/{account_id}/exec")
def account_exec(account_id: str, body: MessageBody, db: Session = Depends(get_session)):
    """One-shot `claude -p` / `codex exec` — no PTY needed."""
    acct = _account(db, account_id)
    adapter = get_adapter(acct.provider)
    run = AICommandRun(account_id=acct.id, command=redact(f"exec: {body.message[:200]}"))
    exit_code, output = docker_svc.exec_run(
        acct.container_name, adapter.exec_command(body.message), timeout=300
    )
    run.stdout = redact(output)
    run.exit_code = exit_code
    run.ended_at = dbm.utcnow()
    db.add(run); db.commit()
    return {"exit_code": exit_code, "output": output}


# ---- websockets -------------------------------------------------------


async def _bridge_ws(ws: WebSocket, session_id: str):
    """Shared xterm.js <-> PTY bridge for terminal and auth sockets."""
    # The browser sends the httpOnly cookie on the WS handshake; a ?token=
    # query param is accepted as a fallback (e.g. non-browser clients).
    token = ws.cookies.get(appauth.COOKIE_NAME) or ws.query_params.get("token")
    if not appauth.valid_token(token):
        await ws.close(code=4401)
        return
    await ws.accept()
    try:
        session = pty_mgr.get(session_id)
    except ApiError:
        await ws.close(code=4004)
        return
    q = session.subscribe()

    import asyncio, json

    async def pump_out():
        while True:
            chunk = await q.get()
            if chunk is None:
                await ws.send_json({"type": "closed", "status": session.status})
                break
            await ws.send_bytes(chunk)

    out_task = asyncio.create_task(pump_out())
    try:
        while True:
            msg = await ws.receive()
            if msg.get("type") == "websocket.disconnect":
                break
            if "bytes" in msg and msg["bytes"]:
                session.write(msg["bytes"])
            elif "text" in msg and msg["text"]:
                data = json.loads(msg["text"])
                if data.get("type") == "input":
                    session.write(data["data"].encode())
                elif data.get("type") == "resize":
                    pty_mgr.resize(session_id, data["rows"], data["cols"])
    except (WebSocketDisconnect, ApiError):
        pass
    finally:
        out_task.cancel()
        session.unsubscribe(q)


@app.websocket("/ws/sessions/{session_id}/terminal")
async def ws_terminal(ws: WebSocket, session_id: str):
    await _bridge_ws(ws, session_id)


@app.websocket("/ws/auth/{auth_session_id}")
async def ws_auth(ws: WebSocket, auth_session_id: str):
    await _bridge_ws(ws, auth_session_id)


@app.get("/health")
def health():
    return {"ok": True}
