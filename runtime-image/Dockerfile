# koyracloud-runtime — the shared buildpack image.
# python:3.12 + node:22 + git + the generic entrypoint. No app code lives here;
# app code, venv and build caches live on the NFS volume mounted at /workspace.
FROM python:3.12-slim

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && git config --system --add safe.directory '*' \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

RUN pip install --no-cache-dir pyyaml==6.0.2

COPY entrypoint.py /entrypoint.py

WORKDIR /workspace
ENTRYPOINT ["python3", "/entrypoint.py"]
