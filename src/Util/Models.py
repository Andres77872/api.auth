"""
Enhanced Multi-Project Authentication - Pydantic Models

Updated models using Pydantic for validation and serialization.
Includes both data models and API response models.
"""

from datetime import datetime
import re
from typing import Any, ClassVar, Dict, FrozenSet, List, Literal, Optional

from pydantic import BaseModel, Field, ConfigDict, field_validator

from src.Util.auth_constants import TOKEN_TYPE_BEARER


# =================== CONFIGURATION ===================

class BaseModelConfig(BaseModel):
    """Base configuration for all models"""
    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True
    )


_EMAIL_FORMAT_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")


def _optional_email_or_none(value: Any) -> Any:
    """Treat omitted/blank optional email values as absent; reject bad supplied values."""
    if isinstance(value, str) and not value.strip():
        return None
    if value is None:
        return None
    if not isinstance(value, str):
        raise ValueError("Email must be a string")
    normalized = value.strip()
    if not _EMAIL_FORMAT_RE.match(normalized):
        raise ValueError("Invalid email format")
    return normalized


def _optional_stripped_string_or_none(value: Any) -> Any:
    """Treat omitted/blank optional string values as absent; reject non-strings."""
    if isinstance(value, str):
        stripped = value.strip()
        return stripped or None
    if value is None:
        return None
    raise ValueError("Value must be a string")


# =================== CORE DATA ENTITIES ===================

class User(BaseModelConfig):
    """Global user entity"""
    id: str
    user_hash: str
    username: str
    email: Optional[str] = None
    password_hash: str
    user_type: str = "consumer"
    assigned_project_id: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    is_active: bool = True
    assigned_at: Optional[datetime] = None  # When user was assigned to a group (from membership record)


class Project(BaseModelConfig):
    """Global project entity"""
    id: str
    project_hash: str
    project_name: str
    project_description: Optional[str] = None
    project_created: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True
    archived: bool = False


class UserGroup(BaseModelConfig):
    """Global user groups that define project access"""
    id: str
    group_hash: str
    group_name: str
    group_description: Optional[str] = None
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True
    joined_at: Optional[datetime] = None  # When user joined this group (from membership record)
    member_count: Optional[int] = None  # Number of members in the group


class ProjectGroup(BaseModelConfig):
    """Project groups that define permissions"""
    id: str
    group_hash: str
    group_name: str
    group_description: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)
    created_at: datetime
    updated_at: Optional[datetime] = None
    is_active: bool = True


class Permission(BaseModelConfig):
    """Model for project-specific permissions in RBAC system"""
    id: str
    permission_hash: str
    project_id: str
    permission_name: str
    permission_display_name: str
    permission_description: Optional[str] = None
    permission_category: str = 'general'
    is_system_permission: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    is_active: bool = True
    granted_through_role: Optional[str] = None


class PermissionGroup(BaseModelConfig):
    """Model for project-specific permission groups (roles) in RBAC system"""
    id: str
    group_hash: str
    project_id: str
    group_name: str
    group_display_name: str
    group_description: Optional[str] = None
    group_priority: int = 0
    is_system_role: bool = False
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    created_by: Optional[str] = None
    is_active: bool = True
    permissions: Optional[List[Permission]] = None


# =================== DATABASE RELATIONSHIP MODELS ===================

class UserProject(BaseModelConfig):
    """Model for user-project access relationships (consumer users)"""
    id: str
    user_id: str
    project_id: str
    user_project_hash: str
    granted_at: Optional[datetime] = None
    granted_by: Optional[str] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    is_active: bool = True


class UserGroupMember(BaseModelConfig):
    """Model for user group membership relationships"""
    id: str
    user_id: str
    user_group_id: str
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[str] = None
    removed_at: Optional[datetime] = None
    removed_by: Optional[str] = None
    is_active: bool = True


class ProjectGroupMember(BaseModelConfig):
    """Model for project group membership relationships"""
    id: str
    project_id: str
    project_group_id: str
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[str] = None
    removed_at: Optional[datetime] = None
    removed_by: Optional[str] = None
    is_active: bool = True


class PermissionGroupPermission(BaseModelConfig):
    """Model for permission group to permission relationships"""
    id: str
    permission_group_id: str
    permission_id: str
    granted_at: Optional[datetime] = None
    granted_by: Optional[str] = None
    revoked_at: Optional[datetime] = None
    revoked_by: Optional[str] = None
    is_active: bool = True


class UserProjectPermissionGroup(BaseModelConfig):
    """Model for user to permission group assignments within projects"""
    id: str
    user_id: str
    project_id: str
    permission_group_id: str
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[str] = None
    removed_at: Optional[datetime] = None
    removed_by: Optional[str] = None
    is_active: bool = True


class PermissionAuditLog(BaseModelConfig):
    """Model for permission and RBAC audit log entries"""
    id: str
    action_type: str
    table_name: Optional[str] = None
    record_id: Optional[str] = None
    old_values: Optional[str] = None  # JSON string
    new_values: Optional[str] = None  # JSON string
    performed_by: Optional[str] = None
    performed_at: Optional[datetime] = None
    ip_address: Optional[str] = None
    user_agent: Optional[str] = None
    project_id: Optional[str] = None


# Legacy alias for backward compatibility
LegacyUserGroup = UserGroup


# =================== COMMON RESPONSE COMPONENTS ===================

class BaseResponse(BaseModelConfig):
    """Base response model"""
    # Default success to True so individual endpoints don't need to explicitly set it
    success: bool = True
    message: Optional[str] = None


class PaginationInfo(BaseModelConfig):
    """Pagination information"""
    limit: int
    offset: int
    total: Optional[int] = None
    has_more: Optional[bool] = None


