#!/usr/bin/env bash
set -euo pipefail

python scripts/wait-for-e2e-services.py
printf 'Running e2e tests inside isolated container with %s\n' "$(python --version 2>&1)"
exec "$@"
