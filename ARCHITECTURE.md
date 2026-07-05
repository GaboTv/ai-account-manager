# AI Account Manager — Architecture

A Portainer-style control plane for managing isolated Claude Code, Codex CLI,
and AI Prime Tech accounts, each in its own Docker container with its own
persistent auth + workspace volumes.

## System overview

```
Browser (Next.js + xterm.js)
   │ REST + WebSocket
   ▼
FastAPI backend ── PostgreSQL (metadata, usage snapshots, audit; NO tokens)
   │ Docker API (socket lives ONLY here)
   ▼
Docker Engine
   ├── ai-<name>   (runner image, non-root, capped, no socket)
   │     ├── volume ai-<name>-home       → /home/agent   (auth state)
   │     └── volume ai-<name>-workspace  → /workspace
   └── … one container + volume pair per account
```

- **One image per provider**, one container + two volumes per account.
- Runner containers run `sleep infinity` under tini; all CLI work happens
  through `docker exec` — non-interactive for status/usage checks, TTY exec
  for login flows and interactive sessions.
- The PTY manager bridges docker-exec sockets to WebSockets (xterm.js), to the
  auth-flow parser, and to the headless usage-capture scraper.

## Component map

| Component | File |
|---|---|
| REST + WS routes, startup migrations, usage poller | `backend/app/main.py` |
| Docker orchestration (only Docker-touching code) | `backend/app/docker_service.py` |
| PTY / session manager, headless slash-capture | `backend/app/pty_manager.py` |
| Auth-flow service (login, callback forwarding) | `backend/app/auth_flow.py` |
| Provider adapters (all CLI-specific knowledge) | `backend/app/adapters.py` |
| Secret redaction | `backend/app/redact.py` |
| Structured errors | `backend/app/errors.py` |
| DB models + audit helper | `backend/app/db.py` |
| Schema | `db/001_init.sql` |
| Runner images | `docker/claude.Dockerfile`, `docker/codex.Dockerfile` |
| Create wizard | `frontend/app/create/page.tsx` |
| Accounts (cards, usage bars, auto-refresh) | `frontend/app/accounts/page.tsx` |
| Dashboard (per-day usage charts) | `frontend/app/page.tsx`, `components/DailyUsageChart.tsx` |
| Terminal / login modal | `frontend/app/terminal/…`, `components/Terminal.tsx`, `LoginModal.tsx` |

## Providers

| Provider | CLI | Image | Auth mechanism |
|---|---|---|---|
| `claude` | Claude Code | `ai-runner-claude` | claude.ai OAuth; paste-back code in terminal |
| `codex` | Codex CLI | `ai-runner-codex` | browser login; localhost:1455 callback forwarded into the container |
| `aiprimetech` | Claude Code (drop-in) | `ai-runner-claude` | API key + base URL as env vars in the home volume |

All provider-specific behavior is confined to `adapters.py`. `AiPrimeTechAdapter`
subclasses `ClaudeAdapter` because it uses the same CLI; it overrides only auth
(env-file based) and wraps every `claude` invocation in
`bash -c 'source ~/.aiprimetech.env; exec claude "$@"'` so the base URL/token
are real environment variables.

## Key design decisions

### 1. Direct Docker API vs Portainer API
- **Decision:** Docker SDK for Python against the local engine.
- **Reason:** No extra service, full exec-socket/TTY control.
- **Tradeoff:** Single-host for MVP.
- **Alternative:** Portainer/multi-host later, behind the `DockerService` seam.

### 2. One image per provider vs per account
- **Decision:** One image per provider; state in per-account volumes.
- **Reason:** Images are code, volumes are state. N accounts = 2 images.
- **Risk:** A CLI upgrade hits all accounts of a provider — pin image tags.

### 3. Named volumes vs bind mounts
- **Decision:** Named Docker volumes.
- **Reason:** No host permission issues, survive container recreation, easy
  labeled cleanup, not casually browsable.
- **Risk:** Not encrypted at rest unless the host disk is.

### 4. Device-code / paste vs localhost redirect
- **Decision:** Per provider, the safest containerized flow. Claude uses
  paste-back code; Codex uses browser login with the localhost callback
  **forwarded into the container** (validated host/port/path); AI Prime Tech
  needs no login at all (API key).
