"""Auth token-pair lifecycle helpers.

This module is the single shared abstraction for the new access/refresh-token
family model. Phase 2 starts with issuance, hashing, key storage, and revocation
primitives; route-level rotation and validation consumers are wired in later
phases.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Dict, Iterable, List, Optional
from unittest.mock import Mock
from uuid import uuid4

from fastapi import HTTPException
from redis.exceptions import WatchError

from src.Util.JWT_Security import JWTTokenHandler, JWT_ACCESS_TOKEN_EXPIRE_MINUTES
from src.Util.auth_constants import (
    ACCESS_COOKIE_NAME,
    ACCESS_COOKIE_PATH,
    AUTH_SCOPE_PLATFORM,
    AUTH_SCOPE_PROJECT,
    COOKIE_HTTPONLY,
    COOKIE_SAMESITE,
    COOKIE_SECURE,
    PLATFORM_COLLECTION_SENTINEL,
    REFRESH_COOKIE_NAME,
    REFRESH_COOKIE_PATH,
    REFRESH_ANCHOR_PREFIX,
    REFRESH_FAMILY_PREFIX,
    REFRESH_FAMILY_TTL_SECONDS,
    REFRESH_TOKEN_PREFIX,
    REFRESH_USED_PREFIX,
    REMEMBER_ME_REFRESH_TTL_SECONDS,
    REVOKED_FAMILY_PREFIX,
    SESSION_FULL_PREFIX,
    SESSION_PREFIX,
    TOKEN_TYPE_BEARER,
    USER_REFRESH_FAMILIES_PREFIX,
    USER_SESSIONS_PREFIX,
)
from src.Util.db_config import redis_client


@dataclass
class TokenPair:
    access_token: str
    refresh_token: str
    session_token: str
    token_type: str
    expires_in: int
    refresh_expires_in: int
    expires_at: datetime
    refresh_expires_at: datetime
    access_claims: Dict[str, Any]
    refresh_claims: Dict[str, Any]
    cookie_metadata: Dict[str, Dict[str, Any]] = field(default_factory=dict)


@dataclass
class RefreshRotation:
    token_pair: TokenPair
    login_data: Any
    session_payload: Dict[str, Any]
    family_payload: Dict[str, Any]
    old_access_jti: str
    old_refresh_jti: str


@dataclass
class AuthContext:
    """DB-backed active user/context reconstruction result.

    This is intentionally small: route response shaping still belongs in the
    routes/models layer. The lifecycle layer only proves that the user, scope,
    project/platform context, and authorization hooks are still valid before a
    cached full-session representation may be trusted.
    """

    scope: str
    user: Any
    project: Optional[Any] = None
    permissions: List[str] = field(default_factory=list)
    groups: List[str] = field(default_factory=list)
    available_projects: List[Any] = field(default_factory=list)


@dataclass
class RevocationSummary:
    sessions_seen: int = 0
    sessions_revoked: int = 0
    families_revoked: int = 0
    sessions_preserved: int = 0
    sessions_skipped: int = 0
    sessions_missing: int = 0


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def compute_refresh_expires_at(
    now: Optional[datetime] = None,
    ttl_seconds: int = REFRESH_FAMILY_TTL_SECONDS,
) -> datetime:
    base = now or _utc_now()
    return base + timedelta(seconds=ttl_seconds)


def _parse_datetime(value: Any) -> Optional[datetime]:
    if value is None:
        return None
    if isinstance(value, datetime):
        parsed = value
    elif isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return None
    else:
        return None

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _seconds_until(value: Any, now: Optional[datetime] = None) -> int:
    expires_at = _parse_datetime(value)
    if expires_at is None:
        return 0
    current = now or _utc_now()
    return max(0, int((expires_at - current).total_seconds()))


def _cache_ttl_for_family(family: Optional[Dict[str, Any]]) -> int:
    if not family:
        return REFRESH_FAMILY_TTL_SECONDS
    if family.get("remember_me"):
        return max(1, _seconds_until(family.get("absolute_expires_at") or family.get("expires_at")))
    return int(family.get("refresh_ttl_seconds") or REFRESH_FAMILY_TTL_SECONDS)


def hash_refresh_token(refresh_token: str) -> str:
    return hashlib.sha256(refresh_token.encode()).hexdigest()


def _json_default(value: Any) -> str:
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def _set_json(key: str, value: Dict[str, Any], ttl_seconds: int) -> None:
    redis_client.set(key, json.dumps(value, default=_json_default), ex=ttl_seconds)


def _get_json(key: str) -> Optional[Dict[str, Any]]:
    raw = redis_client.get(key)
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw)


def _loads_json(raw: Any) -> Optional[Dict[str, Any]]:
    if not raw:
        return None
    if isinstance(raw, bytes):
        raw = raw.decode()
    return json.loads(raw)


def _refresh_anchor_key(family_id: str) -> str:
    return f"{REFRESH_ANCHOR_PREFIX}{family_id}"


def _decode_set_members(members: Iterable[Any]) -> List[str]:
    decoded = []
    for member in members:
        if isinstance(member, bytes):
            member = member.decode()
        decoded.append(str(member))
    return decoded


def _build_refresh_anchor_payload(
    *,
    session_payload: Dict[str, Any],
    family_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Build the long-lived, non-secret refresh continuity seed.

    The anchor deliberately excludes raw tokens, token hashes, permissions,
    groups, and full-session cache payloads. Rotation still reconstructs the
    authoritative user/project/permission context through DB hooks before a new
    pair is issued.
    """
    scope = str(session_payload.get("scope") or family_payload.get("scope") or AUTH_SCOPE_PROJECT)
    project_hash = session_payload.get("project_hash") if scope == AUTH_SCOPE_PROJECT else None
    collection = session_payload.get("collection")
    if scope == AUTH_SCOPE_PLATFORM:
        collection = PLATFORM_COLLECTION_SENTINEL
    else:
        collection = collection or project_hash or family_payload.get("project_hash")

    created_at = family_payload.get("created_at") or session_payload.get("issued_at")
    updated_at = family_payload.get("updated_at") or created_at

    return {
        "anchor_version": 1,
        "family_id": family_payload.get("family_id") or session_payload.get("family_id"),
        "session_id": session_payload.get("session_id"),
        "status": "active",
        "user_id": session_payload.get("user_id") or family_payload.get("user_id"),
        "user_hash": session_payload.get("user_hash") or family_payload.get("user_hash"),
        "username": session_payload.get("username"),
        "user_type": session_payload.get("user_type"),
        "scope": scope,
        "collection": collection,
        "project_id": session_payload.get("project_id") if scope == AUTH_SCOPE_PROJECT else None,
        "project_hash": project_hash,
        "project_name": session_payload.get("project_name") if scope == AUTH_SCOPE_PROJECT else None,
        "current_access_jti": family_payload.get("current_access_jti") or session_payload.get("access_jti"),
        "current_refresh_jti": family_payload.get("current_refresh_jti") or session_payload.get("refresh_jti"),
        "created_at": created_at,
        "updated_at": updated_at,
        "expires_at": family_payload.get("expires_at"),
        "remember_me": bool(family_payload.get("remember_me") or session_payload.get("remember_me", False)),
        "refresh_ttl_seconds": family_payload.get("refresh_ttl_seconds") or session_payload.get("refresh_ttl_seconds"),
        "absolute_expires_at": family_payload.get("absolute_expires_at") or session_payload.get("absolute_expires_at"),
    }