class UserInfo(BaseModelConfig):
    """User information for responses"""
    user_hash: str
    username: str
    email: Optional[str] = None
    user_type: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProjectInfo(BaseModelConfig):
    """Project information for responses"""
    project_hash: str
    project_name: str
    project_description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class UserGroupInfo(BaseModelConfig):
    """User group information for responses"""
    group_hash: str
    group_name: str
    description: Optional[str] = None
    member_count: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class ProjectGroupInfo(BaseModelConfig):
    """Project group information for responses.
    
    Project groups are containers that group projects together.
    Access flow: USER → USER_GROUP → PROJECT_GROUP → PROJECT
    """
    group_hash: str
    group_name: str
    description: Optional[str] = None
    project_count: Optional[int] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class PermissionInfo(BaseModelConfig):
    """Permission information for responses"""
    id: str
    permission_name: str
    category: str
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class RoleInfo(BaseModelConfig):
    """Role (permission group) information for responses"""
    id: str
    group_name: str
    priority: int
    description: Optional[str] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    is_active: bool = True


# =================== AUTHENTICATION RESPONSES ===================

class TokenPairFields(BaseModelConfig):
    """Shared token-pair response fields for auth credential issuers."""
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    session_token: Optional[str] = None  # Deprecated access-token alias
    token_type: str = TOKEN_TYPE_BEARER
    expires_in: Optional[int] = None
    refresh_expires_in: Optional[int] = None
    expires_at: Optional[datetime] = None
    refresh_expires_at: Optional[datetime] = None


class LoginResponse(BaseResponse, TokenPairFields):
    """Login endpoint response"""
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    accessible_projects: List[ProjectInfo] = Field(default_factory=list)
    user_groups: List[UserGroupInfo] = Field(default_factory=list, description="User groups the user belongs to")
    user_id: Optional[str] = None  # Internal field for logging, not exposed in API docs


class RegisterResponse(BaseResponse, TokenPairFields):
    """Register endpoint response"""
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    user_id: Optional[str] = None


class ValidateSessionResponse(BaseResponse):
    """Session validation response"""
    valid: bool
    auth_method: str = "session"
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    session: Optional[Dict[str, Any]] = None
    user_groups: List[str] = Field(default_factory=list, description="User group names from session")


class ApiKeyInfo(BaseModelConfig):
    """Secret-safe API-key metadata returned by validation adapters."""
    key_id: Optional[str] = None
    public_id: Optional[str] = None


class ValidateApiKeyResponse(BaseResponse):
    """API-key validation adapter response for service-to-service callers."""
    valid: bool
    auth_method: str = "api_key"
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    api_key: Optional[ApiKeyInfo] = None
    user_groups: List[str] = Field(default_factory=list, description="User group names for the API-key owner")
    permissions: List[str] = Field(default_factory=list, description="Safe permission names for the API-key owner")


class LogoutResponse(BaseResponse):
    """Logout endpoint response"""
    pass


class GoogleOAuthStartRequest(BaseModelConfig):
    """Google OAuth start request.

    Browser-provided strict project/group hashes are intentionally absent. The
    server resolves those bindings only through the opaque provider-init token.
    """

    provider_init_token: str = Field(..., min_length=1, max_length=4096)
    redirect_uri: Optional[str] = None
    return_origin: Optional[str] = None
    remember_me: bool = False

    @field_validator("provider_init_token", mode="before")
    @classmethod
    def normalize_provider_init_token(cls, value: Any) -> Any:
        if not isinstance(value, str) or not value.strip():
            raise ValueError("provider_init_token is required")
        return value.strip()


class GoogleOAuthStartResponse(BaseResponse):
    """Non-browser/test Google OAuth start response.

    Browser flows normally redirect. This model carries only a provider URL,
    expiry, and non-reversible state fingerprint for explicit negotiated flows.
    """

    authorization_url: Optional[str] = None
    expires_in: int
    state_fingerprint: str


class ExternalIdentityInfo(BaseModelConfig):
    """Secret-safe external identity metadata returned by link/unlink flows."""

    provider: str
    provider_subject_masked: Optional[str] = None
    provider_email_masked: Optional[str] = None
    provider_email_verified_at_link: bool = False
    linked_at: Optional[datetime] = None
    last_seen_at: Optional[datetime] = None
    status: str


class ExternalIdentityLinkResponse(BaseResponse):
    """Response for linking an external identity to an existing local account."""

    external_identity: Optional[ExternalIdentityInfo] = None


class ExternalIdentityUnlinkResponse(BaseResponse):
    """Response for unlinking an external identity without provider secrets."""

    remaining_auth_methods: List[str] = Field(default_factory=list)
    sessions_revoked: int = 0


PatreonEntitlementStatus = Literal["active", "free", "pending", "former", "revoked", "stale"]
PatreonSafeLinkStatus = Literal["none", "pending", "linked", "unlinked", "revoked", "blocked"]
PatreonResyncAcceptanceStatus = Literal["accepted", "queued", "disabled", "rate_limited", "degraded"]

PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES: FrozenSet[str] = frozenset(
    {
        # Local-auth/session material: Patreon is entitlement/link only, never login.
        "access_token",
        "refresh_token",
        "session_token",
        "api_key",
        "token_type",
        "expires_in",
        "refresh_expires_in",
        "expires_at",
        "refresh_expires_at",
        # Raw Patreon/provider internals and secrets that must stay server-only.
        "patreon_user_id",
        "patreon_member_id",
        "patreon_campaign_id",
        "patreon_tier_id",
        "raw_patreon_email",
        "masked_patreon_email",
        "patreon_email",
        "proof_email",
        "proof_email_hash",
        "proof_email_masked",
        "patreon_user_id_hash",
        "patreon_member_id_hash",
        "patreon_campaign_id_hash",
        "patreon_tier_id_hash",
        "patreon_user_id_fingerprint",
        "patreon_member_id_fingerprint",
        "patreon_campaign_id_fingerprint",
        "patreon_tier_id_fingerprint",
        "provider_sub_hash",
        "provider_sub_fingerprint",
        "hash_prefix",
        "member_id_hash",
        "campaign_id_hash",
        "tier_id_hash",
        "member_id_fingerprint",
        "campaign_id_fingerprint",
        "tier_id_fingerprint",
        "patron_status",
        "currently_entitled_tiers",
        "last_charge_status",
        "x-patreon-signature",
        "patreon_signature",
        "webhook_secret",
        "creator_access_token",
        "creator_refresh_token",
        "patreon_access_token",
        "patreon_refresh_token",
        "patreon_payload",
        "provider_payload",
        "raw_payload",
        "raw_body",
        "delivery_hash",
        "raw_body_sha256",
        "payload_hash",
        "audit_rows",
        "proof_token",
        "proof_secret",
        "token_hash",
        "token_fingerprint",
        "s2s_token",
        "s2s_bearer_token",
        "hmac_secret",
    }
)

PATREON_SAFE_ENTITLEMENT_FIELD_NAMES: FrozenSet[str] = frozenset(
    {
        "external_source",
        "status",
        "plan_code",
        "tier_code",
        "tier_name",
        "link_status",
        "next_renewal_at",
        "grace_period_until",
        "last_synced_at",
        "stale_after",
        "classification_version",
    }
)
PATREON_LINK_STATUS_RESPONSE_FIELD_NAMES: FrozenSet[str] = frozenset(
    {"success", "message", "link_status", "entitlement", "retry_after_seconds"}
)
PATREON_PROOF_REQUEST_RESPONSE_FIELD_NAMES: FrozenSet[str] = frozenset(
    {"success", "message", "accepted", "link_status", "retry_after_seconds"}
)
PATREON_UNLINK_RESPONSE_FIELD_NAMES: FrozenSet[str] = frozenset(
    {"success", "message", "link_status", "entitlement"}
)
PATREON_S2S_RESPONSE_FIELD_NAMES: FrozenSet[str] = frozenset(
    {"success", "message", "user_hash", "entitlement", "contract_version"}
)
PATREON_RESYNC_ACCEPTED_RESPONSE_FIELD_NAMES: FrozenSet[str] = frozenset(
    {
        "success",
        "message",
        "accepted",
        "status",
        "user_hash",
        "retry_after_seconds",
        "not_before",
        "correlation_id",
        "contract_version",
    }
)


def _assert_patreon_model_allow_list(model_cls: type[BaseModel], allow_list: FrozenSet[str]) -> FrozenSet[str]:
    """Validate one Patreon response DTO against its explicit response allow-list."""

    if not allow_list:
        raise RuntimeError(f"{model_cls.__name__} is missing an explicit Patreon safe-field allow-list")
    model_fields = frozenset(model_cls.model_fields)
    forbidden = model_fields & PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES
    unexpected = model_fields - allow_list
    missing = allow_list - model_fields
    if forbidden or unexpected or missing:
        raise RuntimeError(
            f"{model_cls.__name__} is not Patreon-safe: "
            f"forbidden={sorted(forbidden)}, unexpected={sorted(unexpected)}, missing={sorted(missing)}"
        )
    return allow_list


def _model_dump_patreon_safe(instance: BaseModel, **kwargs: Any) -> Dict[str, Any]:
    """Serialize only fields explicitly allow-listed for the Patreon DTO surface."""

    safe_fields = getattr(instance.__class__, "safe_fields", frozenset())
    allow_list = _assert_patreon_model_allow_list(instance.__class__, frozenset(safe_fields))
    return instance.model_dump(include=set(allow_list), **kwargs)


class PatreonSafeModelConfig(BaseModelConfig):
    """Base for Patreon browser/S2S DTOs with explicit no-leak defaults.

    Safe Patreon models are allow-list based: unknown extra fields are refused,
    and response DTOs below publish only normalized fields. Raw Patreon IDs,
    emails, payloads, signatures, provider tokens, session tokens, fingerprints,
    hash prefixes, and audit rows belong only on server-side internals.
    """

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )

    safe_fields: ClassVar[FrozenSet[str]] = frozenset()
    forbidden_response_fields: ClassVar[FrozenSet[str]] = PATREON_FORBIDDEN_RESPONSE_FIELD_NAMES

    def model_dump_safe(self, **kwargs: Any) -> Dict[str, Any]:
        """Serialize using this DTO's explicit allow-list; no field fallback is allowed."""

        return _model_dump_patreon_safe(self, **kwargs)


class PatreonLinkRequest(PatreonSafeModelConfig):
    """Authenticated Patreon link initiation request.

    ``patreon_email_hint`` is only a lookup hint. The proof email must be sent
    only to the non-null Patreon member email returned by the creator API.
    """

    patreon_email_hint: Optional[str] = Field(
        default=None,
        min_length=3,
        max_length=320,
        description="Optional user-supplied lookup hint; never durable link authority.",
    )
    explicit_user_intent: bool = Field(
        default=False,
        description="Route-level guard that the user explicitly requested Patreon linking.",
    )
    confirm_email_match: bool = Field(
        default=False,
        description="User confirmation when a non-null Patreon email matches local email.",
    )

    @field_validator("patreon_email_hint", mode="before")
    @classmethod
    def normalize_patreon_email_hint(cls, value: Any) -> Any:
        return _optional_email_or_none(value)


