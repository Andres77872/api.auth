# API keys scenarios

End-to-end workflows. Each step links to the task in [usage.md](usage.md); fields and error codes
are in [reference.md](reference.md).

## Issue a key and use it from a service

A developer creates a key for a CI job, and the service that receives it checks it on each call.

1. Sign in (or reauthenticate) so the session has recent authentication.
2. [Create the key](usage.md#create-a-key) and store `data.api_key` in the CI secret store.

   ```bash
   curl -X POST "http://localhost:8000/users/api-keys" \
     -H "Authorization: Bearer $TOKEN" \
     -d "project_hash=$PROJECT_HASH" \
     -d "name=ci-runner" \
     -d "expires_at=2027-01-01T00:00:00Z"
   ```

3. The CI job sends the token to the receiving service, which validates it:

   ```bash
   curl -X POST "http://localhost:8000/auth/validate-api-key" \
     -H "X-API-Key: $API_KEY"
   ```

4. The service authorizes the call from `user.user_hash`, `project.project_hash` and
   `permissions`. The result for that `public_id` is cached for `60` seconds, so the service may
   call validation on every request.

## Provision a key for a teammate

An admin creates a key owned by another user in a project the admin administers.

1. Confirm the admin has `manage_users` in the project (root does not need it).
2. [Create the key for the user](usage.md#create-a-key-for-a-user):

   ```bash
   curl -X POST "http://localhost:8000/api-keys" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d "user_hash=$USER_HASH" \
     -d "project_hash=$PROJECT_HASH" \
     -d "name=service-key" \
     -d "expires_at=2027-01-01T00:00:00Z"
   ```

3. Deliver `data.api_key` to the owner over a secure channel. The owner can then see and revoke it
   under `/users/api-keys`.

| Response | Meaning |
| --- | --- |
| `403` `AUTHZ_2001` | The project is outside the admin's scope |
| `403` `AUTHZ_2002` | The admin lacks `manage_users` for another user's key |
| `409` `CONF_5005` | The owner is inactive or does not reach the project, or the project is inactive or archived |

## Audit keys for a user or project

1. List a project's keys, including revoked ones, with owner details:

   ```bash
   curl "http://localhost:8000/api-keys/projects/$PROJECT_HASH?limit=200" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

2. List everything one user holds (an admin sees only keys in projects they administer):

   ```bash
   curl "http://localhost:8000/api-keys/users/$USER_HASH?limit=200" \
     -H "Authorization: Bearer $ADMIN_TOKEN"
   ```

3. For each key, check `is_active`, `expires_at` (a past date means the key no longer validates,
   even in the few minutes before the expiry sweep sets `is_active` to false), `last_used_at` and
   `revoked_at`.
4. Review who created, changed or revoked keys in the activity log: filter on the
   `api_key_created`, `api_key_updated`, `api_key_revoked`, `api_key_reactivated` and
   `api_key_expired` activity types
   (see [Audit logs usage](../audit_logs/usage.md)).

## Rotate a key without downtime

1. [Create the replacement key](usage.md#create-a-key) in the same project and save the new token.
2. Validate the new token with `POST /auth/validate-api-key` before deploying it.
3. Deploy the new token to every consumer.
4. Watch the old key's `last_used_at` until it stops changing.
5. [Revoke the old key](usage.md#revoke-a-key):

   ```bash
   curl -X DELETE "http://localhost:8000/users/api-keys/$OLD_PUBLIC_ID" \
     -H "Authorization: Bearer $TOKEN"
   ```

To give consumers a grace period instead, set a near-future `expires_at` on the old key with `PUT`.
Validation rejects it once that time passes, but the key can still be extended later; revoke it
when the rotation is done.

## Respond to a leaked key

1. Identify the key from what leaked: `public_id` is the part between `sk_` and the last `.`.
2. Revoke it immediately. The owner uses `DELETE /users/api-keys/{key_id}`; an admin uses
   `DELETE /api-keys/{key_id}` with a `revoke_reason`:

   ```bash
   curl -X DELETE "http://localhost:8000/api-keys/$PUBLIC_ID" \
     -H "Authorization: Bearer $ADMIN_TOKEN" \
     -d "revoke_reason=leaked in build log"
   ```

3. The Redis validation entry is dropped, so the next validation fails with
   `API key has been revoked: AUTH_1012`.
4. Issue a replacement key and deploy it (see [rotation](#rotate-a-key-without-downtime)).
5. Review the owner's recent activity in the [audit logs](../audit_logs/usage.md).
