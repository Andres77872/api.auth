# OAuth request flow

What each `/auth/oauth/*` request does, in order, and where it can stop. Status codes
and error codes are listed per endpoint in [reference.md](reference.md#error-codes-by-endpoint).

## Transaction material

| Item | Created | Stored | Checked |
| --- | --- | --- | --- |
| Init token | `init`, 32 random bytes | Redis `oauth_init:<HMAC>`, `300` s, with connection id, binding id, project, return origin, `remember_me` | Consumed once by `start` |
| State | `start` or link/reauth start, 32 random bytes | Redis `oauth_state:<HMAC>`, binding `state_ttl_seconds` or `OAUTH_MAX_STATE_TTL_SECONDS`, whichever is lower (at most `600` s) | Consumed once by the callback, before the code exchange |
| Nonce | With the state, 32 random bytes | Inside the state record | Against the ID token's `nonce` (OIDC types) |
| PKCE verifier | With the state, 32 random bytes; `S256` challenge sent to the provider | Inside the state record only | Sent with the code exchange |
| `oauth_state` cookie | With the `303` | Browser; value is a fingerprint of the state | At the callback, only when the browser sends it |

Redis keys are HMACs of the secret under `OAUTH_STATE_PEPPER`; raw values never appear in
key names, logs or activity. A consumed init token or state leaves a `600`-second
tombstone, so reuse is reported as a replay. A Redis error always fails closed.

The state record also holds the purpose (`login`, `link`, `reauth`), the connection and
binding ids, the project, the redirect URI and, for link and reauth, the user and session
that started it. The callback takes all of these from the record, never from the
request, so a caller cannot switch provider, project or user mid-flight.

## Init

`POST /auth/oauth/init`, called by the project backend.

1. `OAUTH_ENABLED` must be on; otherwise `403` `EXT_8011` (checked before the API key).
2. The `X-API-Key` is validated; the project is the key's project. Invalid key: `401`.
3. The JSON body is read. `project_hash`, `user_group_hash`, `project` or `user_group`
   present, `connection` or `return_origin` missing, or `purpose` other than `login`:
   `400` `EXT_8012`.
4. The binding `(project, connection)` is resolved. A
   binding is refused when its provider type, adapter, connection, credentials, binding
   or project is unusable: disabled layers answer `404` `EXT_8011`, missing configuration
   `503` `EXT_8010`.
5. The binding's `login_enabled` (ANDed with the catalog's) must be on: `403` `EXT_8011`.
6. `return_origin` must equal one of the binding's return origins: `400` `EXT_8013`.
7. The init token is minted and returned with `Cache-Control: no-store`.

`init` has no OAuth rate-limit bucket; it is guarded by the API key.

## Start

`POST /auth/oauth/start`, called with the init token.

1. `OAUTH_ENABLED` must be on: `403` `EXT_8011`.
2. The body must be a JSON object without `project_hash` or `user_group_hash`, with an
   `init_token` of at most 512 characters: `400` `EXT_8012`.
3. The start bucket is spent (client IP and token fingerprint): `429` `EXT_8030`.
4. The init token is consumed. Unknown, expired, replayed, or Redis unavailable:
   `401` `EXT_8012`, recorded as `oauth_init_rejected`.
5. The connection and binding named in the token are resolved again, so a layer disabled
   since `init` is enforced: `403` `EXT_8011` or `503` `EXT_8010`.
6. The redirect URI is the requested one if it is on the binding, else the binding's only
   one; the token's return origin must still be on the binding: `400` `EXT_8013`.
7. `remember_me` from the body, when it is a boolean, replaces the value from `init`.
8. State, nonce and PKCE verifier are generated and stored; the adapter builds the
   authorization URL; `oauth_started` is recorded.
9. The answer is `303` with `Location` set to the provider and the `oauth_state` cookie
   (path `/auth/oauth`). If state storage fails the answer is `401` `EXT_8014`; if the URL
   cannot be built, `503` `EXT_8010`.

The authorization URL carries `response_type=code`, `client_id`, `redirect_uri`, the
connection's `scope`, `state`, `nonce` (OIDC types), `code_challenge` with
`code_challenge_method=S256`, and `prompt=login` for reauth. `access_type` is never sent.

## Callback

`GET /auth/oauth/callback` (query) or `POST /auth/oauth/callback` (form), called with what
the provider returned.

1. `oauth_callback_received` is recorded with the state fingerprint.
2. `state` is required, and so is `code` or `error`: `400` `EXT_8014`.
3. The callback and state-consume buckets are spent: `429` `EXT_8030`.
4. The state is consumed, before anything else, including a provider error. Replay:
   `401` `EXT_8016`; unknown, expired, malformed or Redis unavailable: `401` `EXT_8014`.
5. If the request carries an `oauth_state` cookie it must match the state:
   `401` `EXT_8014`. Behind a BFF the cookie is usually absent and the check is skipped.
6. The connection and binding are resolved again from the ids in the state record.
   Disabled since the start: `404` `EXT_8011`; no longer configured: `503` `EXT_8010`.
7. If the provider sent `error`: `access_denied`, `user_cancelled_authorize` and
   `user_cancelled_login` answer `400` `EXT_8031` (`oauth_user_cancelled`); any other
   value `502` `EXT_8018`.
