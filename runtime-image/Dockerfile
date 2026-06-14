# koyracloud-runtime — the base buildpack image.
# python:3.12 + node:22 + git. It's the `FROM` for app images koyracloud
# *generates* from a manifest, and it ships koyra_static.py (the static-site
# server those generated images run). Apps that bring their own Dockerfile
# don't use it. No app code or entrypoint lives here — each app image sets its
# own CMD.
# Pinned to bookworm (Debian 12): the unsuffixed python:3.12-slim now tracks
# trixie (Debian 13), whose apt index 404s here and breaks the node install.
FROM python:3.12-slim-bookworm

RUN apt-get update \
 && apt-get install -y --no-install-recommends git curl ca-certificates \
 && curl -fsSL https://deb.nodesource.com/setup_22.x | bash - \
 && apt-get install -y --no-install-recommends nodejs \
 && git config --system --add safe.directory '*' \
 && apt-get clean && rm -rf /var/lib/apt/lists/*

COPY koyra_static.py /koyra_static.py

WORKDIR /app
