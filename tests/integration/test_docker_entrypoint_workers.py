"""Which processes the container entrypoint starts, run against stub ``python``/``uvicorn`` binaries.

The billing sync worker drains the queue that Stripe webhooks and the S2S resync route write to,
so a container without it silently never repairs billing facts. It starts by default, like the
Patreon worker, and ``BILLING_SYNC_WORKER_ENABLED=0`` opts out.
"""

from __future__ import annotations

import os
import shutil
import stat
import subprocess
from pathlib import Path

import pytest


ROOT = Path(__file__).resolve().parents[2]
ENTRYPOINT = ROOT / "scripts" / "docker-entrypoint.sh"

# Each stub records its argv, then lingers long enough that every sibling has started (and
# recorded itself) before the first exit makes the entrypoint tear the others down.
_STUB = """#!/usr/bin/env bash
echo "$(basename "$0") $*" >> "$ENTRYPOINT_LAUNCH_LOG"
sleep 0.5
"""


def _launched(tmp_path: Path, **env_overrides: str) -> list[str]:
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    for name in ("python", "uvicorn"):
        stub = bin_dir / name
        stub.write_text(_STUB)
        stub.chmod(stub.stat().st_mode | stat.S_IEXEC)
    log = tmp_path / "launched.log"
    env = {
        "PATH": f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}",
        "HOSTNAME": "unit-host",
        "ENTRYPOINT_LAUNCH_LOG": str(log),
        **env_overrides,
    }
    subprocess.run([shutil.which("bash") or "/bin/bash", str(ENTRYPOINT)], env=env, timeout=20, check=False)
    return sorted(log.read_text().splitlines()) if log.exists() else []


def _workers(lines: list[str]) -> set[str]:
    return {line.split()[2] for line in lines if line.startswith("python -m ")}


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_entrypoint_starts_the_billing_sync_worker_by_default(tmp_path):
    lines = _launched(tmp_path)

    assert _workers(lines) == {
        "src.workers.email_worker",
        "src.workers.patreon_sync_worker",
        "src.workers.billing_sync_worker",
    }
    assert any(line.startswith("uvicorn src.main:app") for line in lines)
    billing = next(line for line in lines if "billing_sync_worker" in line)
    assert "--worker-id container-unit-host-billing" in billing


@pytest.mark.skipif(shutil.which("bash") is None, reason="needs bash")
def test_billing_sync_worker_can_be_switched_off(tmp_path):
    lines = _launched(tmp_path, BILLING_SYNC_WORKER_ENABLED="0")

    assert "src.workers.billing_sync_worker" not in _workers(lines)
    assert {"src.workers.email_worker", "src.workers.patreon_sync_worker"} <= _workers(lines)
