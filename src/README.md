# 🔐 3-Tier User Type Multi-Project Authentication System

A comprehensive authentication system with **3-tier user management** (Root/Admin/Consumer) and **complete RBAC**
capabilities for enterprise-grade access control.

## 🌟 What This System Does

**3-Tier Architecture** for clear privilege separation:

```
🔴 ROOT USERS     → Unrestricted Global Access (Super Admins)
🟡 ADMIN USERS    → Multi-Project Admin Access (Project Managers - NEW: Multiple Projects)  
🟢 CONSUMER USERS → RBAC-Based Access (End Users with Group Permissions)
```

**Complete Access Flow:** Users → User Types → Groups → Projects → Global Roles & Permission Groups

**Perfect for:** Enterprise systems, multi-tenant SaaS, complex organizational structures, or any application requiring
sophisticated access control.

## ✨ Features Ready to Use

### 👑 **3-Tier User Type Management**

- ✅ **ROOT USERS**: Create/manage other root users, global system administration
- ✅ **ADMIN USERS**: Multi-project administration with complete project isolation
- ✅ **CONSUMER USERS**: RBAC-based access through user groups
- ✅ User type promotion/demotion with full audit trail
- ✅ Automatic privilege enforcement at database level
- 🆕 **Multi-Project Admin Support**: Admins can manage multiple projects while maintaining isolation

### 🔐 **Advanced Authentication**

- ✅ User registration and login with user type context
- ✅ JWT-based secure session management (3-day sessions with type information)
- ✅ HTTP-only cookie support with Bearer token fallback
- ✅ Project switching based on user type and group access
- ✅ Session validation with comprehensive user context
- ✅ Availability checking for usernames/emails
- 🆕 **Dual Authentication Methods**: Support for both Authorization Bearer headers and secure HTTP-only cookies

### 🎭 **Global Role & Permission System**

- ✅ **Global Roles**: Assign one role per user with hierarchical permission structure
- ✅ **Permission Groups**: Create reusable permission bundles for flexible access control
- ✅ **Permission Management**: Create/manage granular global permissions
- ✅ **User Group Assignments**: Assign permission groups to user groups (organizational scale)
- ✅ **Direct User Assignments**: Assign permission groups directly to users (individual overrides)
- ✅ **Permission Checking**: Real-time permission validation with caching
- ✅ **Project Catalogs**: Metadata-only catalogs for organizing permissions by project context
- ✅ **Audit Trails**: Complete tracking of all permission operations

### 👥 **Hierarchical Group Management**

- ✅ **User Groups**: Global groups that define project access
- ✅ **Project Groups**: Permission sets that define capabilities in projects
- ✅ Group-based project access control
- ✅ Multi-level group assignments
- ✅ Flexible permission inheritance

### 📁 **Advanced Project Management**

- ✅ Create projects with automatic RBAC initialization
- ✅ Project-specific permission and role management
- ✅ Access control based on user types and groups
- ✅ Project isolation with admin boundaries
- ✅ Comprehensive project statistics and monitoring

### 🛡️ **Enterprise Security Features**

- ✅ **Multi-Layer Security**: Transport, authentication, authorization, data isolation
- ✅ **UUID-Based User Identification**: Secure, unpredictable user hashes with `usr-{UUID4}` format
- ✅ **Audit Trails**: Complete tracking of user type changes and permission modifications
- ✅ **JWT Session Security**: Industry-standard cryptographically signed tokens with type context
- ✅ **Secure Cookie Support**: HTTP-only, secure, SameSite cookies for web applications
- ✅ **Access Control**: Hierarchical permission resolution
- ✅ **Data Isolation**: Users only see what their type/groups allow

### 🔧 **Developer & Admin Features**

- ✅ **Comprehensive REST API**: 119 endpoints across 13 major areas
- ✅ **System Monitoring**: Health checks, performance metrics, diagnostics
- ✅ **Activity Logging**: Comprehensive activity tracking with catalog system
- ✅ **Bulk Operations**: Mass user and permission management APIs
- ✅ **Error Handling**: Standardized error codes and responses
- 🆕 **Multi-Project Admin APIs**: New endpoints for managing admin access to multiple projects
- 🆕 **Form Data API**: All endpoints use Form data for consistency (not JSON)

### 🏗️ **Production-Ready Architecture**

- ✅ **Scalable Design**: Supports thousands of users across multiple projects
- ✅ **Advanced Caching**: Comprehensive cache system with 1-hour sessions, access check caching, and automatic
  invalidation
- ✅ **Performance Optimized**: Cache-first authentication with Redis and strategic database indexing
- ✅ **Docker Deployment**: Complete containerization
- ✅ **Database Schema**: Comprehensive MySQL schema with relationships
- ✅ **Monitoring Ready**: Built-in health checks, performance metrics, and cache statistics

## 📚 Complete Documentation Suite

### 📖 **Getting Started** (45 min total)

