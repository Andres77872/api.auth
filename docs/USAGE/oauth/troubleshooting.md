# OAuth troubleshooting

Symptom, cause and fix, grouped by where the failure shows up. Start with
`GET /admin/oauth/projects/{project_hash}/readiness`: it names the failing configuration
layer. For a failed round trip, filter the activity log by `oauth_*`
and read `reason` and `sub_reason`; public error messages are
neutral on purpose. Never paste codes, states, tokens, secrets or raw e-mails into
tickets; use the `correlation_id`, fingerprints and activity ids.

## Configuration

| Symptom | Cause | Fix |
| --- | --- | --- |
| `GET /auth/oauth/providers` returns an empty list | `OAUTH_ENABLED` off; or no binding in the key's project passes readiness with `login_enabled` on | Check readiness for the project. |
| Every OAuth route fails and readiness reports `oauth_globally_disabled` although `OAUTH_ENABLED=true` | The settings loader rejected the environment: a bounded deployment setting outside its allowed range | Bring ceilings into range and configure the required peppers. See [Deployment settings](reference.md#deployment-settings). |
| Returning users are no longer recognized after a deployment | The provider-sub pepper changed, so no stored identity key matches | Restore the previous `OAUTH_PROVIDER_SUB_PEPPER` value. Never rotate it. |
| Readiness `credentials_not_active` right after `PUT .../credentials` | The `PUT` failed: no `OAUTH_SECRET_*` keys on the server | Set `OAUTH_SECRET_ENCRYPTION_KEY`, `OAUTH_SECRET_ENCRYPTION_KEY_ID` and `OAUTH_SECRET_HMAC_KEY`, then store the secret again. |
| Callbacks answer `502` `EXT_8018` after an encryption-key rotation | The key id the secret was stored under is no longer loaded, so the secret cannot be decrypted for the exchange (`oauth_token_exchange_failed`) | Put the previous key in `OAUTH_SECRET_DECRYPTION_KEYS_JSON`, or re-enter the secret. |
| A change made in the admin API is not visible on another instance | Binding rows are cached per process for `30` seconds | Wait `30` seconds. |

## Init and start

| Symptom | Cause | Fix |
| --- | --- | --- |
| `init` `403` `EXT_8011` | `OAUTH_ENABLED` off, or the binding's `login_enabled` (or the catalog's) off | Turn the switch on, or use the binding only for linking. |
| `init` `404` `EXT_8011` or `503` `EXT_8010` | The binding is disabled, or the connection, credentials, catalog entry or project is not usable; or the `connection` key does not exist in the key's project | Check readiness. |
| `init` `400` `EXT_8012` | The body carries `project_hash`, `user_group_hash`, `project` or `user_group`, lacks `connection` or `return_origin`, or sets `purpose` other than `login` | Send only the documented fields. The project comes from the API key. |
| `init` `400` `EXT_8013` | `return_origin` is not byte-identical to a return origin on the binding | Compare scheme, host, port and trailing slash. `http://localhost:3000` and `http://127.0.0.1:3000` are different origins. |
| `init` `401` | The API key is missing, malformed, revoked or expired | Issue a project-scoped user API key for the project. |
| `start` `401` `EXT_8012` | The init token was already used (a retried request, a double click), is older than `300` seconds, or Redis lost it | Mint a new init token for every attempt. `start` must see the same Redis as `init`. |
| `start` `400` `EXT_8013` | `redirect_uri` is not on the binding, or omitted while the binding lists several | Send the exact redirect URI, or keep one per binding. |
| The provider shows "redirect URI mismatch" | The redirect URI registered at the provider differs from the one on the binding | Make them byte-identical. |
| `start` `503` `EXT_8010` for an `oidc` connection | The discovery document cannot be fetched, its issuer differs from the connection's, or the host resolves to a private address | Fix `discovery_url` or `issuer`; run `POST .../credentials/test`, which reports discovery problems. Private hosts need `OAUTH_ALLOW_PRIVATE_IDP_HOSTS` (development only). |

## Callback

