#!/usr/bin/env bash
# Launch the api.auth transactional email outbox worker with .env loaded.
#
# Used by the systemd --user service (api-auth-email-worker.service) and for
# manual runs. The application reads its configuration (DB/Redis/email) from the
# process environment at IMPORT time (src/Util/db_config.py raises if DB_HOST is
# missing), so .env must be sourced before the worker module is imported.
#
# Usage:
#   scripts/run_email_worker.sh            # run forever (poll loop)
#   scripts/run_email_worker.sh --once     # drain one batch and exit
set -euo pipefail

PROJECT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$PROJECT_DIR"

if [[ ! -f .env ]]; then
    echo "run_email_worker: .env not found in $PROJECT_DIR" >&2
    exit 1
fi

# Export every assignment from .env into the environment (handles quoted values).
set -a
# shellcheck disable=SC1091
source .env
set +a

exec .venv/bin/python -m src.workers.email_worker "$@"