def _anchor_matches_claims_and_family(
    anchor: Optional[Dict[str, Any]],
    claims: Dict[str, Any],
    family: Dict[str, Any],
) -> bool:
    if not anchor or anchor.get("status") != "active":
        return False

    family_id = str(family.get("family_id") or "")
    refresh_jti = str(claims.get("jti") or "")
    scope = str(family.get("scope") or claims.get("scope") or AUTH_SCOPE_PROJECT)
    expected_collection = (
        PLATFORM_COLLECTION_SENTINEL
        if scope == AUTH_SCOPE_PLATFORM
        else (family.get("project_hash") or anchor.get("project_hash"))
    )

    required_comparisons = {
        "family_id": family_id,
        "session_id": claims.get("session_id"),
        "user_hash": family.get("user_hash") or claims.get("user_hash"),
        "scope": scope,
        "current_refresh_jti": refresh_jti,
    }
    for anchor_field, expected in required_comparisons.items():
        if expected is None or str(anchor.get(anchor_field)) != str(expected):
            return False

    if family.get("current_access_jti") and str(anchor.get("current_access_jti")) != str(family.get("current_access_jti")):
        return False
    if expected_collection is None or str(anchor.get("collection")) != str(expected_collection):
        return False
    if str(claims.get("collection")) != str(expected_collection):
        return False
    return True


def _anchor_to_session_seed(
    anchor: Dict[str, Any],
    claims: Dict[str, Any],
    family: Dict[str, Any],
) -> Dict[str, Any]:
    scope = str(anchor.get("scope") or family.get("scope") or claims.get("scope") or AUTH_SCOPE_PROJECT)
    collection = PLATFORM_COLLECTION_SENTINEL if scope == AUTH_SCOPE_PLATFORM else anchor.get("collection")
    project_hash = anchor.get("project_hash") if scope == AUTH_SCOPE_PROJECT else None
    if scope == AUTH_SCOPE_PROJECT and not collection:
        collection = project_hash

    return {
        "access_jti": anchor.get("current_access_jti") or family.get("current_access_jti"),
        "session_id": anchor.get("session_id") or claims.get("session_id"),
        "family_id": anchor.get("family_id") or family.get("family_id"),
        "refresh_jti": anchor.get("current_refresh_jti") or claims.get("jti"),
        "user_id": anchor.get("user_id") or family.get("user_id"),
        "user_hash": anchor.get("user_hash") or family.get("user_hash") or claims.get("user_hash"),
        "username": anchor.get("username"),
        "user_type": anchor.get("user_type"),
        "scope": scope,
        "collection": collection,
        "project_id": anchor.get("project_id") if scope == AUTH_SCOPE_PROJECT else None,
        "project_hash": project_hash,
        "project_name": anchor.get("project_name") if scope == AUTH_SCOPE_PROJECT else None,
        "issued_at": anchor.get("updated_at") or anchor.get("created_at"),
        "expires_at": None,
        "remember_me": bool(anchor.get("remember_me", False)),
        "refresh_ttl_seconds": anchor.get("refresh_ttl_seconds"),
        "absolute_expires_at": anchor.get("absolute_expires_at"),
    }


def _legacy_family_claims_seed(family: Dict[str, Any], claims: Dict[str, Any]) -> Dict[str, Any]:
    """Build a safe seed for pre-anchor families after token/family validation.

    This fallback is intentionally narrow. If required identifiers cannot be
    proven from the active family plus signed refresh claims, refresh fails
    closed and the user must re-login.
    """
    family_id = str(family.get("family_id") or "")
    refresh_jti = str(claims.get("jti") or "")
    session_id = claims.get("session_id")
    user_hash = family.get("user_hash") or claims.get("user_hash")
    scope = str(family.get("scope") or claims.get("scope") or AUTH_SCOPE_PROJECT)

    if not family_id or family_id != str(claims.get("family_id")):
        raise _auth_unauthorized("Refresh context unavailable; re-login required")
    if not refresh_jti or not session_id or not user_hash:
        raise _auth_unauthorized("Refresh context unavailable; re-login required")

    if scope == AUTH_SCOPE_PLATFORM:
        collection = PLATFORM_COLLECTION_SENTINEL
        project_hash = None
        project_id = None
    else:
        collection = claims.get("collection") or family.get("project_hash")
        project_hash = family.get("project_hash") or (collection if collection != PLATFORM_COLLECTION_SENTINEL else None)
        project_id = family.get("project_id")
        if not collection or not project_hash:
            raise _auth_unauthorized("Refresh context unavailable; re-login required")

    return {
        "access_jti": str(family.get("current_access_jti") or ""),
        "session_id": str(session_id),
        "family_id": family_id,
        "refresh_jti": refresh_jti,
        "user_id": family.get("user_id"),
        "user_hash": user_hash,
        "username": None,
        "user_type": None,
        "scope": scope,
        "collection": collection,
        "project_id": project_id,
        "project_hash": project_hash,
        "project_name": None,
        "issued_at": family.get("updated_at") or family.get("created_at"),
        "expires_at": None,
        "remember_me": bool(family.get("remember_me", False)),
        "refresh_ttl_seconds": family.get("refresh_ttl_seconds"),
        "absolute_expires_at": family.get("absolute_expires_at"),
    }


def _as_mapping(value: Any) -> Dict[str, Any]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return value
    return {
        key: getattr(value, key)
        for key in dir(value)
        if not key.startswith("_") and not callable(getattr(value, key))
    }


def _field(value: Any, name: str, default: Any = None) -> Any:
    if isinstance(value, dict):
        return value.get(name, default)
    attr = getattr(value, name, default)
    # MagicMock fabricates missing attributes on access. Treat those fabricated
    # child mocks as absent so tests and dependency fakes don't leak invalid
    # values into strict Pydantic response models.
    if isinstance(attr, Mock) and name not in getattr(value, "__dict__", {}):
        return default
    return attr


def _project_is_active_for_auth(project: Any) -> bool:
    """Auth contexts may only target active, non-archived projects."""
    if not bool(_field(project, "is_active", True)):
        return False
    return not bool(_field(project, "archived", False))


def _call_user_by_hash(get_user_by_hash_fn: Callable[..., Any], user_hash: str) -> Any:
    try:
        return get_user_by_hash_fn(user_hash, include_inactive=True)
    except TypeError:
        return get_user_by_hash_fn(user_hash)


def _default_get_user_by_hash(user_hash: str, include_inactive: bool = True) -> Any:
    from src.Util.db.db_users import get_user_by_hash

    return get_user_by_hash(user_hash, include_inactive=include_inactive)


def _default_get_project_by_hash(project_hash: str) -> Any:
    from src.Util.db.db_projects import get_project_by_hash

    return get_project_by_hash(project_hash)


def _default_check_admin_project_access(user_id: str, project_id: str) -> bool:
    # Use the DB helper directly to avoid importing db_enhanced at module load
    # time; db_enhanced will later delegate validation into this module.
    from src.Util.db.db_users import check_admin_multi_project_access

    return check_admin_multi_project_access(user_id, project_id)