- **Reason:** Containers can't receive browser callbacks directly.
- **Risk:** CLI flag/wording changes — isolated in adapters.

### 5. PTY automation vs non-interactive exec
- **Decision:** Both. Non-interactive (`auth status`, `login status`) where
  supported; PTY for logins, interactive sessions, and slash commands (which
  exist only inside the TUI, e.g. `/usage`, `/status`).
- **Risk:** TUI redraws garble output — raw output is always kept.

### 6. Raw output vs structured parsing
- **Decision:** Show raw; parse opportunistically (login URLs, device codes,
  usage bars, session stats) with adapter-owned regexes.
- **Risk:** Parsers silently miss new formats → flow degrades to "read the
  terminal", which still works.

### 7. Token storage: provider volume vs database
- **Decision:** Auth lives only in the per-account home volume (CLI-written for
  OAuth; an env file for AI Prime Tech). The DB stores names, statuses,
  timestamps, and `{method, base_url}` — never a token.
- **Verified:** an inserted API key appears in zero DB rows, audit events, and
  command runs.

### 8. Single-host vs multi-host
- **Decision:** Single host for MVP; `DockerService` is the seam for later.

## Security model

- Runner containers: non-root `agent`, `no-new-privileges:true`,
  `cap_drop: ALL`, `pids_limit`, CPU/memory limits, bridge network with no
  published ports, no host mounts, **no docker.sock**.
- The Docker socket is mounted only into the backend (control plane); that
  container is root-equivalent on the host and must not be exposed.
- `redact.py` scrubs API keys, OAuth codes in URLs, Bearer tokens, and JWTs
  from everything persisted or logged — **not** from the live terminal stream
  (the owner needs to see login URLs/codes).
- Sensitive input (auth codes) uses a dedicated `/sessions/{id}/input` endpoint
  that writes to the PTY **without logging the value**.
- API keys are written to the volume via an env var passed to `docker exec`
  (not argv), single-quote-escaped, so they never appear in the process list.
- Audit events for every account/container/auth/session mutation.
- The app never scrapes cookies, never intercepts unrelated OAuth redirects,
  never extracts tokens outside the CLI's own flow.

### Credit safety
Nothing automated ever sends a billable prompt. The usage poller and the
"Refresh usage" button run only the free TUI slash commands: `/usage` (Claude,
AI Prime Tech) and `/status` (Codex). The message and `exec` paths (`claude -p`,
`codex exec`) consume credits, are manual only, and are visibly flagged
(amber button + confirm dialog).

### Security checklist
- [x] Non-root runner user; `no-new-privileges` + `cap_drop ALL`
- [x] CPU/memory/pids limits per container
- [x] No docker.sock or published ports in runners; named volumes only
- [x] Tokens only in provider volumes, never DB (verified)
- [x] Redaction on persisted/logged output; secret input never logged
- [x] Audit log on all mutations; account-name regex blocks name injection
- [x] Credit-consuming actions are manual and flagged
- [ ] App-level auth (MVP is localhost-only — bind 127.0.0.1)
- [ ] Volume encryption at rest (host-level: LUKS/BitLocker)
- [ ] TLS if ever exposed beyond localhost

## Data model (PostgreSQL)

`db/001_init.sql` + SQLModel models in `db.py`:

- **`ai_accounts`** — provider, name, container/volume names, limits, status,
  `auth_status`, `auth_info` (JSONB: method/base_url/email/plan — no tokens),
  `usage_info` (JSONB: parsed limits + session stats). `provider` CHECK allows
  `claude`/`codex`/`aiprimetech`.
- **`usage_snapshots`** — a point-in-time copy of parsed limits on every
  capture; feeds the per-day dashboard. FK cascades on account delete.
- **`ai_sessions`**, **`ai_command_runs`** (redacted), **`audit_events`**
  (redacted JSONB metadata).

Schema changes since v1 are applied by idempotent startup migrations in
`main.py` (`ADD COLUMN IF NOT EXISTS`, constraint swaps) — no Alembic yet.

## Login / setup flows

- **Wizard** (`/create`): create account → create+start container (progress
  bar) → provider-specific login step → verify → done.
- **Claude**: interactive `claude` launches onboarding; auto-responders answer
  the theme (dark) and account-type (subscription) prompts; the OAuth URL is
  parsed and shown; the user pastes the code into a field →
  `/sessions/{id}/input` (not logged).
