# Consumer integration cleanup status

Verified locally on 2026-10-05 against the current `magic_auth_client` 1.0.0
source and running api.auth 3.0.0. All four requested backends have been migrated
to the current SDK/API contract. These are working-tree changes; this report
does not certify production deployment or a published SDK release.

| Backend | Integration changes | Focused tests passed |
| --- | --- | ---: |
| [api.magic_llm](/home/andres/PycharmProjects/api.magic_llm) | Canonical upstream access tokens; delegation uses `access_token`; its existing browser cookie and `token` response field remain supported. | 195 |
| [ColWrite-api](/home/andres/PycharmProjects/ColWrite-api) | Username/password registration; verified email enrollment/list/resend/verification routes; canonical SDK credentials; isolated application cookies. | 274 |
| [api.findit.moe](/home/andres/PycharmProjects/api.findit.moe) | Username/password registration; supplied signup email gets sanitized guidance to the verified email flow; current SDK profile/email/availability contracts. | 118 |
| [magic-worlds-api](/home/andres/PycharmProjects/magic-worlds-api) | Provider-owned OAuth init/start/callback; dedicated project key; removed legacy redeem bridge; separate verified email enrollment; provider email required for email credit grants. | 480 |

The suites contain 1,067 distinct affected test cases across the four backends.
HTTP provider and database boundaries are mocked in these suites. Each backend
also passed `git diff --check`. Existing unrelated working-tree changes were
preserved. Editable SDK installs were used without reinstalling the package.

## Magic Worlds configuration and live verification

- Provisioned one dedicated key named `Magic Worlds backend OAuth` for its
  configured active project, owned by the project's existing root creator.
  The API key is scoped to that project; it is not an administrative access JWT.
- Stored the credential only in the backend's ignored private `.env`, with
  permissions `0600`. The backend now explicitly uses `OAUTH_INIT_MODE=api`;
  retired `PROVIDER_INIT_*` settings were removed from that file and Compose.
- Confirmed the enabled Google connection's default group matches the backend's
  configured group. Added the configured BFF callback's exact URL to that
  project's Google binding allow-list, preserving existing entries.
- Migrated api.auth's existing deployment values to `OAUTH_ENABLED`,
  `OAUTH_STATE_PEPPER`, `OAUTH_PROVIDER_SUB_PEPPER`, `OAUTH_EMAIL_HASH_PEPPER`, and
  `OAUTH_FAIL_CLOSED_ON_REDIS_ERROR`. Existing identity pepper values and connection
  encryption keys were preserved. The local development API reloaded its settings.
- The actual SDK against the running API verified the new key's project scope,
  enabled Google provider, OAuth init token issuance, and successful OAuth start
  redirect to Google's authorization endpoint. No Google redirect was followed
  and no end-user account was created.
- The mocked browser-flow regression exercises actual BFF routes, adapter, and
  SDK through callback and single-use delivery exchange. It checks scope
  injection rejection, API key confinement to init, issuer relay, refresh-cookie
  isolation, canonical access-token delivery, and remember-me handling.

Signup with an `email` field, including `null`, is explicitly rejected. Email
enrollment uses `/auth/emails` in ColWrite and Findit and `/user/me/emails` in
Magic Worlds. Validation responses for this retired field do not echo signup
passwords. Magic Worlds no longer treats an email-shaped username as verified
identity when claiming email credit grants.

## Reproduce focused tests

Use each backend's existing virtual environment. The commands below were run
outside the execution sandbox because sandbox restrictions affected local
AnyIO/TestClient execution; the mocked suites do not require live provider or
database access.

### api.magic_llm — 195 passed

Working directory: `/home/andres/PycharmProjects/api.magic_llm`.

```bash
PYTHONDONTWRITEBYTECODE=1 QDRANT_HOST=127.0.0.1 QDRANT_HTTP_PORT=9 timeout 180s \
  .venv/bin/python -m pytest -o addopts= -p no:cacheprovider --no-cov --timeout=20 \
  tests/test_routes/test_auth_contract_strings.py \
  tests/test_routes/test_auth_forwarding.py tests/test_routes/test_auth_json_body.py \
  tests/test_routes/test_auth_production_hardening.py tests/test_routes/test_auth_token_sources.py \
  tests/test_routes/test_auth_profile_sync.py tests/test_routes/test_registration_disabled.py \
  tests/test_routes/test_passive_sync_e2e.py tests/test_routes/test_completions_auth.py \
  tests/test_routes/test_auth_sdk_contract.py tests/test_db/test_auth_profile_sync_unit.py \
  tests/unit/test_const.py -q
```

### ColWrite-api — 274 passed

Working directory: `/home/andres/PycharmProjects/ColWrite-api`.

```bash
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -B -m pytest -p no:cacheprovider -q \
  tests/unit/test_auth*.py tests/unit/test_login*.py tests/unit/test_register_policy.py \
  tests/integration/test_login_flow.py tests/integration/test_register_flow.py \
  tests/integration/test_logout_refresh.py tests/integration/test_profile.py \
  tests/integration/test_auth_cookie_isolation.py tests/integration/test_email_flow.py \
  tests/integration/test_check_availability.py \
  --junitxml=/tmp/colwrite-auth-cleanup-final-tests.xml
```

### api.findit.moe — 118 passed

Working directory: `/home/andres/PycharmProjects/api.findit.moe`.

```bash
PYTHONDONTWRITEBYTECODE=1 timeout -k 2s -s INT 90s \
  .venv/bin/python -m pytest -p no:cacheprovider -q \
  tests/test_auth_boundary.py tests/test_auth_browser_integration.py \
  tests/test_auth_client_integration.py tests/test_auth_registration.py \
  tests/test_auth_session_policy.py tests/test_public_auth_contract.py
```

After the final provider fixture refinements, the 24 SDK integration tests in
`tests/test_auth_client_integration.py` were rerun successfully. These are a
subset of the 118 cases, not additional cases.

### magic-worlds-api — 480 passed

Working directory: `/home/andres/PycharmProjects/magic-worlds-api`.

```bash
PYTHONDONTWRITEBYTECODE=1 timeout 90s \
  .venv/bin/python -m pytest -p no:cacheprovider -o addopts='' -q \
  tests/services/test_auth_adapter_oauth.py tests/test_auth_adapter.py \
  tests/test_auth_adapter_provider_surfaces.py tests/test_auth_refresh_bff.py \
  tests/test_auth_provider_cookie_isolation.py tests/test_auth_password_email.py \
  tests/routes/test_google_provider_init_route.py tests/routes/test_google_oauth_routes.py \
  tests/routes/test_oauth_agnostic_routes.py tests/routes/test_oauth_sdk_browser_flow.py \
  tests/test_startup.py tests/test_runtime_config.py tests/test_config_hygiene.py
```

## Remaining provider database cleanup

The earlier read-only schema review of the configured `magic_auth` database
still found legacy session objects, retired OAuth redeem routines/columns, and
missing canonical schema objects including `v_users`. Eleven users had nonblank
legacy `users.email` data without an unremoved canonical `user_emails` row.
Consumer compatibility and the successful live init/start checks do not resolve
that schema/data migration. No schema cleanup or deletion of that legacy user
data was performed here.
