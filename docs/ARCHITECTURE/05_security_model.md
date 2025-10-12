# Security Model & Architecture

## Overview

The 3-Tier User Type Multi-Project Authentication API implements a **comprehensive, defense-in-depth security model** with multiple layers of protection, authentication, and authorization mechanisms.

---

## Security Layers

### Layer 1: Transport Security

**HTTPS/TLS Encryption**
- All production traffic encrypted via HTTPS
- TLS 1.2+ required
- Certificate management for secure communications
- Protection against man-in-the-middle attacks

**CORS Configuration**
```python
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Configure for production
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)
```

**Recommendations:**
- Use specific origins in production (not `*`)
- Implement origin validation
- Configure secure cookies with `httponly` and `secure` flags

---

### Layer 2: Authentication

#### Password Security (Argon2)

**Hashing Algorithm:**
- **Argon2id**: Industry-standard, winner of Password Hashing Competition
- Memory-hard algorithm resistant to GPU cracking
- Automatic salt generation and management
- Configurable time and memory cost parameters

**Implementation:**
```python
from argon2 import PasswordHasher

ph = PasswordHasher(
    time_cost=2,      # Number of iterations
    memory_cost=65536, # Memory usage in KB (64MB)
    parallelism=4,    # Number of parallel threads
    hash_len=32,      # Length of the hash in bytes
    salt_len=16       # Length of the salt in bytes
)

# Hash password
password_hash = ph.hash(password)

# Verify password
try:
    ph.verify(password_hash, password)
    # Password correct
except:
    # Password incorrect
```

**Security Features:**
- Unique salt per password
- Resistant to rainbow tables
- Resistant to timing attacks
- Automatic rehashing on parameter updates

#### Session Token Management

**JWT-Style Session Tokens**
```python
session_token = {
    "user_id": 123,
    "user_hash": "usr-abc123",
    "user_type": "consumer",
    "project_id": 5,
    "issued_at": 1704636000,
    "expires_at": 1704722400,
    "session_id": "sess_xyz789"
}
```

**Token Security:**
- Cryptographically signed tokens
- Short expiration times (3 days default)
- Stored in Redis with TTL
- Backed up in MySQL for persistence
- Automatic cleanup of expired tokens

**Token Validation Flow:**
```
1. Extract token from Authorization header
2. Check token format and signature
3. Verify token not expired
4. Check Redis cache for session
5. Validate user still active
6. Verify project access (if applicable)
7. Return user context or reject
```

#### Multi-Factor Considerations

**Current State:** Single-factor (password)

**Future Enhancements:**
- TOTP (Time-based One-Time Password)
- SMS verification
- Email verification codes
- Biometric authentication
- Hardware security keys (U2F/WebAuthn)

---

### Layer 3: Authorization

#### 3-Tier User Type Authorization

**Privilege Hierarchy:**
```
ROOT (Highest Privilege)
  ↓
ADMIN (Project-Scoped)
  ↓
CONSUMER (RBAC-Controlled)
```

**Authorization Checks:**
```python
def check_user_type_access(session, required_type):
    """
    Check if user has required user type privilege
    """
    user_type = session.get('user_type')
    
    type_hierarchy = {
        'root': 3,
        'admin': 2,
        'consumer': 1
    }
    
    user_level = type_hierarchy.get(user_type, 0)
    required_level = type_hierarchy.get(required_type, 999)
    
    if user_level < required_level:
        raise PermissionDenied(
            f"Required user type: {required_type}, "
            f"current: {user_type}"
        )
```

#### Group-Based Authorization

**User Group Access Control:**
```python
def check_group_project_access(user_id, project_id):
    """
    Verify user has project access via group membership
    """
    # Get user's groups
    user_groups = get_user_groups(user_id)
    
    # Check if any group has project access
    for group in user_groups:
        if has_project_access(group.id, project_id):
            return True
    
    raise PermissionDenied("No group access to project")
```

**Project Group Permissions:**
```python
def get_user_project_permissions(user_id, project_id):
    """
    Get user's effective permissions in a project
    """
    # Check group-based access
    check_group_project_access(user_id, project_id)
    
    # Get project's permission group
    project_group = get_project_group(project_id)
    
    # Extract permissions
    base_permissions = project_group.permissions
    
    # Add RBAC permissions
    rbac_permissions = get_rbac_permissions(user_id, project_id)
    
    # Return union
    return list(set(base_permissions + rbac_permissions))
```

#### RBAC Authorization

**Role-Based Permission Checks:**
```python
def check_rbac_permission(user_id, project_id, permission):
    """
    Check if user has specific permission via RBAC
    """
    # Get user's roles in project
    roles = get_user_project_roles(user_id, project_id)
    
    # Check each role for permission
    for role in roles:
        role_permissions = get_role_permissions(role.id)
        if permission in role_permissions:
            return True
    
    raise PermissionDenied(f"Missing RBAC permission: {permission}")
```

