"""Startup diagnosis for Uvicorn's optional WebSocket protocol dependencies."""
from __future__ import annotations

import importlib
import logging
from pathlib import Path
import shlex
import sys

logger = logging.getLogger(__name__)


def websocket_transport_available() -> bool:
    """Check the same auto-selected protocol used by the deployed Uvicorn CLI.

    Merely importing FastAPI or registering a WebSocket route does not prove the
    server can upgrade a network connection. Without websockets or wsproto,
    Uvicorn can still serve HTTP while treating an upgrade as an ordinary GET.
    This does not import model libraries or open an assistant data store.
    """
    try:
        module = importlib.import_module("uvicorn.protocols.websockets.auto")
    except ImportError:
        return False
    return getattr(module, "AutoWebSocketsProtocol", None) is not None


def warn_if_websocket_transport_missing() -> bool:
    """Warn with the active interpreter so a different environment isn't fixed."""
    ready = websocket_transport_available()
    if not ready:
        requirements = Path(__file__).resolve().parents[2] / "requirements.txt"
        command = f"{shlex.quote(sys.executable)} -m pip install -r {shlex.quote(str(requirements))}"
        logger.warning(
            "AI assistant WebSocket transport is unavailable in Python %s. "
            "HTTP endpoints can still work, but /admin/assistant/ws cannot "
            "upgrade and may return HTTP 404. Install this application's "
            "dependencies into the running interpreter with `%s`, then restart "
            "Uvicorn. Use --ws auto (the default) or an installed WebSocket backend.",
            sys.executable,
            command,
        )
    return ready
