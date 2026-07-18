FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    curl \
    bash \
    procps \
    tini \
    && rm -rf /var/lib/apt/lists/*

# Grok Build (xAI). The npm shim resolves the per-platform binary from the
# global node_modules, so it works for any user; per-user state (credentials,
# sessions) lands in $HOME/.grok — the account's auth volume.
RUN npm install -g @xai-official/grok

RUN useradd -m -s /bin/bash agent
USER agent

WORKDIR /workspace

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sleep", "infinity"]