- [Quick Start Guide](../docs/quick-start.md) - 15 minutes to running system
- [Setup Guide](../docs/setup-guide.md) - Complete installation and configuration
- [Architecture Documentation](../docs/ARCHITECTURE/README.md) - Comprehensive system architecture

### 📡 **API Documentation**

- [Authentication API](../docs/api/authentication.md) - Login, logout, session management
- [User Type Management API](../docs/api/user-type-management.md) - 3-tier user system
- [User Management API](../docs/api/user-management.md) - User profile and access
- [Global Roles API](../docs/api/global_roles.md) - Global role system with permissions
- [Permission Assignments API](../docs/api/permission-assignments.md) - Permission group assignments
- [Project Management API](../docs/api/project-management.md) - Project operations
- [Admin API](../docs/api/admin.md) - Group and system administration
- [Analytics API](../docs/api/analytics.md) - System analytics and metrics
- [Bulk Operations API](../docs/api/bulk-operations.md) - Mass operations
- [System API](../docs/api/system.md) - Monitoring and health checks
- [Errors & Responses](../docs/api/errors-and-responses.md) - Error handling reference

### 🏗️ **System Architecture**

- [Architecture Documentation](../docs/ARCHITECTURE/README.md) - Complete architecture guide
- [User Type System](../docs/ARCHITECTURE/01_user_type_system.md) - 3-tier hierarchy
- [Group System](../docs/ARCHITECTURE/02_group_system.md) - Access control
- [Caching Strategy](../docs/ARCHITECTURE/04_caching_strategy.md) - Performance optimization
- [Security Model](../docs/ARCHITECTURE/05_security_model.md) - Security architecture
- [API Endpoints](../docs/ARCHITECTURE/06_api_endpoints.md) - Complete endpoint reference

### 🆕 **Multi-Project Admin Features**

- [Admin Multi-Project Guide](../ADMIN_MULTI_PROJECT_GUIDE.md) - Complete guide for multi-project admin management
- [Migration Script](../admin_multi_project_migration.sql) - Database migration for multi-project support

## 🛠️ Complete API Overview

### **Core APIs (119 Endpoints)**

| API Area                    | Endpoints     | Purpose                                             |
|-----------------------------|---------------|-----------------------------------------------------|
| **Authentication**          | 7 endpoints   | Login, registration, session management             |
| **User Management**         | 8 endpoints   | User profile, status, and access management         |
| **User Type Management**    | 10 endpoints  | 3-tier user system + multi-project admin management |
| **Project Management**      | 12 endpoints  | Project CRUD with access control                    |
| **Global Roles**            | 22 endpoints  | Global role system with hierarchical permissions    |
| **Permission Assignments**  | 17 endpoints  | Permission group assignments to users/groups        |
| **User Groups Admin**       | 12 endpoints  | Global user group management                        |
| **Project Groups Admin**    | 7 endpoints   | Project permission group management                 |
| **Admin Dashboard**         | 7 endpoints   | Dashboard statistics and activity feed              |
| **Analytics**               | 5 endpoints   | System-wide analytics and trends                    |
| **System Monitoring**       | 7 endpoints   | Health, stats, performance, and cache management    |
| **Bulk Operations**         | 4 endpoints   | Mass user and permission management                 |
| **Access Control (Legacy)** | 1 endpoint    | Legacy compatibility endpoint                       |

### **Database Layer (Comprehensive)**

- **10 Major Modules**: Users, Projects, Global Roles, Permission Assignments, User Groups, Project Groups, Session Analytics, Enhanced Operations
- **Comprehensive Functions**: 200+ database operations with stored procedure support
- **Performance Optimized**: Strategic indexing, Redis caching, and cache-first queries
- **Activity Logging**: Full activity catalog system with detailed tracking

## 📋 Roadmap - Advanced Features

### 🚀 **Authentication Enhancements**

- [ ] Multi-factor authentication (MFA) for ROOT and ADMIN users
- [ ] SSO integration (SAML, OAuth2, LDAP) for enterprise environments
- [ ] Advanced session management with device tracking
- [ ] Passwordless authentication options

### 🎭 **RBAC Extensions**

- [ ] Time-based permissions (temporary access)
- [ ] Conditional permissions based on context
- [ ] Permission templates for rapid deployment
- [ ] Advanced permission inheritance models

### 👑 **User Type Enhancements**

- [ ] Custom user types beyond the 3-tier system
- [ ] User type hierarchies and delegation
- [ ] Automated user type promotion workflows
- [ ] Advanced admin boundaries and scoping

### 🎨 **Management Interface**

- [ ] Web-based admin dashboard for 3-tier management
- [ ] RBAC visual editor for role and permission design
- [ ] User type management interface
- [ ] Real-time system monitoring dashboard

### 📊 **Enterprise Analytics**

- [ ] Advanced user activity analytics by type
- [ ] RBAC usage and access pattern analysis
- [ ] Security compliance reporting
- [ ] Performance and scalability metrics

### 🌍 **Enterprise Integration**