class PatreonProofConfirmRequest(PatreonSafeModelConfig):
    """Request body for consuming a Patreon email-loop proof.

    The accepted ``token``/``lookup_id``/``secret`` values are request-only proof
    material. They are not auth/session/provider tokens and must never be echoed
    by any Patreon response model.
    """

    token: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    lookup_id: Optional[str] = Field(default=None, min_length=1, max_length=256)
    secret: Optional[str] = Field(default=None, min_length=1, max_length=4096)
    explicit_user_intent: bool = Field(default=False)

    @field_validator("token", "lookup_id", "secret", mode="before")
    @classmethod
    def normalize_optional_proof_part(cls, value: Any) -> Any:
        return _optional_stripped_string_or_none(value)


class PatreonLinkConfirmRequest(PatreonProofConfirmRequest):
    """Compatibility name for Patreon link-confirm route bodies."""

    pass


class PatreonUnlinkRequest(PatreonSafeModelConfig):
    """Authenticated unlink request body for clients that send DELETE JSON."""

    explicit_user_intent: bool = Field(default=False)
    confirm_unlink: bool = Field(default=False)


class PatreonSafeEntitlement(PatreonSafeModelConfig):
    """Normalized Patreon entitlement safe for S2S and client projection.

    This DTO deliberately contains no raw Patreon IDs, campaign/tier IDs, raw or
    masked email, provider payloads, charge details, signatures, hashes,
    fingerprints, audit rows, secrets, or local auth tokens.
    """

    safe_fields: ClassVar[FrozenSet[str]] = PATREON_SAFE_ENTITLEMENT_FIELD_NAMES

    external_source: Optional[Literal["patreon"]] = None
    status: PatreonEntitlementStatus = "free"
    plan_code: str = Field(default="free", min_length=1, max_length=128)
    tier_code: Optional[str] = Field(default=None, min_length=1, max_length=128)
    tier_name: Optional[str] = Field(default=None, min_length=1, max_length=256)
    link_status: PatreonSafeLinkStatus = "none"
    next_renewal_at: Optional[datetime] = None
    grace_period_until: Optional[datetime] = None
    last_synced_at: Optional[datetime] = None
    stale_after: Optional[datetime] = None
    classification_version: int = Field(default=1, ge=1)

    @field_validator("plan_code", "tier_code", "tier_name", mode="before")
    @classmethod
    def normalize_optional_codes(cls, value: Any) -> Any:
        return _optional_stripped_string_or_none(value)


class PatreonProofRequestResponse(BaseResponse):
    """Generic, enumeration-safe response for link proof initiation."""

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )
    safe_fields: ClassVar[FrozenSet[str]] = PATREON_PROOF_REQUEST_RESPONSE_FIELD_NAMES

    accepted: bool = True
    message: Optional[str] = "If the Patreon link can be processed, a proof request has been accepted."
    link_status: Optional[PatreonSafeLinkStatus] = None
    retry_after_seconds: Optional[int] = Field(default=None, ge=0)

    def model_dump_safe(self, **kwargs: Any) -> Dict[str, Any]:
        return _model_dump_patreon_safe(self, **kwargs)


class PatreonLinkRequestResponse(PatreonProofRequestResponse):
    """Compatibility name for Patreon link-request responses."""

    pass


class PatreonLinkStatusResponse(BaseResponse):
    """Owning-user Patreon link status response with safe entitlement only."""

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )
    safe_fields: ClassVar[FrozenSet[str]] = PATREON_LINK_STATUS_RESPONSE_FIELD_NAMES

    link_status: PatreonSafeLinkStatus = "none"
    entitlement: Optional[PatreonSafeEntitlement] = None
    retry_after_seconds: Optional[int] = Field(default=None, ge=0)

    def model_dump_safe(self, **kwargs: Any) -> Dict[str, Any]:
        return _model_dump_patreon_safe(self, **kwargs)


class PatreonUnlinkResponse(BaseResponse):
    """Safe unlink response; unlink never revokes or returns local sessions."""

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )
    safe_fields: ClassVar[FrozenSet[str]] = PATREON_UNLINK_RESPONSE_FIELD_NAMES

    link_status: PatreonSafeLinkStatus = "unlinked"
    entitlement: Optional[PatreonSafeEntitlement] = None

    def model_dump_safe(self, **kwargs: Any) -> Dict[str, Any]:
        return _model_dump_patreon_safe(self, **kwargs)


class PatreonEntitlementS2SResponse(BaseResponse):
    """Dedicated Magic Worlds S2S entitlement response.

    The contract is a normalized projection only. It intentionally excludes raw
    provider identifiers, provider emails, webhook data, hashes/fingerprints,
    audit rows, secrets, and all local auth token/session fields.
    """

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )
    safe_fields: ClassVar[FrozenSet[str]] = PATREON_S2S_RESPONSE_FIELD_NAMES

    user_hash: str = Field(..., min_length=1, max_length=255)
    entitlement: PatreonSafeEntitlement
    contract_version: int = Field(default=1, ge=1)

    def model_dump_safe(self, **kwargs: Any) -> Dict[str, Any]:
        return _model_dump_patreon_safe(self, **kwargs)


class PatreonResyncRequest(PatreonSafeModelConfig):
    """S2S/manual resync request body with no raw provider selectors."""

    force: bool = False
    reason: Optional[str] = Field(default=None, min_length=1, max_length=128)

    @field_validator("reason", mode="before")
    @classmethod
    def normalize_reason(cls, value: Any) -> Any:
        return _optional_stripped_string_or_none(value)


