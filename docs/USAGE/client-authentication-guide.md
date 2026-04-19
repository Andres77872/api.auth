# Client Authentication & Session Integration Guide

Practical guide for integrating with the `api.auth` authentication system from browser, mobile, and server-side clients.

> **For raw endpoint documentation** (request/response shapes, parameters, error codes), see **[Authentication Usage Cases](authentication-usage-cases.md)**.
> This guide focuses on **client-side integration patterns** and **code examples**.

---

## Table of Contents
- [Overview](#overview)
- [Authentication Flow](#authentication-flow)
- [Token & Cookie Details](#token--cookie-details)
- [Client Integration Patterns](#client-integration-patterns)
- [Code Examples](#code-examples)
- [Error Handling](#error-handling)
- [Security Considerations](#security-considerations)

---

## Overview

The API provides authentication via JWT tokens stored in HTTP-only cookies. Clients can authenticate using either:
- **Cookies** (browsers, SPAs) — automatic, no manual token handling
- **Bearer header** (mobile, server-to-server, scripts) — manual token management

### Key Integration Points

| Concern | Detail |
|---------|--------|
| Content-Type | Almost all POST/PUT/PATCH use `multipart/form-data`. Exceptions: `POST /admin/user-groups/{hash}/members/bulk` and `POST /admin/audit/export` use JSON. |
| User-Agent | **Required on every request**. Missing it returns 422. |
| CORS | Defaults to `http://localhost:3000,http://localhost:5173`. Set `ALLOWED_ORIGINS` in production. |
| Cookie | `session_token`, HTTP-only, Secure, SameSite=Strict, 72-hour max-age |

---

## Authentication Flow

```
1. Check Availability (optional)    → POST /auth/check-availability
2. Register                         → POST /auth/register        → cookie set automatically
3. Login (subsequent visits)        → POST /auth/login           → cookie set automatically
4. Validate Session (each request)  → GET  /auth/validate        → auto via cookie or Bearer header
5. Switch Project (optional)        → POST /auth/switch-project  → new cookie, old session deleted
6. Refresh Token (before expiry)    → POST /auth/refresh         → session rotation (new token, delete old)
7. Logout                           → POST /auth/logout          → cookie cleared, session deleted
```

For detailed endpoint parameters and response shapes, see [Authentication Usage Cases](authentication-usage-cases.md).

---

## Token & Cookie Details

| Property | Value |
|----------|-------|
| Token Type | JWT (JSON Web Token) |
| Cookie Name | `session_token` |
| Cookie Lifetime | 72 hours (259200 seconds) |
| Cookie Flags | HTTP-only, Secure, SameSite=Strict |
| Session Storage | Redis-backed |
| Refresh Strategy | Session rotation — new token issued, old session deleted (not a refresh-token pattern) |

---

## Client Integration Patterns

### Browser Applications (Cookies)

Browsers automatically handle the `session_token` cookie. Your client code only needs:

```javascript
fetch('/auth/login', {
  method: 'POST',
  headers: {
    'Content-Type': 'application/x-www-form-urlencoded',
    'User-Agent': 'my-app/1.0',
  },
  body: new URLSearchParams({ username, password }),
  credentials: 'include',  // Critical: sends/receives cookies
});
```

No manual token storage needed. The cookie is inaccessible to JavaScript (XSS protection).

### Mobile / Server-to-Server (Bearer Header)

Extract the `session_token` from the login response and include it in subsequent requests:

```python
# Login
response = requests.post(f"{BASE_URL}/auth/login", data={
    'username': username,
    'password': password,
}, headers={'User-Agent': 'my-app/1.0'})
token = response.json()['session_token']

# Subsequent requests
requests.get(f"{BASE_URL}/users/profile", headers={
    'Authorization': f'Bearer {token}',
    'User-Agent': 'my-app/1.0',
})
```

Store tokens in secure storage (Keychain on iOS, KeyStore on Android). Never in plain text.

---

## Code Examples

### JavaScript/TypeScript (Browser)

```javascript
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
    throw new Error(error.detail?.message || 'Registration failed');
  }

  return await response.json();
}

// Login
// NOTE: projectHash is REQUIRED for ALL users on /auth/login (root, admin, consumer)
// Root/admin may use /auth/platform/login if they want login without project_hash
async function login(username, password, projectHash) {
  if (!projectHash) {
    throw new Error('projectHash is required for all users on /auth/login');
  }
  const formData = new URLSearchParams();
  formData.append('username', username);
  formData.append('password', password);
  formData.append('project_hash', projectHash);

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
    throw new Error(error.detail?.message || 'Login failed');
  }

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
    throw new Error(error.detail?.message || 'Switch failed');
  }

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
    throw new Error(error.detail?.message || 'Logout failed');
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
        self.token = None

    def register(self, username: str, password: str,
                 user_group_hash: str, email: Optional[str] = None) -> Dict[Any, Any]:
        data = {'username': username, 'password': password, 'user_group_hash': user_group_hash}
        if email:
            data['email'] = email

        response = self.session.post(f"{BASE_URL}/auth/register", data=data)
        response.raise_for_status()
        result = response.json()
        self.token = result.get('session_token')
        return result

    def login(self, username: str, password: str,
              project_hash: str) -> Dict[Any, Any]:
        """Login. project_hash is REQUIRED for ALL users (root, admin, consumer) on /auth/login.
        Root/admin may use /auth/platform/login if they want login without project_hash."""
        data = {'username': username, 'password': password, 'project_hash': project_hash}

        response = self.session.post(f"{BASE_URL}/auth/login", data=data)
        response.raise_for_status()
        result = response.json()
        self.token = result.get('session_token')
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
            data={'project_hash': project_hash}
        )
        response.raise_for_status()
        result = response.json()
        self.token = result.get('session_token')
        return result

    def logout(self) -> Dict[Any, Any]:
        headers = self._get_auth_headers()
        response = self.session.post(f"{BASE_URL}/auth/logout", headers=headers)
        response.raise_for_status()
        self.token = None
        return response.json()

    def get_profile(self) -> Dict[Any, Any]:
        headers = self._get_auth_headers()
        response = self.session.get(f"{BASE_URL}/users/profile", headers=headers)
        response.raise_for_status()
        return response.json()

    def update_profile(self, username: Optional[str] = None,
                       email: Optional[str] = None,
                       password: Optional[str] = None) -> Dict[Any, Any]:
        headers = self._get_auth_headers()
        data = {}
        if username: data['username'] = username
        if email: data['email'] = email
        if password: data['password'] = password

        response = self.session.put(f"{BASE_URL}/users/profile", headers=headers, data=data)
        response.raise_for_status()
        return response.json()

    def _get_auth_headers(self) -> Dict[str, str]:
        if not self.token:
            raise ValueError("Not authenticated. Please login first.")
        return {'Authorization': f'Bearer {self.token}'}
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

  const login = useCallback(async (username: string, password: string, projectHash: string) => {
    // projectHash is REQUIRED for ALL users (root, admin, consumer) on /auth/login
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);
    formData.append('project_hash', projectHash);

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
      throw new Error(error.detail?.message || 'Login failed');
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
      throw new Error(error.detail?.message || 'Switch failed');
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
  "detail": {
    "error_code": "INVALID_CREDENTIALS",
    "message": "Invalid username or password",
    "details": { "username": "john_doe" },
    "timestamp": "2024-12-14T10:30:00Z",
    "request_id": "req_abc123xyz"
  }
}
```

### Common Error Codes

For the complete error code catalog, see [Error Reference](errors.md).

| Status | Code | When | Resolution |
|--------|------|------|------------|
| 401 | `INVALID_CREDENTIALS` | Wrong username/password | Verify credentials |
| 401 | `SESSION_EXPIRED` | Token expired | Re-authenticate |
| 401 | `SESSION_INVALID` | Token malformed | Re-authenticate |
| 401 | `ACCOUNT_INACTIVE` | User is inactive | Contact admin |
| 403 | `ACCESS_DENIED` | No project access | Contact admin |
| 403 | `PROJECT_ACCESS_DENIED` | Cannot access requested project | Use accessible project |
| 400 | `MISSING_REQUIRED_FIELD` | Required parameter missing | Include all required fields |
| 409 | `USERNAME_EXISTS` | Username taken | Choose different username |
| 409 | `EMAIL_EXISTS` | Email registered | Use different email |
| 422 | — | Missing `User-Agent` header | Add `User-Agent` to every request |

---

## Security Considerations

### Token Storage

**Browser Applications**: Use HTTP-only cookies (automatically handled by API). Cookie is inaccessible to JavaScript (XSS protection).

**Mobile/Desktop Applications**: Store token in secure storage (Keychain on iOS, KeyStore on Android). Include token in `Authorization` header. Never store in plain text.

**Avoid**: localStorage/sessionStorage (XSS vulnerable), URL parameters, console logging.

### Session Lifecycle

```
Token Created (Login/Register)
    ↓
Active Session (72 hours)
    ↓
Refresh Token (optional, session rotation — new token, old deleted)
    ↓
Logout or Expiration
    ↓
Session Invalidated
```

### HTTPS Required

All authentication endpoints MUST use HTTPS in production. The API sets cookies with the `Secure` flag.

### CORS & SameSite

The `session_token` cookie uses `SameSite=Strict`. Ensure your client is served from the same domain or configure CORS appropriately.

---

## Related Documentation

- **[Authentication Usage Cases](authentication-usage-cases.md)** — Raw endpoint documentation: login, register, session management, project switching
- **[Error Reference](errors.md)** — Complete error code catalog and troubleshooting
- **[Getting Started](getting-started.md)** — Platform setup and first steps

---

**Last Updated**: April 2026
**API Version**: 2.2.0