- [ ] Advanced webhook system for external integrations
- [x] Bulk operations API for mass user/permission management ✅ **IMPLEMENTED**
- [ ] Advanced export/import capabilities
- [ ] Third-party system synchronization
- [ ] GraphQL API support alongside REST
- [ ] Event streaming for real-time updates

## 🆘 Need Help?

### 📚 **By User Type**

- **👑 ROOT USERS**: Start with [User Type Management API](../docs/api/user-type-management.md) and [Global Roles API](../docs/api/global_roles.md)
- **🛡️ ADMIN USERS**: Focus on [Admin API](../docs/api/admin.md), [Permission Assignments](../docs/api/permission-assignments.md), and [Analytics](../docs/api/analytics.md)
- **👤 CONSUMER USERS**: Review [Authentication API](../docs/api/authentication.md) and [User Management](../docs/api/user-management.md)
- **🔧 DEVELOPERS**: Begin with [Architecture Documentation](../docs/ARCHITECTURE/README.md) and [System API](../docs/api/system.md)

### 🔧 **Quick Troubleshooting**

| Problem                   | Solution                                         |
|---------------------------|--------------------------------------------------|
| Authentication failing    | Check JWT_SECRET_KEY environment variable        |
| Permission check errors   | Verify user has assigned role and permission groups |
| User type errors          | Verify user type database constraints            |
| Database errors           | Verify MySQL is running with correct schema      |
| Redis cache issues        | Check Redis connection and restart if needed     |
| Session expired errors    | Clear cache via `/system/cache/clear` endpoint   |

### 💡 **Getting Advanced Support**

1. **System Architecture Questions**: Review [Architecture Documentation](../docs/ARCHITECTURE/README.md)
2. **Global Roles & Permissions**: Check [Global Roles API](../docs/api/global_roles.md) and [Permission Assignments](../docs/api/permission-assignments.md)
3. **User Type Management**: See [User Type API](../docs/api/user-type-management.md)
4. **Performance Issues**: Review [System API](../docs/api/system.md) and [Caching Strategy](../docs/ARCHITECTURE/04_caching_strategy.md)
5. **Bulk Operations**: Consult [Bulk Operations API](../docs/api/bulk-operations.md)
6. **Analytics & Monitoring**: Reference [Analytics API](../docs/api/analytics.md) and [Admin Dashboard](../docs/api/admin.md)

## 🎉 Why Choose This 3-Tier System?

### ✅ **Enterprise-Grade Architecture**

- **Hierarchical Control**: Clear separation of privileges and responsibilities
- **Scalable Design**: From small teams to large organizations
- **Security First**: Multi-layer security with comprehensive auditing

### ✅ **Global Role & Permission System**

- **Granular Permissions**: Fine-grained global permission control
- **Hierarchical Roles**: One role per user with permission group inheritance
- **Permission Groups**: Reusable bundles assignable to users and user groups
- **Real-time Validation**: Instant permission checking with caching
- **Flexible Architecture**: Support for both organizational and individual permission assignments

### ✅ **Production-Proven**

- **Comprehensive Testing**: Test suites for all functionality
- **Performance Optimized**: Redis caching and database optimization
- **Monitoring Ready**: Built-in health checks and metrics

### ✅ **Developer Excellence**

- **119 REST Endpoints**: Complete API coverage across all features
- **OpenAPI/Swagger Documentation**: Auto-generated interactive API docs
- **Form Data API**: Consistent Form data format for all requests
- **Standardized Errors**: Comprehensive error codes and handling
- **Easy Integration**: RESTful design with comprehensive examples
- **Version 2.2.0**: Production-ready and actively maintained

## 🔑 Key Architectural Features

### **Global vs Project-Scoped Permissions**
- **Global Roles**: Each user has ONE global role with associated permission groups
- **Permission Groups**: Reusable permission bundles that can be assigned to:
  - User Groups (organizational-level assignments)
  - Individual Users (override/exception assignments)
- **Project Catalogs**: Metadata-only system for organizing permissions by project context (not used for authorization)

### **Form Data API Design**
All API endpoints use **Form Data** instead of JSON for requests:
- Consistent across all endpoints
- Better support for file uploads (future)
- Simpler integration for web forms
- Responses are JSON with Pydantic validation

### **Dual Authentication Support**
- **Bearer Token**: Standard `Authorization: Bearer <token>` header
- **HTTP-Only Cookies**: Secure `session_token` cookie for web applications
- Automatic fallback between both methods

### **Caching Strategy**
- **Session Cache**: 1 hour TTL for user sessions
- **Permission Cache**: 30 minutes TTL for permission checks
- **Access Cache**: 30 minutes TTL for project access checks
- **Automatic Invalidation**: Cache cleared on user/role changes

### **Activity Logging**
- Catalog-based activity types for consistent logging
- Automatic request context capture (IP, User-Agent)
- Detailed activity tracking with metadata support
- Activity statistics and analytics

## 💝 Support This Project

This comprehensive 3-tier authentication system with full RBAC is free and open for everyone!

**[Support on Patreon](https://patreon.com/findit_moe)** 🙏

Your support enables continued development of advanced enterprise features.
