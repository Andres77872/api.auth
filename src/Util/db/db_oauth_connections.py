"""Database wrappers for provider-agnostic OAuth stored procedures.

Security posture (mirrors ``db_billing``):
- Only procedures from ``schemas/stored_procedures/19_oauth_connections.sql`` are called.
- Wrapper argument order mirrors SQL exactly; callers use keyword arguments.
- ``get_connection_operational_credentials`` and ``get_binding_legacy_redeem`` return
  ciphertext and key metadata for authorised server-side code only; nothing they
  return may reach a DTO, a log line or an error context.
- Error contexts name ids/hashes and field names, never secrets, client ids or URLs.
"""

from __future__ import annotations

import json
from typing import Any, Mapping, Sequence

from src.Util.db_config import get_connection
from src.Util.db_error_wrapper import handle_db_operation


JsonParam = Mapping[str, Any] | Sequence[Any] | str | None

_JSON_RESULT_FIELDS = frozenset(
    {"capability_metadata", "restrictions", "provider_params", "rate_limit_overrides", "redirect_uris", "return_origins"}
)
_BOOL_RESULT_FIELDS = frozenset(
    {
        "login_enabled", "link_enabled", "tenant_endpoints_allowed", "has_client_secret", "has_signing_key",
        "catalog_login_enabled", "catalog_link_enabled", "enabled", "has_legacy_redeem", "project_is_active",
        "project_archived", "default_user_group_is_active", "default_user_group_reaches_project",
    }
)


def _json_param(value: JsonParam) -> str | None:
    if value is None or isinstance(value, str):
        return value
    return json.dumps(value, sort_keys=True, separators=(",", ":"), default=str)


def _decode_json_field(value: Any) -> Any:
    if isinstance(value, (dict, list)) or value is None:
        return value
    if isinstance(value, (bytes, bytearray)):
        value = bytes(value).decode("utf-8", errors="replace")
    if isinstance(value, str):
        try:
            return json.loads(value)
        except json.JSONDecodeError:
            return None
    return None


def _row_to_dict(row: tuple[Any, ...] | None, description) -> dict[str, Any] | None:
    if row is None or not description:
        return None
    result = dict(zip([desc[0] for desc in description], row))
    for name in _JSON_RESULT_FIELDS & result.keys():
        result[name] = _decode_json_field(result[name])
    for name in _BOOL_RESULT_FIELDS & result.keys():
        if result[name] is not None:
            result[name] = bool(result[name])
    return result


def _advance_to_result_set(cur) -> bool:
    if cur.description:
        return True
    while cur.nextset():
        if cur.description:
            return True
    return False


def _drain_remaining_result_sets(cur) -> None:
    while cur.nextset():
        pass


def _callproc_one(proc_name: str, args: list[Any], *, context: str, commit: bool = False) -> dict[str, Any] | None:
    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc(proc_name, args)
            result = None
            if _advance_to_result_set(cur):
                description = cur.description
                result = _row_to_dict(cur.fetchone(), description)
            _drain_remaining_result_sets(cur)
            if commit:
                con.commit()
            return result

    return handle_db_operation(_operation, error_context=context)


def _callproc_all(proc_name: str, args: list[Any], *, context: str) -> list[dict[str, Any]]:
    def _operation():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc(proc_name, args)
            rows: list[dict[str, Any]] = []
            if _advance_to_result_set(cur):
                description = cur.description
                rows = [item for item in (_row_to_dict(row, description) for row in cur.fetchall() or []) if item]
            _drain_remaining_result_sets(cur)
            return rows

    return handle_db_operation(_operation, error_context=context)


# ─────────────────────────────────────────────────────────────────────── catalog

def list_provider_catalog() -> list[dict[str, Any]]:
    return _callproc_all("sp_oauth_catalog_list", [], context="list_oauth_provider_catalog")


def get_provider_catalog_entry(*, provider_type: str) -> dict[str, Any] | None:
    return _callproc_one("sp_oauth_catalog_get", [provider_type], context=f"get_oauth_provider(provider_type={provider_type})")


def set_provider_catalog_status(
    *,
    provider_type: str,
    status: str | None,
    login_enabled: bool | None,
    link_enabled: bool | None,
    capability_metadata: JsonParam = None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_oauth_catalog_set_status",
        [provider_type, status, login_enabled, link_enabled, _json_param(capability_metadata)],
        context=f"set_oauth_provider_status(provider_type={provider_type})",
        commit=True,
    )


# ─────────────────────────────────────────────────────────────────── connections

