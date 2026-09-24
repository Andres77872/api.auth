#!/usr/bin/env bash
# Container entrypoint: run the api.auth API server, the email outbox worker, the
# Patreon entitlement sync worker, AND the billing sync worker as sibling processes
# in a single container.
#
# Unlike scripts/run_email_worker.sh / scripts/run_patreon_worker.sh (systemd
# --user host: source .env, use .venv), this reads all configuration from the
# container environment (passed via `docker run --env-file` / compose
# `environment:`). src/Util/db_config.py raises at import if DB_HOST is missing,
# so those vars must be present in the env.
#
# Each worker is a separate long-running process because src/main.py has no
# lifespan hook and the worker loops are blocking. They write Redis heartbeats:
#   - email_worker   -> GET /system/health "email_worker" component
#   - patreon worker -> GET /admin/patreon/status "worker" group (dashboard)
#   - billing worker -> GET /system/health "billing_sync" component
# The Patreon worker drains the patreon_sync_jobs queue (webhook-/admin-triggered
# resyncs + scheduled sweeps). It self-disables when PATREON_SYNC_ENABLED=false,
# writing only a heartbeat, so it is safe to run unconditionally. Set
# PATREON_SYNC_WORKER_ENABLED=0 to skip the process entirely.
# The billing worker drains the billing sync queue (Stripe-webhook and S2S resync
# jobs) and runs the bounded billing retention purge. It self-disables unless
# BILLING_SYNC_ENABLED or STRIPE_SYNC_ENABLED is on, writing only a heartbeat. Set
# BILLING_SYNC_WORKER_ENABLED=0 to skip the process entirely.
#
# SIGTERM/SIGINT are forwarded to all children, and the container exits as soon
# as any process exits so the orchestrator can restart it.
set -uo pipefail

term() {
  trap - TERM INT
  kill -TERM "${WORKER_PID:-}" "${PATREON_WORKER_PID:-}" "${BILLING_WORKER_PID:-}" "${API_PID:-}" 2>/dev/null || true
}
trap term TERM INT

# Email outbox worker. worker-id derived from HOSTNAME so each replica gets a
# distinct heartbeat key (workers claim rows with DB leases; concurrent-safe).
python -m src.workers.email_worker --worker-id "${EMAIL_WORKER_ID:-container-${HOSTNAME:-worker}}" &
WORKER_PID=$!

# Patreon entitlement sync worker (optional; default on). Same isolation +
# distinct heartbeat key as the email worker.
PATREON_WORKER_PID=""
if [[ "${PATREON_SYNC_WORKER_ENABLED:-1}" != "0" ]]; then
  python -m src.workers.patreon_sync_worker --worker-id "${PATREON_WORKER_ID:-container-${HOSTNAME:-worker}-patreon}" &
  PATREON_WORKER_PID=$!
fi

# Billing sync worker (optional; default on). Same isolation + distinct heartbeat key.
BILLING_WORKER_PID=""
if [[ "${BILLING_SYNC_WORKER_ENABLED:-1}" != "0" ]]; then
  python -m src.workers.billing_sync_worker --worker-id "${BILLING_WORKER_ID:-container-${HOSTNAME:-worker}-billing}" &
  BILLING_WORKER_PID=$!
fi

# API server.
uvicorn src.main:app --host 0.0.0.0 --port "${PORT:-8000}" &
API_PID=$!

wait -n            # return when any child exits
status=$?
term               # tear down the survivors
wait
exit "$status"
