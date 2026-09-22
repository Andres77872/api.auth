"""Discord adapter (plain OAuth 2.0). Subject is the snowflake ``id``; global."""

from __future__ import annotations

from typing import Any, Mapping

from src.Util.oauth.adapters.oauth2_userinfo import OAuth2UserInfoAdapter
from src.Util.oauth.provider import (
    EMAIL_TRUST_VERIFIED,
    SUBJECT_SCOPE_GLOBAL,
    ConnectionConfig,
    ExternalIdentity,
    OAuthFailure,
    OAuthIdentityError,
    ProviderCapabilities,
)


class DiscordAdapter(OAuth2UserInfoAdapter):
    provider_type = "discord"
    capabilities = ProviderCapabilities(
        protocol="oauth2",
        pkce=True,
        nonce=False,
        subject_scope=SUBJECT_SCOPE_GLOBAL,
        email_trust=EMAIL_TRUST_VERIFIED,
    )
    authorize_endpoint = "https://discord.com/oauth2/authorize"
    token_endpoint = "https://discord.com/api/oauth2/token"
    userinfo_endpoint = "https://discord.com/api/users/@me"
    default_scopes = "identify email"
    required_scopes = frozenset({"identify"})

    def identity_from_profile(self, connection: ConnectionConfig, profile: Mapping[str, Any]) -> ExternalIdentity:
        subject = profile.get("id")
        if subject in (None, ""):
            raise OAuthIdentityError(OAuthFailure.SUBJECT_MISSING, "Discord account id is missing")
        email = str(profile.get("email") or "").strip().lower() or None
        return ExternalIdentity(
            provider_type=self.provider_type,
            identity_namespace=self.identity_namespace(connection),
            subject=str(subject),
            email=email,
            email_verified=bool(email and profile.get("verified") is True),
            email_trust=self.capabilities.email_trust,
            display_name=str(profile.get("global_name") or profile.get("username") or "") or None,
        )


__all__ = ["DiscordAdapter"]
