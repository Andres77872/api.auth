# 11 — Admin Dashboard: Views and Management Mechanisms

The administrative surface for OAuth lives in the `magic-auth-dashboard` client (React 19, TypeScript, Vite, React Router 7, shadcn/Radix + Tailwind 4, the "Meridian" design system). This document specifies the screens, the management mechanisms, and the concrete files to add.

Paths beginning with `magic-auth-dashboard/` refer to that repository; all other paths refer to `api.auth`. Nothing here is implemented, and no file in the dashboard repository was modified during this review.

**Read `magic-auth-dashboard/AGENTS.md` before implementing.** It is the normative convention document for that repository — architecture, transport rules, routing rules, UI conventions and an implementation checklist. It also states explicitly that the backend having OAuth endpoints does not by itself mean they belong in this management UI. Adding an OAuth area is therefore a deliberate product decision, which is the point of this document.

## 1. Why the dashboard is a first-class part of this refactor

Moving OAuth configuration from environment variables to the database changes *who* configures OAuth and *how*. Today an operator edits an `.env` file and restarts the service. Afterwards, an administrator must be able to:

- register an OAuth client (connection) and store its secret safely,
- **assign a project to that connection** and set that project's policy,
- maintain exact redirect-URI and return-origin allow-lists,
- see why a login button is not working.

Without those screens the refactor replaces "edit a file" with "write SQL by hand", which is worse. The dashboard work is a required workstream — with one exception noted in section 10: the bootstrap import in backend Phase 3 is deliberately a server-side command, so the backend can ship and be verified before any UI exists.

There is no existing OAuth, Google, SSO or external-identity surface anywhere in the dashboard today. This is entirely new surface. The nearest external-integration area, Patreon, is read-only operational telemetry with no credential entry.

## 2. The precedent to copy: billing

The dashboard already solves the same shape of problem for Stripe. The OAuth screens should be a close sibling rather than a new invention.

| Concern | Existing implementation |
| --- | --- |
| List of tenant-scoped configuration objects | `magic-auth-dashboard/src/pages/billing/BillingGroupsPage.tsx` |
| Detail page with sub-views | `magic-auth-dashboard/src/pages/billing/BillingGroupDetailsPage.tsx` — `overview` / `projects` / `catalog` / `credentials` |
| Write-only credentials, root-gated | `CredentialsTab` inside that page |
| **Assigning projects to a configuration object** | `magic-auth-dashboard/src/components/features/billing/BillingAttachProjectsModal.tsx` |
| Status helpers | `magic-auth-dashboard/src/components/features/billing/billing-status.ts` |
| Service layer | `magic-auth-dashboard/src/services/billing.service.ts` |

That service file states the convention that matters most here: form-encoded bodies for ordinary writes, **JSON for credentials so secrets never land in URL-encoded request logs**, and root gating in the UI in addition to the server.

The OAuth admin area is a structural clone of the billing admin area, with connections in place of billing groups and bindings in place of group-project attachments.

## 3. Stack conventions that constrain the design

Verified in the repository, and each one differs from what a reader might assume:

| Area | Convention |
| --- | --- |
| Data fetching | **No react-query, no SWR, no Redux.** Custom hooks with `useState` + `useCallback` + `useEffect`, or local state with an `active` cancellation flag and a `version` counter as `reload()`. Hooks own loading and error; components own toasts via `useToast()`. |
| Forms | **No react-hook-form (zero imports), no zod.** Controlled `useState<FormData>` plus `useState<FormErrors>`, a `validateForm()` returning a boolean, and a `handleInputChange(field)` that clears that field's error. Helpers in `magic-auth-dashboard/src/utils/validators.ts`. |
| Transport | `magic-auth-dashboard/src/services/api.client.ts`, a hand-rolled `fetch` wrapper. Cookie auth (`credentials: 'include'`), no bearer injection, one 401 → refresh → retry cycle, normalized error throwing. `post`/`put` send JSON; `postForm`/`putForm` send URL-encoded bodies for FastAPI `Form(...)` endpoints. |
| Endpoints | No central constants file. Each service defines a local `const BASE = '/admin/...'`. Endpoint strings in page components are forbidden. |
| URLs | **Flat.** Sub-views are `?tab=` query state, not nested routes. |
| Payload casing | `snake_case` in both directions; the dashboard does not camel-case API payloads. |
| Styling | Tailwind semantic tokens only (`bg-card`, `text-muted-foreground`, `border-border`, `*-subtle` status tints) — never hard-coded colours. `cn()` for composition, Lucide icons, `font-mono` for hashes and timestamps, sentence case, buttons are verbs, borders rather than shadows, status pills as quiet tints. |

