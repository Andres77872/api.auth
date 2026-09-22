"""Provider-agnostic OAuth login package.

Three levels (see ``docs/agnostic_oauth``):

* provider *type*  -- adapter code registered in :mod:`src.Util.oauth.registry`
* *connection*     -- client credentials and endpoints (environment or database)
* project *binding* -- per-project policy and URL allow-lists

This package is metadata-only at import time: it does not read environment
variables, touch Redis, open database connections or contact providers. Runtime
code opts in by importing concrete helpers from the submodules.
"""

from __future__ import annotations

PACKAGE_NAME = "src.Util.oauth"
CONTRACT_VERSION = 1

__all__ = ["CONTRACT_VERSION", "PACKAGE_NAME"]