8. The client secret is decrypted for this exchange only, and the code is exchanged at
   the token endpoint with the PKCE verifier. Any failure, including credentials that are
   missing or cannot be decrypted: `502` `EXT_8018`.
9. The adapter resolves the identity: OIDC types verify the ID token (signature, `kid`,
   issuer, audience, `azp`, `exp`/`iat`, nonce); GitHub and Discord read the profile with
   the access token. Connection restrictions are enforced. Failures map to
   `EXT_8017`–`EXT_8023` or `EXT_8010`.
10. All provider token material is dropped.
11. The identity key is derived: `HMAC-SHA256(OAUTH_PROVIDER_SUB_PEPPER, subject)` plus
    the identity namespace; missing pepper: `401` `EXT_8019`.
12. The request continues by the purpose in the state record.

### Login

1. The binding's `login_enabled` must be on: `401` `EXT_8024`.
2. The user is looked up by `(identity_namespace, subject hash)`.
   - Found: the account must be an active consumer, otherwise `401` `EXT_8024`. The
     last-seen time and masked e-mail snapshot are refreshed.
   - Not found: the binding must allow auto-create (`auto_create` or `both`), otherwise
     `401` `EXT_8024`. If the identity carries an e-mail already used by a local account,
     sign-in is refused: `409` `EXT_8032` when the provider verified the e-mail (Google,
     GitHub, Discord), `401` `EXT_8024` otherwise. The provisioning group is the binding's
     default user group; without one, `401` `EXT_8024`. A consumer is then created in one
     transaction with an unusable random password, the group membership, the external
     account link and, when the identity has an e-mail, a `pending`, non-primary e-mail
     row.
3. If the user does not reach the project fixed at `init` and the binding's
   `existing_user_policy` is `join_default_group`, the user is added to the default
   group.
4. The project must be reachable through the user's groups and be active and not
   archived: `403` `EXT_8025`. No other project is ever picked.
5. A local token pair is issued for that project with the `remember_me` from the state,
   the `access_token` and `refresh_token` cookies are set, `oauth_login_succeeded` is
   recorded, and the `LoginResponse` is returned.

Every refusal records `oauth_login_denied` with a `sub_reason` for operators, such as
`auto_create_disabled`, `email_collision_link_required`, `email_collision`,
`no_bound_user_group`, `existing_user_not_active_consumer` or `project_access_denied`.

### Link

1. The state must name a user and the binding must allow linking: `401` `EXT_8024`.
2. If the identity is linked to another user, the subject-collision bucket is spent
   (`429` `EXT_8030`) and the answer is `409` `EXT_8027`.
3. The identity is linked. Linking the same identity again refreshes its snapshot; a
   different identity in a namespace where the user already has one is refused:
   `409` `EXT_8027`.
4. The session that started the link is marked recently authenticated,
   `oauth_external_account_linked` is recorded and the masked identity is returned.

### Reauth

1. The identity must be linked to the user who started the reauth: `401` `EXT_8028`.
2. A recent-reauthentication marker is written for that user and session
   (`oauth_reauth:` key, lifetime `OAUTH_RECENT_REAUTH_SECONDS`), `oauth_reauth_succeeded`
   is recorded and `{"reauthenticated": true}` is returned.

## Link start and reauth start

`POST /auth/oauth/{connection}/link/start` and `.../reauth/start`, called with the user's
access token.

1. The access session is validated: `401` `EXT_8024`.
2. The binding for `(session project, connection)` is resolved: `404` `EXT_8011` or
   `503` `EXT_8010`.
3. Link only: the binding must allow linking, and the session must be recently
   authenticated (its `auth_time` within the window, or a reauth marker for this
   session): `401` `EXT_8024`.
4. A database binding must have exactly one redirect URI (the environment binding uses
   its first). The return origin is the one named in the optional JSON body, which must
   be on the binding, or the binding's only one: `400` `EXT_8013`.
5. State is created with the purpose, user id and session id (and `prompt=login` for
   reauth), and the answer is `303` to the provider. Any failure here: `401` `EXT_8014`.

## Unlink

`DELETE /auth/oauth/{connection}/link`, called with the user's access token.

1. The session is validated and the binding resolved. Invalid session: `401` `EXT_8028`;
   connection not available in the project: `404` `EXT_8028`.
2. The session must be recently authenticated: `401` `EXT_8028`.
3. The unlink bucket is spent (user and client IP): `429` `EXT_8030`.
4. The account must have a usable password: `409` `EXT_8029`. Accounts created by OAuth
   auto-create have none until the user sets one.
5. The link is soft-unlinked (`status = unlinked`); for a multi-tenant Microsoft
   connection every tenant's link for that user is matched. Nothing linked: `404`
   `EXT_8028`.
6. Every session and refresh token of the user is revoked, `oauth_external_account_unlinked`
   is recorded, and the answer reports `sessions_revoked`.

## Configuration reads

Binding rows are cached per process for 30 seconds and invalidated after administration
writes. Connection credentials are decrypted in memory from their database ciphertext;
provider secrets are never cached in Redis. Deployment settings control feature gates,
cryptographic keys, state lifetime ceilings and rate limits.