## 4. Information architecture

```text
/oauth                       Connections list        (admin reads, root writes)
/oauth/:connectionHash       Connection detail, sub-views via ?tab=
       ?tab=overview         provider type, status, scopes, restrictions, namespace
       ?tab=projects         bindings: which projects use this connection   <-- assignment
       ?tab=credentials      write-only client secret, fingerprint, test / rotate (root)
       ?tab=activity         recent oauth_* admin activity for this connection

/projects/:projectHash       existing page, gains ?tab=sign-in
       ?tab=sign-in          this project's bindings, readiness, URL allow-lists

/system                      existing page, gains a provider-catalog panel (root)
```

Two entry points on purpose, because there are two mental models:

- **Connection-first** ("I have a Google client, which projects use it?") — the `/oauth` area, mirroring Billing.
- **Project-first** ("how do people sign in to this project?") — a tab on the existing project detail page. This is where most day-to-day work happens, and it answers the "why is the button broken" question.

Both read and write the same two objects; neither duplicates the other.

## 5. Screens

### 5.1 Connections list — `/oauth`

Built on the shared `DataView` component (table/grid toggle, local search, skeleton and empty states). Columns: display name, provider type badge, status (`draft` / `active` / `disabled` / `archived`), credential status (`absent` / `active` / `rotating` / `revoked`), bound-project count, owner project or "platform", last updated. `FilterBar` for provider type and status. Actions: **New connection** (root), row click to detail. The empty state explains what a connection is.

### 5.2 Connection detail — `/oauth/:connectionHash`

**Overview.** Non-secret configuration: provider type, display name, status, scopes, restrictions (hosted domains for Google, tenant ids for Microsoft, organisations for GitHub). The identity namespace is read-only with an explanatory tooltip. For the generic `oidc` type only, the endpoint fields (issuer, discovery, authorize, token, JWKS, userinfo) are editable; for built-in types they display as "provided by the adapter".

Once any identity is linked, the namespace-affecting inputs must be disabled with a visible reason rather than left editable for the server to reject — changing issuer, tenant or team changes who the connection's subjects are (risk R-07).

**Projects.** The assignment mechanism, section 6.

**Credentials.** Section 7.

**Activity.** Filtered view of the new `oauth_connection_*` activity types, reusing `magic-auth-dashboard/src/components/features/audit`.

### 5.3 Project sign-in tab — `/projects/:projectHash?tab=sign-in`

Per binding: connection, login-enabled switch, provisioning mode, default user group, existing-user policy, and the two URL allow-lists, plus the readiness panel (section 8) and a link to the connection. Primary action: **Enable a provider for this project**, the mirror image of 5.2's projects tab.

### 5.4 Provider catalog panel — `/system`

Root-only. One row per provider type: code, display name, protocol, whether an adapter is registered in the running backend, status, and the login/link capability flags. This is the global kill switch. A type enabled in the catalog with no registered adapter must render as an error state, because that mismatch is what the backend's start-up assertion guards against.

## 6. Assignment mechanism: binding a project to a connection

This is the mechanism the refactor most needs, and it has the closest existing precedent. The `.dev/sdd/changes/group-based-project-assignment-ux` specification in the dashboard repository already settled the interaction pattern for this class of problem: **a modal with a searchable, scrollable checkbox list** — not a transfer list, not a multi-select combobox.