def create_connection(
    *,
    id: str,
    connection_hash: str,
    provider_type: str,
    owner_project_id: str | None,
    display_name: str,
    client_id: str,
    issuer: str | None,
    discovery_url: str | None,
    authorize_endpoint: str | None,
    token_endpoint: str | None,
    jwks_uri: str | None,
    userinfo_endpoint: str | None,
    scopes: str,
    restrictions: JsonParam,
    provider_params: JsonParam,
    identity_namespace: str,
    created_by: str | None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_oauth_connection_create",
        [
            id, connection_hash, provider_type, owner_project_id, display_name, client_id, issuer,
            discovery_url, authorize_endpoint, token_endpoint, jwks_uri, userinfo_endpoint, scopes,
            _json_param(restrictions), _json_param(provider_params), identity_namespace, created_by,
        ],
        context=f"create_oauth_connection(provider_type={provider_type})",
        commit=True,
    )


def update_connection(
    *,
    id: str,
    display_name: str,
    client_id: str,
    issuer: str | None,
    discovery_url: str | None,
    authorize_endpoint: str | None,
    token_endpoint: str | None,
    jwks_uri: str | None,
    userinfo_endpoint: str | None,
    scopes: str,
    restrictions: JsonParam,
    provider_params: JsonParam,
    identity_namespace: str,
    updated_by: str | None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_oauth_connection_update",
        [
            id, display_name, client_id, issuer, discovery_url, authorize_endpoint, token_endpoint,
            jwks_uri, userinfo_endpoint, scopes, _json_param(restrictions), _json_param(provider_params),
            identity_namespace, updated_by,
        ],
        context=f"update_oauth_connection(id={id})",
        commit=True,
    )


def set_connection_status(*, id: str, status: str, updated_by: str | None) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_oauth_connection_set_status", [id, status, updated_by], context=f"set_oauth_connection_status(id={id})", commit=True
    )


def set_connection_credentials(
    *,
    id: str,
    client_secret_ciphertext: bytes | None,
    client_secret_hmac: bytes | None,
    client_secret_fingerprint: str | None,
    signing_key_ciphertext: bytes | None,
    signing_key_hmac: bytes | None,
    signing_key_fingerprint: str | None,
    credential_key_id: str,
    set_by: str | None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_oauth_connection_set_credentials",
        [
            id, client_secret_ciphertext, client_secret_hmac, client_secret_fingerprint,
            signing_key_ciphertext, signing_key_hmac, signing_key_fingerprint, credential_key_id, set_by,
        ],
        context=f"set_oauth_connection_credentials(id={id})",
        commit=True,
    )


def get_connection_by_hash(*, connection_hash: str) -> dict[str, Any] | None:
    return _callproc_one("sp_oauth_connection_get_by_hash", [connection_hash], context="get_oauth_connection_by_hash")


def get_connection_by_id(*, id: str) -> dict[str, Any] | None:
    return _callproc_one("sp_oauth_connection_get_by_id", [id], context=f"get_oauth_connection_by_id(id={id})")


def get_connection_operational_credentials(*, id: str) -> dict[str, Any] | None:
    """SERVER-ONLY: ciphertext + key metadata for the token exchange."""

    return _callproc_one(
        "sp_oauth_connection_get_operational_credentials", [id], context=f"get_oauth_connection_operational_credentials(id={id})"
    )


def list_connections(
    *, provider_type: str | None = None, status: str | None = None, search: str | None = None, limit: int = 50, offset: int = 0
) -> tuple[list[dict[str, Any]], int]:
    def _operation() -> tuple[list[dict[str, Any]], int]:
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc("sp_oauth_connection_list", [provider_type, status, search, int(limit), int(offset)])
            rows: list[dict[str, Any]] = []
            total = 0
            if _advance_to_result_set(cur):
                description = cur.description
                rows = [item for item in (_row_to_dict(row, description) for row in cur.fetchall() or []) if item]
            if cur.nextset() and cur.description:
                total_row = cur.fetchone()
                total = int(total_row[0]) if total_row else 0
            _drain_remaining_result_sets(cur)
            return rows, total

    return handle_db_operation(_operation, error_context="list_oauth_connections")


def delete_connection(*, id: str, deleted_by: str | None) -> dict[str, Any] | None:
    return _callproc_one("sp_oauth_connection_delete", [id, deleted_by], context=f"delete_oauth_connection(id={id})", commit=True)


# ────────────────────────────────────────────────────────────────────── bindings

