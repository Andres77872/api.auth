# Client integration guide

How to build browser, mobile and server clients on top of the `/auth` API: which transport to use,
what the server sets, where to keep tokens, how to refresh safely, and how to react to errors. The
request and response contract of each endpoint is in [Authentication](authentication-usage-cases.md);
this page links there instead of repeating it.

## Choose a transport

| Client | Transport | Why |
| --- | --- | --- |
| Browser app on the **same site** as the API (for example `app.example.com` and `api.example.com`) | HttpOnly cookies set by the API | Tokens never reach JavaScript; the browser sends and rotates them |
| Browser app on **another site**, or a server-rendered web app | A backend-for-frontend (BFF) that holds the tokens and uses bearer mode | The auth cookies are `SameSite=Strict` and are not sent cross-site |
| Mobile and desktop apps | `Authorization: Bearer <access_token>`, refresh token in OS secure storage | No cookie jar to rely on |
| Scripts, CLIs, back-end services acting as a user | Bearer | Same as mobile |
| A service that receives a user's API key | `POST /auth/validate-api-key` with `X-API-Key` | Resolves the key's owner, project and permissions; the key is not a general credential ([details](authentication-usage-cases.md#validate-an-api-key)) |

Every sign-in path (password login, platform login, registration, OAuth callback) returns the token
pair in the JSON body **and** sets it as cookies, so one API serves both styles.

## What the server sets

| Cookie | Carries | `Path` | `Max-Age` | Attributes |
| --- | --- | --- | --- | --- |
| `session_token` | Access token | `/` | Access-token lifetime: `900` seconds by default (`JWT_ACCESS_TOKEN_EXPIRE_MINUTES`) | `HttpOnly`, `Secure`, `SameSite=Strict`, host-only (no `Domain`) |
| `refresh_token` | Refresh token | `/auth` | Remaining family lifetime: `259200` seconds (72 hours) after each rotation, or the seconds left of the 30-day `remember_me` window | `HttpOnly`, `Secure`, `SameSite=Strict`, host-only |

- Both cookies are set by `POST /auth/login`, `/auth/platform/login`, `/auth/register` (when it
  issues tokens), `/auth/refresh`, `/auth/switch-project` and the OAuth callback.
- `POST /auth/logout` clears both. A failed refresh does **not** clear them; the client must treat
  the session as over.
- The access cookie expires with the access token, so after 15 minutes the browser stops sending
  it and protected calls return `401` until the client refreshes.
- `session_token` is a legacy name: the cookie holds the access token, never a refresh credential.
- When a request carries both `Authorization: Bearer` and the cookie, the header wins.

Token lifetimes, rotation and revocation rules are in
[Authentication: tokens and sessions](authentication-usage-cases.md#tokens-and-sessions).

## Browser requirements

- **Same site.** `SameSite=Strict` cookies are sent only when the page and the API share a
  registrable domain. `app.example.com` → `api.example.com` works; `app.example.net` →
  `api.example.com` does not, whatever CORS allows. Use a BFF in that case.
- **HTTPS.** `Secure` cookies are stored and sent only over HTTPS. Chromium- and Firefox-based
  browsers make an exception for `http://localhost`; a plain-HTTP LAN IP or hostname never receives
  the cookies (use HTTPS or bearer mode there).
- **CORS with credentials.** When the page origin differs from the API origin (another subdomain or
  port), add the exact origin to `ALLOWED_ORIGINS` and call `fetch` with `credentials: 'include'`.
  The API answers listed origins with `Access-Control-Allow-Credentials: true` and allows every
  method and request header.
- **Root path.** The refresh cookie is scoped to `Path=/auth`. Serve the API at the root of its
  origin; behind a proxy that adds a prefix (`/api/auth/refresh`), the browser never sends the
  refresh cookie unless the proxy rewrites cookie paths.
- **User-Agent.** Browsers send their own. Do not set it in `fetch`: some browsers ignore it and
  others turn the request into a preflighted one. Non-browser clients must send one on every
  request.

> [!NOTE]
> The API has no CSRF-token mechanism. Cross-site request forgery is blocked by `SameSite=Strict`
> (cookies are not attached to requests started from another site) and CORS keeps other origins
> from reading responses. `SameSite` does not stop requests from a sibling subdomain of the same
> site, so do not host untrusted content under the API's registrable domain.

## Token storage

| Client | Access token | Refresh token |
| --- | --- | --- |
| Same-site browser app | `session_token` cookie only; ignore the copies in the JSON body | `refresh_token` cookie only |
| BFF or server-rendered app | Server memory or its session store; the browser gets only the BFF's own session cookie | Server-side session store, encrypted at rest |
| Mobile and desktop | Memory | iOS Keychain, Android Keystore, or the OS credential store |
| Scripts and services | Memory | Secret manager, or a file readable only by the service account |

Never put tokens in `localStorage`, `sessionStorage`, URLs, logs, crash reports or analytics events.
The same applies to user API keys: treat them like passwords.

## Refresh strategy

- **Refresh on `401`, once.** When a protected call returns `401`, refresh and retry the call once.
  If the retry fails too, stop: the session is over.
- **Or refresh ahead of time.** Every token-pair response has `expires_at`; refreshing about a
  minute before it avoids failed calls. Keep the `401` path as the fallback.
- **One refresh at a time per family.** Two concurrent refreshes present the same refresh token:
  within the replay grace (default `10` seconds) the loser gets `401 AUTH_1022` and must use the
  winner's pair; after it, the server treats the second use as theft (`AUTH_1015`) and revokes the
  family. Funnel refreshes through a single in-flight promise, lock or queue.
- **Swap both tokens every time.** Each refresh or project switch invalidates the previous access
  token immediately, not at its expiry. Calls already in flight with the old token get `401`; retry
  them with the new one.
- **One family per client instance.** Do not share a token pair between processes, devices or
  users: independent refreshes collide and trigger reuse detection. Log in once per instance, or
  make one component responsible for refreshing.
- **Plan for the end.** A default family ends 72 hours after its last refresh; a `remember_me`
  family ends 30 days after sign-in regardless of activity. Then a new login is needed.
- **Project switching needs a fresh sign-in.** `/auth/switch-project` works only within 300 seconds
  of the sign-in; after that it returns `401 AUTH_1008` and refreshing does not help. Offer a login
  with the target `project_hash` instead.

What to do when `POST /auth/refresh` fails:

| Code | Meaning | Client action |
| --- | --- | --- |
| `AUTH_1022` | This refresh token was rotated seconds ago by another request | Use the newer pair (a browser already has it as cookies) and retry the original call |
| `AUTH_1015`, `AUTH_1017` | Reuse detected, or the family was revoked | Clear local state and go to login |
| `AUTH_1013`, `AUTH_1014`, `AUTH_1019` | No, invalid or expired refresh token | Go to login |
| `AUTH_1016`, `AUTH_1018` | Cookie and form value differ, or an access token was sent | Fix the client; send only the current refresh token |
| `AUTH_1020` | The user or project is no longer valid | Go to login; the user may have lost access |

## Handling errors

Errors use the [standard error envelope](errors.md#standard-error-envelope)
`{"status": "error", "error": {"code", "category", "message"}}`, except the middleware bodies listed
under [other error bodies](errors.md#other-error-bodies). Branch on `error.code` and the HTTP
status, never on the message text; `error.details` is not returned in production except for
request-validation failures and rate limits.

| Status | Typical codes | Client action |
| --- | --- | --- |
| `400` | `VAL_3001`, `VAL_3002`, `VAL_3007` | Fix the input. For `VAL_3007`, show general password guidance; the reasons are not returned in production. |
| `401` on a protected route | `AUTH_1003` | Refresh once and retry once |
| `401` on login or password change | `AUTH_1001` | Show one generic "invalid credentials" message; do not refresh |
| `401` on project switch | `AUTH_1008` | Ask the user to sign in again for that project |
| `401` on refresh | `AUTH_1013` to `AUTH_1022` | See the refresh table above |
| `403` | `AUTHZ_2001`, `AUTHZ_2002`, `AUTHZ_2003` | Show "access denied"; refreshing does not change it |
| `409` | `CONF_5001`, `CONF_5002` | Ask for another username or email |
| `413`, `422` | none: body is `{"status": "Error", "action": "..."}` | Request too large, or `User-Agent` missing; fix the client |
| `429` | `INT_7005` | Wait for the `Retry-After` seconds before trying again |
| `5xx` | `INT_*`, `DB_*` | Retry idempotent calls with backoff |

Public email routes (`/auth/email/verify`, `/auth/password/forgot`, `/auth/password/reset`) answer
`202` whether or not the account or link exists. Show the same neutral message for every `202`
and never tell the user whether an address is registered.

## Integration patterns

### Same-site browser app

1. Sign in with `fetch(..., { credentials: 'include' })` and a form body; keep only the non-secret
   parts of the response (`user`, `project`, `accessible_projects`, `expires_at`).
2. Call protected routes with `credentials: 'include'`; the browser attaches `session_token`.
3. On `401`, call `POST /auth/refresh` with no body (the `refresh_token` cookie is sent because the
   path starts with `/auth`), then retry once.
4. On startup, call `GET /auth/validate` to learn whether a session exists; it refreshes through
   step 3 when the access cookie has already expired.
5. Log out with `POST /auth/logout`. If it returns `401` because the access cookie expired, refresh
   first and log out again so the family is revoked, then clear local state either way.

### Backend-for-frontend

The BFF signs in with bearer mode, stores the pair server-side keyed by its own session, and
forwards calls with `Authorization: Bearer`. It must serialize refreshes per user session. When it
relays `POST /auth/password/forgot` or the email routes under `/users/me/emails`, it should send the
browser origin in `X-Public-Base-Url` so emailed links point back to that frontend (the origin must
be listed in `ALLOWED_ORIGINS`); otherwise the links use the API's own origin unless the deployment
pins `AUTH_EMAIL_PUBLIC_BASE_URL`.

### Mobile and desktop apps

Send `Authorization: Bearer <access_token>` on every call and a descriptive `User-Agent`. Keep the
refresh token in secure storage, refresh through one serialized path, and persist the new refresh
token before using the new access token, so a crash never leaves the app holding a rotated-away
token. Clear both on logout or on a terminal refresh error.

### Scripts and services

Use the same bearer flow as mobile apps. A service that calls the API on behalf of many users needs
one token pair per user session; a service that only needs to verify a user's API key calls
`POST /auth/validate-api-key` with `X-API-Key` and no `Authorization` header (sending both returns
`400`).

### Email links

The emailed activation and reset links open `/auth/email/verify?token=...` and
`/auth/password/reset?token=...` on your frontend. Read the token from the query string once, remove
it from the address bar with `history.replaceState`, and POST it as JSON. A `202` does not say whether
the link was valid: after a reset, tell the user to log in with the new password and to request a
new link if that fails. Neither route signs the user in.

## Code examples

The examples cover the endpoints in [Authentication](authentication-usage-cases.md) and read
response fields at the top level of the JSON body (`access_token`, `user`, `error.code`).

### Browser client (TypeScript)

Cookie mode for a same-site app. Tokens in response bodies are deliberately ignored.

```typescript
// authClient.ts
export const API = 'https://api.example.com';

export class ApiError extends Error {
  constructor(
    readonly status: number,
    readonly code: string | undefined,
    message: string,
    readonly retryAfter: number | null = null,
  ) {
    super(message);
  }
}

export async function toApiError(response: Response): Promise<ApiError> {
  let body: any = null;
  try {
    body = await response.json();
  } catch {
    // 413 and 422 middleware responses do not use the standard envelope
  }
  const retryAfter = response.headers.get('Retry-After');
  return new ApiError(
    response.status,
    body?.error?.code,
    body?.error?.message ?? body?.action ?? `HTTP ${response.status}`,
    retryAfter ? Number(retryAfter) : null,
  );
}

// 401 codes that a refresh cannot fix: wrong password, and "sign in again" for project switching.
const NOT_REFRESHABLE = new Set(['AUTH_1001', 'AUTH_1008']);

let refreshing: Promise<void> | null = null;

/** Rotate the pair once, however many callers ask at the same time. */
export function refreshSession(): Promise<void> {
  if (!refreshing) {
    refreshing = (async () => {
      const response = await fetch(`${API}/auth/refresh`, { method: 'POST', credentials: 'include' });
      if (response.ok) return;
      const error = await toApiError(response);
      if (error.code === 'AUTH_1022') return; // another tab just rotated; its cookies are already set
      throw error; // the session is over: send the user to login
    })().finally(() => {
      refreshing = null;
    });
  }
  return refreshing;
}

/** fetch() for protected routes: sends the cookies, refreshes once on 401 and retries once. */
export async function apiFetch(path: string, init: RequestInit = {}): Promise<Response> {
  const send = () => fetch(`${API}${path}`, { ...init, credentials: 'include' });
  const response = await send();
  if (response.status !== 401) return response;
  const { code } = await toApiError(response.clone());
  if (code && NOT_REFRESHABLE.has(code)) return response;
  await refreshSession();
  return send();
}

export interface ProjectRef {
  project_hash: string;
  project_name: string;
}

export interface LoginResult {
  user: { user_hash: string; username: string; email: string | null; user_type: string | null };
  project: ProjectRef | null;
  accessible_projects: ProjectRef[];
  expires_at: string;
  refresh_expires_at: string;
  remember_me: boolean;
}

async function postForm(path: string, fields: Record<string, string>): Promise<any> {
  const response = await fetch(`${API}${path}`, {
    method: 'POST',
    body: new URLSearchParams(fields), // sent as application/x-www-form-urlencoded
    credentials: 'include',            // lets the browser store the Set-Cookie headers
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

/** project_hash is required for every user type on /auth/login. */
export function login(username: string, password: string, projectHash: string, rememberMe = false): Promise<LoginResult> {
  const fields: Record<string, string> = { username, password, project_hash: projectHash };
  if (rememberMe) fields.remember_me = 'true';
  return postForm('/auth/login', fields);
}

/** Root and admin only; the session has no project. */
export function platformLogin(username: string, password: string, rememberMe = false): Promise<LoginResult> {
  const fields: Record<string, string> = { username, password };
  if (rememberMe) fields.remember_me = 'true';
  return postForm('/auth/platform/login', fields);
}

/** Signs the new consumer in when the group reaches a project (token fields are null otherwise). */
export function register(username: string, password: string, userGroupHash: string, email?: string) {
  const fields: Record<string, string> = { username, password, user_group_hash: userGroupHash };
  if (email) fields.email = email; // stored only; activate it via /users/me/emails before using it to log in
  return postForm('/auth/register', fields);
}

/** Works within 300 seconds of sign-in; afterwards throws AUTH_1008: call login() with projectHash. */
export async function switchProject(projectHash: string): Promise<{ project: ProjectRef; user_groups: string[] }> {
  const response = await apiFetch('/auth/switch-project', {
    method: 'POST',
    body: new URLSearchParams({ project_hash: projectHash }), // the refresh cookie is sent automatically
  });
  if (!response.ok) throw await toApiError(response);
  return response.json();
}

export async function changePassword(currentPassword: string, newPassword: string): Promise<void> {
  const response = await apiFetch('/auth/password/change', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify({ current_password: currentPassword, new_password: newPassword }),
  });
  // AUTH_1001 wrong current password, VAL_3007 weak password, INT_7005 rate limit (see retryAfter)
  if (!response.ok) throw await toApiError(response);
}

export async function logout(): Promise<void> {
  try {
    // apiFetch refreshes first if the access cookie already expired, so the family is revoked.
    await apiFetch('/auth/logout', { method: 'POST' });
  } catch {
    // The refresh token is gone too: nothing is left to revoke.
  }
}

/** Always resolves on 202, which does not reveal whether the account exists. */
export async function requestPasswordReset(identifier: string, idempotencyKey = crypto.randomUUID()): Promise<void> {
  // Reuse the same idempotencyKey when retrying the same submission.
  const response = await fetch(`${API}/auth/password/forgot`, {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'Idempotency-Key': idempotencyKey,
      'X-Public-Base-Url': location.origin, // emailed link returns here; must be in ALLOWED_ORIGINS
    },
    body: JSON.stringify({ email_or_username: identifier }),
  });
  if (response.status !== 202) throw await toApiError(response); // 400 VAL_3002 or 429 INT_7005
}

/** Call once when an emailed link page loads: returns the token and strips it from the address bar. */
export function takeLinkToken(): string {
  const token = new URLSearchParams(location.search).get('token') ?? '';
  history.replaceState(null, '', location.pathname); // keep the link token out of history and referrers
  return token;
}

async function postLinkToken(path: string, body: Record<string, string>): Promise<void> {
  const response = await fetch(`${API}${path}`, {
    method: 'POST',
    headers: { 'Content-Type': 'application/json' },
    body: JSON.stringify(body),
  });
  if (response.status !== 202) throw await toApiError(response); // 400 or 429; 202 covers every link outcome
}

/** Page for /auth/email/verify?token=... */
export function activateEmail(token: string): Promise<void> {
  return postLinkToken('/auth/email/verify', { token });
}

/** Page for /auth/password/reset?token=...; a 400 VAL_3007 rejects the password, so keep the token for a retry. */
export function resetPassword(token: string, newPassword: string): Promise<void> {
  return postLinkToken('/auth/password/reset', { token, new_password: newPassword });
}
```

### Python client (requests)

Bearer mode with in-memory tokens, one retry after a refresh, and a lock so concurrent threads
never rotate the same refresh token twice.

```python
import http.cookiejar
import os
import threading
from typing import Any, Optional

import requests

NOT_REFRESHABLE = {"AUTH_1001", "AUTH_1008"}


class ApiError(Exception):
    def __init__(self, response: requests.Response) -> None:
        try:
            error = response.json().get("error") or {}
        except ValueError:
            error = {}
        self.status = response.status_code
        self.code: Optional[str] = error.get("code")
        self.retry_after = response.headers.get("Retry-After")
        super().__init__(error.get("message") or f"HTTP {response.status_code}")


class AuthClient:
    def __init__(self, base_url: str, user_agent: str = "my-app/1.0") -> None:
        self.base_url = base_url.rstrip("/")
        self.http = requests.Session()
        self.http.headers["User-Agent"] = user_agent
        # Bearer mode: ignore Set-Cookie so a cookie jar never competes with the stored tokens.
        self.http.cookies.set_policy(http.cookiejar.DefaultCookiePolicy(allowed_domains=[]))
        self.access_token: Optional[str] = None
        self.refresh_token: Optional[str] = None
        self._lock = threading.RLock()

    def _store(self, body: dict) -> dict:
        with self._lock:
            self.access_token = body.get("access_token")
            self.refresh_token = body.get("refresh_token")
        return body

    def _post_form(self, path: str, data: dict, headers: Optional[dict] = None) -> dict:
        response = self.http.post(f"{self.base_url}{path}", data=data, headers=headers)
        if not response.ok:
            raise ApiError(response)
        return response.json()

    def login(self, username: str, password: str, project_hash: str, remember_me: bool = False) -> dict:
        data = {"username": username, "password": password, "project_hash": project_hash}
        if remember_me:
            data["remember_me"] = "true"
        return self._store(self._post_form("/auth/login", data))

    def platform_login(self, username: str, password: str, remember_me: bool = False) -> dict:
        data = {"username": username, "password": password}
        if remember_me:
            data["remember_me"] = "true"
        return self._store(self._post_form("/auth/platform/login", data))

    def register(self, username: str, password: str, user_group_hash: str, email: Optional[str] = None) -> dict:
        data = {"username": username, "password": password, "user_group_hash": user_group_hash}
        if email:
            data["email"] = email
        # Token fields are null when the group reaches no active project.
        return self._store(self._post_form("/auth/register", data))

    def refresh(self, stale_access_token: Optional[str] = None) -> None:
        with self._lock:
            if stale_access_token is not None and self.access_token != stale_access_token:
                return  # another thread already rotated the pair
            if not self.refresh_token:
                raise RuntimeError("Not signed in")
            self._store(self._post_form("/auth/refresh", {"refresh_token": self.refresh_token}))

    def request(self, method: str, path: str, **kwargs: Any) -> requests.Response:
        """Call a protected route; on a refreshable 401, rotate once and retry once."""
        extra_headers = kwargs.pop("headers", None) or {}

        def send(token: Optional[str]) -> requests.Response:
            headers = {**extra_headers, "Authorization": f"Bearer {token}"}
            return self.http.request(method, f"{self.base_url}{path}", headers=headers, **kwargs)

        token = self.access_token
        response = send(token)
        if response.status_code == 401 and ApiError(response).code not in NOT_REFRESHABLE:
            self.refresh(stale_access_token=token)  # raises ApiError when a new login is needed
            response = send(self.access_token)
        return response

    def validate(self) -> dict:
        response = self.request("GET", "/auth/validate")
        if not response.ok:
            raise ApiError(response)
        return response.json()

    def switch_project(self, project_hash: str) -> dict:
        # Not routed through request(): the retry would resend a refresh token that was just rotated.
        with self._lock:
            body = self._post_form(
                "/auth/switch-project",
                {"project_hash": project_hash, "refresh_token": self.refresh_token},
                headers={"Authorization": f"Bearer {self.access_token}"},
            )  # ApiError AUTH_1008 after 300 seconds: call login() with this project_hash
            return self._store(body)

    def change_password(self, current_password: str, new_password: str) -> None:
        response = self.request(
            "POST",
            "/auth/password/change",
            json={"current_password": current_password, "new_password": new_password},
        )
        if not response.ok:
            raise ApiError(response)  # AUTH_1001, VAL_3007, or INT_7005 with retry_after

    def logout(self) -> None:
        try:
            response = self.request("POST", "/auth/logout")
            if not response.ok:
                raise ApiError(response)
        except (ApiError, RuntimeError):
            pass  # nothing left to revoke
        finally:
            self._store({})


def validate_api_key(base_url: str, api_key: str) -> dict:
    """Resolve a user API key. Never send an Authorization header with it (400)."""
    response = requests.post(
        f"{base_url.rstrip('/')}/auth/validate-api-key",
        headers={"X-API-Key": api_key, "User-Agent": "my-service/1.0"},
    )
    if not response.ok:
        raise ApiError(response)
    return response.json()  # auth_method, user, project, api_key {key_id, public_id}, permissions


client = AuthClient("https://api.example.com")
client.login("alice", os.environ["ALICE_PASSWORD"], project_hash=os.environ["PROJECT_HASH"])
profile = client.request("GET", "/users/profile").json()
```

### React hook (TypeScript)

Session state for a same-site app, built on the browser client above.

```typescript
// useAuth.ts
import { useCallback, useEffect, useState } from 'react';
import {
  type ProjectRef,
  apiFetch,
  login as apiLogin,
  logout as apiLogout,
  switchProject as apiSwitchProject,
} from './authClient';

interface SessionUser {
  user_hash: string;
  username: string;
  user_type: string | null;
}

interface AuthState {
  user: SessionUser | null;
  project: ProjectRef | null;
  accessibleProjects: ProjectRef[];
  loading: boolean;
}

const SIGNED_OUT: AuthState = { user: null, project: null, accessibleProjects: [], loading: false };

export function useAuth() {
  const [state, setState] = useState<AuthState>({ ...SIGNED_OUT, loading: true });

  const reload = useCallback(async () => {
    try {
      const response = await apiFetch('/auth/validate'); // refreshes once if the access cookie expired
      if (!response.ok) {
        setState(SIGNED_OUT);
        return;
      }
      const data = await response.json();
      // /auth/validate has no accessible_projects; keep the list from the last login.
      setState(prev => ({ ...prev, user: data.user, project: data.project, loading: false }));
    } catch {
      setState(SIGNED_OUT); // the refresh failed: a new login is needed
    }
  }, []);

  useEffect(() => {
    void reload();
  }, [reload]);

  const login = useCallback(async (username: string, password: string, projectHash: string, rememberMe = false) => {
    const data = await apiLogin(username, password, projectHash, rememberMe);
    setState({ user: data.user, project: data.project, accessibleProjects: data.accessible_projects, loading: false });
    return data;
  }, []);

  const logout = useCallback(async () => {
    await apiLogout();
    setState(SIGNED_OUT);
  }, []);

  const switchProject = useCallback(async (projectHash: string) => {
    const data = await apiSwitchProject(projectHash); // ApiError AUTH_1008: prompt for a new login
    setState(prev => ({ ...prev, project: data.project }));
    return data;
  }, []);

  return { ...state, login, logout, switchProject, reload };
}
```

## Related

- [Authentication](authentication-usage-cases.md) — endpoint contract, lifetimes, error codes per route
- [Getting started](getting-started.md) — configuration, `ALLOWED_ORIGINS`, first user
- [Error reference](errors.md) — envelope and full code catalog
- [OAuth suite](oauth/README.md) — external identity sign-in; afterwards this guide applies unchanged
- [API keys suite](api-keys/README.md) — creating and revoking user API keys