| Symptom | Cause | Fix |
| --- | --- | --- |
| `401` `EXT_8016` | The same `code` and `state` were relayed twice (browser refresh, a retrying proxy) | Relay each callback once; start a new sign-in. |
| `401` `EXT_8014` | The state expired (the user took longer than the state TTL), never existed, or the `oauth_state` cookie sent with the request belongs to another round trip | Start again. If users are slow, raise the binding's `state_ttl_seconds` (at most `600`). |
| `400` `EXT_8014` | The relay dropped `state`, or sent neither `code` nor `error` | Forward every query parameter the provider sent. |
| `400` `EXT_8031` | The user cancelled at the provider | Normal outcome; offer to try again. |
| `502` `EXT_8018` | Wrong client secret, the code expired or was already exchanged, the redirect URI at the token endpoint differs, or the provider answered an error | Test and re-store the secret; check the redirect URI; start a new sign-in. |
| `401` `EXT_8019`–`EXT_8022` | ID token rejected: wrong `client_id`, issuer not configured, clock skew beyond `OAUTH_LEEWAY_SECONDS`, signing key not found after one JWKS refetch | Check the connection's `client_id` and `issuer`; check server time. The flow fails closed; do not weaken validation. |
| `401` `EXT_8020` for Microsoft | The user's tenant is not the connection's tenant or in `restrictions.tenant_ids` | Add the tenant, or use `common` without `tenant_ids`. |
| `401` `EXT_8023` | Connection restriction not met: Google `hosted_domains` or GitHub `orgs` | Adjust the restriction. GitHub `orgs` also needs the `read:org` scope. |
| `401` `EXT_8024` | Login refused; see `sub_reason` below | Depends on the reason. |
| `409` `EXT_8032` | A local account already has this verified e-mail | The user signs in with the existing method, then links the provider. Accounts are never merged. |
| `403` `EXT_8025` | The account does not reach the project fixed at `init`, or the project is inactive or archived | Grant access through groups, or set the binding's `existing_user_policy` to `join_default_group` if signing in here should grant it. |

`sub_reason` values recorded with `oauth_login_denied`:

| `sub_reason` | Meaning | Fix |
| --- | --- | --- |
| `auto_create_disabled` | New identity and the binding's mode is `disabled` or `link_only` | Switch to `auto_create` or `both`, or have the user link from an existing account. |
| `email_collision` | A local account has the e-mail, and the provider did not verify it or its e-mail is administrator-controlled (Microsoft, generic OIDC) | The user signs in locally and links. |
| `email_collision_link_required` | Same, with a provider-verified e-mail; the client saw `EXT_8032` | As above. |
| `no_bound_user_group`, `user_group_not_found` | Auto-create has no usable default group.  | Set the binding's default group . |
| `existing_user_not_active_consumer` | The linked account is inactive, or is a root or admin user | OAuth signs in consumers only. |
| `auto_create_error`, `auto_create_incomplete`, `auto_create_inactive` | Account creation failed in the database | Check the default group is active and the provider type's catalog status is `enabled` with login allowed. |

When the binding's `login_enabled` is off the denial carries `reason`
`login_disabled_for_binding` instead.

## Link, reauth and unlink

| Symptom | Cause | Fix |
| --- | --- | --- |
| `link/start` `401` `EXT_8024` | No recent authentication, `link_enabled` off, or provisioning mode not `link_only`/`both` | Sign in again or run a reauth round trip first; check the binding. |
| `link/start` or `reauth/start` `400` `EXT_8013` | The binding lists several redirect URIs, or several return origins and none was named | Keep one redirect URI per binding; send `{"return_origin": "..."}`. |
| Link callback `409` `EXT_8027` | The identity is linked to another user, or this user already has a different identity for the provider | Unlink the other identity first. The owner is never disclosed. |
| Reauth callback `401` `EXT_8028` | The account chosen at the provider is not the one linked to this user | Sign in at the provider with the linked account. |
| Unlink `409` `EXT_8029` | The account has no usable password; accounts created by auto-create have none | Set a password first. |
| Unlink `401` `EXT_8028` | No recent authentication | Sign in again or reauth, then retry. |
| All sessions ended after an unlink | Expected: unlink revokes every session and refresh token of the user | Sign in again. |

## Administration API

| Symptom | Cause | Fix |
| --- | --- | --- |
| `403` `AUTHZ_2002` on `/admin/oauth/*` | The caller is a consumer, or the session lacks the `admin` permission | Use a root or admin user. Writes to connections, credentials and the catalog need root. |
| `403` `AUTHZ_2003` on a binding route | The admin is not assigned to the project, or the connection belongs to another project | Ask root, or use a shared connection. |
| `POST .../activate` `400` | No active credentials, or the stored configuration no longer validates | Store the secret; run `POST .../credentials/test` to see problems. |
| `PUT .../connections/{connection_hash}` `409` | The change would move the identity namespace of a connection with linked identities | Create a new connection. |
| `DELETE .../connections/{connection_hash}` `409` | Project bindings still use the connection | Delete the bindings first. |
| Binding `PUT` `400` `VAL_3001` | `auto_create` or `both` without a default user group | Send `default_user_group_hash`. |
| Binding `PUT` `409` `CONF_5005` | The default group is inactive or does not reach the project, or `join_default_group` without a group | Fix the group's project-group chain. |
| Binding `PUT` `409` `CONF_5004` | The connection is already bound to the project under another key | Reuse that key, or delete it first. |
| `POST .../urls` `400` | Not `https`, a wildcard, fragment or credentials in a redirect URI; a path or trailing slash in a return origin | Send `scheme://host[:port]` for origins. `http://localhost` works only outside production. |

## Related

- [OAuth runbook](../../RUNBOOKS/oauth.md) — migration, key rotation, emergency switches.