class PatreonResyncAcceptedResponse(BaseResponse):
    """Safe acceptance response for internal Patreon resync enqueue requests."""

    model_config = ConfigDict(
        from_attributes=True,
        validate_assignment=True,
        arbitrary_types_allowed=True,
        extra="forbid",
    )
    safe_fields: ClassVar[FrozenSet[str]] = PATREON_RESYNC_ACCEPTED_RESPONSE_FIELD_NAMES

    accepted: bool = True
    status: PatreonResyncAcceptanceStatus = "accepted"
    user_hash: Optional[str] = Field(default=None, min_length=1, max_length=255)
    retry_after_seconds: Optional[int] = Field(default=None, ge=0)
    not_before: Optional[datetime] = None
    correlation_id: Optional[str] = Field(default=None, min_length=1, max_length=128)
    contract_version: int = Field(default=1, ge=1)
    message: Optional[str] = "Patreon entitlement resync request accepted."

    def model_dump_safe(self, **kwargs: Any) -> Dict[str, Any]:
        return _model_dump_patreon_safe(self, **kwargs)


def assert_patreon_response_model_allow_lists() -> None:
    """Fail fast if Patreon response DTOs drift outside their safe allow-lists."""

    model_allow_lists = {
        PatreonSafeEntitlement: PATREON_SAFE_ENTITLEMENT_FIELD_NAMES,
        PatreonProofRequestResponse: PATREON_PROOF_REQUEST_RESPONSE_FIELD_NAMES,
        PatreonLinkRequestResponse: PATREON_PROOF_REQUEST_RESPONSE_FIELD_NAMES,
        PatreonLinkStatusResponse: PATREON_LINK_STATUS_RESPONSE_FIELD_NAMES,
        PatreonUnlinkResponse: PATREON_UNLINK_RESPONSE_FIELD_NAMES,
        PatreonEntitlementS2SResponse: PATREON_S2S_RESPONSE_FIELD_NAMES,
        PatreonResyncAcceptedResponse: PATREON_RESYNC_ACCEPTED_RESPONSE_FIELD_NAMES,
    }
    for model_cls, allow_list in model_allow_lists.items():
        if frozenset(getattr(model_cls, "safe_fields", frozenset())) != allow_list:
            raise RuntimeError(f"{model_cls.__name__} safe_fields does not match its explicit allow-list")
        _assert_patreon_model_allow_list(model_cls, allow_list)


assert_patreon_response_model_allow_lists()


class OAuthErrorResponse(BaseResponse):
    """Neutral OAuth error response with optional correlation only."""

    success: bool = False
    correlation_id: Optional[str] = None


class WeakPasswordErrorDetails(BaseModelConfig):
    """Secret-safe weak-password error details.

    Contains only non-secret policy categories and server configuration. It must
    never include the submitted password, contextual identifiers, or denylist
    contents.
    """

    reason_codes: List[str] = Field(default_factory=list)
    min_length: Optional[int] = None


class ChangePasswordRequest(BaseModelConfig):
    """Authenticated password-change request.

    Password fields are accepted only by the dedicated change-password endpoint;
    profile update models remain a non-credential surface.
    """

    current_password: str = Field(..., min_length=1, max_length=1024)
    new_password: str = Field(..., min_length=1, max_length=1024)


class ChangePasswordResponse(BaseResponse):
    """Secret-free authenticated password-change response."""

    message: Optional[str] = "Password changed successfully"


class SwitchProjectResponse(BaseResponse, TokenPairFields):
    """Switch project response"""
    project: Optional[ProjectInfo] = None
    user_groups: List[str] = Field(default_factory=list)


class CheckAvailabilityResponse(BaseResponse):
    """Username/email availability response"""
    username_available: Optional[bool] = None
    email_available: Optional[bool] = None


# =================== USER MANAGEMENT RESPONSES ===================

