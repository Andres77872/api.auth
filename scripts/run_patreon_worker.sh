#!/usr/bin/env bash
# Launch the api.auth Patreon entitlement sync worker with .env loaded.
#
# Mirrors scripts/run_email_worker.sh. Used by a systemd --user service and for
# manual/host runs. The application reads its configuration (DB/Redis/Patreon)
# from the process environment at IMPORT time (src/Util/db_config.py raises if
# DB_HOST is missing), so .env must be sourced before the worker is imported.
#
# The worker is a separate long-running process: it polls the patreon_sync_jobs
# queue (webhook-/admin-/schedule-triggered), re-fetches from Patreon, and
# re-classifies entitlements. It self-disables (no DB writes) when
# PATREON_SYNC_ENABLED is false, writing only a heartbeat the dashboard reads.
#
# Usage:
#   scripts/run_patreon_worker.sh                         # run forever (poll loop)
#   scripts/run_patreon_worker.sh --once                  # one queued pass and exit
#   scripts/run_patreon_worker.sh --once --mode full_campaign_sweep
#   scripts/run_patreon_worker.sh --once --mode retention_only
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ ! -f .env ]]; then
    echo "run_patreon_worker: .env not found in $PROJECT_DIR" >&2
    exit 1
fi

# Export every assignment from .env into the environment (handles quoted values).
set -a
# shellcheck disable=SC1091
source .env
set +a

# Stable worker id so the heartbeat key is distinct from other workers.
WORKER_ID="${PATREON_WORKER_ID:-host-$(hostname)-patreon}"

PY="${PROJECT_DIR}/.venv/bin/python"
[[ -x "$PY" ]] || PY="python"

exec "$PY" -m src.workers.patreon_sync_worker --worker-id "$WORKER_ID" "$@"
