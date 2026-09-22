"""GitHub adapter (plain OAuth 2.0, no ID token).

Subject is the numeric account ``id`` -- stable and global, unlike ``login`` which
users can rename. A verified e-mail needs a second API call; only an address that
is both ``primary`` and ``verified`` is reported as verified. Optional ``orgs``
restriction requires the ``read:org`` scope.
"""

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


class GitHubAdapter(OAuth2UserInfoAdapter):
    provider_type = "github"
    capabilities = ProviderCapabilities(
        protocol="oauth2",
        pkce=True,
        nonce=False,
        subject_scope=SUBJECT_SCOPE_GLOBAL,
        email_trust=EMAIL_TRUST_VERIFIED,
    )
    authorize_endpoint = "https://github.com/login/oauth/authorize"
    token_endpoint = "https://github.com/login/oauth/access_token"
    userinfo_endpoint = "https://api.github.com/user"
    emails_endpoint = "https://api.github.com/user/emails"
    orgs_endpoint = "https://api.github.com/user/orgs"
    default_scopes = "read:user user:email"
    required_scopes = frozenset({"read:user", "user:email"})
    userinfo_headers = {"Accept": "application/vnd.github+json", "X-GitHub-Api-Version": "2022-11-28"}

    def validate_connection(self, connection: ConnectionConfig) -> list[str]:
        problems = super().validate_connection(connection)
        if connection.restriction_list("orgs") and "read:org" not in set(connection.scopes.split()):
            problems.append("scopes must include 'read:org' when an organisation restriction is set")
        return problems

    def fetch_profile(self, connection: ConnectionConfig, access_token: str) -> Mapping[str, Any]:
        profile = dict(super().fetch_profile(connection, access_token))
        emails = self._api_get(self.emails_endpoint, access_token)
        profile["_emails"] = emails if isinstance(emails, list) else []
        if connection.restriction_list("orgs"):
            orgs = self._api_get(self.orgs_endpoint, access_token)
            profile["_orgs"] = [
                str(item.get("login") or "").lower() for item in orgs if isinstance(item, Mapping)
            ] if isinstance(orgs, list) else []
        return profile

    def identity_from_profile(self, connection: ConnectionConfig, profile: Mapping[str, Any]) -> ExternalIdentity:
        subject = profile.get("id")
        if subject in (None, ""):
            raise OAuthIdentityError(OAuthFailure.SUBJECT_MISSING, "GitHub account id is missing")
        email, verified = None, False
        for entry in profile.get("_emails") or []:
            if isinstance(entry, Mapping) and entry.get("primary") and entry.get("verified") and entry.get("email"):
                email, verified = str(entry["email"]).strip().lower(), True
                break
        attributes: dict[str, str] = {}
        if "_orgs" in profile:
            attributes["orgs"] = ",".join(sorted(profile.get("_orgs") or []))
        return ExternalIdentity(
            provider_type=self.provider_type,
            identity_namespace=self.identity_namespace(connection),
            subject=str(subject),
            email=email,
            email_verified=verified,
            email_trust=self.capabilities.email_trust,
            display_name=str(profile.get("name") or profile.get("login") or "") or None,
            attributes=attributes,
        )

    def enforce_restrictions(self, connection: ConnectionConfig, identity: ExternalIdentity) -> None:
        allowed = {org.lower() for org in connection.restriction_list("orgs")}
        if not allowed:
            return
        member_of = {org for org in str(identity.attributes.get("orgs", "")).split(",") if org}
        if not allowed & member_of:
            raise OAuthIdentityError(OAuthFailure.RESTRICTION_DENIED, "Account is not a member of an allowed organisation")


__all__ = ["GitHubAdapter"]
