# ─── Stage 1: Vite build for the hub dashboard frontend ─────────────
# Produces hub/static/hub/dist/orochi-<hash>.js + .vite/manifest.json
# (consumed by hub.templatetags.vite.vite_bundle in dashboard.html).
FROM node:20-slim AS frontend-build

WORKDIR /build

# Install JS deps. We deliberately do NOT copy package-lock.json into
# the image: rollup/vite ship native binaries per (os, arch) and a
# lockfile generated on x86 won't pull arm64 binaries when mba builds.
# `npm install` (no lockfile) resolves the right native dep for the
# build host.
COPY hub/frontend/package.json ./
RUN npm install --no-audit --no-fund

# Copy TS sources + config and build.
COPY hub/frontend/ ./
RUN npm run build


# ─── Stage 2: Python runtime ─────────────────────────────────────────
FROM python:3.11-slim

WORKDIR /app

COPY pyproject.toml README.md ./
COPY src/ src/
COPY hub/ hub/
COPY orochi/ orochi/
COPY manage.py ./

# Overlay the Vite build output into the source tree so Django's
# staticfiles app can collect it alongside the hand-authored CSS
# that still lives under hub/static/hub/.
# vite.config.ts resolves outDir to ../static/hub/dist relative to
# the frontend dir; inside stage 1 that lands at /static/hub/dist.
COPY --from=frontend-build /static/hub/dist /app/hub/static/hub/dist

RUN pip install --no-cache-dir .

EXPOSE 8559

ENV DJANGO_SETTINGS_MODULE=orochi.settings
ENV DJANGO_ALLOWED_HOSTS=*
ENV SCITEX_OROCHI_DB_PATH=/data/db.sqlite3

COPY deployment/docker/entrypoint.sh /app/entrypoint.sh
RUN chmod +x /app/entrypoint.sh

VOLUME /data

ENTRYPOINT ["/app/entrypoint.sh"]
