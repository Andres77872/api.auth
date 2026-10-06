# OAuth runbook

All providers use database connections, encrypted credentials and project bindings.
The [reference](../USAGE/oauth/reference.md) describes the current endpoints.

## Configure a deployment

Keep `OAUTH_STATE_PEPPER`, `OAUTH_PROVIDER_SUB_PEPPER` and `OAUTH_EMAIL_HASH_PEPPER`
stable. The subject pepper keys existing identity links; changing it disconnects those
links. Configure `OAUTH_SECRET_ENCRYPTION_KEY`, its key ID and `OAUTH_SECRET_HMAC_KEY`
before storing provider credentials. Redis is required for state and single-use init tokens.

Apply the canonical schema using `scripts/schema_sync.py --env-file <deployment-env>
--apply --verify` in a maintenance window. Review its dry run first: catch-up replaces
procedures and removes retired email and OAuth bridge columns. It preserves activated
email identities and historical activity rows. Existing opaque sessions must sign in again.

Create the connection and credentials through the root `/admin/oauth/*` API. Bind it to
its project, choose provisioning policy and default user group, and add exact redirect
URIs and return origins. Verify the project's readiness endpoint before enabling traffic.

## Provision Google for development

Set `SETUP_GOOGLE_OAUTH_CLIENT_ID`, `SETUP_GOOGLE_OAUTH_CLIENT_SECRET`,
`SETUP_GOOGLE_OAUTH_REDIRECT_URIS` and `SETUP_GOOGLE_OAUTH_RETURN_ORIGINS` as inputs
to `scripts/provision_google_oauth.py`. Supply `--project-hash` and, for provisioning,
`--default-user-group-hash`. Review its default dry run before using `--apply`.
`scripts/dev_env_setup.py` can provision the project, groups and OAuth binding together.
Runtime OAuth requests use the stored connection, not the setup inputs.

## Diagnose sign-in

Check deployment enablement, provider catalog status, registered adapter, active connection
and credentials, project status, binding flags and both URL allow-lists. Init derives project
scope solely from the user API key. Start consumes the init token once; callbacks consume
state once and verify PKCE plus nonce for OIDC. An expired or replayed token requires a
new sign-in attempt. Activity uses `oauth_*` codes with redacted diagnostics.

## Rotate credentials and keys

Rotate client secrets through the connection credentials endpoint. Keep identity and state
peppers unchanged. For encryption-key rotation, retain old key IDs in
`OAUTH_SECRET_DECRYPTION_KEYS_JSON`, activate the new key and rewrite credentials through
the administration API. Remove an old key only after no ciphertext references it.

## Emergency controls

Disable a project binding or connection for narrow containment. `OAUTH_ENABLED=false`
disables new OAuth starts across the deployment. Review existing session families separately
when an incident requires session revocation.
