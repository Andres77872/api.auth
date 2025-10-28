# Activity Logging Quick Reference

One-page reference for developers working with the Activity Logging System.

---

## 🚀 Installation (3 Commands)

```bash
mysql -u root -p < schemas/tables/08_activity_logging_tables.sql
mysql -u root -p < schemas/stored_procedures/11_activity_logging.sql
mysql -u root -p < schemas/triggers/01_activity_logging_triggers.sql
mysql -u root -p < schemas/triggers/02_permission_activity_triggers.sql
```

---

## 📝 When to Log Manually

| Event | Code | When |
|-------|------|------|
| User login | `user_login` | After successful auth |
| Failed login | `user_login_failed` | After auth failure |
| Session expired | `session_expired` | Cleanup job |
| Project member add | `project_member_add` | Membership endpoint |
| Project member remove | `project_member_remove` | Membership endpoint |
| Bulk operations | `bulk_*` | After batch complete |
| Admin actions | `admin_action` | Custom operations |
| Security alerts | `security_alert` | Suspicious activity |

**Everything else**: Logged automatically by triggers!

---

## 💻 Python Code Snippets

### Basic Activity Logging

```python
from src.Util.activity_logger import ActivityLogger

# Simple log
await ActivityLogger.log_activity(
    user_id="user-123",
    activity_code="user_login",
    details="User logged in",
    ip_address="192.168.1.1",
    metadata={"method": "password"}
)
```

### Login Success

```python
await ActivityLogger.log_login(
    user_id=user.id,
    username=user.username,
    ip_address=request.client.host,
    user_agent=request.headers.get("user-agent"),
    project_id=project_id
)
```

### Login Failed

```python
await ActivityLogger.log_failed_login(
    username=credentials.username,
    ip_address=request.client.host,
    user_agent=request.headers.get("user-agent"),
    reason="Invalid credentials"
)
```

### Bulk Operation

```python
await ActivityLogger.log_bulk_operation(
    user_id=current_user.id,
    operation_type="bulk_user_update",
    target_count=len(user_ids),
    success_count=success_count,
    details="Bulk updated users",
    metadata={"changes": changes}
)
```

---

## 🔍 Querying Activities

### Get Recent Activities

```sql
CALL sp_get_activity_logs(
    50,          -- limit
    0,           -- offset
    NULL,        -- user_id (NULL = all)
    NULL,        -- project_id (NULL = all)
    NULL,        -- activity_code (NULL = all)
    7            -- days
);
```

### Get User Activity Summary

```sql
CALL sp_get_user_activity_summary('user-123', 30);
```

### Get Security Events

```sql
CALL sp_get_recent_security_events(24, 100);  -- Last 24 hours, max 100
```

### Get Activity Statistics

```sql
CALL sp_get_activity_stats(NULL, 30);  -- All projects, 30 days
```

### Direct Query (Custom)

```sql
SELECT al.*, u.username, ac.activity_name
FROM activity_logs al
LEFT JOIN users u ON al.user_id = u.id
LEFT JOIN activity_catalog ac ON al.activity_catalog_id = ac.id
WHERE al.severity_level IN ('warning', 'critical')
  AND al.created_at >= DATE_SUB(NOW(), INTERVAL 24 HOUR)
ORDER BY al.created_at DESC;
```

---

## 📊 Activity Categories & Codes

| Category | Example Codes |
|----------|--------------|
| **authentication** | user_login, user_logout, user_login_failed |
| **user_management** | user_registration, user_update, user_deleted |
| **project_management** | project_creation, project_archived, project_delete |
| **group_management** | group_creation, user_group_assign, group_project_access_granted |
| **permission_management** | permission_grant, role_assigned, permission_group_assigned |
| **bulk_operations** | bulk_role_assignment, bulk_user_delete |
| **admin** | admin_action |
| **security** | security_alert |

See `ACTIVITY_EVENTS_CATALOG.md` for all 40 codes.

---

## 🎯 Severity Levels

- **info**: Normal operations (55% of events)
- **warning**: Attention required (37.5% of events)
- **critical**: High-impact operations (7.5% of events)

---

## ✅ What's Automatic (No Code Needed)

