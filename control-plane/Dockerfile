# koyracloud control plane — single container serving API + built React SPA.
# Build from the REPO ROOT:  docker build -f control-plane/Dockerfile -t koyracloud .
FROM node:22-slim AS web
WORKDIR /web
COPY web/package.json web/package-lock.json* ./
RUN npm ci
COPY web/ ./
# Optional: bake a Google Analytics 4 gtag into index.html (empty => no analytics).
ARG KOYRA_GA_MEASUREMENT_ID=""
ENV KOYRA_GA_MEASUREMENT_ID=$KOYRA_GA_MEASUREMENT_ID
RUN npm run build

FROM python:3.12-slim
# git: clone consumer repos. docker CLI: drive the swarm via the mounted socket
# (client only — no daemon). Installed as the official static binary because the
# Debian `docker.io` package no longer ships the client on trixie.
ARG DOCKER_CLI_VERSION=27.5.1
ARG DOCKER_CLI_SHA256=4f798b3ee1e0140eab5bf30b0edc4e84f4cdb53255a429dc3bbae9524845d640
RUN set -eux; \
    apt-get update; \
    apt-get install -y --no-install-recommends git curl ca-certificates; \
    curl -fsSLo /tmp/docker.tgz "https://download.docker.com/linux/static/stable/x86_64/docker-${DOCKER_CLI_VERSION}.tgz"; \
    echo "${DOCKER_CLI_SHA256}  /tmp/docker.tgz" | sha256sum -c -; \
    tar -xz -C /usr/local/bin --strip-components=1 -f /tmp/docker.tgz docker/docker; \
    rm /tmp/docker.tgz; \
    docker --version; \
    git config --system --add safe.directory '*'; \
    apt-get clean; rm -rf /var/lib/apt/lists/*
WORKDIR /app
COPY control-plane/ /app/control-plane/
RUN pip install --no-cache-dir /app/control-plane
COPY --from=web /web/dist /app/web/dist
ENV KOYRA_WEB_DIST=/app/web/dist
EXPOSE 8000
CMD ["uvicorn", "koyracloud.main:app", "--host", "0.0.0.0", "--port", "8000"]
