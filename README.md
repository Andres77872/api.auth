# Enhanced Multi-Project Authentication API

A powerful, modern authentication system with multi-project support, user isolation, and flexible permission management.

## 🚀 Features

- **🏢 Project Isolation**: Users are isolated by project by default
- **🔄 Cross-Project Access**: Same user can access multiple projects with appropriate permissions
- **👥 Group-Based Permissions**: Flexible role management with customizable permissions
- **🔀 Project Switching**: Seamless switching between projects without re-authentication
- **🔒 Enhanced Security**: Session tokens with Redis-backed session management
- **📊 Audit Trail**: Complete tracking of access grants, revocations, and user activities
- **⚡ High Performance**: Redis caching with database persistence
- **🛡️ Secure**: Password hashing, session management, and permission-based access control

## 🏗️ Architecture

```
┌─────────────────┐    ┌─────────────────┐    ┌─────────────────┐
│   Global User   │────│ User-Project    │────│     Project     │
│                 │    │   Relationship  │    │                 │
├─────────────────┤    ├─────────────────┤    ├─────────────────┤
│ • Username      │    │ • Access Level  │    │ • Project Hash  │
│ • Email         │    │ • Granted Date  │    │ • Name          │
│ • Password      │    │ • Unique Hash   │    │ • Description   │
│ • User Hash     │    │ • Groups        │    │ • Groups        │
└─────────────────┘    └─────────────────┘    └─────────────────┘
                                │
                                ▼
                       ┌─────────────────┐
                       │     Groups      │
                       │                 │
                       ├─────────────────┤
                       │ • admin         │
                       │ • user          │
                       │ • readonly      │
                       │ • custom...     │
                       └─────────────────┘
```

## 🚀 Quick Start

### 1. Installation

```bash
# Clone the repository
git clone <repository-url>
cd api.auth

# Install dependencies
pip install -r requirements.txt
```

### 2. Environment Setup

Create a `.env` file:

```bash
DB_MYSQL_PASSWORD=your_mysql_password
DB_REDIS_PASSWORD=your_redis_password

# Optional: Custom database settings
DB_HOST=192.168.1.90
DB_USER=root
DB_DATABASE=magic_auth_enhanced
```

### 3. Database Setup

```bash
# Initialize the database with sample data
python setup_enhanced_auth.py --with-sample-data

# Or just create the schema
python setup_enhanced_auth.py
```

### 4. Start the Application

```bash
# Development mode
python -m uvicorn src.main:app --reload

# Production mode
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### 5. Access the API

- **Interactive Docs**: http://localhost:8000/docs
- **System Info**: http://localhost:8000/system/info
- **Health Check**: http://localhost:8000/ping

## 📡 API Endpoints

### Authentication Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/user/login` | Login to a specific project |
| `POST` | `/user/register` | Register user or grant project access |
| `GET` | `/user/profile` | Get user profile and project access |
| `POST` | `/user/switch-project` | Switch to different project |
| `GET` | `/user/validate` | Validate session token |

### Project Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/user/create-project` | Create new project (admin only) |
| `POST` | `/user/grant-access` | Grant user access to project |
| `POST` | `/user/check-availability` | Check username/email availability |

### Access Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| `HEAD` | `/access` | Validate token and permissions |

## 🔐 Authentication Flow

### 1. Login Example

```bash
curl -X POST "http://localhost:8000/user/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=YOUR_PROJECT_HASH"
```

**Response:**
```json
{
  "success": true,
  "session_token": "abc123...",
  "user": {
    "user_hash": "def456...",
    "user_id": 1,
    "user_project_id": 1
  },
  "project": {
    "project_hash": "ghi789...",
    "project_name": "My Project",
    "project_id": 1
  },
  "access": {
    "groups": ["admin"],
    "permissions": ["admin", "read", "write", "delete", "manage_users"]
  },
  "available_projects": [...]
}
```

### 2. Using the Token

