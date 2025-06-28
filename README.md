# Enhanced Multi-Project Authentication API

> A powerful, modern authentication system with multi-project support, user isolation, and flexible permission management.

## 🚀 Features

- **🏢 Project Isolation**: Users are isolated by project by default
- **🔄 Cross-Project Access**: Same user can access multiple projects with same credentials
- **👥 Group-Based Permissions**: Flexible role management with customizable permissions
- **🔀 Project Switching**: Seamless switching between projects without re-authentication
- **🔒 Enhanced Security**: Session tokens with Redis-backed session management
- **📊 Complete Project CRUD**: Full project lifecycle management with API
- **🛡️ Audit Trail**: Complete tracking of access grants, revocations, and activities
- **⚡ High Performance**: Redis caching with database persistence

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
```

## 🚀 Quick Start

### 1. Installation

```bash
# Clone and install
git clone <repository-url>
cd api.auth
pip install -r requirements.txt
```

### 2. Environment Setup

Create a `.env` file:

```bash
DB_MYSQL_PASSWORD=your_mysql_password
DB_REDIS_PASSWORD=your_redis_password
DB_HOST=192.168.1.90
DB_DATABASE=magic_auth_enhanced
```

### 3. Initialize Database

```bash
# Create database with sample data
python setup_enhanced_auth.py --with-sample-data
```

### 4. Start Application

```bash
# Development
python -m uvicorn src.main:app --reload

# Production
python -m uvicorn src.main:app --host 0.0.0.0 --port 8000
```

### 5. Access the API

- **Interactive Docs**: http://localhost:8000/docs
- **System Info**: http://localhost:8000/system/info
- **Health Check**: http://localhost:8000/ping

## 📡 API Endpoints

### Authentication & User Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/user/login` | Login to a specific project |
| `POST` | `/user/register` | Register user or grant project access |
| `POST` | `/user/check-availability` | Check username/email availability |
| `GET` | `/user/profile` | Get user profile and project access |
| `POST` | `/user/switch-project` | Switch to different project |
| `GET` | `/user/validate` | Validate session token |

### Project Management

| Method | Endpoint | Description |
|--------|----------|-------------|
| `POST` | `/user/create-project` | Create new project |
| `GET` | `/user/projects` | List projects with pagination/search |
| `GET` | `/user/projects/{hash}` | Get project details |
| `PUT` | `/user/projects/{hash}` | Update project |
| `DELETE` | `/user/projects/{hash}` | Delete project |
| `GET` | `/user/projects/{hash}/stats` | Get project statistics |
| `POST` | `/user/grant-access` | Grant user access to project |

### Access Control

| Method | Endpoint | Description |
|--------|----------|-------------|
| `HEAD` | `/access` | Validate token and permissions |

## 🔐 Quick Example

```bash
# Login
curl -X POST "http://localhost:8000/user/login" \
  -H "Content-Type: application/x-www-form-urlencoded" \
  -d "username=admin&password=admin123&project_hash=YOUR_PROJECT_HASH"

# Use the returned session_token for authenticated requests
curl -X GET "http://localhost:8000/user/profile" \
  -H "Authorization: Bearer YOUR_SESSION_TOKEN"
```

## 🧪 Testing

If you used `--with-sample-data` during setup:

```bash
# Admin user (access to all projects)
Username: admin / Password: admin123

# Regular users (access to first project)
Username: john_doe / Password: password123
Username: jane_smith / Password: password456
```

## 🏗️ Modular Database Architecture

The system uses a clean modular structure:

```
src/Util/db/
├── __init__.py         # Main interface - imports all functions
├── db_enhanced.py      # Core authentication (login, register, session)
├── db_users.py         # User management (CRUD, sessions, groups)
└── db_projects.py      # Project management (CRUD, stats, groups)
```

## 📚 Documentation

| Document | Description |
|----------|-------------|
| **[Setup Guide](docs/setup-guide.md)** | Complete setup and configuration guide |
| **[API Reference](docs/api-reference.md)** | Detailed API documentation with examples |
| **[Database Schema](docs/database-schema.md)** | Complete database structure and relationships |
| **[Architecture Guide](docs/architecture.md)** | System architecture and design decisions |
| **[Migration Guide](docs/migration-guide.md)** | Migrating from legacy systems |

## 🔧 Configuration

### Database Configuration

```python
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

## 🆘 Troubleshooting

### Common Issues

1. **Database Connection**
   ```bash
   python -c "from src.Util.db import get_connection; print('✓ Connected' if get_connection() else '✗ Failed')"
   ```

2. **Redis Connection**
   ```bash
   python -c "from src.Util.db import client; client.ping(); print('✓ Redis OK')"
   ```

3. **Module Structure**
   ```bash
   python test_modular_structure.py
   ```

## 👨‍💻 Author

**Andrés**
- Website: https://arizmendi.io
- Email: andres@arz.ai

---

**💡 For detailed documentation, examples, and advanced configuration, see the [docs/](docs/) folder.** 