def _default_get_user_groups_in_project_by_hash(user_id: str, project_hash: str) -> List[Any]:
    from src.Util.db.db_user_groups import get_user_groups_in_project_by_hash

    return get_user_groups_in_project_by_hash(user_id, project_hash)


def _default_get_user_permissions(user_id: str) -> List[str]:
    from src.Util.db.db_global_roles import get_user_permissions

    return get_user_permissions(user_id)


def _default_get_user_accessible_projects(user_id: str) -> List[Any]:
    from src.Util.db.db_user_groups import get_user_accessible_projects

    return get_user_accessible_projects(user_id)


def _group_names(groups: Iterable[Any]) -> List[str]:
    return [str(_field(group, "group_name", group)) for group in groups]


def _safe_call_list(fn: Callable[..., Iterable[Any]], *args: Any) -> List[Any]:
    try:
        return list(fn(*args) or [])
    except Exception:
        return []


def _revoke_context_state(session_payload: Dict[str, Any], reason: str) -> None:
    family_id = session_payload.get("family_id")
    access_jti = (
        session_payload.get("access_jti")
        or session_payload.get("jti")
        or session_payload.get("current_access_jti")
    )

    if family_id:
        revoke_refresh_family(str(family_id), reason=reason)
    elif access_jti:
        revoke_access_session(str(access_jti))


def load_active_user(
    user_hash: str,
    *,
    session_payload: Optional[Dict[str, Any]] = None,
    get_user_by_hash_fn: Optional[Callable[..., Any]] = None,
) -> Optional[Any]:
    """Load a user including inactive rows and fail closed if not active.

    The adapter intentionally asks for inactive visibility so missing and
    deactivated users can both be classified instead of letting a default
    active-only lookup hide the reason. In either case, known auth state is
    revoked before returning ``None``.
    """
    getter = get_user_by_hash_fn or _default_get_user_by_hash
    user = _call_user_by_hash(getter, user_hash)
    payload = session_payload or {}

    if user is None:
        _revoke_context_state(payload, reason="missing_user")
        return None

    if not bool(_field(user, "is_active", True)):
        _revoke_context_state(payload, reason="inactive_user")
        return None

    return user


def reconstruct_auth_context(
    session_payload: Dict[str, Any],
    *,
    get_user_by_hash_fn: Optional[Callable[..., Any]] = None,
    get_project_by_hash_fn: Optional[Callable[[str], Any]] = None,
    check_admin_project_access_fn: Optional[Callable[[str, str], bool]] = None,
    get_user_groups_in_project_by_hash_fn: Optional[Callable[[str, str], Iterable[Any]]] = None,
    get_user_permissions_fn: Optional[Callable[[str], Iterable[str]]] = None,
    get_user_accessible_projects_fn: Optional[Callable[[str], Iterable[Any]]] = None,
) -> Optional[AuthContext]:
    """Reconstruct active project/platform auth context through DB hooks.

    This adapter is used by later validation/refresh/switch paths to ensure a
    cached session cannot bypass missing-user, inactive-user, platform-scope, or
    project-access checks.
    """
    user_hash = session_payload.get("user_hash")
    if not user_hash:
        _revoke_context_state(session_payload, reason="missing_user")
        return None

    user = load_active_user(
        str(user_hash),
        session_payload=session_payload,
        get_user_by_hash_fn=get_user_by_hash_fn,
    )
    if user is None:
        return None

    scope = session_payload.get("scope") or AUTH_SCOPE_PROJECT
    user_id = str(_field(user, "id", session_payload.get("user_id")))
    user_type = str(_field(user, "user_type", session_payload.get("user_type", "consumer")))

    if scope == AUTH_SCOPE_PLATFORM:
        if user_type not in {"root", "admin"}:
            _revoke_context_state(session_payload, reason="platform_access_denied")
            return None

        if user_type == "root":
            default_permissions = ["admin", "global_admin", "manage_users", "manage_roles", "unrestricted_access"]
            default_groups = ["platform_root_users"]
        else:
            default_permissions = ["admin", "project_admin", "manage_users", "manage_roles", "manage_permissions"]
            default_groups = ["platform_admins"]

        return AuthContext(
            scope=AUTH_SCOPE_PLATFORM,
            user=user,
            project=None,
            permissions=list(session_payload.get("permissions") or default_permissions),
            groups=list(session_payload.get("groups") or default_groups),
            available_projects=[],
        )

    project_hash = session_payload.get("project_hash") or session_payload.get("collection")
    if not project_hash:
        _revoke_context_state(session_payload, reason="missing_project_context")
        return None

    project_getter = get_project_by_hash_fn or _default_get_project_by_hash
    project = project_getter(str(project_hash))
    if project is None:
        _revoke_context_state(session_payload, reason="missing_project")
        return None
    if not _project_is_active_for_auth(project):
        _revoke_context_state(session_payload, reason="project_inactive_or_archived")
        return None

    accessible_projects_getter = get_user_accessible_projects_fn or _default_get_user_accessible_projects
    available_projects = _safe_call_list(accessible_projects_getter, user_id)

    if user_type == "root":
        return AuthContext(
            scope=AUTH_SCOPE_PROJECT,
            user=user,
            project=project,
            permissions=list(session_payload.get("permissions") or ["admin", "global_admin", "unrestricted_access"]),
            groups=list(session_payload.get("groups") or ["root_users"]),
            available_projects=available_projects,
        )

    if user_type == "admin":
        access_checker = check_admin_project_access_fn or _default_check_admin_project_access
        if not access_checker(user_id, str(_field(project, "id"))):
            _revoke_context_state(session_payload, reason="project_access_denied")
            return None
        return AuthContext(
            scope=AUTH_SCOPE_PROJECT,
            user=user,
            project=project,
            permissions=list(session_payload.get("permissions") or ["admin", "project_admin", "manage_users", "manage_groups", "manage_permissions"]),
            groups=list(session_payload.get("groups") or ["project_admins"]),
            available_projects=available_projects,
        )

    groups_getter = get_user_groups_in_project_by_hash_fn or _default_get_user_groups_in_project_by_hash
    groups = _safe_call_list(groups_getter, user_id, str(project_hash))
    if not groups:
        _revoke_context_state(session_payload, reason="project_access_denied")
        return None

    permissions_getter = get_user_permissions_fn or _default_get_user_permissions
    permissions = [str(permission) for permission in _safe_call_list(permissions_getter, user_id)]

    return AuthContext(
        scope=AUTH_SCOPE_PROJECT,
        user=user,
        project=project,
        permissions=permissions,
        groups=_group_names(groups),
        available_projects=available_projects,
    )


