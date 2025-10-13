# Architecture Documentation

This folder contains **comprehensive architecture documentation** for the **3-Tier User Type Multi-Project Authentication API**.

---

## 📚 Documentation Structure

### [00_overview.md](00_overview.md) - Start Here
**Executive summary of the entire system**

- System identity and philosophy
- Core capabilities at a glance
- Architecture layers
- Key architectural patterns
- Technology choices
- Performance characteristics

**Read this first** to understand the big picture.

---

### [01_user_type_system.md](01_user_type_system.md)
**3-Tier User Type Hierarchy**

- ROOT users (Super administrators)
- ADMIN users (Project administrators)
- CONSUMER users (End users with RBAC)
- User type comparison matrix
- Conversion flows
- API endpoints for user type management

**Read if you need to:** Understand administrative hierarchies, implement user type checks, or manage user privileges.

---

### [02_group_system.md](02_group_system.md)
**Group-Based Access Control**

- User Groups (global organization)
- Project Groups (permission templates)
- How groups work together
- Group operations and API endpoints
- Permission resolution logic
- Usage patterns and best practices

**Read if you need to:** Implement group-based access, organize users, or manage project permissions.

---

### [03_rbac_system.md](03_rbac_system.md) *(Deprecated)*
**Role-Based Access Control Deep Dive**

⚠️ **DEPRECATED**: The project-specific RBAC system has been replaced by the Global Roles System.

**See instead:** [Global Roles System API](../api/global_roles.md) for the current implementation.

---

### [04_caching_strategy.md](04_caching_strategy.md)
**Multi-Layer Caching Architecture**

- 5 cache layers explained
- Cache hit rates and performance gains
- Automatic cache invalidation
- Cache warming strategies
- Monitoring and troubleshooting

**Read if you need to:** Optimize performance, understand caching behavior, or troubleshoot cache issues.

---

### [05_security_model.md](05_security_model.md)
**Security Architecture**

- 6-layer security model
- Argon2 password hashing
- JWT-style session tokens
- Multi-level authorization
- Threat model and mitigations
- Compliance considerations (GDPR, SOC 2)
- Security best practices and checklists

**Read if you need to:** Implement security features, conduct security audits, or ensure compliance.

---

### [06_api_endpoints.md](06_api_endpoints.md)
**Complete API Endpoints Reference**

- All 95+ endpoints cataloged
- Organized by 11 functional modules
- Authentication requirements
- Common patterns
- Rate limiting
- Response formats

**Read if you need to:** Integrate with the API, understand endpoint organization, or plan API usage.

---

### [07_data_model.md](07_data_model.md) *(Coming Soon)*
**Database Schema and Data Model**

- Complete database schema
- Entity relationships
- Indexes and optimization
- Migration strategies
- Data integrity constraints

**Read if you need to:** Understand data structure, plan migrations, or optimize database performance.

---

### [08_deployment.md](08_deployment.md) *(Coming Soon)*
**Deployment Architecture**

- Development environment
- Production deployment
- Container orchestration
- Scalability considerations
- Monitoring and logging
- Backup and disaster recovery

**Read if you need to:** Deploy the system, scale infrastructure, or plan production architecture.

---

## 🎯 Quick Navigation

### By Role

**For Developers:**
1. Start with [Overview](00_overview.md)
2. Read [User Type System](01_user_type_system.md)
3. Study [Group System](02_group_system.md)
4. Review [API Endpoints](06_api_endpoints.md)
5. Refer to [Caching Strategy](04_caching_strategy.md) for optimization
6. Check [Security Model](05_security_model.md) for security implementation

**For DevOps/SRE:**
1. Start with [Overview](00_overview.md)
2. Focus on [Caching Strategy](04_caching_strategy.md)
3. Study [Security Model](05_security_model.md)
4. Review Deployment (coming soon)

**For System Architects:**
1. Read [Overview](00_overview.md)
2. Study all system components
3. Focus on [Group System](02_group_system.md)
4. Review Data Model (coming soon)

**For Security Engineers:**
1. Start with [Overview](00_overview.md)
2. Study [Security Model](05_security_model.md) - START HERE
3. Focus on [User Type System](01_user_type_system.md)
4. Review [Group System](02_group_system.md)
5. Check [Caching Strategy](04_caching_strategy.md) for cache security

