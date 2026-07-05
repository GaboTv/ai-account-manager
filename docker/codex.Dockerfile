FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    curl \
    bash \
    procps \
    tini \
    bubblewrap \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @openai/codex

RUN useradd -m -s /bin/bash agent
USER agent

WORKDIR /workspace

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["sleep", "infinity"]