class UserProfileResponse(BaseResponse):
    """User profile response with comprehensive user information"""
    user_hash: Optional[str] = None
    username: Optional[str] = None
    email: Optional[str] = None
    user_type: Optional[str] = None
    user_type_info: Optional[Dict[str, Any]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None
    last_login: Optional[datetime] = None
    is_active: Optional[bool] = None
    groups: List[Dict[str, Any]] = Field(default_factory=list)
    projects: List[ProjectInfo] = Field(default_factory=list)


class UpdateProfileResponse(BaseResponse):
    """Update profile response"""
    user: Optional[UserInfo] = None


class AccessSummaryResponse(BaseResponse):
    """Access summary response"""
    access_summary: Optional[Dict[str, Any]] = None


class ListUsersResponse(BaseResponse):
    """List users response"""
    users: List[Dict[str, Any]] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None
    filters: Optional[Dict[str, Any]] = None


class GetUserDetailsResponse(BaseResponse):
    """Get user details response"""
    user: Optional[Dict[str, Any]] = None
    permissions: List[str] = Field(default_factory=list)
    groups: List[str] = Field(default_factory=list)
    accessible_projects: List[ProjectInfo] = Field(default_factory=list)
    statistics: Optional[Dict[str, Any]] = None


class UpdateUserStatusResponse(BaseResponse):
    """Update user status response"""
    user_hash: Optional[str] = None
    is_active: Optional[bool] = None


class ChangeUserTypeResponse(BaseResponse):
    """Change user type response"""
    user_hash: Optional[str] = None
    previous_type: Optional[str] = None
    new_type: Optional[str] = None


class DeleteUserResponse(BaseResponse):
    """Delete user response"""
    user_hash: Optional[str] = None
    username: Optional[str] = None
    deleted_at: Optional[str] = None


class SearchUsersResponse(BaseResponse):
    """Search users response"""
    users: List[Dict[str, Any]] = Field(default_factory=list)
    search_term: Optional[str] = None
    total_results: Optional[int] = None


class CreateConsumerUserResponse(BaseResponse):
    """Create consumer user response"""
    user: Optional[UserInfo] = None
    assigned_groups: List[str] = Field(default_factory=list)


# =================== PROJECT MANAGEMENT RESPONSES ===================

class ProjectAccessInfo(BaseModelConfig):
    """Project access information"""
    project_hash: str
    project_name: str
    project_description: Optional[str] = None
    access_level: str
    access_through: str


class ListProjectsResponse(BaseResponse):
    """List projects response"""
    projects: List[ProjectAccessInfo] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None
    user_access_level: str


class CreateProjectResponse(BaseResponse):
    """Create project response"""
    project: Optional[ProjectInfo] = None


class ProjectDetailsResponse(BaseResponse):
    """Project details response"""
    project: Optional[ProjectInfo] = None
    user_access: Optional[Dict[str, Any]] = None
    statistics: Optional[Dict[str, Any]] = None
    project_groups: List[Dict[str, Any]] = Field(default_factory=list, description="Project groups this project belongs to")


class UpdateProjectResponse(BaseResponse):
    """Update project response"""
    project: Optional[ProjectInfo] = None


class DeleteProjectResponse(BaseResponse):
    """Delete project response"""
    deleted_project: Optional[ProjectInfo] = None
    warning: Optional[str] = None


# =================== USER TYPE MANAGEMENT RESPONSES ===================

class UserTypeInfo(BaseModelConfig):
    """User type information"""
    user_id: str
    user_hash: str
    username: str
    user_type: str
    capabilities: List[str] = Field(default_factory=list)
    assigned_project_id: Optional[str] = None
    assigned_projects: Optional[List[Dict[str, Any]]] = None
    created_at: Optional[datetime] = None
    updated_at: Optional[datetime] = None


class CreateRootUserResponse(BaseResponse):
    """Create root user response"""
    user: Optional[UserInfo] = None


class CreateAdminUserResponse(BaseResponse):
    """Create admin user response"""
    user: Optional[Dict[str, Any]] = None


class UserTypeInfoResponse(BaseResponse):
    """User type info response"""
    user_type_info: Optional[UserTypeInfo] = None


class UpdateUserTypeResponse(BaseResponse):
    """Update user type response"""
    user_type_info: Optional[UserTypeInfo] = None


class ListUsersByTypeResponse(BaseResponse):
    """List users by type response"""
    users: List[Dict[str, Any]] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None
    filter: Optional[Dict[str, Any]] = None


class UserTypeStatsResponse(BaseResponse):
    """User type statistics response"""
    statistics: Optional[Dict[str, Any]] = None


# =================== ADMIN PROJECT MANAGEMENT RESPONSES ===================

class AdminProjectInfo(BaseModelConfig):
    """Admin project assignment information"""
    project_id: str
    project_hash: str
    project_name: str
    project_description: Optional[str] = None
    assigned_at: Optional[datetime] = None
    assigned_by: Optional[str] = None


class AdminProjectsResponse(BaseResponse):
    """Get admin user's projects response"""
    user_hash: str
    assigned_projects: List[AdminProjectInfo] = Field(default_factory=list)


class UpdateAdminProjectsResponse(BaseResponse):
    """Update admin user's projects response"""
    user_hash: str
    assigned_projects: List[AdminProjectInfo] = Field(default_factory=list)
    total_projects: int = 0


class AddAdminToProjectResponse(BaseResponse):
    """Add admin to project response"""
    user_hash: str
    project_id: str
    project_hash: Optional[str] = None
    project_name: Optional[str] = None


class RemoveAdminFromProjectResponse(BaseResponse):
    """Remove admin from project response"""
    user_hash: str
    project_id: str


class UpdateUserResponse(BaseResponse):
    """Update user details response"""
    user: Optional[UserInfo] = None
    updated_at: Optional[datetime] = None


# =================== ADMIN GROUP MANAGEMENT RESPONSES ===================

class ListUserGroupsResponse(BaseResponse):
    """List user groups response"""
    user_groups: List[UserGroupInfo] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None


class CreateUserGroupResponse(BaseResponse):
    """Create user group response"""
    user_group: Optional[UserGroupInfo] = None


class UserGroupDetailsResponse(BaseResponse):
    """User group details response"""
    user_group: Optional[UserGroupInfo] = None
    members: List[UserInfo] = Field(default_factory=list)
    accessible_projects: List[ProjectInfo] = Field(default_factory=list)
    accessible_project_groups: List[Dict[str, Any]] = Field(default_factory=list)  # Groups-of-Groups architecture
    derived_projects: List[ProjectInfo] = Field(default_factory=list)  # Projects via project_groups
    statistics: Optional[Dict[str, Any]] = None


class UpdateUserGroupResponse(BaseResponse):
    """Update user group response"""
    user_group: Optional[UserGroupInfo] = None


class DeleteUserGroupResponse(BaseResponse):
    """Delete user group response"""
    warning: Optional[str] = None


class AssignUserToGroupResponse(BaseResponse):
    """Assign user to group response"""
    assignment: Optional[Dict[str, Any]] = None


class RemoveUserFromGroupResponse(BaseResponse):
    """Remove user from group response"""
    pass


# =================== PROJECT-GROUP ACCESS RESPONSES (Groups-of-Groups Architecture) ===================

class GrantUserGroupProjectGroupAccessResponse(BaseResponse):
    """Grant user group access to project group response (groups-of-groups architecture)"""
    access_details: Optional[Dict[str, Any]] = None
    user_group: Optional[Dict[str, Any]] = None
    project_group: Optional[Dict[str, Any]] = None


class RevokeUserGroupProjectGroupAccessResponse(BaseResponse):
    """Revoke user group access to project group response"""
    pass


class ListProjectGroupsForUserGroupResponse(BaseResponse):
    """List project groups that a user group has access to"""
    user_group: Optional[UserGroupInfo] = None
    project_groups: List[Dict[str, Any]] = Field(default_factory=list)
    total_project_groups: int = 0
    total_derived_projects: int = 0


class ListProjectGroupsResponse(BaseResponse):
    """List project groups response"""
    project_groups: List[ProjectGroupInfo] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None


class CreateProjectGroupResponse(BaseResponse):
    """Create project group response"""
    project_group: Optional[ProjectGroupInfo] = None


class ProjectGroupDetailsResponse(BaseResponse):
    """Project group details response"""
    project_group: Optional[ProjectGroupInfo] = None
    assigned_projects: List[ProjectInfo] = Field(default_factory=list)
    statistics: Optional[Dict[str, Any]] = None


class UpdateProjectGroupResponse(BaseResponse):
    """Update project group response"""
    project_group: Optional[ProjectGroupInfo] = None


class DeleteProjectGroupResponse(BaseResponse):
    """Delete project group response"""
    warning: Optional[str] = None


class AssignProjectToGroupResponse(BaseResponse):
    """Assign project to group response"""
    assignment: Optional[Dict[str, Any]] = None


class RemoveProjectFromGroupResponse(BaseResponse):
    """Remove project from group response"""
    pass


# =================== RBAC MANAGEMENT RESPONSES ===================

class ListPermissionsResponse(BaseResponse):
    """List permissions response"""
    project: Optional[ProjectInfo] = None
    permissions: List[PermissionInfo] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None


class CreatePermissionResponse(BaseResponse):
    """Create permission response"""
    permission: Optional[PermissionInfo] = None


class ListRolesResponse(BaseResponse):
    """List roles response"""
    project: Optional[ProjectInfo] = None
    roles: List[RoleInfo] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None


class CreateRoleResponse(BaseResponse):
    """Create role response"""
    role: Optional[Dict[str, Any]] = None


class AssignUserToRoleResponse(BaseResponse):
    """Assign user to role response"""
    assignment: Optional[Dict[str, Any]] = None


class ListUserRolesResponse(BaseResponse):
    """List user roles response"""
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    roles: List[RoleInfo] = Field(default_factory=list)


class UserEffectivePermissionsResponse(BaseResponse):
    """User effective permissions response"""
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    effective_permissions: List[Dict[str, Any]] = Field(default_factory=list)
    summary: Optional[Dict[str, Any]] = None


class CheckPermissionResponse(BaseResponse):
    """Check permission response"""
    user: Optional[UserInfo] = None
    project: Optional[ProjectInfo] = None
    permission_check: Optional[Dict[str, Any]] = None


class InitializeRBACResponse(BaseResponse):
    """Initialize RBAC response"""
    project: Optional[ProjectInfo] = None
    initialization_summary: Optional[Dict[str, Any]] = None
    created_permissions: List[str] = Field(default_factory=list)
    created_roles: List[str] = Field(default_factory=list)


class ProjectAuditLogResponse(BaseResponse):
    """Project audit log response"""
    project: Optional[ProjectInfo] = None
    audit_log: List[Dict[str, Any]] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None


class RBACProjectSummaryResponse(BaseResponse):
    """RBAC project summary response"""
    project: Optional[ProjectInfo] = None
    rbac_summary: Optional[Dict[str, Any]] = None


# =================== SYSTEM RESPONSES ===================

class SystemInfoResponse(BaseResponse):
    """System info response"""
    system: Optional[Dict[str, Any]] = None
    statistics: Optional[Dict[str, Any]] = None
    features: List[str] = Field(default_factory=list)


class HealthCheckResponse(BaseResponse):
    """Health check response"""
    status: str
    timestamp: str
    components: Optional[Dict[str, Any]] = None


class PingResponse(BaseResponse):
    """Ping response"""
    timestamp: str


class CacheStatsResponse(BaseResponse):
    """Cache statistics response"""
    cache_statistics: Optional[Dict[str, Any]] = None
    cache_configuration: Optional[Dict[str, Any]] = None
    timestamp: str


class ClearCacheResponse(BaseResponse):
    """Clear cache response"""
    cleared_by: Optional[str] = None
    timestamp: str
    warning: Optional[str] = None


class InvalidateCacheResponse(BaseResponse):
    """Invalidate cache response"""
    invalidated_by: Optional[str] = None
    timestamp: str


# =================== REQUEST MODELS ===================

class LoginRequest(BaseModelConfig):
    """Login request model"""
    username: str
    password: str
    project_hash: Optional[str] = None  # Required for all users at route level; root bypasses group validation


class RegisterRequest(BaseModelConfig):
    """Register request model – updated to accept a *user_group_hash* instead of a project hash"""
    username: str
    password: str
    email: Optional[str] = None
    user_group_hash: str

    @field_validator("email", mode="before")
    @classmethod
    def normalize_optional_email(cls, value: Any) -> Any:
        return _optional_email_or_none(value)


class SwitchProjectRequest(BaseModelConfig):
    """Switch project request model"""
    project_hash: str


class CheckAvailabilityRequest(BaseModelConfig):
    """Check availability request model"""
    username: Optional[str] = None
    email: Optional[str] = None

    @field_validator("email", mode="before")
    @classmethod
    def normalize_optional_email(cls, value: Any) -> Any:
        return _optional_email_or_none(value)


class UserUpdateRequest(BaseModelConfig):
    """User update request model.

    The legacy ``password`` field is retained only for parser compatibility
    while routes reject it before persistence. Clients must use
    ``POST /auth/password/change`` for credential rotation.
    """
    username: Optional[str] = None
    email: Optional[str] = None
    password: Optional[str] = None

    @field_validator("email", mode="before")
    @classmethod
    def normalize_optional_email(cls, value: Any) -> Any:
        return _optional_email_or_none(value)


class ProjectCreateRequest(BaseModelConfig):
    """Project create request model"""
    project_name: str
    project_description: Optional[str] = None


class ProjectUpdateRequest(BaseModelConfig):
    """Project update request model"""
    project_name: Optional[str] = None
    project_description: Optional[str] = None


class CreateRootUserRequest(BaseModelConfig):
    """Create root user request model"""
    username: str
    password: str
    email: Optional[str] = None

    @field_validator("email", mode="before")
    @classmethod
    def normalize_optional_email(cls, value: Any) -> Any:
        return _optional_email_or_none(value)


class CreateAdminUserRequest(BaseModelConfig):
    """Create admin user request model"""
    username: str
    password: str
    email: Optional[str] = None
    assigned_project_id: Optional[str] = None
    assigned_project_ids: Optional[List[str]] = None

    @field_validator("email", mode="before")
    @classmethod
    def normalize_optional_email(cls, value: Any) -> Any:
        return _optional_email_or_none(value)


class UpdateUserTypeRequest(BaseModelConfig):
    """Update user type request model"""
    user_type: str
    assigned_project_id: Optional[str] = None


class UserGroupCreateRequest(BaseModelConfig):
    """User group create request model"""
    group_name: str
    description: Optional[str] = None


class UserGroupUpdateRequest(BaseModelConfig):
    """User group update request model"""
    group_name: Optional[str] = None
    description: Optional[str] = None


class ProjectGroupCreateRequest(BaseModelConfig):
    """Project group create request model"""
    group_name: str
    permissions: List[str]
    description: Optional[str] = None


class ProjectGroupUpdateRequest(BaseModelConfig):
    """Project group update request model"""
    group_name: Optional[str] = None
    permissions: Optional[List[str]] = None
    description: Optional[str] = None


class PermissionCreateRequest(BaseModelConfig):
    """Permission create request model"""
    permission_name: str
    category: str = "general"
    description: Optional[str] = None


class PermissionGroupCreateRequest(BaseModelConfig):
    """Permission group create request model"""
    group_name: str
    priority: int = 50
    description: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)