### From the connection side

The **Projects** tab lists bound projects with provisioning mode and enabled state. **Assign projects** opens a modal modelled directly on `BillingAttachProjectsModal`:

- `Dialog` at large size, search `Input` with a leading icon, debounced server-side search with an instant client-side overlay;
- a scrollable bordered list of `divide-y` rows, each row fully clickable with a `Checkbox` inside a `stopPropagation` wrapper;
- `LoadingSpinner` and `EmptyState` branches;
- a footer action labelled with the selection count;
- submission as a **sequential loop of per-item calls**, accumulating assigned / conflict / failed counters, with a per-row result `Badge`, one aggregate toast per bucket, and the modal staying open if anything failed.

One deliberate difference from billing: a project may hold several bindings (Google *and* GitHub), whereas a project belongs to exactly one billing group. The conflict case is therefore a project already bound to a *different connection of the same provider type*, which `uk_project_oauth_key` in [06-data-model.md](06-data-model.md) forbids. That deserves its own row badge — "already uses another Google connection" — rather than a generic failure, exactly as the billing modal distinguishes its 409.

Newly created bindings must use safe defaults: `enabled: false`, `provisioning_mode: 'disabled'`, `existing_user_policy: 'deny'`, no URLs. A binding cannot work until its redirect URI and return origin are set, so the result summary must say so and link to each new binding — otherwise administrators will assume assignment alone enabled sign-in.

### From the project side

A single-select dialog listing connections available to this project (platform-owned plus project-owned), grouped by provider type, showing each connection's credential status so nobody binds a connection whose secret was never set. `SearchableSelect` or the radio-list variant in `magic-auth-dashboard/src/components/features/users/AssignProjectModal.tsx` both fit.

Removal goes through `ConfirmDialog` with a warning that users signing in through that provider will lose access, following the established pattern for access-removing actions.

### The binding editor

Provisioning mode and existing-user policy change account behaviour, so both need explanatory copy rather than bare enum labels:

