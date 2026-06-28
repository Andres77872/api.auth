"""Provider-agnostic billing utility package.

This package is deliberately metadata-only at import time: it does not read
environment variables, create provider clients, import Stripe, touch Redis, or
open database connections. Runtime code must opt in by importing concrete
helpers from the submodules.
"""

from __future__ import annotations

PACKAGE_NAME = "src.Util.billing"
CONTRACT_VERSION = 2

__all__ = ["CONTRACT_VERSION", "PACKAGE_NAME"]