---

### Layer 4: Data Security

#### Project Boundary Enforcement

**Database-Level Isolation:**
```sql
-- Admin users can only see their assigned projects
SELECT p.*
FROM projects p
INNER JOIN admin_project_assignments apa
  ON p.id = apa.project_id
WHERE apa.admin_user_id = ?

-- Consumer users can only see group-accessible projects
SELECT DISTINCT p.*
FROM projects p
INNER JOIN user_group_project_access ugpa
  ON p.id = ugpa.project_id
INNER JOIN user_group_members ugm
  ON ugpa.user_group_id = ugm.group_id
WHERE ugm.user_id = ?
```

**Application-Level Validation:**
```python
def validate_project_access(user_id, project_id, user_type):
    """
    Enforce project boundaries based on user type
    """
    if user_type == 'root':
        return True  # Root users bypass checks
    
    elif user_type == 'admin':
        # Check admin assignment
        assigned_projects = get_admin_projects(user_id)
        if project_id not in assigned_projects:
            raise PermissionDenied("Not assigned to this project")
    
    elif user_type == 'consumer':
        # Check group access
        check_group_project_access(user_id, project_id)
    
    return True
```

#### Sensitive Data Protection

**Password Storage:**
- Never store plaintext passwords
- Use Argon2 hashing with unique salts
- Hash comparison uses constant-time algorithm
- Failed login attempts logged

**Session Token Storage:**
- Tokens stored hashed in database
- Redis cache uses encrypted values
- Tokens never logged or exposed in errors
- Automatic expiration and cleanup

**Personal Data Handling:**
- Email addresses encrypted at rest
- PII access logged for audit
- Data retention policies enforced
- GDPR-compliant data handling

---

### Layer 5: Application Security

#### Input Validation

**Request Validation:**
```python
from pydantic import BaseModel, validator

class UserCreateRequest(BaseModel):
    username: str
    password: str
    email: Optional[str]
    
    @validator('username')
    def validate_username(cls, v):
        if len(v) < 3:
            raise ValueError('Username too short')
        if not v.isalnum():
            raise ValueError('Username must be alphanumeric')
        return v
    
    @validator('password')
    def validate_password(cls, v):
        if len(v) < 8:
            raise ValueError('Password too short')
        return v
```

**SQL Injection Prevention:**
- All queries use parameterized statements
- ORM-style query building
- No dynamic SQL construction
- Input sanitization at entry points

**XSS Prevention:**
- API responses are JSON (not HTML)
- No user input rendered as HTML
- Content-Type headers set correctly
- CSP headers in place

#### Rate Limiting

**Endpoint Rate Limits:**
```python
rate_limits = {
    'public': '100/hour',      # Public endpoints
    'authenticated': '1000/hour',  # Authenticated users
    'admin': '2000/hour',      # Admin users
    'bulk': '100/hour'         # Bulk operations
}
```

**Implementation:**
```python
from slowapi import Limiter
from slowapi.util import get_remote_address

limiter = Limiter(key_func=get_remote_address)

@app.post("/auth/login")
@limiter.limit("5/minute")  # Prevent brute force
async def login(request: Request):
    # Login logic
    pass
```

**Protections:**
- Prevents brute force attacks
- Mitigates DoS attempts
- Per-IP and per-user limits
- Configurable thresholds

#### Request Size Limits

**Content Length Validation:**
```python
@app.middleware("http")
async def check_content_length(request: Request, call_next):
    if request.method == 'POST':
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > 8388608:  # 8MB
            return JSONResponse(
                status_code=413,
                content={"detail": "Request too large"}
            )
    return await call_next(request)
```

---

### Layer 6: Audit & Monitoring

#### Comprehensive Activity Logging

**Activity Types Logged:**
- User login/logout
- User creation/deletion
- User type changes
- Group membership changes
- Project access grants/revokes
- Permission modifications
- Failed authentication attempts
- Suspicious activities

**Activity Log Structure:**
```python
activity_log = {
    "id": 1523,
    "activity_type": "user_login",
    "user_id": 123,
    "target_user_id": None,
    "project_id": 5,
    "details": "User logged in successfully",
    "ip_address": "192.168.1.100",
    "user_agent": "Mozilla/5.0...",
    "created_at": "2024-01-15T10:30:00Z"
}
```

**Audit Trail Features:**
- Immutable activity records
- Full context capture
- IP address tracking
- User agent logging
- Timestamp precision
- Retention policies

#### Security Monitoring

**Metrics to Monitor:**
- Failed login attempts per user/IP
- Permission denied errors
- Unusual access patterns
- Token validation failures
- Cache invalidation spikes
- Bulk operation frequencies

**Alert Triggers:**
- 5+ failed logins in 5 minutes
- Root user creation
- Mass user deletions
- Permission escalation attempts
- Suspicious IP addresses
- Off-hours administrative actions

---