class AssignUserToRoleRequest(BaseModelConfig):
    """Assign user to role request model"""
    role_id: str


class AssignmentRequest(BaseModelConfig):
    """Generic assignment request model"""
    user_hash: Optional[str] = None
    group_hash: Optional[str] = None
    project_hash: Optional[str] = None


# =================== LEGACY COMPATIBILITY MODELS ===================

class UserLogin(BaseModelConfig):
    """Legacy compatibility login response"""
    user_session: str
    user_session_length: int
    user_hash: str
    user_collection: str
    user_id: str
    project_id: Optional[str] = None  # Optional for global root sessions
    user_project_id: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    user_type: str = 'consumer'
    assigned_project_id: Optional[str] = None


class EnhancedUserLogin(BaseModelConfig):
    """Enhanced login response with group-based access"""
    user_hash: str
    scope: Optional[str] = None
    project_hash: Optional[str] = None
    project_name: Optional[str] = None
    user_project_hash: str = ""
    session_token: str
    session_length: int
    user_id: str
    username: Optional[str] = None  # Phase 1.2a: populated from session data to avoid get_user_by_hash()
    project_id: Optional[str] = None  # Optional for global root sessions
    user_project_id: Optional[str] = None
    groups: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    available_projects: List['ProjectSummary'] = Field(default_factory=list)
    user_type: str = 'consumer'
    assigned_project_id: Optional[str] = None
    access_token: Optional[str] = None
    refresh_token: Optional[str] = None
    token_type: str = TOKEN_TYPE_BEARER
    expires_in: Optional[int] = None
    refresh_expires_in: Optional[int] = None
    expires_at: Optional[datetime] = None
    refresh_expires_at: Optional[datetime] = None
    cookie_metadata: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