**For Product Managers:**
1. Read [Overview](00_overview.md)
2. Review [API Endpoints](06_api_endpoints.md)
3. Understand [User Type System](01_user_type_system.md)
4. Study [Group System](02_group_system.md) for features

### By Topic

**Authentication & Authorization:**
- [User Type System](01_user_type_system.md)
- [Group System](02_group_system.md)
- [Security Model](05_security_model.md)
- Global Roles System (see [API docs](../api/global_roles.md))

**Performance:**
- [Caching Strategy](04_caching_strategy.md)
- Deployment (coming soon)

**API Integration:**
- [API Endpoints](06_api_endpoints.md)
- [Overview](00_overview.md)

**Data & Storage:**
- Data Model (coming soon)
- [Caching Strategy](04_caching_strategy.md)

---

## 📊 System Statistics

### Code & API
- **11 Functional Modules**
- **102+ REST Endpoints**
- **5 Cache Layers**
- **3 User Types**
- **2 Group Types**

### Performance
- **82% Faster** average response time
- **89-92% Cache Hit Rate**
- **10x Concurrent Users** supported with caching
- **27ms** average response time

### Scale
- Supports **100,000+** users
- Supports **1,000+** user groups
- **Unlimited** projects
- **Multi-project** admin assignments

### System Capabilities (v2.2.0)

**Core Features:**
- ✅ **3-Tier User Type Hierarchy**: Root (global) → Admin (project-scoped) → Consumer (RBAC)
- ✅ **Group-Based Access Control**: User Groups (organization) + Project Groups (permissions)
- ✅ **Multi-Project Architecture**: Unlimited projects with cross-project access
- ✅ **Global Roles System**: 22 endpoints for global role-based permissions
- ✅ **Multi-Admin Support**: Admins can manage multiple projects simultaneously

**API & Operations:**
- ✅ **102+ REST Endpoints**: Across 11 functional modules
- ✅ **Comprehensive CRUD**: Users, projects, groups, roles, permissions
- ✅ **Bulk Operations**: Batch updates for users, roles, and groups
- ✅ **Advanced Filtering**: Search, sort, paginate across all resources
- ✅ **Activity Logging**: Complete audit trail with IP and user agent tracking

**Performance & Caching:**
- ✅ **5-Layer Cache System**: Session, access, RBAC, user type, user groups
- ✅ **82-92% Cache Hit Rates**: Across all cache layers
- ✅ **82% Performance Gain**: With intelligent caching strategy
- ✅ **Automatic Invalidation**: Smart cache clearing on data changes
- ✅ **10x Capacity Improvement**: Concurrent user support with caching

**Analytics & Monitoring:**
- ✅ **Admin Dashboard**: Real-time statistics and metrics
- ✅ **System Analytics**: User, project, and activity analytics
- ✅ **Health Checks**: Component-level monitoring (database, Redis, cache)
- ✅ **Growth Metrics**: 7-day and 30-day trend analysis
- ✅ **Performance Tracking**: Response times, throughput, error rates

**Security:**
- ✅ **Argon2 Password Hashing**: Industry-standard protection
- ✅ **JWT-Style Session Tokens**: Cryptographically signed
- ✅ **Multi-Level Authorization**: User type + groups + RBAC
- ✅ **Rate Limiting**: Per-endpoint and per-user protection
- ✅ **Complete Audit Trail**: All actions logged with context
- ✅ **Input Validation**: Comprehensive request validation
- ✅ **SQL Injection Prevention**: Parameterized queries only

---

## 📁 Project Structure

### High-Level Layout

