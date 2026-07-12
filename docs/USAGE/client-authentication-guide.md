# Client Authentication & Session Integration Guide

Practical guide for integrating with the `api.auth` authentication system from browser, mobile, and server-side clients.

> **For raw endpoint documentation** (request/response shapes, parameters, error codes), see **[Authentication Usage Cases](authentication-usage-cases.md)**.
> This guide focuses on **client-side integration patterns** and **code examples**.

---

## Table of Contents
- [Overview](#overview)
- [Authentication Flow](#authentication-flow)
- [Token & Cookie Details](#token--cookie-details)
- [Supported Protected-Route Credentials](#supported-protected-route-credentials)
- [Email Activation and Reset Links](#email-activation-and-reset-links)
- [Password Changes](#password-changes)
- [API Keys](#api-keys)
- [Client Integration Patterns](#client-integration-patterns)
- [Code Examples](#code-examples)
- [Error Handling](#error-handling)
- [Security Considerations](#security-considerations)

---

## Overview

The API uses a **true access/refresh token model**:
- **Access tokens** (default 15-minute expiry) authorize protected requests, `/auth/validate`, `/auth/logout`, and `/auth/switch-project`.
- **Refresh tokens** authorize only `/auth/refresh` and rotate the session family. They are 72h-sliding by default, or a 30-day absolute window when the user logs in with `remember_me=true`.
- **API keys** are validated through `POST /auth/validate-api-key` (`X-API-Key` header); see [API Keys](#api-keys).
- **Cookies** (browsers, SPAs) can carry both tokens automatically.
- **Bearer header** clients use the access token manually and must store/use the refresh token separately.

### Key Integration Points

| Concern | Detail |
|---------|--------|
| Content-Type (auth routes) | `/auth/login`, `/auth/register`, `/auth/refresh`, and `/auth/switch-project` use `application/x-www-form-urlencoded` (form fields). The email/password JSON routes (`/auth/email/verify`, `/auth/password/forgot`, `/auth/password/reset`, `/auth/password/change`) use `application/json`. `/auth/validate-api-key` carries no body (header auth). |
| Content-Type (other routes) | Most other POST/PUT/PATCH use `multipart/form-data`; JSON exceptions include `POST /admin/user-groups/{hash}/members/bulk` and `POST /admin/audit/export`. |
| User-Agent | **Required on every request**. Missing it returns 422. |
| CORS | Defaults to explicit local origins `http://localhost:3000,http://localhost:5173,http://localhost:4173,http://localhost:5177` plus dashboard origin `https://auth-ui.arz.ai`. Set `ALLOWED_ORIGINS` in production. |
| Cookies | `session_token` carries the access token; `refresh_token` carries the refresh token. Both are HTTP-only, Secure, SameSite=Strict. |

---

## Authentication Flow

```
1. Check Availability (optional)    → POST /auth/check-availability
2. Register                         → POST /auth/register        → access + refresh token pair
3. Login (subsequent visits)        → POST /auth/login           → access + refresh token pair
4. Validate access token            → GET  /auth/validate        → access cookie or Bearer access token
5. Refresh access token             → POST /auth/refresh         → refresh cookie/body only; rotates refresh token
6. Switch Project (optional)        → POST /auth/switch-project  → access token + current refresh token
7. Change Password (optional)       → POST /auth/password/change → access token + current password; no new session
8. Logout                           → POST /auth/logout          → access/refresh cookies cleared; family revoked
```

For detailed endpoint parameters and response shapes, see [Authentication Usage Cases](authentication-usage-cases.md).

---

## Token & Cookie Details

| Property | Value |
|----------|-------|
| Access Token | Short-lived JWT (default 15 min, `expires_in: 900`) returned as `access_token` and deprecated `session_token` alias |
| Refresh Token | JWT returned as `refresh_token` in JSON and `refresh_token` cookie. 72-hour sliding by default (`refresh_expires_in: 259200`); 30-day absolute window when `remember_me=true` (`refresh_expires_in` ≈ `2592000`, non-sliding) |
| Access Cookie | `session_token`, HTTP-only, Secure, SameSite=Strict, access-token TTL |
| Refresh Cookie | `refresh_token`, HTTP-only, Secure, SameSite=Strict, path compatible with `/auth/refresh`. Max-Age tracks the refresh family TTL (72h sliding, or ~30 days when `remember_me=true`) |
| Session Storage | Redis-backed `session:{access_jti}` plus refresh family records |
| Refresh Strategy | Strict single-use refresh-token rotation; reused/old refresh tokens revoke the family. Default rotation slides the 72h window; a `remember_me=true` family keeps its fixed `absolute_expires_at` and does not slide |
| Remember Me | Optional `remember_me` form field on `/auth/login` and `/auth/platform/login` (default `false`). `true` switches the family from 72h-sliding to a 30-day absolute window. Successful login, refresh, and switch-project responses return the mode as top-level `remember_me`; `/auth/validate` returns it under `session.remember_me` |

`POST /auth/refresh` **does not** accept `Authorization: Bearer <access_token>` and does not upgrade legacy session/access tokens. Send the refresh token through the `refresh_token` cookie or explicit `refresh_token` form/body field.

---

## Supported Protected-Route Credentials

For protected endpoints, clients must use one of the currently wired session credentials:

| Client type | Credential to send |
|-------------|--------------------|
| Browser/SPA | `session_token` cookie carrying the access JWT |
| API clients, scripts, mobile apps, server-to-server callers | `Authorization: Bearer <access_token>` |

Do not send refresh tokens to protected endpoints. Refresh tokens are accepted only by `/auth/refresh`.

---

## Email Activation and Reset Links

Email is optional. Clients must not block registration or account use just because a user has no activated email.

Client rules:

- `POST /auth/email/verify`, `/auth/password/forgot`, and `/auth/password/reset` return generic `202` when syntactically processable.
- Activation/reset consumes do **not** create login sessions.
- Forgot-password recovery only enqueues for active activated email rows; pending, removed, suppressed, unknown, or legacy-only emails keep the same generic public posture.
- After successful activation/reset, prompt the user to login with password.
- If the server returns `429`, honor the `Retry-After` header.
- Use `Idempotency-Key` for add/resend/forgot/reset submissions that may be retried by the client. Reusing a key with a different route, recipient, purpose, or body is a semantic conflict.
- Never log full activation/reset URLs, token `secret`, raw `Idempotency-Key`, or full recipient email.

```javascript
async function submitActivationToken(token) {
  const response = await fetch('/auth/email/verify', {
    method: 'POST',
    headers: { 'Content-Type': 'application/json', 'User-Agent': 'my-app/1.0' },
    body: JSON.stringify({ token }),
    credentials: 'include'
  });
  if (response.status === 429) throw new Error(`Retry after ${response.headers.get('Retry-After')} seconds`);
  if (response.status !== 202) throw new Error('Activation request was not accepted');
  return { accepted: true }; // not proof of token validity
}
```

Forgot/reset handling follows the same generic-response rule:

```javascript
async function requestPasswordReset(identifier) {
  const response = await fetch('/auth/password/forgot', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'User-Agent': 'my-app/1.0',
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify({ email_or_username: identifier }),
    credentials: 'include'
  });
  if (response.status === 429) throw new Error(`Retry after ${response.headers.get('Retry-After')} seconds`);
  if (response.status !== 202) throw new Error('Reset request was not accepted');
  return { accepted: true }; // not proof that the account exists
}

async function submitPasswordReset(token, newPassword) {
  const response = await fetch('/auth/password/reset', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'User-Agent': 'my-app/1.0',
      'Idempotency-Key': crypto.randomUUID(),
    },
    body: JSON.stringify({ token, new_password: newPassword }),
    credentials: 'include'
  });
  if (response.status === 429) throw new Error(`Retry after ${response.headers.get('Retry-After')} seconds`);
  if (response.status !== 202) throw new Error('Reset request was not accepted');
  return { accepted: true }; // prompt for login; no session was created
}
```

Activated-email login is still normal password login. Send the activated email in the existing `username` form field with `project_hash`:

```javascript
async function loginWithActivatedEmail(email, password, projectHash) {
  const formData = new URLSearchParams({
    username: email,
    password,
    project_hash: projectHash,
  });

  const response = await fetch('/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': 'my-app/1.0',
    },
    body: formData,
    credentials: 'include'
  });

  if (!response.ok) throw new Error('Login failed');
  return await response.json();
}
```

---

## Password Changes

Clients must use `POST /auth/password/change` for authenticated password rotation. Do not send `password`, `current_password`, `new_password`, `password_confirmation`, or password-hash shaped fields to `PUT /users/profile`; profile updates reject password mutation before touching the user update helper.

```javascript
async function changePassword(currentPassword, newPassword) {
  const response = await fetch('/auth/password/change', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/json',
      'User-Agent': 'my-app/1.0',
    },
    body: JSON.stringify({
      current_password: currentPassword,
      new_password: newPassword,
    }),
    credentials: 'include'
  });

  if (response.status === 429) {
    throw new Error(`Retry after ${response.headers.get('Retry-After')} seconds`);
  }
  if (!response.ok) {
    const error = await response.json();
    throw new Error(authErrorMessage(error, 'Password change failed'));
  }
  return await response.json(); // no replacement token/session is returned
}
```

Client behavior rules:

- A successful change preserves the authorizing session and revokes other sessions/families; keep using the current access/refresh pair until normal expiry/refresh.
- The response does not include replacement tokens, passwords, password hashes, token secrets, full links, or provider payloads.
- Wrong `current_password` uses generic `AUTH_1001` invalid-credentials posture; do not branch UI copy into "wrong password vs account state" variants.
- Weak `new_password` returns `VAL_3007` with safe `reason_codes` such as `too_short`, `common_password`, `obvious_identifier_derivation`, or `repeated_or_sequential`, plus `min_length`.
- Rate limits return `429` with `Retry-After` and `INT_7005`; back off instead of retry-looping.

---

## API Keys

API keys have full lifecycle support **and** a dedicated validation endpoint, `POST /auth/validate-api-key`, which accepts the `X-API-Key` header. They are **not yet** a general substitute for an access/session JWT on the broader set of protected routes.

What clients can do today:

- Create, list, inspect, update, and revoke API keys through `/users/api-keys` and admin `/api-keys` endpoints.
- Receive the full key value only once at creation time.
- Rely on server-side hashing, storage, cache validation, expiration, and revocation behavior for the key records.
- Validate a key and resolve the owner's user/project/permissions through `POST /auth/validate-api-key` (the API-key analog of `GET /auth/validate`).

Validating an API key:

```javascript
async function validateApiKey(apiKey) {
  const response = await fetch('/auth/validate-api-key', {
    method: 'POST',
    headers: {
      'X-API-Key': apiKey, // format: sk_<public_id>.<secret>
      'User-Agent': 'my-app/1.0',
    },
    // Do NOT also send Authorization; sending both returns 400 "ambiguous_credentials".
  });
  if (!response.ok) throw new Error('API key validation failed');
  return await response.json(); // { valid, auth_method: "api_key", user, project, api_key: { key_id, public_id }, user_groups, permissions }
}
```

```python
# requests: validate an API key (do not also send Authorization)
response = requests.post(
    f"{BASE_URL}/auth/validate-api-key",
    headers={'X-API-Key': api_key, 'User-Agent': 'my-app/1.0'},
)
response.raise_for_status()
context = response.json()  # auth_method == "api_key"; never includes the raw key/secret
```

Rules for `/auth/validate-api-key`:

- Authenticate with the `X-API-Key` header only. Sending **both** `Authorization` and `X-API-Key` returns `400` with `detail: "ambiguous_credentials"`.
- The response never contains the raw key or its secret; only a secret-safe `api_key { key_id, public_id }` object.
- Invalid, missing, revoked, or expired keys return `401`.

Current limitation on other routes:

- `X-API-Key: sk_<public_id>.<secret>` by itself still returns `401` on general protected endpoints such as `/users/profile`; only `/auth/validate-api-key` honors it.
- Middleware may read the key and set request/audit context, but that context does not yet satisfy route authorization on those routes.
- API-key lifecycle/management endpoints still require Bearer access JWT or `session_token` cookie authentication.

Expected future behavior:

API tokens generated for a specific user and project should authenticate **any** protected route as that user. That requires a unified auth dependency and route migration. Until then, use `POST /auth/validate-api-key` to validate keys, and use Bearer access JWTs or the `session_token` cookie for other protected requests.

---

## Client Integration Patterns

### Browser Applications (Cookies)

Browsers automatically handle both the `session_token` access cookie and `refresh_token` cookie. Your client code must send `credentials: 'include'` and serialize refresh attempts so two concurrent refreshes do not reuse the same refresh token:

```javascript
fetch('/auth/login', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
    'User-Agent': 'my-app/1.0',
  },
  body: new URLSearchParams({ username, password, project_hash: projectHash }),
  credentials: 'include',  // Critical: sends/receives cookies
});
```

No manual token storage is required for browser clients. Cookies are inaccessible to JavaScript (XSS protection), and `/auth/refresh` can use the `refresh_token` cookie.

### Mobile / Server-to-Server (Bearer Header)

Extract `access_token` and `refresh_token` from the login/register/platform-login response. Use the access token in `Authorization` for protected requests; use the refresh token only on `/auth/refresh`:

```python
# Login
response = requests.post(f"{BASE_URL}/auth/login", data={
    'username': username,
    'password': password,
    'project_hash': project_hash,
}, headers={'User-Agent': 'my-app/1.0'})
tokens = response.json()
access_token = tokens['access_token']
refresh_token = tokens['refresh_token']

# Subsequent requests
requests.get(f"{BASE_URL}/users/profile", headers={
    'Authorization': f'Bearer {access_token}',
    'User-Agent': 'my-app/1.0',
})

# Refresh: no Authorization Bearer; send refresh_token cookie/body only
response = requests.post(
    f"{BASE_URL}/auth/refresh",
    data={'refresh_token': refresh_token},
    headers={'User-Agent': 'my-app/1.0'},
)
tokens = response.json()
access_token = tokens['access_token']
refresh_token = tokens['refresh_token']
```

Store both tokens in secure storage (Keychain on iOS, KeyStore on Android). Never store tokens in plain text, URLs, or logs.

---

## Code Examples

### JavaScript/TypeScript (Browser)

```javascript
function authErrorMessage(error, fallback) {
  return error?.error?.message || error?.detail?.message || fallback;
}

let refreshInFlight = null;

async function refreshAccessToken() {
  // Browser flow: refresh_token cookie is sent automatically.
  // Never send Authorization: Bearer <access_token> to /auth/refresh.
  if (!refreshInFlight) {
    refreshInFlight = fetch('https://api.example.com/auth/refresh', {
      method: 'POST',
      headers: { 'User-Agent': 'my-app/1.0' },
      credentials: 'include'
    }).finally(() => { refreshInFlight = null; });
  }

  const response = await refreshInFlight;
  if (!response.ok) {
    const error = await response.json();
    throw new Error(authErrorMessage(error, 'Refresh failed; user must log in again'));
  }

  return await response.json(); // includes new access_token + refresh_token fields
}

async function fetchWithAuthRetry(url, options = {}) {
  let response = await fetch(url, { ...options, credentials: 'include' });
  if (response.status !== 401) return response;

  await refreshAccessToken();
  response = await fetch(url, { ...options, credentials: 'include' });
  return response;
}

// Registration
async function register(username, password, email, groupHash) {
  const formData = new URLSearchParams();
  formData.append('username', username);
  formData.append('password', password);
  formData.append('email', email);
  formData.append('user_group_hash', groupHash);

  const response = await fetch('https://api.example.com/auth/register', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': 'my-app/1.0',
    },
    body: formData,
    credentials: 'include'
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(authErrorMessage(error, 'Registration failed'));
  }

  // Response includes access_token, refresh_token, and session_token access alias.
  return await response.json();
}

// Login
// NOTE: projectHash is REQUIRED for ALL users on /auth/login (root, admin, consumer)
// Root/admin may use /auth/platform/login if they want login without project_hash
// rememberMe is optional (default false); true => 30-day absolute refresh family
// instead of the default 72-hour sliding window.
async function login(username, password, projectHash, rememberMe = false) {
  if (!projectHash) {
    throw new Error('projectHash is required for all users on /auth/login');
  }
  const formData = new URLSearchParams();
  formData.append('username', username);
  formData.append('password', password);
  formData.append('project_hash', projectHash);
  if (rememberMe) formData.append('remember_me', 'true');

  const response = await fetch('https://api.example.com/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': 'my-app/1.0',
    },
    body: formData,
    credentials: 'include'
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(authErrorMessage(error, 'Login failed'));
  }

  // Response includes access_token, refresh_token, and session_token access alias.
  return await response.json();
}

// Platform Login (root/admin only, no project_hash)
// rememberMe is optional (default false); true => 30-day absolute refresh family.
async function platformLogin(username, password, rememberMe = false) {
  const formData = new URLSearchParams();
  formData.append('username', username);
  formData.append('password', password);
  if (rememberMe) formData.append('remember_me', 'true');

  const response = await fetch('https://api.example.com/auth/platform/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': 'my-app/1.0',
    },
    body: formData,
    credentials: 'include'
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(authErrorMessage(error, 'Platform login failed'));
  }

  // Response includes platform access_token + refresh_token with no project binding.
  return await response.json();
}

// Validate Session
async function validateSession() {
  const response = await fetch('https://api.example.com/auth/validate', {
    method: 'GET',
    headers: { 'User-Agent': 'my-app/1.0' },
    credentials: 'include'
  });

  if (!response.ok) return null;
  return await response.json();
}

// Switch Project
async function switchProject(projectHash) {
  const formData = new URLSearchParams();
  formData.append('project_hash', projectHash);

  const response = await fetch('https://api.example.com/auth/switch-project', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
      'User-Agent': 'my-app/1.0',
    },
    body: formData,
    credentials: 'include'
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(authErrorMessage(error, 'Switch failed'));
  }

  // Response includes the new project-scoped access_token + refresh_token pair.
  return await response.json();
}

// Logout
async function logout() {
  const response = await fetch('https://api.example.com/auth/logout', {
    method: 'POST',
    headers: { 'User-Agent': 'my-app/1.0' },
    credentials: 'include'
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(authErrorMessage(error, 'Logout failed'));
  }

  return await response.json();
}
```

### Python (with requests library)

```python
import requests
from typing import Optional, Dict, Any

BASE_URL = "https://api.example.com"

class AuthClient:
    def __init__(self):
        self.session = requests.Session()
        self.session.headers['User-Agent'] = 'my-app/1.0'
        self.access_token = None
        self.refresh_token = None

    def _store_tokens(self, result: Dict[Any, Any]) -> None:
        self.access_token = result.get('access_token') or result.get('session_token')
        self.refresh_token = result.get('refresh_token')

    def register(self, username: str, password: str,
                 user_group_hash: str, email: Optional[str] = None) -> Dict[Any, Any]:
        data = {'username': username, 'password': password, 'user_group_hash': user_group_hash}
        if email:
            data['email'] = email

        response = self.session.post(f"{BASE_URL}/auth/register", data=data)
        response.raise_for_status()
        result = response.json()
        self._store_tokens(result)
        return result

    def login(self, username: str, password: str,
              project_hash: str, remember_me: bool = False) -> Dict[Any, Any]:
        """Login. project_hash is REQUIRED for ALL users (root, admin, consumer) on /auth/login.
        Root/admin may use /auth/platform/login if they want login without project_hash.
        remember_me defaults to False; True issues a 30-day absolute refresh family
        instead of the default 72-hour sliding window."""
        data = {'username': username, 'password': password, 'project_hash': project_hash}
        if remember_me:
            data['remember_me'] = 'true'

        response = self.session.post(f"{BASE_URL}/auth/login", data=data)
        response.raise_for_status()
        result = response.json()
        self._store_tokens(result)
        return result

    def refresh(self) -> Dict[Any, Any]:
        """Refresh using refresh_token only. Do not send Authorization Bearer here."""
        if not self.refresh_token:
            raise ValueError("No refresh token. Please login first.")
        response = self.session.post(
            f"{BASE_URL}/auth/refresh",
            data={'refresh_token': self.refresh_token},
        )
        response.raise_for_status()
        result = response.json()
        self._store_tokens(result)
        return result

    def validate_session(self) -> Dict[Any, Any]:
        headers = self._get_auth_headers()
        response = self.session.get(f"{BASE_URL}/auth/validate", headers=headers)
        response.raise_for_status()
        return response.json()

    def switch_project(self, project_hash: str) -> Dict[Any, Any]:
        headers = self._get_auth_headers()
        response = self.session.post(
            f"{BASE_URL}/auth/switch-project",
            headers=headers,
            data={'project_hash': project_hash, 'refresh_token': self.refresh_token}
        )
        response.raise_for_status()
        result = response.json()
        self._store_tokens(result)
        return result

    def logout(self) -> Dict[Any, Any]:
        headers = self._get_auth_headers()
        response = self.session.post(f"{BASE_URL}/auth/logout", headers=headers)
        response.raise_for_status()
        self.access_token = None
        self.refresh_token = None
        return response.json()

    def get_profile(self) -> Dict[Any, Any]:
        headers = self._get_auth_headers()
        response = self.session.get(f"{BASE_URL}/users/profile", headers=headers)
        response.raise_for_status()
        return response.json()

    def update_profile(self, username: Optional[str] = None,
                       email: Optional[str] = None) -> Dict[Any, Any]:
        headers = self._get_auth_headers()
        data = {}
        if username: data['username'] = username
        if email: data['email'] = email

        response = self.session.put(f"{BASE_URL}/users/profile", headers=headers, data=data)
        response.raise_for_status()
        return response.json()

    def change_password(self, current_password: str, new_password: str) -> Dict[Any, Any]:
        headers = self._get_auth_headers()
        response = self.session.post(
            f"{BASE_URL}/auth/password/change",
            headers=headers,
            json={
                'current_password': current_password,
                'new_password': new_password,
            },
        )
        response.raise_for_status()
        return response.json()

    def _get_auth_headers(self) -> Dict[str, str]:
        if not self.access_token:
            raise ValueError("Not authenticated. Please login first.")
        return {'Authorization': f'Bearer {self.access_token}'}
```

### React Hook Example

```typescript
// useAuth.ts
import { useState, useCallback, useEffect } from 'react';

interface User {
  user_hash: string;
  username: string;
  email: string;
  user_type: string;
}

interface Project {
  project_hash: string;
  project_name: string;
  project_description?: string;
}

interface AuthState {
  user: User | null;
  project: Project | null;
  accessibleProjects: Project[];
  isAuthenticated: boolean;
  isLoading: boolean;
}

export function useAuth() {
  const [authState, setAuthState] = useState<AuthState>({
    user: null, project: null, accessibleProjects: [],
    isAuthenticated: false, isLoading: true,
  });

  useEffect(() => { validateSession(); }, []);

  const validateSession = useCallback(async () => {
    try {
      const response = await fetch('/auth/validate', {
        credentials: 'include',
        headers: { 'User-Agent': 'my-app/1.0' },
      });
      if (response.ok) {
        const data = await response.json();
        setAuthState({
          user: data.user, project: data.project,
          accessibleProjects: [], isAuthenticated: true, isLoading: false,
        });
      } else {
        setAuthState(prev => ({ ...prev, isLoading: false }));
      }
    } catch {
      setAuthState(prev => ({ ...prev, isLoading: false }));
    }
  }, []);

  const login = useCallback(async (username: string, password: string, projectHash: string, rememberMe = false) => {
    // projectHash is REQUIRED for ALL users (root, admin, consumer) on /auth/login
    // rememberMe is optional (default false); true => 30-day absolute refresh family.
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);
    formData.append('project_hash', projectHash);
    if (rememberMe) formData.append('remember_me', 'true');

    const response = await fetch('/auth/login', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'my-app/1.0',
      },
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error?.error?.message || 'Login failed');
    }

    const data = await response.json();
    setAuthState({
      user: data.user, project: data.project,
      accessibleProjects: data.accessible_projects,
      isAuthenticated: true, isLoading: false,
    });
    return data;
  }, []);

  const logout = useCallback(async () => {
    await fetch('/auth/logout', {
      method: 'POST',
      headers: { 'User-Agent': 'my-app/1.0' },
      credentials: 'include',
    });
    setAuthState({
      user: null, project: null, accessibleProjects: [],
      isAuthenticated: false, isLoading: false,
    });
  }, []);

  const switchProject = useCallback(async (projectHash: string) => {
    const formData = new URLSearchParams();
    formData.append('project_hash', projectHash);

    const response = await fetch('/auth/switch-project', {
      method: 'POST',
      headers: {
        'Content-Type': 'application/x-www-form-urlencoded',
        'User-Agent': 'my-app/1.0',
      },
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error?.error?.message || 'Switch failed');
    }

    const data = await response.json();
    setAuthState(prev => ({ ...prev, project: data.project }));
    return data;
  }, []);

  return { ...authState, login, logout, switchProject, validateSession };
}
```

---

## Error Handling

### Standard Error Response

```json
{
  "status": "error",
  "error": {
    "code": "AUTH_1001",
    "category": "authentication",
    "message": "Invalid username or password"
  }
}
```

Always parse client-facing text from `error.message`, not from legacy `detail.message`.

### Common Error Codes

For the complete error code catalog, see [Error Reference](errors.md).

| Status | Code | When | Resolution |
|--------|------|------|------------|
| 401 | `INVALID_CREDENTIALS` | Wrong username/password | Verify credentials |
| 401 | `SESSION_EXPIRED` | Token expired | Re-authenticate |
| 401 | `SESSION_INVALID` | Token malformed | Re-authenticate |
| 401 | `ACCOUNT_INACTIVE` | User is inactive | Contact admin |
| 401 | `REFRESH_TOKEN_INVALID` | Refresh token invalid/expired/revoked | Re-authenticate |
| 401 | `REFRESH_TOKEN_REUSED` | Old refresh token reused; family revoked | Clear tokens and re-authenticate |
| 401 | `TOKEN_TYPE_INVALID` | Refresh token used as access token, or access token used for refresh | Use the right token type |
| 401 | `TOKEN_EXPIRED` | JWT `exp` elapsed | Refresh access token or re-authenticate |
| 401 | `SESSION_REVOKED` | Access session or family revoked | Re-authenticate |
| 400 | `WEAK_PASSWORD` | Shared password policy rejected a new password | Show safe reason codes and ask for a stronger passphrase |
| 400 | `INVALID_INPUT` | Profile password mutation or unsupported password-control field | Use `/auth/password/change` or reset-link recovery |
| 403 | `ACCESS_DENIED` | No project access | Contact admin |
| 403 | `PROJECT_ACCESS_DENIED` | Cannot access requested project | Use accessible project |
| 400 | `MISSING_REQUIRED_FIELD` | Required parameter missing | Include all required fields |
| 409 | `USERNAME_EXISTS` | Username taken | Choose different username |
| 409 | `EMAIL_EXISTS` | Email registered | Use different email |
| 422 | — | Missing `User-Agent` header | Add `User-Agent` to every request |
| 429 | `RATE_LIMIT_EXCEEDED` | Login/email/change-password bucket exceeded | Honor `Retry-After` |

---

## Security Considerations

### Token Storage

**Browser Applications**: Use HTTP-only cookies (automatically handled by API). Cookie is inaccessible to JavaScript (XSS protection).

**Mobile/Desktop Applications**: Store token in secure storage (Keychain on iOS, KeyStore on Android). Include token in `Authorization` header. Never store in plain text.

**API Keys**: Store API keys like credentials. They are validated through `POST /auth/validate-api-key` (`X-API-Key` header), but are not yet accepted as auth on other protected routes until the API-key auth dependency is wired into them.

**Avoid**: localStorage/sessionStorage (XSS vulnerable), URL parameters, console logging.

### Session Lifecycle

```
Token Created (Login/Register)
    ↓
Access Token Active (short-lived, default 15 min)
    ↓
Refresh Token Rotation (72h sliding family by default, or 30-day absolute when remember_me=true; old refresh token becomes invalid)
    ↓
Logout or Expiration
    ↓
Access sessions and refresh family invalidated
```

### HTTPS Required

All authentication endpoints MUST use HTTPS in production. The API sets cookies with the `Secure` flag.

### CORS & SameSite

The `session_token` cookie uses `SameSite=Strict`. Ensure your client is served from the same domain or configure CORS appropriately.

---

## Migration and Rollback Notes for Clients

- This is a breaking auth-contract deployment: clients using the old "send the session/access token to `/auth/refresh`" flow will receive HTTP 401.
- Users with legacy sessions may need to log in again so the server can issue a refresh-family-backed token pair.
- Deployments must configure `JWT_SECRET_KEY`; missing configuration fails outside explicit tests and cannot be fixed client-side.
- Clients should serialize refresh calls. A late duplicate refresh attempt is treated as refresh-token reuse and revokes the whole family.
- On rollback to a pre-refresh-family release, tokens issued by this release may not be usable; operators may clear/expire `refresh_family:*`, `refresh_token:*`, `refresh_used:*`, and `revoked_family:*` Redis namespaces and require re-login.

---

## Related Documentation

- **[Authentication Usage Cases](authentication-usage-cases.md)** — Raw endpoint documentation: login, register, session management, project switching
- **[Error Reference](errors.md)** — Complete error code catalog and troubleshooting
- **[Getting Started](getting-started.md)** — Platform setup and first steps

---

**Last Updated**: June 2026
**API Version**: 2.2.0