# =================== SPECIALIZED MODELS ===================

class ProjectSummary(BaseModelConfig):
    """Summary of projects accessible to user"""
    id: str
    project_hash: str
    project_name: str
    project_description: Optional[str] = None
    project_group_name: str
    permissions: List[str] = Field(default_factory=list)


class UserPermissionSummary(BaseModelConfig):
    """Summary of user's permissions within a project"""
    user_id: str
    user_hash: str
    username: str
    project_id: str
    project_hash: str
    project_name: str
    assigned_roles: List[PermissionGroup] = Field(default_factory=list)
    effective_permissions: List[Permission] = Field(default_factory=list)
    highest_priority_role: Optional[PermissionGroup] = None


class ProjectRoleSummary(BaseModelConfig):
    """Summary of roles within a project"""
    project_id: str
    project_hash: str
    project_name: str
    roles: List[PermissionGroup] = Field(default_factory=list)
    total_permissions: int
    total_users: int
    permission_categories: List[str] = Field(default_factory=list)


# =================== ADMIN USER GROUPS ADDITIONAL RESPONSES ===================

class GroupMembersPaginatedResponse(BaseResponse):
    """Response model for paginated group members listing"""
    user_group: Optional[UserGroupInfo] = None
    members: List[Dict[str, Any]] = Field(default_factory=list)
    pagination: Optional[PaginationInfo] = None
    statistics: Optional[Dict[str, Any]] = None
    generated_at: Optional[str] = None


class BulkAddUsersToGroupRequest(BaseModelConfig):
    """Request model for bulk adding users to a group"""
    user_hashes: List[str] = Field(..., min_length=1, max_length=100, description="List of user hashes to add to the group")


class BulkAddUsersToGroupResponse(BaseResponse):
    """Response model for bulk adding users to a group"""
    user_group: Optional[Dict[str, Any]] = None
    summary: Optional[Dict[str, Any]] = None
    results: List[Dict[str, Any]] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)
    performed_by: Optional[str] = None
    performed_at: Optional[str] = None


class UserGroupsForUserResponse(BaseResponse):
    """Response model for listing user's group memberships"""
    user: Optional[Dict[str, Any]] = None
    groups: List[Dict[str, Any]] = Field(default_factory=list)
    statistics: Optional[Dict[str, Any]] = None
    generated_at: Optional[str] = None
