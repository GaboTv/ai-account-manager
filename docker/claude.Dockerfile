FROM node:22-bookworm-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    ca-certificates \
    git \
    curl \
    bash \
    procps \
    tini \
    && rm -rf /var/lib/apt/lists/*

RUN npm install -g @anthropic-ai/claude-code

RUN useradd -m -s /bin/bash agent
USER agent

WORKDIR /workspace

ENTRYPOINT ["/usr/bin/tini", "--"]
# Container is kept alive; all CLI work happens via docker exec PTYs.
CMD ["sleep", "infinity"]
