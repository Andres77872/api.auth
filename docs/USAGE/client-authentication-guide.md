# Client Authentication & Session Management Guide

## Table of Contents
- [Overview](#overview)
- [Authentication Flow](#authentication-flow)
- [Registration](#registration)
- [Login](#login)
- [Session Management](#session-management)
- [Profile Management](#profile-management)
- [Security Considerations](#security-considerations)
- [Error Handling](#error-handling)
- [Code Examples](#code-examples)

---

## Overview

This API provides a comprehensive authentication system with support for:
- **User registration** with automatic group assignment
- **Login** with multi-project support
- **Session management** using secure JWT tokens
- **HTTP-only cookies** for enhanced security
- **Project switching** without re-authentication
- **Session validation and refresh**
- **User profile management**

### Authentication Architecture

The system uses a **group-based multi-project authentication** model:
- Users are assigned to **user groups**
- User groups have access to **project groups**
- Users can access multiple projects through their group memberships
- Sessions are project-scoped (or global for root users)

### Token & Cookie Details

- **Token Type**: JWT (JSON Web Token)
- **Cookie Name**: `session_token`
- **Cookie Lifetime**: 72 hours (3 days)
- **Cookie Security**: HTTP-only, Secure, SameSite=Strict
- **Session Storage**: Redis-backed for instant validation

---

## Authentication Flow

### Standard User Journey

```
1. Check Availability (optional)
   └─> Check if username/email is available
   
2. Register
   └─> Create account with group assignment
   └─> Receive session token + cookie
   
3. Login (subsequent visits)
   └─> Authenticate with credentials
   └─> Receive session token + cookie
   └─> Get list of accessible projects
   
4. Validate Session (each request)
   └─> Verify token is still valid
   └─> Get current user & project context
   
5. Switch Project (optional)
   └─> Change to different accessible project
   └─> Receive new token with updated context
   
6. Refresh Token (before expiration)
   └─> Extend session lifetime
   └─> Receive new token
   
7. Logout
   └─> Invalidate session
   └─> Clear cookie
```

---

## Registration

### Endpoint: `POST /auth/register`

Register a new user account with automatic group assignment.

#### Request Parameters (Form Data)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `username` | string | **Yes** | Unique username (3-50 characters) |
| `password` | string | **Yes** | Password (min 8 characters recommended) |
| `email` | string | No | User's email address (must be unique if provided) |
| `user_group_hash` | string | **Yes** | Hash of the user group to join |

#### Response: `RegisterResponse`

```json
{
  "success": true,
  "message": "User registered successfully",
  "user": {
    "user_hash": "usr_abc123...",
    "username": "john_doe",
    "email": "john@example.com",
    "user_type": "consumer"
  },
  "project": {
    "project_hash": "prj_xyz789...",
    "project_name": "Main Application"
  }
}
```

#### How to Get `user_group_hash`

The `user_group_hash` must be provided by your organization's administrator or obtained through a registration portal. This ensures users are assigned to the correct group with appropriate permissions.

> **Important**: The user group must be linked to at least one project before users can register with it. If the user group has no associated projects, registration will fail with an `INVALID_INPUT` error.

#### Cookie Behavior

✅ Upon successful registration, the API automatically:
- Sets an HTTP-only cookie named `session_token`
- Cookie is valid for 72 hours
- No need to manually handle the token for subsequent requests

#### Example: Registration Request

```bash
curl -X POST "https://api.example.com/auth/register" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe" \
  -d "password=SecurePass123!" \
  -d "email=john@example.com" \
  -d "user_group_hash=grp_abc123xyz789"
```

#### Common Errors

| Status Code | Error Code | Description |
|-------------|------------|-------------|
| 400 | `MISSING_REQUIRED_FIELD` | Missing username, password, or user_group_hash |
| 409 | `USERNAME_EXISTS` | Username is already taken |
| 409 | `EMAIL_EXISTS` | Email is already registered |
| 404 | `GROUP_NOT_FOUND` | Invalid user_group_hash |

---

## Login

### Endpoint: `POST /auth/login`

Authenticate with existing credentials and establish a session.

#### Request Parameters (Form Data)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `username` | string | **Yes** | Username or email address |
| `password` | string | **Yes** | User's password |
| `project_hash` | string | No | Specific project to log into (if not provided, uses first accessible project) |

#### Response: `LoginResponse`

```json
{
  "success": true,
  "message": "Login successful",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "user_hash": "usr_abc123...",
    "username": "john_doe",
    "email": "john@example.com",
    "user_type": "consumer"
  },
  "project": {
    "project_hash": "prj_xyz789...",
    "project_name": "Main Application",
    "project_description": "Primary application project"
  },
  "accessible_projects": [
    {
      "project_hash": "prj_xyz789...",
      "project_name": "Main Application",
      "project_description": "Primary application project"
    },
    {
      "project_hash": "prj_def456...",
      "project_name": "Analytics Dashboard",
      "project_description": "Data analytics and reporting"
    }
  ],
  "user_groups": [
    {
      "group_hash": "grp_abc123...",
      "group_name": "Standard Users",
      "description": "Regular application users"
    }
  ]
}
```

#### Project Selection Logic

1. **Specified Project**: If `project_hash` is provided:
   - Verifies user has access to that project
   - Logs into that specific project
   - Returns error if access denied

2. **Auto-Selection**: If `project_hash` is NOT provided:
   - Automatically logs into the first accessible project
   - Returns list of all accessible projects for future switching

3. **Root Users**: Root users receive global access without project binding

#### Cookie Behavior

✅ Upon successful login, the API automatically sets the `session_token` cookie.

#### Example: Basic Login

```bash
curl -X POST "https://api.example.com/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe" \
  -d "password=SecurePass123!"
```

#### Example: Login to Specific Project

```bash
curl -X POST "https://api.example.com/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe" \
  -d "password=SecurePass123!" \
  -d "project_hash=prj_def456..."
```

#### Common Errors

| Status Code | Error Code | Description |
|-------------|------------|-------------|
| 400 | `MISSING_REQUIRED_FIELD` | Missing username or password |
| 401 | `INVALID_CREDENTIALS` | Incorrect username or password |
| 403 | `ACCESS_DENIED` | User has no access to any project |
| 403 | `PROJECT_ACCESS_DENIED` | User doesn't have access to requested project |

---

## Session Management

### Validate Session

#### Endpoint: `GET /auth/validate`

Verify that the current session is still valid and retrieve session context.

#### Authentication Required

Include the session token via:
- **Cookie**: Automatically sent by browser
- **Header**: `Authorization: Bearer <token>`

#### Response: `ValidateSessionResponse`

```json
{
  "success": true,
  "valid": true,
  "user": {
    "user_hash": "usr_abc123...",
    "username": "john_doe",
    "user_type": "consumer"
  },
  "project": {
    "project_hash": "prj_xyz789...",
    "project_name": "Main Application"
  },
  "session": {
    "created_at": null,
    "is_global_session": false
  },
  "user_groups": ["Standard Users", "Beta Testers"]
}
```

#### Example Request

```bash
curl -X GET "https://api.example.com/auth/validate" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

#### Use Cases

- Check if user is still authenticated before sensitive operations
- Retrieve current project context
- Verify group memberships
- Implement "stay logged in" functionality

---

### Refresh Token

#### Endpoint: `POST /auth/refresh`

Extend session lifetime by generating a new token with the same context.

#### Authentication Required

Yes - current valid session token required.

#### Response: `LoginResponse`

Returns same structure as login response with a new token.

#### Example Request

```bash
curl -X POST "https://api.example.com/auth/refresh" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

#### Refresh Strategy

**Recommended**: Refresh token when:
- User is active and session is within 12 hours of expiration
- Before performing important operations if token is older than 48 hours
- After detecting a `SESSION_EXPIRED` error

**Best Practice**: Implement automatic refresh in your client application to maintain seamless user experience.

---

### Switch Project

#### Endpoint: `POST /auth/switch-project`

Change to a different project without logging out.

#### Authentication Required

Yes - current valid session token required.

#### Request Parameters (Form Data)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `project_hash` | string | **Yes** | Hash of the project to switch to |

#### Response: `SwitchProjectResponse`

```json
{
  "success": true,
  "message": "Successfully switched to project: Analytics Dashboard",
  "session_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "project": {
    "project_hash": "prj_def456...",
    "project_name": "Analytics Dashboard",
    "project_description": "Data analytics and reporting"
  },
  "user_groups": ["Standard Users", "Analytics Team"]
}
```

#### Example Request

```bash
curl -X POST "https://api.example.com/auth/switch-project" \
  -H "Authorization: Bearer <current_token>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=prj_def456..."
```

#### Behavior

- Generates a new session token with updated project context
- Invalidates the previous session token
- Updates the session cookie automatically
- Returns user groups relevant to the new project

#### Use Cases

- Multi-tenant applications where users work in different projects
- Switching between client accounts
- Changing organizational contexts

---

### Logout

#### Endpoint: `POST /auth/logout`

Invalidate the current session and clear authentication cookie.

#### Authentication Required

Yes - current session token required.

#### Response: `LogoutResponse`

```json
{
  "success": true,
  "message": "Logged out successfully"
}
```

#### Example Request

```bash
curl -X POST "https://api.example.com/auth/logout" \
  -H "Authorization: Bearer eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
```

#### Behavior

- Removes session from Redis cache (instant invalidation)
- Clears the `session_token` cookie
- Token becomes immediately invalid for all subsequent requests

---

### Check Availability

#### Endpoint: `POST /auth/check-availability`

Check if a username or email is available before registration.

#### No Authentication Required

This endpoint is public to facilitate user registration.

#### Request Parameters (Form Data)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `username` | string | No* | Username to check |
| `email` | string | No* | Email to check |

*At least one parameter is required.

#### Response: `CheckAvailabilityResponse`

```json
{
  "success": true,
  "username_available": true,
  "email_available": false
}
```

#### Example Request

```bash
curl -X POST "https://api.example.com/auth/check-availability" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe" \
  -d "email=john@example.com"
```

#### Use Cases

- Real-time validation in registration forms
- Providing immediate feedback to users
- Preventing registration failures due to conflicts

---

## Profile Management

### Get User Profile

#### Endpoint: `GET /users/profile`

Retrieve the current user's complete profile including groups and projects.

#### Authentication Required

Yes - current session token required.

#### Response: `UserProfileResponse`

```json
{
  "user_hash": "usr_abc123...",
  "username": "john_doe",
  "email": "john@example.com",
  "user_type": "consumer",
  "user_type_info": {
    "user_id": "42",
    "user_hash": "usr_abc123...",
    "username": "john_doe",
    "user_type": "consumer",
    "capabilities": [
      "global_role_permissions",
      "group_based_access",
      "project_access_via_groups"
    ],
    "accessible_projects": ["1", "2"],
    "accessible_projects_details": [
      {
        "project_id": "1",
        "project_hash": "prj_xyz789...",
        "project_name": "Main Application",
        "project_description": "Primary application project"
      }
    ],
    "user_groups": ["Standard Users"]
  },
  "created_at": "2024-01-15T10:30:00Z",
  "updated_at": "2024-12-01T14:20:00Z",
  "last_login": "2024-12-14T09:15:00Z",
  "is_active": true,
  "groups": [
    {
      "group_hash": "grp_abc123...",
      "group_name": "Standard Users",
      "group_description": "Regular application users",
      "assigned_at": "2024-01-15T10:30:00Z",
      "assigned_by": "admin_user"
    }
  ],
  "projects": [
    {
      "project_hash": "prj_xyz789...",
      "project_name": "Main Application",
      "project_description": "Primary application project",
      "project_group": "Core Applications",
      "permissions": ["read", "write", "execute"]
    }
  ]
}
```

#### Example Request

```bash
curl -X GET "https://api.example.com/users/profile" \
  -H "Authorization: Bearer <token>"
```

#### Use Cases

- Display user information in UI
- Show available projects and permissions
- Verify group memberships
- Display account details page

---

### Update User Profile

#### Endpoint: `PUT /users/profile`

Update the current user's profile information.

#### Authentication Required

Yes - current session token required.

#### Request Parameters (Form Data)

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `username` | string | No | New username |
| `email` | string | No | New email address |
| `password` | string | No | New password |

*At least one parameter must be provided.*

#### Response: `UpdateProfileResponse`

```json
{
  "success": true,
  "message": "Profile updated successfully",
  "user": {
    "user_hash": "usr_abc123...",
    "username": "john_doe_updated",
    "email": "newemail@example.com",
    "user_type": "consumer",
    "created_at": "2024-01-15T10:30:00Z",
    "updated_at": "2024-12-14T10:30:00Z"
  }
}
```

#### Example Request

```bash
curl -X PUT "https://api.example.com/users/profile" \
  -H "Authorization: Bearer <token>" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=john_doe_updated" \
  -d "email=newemail@example.com"
```

#### Security Notes

- Password changes require the new password only (no old password confirmation in this version)
- Username and email must remain unique across all users
- Changes are logged in the activity audit system

---

## Security Considerations

### Token Storage

**✅ Recommended Approaches:**

1. **Browser Applications**: 
   - Use HTTP-only cookies (automatically handled by API)
   - Cookie is inaccessible to JavaScript (XSS protection)
   - Automatically sent with each request

2. **Mobile/Desktop Applications**:
   - Store token in secure storage (Keychain on iOS, KeyStore on Android)
   - Include token in `Authorization` header for each request
   - Never store in plain text files or shared preferences

**❌ Avoid:**
- Storing tokens in localStorage or sessionStorage (vulnerable to XSS)
- Storing tokens in URL parameters
- Logging tokens in console or analytics

### Session Lifecycle

```
Token Created (Login/Register)
    ↓
Active Session (72 hours)
    ↓
Refresh Token (optional, extends 72 hours)
    ↓
Logout or Expiration
    ↓
Session Invalidated
```

### HTTPS Required

🔒 **All authentication endpoints MUST be accessed over HTTPS in production.**

The API sets cookies with the `Secure` flag, meaning they will only be transmitted over secure connections.

### CORS & SameSite

The `session_token` cookie uses `SameSite=Strict` to prevent CSRF attacks. Ensure your client application is served from the same domain or configure appropriate CORS policies.

---

## Error Handling

### Standard Error Response

```json
{
  "detail": {
    "error_code": "INVALID_CREDENTIALS",
    "message": "Invalid username or password",
    "details": {
      "username": "john_doe"
    },
    "timestamp": "2024-12-14T10:30:00Z",
    "request_id": "req_abc123xyz"
  }
}
```

### Common Error Codes

#### Authentication Errors (401)

| Error Code | Description | Resolution |
|------------|-------------|------------|
| `INVALID_CREDENTIALS` | Wrong username or password | Verify credentials and retry |
| `SESSION_INVALID` | Session token is invalid | Login again |
| `SESSION_EXPIRED` | Session has expired | Login again or refresh token |

#### Authorization Errors (403)

| Error Code | Description | Resolution |
|------------|-------------|------------|
| `ACCESS_DENIED` | User has no project access | Contact administrator |
| `PROJECT_ACCESS_DENIED` | Cannot access requested project | Use an accessible project |
| `INSUFFICIENT_PERMISSIONS` | Lacking required permissions | Contact administrator |

#### Validation Errors (400)

| Error Code | Description | Resolution |
|------------|-------------|------------|
| `MISSING_REQUIRED_FIELD` | Required parameter missing | Include all required fields |
| `INVALID_INPUT` | Input format is invalid | Check parameter format |

#### Conflict Errors (409)

| Error Code | Description | Resolution |
|------------|-------------|------------|
| `USERNAME_EXISTS` | Username already taken | Choose different username |
| `EMAIL_EXISTS` | Email already registered | Use different email or login |

#### Not Found Errors (404)

| Error Code | Description | Resolution |
|------------|-------------|------------|
| `USER_NOT_FOUND` | User doesn't exist | Verify user_hash |
| `PROJECT_NOT_FOUND` | Project doesn't exist | Verify project_hash |
| `USER_GROUP_NOT_FOUND` | User group doesn't exist | Verify user_group_hash |

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
    },
    body: formData,
    credentials: 'include' // Important: Include cookies
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail.message);
  }

  return await response.json();
}

// Login
async function login(username, password, projectHash = null) {
  const formData = new URLSearchParams();
  formData.append('username', username);
  formData.append('password', password);
  if (projectHash) {
    formData.append('project_hash', projectHash);
  }

  const response = await fetch('https://api.example.com/auth/login', {
    method: 'POST',
    headers: {
      'Content-Type': 'application/x-www-form-urlencoded',
    },
    body: formData,
    credentials: 'include'
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail.message);
  }

  return await response.json();
}

// Validate Session
async function validateSession() {
  const response = await fetch('https://api.example.com/auth/validate', {
    method: 'GET',
    credentials: 'include'
  });

  if (!response.ok) {
    return null;
  }

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
    },
    body: formData,
    credentials: 'include'
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail.message);
  }

  return await response.json();
}

// Logout
async function logout() {
  const response = await fetch('https://api.example.com/auth/logout', {
    method: 'POST',
    credentials: 'include'
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail.message);
  }

  return await response.json();
}

// Get User Profile
async function getUserProfile() {
  const response = await fetch('https://api.example.com/users/profile', {
    method: 'GET',
    credentials: 'include'
  });

  if (!response.ok) {
    const error = await response.json();
    throw new Error(error.detail.message);
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
        self.token = None
    
    def register(self, username: str, password: str, 
                 user_group_hash: str, email: Optional[str] = None) -> Dict[Any, Any]:
        """Register a new user"""
        data = {
            'username': username,
            'password': password,
            'user_group_hash': user_group_hash
        }
        if email:
            data['email'] = email
        
        response = self.session.post(
            f"{BASE_URL}/auth/register",
            data=data
        )
        response.raise_for_status()
        result = response.json()
        self.token = result.get('session_token')
        return result
    
    def login(self, username: str, password: str, 
              project_hash: Optional[str] = None) -> Dict[Any, Any]:
        """Login with credentials"""
        data = {
            'username': username,
            'password': password
        }
        if project_hash:
            data['project_hash'] = project_hash
        
        response = self.session.post(
            f"{BASE_URL}/auth/login",
            data=data
        )
        response.raise_for_status()
        result = response.json()
        self.token = result.get('session_token')
        return result
    
    def validate_session(self) -> Dict[Any, Any]:
        """Validate current session"""
        headers = self._get_auth_headers()
        response = self.session.get(
            f"{BASE_URL}/auth/validate",
            headers=headers
        )
        response.raise_for_status()
        return response.json()
    
    def switch_project(self, project_hash: str) -> Dict[Any, Any]:
        """Switch to different project"""
        headers = self._get_auth_headers()
        data = {'project_hash': project_hash}
        
        response = self.session.post(
            f"{BASE_URL}/auth/switch-project",
            headers=headers,
            data=data
        )
        response.raise_for_status()
        result = response.json()
        self.token = result.get('session_token')
        return result
    
    def logout(self) -> Dict[Any, Any]:
        """Logout and invalidate session"""
        headers = self._get_auth_headers()
        response = self.session.post(
            f"{BASE_URL}/auth/logout",
            headers=headers
        )
        response.raise_for_status()
        self.token = None
        return response.json()
    
    def get_profile(self) -> Dict[Any, Any]:
        """Get user profile"""
        headers = self._get_auth_headers()
        response = self.session.get(
            f"{BASE_URL}/users/profile",
            headers=headers
        )
        response.raise_for_status()
        return response.json()
    
    def update_profile(self, username: Optional[str] = None,
                      email: Optional[str] = None,
                      password: Optional[str] = None) -> Dict[Any, Any]:
        """Update user profile"""
        headers = self._get_auth_headers()
        data = {}
        if username:
            data['username'] = username
        if email:
            data['email'] = email
        if password:
            data['password'] = password
        
        response = self.session.put(
            f"{BASE_URL}/users/profile",
            headers=headers,
            data=data
        )
        response.raise_for_status()
        return response.json()
    
    def _get_auth_headers(self) -> Dict[str, str]:
        """Get authorization headers"""
        if not self.token:
            raise ValueError("Not authenticated. Please login first.")
        return {'Authorization': f'Bearer {self.token}'}

# Usage example
if __name__ == "__main__":
    client = AuthClient()
    
    # Login
    login_result = client.login("john_doe", "SecurePass123!")
    print(f"Logged in as: {login_result['user']['username']}")
    print(f"Current project: {login_result['project']['project_name']}")
    print(f"Accessible projects: {len(login_result['accessible_projects'])}")
    
    # Get profile
    profile = client.get_profile()
    print(f"User type: {profile['user_type']}")
    print(f"Groups: {[g['group_name'] for g in profile['groups']]}")
    
    # Logout
    client.logout()
    print("Logged out successfully")
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
    user: null,
    project: null,
    accessibleProjects: [],
    isAuthenticated: false,
    isLoading: true,
  });

  // Validate session on mount
  useEffect(() => {
    validateSession();
  }, []);

  const validateSession = useCallback(async () => {
    try {
      const response = await fetch('/auth/validate', {
        credentials: 'include',
      });

      if (response.ok) {
        const data = await response.json();
        setAuthState({
          user: data.user,
          project: data.project,
          accessibleProjects: [], // Load from profile if needed
          isAuthenticated: true,
          isLoading: false,
        });
      } else {
        setAuthState(prev => ({ ...prev, isLoading: false }));
      }
    } catch (error) {
      setAuthState(prev => ({ ...prev, isLoading: false }));
    }
  }, []);

  const login = useCallback(async (username: string, password: string, projectHash?: string) => {
    const formData = new URLSearchParams();
    formData.append('username', username);
    formData.append('password', password);
    if (projectHash) {
      formData.append('project_hash', projectHash);
    }

    const response = await fetch('/auth/login', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail.message);
    }

    const data = await response.json();
    setAuthState({
      user: data.user,
      project: data.project,
      accessibleProjects: data.accessible_projects,
      isAuthenticated: true,
      isLoading: false,
    });

    return data;
  }, []);

  const logout = useCallback(async () => {
    await fetch('/auth/logout', {
      method: 'POST',
      credentials: 'include',
    });

    setAuthState({
      user: null,
      project: null,
      accessibleProjects: [],
      isAuthenticated: false,
      isLoading: false,
    });
  }, []);

  const switchProject = useCallback(async (projectHash: string) => {
    const formData = new URLSearchParams();
    formData.append('project_hash', projectHash);

    const response = await fetch('/auth/switch-project', {
      method: 'POST',
      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },
      body: formData,
      credentials: 'include',
    });

    if (!response.ok) {
      const error = await response.json();
      throw new Error(error.detail.message);
    }

    const data = await response.json();
    setAuthState(prev => ({
      ...prev,
      project: data.project,
    }));

    return data;
  }, []);

  return {
    ...authState,
    login,
    logout,
    switchProject,
    validateSession,
  };
}
```

---

## Quick Reference

### Authentication Endpoints Summary

| Endpoint | Method | Auth Required | Purpose |
|----------|--------|---------------|---------|
| `/auth/register` | POST | No | Create new account |
| `/auth/login` | POST | No | Authenticate user |
| `/auth/validate` | GET | Yes | Check session validity |
| `/auth/refresh` | POST | Yes | Extend session lifetime |
| `/auth/switch-project` | POST | Yes | Change project context |
| `/auth/logout` | POST | Yes | End session |
| `/auth/check-availability` | POST | No | Check username/email |
| `/users/profile` | GET | Yes | Get user profile |
| `/users/profile` | PUT | Yes | Update user profile |

### Token Lifecycle

| Action | Token Status | Session Valid | Cookie Status |
|--------|--------------|---------------|---------------|
| Register | Created | ✅ 72 hours | Set |
| Login | Created | ✅ 72 hours | Set |
| Validate | Unchanged | ✅ Checked | Unchanged |
| Refresh | New token | ✅ 72 hours (renewed) | Updated |
| Switch Project | New token | ✅ 72 hours (renewed) | Updated |
| Logout | Invalidated | ❌ Terminated | Cleared |
| Expire (72h) | Invalid | ❌ Expired | Expired |

---

## Support & Additional Resources

For administrative operations (user management, group management, permission assignments), see:
- [Admin Usage Cases](admin-usage-cases.md)
- [Users Management](users-usage-cases.md)
- [Groups Management](groups-usage-cases.md)
- [Permissions Management](permissions-usage-cases.md)

For audit logging and monitoring:
- [Audit Log Usage Cases](audit-log-usage-cases.md)

---

**Last Updated**: January 18, 2026  
**API Version**: 1.0  
**Authentication System**: Group-Based Multi-Project Authentication