def upsert_binding(
    *,
    id: str,
    project_id: str,
    connection_id: str,
    connection_key: str,
    enabled: bool | None,
    login_enabled: bool | None,
    link_enabled: bool | None,
    provisioning_mode: str | None,
    default_user_group_id: str | None,
    existing_user_policy: str | None,
    init_mode: str | None,
    delivery_mode: str | None,
    state_ttl_seconds: int | None,
    rate_limit_overrides: JsonParam,
    actor: str | None,
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_oauth_binding_upsert",
        [
            id, project_id, connection_id, connection_key, enabled, login_enabled, link_enabled,
            provisioning_mode, default_user_group_id, existing_user_policy, init_mode, delivery_mode,
            state_ttl_seconds, _json_param(rate_limit_overrides), actor,
        ],
        context=f"upsert_oauth_binding(connection_key={connection_key})",
        commit=True,
    )


def get_binding(*, project_hash: str, connection_key: str) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_oauth_binding_get", [project_hash, connection_key], context=f"get_oauth_binding(connection_key={connection_key})"
    )


def get_binding_by_ids(*, connection_id: str, binding_id: str) -> dict[str, Any] | None:
    return _callproc_one("sp_oauth_binding_get_by_ids", [connection_id, binding_id], context="get_oauth_binding_by_ids")


def get_binding_by_id(*, binding_id: str) -> dict[str, Any] | None:
    return _callproc_one("sp_oauth_binding_select", [binding_id], context="get_oauth_binding_by_id")


def _resolved_bindings(proc_name: str, args: list[Any], *, context: str) -> list[dict[str, Any]]:
    resolved: list[dict[str, Any]] = []
    for row in _callproc_all(proc_name, args, context=context):
        binding = get_binding_by_id(binding_id=str(row["binding_id"]))
        if binding:
            resolved.append(binding)
    return resolved


def list_bindings_for_project(*, project_hash: str) -> list[dict[str, Any]]:
    return _resolved_bindings("sp_oauth_binding_list_for_project", [project_hash], context="list_oauth_bindings_for_project")


def list_bindings_for_connection(*, connection_id: str) -> list[dict[str, Any]]:
    return _resolved_bindings(
        "sp_oauth_binding_list_for_connection", [connection_id], context="list_oauth_bindings_for_connection"
    )


def list_legacy_bindings(*, connection_key: str) -> list[dict[str, Any]]:
    return _resolved_bindings("sp_oauth_binding_list_legacy", [connection_key], context="list_oauth_legacy_bindings")


def set_binding_legacy_redeem(
    *, binding_id: str, url_ciphertext: bytes | None, token_ciphertext: bytes | None, key_id: str | None, actor: str | None
) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_oauth_binding_set_legacy_redeem",
        [binding_id, url_ciphertext, token_ciphertext, key_id, actor],
        context="set_oauth_binding_legacy_redeem",
        commit=True,
    )


def get_binding_legacy_redeem(*, binding_id: str) -> dict[str, Any] | None:
    """SERVER-ONLY: encrypted companion-handshake material."""

    return _callproc_one("sp_oauth_binding_get_legacy_redeem", [binding_id], context="get_oauth_binding_legacy_redeem")


def delete_binding(*, binding_id: str) -> dict[str, Any] | None:
    return _callproc_one("sp_oauth_binding_delete", [binding_id], context="delete_oauth_binding", commit=True)


def add_binding_url(*, id: str, binding_id: str, kind: str, url: str, url_hash: bytes, created_by: str | None) -> dict[str, Any] | None:
    return _callproc_one(
        "sp_oauth_binding_url_add", [id, binding_id, kind, url, url_hash, created_by], context=f"add_oauth_binding_url(kind={kind})", commit=True
    )


def remove_binding_url(*, binding_id: str, url_id: str) -> dict[str, Any] | None:
    return _callproc_one("sp_oauth_binding_url_remove", [binding_id, url_id], context="remove_oauth_binding_url", commit=True)


def list_binding_urls(*, binding_id: str) -> list[dict[str, Any]]:
    return _callproc_all("sp_oauth_binding_urls", [binding_id], context="list_oauth_binding_urls")


__all__ = [
    "add_binding_url",
    "create_connection",
    "delete_binding",
    "delete_connection",
    "get_binding",
    "get_binding_by_id",
    "get_binding_by_ids",
    "get_binding_legacy_redeem",
    "get_connection_by_hash",
    "get_connection_by_id",
    "get_connection_operational_credentials",
    "get_provider_catalog_entry",
    "list_binding_urls",
    "list_bindings_for_connection",
    "list_bindings_for_project",
    "list_connections",
    "list_legacy_bindings",
    "list_provider_catalog",
    "remove_binding_url",
    "set_binding_legacy_redeem",
    "set_connection_credentials",
    "set_connection_status",
    "set_provider_catalog_status",
    "update_connection",
    "upsert_binding",
]
