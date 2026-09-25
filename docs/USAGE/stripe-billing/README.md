# Stripe billing

`api.auth` keeps a product-agnostic billing catalog, runs Stripe Checkout and Customer Portal
sessions, verifies Stripe webhooks, and exposes the resulting subscription and purchase facts to
trusted backend services. Admins set it up through `/admin/billing`; consuming services call the
`/internal/...` billing routes with a dedicated bearer token; Stripe calls `/webhooks/stripe/...`.
Billing never creates sessions or login credentials, and everything is off by default.

## Key concepts

| Concept | Meaning |
| --- | --- |
| Billing group | The billing unit: one Stripe account, one catalog, one or more projects. A project belongs to at most one active group. Subscriptions are per user and group, so one subscription covers every project in the group; credit purchases stay tied to the project they were bought in |
| Group credentials | The group's Stripe secret key, webhook secret, and optional portal configuration id, stored encrypted and never returned. Every Stripe call for the group uses them |
| Capabilities | Per-group switches (`checkout_enabled`, `portal_enabled`, `provisioning_enabled`, `webhooks_enabled`) that work only together with the global flags |
| Catalog | Subscription plans and credit packages owned by `api.auth`. Creating or repricing an item creates the Stripe Product and Price. `features` is opaque JSON that consumers interpret |
| Facts | Normalized subscription status (per user and group) and purchase status (per purchase), written from Stripe webhooks |
| Opaque refs | `bco-`, `bsub-`, `bpur-`, `bpo-` values returned instead of Stripe ids |
| Plan projection | A small `plan` object (`none`, `free`, `trial`, `active`, `past_due`, `canceled`) on consumer login, refresh, `/auth/validate`, and API-key validation |

## Route families

| Family | Routes | Caller and auth | Bodies |
| --- | --- | --- | --- |
| Admin | 22 under `/admin/billing` | Root or admin user with `admin` or `manage_billing`; credential writes root only | Form for groups, projects, and catalog items; JSON for capabilities, credentials, and import |
| Billing S2S | 6 under `/internal/users/{user_hash}/billing` and `/internal/projects/{project_hash}/billing/catalog` | Backend service with `Authorization: Bearer <BILLING_S2S_BEARER_TOKEN>` | JSON |
| Stripe webhooks | `POST /webhooks/stripe/{billing_group_hash}` and the fallback `POST /webhooks/stripe` | Stripe, verified by `Stripe-Signature` | Raw signed bytes |

Full tables: [reference](reference.md#endpoints).

## Rules and caveats

- Checkout and Portal need both `BILLING_ENABLED` and `STRIPE_BILLING_ENABLED`, plus their own
  `BILLING_*` and `STRIPE_*` flags and a ready group. Health can report Stripe `ready` while they
  answer `503` ([feature flags](reference.md#feature-flags)).
- The S2S routes answer `401` to everything until `BILLING_ENABLED`, `BILLING_S2S_ENABLED`, the
  bearer token, and `BILLING_ID_HMAC_SECRET` are all set.
- Checkout does not check `price_ref` or the plan labels against the catalog. Consumers must
  take them from the catalog read.
- Facts change through webhooks and through the sync worker, which fetches the Stripe object
  and writes it back; the S2S resync route queues such a job for one user
  ([architecture](architecture.md#sync-worker)).
- Checkout and Portal refuse every request with `503` until `BILLING_RETURN_URL_ALLOWLIST`
  lists the consuming apps' origins.
- Remaining limits (unbound `price_ref`, no `stale_after`, unpersisted billing activity) are
  listed under [known gaps](architecture.md#known-gaps).
- `api.auth` never decides benefits, quotas, credit balances, or credit ledgers. Consumers do.
- Platform-wide contracts (User-Agent, body size, error envelope) are in
  [the platform overview](../README.md#platform-wide-contracts).

## In this suite

| Document | Purpose |
| --- | --- |
| [Usage](usage.md) | Set up a group, credentials, catalog, and webhooks; call the S2S routes from a consumer |
| [Scenarios](scenarios.md) | End-to-end lifecycles: subscribe, change plan, cancel, credit packs, refunds, repricing, rotation |
| [Reference](reference.md) | Endpoints, fields, statuses, error responses, rate limits, configuration |
| [Request flow](request-flow.md) | The order of checks and side effects inside each route and the worker |
| [Architecture](architecture.md) | Components, tables, encryption, idempotency, design decisions, known gaps |
| [Troubleshooting](troubleshooting.md) | Symptom, cause, and fix |

## Related

- [Stripe billing runbook](../../RUNBOOKS/stripe-billing.md): deployment order, health checks,
  key rotation, incident response, rollback
- [Patreon link](../patreon-link/README.md): the other provider-facts integration, separate
  routes and tables
- [Errors](../errors.md): the error envelope and code catalog
