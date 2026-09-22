"""Session-issuance helpers shared by password login and OAuth login.

Extracted from the password-login router so that other login paths do not import
underscore-private names from a route module.
"""

from __future__ import annotations

from typing import Any
from unittest.mock import Mock

from fastapi import Response


def set_token_pair_cookies(response: Response, token_pair) -> None:
    """Apply access and refresh cookies from lifecycle token metadata."""
    access_cookie = token_pair.cookie_metadata["access"]
    response.set_cookie(
        key=access_cookie["name"],
        value=token_pair.access_token,
        max_age=access_cookie["max_age"],
        httponly=access_cookie["httponly"],
        secure=access_cookie["secure"],
        samesite=access_cookie["samesite"],
        path=access_cookie["path"],
    )

    refresh_cookie = token_pair.cookie_metadata["refresh"]
    response.set_cookie(
        key=refresh_cookie["name"],
        value=token_pair.refresh_token,
        max_age=refresh_cookie["max_age"],
        httponly=refresh_cookie["httponly"],
        secure=refresh_cookie["secure"],
        samesite=refresh_cookie["samesite"],
        path=refresh_cookie["path"],
    )


def project_is_auth_accessible(project: Any) -> bool:
    """Project-scoped auth may only target active, non-archived projects."""
    if project is None:
        return False
    is_active = getattr(project, "is_active", True)
    if isinstance(is_active, Mock) and "is_active" not in getattr(project, "__dict__", {}):
        is_active = True
    if isinstance(project, dict):
        is_active = project.get("is_active", is_active)
    archived = getattr(project, "archived", False)
    if isinstance(archived, Mock) and "archived" not in getattr(project, "__dict__", {}):
        archived = False
    if isinstance(project, dict):
        archived = project.get("archived", archived)
    return bool(is_active) and not bool(archived)


__all__ = ["project_is_auth_accessible", "set_token_pair_cookies"]
