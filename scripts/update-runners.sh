#!/usr/bin/env bash
# Keep the runner CLIs up to date. Rebuilds each runner image with --no-cache
# (npm install pulls the latest CLI); if the CLI version changed, recreates
# every account container using that image via the app's own API. Auth and
# workspace volumes survive recreation, so logins persist. Active terminal
# sessions on updated accounts are dropped - schedule this at a quiet hour.
#
# Requires: docker, curl, jq. Env: API_URL, APP_USERNAME, APP_PASSWORD.
#   API_URL=https://accounts.example.com/api APP_USERNAME=... APP_PASSWORD=... \
#     ./scripts/update-runners.sh
set -euo pipefail

REPO_DIR=$(cd "$(dirname "$0")/.." && pwd)
: "${API_URL:?}" "${APP_USERNAME:?}" "${APP_PASSWORD:?}"

cli_version() { # image cli
  docker run --rm "$1" "$2" --version 2>/dev/null | tail -1
}

changed_images=()
for spec in "ai-runner-claude:latest claude claude.Dockerfile" \
            "ai-runner-codex:latest codex codex.Dockerfile" \
            "ai-runner-grok:latest grok grok.Dockerfile"; do
  read -r image cli dockerfile <<<"$spec"
  old=$(cli_version "$image" "$cli" || echo "none")
  docker build --pull --no-cache -q -f "$REPO_DIR/docker/$dockerfile" -t "$image" "$REPO_DIR/docker/" >/dev/null
  new=$(cli_version "$image" "$cli")
  if [ "$old" != "$new" ]; then
    echo "$image: $old -> $new"
    changed_images+=("$image")
  else
    echo "$image: $new (unchanged)"
  fi
done

# Prune only after recreation below moves containers off the old images:
# pruning first strands running containers' image refs (containerd snapshotter).
finish() { docker image prune -f >/dev/null; }

[ ${#changed_images[@]} -eq 0 ] && { echo "nothing to recreate"; finish; exit 0; }

JAR=$(mktemp)
trap 'rm -f "$JAR"' EXIT
curl -sf -c "$JAR" -H 'Content-Type: application/json' \
  -d "{\"username\":\"$APP_USERNAME\",\"password\":\"$APP_PASSWORD\"}" \
  "$API_URL/auth/login" >/dev/null

api() { curl -sf -b "$JAR" -X "$1" "$API_URL$2"; }

api GET /accounts | jq -c '.[]' | while read -r acct; do
  id=$(jq -r .id <<<"$acct"); image=$(jq -r .image <<<"$acct")
  name=$(jq -r .name <<<"$acct")
  printf '%s\n' "${changed_images[@]}" | grep -qx "$image" || continue
  state=$(api GET "/accounts/$id/container/status" 2>/dev/null | jq -r '.status // empty' || true)
  [ -z "$state" ] && { echo "$name: no container, skipped"; continue; }
  api DELETE "/accounts/$id/container" >/dev/null
  api POST "/accounts/$id/container/create" >/dev/null
  [ "$state" = "running" ] && api POST "/accounts/$id/container/start" >/dev/null
  echo "$name: recreated on new $image (was $state)"
done
finish
