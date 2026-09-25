# Google OAuth request flow

What the deprecated `/auth/google/*` aliases do. Only `POST /auth/google/start` has its
own logic; the other aliases run the shared pipeline described in the
[OAuth request flow](../oauth/request-flow.md), with the connection key fixed to `google`.
Examples use localhost placeholders only; never paste real Google codes, tokens, client
credentials, raw `project_hash`, raw `user_group_hash` or production origins.

## Legacy start

`POST /auth/google/start`, called with a provider-init token minted by the companion
backend.

1. The body must be a JSON object without `project_hash` or `user_group_hash`, with a
   `provider_init_token` of at most 4,096 characters: `400` `EXT_8012`. A forbidden field
   also records `google_oauth_provider_init_rejected`.
2. The Google bindings that accept the legacy handshake are found. Under
   `OAUTH_CONFIG_SOURCE=env` that is the environment connection, available when
   `GOOGLE_OAUTH_ENABLED` is on (`403` `EXT_8011`) and `GOOGLE_OAUTH_CLIENT_ID` is set
   (`503` `EXT_8010`). Under `db` it is every usable binding with connection key `google`
   and `init_mode: legacy_redeem`; none answers `403` `EXT_8011`.
3. Exactly one binding must own the pair of redirect URI (the requested one, else the
   binding's only one; the environment binding falls back to its first) and return origin
   (the requested one; the environment binding falls back to its first): `400`
   `EXT_8013`. Bindings of different projects are never merged.
4. The start and provider-init redeem buckets are spent: `429` `EXT_8030`.
5. The token is redeemed with one server-to-server `POST` to the redeem URL, carrying the
   redeem bearer, with a 5-second timeout and no redirects. The answer is validated:
   active, provider `google`, audience `api.auth` when present, a known purpose, a
   `project_hash`, an allowed return origin equal to the one in use, and a lifetime of at
   most `600` seconds. Under `db`, the project must be the binding's and a group, if
   present, the binding's default group. Any failure: `401` `EXT_8012` and
   `google_oauth_provider_init_rejected` with the reason.
6. State, nonce and PKCE verifier are stored in Redis for the login purpose with the
   redeemed project (and, for the environment binding, the redeemed group as the
   provisioning group) and `remember_me` from the body.
7. The answer is `303` to Google with the `oauth_state` cookie on path `/auth/google`, and
   `google_oauth_started` is recorded. State storage failure: `401` `EXT_8014`; any other
   failure: `503` `EXT_8010`.

The Google authorization URL carries:

- `response_type=code`
- `client_id` and `redirect_uri`
- `scope=openid email`
- `state` and `nonce` (256-bit random each)
- `code_challenge` with `code_challenge_method=S256`
- `prompt=login` for reauth

It must not include `profile`, `offline_access`, `access_type=offline`, or refresh-token consent parameters.

## Callback

`GET /auth/google/callback` behaves exactly like `GET /auth/oauth/callback`: the state is
consumed first, the code is exchanged once with the PKCE verifier, the ID token is
verified (RS256, `kid` with one JWKS refetch, issuer, audience, `azp`, expiry, nonce,
hosted domain, `google-auth` cross-check), Google token material is dropped, and the
purpose stored in the state decides the result: a `LoginResponse` with local session
cookies, a linked identity, or `{"reauthenticated": true}`. It accepts `code`, `state`
and `error`; `error_description` is ignored and there is no `iss` parameter. Activity is
recorded with the `google_oauth_*` codes.

## Link, reauth and unlink

| Alias | Runs | Notes |
| --- | --- | --- |
| `POST /auth/google/link/start` | The shared link start for the `google` binding of the session's project | Needs recent authentication and provisioning mode `link_only` or `both`; a session, provisioning or recent-authentication failure answers `401` `EXT_8024`. |
| `POST /auth/google/reauth/start` | The shared reauth start | No provisioning check and no recent authentication needed; sends `prompt=login`. |
| `DELETE /auth/google/unlink` | The shared unlink | Needs recent authentication and a usable password; revokes every session of the user. |

Linking and reauthentication complete inside the callback; there is no finish route.
Recent authentication counts the same whether the session came from a password login or
from Google.

## Middleware and audit

`/auth/google/start` and `/auth/google/callback` skip session extraction in
`AuthContextMiddleware` (no local session exists yet); the link, reauth and unlink aliases
do not. API audit stays active on all of them with `auth_method='oauth'` and the tags
`authentication`, `oauth`, `google_oauth` and `external_idp`; responses of `400` and above
are security events, and OAuth secrets are redacted.