```
api.auth/
├── src/                           # Source code
│   ├── main.py                    # FastAPI application entry point (v2.2.0)
│   ├── routes/                    # API endpoint definitions (11 modules)
│   │   ├── auth.py                # Authentication endpoints
│   │   ├── users.py               # User management
│   │   ├── user_types_auth.py     # User type management (3-tier)
│   │   ├── projects.py            # Project management
│   │   ├── admin_user_groups.py   # User group administration
│   │   ├── admin_project_groups.py# Project group administration
│   │   ├── admin_dashboard.py     # Admin dashboard
│   │   ├── analytics.py           # Analytics and reporting
│   │   ├── system.py              # System health and info
│   │   ├── rbac.py                # RBAC management
│   │   ├── bulk_operations.py     # Bulk operations
│   │   └── Access.py              # Legacy access validation
│   ├── middleware/                # Middleware components
│   │   ├── authentication.py      # Auth middleware
│   │   └── activity_logging.py    # Activity logging
│   └── Util/                      # Utility modules
│       ├── Models.py              # Data models
│       ├── Seccurity.py           # Security utilities
│       ├── JWT_Security.py        # JWT token management
│       ├── activity_logger.py     # Activity tracking
│       └── db/                    # Database operations
│
├── schemas/                       # Database schemas
│   ├── 01_create_database.sql     # Database creation
│   ├── 02_create_tables.sql       # Table definitions
│   ├── 03_create_index.sql        # Index optimization
│   └── 04_add_constraints.sql     # Constraints
│
├── docs/                          # Documentation
│   ├── ARCHITECTURE/              # Architecture documentation (you are here)
│   ├── api/                       # API endpoint documentation
│   └── architecture.md            # Legacy document (deprecated)
│
├── requirements.txt               # Python dependencies
├── Dockerfile                     # Container configuration
└── README.md                      # Main project documentation
```

### Key Directories

**`src/routes/`** - 11 modular route files for API endpoints
- Organized by functionality (auth, users, projects, admin, analytics, etc.)
- Each module handles a specific domain area
- Clear separation of concerns

**`src/Util/db/`** - Database operation modules
- User management
- Group operations
- Project management
- RBAC operations
- Session management

**`docs/ARCHITECTURE/`** - Architecture documentation
- Modular documents for each system component
- Role-based navigation guides
- Code examples and best practices

---

## 💻 Quick Code Examples

### User Group Management

```python
from Util.db.group_based_crud_operations import UserGroupCRUD, UserGroupMembershipCRUD, ProjectAccessCRUD

# Create user group
admin_group = UserGroupCRUD.create("administrators", "System administrators")

# Assign user to group
UserGroupMembershipCRUD.assign_user_to_group(user_id, admin_group.id)

# Grant group access to project
ProjectAccessCRUD.grant_group_project_access(admin_group.id, project_id)
```

### Project Group Management

```python
from Util.db.group_based_crud_operations import ProjectGroupCRUD, ProjectGroupMembershipCRUD

# Create project group with permissions
full_access = ProjectGroupCRUD.create(
    "full-access",
    ["admin", "read", "write", "delete"],
    "Complete project control"
)

# Assign project to group
ProjectGroupMembershipCRUD.assign_project_to_group(project_id, full_access.id)
```

### Permission Resolution

```python
from Util.db.group_based_crud_operations import PermissionUtils

# Get user's permissions for a project
permissions = PermissionUtils.get_user_project_permissions(user_id, project_id)

# Check specific permission
has_access = PermissionUtils.check_user_permission(user_id, project_id, "admin")

# Get all accessible projects
projects = PermissionUtils.get_user_accessible_projects(user_id)
```

### Group-Based Security Validation

```python
# Validate user group access
def validate_user_group_access(session_token, required_permission):
    """Validate user has required permission through their groups"""
    pass

# Get user's group context
def get_user_group_context(session_token):
    """Get user's group membership and permissions"""
    pass

# Check project group permission
def check_project_group_permission(project_id, permission):
    """Check if project group grants specific permission"""
    pass
```

---

## 🐳 Deployment Examples

### Development Environment

```yaml
# docker-compose.dev.yml
services:
  auth-api:
    build: .
    ports:
      - "8000:8000"
    environment:
      - DEBUG=true
      - GROUP_SYSTEM_ENABLED=true
    volumes:
      - ./src:/app/src  # Hot reload
    
  mysql:
    image: mysql:8.0
    environment:
      - MYSQL_ROOT_PASSWORD=devpassword
      - MYSQL_DATABASE=magic_auth_enhanced_groups
    
  redis:
    image: redis:7-alpine
```

### Production Environment