- **Codex**: `codex login` (browser flow) serves a callback on `localhost:1455`
  inside the container; the user pastes the dead-end callback URL →
  `/accounts/{id}/setup/callback` → validated → `curl`'d to the in-container
  server. (Device-auth is available but gated by OpenAI, so browser is default.)
- **AI Prime Tech**: no terminal login — an API-key form → `/accounts/{id}/setkey`
  writes `~/.aiprimetech.env` (base URL, token, `CLAUDE_CODE_*` flags) into the
  home volume.

## Usage / status capture

- `pty_manager.run_slash_capture` boots the CLI TUI headlessly, auto-answers
  first-run prompts, types the slash command, waits for output to settle (with
  a `post_wait` for server-fetched panels), and returns the drawn text.
- Adapters parse limit gauges (`used_percent`, `resets`) and session stats
  (cost, input/output tokens). Codex reports "% left" (normalized to used);
  Claude reports "% used". Reset times render in `RUNNER_TZ`.
- **Two distinct refresh rates:**
  - *Data capture* — a background poller re-captures usage for running,
    logged-in accounts every `USAGE_POLL_MINUTES` (default **2 min**) and
    snapshots it. This is the only thing that produces new numbers; each
    capture boots the TUI (~30 s per account), so it can't run every few
    seconds. A manual **📊 Usage** click forces an immediate capture.
  - *Display refresh* — the accounts page re-fetches the account list and ticks
    the "updated Xs ago" label every **10 s**. This is a cheap DB read that
    only re-renders what's already stored; it never triggers a capture. The 10 s
    tick is why the UI looks live even though numbers change at most every
    2 minutes.
- **AI Prime Tech limitation:** `/usage` shows only per-session token counts
  (the proxy exposes no plan-limit bars and no usage API), so a fresh headless
  capture reads 0; real numbers appear in a live terminal session.

## Error handling

`ApiError(code, message, status, details)` → `{"error": {code, message,
details}}`. A catch-all handler wraps unexpected 500s **with CORS headers**
(Starlette runs the generic handler outside CORSMiddleware, which otherwise
produces an opaque "Failed to fetch"). Bad UUIDs return a clean 404, not a 500.
`get_session` uses `expire_on_commit=False` so a post-commit audit never blanks
a returned object.

Codes: `DOCKER_UNAVAILABLE, IMAGE_MISSING, CONTAINER_EXISTS,
CONTAINER_NOT_RUNNING, CONTAINER_NOT_FOUND, CLI_MISSING, LOGIN_FAILED,
AUTH_TIMEOUT, PTY_CRASHED, PARSE_FAILED, VOLUME_PERMISSION,
UNSUPPORTED_PROVIDER, ACCOUNT_NOT_FOUND, SESSION_NOT_FOUND, NAME_TAKEN,
INVALID_NAME, INTERNAL`.

## Testing

`backend/tests/`: adapter command generation and parsing (login URLs, device
codes, usage bars in both layouts, session stats, auth-status JSON), redaction,
callback-URL validation, PTY responder behavior, and account/volume naming.
Docker is mocked; live verification uses real containers.

## Deployment

- MVP: `docker compose up` on one host; all ports on 127.0.0.1.
- The backend needs the Docker socket — treat it as root-equivalent; never
  expose port 8000 beyond localhost without authentication.
- Hardening order before exposure: app auth (OIDC / reverse-proxy) → TLS →
  a Docker socket proxy limiting endpoints → Portainer/multi-host if needed.

## Known limitations & risks

1. **Terminal/usage parsing is brittle.** CLI updates break regexes; raw output
   is always shown and regexes are centralized in adapters. Pin CLI versions.
2. **PTY sessions are in-memory.** A backend restart orphans exec processes;
   audit rows survive. Orphaned CLI processes may accumulate in a container.
3. **No app-level auth.** Localhost binding is the only gate in the MVP.
4. **Volumes are unencrypted** unless the host disk is.
5. **Codex sandbox (bwrap)** can't create user namespaces on Docker Desktop's
   kernel; the runner container is the isolation boundary instead.
6. **AI Prime Tech usage** is per-session only via the CLI (no usage API).
7. **Terms of service.** Manage only accounts you own; do not use this to evade
   provider limits or automate abuse — all actions are audited.
