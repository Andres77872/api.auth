"""
System Metrics Utility

Provides system performance monitoring, metrics collection,
and health status tracking for the authentication system.
"""

import time
import json
from datetime import datetime, timezone
from typing import Dict, Any

import psutil

from src.Util.db import count_users, count_projects, count_active_sessions
from src.Util.db_config import get_connection, redis_client
from src.Util.auth_constants import EMAIL_WORKER_WAKE_PREFIX
from src.Util.email.config import load_email_config, validate_email_readiness


class SystemMetrics:
    """
    System metrics collection and monitoring
    """

    @staticmethod
    def get_system_overview() -> Dict[str, Any]:
        """
        Get comprehensive system overview
        
        Returns:
            System overview with health and performance data
        """
        try:
            # Get system stats
            cpu_percent = psutil.cpu_percent(interval=1)
            memory = psutil.virtual_memory()
            disk = psutil.disk_usage('/')

            # Get database stats
            db_health = SystemMetrics.get_database_health()

            # Get Redis stats
            redis_health = SystemMetrics.get_redis_health()

            # Get application metrics
            app_metrics = SystemMetrics.get_application_metrics()

            # Calculate overall health score
            health_score = SystemMetrics.calculate_health_score(
                cpu_percent, memory.percent, db_health, redis_health
            )

            return {
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "health_score": health_score,
                "status": "healthy" if health_score >= 80 else ("degraded" if health_score >= 60 else "unhealthy"),
                "system": {
                    "cpu_usage": cpu_percent,
                    "memory_usage": memory.percent,
                    "memory_available": memory.available // (1024 ** 2),  # MB
                    "disk_usage": disk.percent,
                    "disk_free": disk.free // (1024 ** 3),  # GB
                    "uptime": SystemMetrics.get_system_uptime()
                },
                "database": db_health,
                "redis": redis_health,
                "application": app_metrics
            }

        except Exception as e:
            return {
                "timestamp": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "health_score": 0,
                "status": "error",
                "error": str(e)
            }

    @staticmethod
    def get_database_health() -> Dict[str, Any]:
        """Get database health and performance metrics"""
        try:
            start_time = time.time()

            with get_connection() as con:
                cur = con.cursor()

                # Test basic connectivity
                cur.execute("SELECT 1")
                cur.fetchone()

                # Get connection count
                cur.execute("SHOW STATUS LIKE 'Threads_connected'")
                connections = cur.fetchone()

                # Get database size
                cur.execute(
                    "SELECT SUM(data_length + index_length) / 1024 / 1024 AS size_mb FROM information_schema.tables WHERE table_schema = DATABASE()")
                size_result = cur.fetchone()

                # Get table counts
                cur.execute("SELECT COUNT(*) FROM information_schema.tables WHERE table_schema = DATABASE()")
                table_count = cur.fetchone()

                response_time = (time.time() - start_time) * 1000  # ms

                return {
                    "status": "healthy",
                    "response_time_ms": round(response_time, 2),
                    "connections": connections[1] if connections else 0,
                    "size_mb": round(size_result[0], 2) if size_result and size_result[0] else 0,
                    "table_count": table_count[0] if table_count else 0,
                    "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
                }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            }

    @staticmethod
    def get_redis_health() -> Dict[str, Any]:
        """Get Redis health and performance metrics"""
        try:
            start_time = time.time()

            # Test connectivity
            redis_client.ping()

            # Get Redis info
            info = redis_client.info()

            response_time = (time.time() - start_time) * 1000  # ms

            return {
                "status": "healthy",
                "response_time_ms": round(response_time, 2),
                "memory_used": info.get('used_memory_human', 'unknown'),
                "connected_clients": info.get('connected_clients', 0),
                "total_commands": info.get('total_commands_processed', 0),
                "uptime_seconds": info.get('uptime_in_seconds', 0),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            }

        except Exception as e:
            return {
                "status": "unhealthy",
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
            }

    @staticmethod
    def get_application_metrics() -> Dict[str, Any]:
        """Get application-specific metrics"""
        try:
            # Get entity counts
            total_users = count_users()
            total_projects = count_projects()
            active_sessions = count_active_sessions()

            # Get user type breakdown
            from src.Util.db import count_users as count_users_by_type
            user_breakdown = {
                "root": count_users_by_type(user_type='root'),
                "admin": count_users_by_type(user_type='admin'),
                "consumer": count_users_by_type(user_type='consumer')
            }

            # Get recent activity (last 24 hours)
            from src.Util.db import get_recent_activity_count
            recent_activity = get_recent_activity_count(days=1)

            return {
                "entities": {
                    "total_users": total_users,
                    "total_projects": total_projects,
                    "active_sessions": active_sessions,
                    "user_breakdown": user_breakdown
                },
                "activity": {
                    "last_24h": recent_activity,
                    "avg_per_hour": round(recent_activity / 24, 1)
                },
                "performance": {
                    "sessions_per_user": round(active_sessions / max(total_users, 1), 2),
                    "projects_per_user": round(total_projects / max(total_users, 1), 2)
                }
            }

        except Exception as e:
            return {
                "status": "error",
                "error": str(e)
            }

    @staticmethod
    def get_email_provider_health() -> Dict[str, Any]:
        """Return email provider readiness without contacting external networks."""

        try:
            config = load_email_config(validate_real_send_guard=False)
            readiness = validate_email_readiness(config)
            return {
                "status": readiness.status,
                "provider": readiness.provider or config.provider,
                "delivery_enabled": config.delivery_enabled,
                "ready": readiness.ready,
                "missing": readiness.missing,
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "not_ready",
                "ready": False,
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_email_outbox_metrics() -> Dict[str, Any]:
        """Return durable email outbox depth/DLQ/success metrics."""

        try:
            from src.Util.db import db_email

            health = db_email.get_email_outbox_health()
            pending = int(health.get("pending_count") or 0)
            processing = int(health.get("processing_count") or 0)
            retry = int(health.get("retry_count") or 0)
            dead = int(health.get("dead_count") or 0)
            sent = int(health.get("sent_count") or 0)
            terminal = int(health.get("terminal_count") or 0)
            denominator = sent + dead
            success_ratio = round(sent / denominator, 4) if denominator else None
            return {
                "status": "healthy",
                "queue_depth": pending + retry,
                "pending_count": pending,
                "processing_count": processing,
                "retry_count": retry,
                "dlq_depth": dead,
                "sent_count": sent,
                "terminal_count": terminal,
                "success_ratio": success_ratio,
                "oldest_pending_age_seconds": health.get("oldest_pending_age_seconds"),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "queue_depth": 0,
                "dlq_depth": 0,
                "success_ratio": None,
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def email_worker_heartbeat_key(worker_id: str) -> str:
        safe_worker = str(worker_id or "unknown").replace(" ", "_")[:128]
        return f"{EMAIL_WORKER_WAKE_PREFIX}heartbeat:{safe_worker}"

    @staticmethod
    def record_email_worker_heartbeat(
        worker_id: str,
        *,
        counters: Dict[str, Any] | None = None,
        ttl_seconds: int = 120,
    ) -> bool:
        """Record worker heartbeat/counters in Redis without touching provider APIs."""

        try:
            payload = {
                "worker_id": worker_id,
                "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "counters": dict(counters or {}),
            }
            return bool(
                redis_client.set(
                    SystemMetrics.email_worker_heartbeat_key(worker_id),
                    json.dumps(payload, sort_keys=True, default=str),
                    ex=max(1, int(ttl_seconds)),
                )
            )
        except Exception:
            return False

    @staticmethod
    def get_email_worker_metrics() -> Dict[str, Any]:
        """Return worker heartbeat/counter visibility from Redis."""

        try:
            config = load_email_config(validate_real_send_guard=False)
            heartbeats = []
            for key in redis_client.scan_iter(match=f"{EMAIL_WORKER_WAKE_PREFIX}heartbeat:*", count=100):
                raw = redis_client.get(key)
                if isinstance(raw, bytes):
                    raw = raw.decode("utf-8", errors="ignore")
                if not raw:
                    continue
                try:
                    decoded = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    heartbeats.append(decoded)

            latest = max((item.get("recorded_at", "") for item in heartbeats), default=None)
            status = "healthy" if heartbeats else ("disabled" if not config.delivery_enabled else "unknown")
            return {
                "status": status,
                "delivery_enabled": config.delivery_enabled,
                "heartbeat_count": len(heartbeats),
                "latest_heartbeat": latest,
                "workers": heartbeats[:10],
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "heartbeat_count": 0,
                "latest_heartbeat": None,
                "workers": [],
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_email_metrics() -> Dict[str, Any]:
        """Return email delivery metrics grouped for health/ops surfaces."""

        provider = SystemMetrics.get_email_provider_health()
        outbox = SystemMetrics.get_email_outbox_metrics()
        worker = SystemMetrics.get_email_worker_metrics()
        return {
            "provider": provider,
            "outbox": outbox,
            "worker": worker,
            "metrics": {
                "email_queue_depth": outbox.get("queue_depth", 0),
                "email_oldest_pending_age_seconds": outbox.get("oldest_pending_age_seconds"),
                "email_dlq_depth": outbox.get("dlq_depth", 0),
                "email_send_success_ratio": outbox.get("success_ratio"),
                "email_provider_send_p95_ms": None,
                "email_webhook_invalid_signature_count": None,
            },
        }

    @staticmethod
    def get_user_statistics(date_range: int = 30) -> Dict[str, Any]:
        """Get user statistics over a date range"""
        try:
            with get_connection() as con:
                cur = con.cursor()

                # Total users by type
                cur.execute("""
                            SELECT user_type, COUNT(*) as count
                            FROM users
                            WHERE is_active = 1
                            GROUP BY user_type
                            """)
                user_types = dict(cur.fetchall())

                # New users in date range
                cur.execute("""
                            SELECT COUNT(*)
                            FROM users
                            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                              AND is_active = 1
                            """, [date_range])
                new_users = cur.fetchone()[0]

                # Active users (users with recent activity)
                cur.execute("""
                            SELECT COUNT(DISTINCT user_id)
                            FROM activity_logs
                            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                            """, [date_range])
                active_users_result = cur.fetchone()
                active_users = active_users_result[0] if active_users_result else 0

                # Growth rate calculation
                total_users = sum(user_types.values())
                growth_rate = (new_users / max(total_users - new_users, 1)) * 100

                return {
                    "total_users": total_users,
                    "user_types": user_types,
                    "new_users": new_users,
                    "active_users": active_users,
                    "growth_rate": round(growth_rate, 2),
                    "date_range_days": date_range,
                    "activity_rate": round((active_users / max(total_users, 1)) * 100, 2)
                }

        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def get_project_statistics(date_range: int = 30) -> Dict[str, Any]:
        """Get project statistics over a date range"""
        try:
            with get_connection() as con:
                cur = con.cursor()

                # Total projects
                cur.execute("SELECT COUNT(*) FROM projects WHERE is_active = 1")
                total_projects = cur.fetchone()[0]

                # New projects in date range
                cur.execute("""
                            SELECT COUNT(*)
                            FROM projects
                            WHERE project_created >= DATE_SUB(NOW(), INTERVAL %s DAY)
                              AND is_active = 1
                            """, [date_range])
                new_projects = cur.fetchone()[0]

                # Projects with activity
                cur.execute("""
                            SELECT COUNT(DISTINCT project_id)
                            FROM activity_logs
                            WHERE created_at >= DATE_SUB(NOW(), INTERVAL %s DAY)
                              AND project_id IS NOT NULL
                            """, [date_range])
                active_projects_result = cur.fetchone()
                active_projects = active_projects_result[0] if active_projects_result else 0

                # Average members per project
                cur.execute("""
                            SELECT AVG(member_count)
                            FROM (SELECT COUNT(*) as member_count
                                  FROM user_projects up
                                           JOIN projects p ON up.project_id = p.id
                                  WHERE up.is_active = 1
                                    AND p.is_active = 1
                                  GROUP BY p.id) AS project_members
                            """)
                avg_members_result = cur.fetchone()
                avg_members = round(avg_members_result[0], 1) if avg_members_result and avg_members_result[0] else 0

                return {
                    "total_projects": total_projects,
                    "new_projects": new_projects,
                    "active_projects": active_projects,
                    "avg_members_per_project": avg_members,
                    "date_range_days": date_range,
                    "utilization_rate": round((active_projects / max(total_projects, 1)) * 100, 2)
                }

        except Exception as e:
            return {"error": str(e)}

    @staticmethod
    def calculate_health_score(cpu_percent: float, memory_percent: float,
                               db_health: Dict, redis_health: Dict) -> int:
        """Calculate overall system health score (0-100)"""
        score = 100

        # CPU penalty
        if cpu_percent > 80:
            score -= 20
        elif cpu_percent > 60:
            score -= 10

        # Memory penalty
        if memory_percent > 90:
            score -= 20
        elif memory_percent > 75:
            score -= 10

        # Database penalty
        if db_health.get("status") != "healthy":
            score -= 30
        elif db_health.get("response_time_ms", 0) > 1000:
            score -= 10

        # Redis penalty
        if redis_health.get("status") != "healthy":
            score -= 20
        elif redis_health.get("response_time_ms", 0) > 500:
            score -= 5

        return max(0, score)

    @staticmethod
    def get_system_uptime() -> str:
        """Get system uptime in human readable format"""
        try:
            boot_time = psutil.boot_time()
            uptime_seconds = time.time() - boot_time

            days = int(uptime_seconds // 86400)
            hours = int((uptime_seconds % 86400) // 3600)
            minutes = int((uptime_seconds % 3600) // 60)

            return f"{days}d {hours}h {minutes}m"

        except Exception:
            return "unknown"

    @staticmethod
    def get_api_metrics() -> Dict[str, Any]:
        """Get API performance metrics"""
        try:
            # This would typically come from request logging
            # For now, return basic metrics
            return {
                "total_requests": 0,  # Would be tracked in real implementation
                "avg_response_time": 0,  # Would be calculated from logs
                "error_rate": 0,  # Would be calculated from error logs
                "active_endpoints": 55,  # Number of API endpoints
                "cache_hit_rate": 0  # Would be calculated from cache stats
            }
        except Exception as e:
            return {"error": str(e)}


# Global instance
system_metrics = SystemMetrics()


# Convenience functions
def get_system_overview() -> Dict[str, Any]:
    """Get comprehensive system overview"""
    return system_metrics.get_system_overview()


def get_user_statistics(date_range: int = 30) -> Dict[str, Any]:
    """Get user statistics"""
    return system_metrics.get_user_statistics(date_range)


def get_project_statistics(date_range: int = 30) -> Dict[str, Any]:
    """Get project statistics"""
    return system_metrics.get_project_statistics(date_range)


def get_database_health() -> Dict[str, Any]:
    """Get database health"""
    return system_metrics.get_database_health()


def get_redis_health() -> Dict[str, Any]:
    """Get Redis health"""
    return system_metrics.get_redis_health()


def get_email_metrics() -> Dict[str, Any]:
    """Get transactional auth email delivery metrics"""
    return system_metrics.get_email_metrics()