```bash
curl -X GET "http://localhost:8000/user/profile" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

### 3. Project Switching

```bash
curl -X POST "http://localhost:8000/user/switch-project" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "project_hash=ANOTHER_PROJECT_HASH"
```

## 👥 User Management

### Default Groups

- **`admin`**: Full project control, user management, project creation
- **`user`**: Read/write access to project resources
- **`readonly`**: Read-only access to project resources

### Permission System

Permissions are stored as JSON arrays in groups:

```json
{
  "admin": ["admin", "read", "write", "delete", "manage_users", "manage_groups"],
  "user": ["read", "write"],
  "readonly": ["read"]
}
```

### Creating Custom Groups

Groups are project-specific and can be customized through the database or API.

## 🗄️ Database Schema

The system uses 6 main tables:

- **`users`**: Global user accounts
- **`projects`**: Project/application registry  
- **`user_projects`**: User access to projects
- **`user_groups`**: Project-specific groups and permissions
- **`user_project_groups`**: User membership in groups
- **`user_sessions`**: Session tracking and management

For detailed schema information, see [DATABASE_SCHEMA.md](DATABASE_SCHEMA.md).

## 🔧 Configuration

### Database Configuration

```python
# src/Util/db_enhanced.py
connectionDB = {
    "host": os.environ.get("DB_HOST", "192.168.1.90"),
    "user": os.environ.get("DB_USER", "root"),
    "password": os.environ.get("DB_MYSQL_PASSWORD"),
    "database": os.environ.get("DB_DATABASE", "magic_auth_enhanced")
}
```

### Redis Configuration

```python
client = redis.StrictRedis(
    host=os.environ.get("DB_HOST", "192.168.1.90"),
    port=6379,
    db=0,
    password=os.environ.get("DB_REDIS_PASSWORD")
)
```

## 🐳 Docker Support

```dockerfile
# Dockerfile included
FROM python:3.11-slim

WORKDIR /app
COPY requirements.txt .
RUN pip install -r requirements.txt

COPY . .
EXPOSE 8000

CMD ["python", "-m", "uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000"]
```

## 🧪 Testing

### Sample Data

If you used `--with-sample-data` during setup:

```bash
# Admin user (access to all projects)
Username: admin
Password: admin123

# Regular users (access to first project only)
Username: john_doe
Password: password123

Username: jane_smith  
Password: password456
```

### API Testing

Use the included `test_main.http` file with REST client tools or create your own tests.

## 📚 Documentation

- **[Database Schema](DATABASE_SCHEMA.md)**: Complete database documentation
- **[Enhanced Auth Guide](ENHANCED_AUTH_README.md)**: Detailed setup and usage instructions
- **Interactive API Docs**: Available at `/docs` when running

## 🆘 Troubleshooting

### Common Issues

1. **Database Connection Failed**
   ```bash
   # Test database connection
   python -c "from src.Util.db import get_connection; print('✓ Connected' if get_connection() else '✗ Failed')"
   ```

2. **Redis Connection Failed**
   ```bash
   # Test Redis connection  
   python -c "from src.Util.db import client; client.ping(); print('✓ Redis OK')"
   ```

3. **Token Validation Issues**
   - Check token format and expiration
   - Verify project_hash matches user's project access
   - Ensure session hasn't expired (default: 3 days)

### Debug Mode

Enable debug logging:

```python
import logging
logging.basicConfig(level=logging.DEBUG)
```

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/amazing-feature`)
3. Commit your changes (`git commit -m 'Add amazing feature'`)
4. Push to the branch (`git push origin feature/amazing-feature`)
5. Open a Pull Request

## 📄 License

This project is licensed under the MIT License - see the LICENSE file for details.

## 👨‍💻 Author

**Andrés**
- Website: https://arizmendi.io
- Email: andres@arz.ai

---

## 🎯 Next Steps

1. **Set up your projects** and user groups
2. **Integrate with your applications** using the REST API
3. **Customize permissions** based on your needs
4. **Monitor and maintain** using the built-in logging and audit trails

**🎉 Happy coding with your enhanced authentication system!** 