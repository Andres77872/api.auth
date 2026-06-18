"""Patreon provider utility package boundary.

The package initializer is deliberately metadata-only.  Do not import runtime
helpers here: submodules parse server-only configuration and security material
only when their explicit functions are called.  Keeping this file free of
imports prevents accidental secret reads or provider side effects at package
import time.
"""

from __future__ import annotations

PACKAGE_NAME = "src.Util.patreon"

__all__ = ("PACKAGE_NAME",)