- ✅ User CREATE, UPDATE, DELETE
- ✅ Project CREATE, UPDATE, DELETE
- ✅ User Group CREATE, UPDATE, DELETE
- ✅ Group membership changes
- ✅ Group-project access changes
- ✅ Role CREATE, UPDATE, DELETE
- ✅ Permission CREATE, UPDATE, DELETE
- ✅ Permission group CREATE, UPDATE, DELETE
- ✅ All permission assignments
- ✅ Session creation
- ✅ Session deactivation (logout)

**Total: 27 events automatic, 13 manual**

---

## 🔧 Common Tasks

### Check Installation

```sql
-- Activity types
SELECT COUNT(*) FROM activity_catalog;  -- Should be 40

-- Triggers installed
SHOW TRIGGERS FROM magic_auth LIKE 'trg_after_%';  -- Should be 28

-- Test logging
INSERT INTO users (...) VALUES (...);
SELECT * FROM activity_logs ORDER BY created_at DESC LIMIT 1;
```

### Cleanup Old Logs

```sql
-- Dry run (preview)
CALL sp_cleanup_old_activity_logs(90, TRUE);

-- Execute cleanup
CALL sp_cleanup_old_activity_logs(90, FALSE);
```

### Monitor Security

```python
# Get critical events from last 24 hours
events = await get_recent_activities(
    activity_code=None,
    days=1
)
critical = [e for e in events if e['severity_level'] == 'critical']
```

---

## 🐛 Troubleshooting

### Triggers Not Logging?

```sql
-- Check triggers exist
SHOW TRIGGERS FROM magic_auth;

-- Check activity catalog
SELECT * FROM activity_catalog WHERE activity_code = 'user_registration';

-- Test manually
CALL sp_log_activity(
    CONCAT('test-', UUID()),
    'user-123',
    'user_login',
    'Test log',
    NULL, NULL, NULL, NULL, NULL, NULL
);
```

### No Results in Query?

```sql
-- Check if logs exist
SELECT COUNT(*) FROM activity_logs;

-- Check date range
SELECT MIN(created_at), MAX(created_at) FROM activity_logs;

-- Verify user_id
SELECT DISTINCT user_id FROM activity_logs LIMIT 10;
```

---

## 📈 Performance Tips

1. **Use indexes**: All critical paths are indexed
2. **Limit results**: Always use LIMIT in queries
3. **Filter by date**: Narrow down time ranges
4. **Cleanup regularly**: Run `sp_cleanup_old_activity_logs` monthly
5. **Use stored procedures**: Faster than raw queries

---

## 🔒 Security Best Practices

1. ✅ Never log passwords or tokens
2. ✅ Filter sensitive fields from metadata
3. ✅ Restrict log access to admins only
4. ✅ Implement retention policies
5. ✅ Monitor critical events daily
6. ✅ Alert on security patterns

---

## 📚 Full Documentation

| Document | Purpose |
|----------|---------|
| README.md | System overview |
| ACTIVITY_EVENTS_CATALOG.md | All 40 event types |
| IMPLEMENTATION_GUIDE.md | Complete setup guide |
| CRUD_OPERATIONS_MAPPING.md | Entity mapping |
| USAGE_EXAMPLES.md | Code examples |
| SYSTEM_ANALYSIS.md | Technical details |
| SUMMARY.md | Project overview |
| QUICK_REFERENCE.md | This document |

---

## 🎓 Key Concepts

**Activity Logs** = User actions (user created, role assigned)  
**API Audit Logs** = HTTP requests (POST /api/users)

Use **both** for complete visibility!

**Triggers** = Automatic logging (no code)  
**Manual** = Explicit logging (requires code)

Prefer triggers when possible!

---

## 💡 Pro Tips

1. **Start Simple**: Let triggers handle most logging
2. **Add Context**: Enhance automatic logs with business details when needed
3. **Monitor Daily**: Check security events every day
4. **Clean Regularly**: Schedule monthly cleanup jobs
5. **Export for Compliance**: Generate reports quarterly
6. **Test Thoroughly**: Verify triggers after schema changes

---

## 📞 Need Help?

- **Setup Issues**: See `IMPLEMENTATION_GUIDE.md`
- **Event Questions**: See `ACTIVITY_EVENTS_CATALOG.md`
- **Code Examples**: See `USAGE_EXAMPLES.md`
- **Performance**: See `SYSTEM_ANALYSIS.md`
- **CRUD Mapping**: See `CRUD_OPERATIONS_MAPPING.md`

---

**Last Updated**: October 26, 2025  
**Version**: 1.0
