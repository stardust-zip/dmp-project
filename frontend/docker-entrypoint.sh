#!/bin/sh
set -e

# When the node_modules named volume is empty (e.g. first `docker compose up`
# or after a `docker compose down -v`), install dependencies.
#
# Uses `npm ci` rather than `npm install` to strictly follow package-lock.json
# — this prevents the lockfile from being silently rewritten and ensures the
# same libc-annotated optional dependency metadata is preserved.
#
# The `--prefer-offline` flag pulls from the npm cache populated by the
# `RUN npm ci` layer in the Dockerfile, so no external network is needed
# on subsequent container restarts.

SENTINEL="node_modules/.package-lock.json"

if [ ! -f "$SENTINEL" ]; then
  echo "[entrypoint] node_modules is empty — running npm ci..."
  npm ci --prefer-offline
else
  echo "[entrypoint] node_modules already populated — skipping install"
fi

exec "$@"