```yaml
# docker-compose.prod.yml
services:
  auth-api:
    image: group-auth-api:latest
    replicas: 3
    environment:
      - DEBUG=false
      - DB_HOST=mysql-cluster
      - GROUP_SYSTEM_ENABLED=true
    
  nginx:
    image: nginx:alpine
    ports:
      - "443:443"
    volumes:
      - ./nginx.conf:/etc/nginx/nginx.conf
      - ./ssl:/etc/ssl
    
  mysql-cluster:
    image: mysql:8.0
    environment:
      - MYSQL_ROOT_PASSWORD=${MYSQL_PASSWORD}
      - MYSQL_DATABASE=magic_auth_enhanced_groups
    
  redis-cluster:
    image: redis:7-alpine
```

---

## 🔄 Documentation Updates

This documentation is actively maintained and updated with each major release.

**Current Version:** 2.2.0  
**Last Updated:** 2024  
**Status:** ✅ Active Development

### Change Log

**v2.2.0** (Current)
- Added comprehensive architecture documentation
- Documented 3-tier user type system
- Detailed group-based access control
- Complete API endpoint catalog
- Multi-layer caching strategy

**v2.0.0**
- Initial group-based architecture
- 3-tier user type implementation
- RBAC system
- Multi-project admin support

---

## 🤝 Contributing to Documentation

### Documentation Standards

1. **Use Markdown** formatting
2. **Include code examples** where relevant
3. **Add diagrams** using ASCII art or Mermaid
4. **Keep it practical** - focus on implementation
5. **Update the README** when adding new documents

### Document Template

Each architecture document should include:
- **Overview**: High-level explanation
- **Core Concepts**: Key ideas and terminology
- **Implementation Details**: Code and schema
- **API Reference**: Relevant endpoints
- **Best Practices**: Dos and don'ts
- **Troubleshooting**: Common issues
- **Related Documentation**: Links to other docs

---

## 📖 Related Documentation

### API Documentation
Located in `/docs/api/`:
- [Authentication API](../api/authentication.md)
- [User Management API](../api/user-management.md)
- [User Type Management API](../api/user-type-management.md)
- [Project Management API](../api/project-management.md)
- [Admin API](../api/admin.md)
- [Analytics API](../api/analytics.md)
- [Global Roles System API](../api/global_roles.md)
- [System API](../api/system.md)
- [Bulk Operations API](../api/bulk-operations.md)
- [Errors and Responses](../api/errors-and-responses.md)

### Other Documentation
- [Main README](../../README.md) - Project overview and quick start
- [Architecture Overview](../architecture.md) - **⚠️ DEPRECATED** (use this folder instead)
- [Activity Logger Guide](../ACTIVITY_LOGGER_GUIDE.md) - Activity tracking implementation

---

## 🆘 Getting Help

### For Architecture Questions
1. Read the relevant architecture document
2. Check the API documentation
3. Review code examples
4. Contact the development team

### For Implementation Help
1. Start with [Overview](00_overview.md)
2. Follow the quick navigation by role
3. Review API endpoint documentation
4. Check troubleshooting sections

### For Performance Issues
1. Read [Caching Strategy](04_caching_strategy.md)
2. Check monitoring dashboards
3. Review cache statistics
4. Consult deployment documentation

---

## 🎓 Learning Path

### Week 1: Understanding the System
- Day 1-2: Read [Overview](00_overview.md)
- Day 3-4: Study [User Type System](01_user_type_system.md)
- Day 5: Review [API Endpoints](06_api_endpoints.md)

### Week 2: Deep Dive
- Day 1-3: Master [Group System](02_group_system.md)
- Day 4-5: Study RBAC System (when available)

### Week 3: Performance & Security
- Day 1-2: Understand [Caching Strategy](04_caching_strategy.md)
- Day 3-5: Study [Security Model](05_security_model.md)

### Week 4: Advanced Topics
- Day 1-2: Data Model (when available)
- Day 3-5: Deployment architecture (when available)

---

## 📝 Glossary

**User Type**: The administrative level of a user (Root, Admin, Consumer)

**User Group**: Global group organizing users and controlling project access

**Project Group**: Permission template defining what users can do in projects

**RBAC**: Role-Based Access Control - project-specific permission system

**Session**: Authenticated user connection with associated context

**Cache Layer**: One of the 5 caching levels for performance optimization

**Permission**: A specific action or capability (e.g., read, write, admin)

**Role**: Collection of permissions assigned to users in a project

**Access Check**: Verification that a user can perform an action

---

**Questions or feedback?** Contact the development team or file an issue.
