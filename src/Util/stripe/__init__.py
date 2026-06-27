"""Stripe provider adapter package for provider-agnostic billing.

Trace: `.dev/sdd/changes/provider-agnostic-billing-stripe/tasks.md` task 6.1.

This package is intentionally metadata-only at import time: no Stripe SDK client
is created, no environment variables are read, and no provider calls are made.
"""

from __future__ import annotations

PROVIDER = "stripe"
PACKAGE_CONTRACT_VERSION = 2

__all__ = ["PACKAGE_CONTRACT_VERSION", "PROVIDER"]
