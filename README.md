# AI Account Manager

A Portainer-style web app for managing **isolated AI CLI accounts inside Docker
containers**. Each account runs in its own hardened container with its own
persistent auth and workspace volumes. Create accounts, run guided logins,
open interactive terminals, and track per-day usage — all from one UI.

Supports three providers:

| Provider | CLI | Auth | Runner image |
|---|---|---|---|
| **Claude Code** | `@anthropic-ai/claude-code` | claude.ai OAuth (paste-back code) | `ai-runner-claude` |
| **Codex CLI** | `@openai/codex` | browser login + localhost callback | `ai-runner-codex` |
| **AI Prime Tech** | Claude Code (drop-in) | API key (env vars) | `ai-runner-claude` |

> One reusable runner image **per provider**; one container + two volumes
> **per account**. Never one image per account.

See [`ARCHITECTURE.md`](./ARCHITECTURE.md) for the full design, security model,
and the rationale behind every major decision.

## Features

- **Guided create wizard** (`/create`): pick a provider, name it, watch a live
  progress bar build the container, then complete login in an embedded terminal.
- **Container lifecycle**: create / start / stop / restart / delete, status, logs.
- **Login flows** per provider: Claude paste-back code, Codex localhost-callback
  forwarding, AI Prime Tech API-key entry. Onboarding prompts (theme, account
  type) are auto-answered where the flow is automated.
- **Interactive terminals** over WebSocket (xterm.js) with a real PTY.
- **Per-day usage dashboard**: usage is captured via the free `/usage` (Claude)
  and `/status` (Codex) slash commands, snapshotted into Postgres, and charted
  by day of the month. The accounts list auto-refreshes every 10 s with a live
  "updated Xs ago" label.
- **Credit-safe by design**: nothing automated ever sends a billable prompt.
  Only the free slash commands run on a schedule; message/exec paths are manual
  and clearly marked.
- **Security-first runners**: non-root, `cap_drop: ALL`, `no-new-privileges`,
  CPU/memory/pid limits, no published ports, no Docker socket, named volumes.
- **No tokens in the database**: provider auth lives only in the per-account
  home volume. The DB stores metadata and redacted audit events.

## Screenshots

### Create wizard

Pick a provider, name the account, and the wizard builds the container and walks
you through login (`Name › Create › Login › Done`).

![Create wizard](docs/screenshots/create-wizard.png)

Other views (not shown here because they display live account data — add your own
scrubbed captures to `docs/screenshots/`):

- **Dashboard** — total/running/authenticated counts and per-day usage charts
  for the current month.
- **Accounts** — cards with provider badge, running/auth chips, live usage bars,
  a "updated Xs ago" label, and lifecycle actions. Auto-refreshes every 10 s.
- **Terminal** — interactive xterm.js session with free `/usage` and `/status`
  buttons and a (credit-flagged) message box.
- **Login modal** — login URL, device/paste-back code, live terminal, and the
  code / localhost-callback input.

## Stack

- **Frontend**: Next.js (App Router) · React · TypeScript · Tailwind CSS · xterm.js
- **Backend**: FastAPI · Docker SDK for Python · SQLModel · WebSockets
- **Database**: PostgreSQL
- **Runtime**: Docker Engine (single host); the `DockerService` seam allows a
  Portainer/multi-host backend later.

## Quick start

Prereqs: Docker Engine (Docker Desktop / WSL2 on Windows), and the runner
images built once.

```bash
# 1. Build the two runner images (rebuild after CLI upgrades)
docker build -f docker/claude.Dockerfile -t ai-runner-claude:latest docker/
docker build -f docker/codex.Dockerfile  -t ai-runner-codex:latest  docker/

# 2. Bring up db + backend + frontend
docker compose up --build
#   UI:  http://localhost:3000
#   API: http://localhost:8000/docs
```

Everything binds to `127.0.0.1`. There is **no app-level authentication** in the
MVP — do not expose it beyond localhost without adding auth + TLS (see
ARCHITECTURE.md § Deployment).

### Configuration

Set in `docker-compose.yml` (backend service):

| Env var | Default | Purpose |
|---|---|---|
| `RUNNER_TZ` | `Europe/Madrid` | Timezone the CLIs render usage/reset times in |
| `USAGE_POLL_MINUTES` | `15` | Auto usage-capture interval (`0` disables) |
| `DATABASE_URL` | compose-provided | Postgres connection |

## Using it

1. **Create** — go to `/create`, choose a provider, name the account. The wizard
   creates the container and volumes with a progress bar.
2. **Log in**:
   - **Claude**: pick a theme and the subscription account in the terminal, open
     the printed URL, then paste the code back in the field (or the terminal).
   - **Codex**: open the URL, sign in; your browser dead-ends on a `localhost`
     page — paste that full URL into the field to forward it to the CLI.
   - **AI Prime Tech**: paste your `sk-` API key; it's written only to the
     account's home volume (`~/.aiprimetech.env`), never the database.
3. **Verify** — the wizard checks auth via each provider's status command.
4. **Use** — open a terminal (⌨), or watch usage on the dashboard. The **/usage**
   and **/status** buttons are free; sending a message consumes credits and is
   clearly flagged.

## Tests

```bash
cd backend
pip install -r requirements.txt pytest
pytest tests/          # adapters, redaction, callback validation, PTY responders
```

Unit tests mock Docker and need no daemon. Live verification uses the real
containers once the runner images are built.

## Repository layout

```
backend/      FastAPI app (adapters, docker_service, pty_manager, auth_flow, …)
frontend/     Next.js app (create wizard, accounts, terminal, dashboard)
docker/       claude.Dockerfile, codex.Dockerfile (runner images)
db/           001_init.sql (Postgres schema)
docker-compose.yml
ARCHITECTURE.md
```

## Security & limitations (read before deploying)

- Localhost-only, no app auth, in the MVP. Add auth + TLS before any exposure.
- Docker-daemon access is root-equivalent; the backend container holds the
  socket and must be treated accordingly.
- Terminal/usage parsing is intentionally best-effort — CLI updates can change
  output; raw output is always preserved.
- This tool manages accounts a user legitimately owns. It must not be used to
  bypass provider limits, rotate accounts, or automate abuse. Nothing in the
  design facilitates that, and all account actions are audited.

Full risk list and mitigations are in `ARCHITECTURE.md`.

## License

MIT — see [`LICENSE`](./LICENSE).
