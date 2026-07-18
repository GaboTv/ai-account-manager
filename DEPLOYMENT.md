# Dokploy deployment plan

Target: `https://accounts.terceros.ch` on the terceros VPS (Dokploy v0.29.12,
single-node Swarm, Traefik on loopback behind the Cloudflare Tunnel). The
wildcard tunnel + DNS already cover any `*.terceros.ch` subdomain, so no
Cloudflare changes are needed. Read `/home/claude/SERVER.md` and
`/home/claude/lessons_learned.md` before executing.

## Shape

Single-origin, same as the repo's TLS overlay, but Caddy listens on plain
HTTP and Dokploy Traefik + the tunnel provide TLS:

```
Cloudflare edge (TLS) -> tunnel -> Traefik (Host: accounts.terceros.ch)
  -> caddy:80  -> /api/* stripped -> backend:8000 (REST + WS)
              -> everything else  -> frontend:3000
```

Same origin means the existing CORS config and the Secure httpOnly cookie
work untouched. `NEXT_PUBLIC_API_URL=https://accounts.terceros.ch/api` must
be absolute (the WS URL is derived from it by `http`->`ws` replace in
`frontend/lib/api.ts`).

## 1. One-time host prep (SSH, as `claude`)

Build the runner images. Dokploy will not build these - they are not compose
services, the backend spawns them via the Docker socket.

```bash
cd /home/claude/projects/ai-account-manager
docker build -f docker/claude.Dockerfile -t ai-runner-claude:latest docker/
docker build -f docker/codex.Dockerfile  -t ai-runner-codex:latest  docker/
docker build -f docker/grok.Dockerfile   -t ai-runner-grok:latest   docker/
```

CLI updates are automatic after that: a host cron entry (user `claude`,
daily 04:45) runs `scripts/update-runners.sh`, which rebuilds both images
with `--no-cache` and, only when a CLI version actually changed, recreates
the affected account containers through the app's API (auth/workspace
volumes survive, so logins persist; any open terminal session on an updated
account is dropped). Log: `/home/claude/aimgr-update-runners.log`.

## 2. Repo changes (commit before deploying)

Three small files:

1. **`frontend/Dockerfile`** - production build. Replace `CMD npm run dev`
   with `RUN npm run build` + `CMD ["npm", "start"]`; local dev keeps hot
   reload by adding `command: npm run dev` to the frontend service in the
   existing `docker-compose.yml`.
2. **`Caddyfile.dokploy`** - copy of `Caddyfile` with the site address
   `:80` and no `tls internal`; routing blocks unchanged.
3. **`docker-compose.dokploy.yml`** - standalone compose (not an overlay):
   - `db`: as in `docker-compose.yml` but **no `ports:`**, password from
     `${POSTGRES_PASSWORD}`; keep the `./db/001_init.sql` mount (Dokploy
     clones the repo, relative paths work).
   - `backend`: no `ports:`; keep the Docker socket mount; env
     `APP_COOKIE_SECURE=1`, `APP_USERNAME`/`APP_PASSWORD`/`APP_SECRET` from
     Dokploy env vars, `DATABASE_URL` using `${POSTGRES_PASSWORD}`.
   - `frontend`: no `ports:`; build arg
     `NEXT_PUBLIC_API_URL=https://accounts.terceros.ch/api`.
   - `proxy` (caddy:2): mounts `Caddyfile.dokploy`, joins the external
     `dokploy-network` in addition to the default project network; no
     `ports:`, no `profiles:`.
   - Do NOT define custom subnets (172.20.0.0/16 is taken on this host) and
     do NOT publish any host ports - every service is reachable only via
     Traefik.

## 3. Dokploy setup (panel or API)

1. Project `ai-account-manager` -> **Compose** service.
   Provider: Git, `https://github.com/GaboTv/ai-account-manager.git`,
   branch `main` (repo is public - no deploy key needed), compose path
   `docker-compose.dokploy.yml`.
2. Environment tab: `POSTGRES_PASSWORD`, `APP_USERNAME`, `APP_PASSWORD`,
   `APP_SECRET`. The generated values live in `/home/claude/projects/.env`
   on the server as `AIMGR_APP_USERNAME`, `AIMGR_APP_PASSWORD`,
   `AIMGR_APP_SECRET`, `AIMGR_POSTGRES_PASSWORD` - never in this repo.
   The app login gates a Docker-socket-holding backend; treat the password
   accordingly.
3. Domain: `accounts.terceros.ch` -> service `proxy`, container port `80`,
   HTTPS enabled, certificate **none** (port 80 is closed publicly, so
   Let's Encrypt cannot issue; the tunnel connects with No TLS Verify and
   ignores Traefik's cert - same as every other domain on this host).
4. Deploy. First build takes a few minutes (Next.js build).

## 4. Verify (from the server + externally)

```bash
curl -I https://accounts.terceros.ch                  # 200, login page
curl -sI https://accounts.terceros.ch/api/docs        # backend reachable via /api
ss -lntup                                             # no new host ports
curl -s http://127.0.0.1:20241/ready                  # tunnel still ready
```

Then in a browser: log in, create a Claude account end-to-end (wizard ->
login -> terminal), confirm the xterm WebSocket connects (wss:// through
tunnel + Traefik + Caddy) and usage snapshots appear on the dashboard.
Re-verify the other production domains afterwards (lesson 35).

## Security notes

- The backend holds `/var/run/docker.sock` = root-equivalent on the host,
  now behind an internet-reachable login. The app has bcrypt users, lockout,
  and httpOnly cookies, but treat `APP_PASSWORD` like a root password.
  Optional hardening: put Cloudflare Access in front of the hostname.
- Runner containers are created by the backend on the default bridge with
  no published ports, cap_drop ALL, no socket - no Traefik/Dokploy exposure.

## Persistence and backups

| Data | Where | Covered today? |
|---|---|---|
| Users, accounts metadata, usage snapshots | compose volume `pgdata` | No - named volumes are not in the Dokploy web backup |
| Per-account provider tokens | `ai-auth-<account>` volumes (created at runtime) | No |
| Per-account workspaces | `ai-ws-<account>` volumes | No |

If losing provider logins matters, add these volumes to the host rclone
backup script (`/home/claude/bin/r2-host-backup.sh`); otherwise accept
re-login after a loss. `pgdata` is small - back it up.