| Field | Presentation |
| --- | --- |
| `provisioning_mode` | Four radio options with one-line consequences, from `disabled` to `both`. |
| `default_user_group_id` | `Select` populated from the existing `GET /projects/{project_hash}/groups`. Required before `auto_create` or `both` can be chosen; block that combination client-side, since the backend rejects it anyway. |
| `existing_user_policy` | *Deny* (a user known from another project is refused) or *join default group* (they are added to this project's default group). Default deny; the join option needs a short warning that it grants access to an account created elsewhere (risk R-11). |
| `enabled`, `login_enabled`, `link_enabled` | `Switch` controls, with the effective state as a computed badge — the real answer is the AND of global, catalog, connection and binding flags. |

### URL allow-lists

One row per URL with add and remove, never a free-text comma-separated field — that is how the backend stores them and the reason is exact matching. Validate on entry: HTTPS outside development, no wildcards, no fragments, and for origins scheme + host + optional port only. Render each URI with the existing `CopyableId` / `CopyButton` component: the value must be pasted byte-identically into the provider's console, and mismatch there is the most common setup failure (risk R-13).

## 7. Credentials: write-only secrets in the UI

Follow `CredentialsTab` in the billing details page closely. Its shape, verified:

1. **Never render a secret.** A read-only status grid shows `credential_status` as a `Badge`, "secret key: set ({fingerprint}) | not set", and "set at". There is no reveal control, because the server cannot return the value.
2. **Root gate as a render-level branch.** Non-root users see a warning panel explaining that only root may set or rotate credentials — the form fields are not rendered at all, rather than disabled.
3. **JSON bodies** for every credentials call (`apiClient.put` / `apiClient.post`, never the `Form` variants).
4. **Secret inputs are `type="password"`, never seeded from the server**, and cleared on success.
5. **Test before save.** A "Test connection" button calls the non-persisting probe and renders an inline result line. This is the main defence against a mistyped secret breaking sign-in for a whole project.
6. **One save button whose verb flips**: "Save credentials" when absent, "Rotate credentials" when active, mapping to the set and rotate endpoints. The rotate path should explain that the old secret stops working immediately.
7. **Apple** additionally needs the `.p8` signing key plus team id and key id. The file contents must never be logged, retained in state after submission, or echoed back.
8. A footer disclosure stating that secrets are encrypted server-side and never returned — only presence flags and fingerprints are shown.

The "secret shown once" modal used for API keys (`ApiKeyRevealModal`) is deliberately **not** needed here: OAuth client secrets originate at the provider, so the dashboard only ever writes them.

## 8. Readiness and diagnostics

The effective state is an AND across four layers plus external configuration, so the dashboard should answer "why is sign-in not working?" in one panel, driven by the readiness endpoint in [06-data-model.md](06-data-model.md):

| Check | Failure message |
| --- | --- |
| Global `OAUTH_ENABLED` | OAuth is disabled for the whole deployment. |
| Catalog status and adapter registered | Provider type is disabled, or the running backend has no adapter for it. |
| Connection status | Connection is draft, disabled or archived. |
| Credential status | No client secret stored, or credentials revoked. |
| Binding enabled | Provider is not enabled for this project. |
| Redirect URI present | No redirect URI configured. |
| Return origin present | No return origin configured. |
| Default group set and reaching the project | Auto-create is on but the default group is missing, inactive, or does not reach this project. |

That last check is the structural fix for the failure the backend names as the most common cause of a post-redirect 401 (gap G-04), surfaced before a user hits it rather than after.

## 9. Files to add, and registration points

**New files**, all under `magic-auth-dashboard/src/`:

```text
types/oauth.types.ts                         connection, binding, credential status, catalog DTOs
services/oauth.service.ts                    class + singleton, BASE = '/admin/oauth'
pages/oauth/OAuthConnectionsPage.tsx         list
pages/oauth/OAuthConnectionDetailsPage.tsx   detail, ?tab= sub-views
pages/oauth/index.ts                         barrel
components/features/oauth/OAuthAssignProjectsModal.tsx
components/features/oauth/OAuthConnectionFormModal.tsx
components/features/oauth/OAuthCredentialsTab.tsx
components/features/oauth/OAuthBindingEditor.tsx
components/features/oauth/OAuthAllowedUrlList.tsx
components/features/oauth/OAuthReadinessPanel.tsx
components/features/oauth/ProjectSignInTab.tsx
components/features/oauth/oauth-status.ts    badge variants, conflict detection
components/features/oauth/index.ts           barrel
hooks/useOAuthConnections.ts                 list + mutations, modelled on hooks/useApiKeys.ts
```

**Registration points.** Each must be edited; all are places the billing or Patreon features already occupy. The last two are easy to miss and both are required:

| File | Edit |
| --- | --- |
| `magic-auth-dashboard/src/utils/routes.ts` | Add `OAUTH: '/oauth'` to `ROUTES`; add a `NavItem` to `NAVIGATION_SECTIONS` (the structure the sidebar actually renders — `NAVIGATION_ITEMS` is the legacy flat list). Shape: `{ id, label, path, icon, allowedUserTypes }` with `allowedUserTypes: ['root', 'admin']`. |
| `magic-auth-dashboard/src/App.tsx` | Two routes inside the `AdminRoute` block: `oauth` and `oauth/:connectionHash`. |
| `magic-auth-dashboard/src/components/navigation/NavigationItem.tsx` | `icon` is a **string key** resolved by a `getIcon` switch. A new icon needs a new case; reusing an existing key avoids this edit. |
| `magic-auth-dashboard/src/utils/permissions.ts` | If any route is root-only, add its prefix to `ROOT_ONLY_ROUTE_PREFIXES`. The conventions require this to stay in sync with the guards. |
| `magic-auth-dashboard/src/pages/index.ts` | Export the new pages. |
| `magic-auth-dashboard/src/services/index.ts` | Export `oauthService`. |
| Existing project details page | Add the `sign-in` tab. |
| Existing system page | Add the provider catalog panel. |

Types mirror the backend DTOs exactly, in `snake_case`, as the billing types do.

## 10. Sequencing against the backend plan

The dashboard follows the backend phases in [07-migration-plan.md](07-migration-plan.md). It cannot start before the admin API exists in Phase 3, and it need not be complete for Phase 3 to ship, because the bootstrap import is a server-side command.

| Backend phase | Dashboard work |
| --- | --- |
| 0–2 | None. No configuration surface changes. |
| **3** | The bulk: types, service, hook, connections list and detail, credentials tab, assignment modal, project sign-in tab, readiness panel, system catalog panel. Ships shortly **after** the backend phase. |
| 4 | Surface the binding's `init_mode` and where the project credential for the init API is managed. If project-scoped API keys are reused, link to the existing tokens area rather than duplicating it. |
| 5 | The provider-type selector becomes genuinely multi-valued: provider icons, per-type restriction editors, the Apple signing-key input, per-type endpoint editing for generic OIDC. |
| 6 | Nothing required. Optionally drop Google-specific labels in favour of connection display names. |
| 7 | Project-admin-scoped self-service views, if that decision is taken (open question 3). |

A practical consequence for Phase 5: build the connection form with per-provider-type field branching from the start, even while Google is the only type, or the form will need restructuring exactly when a second provider is being added.

## 11. Permissions in the UI

`AuthContext` is the single source, consumed through `useAuth()`, `useUserType()` and `usePermissions()`. Gate navigation with `allowedUserTypes: ['root', 'admin']`, routes with the existing `AdminRoute` / `RootOnlyRoute` guards, and secret-accepting controls with a plain `isRoot` branch, as `CredentialsTab` does. Note that `usePermissions().isAdmin` is true for root as well.

Server-side gating remains authoritative. The dashboard's own conventions are emphatic that hidden navigation, disabled controls and client-side permission checks are UX only and never authorization.

If self-service for project administrators is adopted later (open question 3), the connection list must be filtered to the projects the current user administers, and creating a generic `oidc` connection must stay root-only regardless, because of the mix-up and SSRF surface described in [04-research.md](04-research.md).

## 12. Testing

Vitest with Testing Library, colocated `__tests__` folders, `vi.mock` for hooks and services, rendering inside `MemoryRouter`. `magic-auth-dashboard/src/routes/__tests__/patreon-navigation.test.ts` is the established template for "a new section is reachable and correctly role-gated" and should be copied for `/oauth`.

Coverage worth having:

- Navigation and route guards: the section appears for admin and root, and root-only surfaces are refused for admin.
- Assignment modal: search, multi-select, the same-provider-type conflict badge, bucketed toasts, modal stays open on partial failure, refetch on success.
- Credentials tab: no secret is ever rendered; non-root sees the warning panel instead of the form; test-before-save; inputs cleared after submit.
- Binding editor: `auto_create` blocked until a default group is chosen; the warning on the join-default-group policy.
- URL list: validation rejects wildcards, fragments and plain HTTP outside development.
- Readiness panel: each failing layer produces its own message and the AND across layers is computed correctly.

## 13. Open questions specific to the UI

1. **Where does the OAuth area live in the navigation?** A top-level `/oauth` entry mirrors Billing and is easy to find; nesting under System or Projects keeps the sidebar shorter. Recommendation: top-level in the `operations` section, next to Billing and Tokens, because it is an object administrators manage repeatedly rather than a one-off system setting.
2. **Naming.** [09-open-questions.md](09-open-questions.md) item 12 leaves "connection" versus "identity provider" open. The UI label should follow the schema decision so screens, API and database agree.
3. **Does the project sign-in tab allow creating a connection inline?** Convenient for the first provider on a new project, but it places a root-only action inside an admin-level screen. Recommendation: no — link to `/oauth`, and show a clear message when no connection is available.
