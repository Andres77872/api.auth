# Quick Start Guide

Get the Group-Based Multi-Project Authentication API running in 15 minutes.

## 🚀 Prerequisites

- **Docker & Docker Compose** (recommended)
- OR **Python 3.11+**, **MySQL 8.0+**, **Redis 6.0+**

## ⚡ Option 1: Docker Quick Start (Recommended)

### 1. Clone and Setup

```bash
git clone <repository-url>
cd api.auth
```

### 2. Create Environment File

```bash
cat > .env << EOF
# Database Configuration
DB_HOST=mysql
DB_USER=root
DB_MYSQL_PASSWORD=quickstart123
DB_DATABASE=magic_auth_groups

# Redis Configuration
DB_REDIS_PASSWORD=redis123

# Group System
GROUP_SYSTEM_ENABLED=true
EOF
```

### 3. Start Everything

```bash
# Start all services
docker-compose up -d

# Wait for services to initialize (30 seconds)
sleep 30

# Check if everything is running
docker-compose ps
```

### 4. Initialize with Sample Data

```bash
# Initialize database with sample groups and admin user
docker-compose exec auth-api python group_based_crud_operations.py --init-defaults

# Verify the setup
curl http://localhost:8000/system/ping
```

### 5. Test Your First Login

```bash
# Get the project hash from the admin user
PROJECT_HASH=$(docker-compose exec auth-api python -c "
from group_based_crud_operations import ProjectCRUD
projects = ProjectCRUD.read_all()
print(projects[0].project_hash if projects else 'No projects found')
")

# Login with the admin user
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=$PROJECT_HASH"
```

**🎉 Success!** Your group-based authentication system is running.

---

## ⚡ Option 2: Manual Setup

### 1. Install Dependencies

```bash
git clone <repository-url>
cd api.auth
python -m venv .venv
source .venv/bin/activate  # Linux/Mac
pip install -r requirements.txt
```

### 2. Setup Database

```bash
# Create MySQL database
mysql -u root -p -e "CREATE DATABASE magic_auth_groups;"

# Initialize schema
mysql -u root -p magic_auth_groups < new_database_schema.sql
```

### 3. Configure Environment

```bash
cat > .env << EOF
DB_HOST=localhost
DB_USER=root
DB_MYSQL_PASSWORD=your_mysql_password
DB_DATABASE=magic_auth_groups
DB_REDIS_PASSWORD=your_redis_password
GROUP_SYSTEM_ENABLED=true
EOF
```

### 4. Start Services and Initialize

```bash
# Start the API
python -m uvicorn src.main:app --reload --host 0.0.0.0 --port 8000 &

# Initialize with sample data
python group_based_crud_operations.py --init-defaults

# Test the API
curl http://localhost:8000/system/ping
```

---

## 🧪 Quick Test

### Test the System

```bash
# 1. Check system health
curl http://localhost:8000/system/health

# 2. Check available user groups
curl http://localhost:8000/system/info

# 3. Test login (replace PROJECT_HASH with actual value)
curl -X POST "http://localhost:8000/auth/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=YOUR_PROJECT_HASH"
```

### Expected Response

```json
{
  "success": true,
  "message": "Login successful",
  "session_token": "eyJ0eXAiOiJKV1QiLCJhbGc...",
  "user": {
    "username": "admin",
    "email": "admin@example.com",
    "user_groups": ["administrators"]
  },
  "project": {
    "project_name": "Default Project",
    "permissions": ["admin", "read", "write", "delete"]
  }
}
```

---

## 🎯 Next Steps

### Immediate Actions
1. **Change default passwords** in production
2. **Review the [Setup Guide](setup-guide.md)** for detailed configuration
3. **Explore the [API Documentation](api/authentication.md)** for integration

### Create Your First Group

```bash
# Create a new user group
curl -X POST "http://localhost:8000/admin/user-groups" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"group_name": "developers", "description": "Development team"}'

# Create a new project
curl -X POST "http://localhost:8000/projects" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/json" \
  -d '{"project_name": "My First Project", "project_description": "A test project"}'
```

### Initialize RBAC
The system includes a project-specific RBAC module. After logging in, you can initialize it for your project.

```bash
# Initialize RBAC for your project (replace with your project hash and token)
curl -X POST "http://localhost:8000/rbac/projects/YOUR_PROJECT_HASH/initialize" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

### Learn More
- **[API Authentication](api/authentication.md)** - Authentication endpoints
- **[Admin API](api/admin.md)** - Group management
- **[Architecture Overview](architecture.md)** - System design

---

## 🆘 Quick Troubleshooting

### Common Issues

| Problem | Quick Fix |
|---------|-----------|
| Port 8000 already in use | Use `docker-compose down` or change port |
| Database connection failed | Check MySQL is running and credentials are correct |
| Redis connection failed | Check Redis is running and password is correct |
| Empty response from API | Wait 30 seconds for services to initialize |

### Verification Commands

```bash
# Check if services are running
docker-compose ps

# Check API logs
docker-compose logs auth-api

# Check database
docker-compose exec mysql mysql -u root -p magic_auth_groups -e "SHOW TABLES;"

# Check Redis
docker-compose exec redis redis-cli ping
```

---

## 📋 What You've Accomplished

✅ **Group-Based Authentication System** running locally  
✅ **Admin user** created with full permissions  
✅ **Default user and project groups** initialized  
✅ **Sample project** created and accessible  
✅ **API endpoints** ready for integration  

**🎉 Ready to integrate!** Your system is now ready for development and testing.

---

**Next:** Continue with the [Setup Guide](setup-guide.md) for production configuration or jump to [API Documentation](api/authentication.md) to start integrating. 