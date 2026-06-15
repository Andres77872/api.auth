#!/usr/bin/env bash
# Container entrypoint: run the api.auth API server AND the email outbox worker
# as sibling processes in a single container.
#
# Unlike scripts/run_email_worker.sh (systemd --user host: sources .env, uses
# .venv), this reads all configuration from the container environment (passed via
# `docker run --env-file` / compose `environment:`). src/Util/db_config.py raises
# at import if DB_HOST is missing, so those vars must be present in the env.
#
# The worker is a separate long-running process because src/main.py has no
# lifespan hook and the worker loop is blocking. It writes the Redis heartbeat
# that GET /system/health reads, so without it `email_worker` reports unhealthy.
#
# SIGTERM/SIGINT are forwarded to both children, and the container exits as soon
# as either process exits so the orchestrator can restart it.
set -uo pipefail

term() {
  trap - TERM INT
  kill -TERM "${WORKER_PID:-}" "${API_PID:-}" 2>/dev/null || true
}
trap term TERM INT

# Email outbox worker. worker-id derived from HOSTNAME so each replica gets a
# distinct heartbeat key (workers claim rows with DB leases; concurrent-safe).
python -m src.workers.email_worker --worker-id "${EMAIL_WORKER_ID:-container-${HOSTNAME:-worker}}" &
WORKER_PID=$!

# API server.
uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
API_PID=$!

wait -n            # return when either child exits
status=$?
term               # tear down the survivor
wait
exit "$status"