def _build_cookie_metadata(refresh_max_age: int = REFRESH_FAMILY_TTL_SECONDS) -> Dict[str, Dict[str, Any]]:
    access_ttl = int(JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    return {
        "access": {
            "name": ACCESS_COOKIE_NAME,
            "path": ACCESS_COOKIE_PATH,
            "max_age": access_ttl,
            "httponly": COOKIE_HTTPONLY,
            "secure": COOKIE_SECURE,
            "samesite": COOKIE_SAMESITE,
        },
        "refresh": {
            "name": REFRESH_COOKIE_NAME,
            "path": REFRESH_COOKIE_PATH,
            "max_age": refresh_max_age,
            "httponly": COOKIE_HTTPONLY,
            "secure": COOKIE_SECURE,
            "samesite": COOKIE_SAMESITE,
        },
    }


def _issue_token_pair(
    *,
    user: Any,
    scope: str,
    collection: Optional[str],
    project: Optional[Any] = None,
    permissions: Optional[List[str]] = None,
    groups: Optional[List[str]] = None,
    group_ids: Optional[List[str]] = None,
    remember_me: bool = False,
    refresh_ttl_seconds: Optional[int] = None,
) -> TokenPair:
    user_data = _as_mapping(user)
    project_data = _as_mapping(project)
    now = _utc_now()
    access_ttl = int(JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    access_expires_at = now + timedelta(seconds=access_ttl)
    effective_refresh_ttl = int(
        refresh_ttl_seconds
        or (REMEMBER_ME_REFRESH_TTL_SECONDS if remember_me else REFRESH_FAMILY_TTL_SECONDS)
    )
    refresh_expires_at = compute_refresh_expires_at(now, effective_refresh_ttl)
    absolute_expires_at = refresh_expires_at.isoformat() if remember_me else None

    family_id = str(uuid4())
    session_id = str(uuid4())
    access_jti = str(uuid4())
    refresh_jti = str(uuid4())

    access_token = JWTTokenHandler.create_access_token(
        session_id=session_id,
        user_hash=user_data.get("user_hash"),
        collection=collection,
        scope=scope,
        jti=access_jti,
        family_id=family_id,
    )
    refresh_token = JWTTokenHandler.create_refresh_token(
        session_id=session_id,
        user_hash=user_data.get("user_hash"),
        collection=collection,
        scope=scope,
        jti=refresh_jti,
        family_id=family_id,
        expires_delta=timedelta(seconds=effective_refresh_ttl),
    )
    access_claims = JWTTokenHandler.decode_access_token(access_token)
    refresh_claims = JWTTokenHandler.decode_refresh_token(refresh_token)

    session_payload = {
        "access_jti": access_jti,
        "session_id": session_id,
        "family_id": family_id,
        "refresh_jti": refresh_jti,
        "user_id": user_data.get("id"),
        "user_hash": user_data.get("user_hash"),
        "username": user_data.get("username"),
        "user_type": user_data.get("user_type", "consumer"),
        "scope": scope,
        "project_id": project_data.get("id"),
        "project_hash": project_data.get("project_hash") if scope == AUTH_SCOPE_PROJECT else None,
        "project_name": project_data.get("project_name") if scope == AUTH_SCOPE_PROJECT else None,
        "collection": collection,
        "permissions": permissions or [],
        "groups": groups or [],
        "user_group_ids": group_ids or [],
        "user_group_names": groups or [],
        "issued_at": now.isoformat(),
        "expires_at": access_expires_at.isoformat(),
        "remember_me": bool(remember_me),
        "refresh_ttl_seconds": effective_refresh_ttl,
        "absolute_expires_at": absolute_expires_at,
    }
    family_payload = {
        "family_id": family_id,
        "status": "active",
        "user_id": user_data.get("id"),
        "user_hash": user_data.get("user_hash"),
        "scope": scope,
        "project_id": project_data.get("id") if scope == AUTH_SCOPE_PROJECT else None,
        "project_hash": project_data.get("project_hash") if scope == AUTH_SCOPE_PROJECT else None,
        "current_refresh_jti": refresh_jti,
        "current_access_jti": access_jti,
        "created_at": now.isoformat(),
        "updated_at": now.isoformat(),
        "expires_at": refresh_expires_at.isoformat(),
        "remember_me": bool(remember_me),
        "refresh_ttl_seconds": effective_refresh_ttl,
        "absolute_expires_at": absolute_expires_at,
        "revoked_at": None,
        "revocation_reason": None,
    }
    refresh_payload = {
        "refresh_jti": refresh_jti,
        "family_id": family_id,
        "user_id": user_data.get("id"),
        "token_hash": hash_refresh_token(refresh_token),
        "status": "current",
        "parent_jti": None,
        "child_jti": None,
        "issued_at": now.isoformat(),
        "used_at": None,
        "expires_at": refresh_expires_at.isoformat(),
        "remember_me": bool(remember_me),
        "refresh_ttl_seconds": effective_refresh_ttl,
        "absolute_expires_at": absolute_expires_at,
    }
    anchor_payload = _build_refresh_anchor_payload(
        session_payload=session_payload,
        family_payload=family_payload,
    )

    _set_json(f"{SESSION_PREFIX}{access_jti}", session_payload, access_ttl)
    _set_json(f"{REFRESH_FAMILY_PREFIX}{family_id}", family_payload, effective_refresh_ttl)
    _set_json(f"{REFRESH_TOKEN_PREFIX}{refresh_jti}", refresh_payload, effective_refresh_ttl)
    _set_json(_refresh_anchor_key(family_id), anchor_payload, effective_refresh_ttl)
    redis_client.sadd(f"{USER_SESSIONS_PREFIX}{user_data.get('id')}", access_jti)
    redis_client.expire(f"{USER_SESSIONS_PREFIX}{user_data.get('id')}", effective_refresh_ttl)
    redis_client.sadd(f"{USER_REFRESH_FAMILIES_PREFIX}{user_data.get('id')}", family_id)
    redis_client.expire(f"{USER_REFRESH_FAMILIES_PREFIX}{user_data.get('id')}", effective_refresh_ttl)
    redis_client.expire(f"{REFRESH_USED_PREFIX}{family_id}", effective_refresh_ttl)

    return TokenPair(
        access_token=access_token,
        refresh_token=refresh_token,
        session_token=access_token,
        token_type=TOKEN_TYPE_BEARER,
        expires_in=access_ttl,
        refresh_expires_in=effective_refresh_ttl,
        expires_at=access_expires_at,
        refresh_expires_at=refresh_expires_at,
        access_claims=access_claims,
        refresh_claims=refresh_claims,
        cookie_metadata=_build_cookie_metadata(effective_refresh_ttl),
    )


def issue_project_token_pair(
    *,
    user: Any,
    project: Any,
    permissions: Optional[List[str]] = None,
    groups: Optional[List[str]] = None,
    group_ids: Optional[List[str]] = None,
    remember_me: bool = False,
) -> TokenPair:
    project_data = _as_mapping(project)
    return _issue_token_pair(
        user=user,
        project=project,
        scope=AUTH_SCOPE_PROJECT,
        collection=project_data.get("project_hash"),
        permissions=permissions,
        groups=groups,
        group_ids=group_ids,
        remember_me=remember_me,
    )


def issue_platform_token_pair(
    *,
    user: Any,
    permissions: Optional[List[str]] = None,
    groups: Optional[List[str]] = None,
    remember_me: bool = False,
) -> TokenPair:
    return _issue_token_pair(
        user=user,
        project=None,
        scope=AUTH_SCOPE_PLATFORM,
        collection=PLATFORM_COLLECTION_SENTINEL,
        permissions=permissions or [],
        groups=groups or [],
        remember_me=remember_me,
    )


def _auth_unauthorized(detail: str) -> HTTPException:
    return HTTPException(status_code=401, detail=detail)


def _require_claim_session_match(claims: Dict[str, Any], session: Dict[str, Any]) -> None:
    comparisons = {
        "jti": session.get("access_jti"),
        "session_id": session.get("session_id"),
        "family_id": session.get("family_id"),
        "user_hash": session.get("user_hash"),
        "scope": session.get("scope"),
    }
    for claim_name, session_value in comparisons.items():
        if str(claims.get(claim_name)) != str(session_value):
            raise _auth_unauthorized(f"Access token/session mismatch: {claim_name}")

    expected_collection = session.get("collection")
    if expected_collection is None:
        expected_collection = (
            PLATFORM_COLLECTION_SENTINEL
            if session.get("scope") == AUTH_SCOPE_PLATFORM
            else session.get("project_hash")
        )
    if str(claims.get("collection")) != str(expected_collection):
        raise _auth_unauthorized("Access token/session mismatch: collection")


def _require_active_family(claims: Dict[str, Any], session: Dict[str, Any]) -> Dict[str, Any]:
    family_id = str(claims.get("family_id"))
    access_jti = str(claims.get("jti"))
    family = _get_json(f"{REFRESH_FAMILY_PREFIX}{family_id}")

    if not family:
        raise _auth_unauthorized("Refresh family missing")
    if family.get("status") != "active" or is_refresh_family_revoked(family_id):
        raise _auth_unauthorized("Refresh family revoked")
    if family.get("current_access_jti") and str(family.get("current_access_jti")) != access_jti:
        raise _auth_unauthorized("Access session revoked")
    if family.get("user_hash") and str(family.get("user_hash")) != str(session.get("user_hash")):
        raise _auth_unauthorized("Refresh family/session mismatch: user")
    if family.get("scope") and str(family.get("scope")) != str(session.get("scope")):
        raise _auth_unauthorized("Refresh family/session mismatch: scope")
    if session.get("scope") == AUTH_SCOPE_PROJECT and str(family.get("project_hash")) != str(session.get("project_hash")):
        raise _auth_unauthorized("Refresh family/session mismatch: project")

    return family


def _login_from_context(access_token: str, session: Dict[str, Any], context: AuthContext) -> Any:
    from src.Util.Models import EnhancedUserLogin, ProjectSummary

    project = context.project
    project_hash = session.get("project_hash") if context.scope == AUTH_SCOPE_PROJECT else None
    project_name = session.get("project_name") if context.scope == AUTH_SCOPE_PROJECT else None
    project_id = session.get("project_id") if context.scope == AUTH_SCOPE_PROJECT else None
    if project is not None:
        project_hash = _field(project, "project_hash", project_hash)
        project_name = _field(project, "project_name", project_name)
        project_id = _field(project, "id", project_id)

    available_projects = []
    for available_project in context.available_projects or []:
        project_hash_value = _field(available_project, "project_hash")
        project_id_value = _field(available_project, "id", _field(available_project, "project_id", project_hash_value))
        project_name_value = _field(available_project, "project_name", "")
        if not project_hash_value or not project_id_value:
            continue
        available_projects.append(ProjectSummary(
            id=str(project_id_value),
            project_hash=str(project_hash_value),
            project_name=str(project_name_value or ""),
            project_description=_field(available_project, "project_description", None),
            project_group_name=str(_field(available_project, "project_group_name", "")),
            permissions=list(_field(available_project, "permissions", []) or []),
        ))

    user_type_value = str(session.get("user_type") or _field(context.user, "user_type", "consumer"))

    session_plan = None
    if context.scope == AUTH_SCOPE_PROJECT and user_type_value == "consumer" and project_id:
        from src.Util.session_plan import resolve_session_plan
        session_plan = resolve_session_plan(str(session.get("user_id")), str(project_id))

    return EnhancedUserLogin(
        user_hash=str(session.get("user_hash")),
        scope=context.scope,
        project_hash=project_hash,
        project_name=project_name,
        user_project_hash=session.get("user_project_hash", ""),
        session_token=access_token,
        session_length=0,
        user_id=str(session.get("user_id")),
        username=session.get("username") or _field(context.user, "username"),
        project_id=project_id,
        user_project_id=session.get("user_project_id"),
        groups=context.groups,
        permissions=context.permissions,
        available_projects=available_projects,
        user_type=user_type_value,
        assigned_project_id=session.get("assigned_project_id") or _field(context.user, "assigned_project_id", None),
        plan=session_plan,
    )


def validate_access_session(
    access_token: str,
    *,
    get_user_by_hash_fn: Optional[Callable[..., Any]] = None,
    get_project_by_hash_fn: Optional[Callable[[str], Any]] = None,
    check_admin_project_access_fn: Optional[Callable[[str, str], bool]] = None,
    get_user_groups_in_project_by_hash_fn: Optional[Callable[[str, str], Iterable[Any]]] = None,
    get_user_permissions_fn: Optional[Callable[[str], Iterable[str]]] = None,
    get_user_accessible_projects_fn: Optional[Callable[[str], Iterable[Any]]] = None,
) -> Any:
    """Canonical access-token validation path.

    JWT signature/type/required claims are validated before Redis state. The
    derived `session_full:{access_jti}` cache is consulted only after access
    session, refresh family, claim/session, and active context checks pass.
    """
    claims = JWTTokenHandler.decode_access_token(access_token)
    access_jti = str(claims.get("jti"))
    session = _get_json(f"{SESSION_PREFIX}{access_jti}")
    if not session:
        raise _auth_unauthorized("Access session missing or revoked")

    _require_claim_session_match(claims, session)
    _require_active_family(claims, session)

    context = reconstruct_auth_context(
        session,
        get_user_by_hash_fn=get_user_by_hash_fn,
        get_project_by_hash_fn=get_project_by_hash_fn,
        check_admin_project_access_fn=check_admin_project_access_fn,
        get_user_groups_in_project_by_hash_fn=get_user_groups_in_project_by_hash_fn,
        get_user_permissions_fn=get_user_permissions_fn,
        get_user_accessible_projects_fn=get_user_accessible_projects_fn,
    )
    if context is None:
        raise _auth_unauthorized("User or auth context inactive")

    from src.Util.cache_manager import cache_manager

    cached = cache_manager.get_session_full(access_jti)
    if cached is not None:
        return cached

    login_data = _login_from_context(access_token, session, context)
    cache_manager.set_session_full(access_jti, login_data)
    return login_data


def _require_refresh_claim_session_match(claims: Dict[str, Any], family: Dict[str, Any], session: Dict[str, Any]) -> None:
    comparisons = {
        "session_id": session.get("session_id"),
        "family_id": family.get("family_id"),
        "user_hash": session.get("user_hash"),
        "scope": session.get("scope"),
    }
    for claim_name, expected in comparisons.items():
        if str(claims.get(claim_name)) != str(expected):
            raise _auth_unauthorized(f"Refresh token/session mismatch: {claim_name}")

    if session.get("refresh_jti") and str(claims.get("jti")) != str(session.get("refresh_jti")):
        raise _auth_unauthorized("Refresh token/session mismatch: refresh_jti")

    if family.get("current_refresh_jti") and str(claims.get("jti")) != str(family.get("current_refresh_jti")):
        raise _auth_unauthorized("Refresh token/family mismatch: current_refresh_jti")

    expected_collection = (
        PLATFORM_COLLECTION_SENTINEL
        if session.get("scope") == AUTH_SCOPE_PLATFORM
        else (session.get("collection") or session.get("project_hash"))
    )
    if str(claims.get("collection")) != str(expected_collection):
        raise _auth_unauthorized("Refresh token/session mismatch: collection")


def _build_rotated_pair(
    *,
    refresh_claims: Dict[str, Any],
    old_session: Dict[str, Any],
    family: Dict[str, Any],
    context: AuthContext,
) -> tuple[TokenPair, Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    now = _utc_now()
    access_ttl = int(JWT_ACCESS_TOKEN_EXPIRE_MINUTES * 60)
    access_expires_at = now + timedelta(seconds=access_ttl)
    remember_me = bool(family.get("remember_me") or old_session.get("remember_me", False))
    if remember_me:
        refresh_expires_at = _parse_datetime(family.get("absolute_expires_at") or family.get("expires_at"))
        if refresh_expires_at is None:
            raise _auth_unauthorized("Refresh family expiry unavailable")
        refresh_ttl = _seconds_until(refresh_expires_at, now)
        if refresh_ttl <= 0:
            raise _auth_unauthorized("Refresh family expired")
        absolute_expires_at = refresh_expires_at.isoformat()
    else:
        refresh_ttl = int(family.get("refresh_ttl_seconds") or REFRESH_FAMILY_TTL_SECONDS)
        refresh_expires_at = compute_refresh_expires_at(now, refresh_ttl)
        absolute_expires_at = None

    family_id = str(refresh_claims["family_id"])
    session_id = str(refresh_claims["session_id"])
    scope = str(refresh_claims.get("scope") or old_session.get("scope") or AUTH_SCOPE_PROJECT)
    collection = (
        PLATFORM_COLLECTION_SENTINEL
        if scope == AUTH_SCOPE_PLATFORM
        else (old_session.get("project_hash") or old_session.get("collection"))
    )
    access_jti = str(uuid4())
    refresh_jti = str(uuid4())

    access_token = JWTTokenHandler.create_access_token(
        session_id=session_id,
        user_hash=str(old_session.get("user_hash")),
        collection=collection,
        scope=scope,
        jti=access_jti,
        family_id=family_id,
    )
    refresh_token = JWTTokenHandler.create_refresh_token(
        session_id=session_id,
        user_hash=str(old_session.get("user_hash")),
        collection=collection,
        scope=scope,
        jti=refresh_jti,
        family_id=family_id,
        expires_delta=timedelta(seconds=refresh_ttl),
    )
    access_claims = JWTTokenHandler.decode_access_token(access_token)
    new_refresh_claims = JWTTokenHandler.decode_refresh_token(refresh_token)

    project = context.project
    session_payload = dict(old_session)
    session_payload.update({
        "access_jti": access_jti,
        "session_id": session_id,
        "family_id": family_id,
        "refresh_jti": refresh_jti,
        "scope": scope,
        "collection": collection,
        "permissions": list(context.permissions),
        "groups": list(context.groups),
        "user_group_names": list(context.groups),
        "issued_at": now.isoformat(),
        "expires_at": access_expires_at.isoformat(),
        "remember_me": remember_me,
        "refresh_ttl_seconds": refresh_ttl,
        "absolute_expires_at": absolute_expires_at,
    })
    if scope == AUTH_SCOPE_PLATFORM:
        session_payload.update({
            "project_id": None,
            "project_hash": None,
            "project_name": None,
        })
    elif project is not None:
        session_payload.update({
            "project_id": _field(project, "id", session_payload.get("project_id")),
            "project_hash": _field(project, "project_hash", session_payload.get("project_hash")),
            "project_name": _field(project, "project_name", session_payload.get("project_name")),
        })

    family_payload_updates = {
        "current_refresh_jti": refresh_jti,
        "current_access_jti": access_jti,
        "updated_at": now.isoformat(),
        "expires_at": refresh_expires_at.isoformat(),
        "remember_me": remember_me,
        "refresh_ttl_seconds": refresh_ttl,
        "absolute_expires_at": absolute_expires_at,
        "scope": scope,
        "project_id": session_payload.get("project_id") if scope == AUTH_SCOPE_PROJECT else None,
        "project_hash": session_payload.get("project_hash") if scope == AUTH_SCOPE_PROJECT else None,
    }
    refresh_payload = {
        "refresh_jti": refresh_jti,
        "family_id": family_id,
        "user_id": session_payload.get("user_id"),
        "token_hash": hash_refresh_token(refresh_token),
        "status": "current",
        "parent_jti": str(refresh_claims["jti"]),
        "child_jti": None,
        "issued_at": now.isoformat(),
        "used_at": None,
        "expires_at": refresh_expires_at.isoformat(),
        "remember_me": remember_me,
        "refresh_ttl_seconds": refresh_ttl,
        "absolute_expires_at": absolute_expires_at,
    }

    return (
        TokenPair(
            access_token=access_token,
            refresh_token=refresh_token,
            session_token=access_token,
            token_type=TOKEN_TYPE_BEARER,
            expires_in=access_ttl,
            refresh_expires_in=refresh_ttl,
            expires_at=access_expires_at,
            refresh_expires_at=refresh_expires_at,
            access_claims=access_claims,
            refresh_claims=new_refresh_claims,
            cookie_metadata=_build_cookie_metadata(refresh_ttl),
        ),
        session_payload,
        family_payload_updates,
        refresh_payload,
    )


def rotate_refresh_family(
    refresh_token: str,
    *,
    target_project: Optional[Any] = None,
    get_user_by_hash_fn: Optional[Callable[..., Any]] = None,
    get_project_by_hash_fn: Optional[Callable[[str], Any]] = None,
    check_admin_project_access_fn: Optional[Callable[[str, str], bool]] = None,
    get_user_groups_in_project_by_hash_fn: Optional[Callable[[str, str], Iterable[Any]]] = None,
    get_user_permissions_fn: Optional[Callable[[str], Iterable[str]]] = None,
    get_user_accessible_projects_fn: Optional[Callable[[str], Iterable[Any]]] = None,
) -> RefreshRotation:
    """Rotate the current refresh token and issue a new token pair.

    The presented refresh token is single-use. Non-current/used/revoked refresh
    records revoke the whole family before failing closed.
    """
    claims = JWTTokenHandler.decode_refresh_token(refresh_token)
    family_id = str(claims["family_id"])
    refresh_jti = str(claims["jti"])
    family_key = f"{REFRESH_FAMILY_PREFIX}{family_id}"
    token_key = f"{REFRESH_TOKEN_PREFIX}{refresh_jti}"
    used_key = f"{REFRESH_USED_PREFIX}{family_id}"
    anchor_key = _refresh_anchor_key(family_id)
    revoked_key = f"{REVOKED_FAMILY_PREFIX}{family_id}"

    family = _get_json(family_key)
    token_record = _get_json(token_key)
    if not family or not token_record:
        raise _auth_unauthorized("Invalid refresh token")

    if family.get("status") != "active" or is_refresh_family_revoked(family_id):
        raise _auth_unauthorized("Refresh family revoked")

    if token_record.get("token_hash") != hash_refresh_token(refresh_token):
        raise _auth_unauthorized("Invalid refresh token")

    if family.get("current_refresh_jti") != refresh_jti or token_record.get("status") != "current":
        classify_refresh_token_state(family_id, refresh_jti)
        raise _auth_unauthorized("Refresh token reused or revoked")

    old_access_jti = str(family.get("current_access_jti") or "")
    old_session = _get_json(f"{SESSION_PREFIX}{old_access_jti}") if old_access_jti else None
    anchor = _get_json(anchor_key)

    if old_session:
        context_session = dict(old_session)
    elif anchor is not None:
        if not _anchor_matches_claims_and_family(anchor, claims, family):
            raise _auth_unauthorized("Refresh token/session mismatch: anchor")
        context_session = _anchor_to_session_seed(anchor, claims, family)
    else:
        context_session = _legacy_family_claims_seed(family, claims)

    _require_refresh_claim_session_match(claims, family, context_session)
    if target_project is not None:
        context_session.update({
            "scope": AUTH_SCOPE_PROJECT,
            "project_id": _field(target_project, "id"),
            "project_hash": _field(target_project, "project_hash"),
            "project_name": _field(target_project, "project_name", None),
            "collection": _field(target_project, "project_hash"),
        })

    context = reconstruct_auth_context(
        context_session,
        get_user_by_hash_fn=get_user_by_hash_fn,
        get_project_by_hash_fn=get_project_by_hash_fn,
        check_admin_project_access_fn=check_admin_project_access_fn,
        get_user_groups_in_project_by_hash_fn=get_user_groups_in_project_by_hash_fn,
        get_user_permissions_fn=get_user_permissions_fn,
        get_user_accessible_projects_fn=get_user_accessible_projects_fn,
    )
    if context is None:
        raise _auth_unauthorized("User or auth context inactive")

    token_pair, new_session, family_updates, new_refresh_record = _build_rotated_pair(
        refresh_claims=claims,
        old_session=context_session,
        family=family,
        context=context,
    )
    login_data = _login_from_context(token_pair.access_token, new_session, context)
    old_token_record = dict(token_record)
    now = _utc_now().isoformat()
    old_token_record.update({
        "status": "used",
        "used_at": now,
        "child_jti": token_pair.refresh_claims["jti"],
    })
    new_family = dict(family)
    new_family.update(family_updates)
    new_anchor = _build_refresh_anchor_payload(
        session_payload=new_session,
        family_payload=new_family,
    )

    new_access_jti = token_pair.access_claims["jti"]
    new_refresh_jti = token_pair.refresh_claims["jti"]
    refresh_cache_ttl = token_pair.refresh_expires_in
    user_id = new_session.get("user_id")

    try:
        with redis_client.pipeline(transaction=True) as pipe:
            pipe.watch(family_key, token_key, anchor_key, revoked_key)
            watched_family = _loads_json(pipe.get(family_key))
            watched_token = _loads_json(pipe.get(token_key))
            watched_revoked = pipe.get(revoked_key)
            if (
                not watched_family
                or not watched_token
                or watched_revoked is not None
                or watched_family.get("status") != "active"
                or watched_family.get("current_refresh_jti") != refresh_jti
                or watched_token.get("status") != "current"
                or watched_token.get("token_hash") != hash_refresh_token(refresh_token)
            ):
                pipe.unwatch()
                classify_refresh_token_state(family_id, refresh_jti)
                raise _auth_unauthorized("Refresh token reused or revoked")

            pipe.multi()
            pipe.set(token_key, json.dumps(old_token_record, default=_json_default), ex=refresh_cache_ttl)
            pipe.sadd(used_key, refresh_jti)
            pipe.expire(used_key, refresh_cache_ttl)
            pipe.set(f"{REFRESH_TOKEN_PREFIX}{new_refresh_jti}", json.dumps(new_refresh_record, default=_json_default), ex=refresh_cache_ttl)
            pipe.set(family_key, json.dumps(new_family, default=_json_default), ex=refresh_cache_ttl)
            pipe.set(f"{SESSION_PREFIX}{new_access_jti}", json.dumps(new_session, default=_json_default), ex=token_pair.expires_in)
            pipe.set(anchor_key, json.dumps(new_anchor, default=_json_default), ex=refresh_cache_ttl)
            pipe.delete(f"{SESSION_PREFIX}{old_access_jti}", f"{SESSION_FULL_PREFIX}{old_access_jti}")
            if user_id:
                pipe.sadd(f"{USER_SESSIONS_PREFIX}{user_id}", new_access_jti)
                pipe.expire(f"{USER_SESSIONS_PREFIX}{user_id}", refresh_cache_ttl)
                pipe.sadd(f"{USER_REFRESH_FAMILIES_PREFIX}{user_id}", family_id)
                pipe.expire(f"{USER_REFRESH_FAMILIES_PREFIX}{user_id}", refresh_cache_ttl)
            pipe.execute()
    except WatchError:
        classify_refresh_token_state(family_id, refresh_jti)
        raise _auth_unauthorized("Refresh token reused or revoked")

    return RefreshRotation(
        token_pair=token_pair,
        login_data=login_data,
        session_payload=new_session,
        family_payload=new_family,
        old_access_jti=old_access_jti,
        old_refresh_jti=refresh_jti,
    )


def revoke_access_session(access_jti: str) -> None:
    # Access-session revocation is intentionally access-only. True logout or
    # user/session termination must revoke the refresh family so its anchor and
    # tombstone are updated consistently.
    redis_client.delete(f"{SESSION_PREFIX}{access_jti}", f"{SESSION_FULL_PREFIX}{access_jti}")


def _default_has_project_access(user_id: str, project_id: str) -> bool:
    from src.Util.db.db_users import get_user_project_access

    return bool(get_user_project_access(user_id, project_id))


def revoke_project_sessions_losing_access(
    *,
    user_ids: Iterable[str],
    project_ids: Iterable[str],
    reason: str,
    has_project_access_fn: Callable[[str, str], bool] = _default_has_project_access,
) -> RevocationSummary:
    """Revoke active project sessions that no longer have a valid direct chain.

    Candidate sessions are limited by user index and current project. Each
    affected session is checked after the DB mutation so alternate direct chains
    preserve valid sessions. Revocation always deletes both `session:*` and
    `session_full:*`; refresh families are also revoked when a family id exists.
    """
    summary = RevocationSummary()
    candidate_user_ids = {str(user_id) for user_id in user_ids or [] if user_id is not None}
    candidate_project_ids = {str(project_id) for project_id in project_ids or [] if project_id is not None}
    if not candidate_user_ids or not candidate_project_ids:
        return summary

    for user_id in candidate_user_ids:
        session_index_key = f"{USER_SESSIONS_PREFIX}{user_id}"
        for access_jti in _decode_set_members(redis_client.smembers(session_index_key)):
            summary.sessions_seen += 1
            session_key = f"{SESSION_PREFIX}{access_jti}"
            session_payload = _get_json(session_key)
            if not session_payload:
                summary.sessions_missing += 1
                redis_client.srem(session_index_key, access_jti)
                continue

            current_project_id = session_payload.get("project_id")
            if current_project_id is None or str(current_project_id) not in candidate_project_ids:
                summary.sessions_skipped += 1
                continue

            if has_project_access_fn(str(session_payload.get("user_id") or user_id), str(current_project_id)):
                summary.sessions_preserved += 1
                continue

            family_id = session_payload.get("family_id")
            if family_id:
                revoke_refresh_family(str(family_id), reason=reason)
                summary.families_revoked += 1

            revoke_access_session(str(access_jti))
            redis_client.srem(session_index_key, access_jti)
            summary.sessions_revoked += 1

    return summary


def is_refresh_family_revoked(family_id: str) -> bool:
    family = _get_json(f"{REFRESH_FAMILY_PREFIX}{family_id}")
    if family and family.get("status") in {"revoked", "reused", "expired"}:
        return True
    return redis_client.get(f"{REVOKED_FAMILY_PREFIX}{family_id}") is not None


def revoke_refresh_family(family_id: str, reason: str = "revoked") -> None:
    now = _utc_now().isoformat()
    family_key = f"{REFRESH_FAMILY_PREFIX}{family_id}"
    family = _get_json(family_key) or {"family_id": family_id}
    cache_ttl = _cache_ttl_for_family(family)
    family["status"] = "reused" if reason == "refresh_reuse" else "revoked"
    family["revoked_at"] = now
    family["revocation_reason"] = reason
    _set_json(family_key, family, cache_ttl)
    _set_json(f"{REVOKED_FAMILY_PREFIX}{family_id}", {"family_id": family_id, "reason": reason, "revoked_at": now}, cache_ttl)
    redis_client.delete(_refresh_anchor_key(family_id))

    access_jtis = set()
    if family.get("current_access_jti"):
        access_jtis.add(family["current_access_jti"])
    user_id = family.get("user_id")
    if user_id:
        access_jtis.update(_decode_set_members(redis_client.smembers(f"{USER_SESSIONS_PREFIX}{user_id}")))

    for access_jti in access_jtis:
        session = _get_json(f"{SESSION_PREFIX}{access_jti}")
        if session is None or session.get("family_id") == family_id:
            revoke_access_session(access_jti)


def classify_refresh_token_state(family_id: str, refresh_jti: str) -> str:
    family = _get_json(f"{REFRESH_FAMILY_PREFIX}{family_id}")
    token = _get_json(f"{REFRESH_TOKEN_PREFIX}{refresh_jti}")
    used_key = f"{REFRESH_USED_PREFIX}{family_id}"

    if not family or not token:
        return "invalid"
    if family.get("status") != "active" or is_refresh_family_revoked(family_id):
        return "revoked"
    if family.get("current_refresh_jti") == refresh_jti and token.get("status") == "current":
        return "current"
    if token.get("status") in {"used", "revoked"} or redis_client.sismember(used_key, refresh_jti):
        revoke_refresh_family(family_id, reason="refresh_reuse")
        return "reused"
    return "invalid"


def revoke_user_auth_state(user_id: str, reason: str = "user_revoked") -> None:
    session_key = f"{USER_SESSIONS_PREFIX}{user_id}"
    family_index_key = f"{USER_REFRESH_FAMILIES_PREFIX}{user_id}"
    for access_jti in _decode_set_members(redis_client.smembers(session_key)):
        revoke_access_session(access_jti)
    for family_id in _decode_set_members(redis_client.smembers(family_index_key)):
        revoke_refresh_family(family_id, reason=reason)
    redis_client.delete(session_key, family_index_key)


def revoke_user_auth_state_except_current(
    user_id: str,
    *,
    current_access_token: str | None = None,
    current_access_jti: str | None = None,
    current_family_id: str | None = None,
    reason: str = "user_identity_changed",
) -> RevocationSummary:
    """Revoke a user's auth state while preserving the current session family.

    Email activation/removal/primary-change requirements need two behaviors:
    public token consumption revokes everything, while authenticated email
    management revokes all *other* sessions and keeps the caller's current
    session usable.  This helper is deliberately narrow and lives beside the
    full `revoke_user_auth_state(...)` primitive instead of changing it.
    """

    summary = RevocationSummary()
    if current_access_token and (not current_access_jti or not current_family_id):
        try:
            claims = JWTTokenHandler.decode_access_token(current_access_token)
            current_access_jti = current_access_jti or str(claims.get("jti") or "") or None
            current_family_id = current_family_id or str(claims.get("family_id") or "") or None
        except Exception:
            current_access_jti = current_access_jti or None
            current_family_id = current_family_id or None

    # If no current session can be proven, fall back to the existing full
    # revocation behavior required by public activation/reset flows.
    if not current_access_jti and not current_family_id:
        revoke_user_auth_state(user_id, reason=reason)
        return summary

    session_index_key = f"{USER_SESSIONS_PREFIX}{user_id}"
    family_index_key = f"{USER_REFRESH_FAMILIES_PREFIX}{user_id}"
    revoked_families: set[str] = set()

    for access_jti in _decode_set_members(redis_client.smembers(session_index_key)):
        summary.sessions_seen += 1
        if current_access_jti and str(access_jti) == str(current_access_jti):
            summary.sessions_preserved += 1
            continue

        session_payload = _get_json(f"{SESSION_PREFIX}{access_jti}")
        if not session_payload:
            summary.sessions_missing += 1
            redis_client.srem(session_index_key, access_jti)
            continue

        family_id = session_payload.get("family_id")
        if family_id and current_family_id and str(family_id) == str(current_family_id):
            # Same refresh family as the current session. Keep the family so the
            # caller can continue/refresh, but drop any stale sibling access JTI.
            revoke_access_session(str(access_jti))
            redis_client.srem(session_index_key, access_jti)
            summary.sessions_revoked += 1
            continue

        if family_id:
            family_key = str(family_id)
            if family_key not in revoked_families:
                revoke_refresh_family(family_key, reason=reason)
                revoked_families.add(family_key)
                redis_client.srem(family_index_key, family_key)
                summary.families_revoked += 1
            # Be defensive: family revocation should delete its current access
            # session, but this helper is already iterating a concrete sibling
            # access JTI. Delete it directly as well so incomplete/stale family
            # metadata cannot leave an alternate session alive after a password
            # change or email-identity mutation.
            revoke_access_session(str(access_jti))
        else:
            revoke_access_session(str(access_jti))

        redis_client.srem(session_index_key, access_jti)
        summary.sessions_revoked += 1

    for family_id in _decode_set_members(redis_client.smembers(family_index_key)):
        family_key = str(family_id)
        if current_family_id and family_key == str(current_family_id):
            summary.sessions_preserved += 1
            continue
        if family_key in revoked_families:
            continue
        revoke_refresh_family(family_key, reason=reason)
        revoked_families.add(family_key)
        redis_client.srem(family_index_key, family_key)
        summary.families_revoked += 1

    return summary