## Security Best Practices

### For Development

1. **Never Commit Secrets**
   - Use environment variables
   - Store credentials in secret management
   - Rotate keys regularly

2. **Secure Defaults**
   - Enable security features by default
   - Fail securely (deny access on error)
   - Use secure session settings

3. **Principle of Least Privilege**
   - Grant minimum required permissions
   - Use time-limited elevated access
   - Regular permission audits

### For Deployment

1. **Infrastructure Security**
   - Keep systems patched
   - Use firewall rules
   - Segment networks
   - Enable encryption at rest

2. **Database Security**
   - Use strong database passwords
   - Limit database user privileges
   - Enable database audit logging
   - Regular backups encrypted

3. **Redis Security**
   - Use Redis authentication
   - Disable dangerous commands
   - Use TLS for Redis connections
   - Limit network access

### For Operations

1. **Access Management**
   - Regular user access reviews
   - Disable inactive accounts
   - Monitor privileged access
   - Enforce strong passwords

2. **Incident Response**
   - Document security procedures
   - Regular security drills
   - Incident response plan
   - Contact information maintained

3. **Compliance**
   - GDPR data handling
   - SOC 2 compliance preparation
   - Regular security audits
   - Penetration testing

---

## Threat Model

### Identified Threats

**1. Credential Theft**
- **Threat:** Attacker obtains user credentials
- **Mitigation:** Argon2 hashing, rate limiting, MFA (future)
- **Detection:** Failed login monitoring

**2. Session Hijacking**
- **Threat:** Attacker steals session token
- **Mitigation:** HTTPS only, short token expiration, secure storage
- **Detection:** Unusual session activity patterns

**3. Privilege Escalation**
- **Threat:** User gains unauthorized elevated privileges
- **Mitigation:** 3-tier user type system, permission checks at every layer
- **Detection:** Audit logs, permission change alerts

**4. SQL Injection**
- **Threat:** Attacker manipulates database queries
- **Mitigation:** Parameterized queries, input validation, ORM usage
- **Detection:** Database query logging, error monitoring

**5. Brute Force Attacks**
- **Threat:** Automated password guessing
- **Mitigation:** Rate limiting, account lockout, CAPTCHA
- **Detection:** Failed login attempt monitoring

**6. Insider Threats**
- **Threat:** Authorized user abuses access
- **Mitigation:** Principle of least privilege, comprehensive audit logs
- **Detection:** Anomaly detection, regular audits

**7. Data Breach**
- **Threat:** Unauthorized access to stored data
- **Mitigation:** Encryption at rest, access controls, network segmentation
- **Detection:** Database access logs, data exfiltration monitoring

**8. Denial of Service**
- **Threat:** Service unavailability
- **Mitigation:** Rate limiting, request size limits, load balancing
- **Detection:** Traffic monitoring, performance metrics

---

## Compliance Considerations

### GDPR (General Data Protection Regulation)

**Data Subject Rights:**
- ✅ Right to access (GET /users/profile)
- ✅ Right to rectification (PUT /users/profile)
- ✅ Right to erasure (DELETE /users/{user_hash})
- ✅ Right to data portability (export endpoints)
- ✅ Right to be informed (activity logs)

**Data Processing:**
- Lawful basis documented
- Data minimization practiced
- Purpose limitation enforced
- Storage limitation via retention policies
- Consent management (where applicable)

### SOC 2 Preparation

**Security Controls:**
- Access controls implemented
- Encryption in transit and at rest
- Logging and monitoring active
- Incident response procedures
- Vendor management processes

**Availability Controls:**
- High availability architecture
- Backup and recovery procedures
- Disaster recovery planning
- Performance monitoring

---

## Security Checklist

### Pre-Deployment

- [ ] All secrets in environment variables
- [ ] HTTPS/TLS configured
- [ ] Database credentials rotated
- [ ] Redis authentication enabled
- [ ] CORS configured for production
- [ ] Rate limiting enabled
- [ ] Session expiration configured
- [ ] Logging configured
- [ ] Backup procedures tested
- [ ] Security scan completed

### Post-Deployment

- [ ] Monitor failed login attempts
- [ ] Review audit logs daily
- [ ] Check for unusual patterns
- [ ] Verify backup integrity
- [ ] Update dependencies
- [ ] Rotate credentials monthly
- [ ] Review user permissions quarterly
- [ ] Conduct security training
- [ ] Test incident response
- [ ] Annual penetration testing

---

## Security Contact

For security issues or vulnerabilities:

1. **Do not** create public GitHub issues
2. Email security team directly
3. Use encrypted communication when possible
4. Provide detailed reproduction steps
5. Allow reasonable disclosure timeline

---

**Related Documentation:**
- [User Type System](01_user_type_system.md)
- [Group System](02_group_system.md)
- [Caching Strategy](04_caching_strategy.md)
- [API Endpoints](06_api_endpoints.md)
