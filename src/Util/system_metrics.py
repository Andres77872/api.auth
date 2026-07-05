"""
System Metrics Utility

Provides system performance monitoring, metrics collection,
and health status tracking for the authentication system.
"""

import time
import json
import os
from datetime import datetime, timezone
from typing import Dict, Any

import psutil

from src.Util import auth_constants as constants
from src.Util.billing.config import load_billing_config, validate_billing_readiness
from src.Util.billing.redaction import sanitize_billing_sensitive_text
from src.Util.db import count_users, count_projects, count_active_sessions
from src.Util.db_config import get_connection, redis_client
from src.Util.auth_constants import EMAIL_WORKER_WAKE_PREFIX
from src.Util.email.config import load_email_config, validate_email_readiness
from src.Util.patreon.config import load_patreon_config, validate_patreon_readiness
from src.Util.stripe.config import load_stripe_config, validate_stripe_runtime_readiness


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
                "application": app_metrics,
                "patreon": SystemMetrics.get_patreon_metrics(),
                "billing": SystemMetrics.get_billing_metrics(),
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
                "provider": os.environ.get(constants.EMAIL_PROVIDER_ENV, "unknown"),
                "delivery_enabled": str(os.environ.get(constants.EMAIL_DELIVERY_ENABLED_ENV, "")).strip().lower()
                in {"1", "true", "yes", "y", "on"},
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
            readiness = validate_email_readiness(config)
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
            if not config.delivery_enabled:
                status = "disabled"
            elif not readiness.ready:
                status = "not_ready"
            elif heartbeats:
                status = "healthy"
            else:
                status = "unknown"
            return {
                "status": status,
                "delivery_enabled": config.delivery_enabled,
                "ready": status == "healthy",
                "heartbeat_count": len(heartbeats),
                "latest_heartbeat": latest,
                "workers": heartbeats[:10],
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "delivery_enabled": str(os.environ.get(constants.EMAIL_DELIVERY_ENABLED_ENV, "")).strip().lower()
                in {"1", "true", "yes", "y", "on"},
                "ready": False,
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
    def _safe_int(value: Any, default: int = 0) -> int:
        try:
            if isinstance(value, bool):
                return default
            return int(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def _parse_utc_datetime(value: Any) -> datetime | None:
        if value is None or value == "":
            return None
        if isinstance(value, datetime):
            parsed = value
        elif isinstance(value, str):
            try:
                parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
            except ValueError:
                return None
        else:
            return None
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc).replace(microsecond=0)

    @staticmethod
    def _seconds_since(value: Any) -> int | None:
        parsed = SystemMetrics._parse_utc_datetime(value)
        if parsed is None:
            return None
        return max(0, int((datetime.now(timezone.utc) - parsed).total_seconds()))

    @staticmethod
    def _redis_string_value(key: Any) -> str | None:
        raw = redis_client.get(key)
        if isinstance(raw, bytes):
            return raw.decode("utf-8", errors="ignore")
        if raw is None:
            return None
        return str(raw)

    @staticmethod
    def _redis_count_for_prefix(prefix: str) -> Dict[str, Any]:
        """Return aggregate counts for a Redis prefix without exposing keys."""

        bucket_count = 0
        value_total = 0
        max_ttl = 0
        for key in redis_client.scan_iter(match=f"{prefix}*", count=100):
            bucket_count += 1
            raw = SystemMetrics._redis_string_value(key)
            value_total += SystemMetrics._safe_int(raw, 0)
            try:
                ttl = int(redis_client.ttl(key))
            except Exception:
                ttl = 0
            if ttl > max_ttl:
                max_ttl = ttl
        return {
            "bucket_count": bucket_count,
            "event_count": value_total,
            "max_ttl_seconds": max_ttl if max_ttl > 0 else None,
        }

    @staticmethod
    def _fetch_one_metric_row(query: str, params: tuple[Any, ...] = ()) -> dict[str, Any] | None:
        with get_connection() as con:
            cur = con.cursor()
            cur.execute(query, params)
            row = cur.fetchone()
            if not row or not cur.description:
                return None
            columns = [desc[0] for desc in cur.description]
            return dict(zip(columns, row))

    @staticmethod
    def patreon_worker_heartbeat_key(worker_id: str) -> str:
        safe_worker = "".join(
            char if char.isalnum() or char in {"-", "_", ":"} else "_"
            for char in str(worker_id or "unknown")
        )[:128]
        return f"{constants.PATREON_SYNC_JOB_PREFIX}heartbeat:{safe_worker}"

    @staticmethod
    def record_patreon_worker_heartbeat(
        worker_id: str,
        *,
        mode: str,
        counters: Dict[str, Any] | None = None,
        results: list[Dict[str, Any]] | None = None,
        ttl_seconds: int = 300,
    ) -> bool:
        """Record a non-secret Patreon sync-worker heartbeat in Redis."""

        try:
            safe_counters = {
                str(key): SystemMetrics._safe_int(value, 0)
                for key, value in dict(counters or {}).items()
                if str(key) in {
                    "processed",
                    "members_seen",
                    "members_persisted",
                    "pages_fetched",
                    "tier_map_misses",
                    "retry",
                    "failed",
                    "proof_requests_purged",
                    "webhook_delivery_hashes_purged",
                    "raw_payloads_purged",
                }
            }
            safe_results: list[dict[str, Any]] = []
            for item in results or []:
                safe_results.append(
                    {
                        key: item.get(key)
                        for key in (
                            "status",
                            "job_type",
                            "members_seen",
                            "members_persisted",
                            "pages_fetched",
                            "tier_map_misses",
                            "proof_requests_purged",
                            "webhook_delivery_hashes_purged",
                            "raw_payloads_purged",
                            "retry_after_seconds",
                            "reason",
                        )
                        if item.get(key) is not None
                    }
                )

            payload = {
                "worker_id": str(worker_id or "unknown")[:128],
                "mode": str(mode or "unknown")[:64],
                "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "counters": safe_counters,
                "results": safe_results[:10],
            }
            return bool(
                redis_client.set(
                    SystemMetrics.patreon_worker_heartbeat_key(worker_id),
                    json.dumps(payload, sort_keys=True, default=str),
                    ex=max(1, int(ttl_seconds)),
                )
            )
        except Exception:
            return False

    @staticmethod
    def get_patreon_readiness_metrics() -> Dict[str, Any]:
        """Return non-secret Patreon readiness and kill-switch posture."""

        try:
            config = load_patreon_config()
            readiness = validate_patreon_readiness(config)
            feature_flags = {
                "linking": bool(config.linking_enabled),
                "webhooks": bool(config.webhooks_enabled),
                "sync": bool(config.sync_enabled),
                "s2s_entitlement": bool(config.s2s_entitlement_enabled),
                "creator_token_refresh": bool(config.creator_token_refresh_enabled),
                "raw_payload_capture": bool(config.raw_payload_capture_enabled),
            }
            return {
                "status": readiness.status,
                "ready": bool(readiness.ready),
                "disabled": config.disabled,
                "degraded": list(readiness.degraded),
                "missing": list(readiness.missing),
                "feature_flags": feature_flags,
                "configured_campaign_count": len(config.campaign_ids),
                "configured_tier_map_entries": len(config.campaign_tier_maps),
                "retention": {
                    "proof_retention_after_expiry_hours": config.proof_retention_after_expiry_hours,
                    "webhook_delivery_retention_days": config.webhook_delivery_retention_days,
                    "raw_payload_retention_days": config.raw_payload_retention_days,
                    "link_history": constants.PATREON_LINK_HISTORY_RETENTION,
                    "snapshot_history": constants.PATREON_SNAPSHOT_HISTORY_RETENTION,
                    "unlink_history": constants.PATREON_UNLINK_HISTORY_RETENTION,
                },
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "not_ready",
                "ready": False,
                "disabled": True,
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_patreon_creator_token_health() -> Dict[str, Any]:
        """Return creator-token health metadata without token/fingerprint material."""

        try:
            from src.Util.db import db_patreon

            row = db_patreon.get_patreon_creator_token_health()
            status = str(row.get("status") or "unknown") if isinstance(row, dict) else "unknown"
            return {
                "status": status,
                "configured": bool(row.get("configured")) if isinstance(row, dict) else False,
                "degraded": bool(row.get("degraded")) if isinstance(row, dict) else status in {"refresh_failed", "revoked", "expired"},
                "expires_at": row.get("expires_at") if isinstance(row, dict) else None,
                "refreshed_at": row.get("refreshed_at") if isinstance(row, dict) else None,
                "rotated_at": row.get("rotated_at") if isinstance(row, dict) else None,
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "configured": False,
                "degraded": True,
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_patreon_webhook_metrics() -> Dict[str, Any]:
        """Return non-secret webhook failure and retry/paused state."""

        try:
            config = load_patreon_config()
            redis_counts = SystemMetrics._redis_count_for_prefix(constants.PATREON_WEBHOOK_SIGNATURE_FAILURE_RATE_PREFIX)
            ledger_count = 0
            retry_count = 0
            try:
                row = SystemMetrics._fetch_one_metric_row(
                    """
                    SELECT
                        SUM(CASE WHEN signature_valid = 0 THEN 1 ELSE 0 END) AS signature_failures,
                        SUM(CASE WHEN status IN ('failed','processing') OR retry_after_at IS NOT NULL THEN 1 ELSE 0 END) AS retrying_deliveries
                    FROM patreon_webhook_deliveries
                    WHERE received_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s SECOND)
                    """,
                    (max(1, int(config.webhook_signature_failure_alert_window_seconds)),),
                ) or {}
                ledger_count = SystemMetrics._safe_int(row.get("signature_failures"), 0)
                retry_count = SystemMetrics._safe_int(row.get("retrying_deliveries"), 0)
            except Exception:
                ledger_count = 0
                retry_count = 0
            signature_failure_count = max(SystemMetrics._safe_int(redis_counts.get("event_count"), 0), ledger_count)
            degraded = signature_failure_count >= max(1, int(config.webhook_signature_failure_alert_limit))
            return {
                "status": "degraded" if degraded else ("disabled" if not config.webhooks_enabled else "healthy"),
                "enabled": bool(config.webhooks_enabled),
                "signature_failure_count": signature_failure_count,
                "signature_failure_bucket_count": redis_counts.get("bucket_count", 0),
                "signature_failure_window_seconds": config.webhook_signature_failure_alert_window_seconds,
                "signature_failure_alert_limit": config.webhook_signature_failure_alert_limit,
                "signature_failure_rate_per_minute": round(
                    signature_failure_count / max(1, config.webhook_signature_failure_alert_window_seconds / 60),
                    4,
                ),
                "paused": degraded,
                "retrying_deliveries": retry_count,
                "retry_after_seconds": redis_counts.get("max_ttl_seconds"),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "enabled": False,
                "signature_failure_count": 0,
                "paused": False,
                "retrying_deliveries": 0,
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_patreon_snapshot_metrics() -> Dict[str, Any]:
        """Return safe aggregate snapshot freshness and tier-map-miss health."""

        try:
            row = SystemMetrics._fetch_one_metric_row(
                """
                SELECT
                    COUNT(*) AS current_snapshot_count,
                    SUM(CASE WHEN stale_after IS NOT NULL AND stale_after < UTC_TIMESTAMP() THEN 1 ELSE 0 END) AS stale_snapshot_count,
                    MAX(CASE WHEN stale_after IS NOT NULL AND stale_after < UTC_TIMESTAMP()
                        THEN TIMESTAMPDIFF(SECOND, stale_after, UTC_TIMESTAMP()) ELSE 0 END) AS max_stale_age_seconds,
                    MAX(CASE WHEN last_synced_at IS NOT NULL
                        THEN TIMESTAMPDIFF(SECOND, last_synced_at, UTC_TIMESTAMP()) ELSE NULL END) AS oldest_snapshot_age_seconds
                FROM patreon_entitlements_current
                """
            ) or {}
            tier_row = SystemMetrics._fetch_one_metric_row(
                """
                SELECT COUNT(*) AS tier_map_misses
                FROM patreon_entitlement_history
                WHERE reason = 'tier_map_miss'
                  AND observed_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR)
                """
            ) or {}
            stale_count = SystemMetrics._safe_int(row.get("stale_snapshot_count"), 0)
            return {
                "status": "degraded" if stale_count else "healthy",
                "current_snapshot_count": SystemMetrics._safe_int(row.get("current_snapshot_count"), 0),
                "stale_snapshot_count": stale_count,
                "max_stale_age_seconds": SystemMetrics._safe_int(row.get("max_stale_age_seconds"), 0),
                "oldest_snapshot_age_seconds": row.get("oldest_snapshot_age_seconds"),
                "tier_map_misses_24h": SystemMetrics._safe_int(tier_row.get("tier_map_misses"), 0),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "current_snapshot_count": 0,
                "stale_snapshot_count": 0,
                "max_stale_age_seconds": None,
                "tier_map_misses_24h": 0,
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_patreon_proof_delivery_health() -> Dict[str, Any]:
        """Return aggregate Patreon proof-email delivery health."""

        try:
            row = SystemMetrics._fetch_one_metric_row(
                """
                SELECT
                    SUM(CASE WHEN status IN ('pending','retry','processing') THEN 1 ELSE 0 END) AS in_flight,
                    SUM(CASE WHEN status IN ('sent','delivered') THEN 1 ELSE 0 END) AS delivered,
                    SUM(CASE WHEN status IN ('dead','bounced','complained','suppressed','cancelled') THEN 1 ELSE 0 END) AS failed,
                    MAX(CASE WHEN status IN ('pending','retry','processing')
                        THEN TIMESTAMPDIFF(SECOND, created_at, UTC_TIMESTAMP()) ELSE NULL END) AS oldest_in_flight_age_seconds
                FROM email_messages
                WHERE purpose = 'patreon_link_proof'
                  AND created_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR)
                """
            ) or {}
            failed = SystemMetrics._safe_int(row.get("failed"), 0)
            in_flight = SystemMetrics._safe_int(row.get("in_flight"), 0)
            return {
                "status": "degraded" if failed else "healthy",
                "in_flight": in_flight,
                "delivered_24h": SystemMetrics._safe_int(row.get("delivered"), 0),
                "failed_24h": failed,
                "oldest_in_flight_age_seconds": row.get("oldest_in_flight_age_seconds"),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "in_flight": 0,
                "delivered_24h": 0,
                "failed_24h": 0,
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_patreon_s2s_health() -> Dict[str, Any]:
        """Return S2S enablement and safe rate-limit health."""

        try:
            config = load_patreon_config()
            redis_counts = SystemMetrics._redis_count_for_prefix(constants.PATREON_S2S_RATE_PREFIX)
            ready = bool(config.s2s_entitlement_enabled and config.s2s_bearer_token)
            return {
                "status": "healthy" if ready else ("disabled" if not config.s2s_entitlement_enabled else "not_ready"),
                "enabled": bool(config.s2s_entitlement_enabled),
                "ready": ready,
                "rate_bucket_count": redis_counts.get("bucket_count", 0),
                "rate_event_count": redis_counts.get("event_count", 0),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "enabled": False,
                "ready": False,
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_patreon_worker_metrics() -> Dict[str, Any]:
        """Return Patreon sync-worker heartbeat/counter visibility."""

        try:
            config = load_patreon_config()
            heartbeats = []
            for key in redis_client.scan_iter(match=f"{constants.PATREON_SYNC_JOB_PREFIX}heartbeat:*", count=100):
                raw = SystemMetrics._redis_string_value(key)
                if not raw:
                    continue
                try:
                    decoded = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    heartbeats.append(decoded)
            latest = max((item.get("recorded_at", "") for item in heartbeats), default=None)
            latest_payload = max(heartbeats, key=lambda item: item.get("recorded_at", "")) if heartbeats else {}
            latest_age = SystemMetrics._seconds_since(latest)
            stale_after = max(60, int(config.sync_worker_poll_seconds) * 4)
            has_stale_heartbeat = latest_age is not None and latest_age > stale_after
            status = "healthy" if heartbeats and not has_stale_heartbeat else (
                "stale" if heartbeats else ("disabled" if not config.sync_enabled else "unknown")
            )
            counters = latest_payload.get("counters") if isinstance(latest_payload.get("counters"), dict) else {}
            retention_results = [
                item for item in latest_payload.get("results", [])
                if isinstance(item, dict) and item.get("job_type") == "retention"
            ] if isinstance(latest_payload.get("results"), list) else []
            return {
                "status": status,
                "sync_enabled": bool(config.sync_enabled),
                "heartbeat_count": len(heartbeats),
                "latest_heartbeat": latest,
                "latest_heartbeat_age_seconds": latest_age,
                "latest_mode": latest_payload.get("mode"),
                "counters": counters,
                "retention_job_status": retention_results[-1].get("status") if retention_results else None,
                "retention_purged": {
                    "proof_requests": SystemMetrics._safe_int(counters.get("proof_requests_purged"), 0),
                    "webhook_delivery_hashes": SystemMetrics._safe_int(counters.get("webhook_delivery_hashes_purged"), 0),
                    "raw_payloads": SystemMetrics._safe_int(counters.get("raw_payloads_purged"), 0),
                },
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "heartbeat_count": 0,
                "latest_heartbeat": None,
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_patreon_sync_queue_metrics() -> Dict[str, Any]:
        """Return aggregate sync queue retry/paused/retention status."""

        try:
            row = SystemMetrics._fetch_one_metric_row(
                """
                SELECT
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_jobs,
                    SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_jobs,
                    SUM(CASE WHEN status = 'retry' THEN 1 ELSE 0 END) AS retry_jobs,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_jobs,
                    SUM(CASE WHEN job_type = 'retention' AND status IN ('completed','failed') THEN 1 ELSE 0 END) AS terminal_retention_jobs,
                    MAX(CASE WHEN job_type = 'retention' THEN completed_at ELSE NULL END) AS last_retention_completed_at
                FROM patreon_sync_jobs
                """
            ) or {}
            retry_jobs = SystemMetrics._safe_int(row.get("retry_jobs"), 0)
            failed_jobs = SystemMetrics._safe_int(row.get("failed_jobs"), 0)
            return {
                "status": "degraded" if failed_jobs else ("retrying" if retry_jobs else "healthy"),
                "pending_jobs": SystemMetrics._safe_int(row.get("pending_jobs"), 0),
                "running_jobs": SystemMetrics._safe_int(row.get("running_jobs"), 0),
                "retry_jobs": retry_jobs,
                "failed_jobs": failed_jobs,
                "terminal_retention_jobs": SystemMetrics._safe_int(row.get("terminal_retention_jobs"), 0),
                "last_retention_completed_at": row.get("last_retention_completed_at"),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "pending_jobs": 0,
                "running_jobs": 0,
                "retry_jobs": 0,
                "failed_jobs": 0,
                "error": str(e),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_patreon_metrics() -> Dict[str, Any]:
        """Return non-secret Patreon operational metrics for health/readiness."""

        readiness = SystemMetrics.get_patreon_readiness_metrics()
        creator_token = SystemMetrics.get_patreon_creator_token_health()
        webhooks = SystemMetrics.get_patreon_webhook_metrics()
        snapshots = SystemMetrics.get_patreon_snapshot_metrics()
        proof_delivery = SystemMetrics.get_patreon_proof_delivery_health()
        s2s = SystemMetrics.get_patreon_s2s_health()
        worker = SystemMetrics.get_patreon_worker_metrics()
        sync_queue = SystemMetrics.get_patreon_sync_queue_metrics()

        component_statuses = [
            readiness.get("status"),
            creator_token.get("status"),
            webhooks.get("status"),
            snapshots.get("status"),
            proof_delivery.get("status"),
            s2s.get("status"),
            worker.get("status"),
            sync_queue.get("status"),
        ]
        if readiness.get("disabled"):
            status = "disabled"
        elif any(item in {"degraded", "stale", "retrying", "unknown", "not_ready"} for item in component_statuses):
            status = "degraded"
        else:
            status = "healthy"

        return {
            "status": status,
            "readiness": readiness,
            "creator_token": creator_token,
            "webhooks": webhooks,
            "snapshots": snapshots,
            "tier_map": {
                "misses_24h": snapshots.get("tier_map_misses_24h", 0),
                "status": "degraded" if SystemMetrics._safe_int(snapshots.get("tier_map_misses_24h"), 0) else snapshots.get("status"),
            },
            "proof_delivery": proof_delivery,
            "s2s": s2s,
            "worker": worker,
            "sync_queue": sync_queue,
            "metrics": {
                "patreon_ready": bool(readiness.get("ready")),
                "patreon_disabled": bool(readiness.get("disabled")),
                "patreon_creator_token_degraded": bool(creator_token.get("degraded")),
                "patreon_webhook_signature_failure_rate_per_minute": webhooks.get("signature_failure_rate_per_minute"),
                "patreon_webhook_retrying_deliveries": webhooks.get("retrying_deliveries", 0),
                "patreon_stale_snapshot_count": snapshots.get("stale_snapshot_count", 0),
                "patreon_max_stale_snapshot_age_seconds": snapshots.get("max_stale_age_seconds"),
                "patreon_tier_map_misses_24h": snapshots.get("tier_map_misses_24h", 0),
                "patreon_proof_delivery_failed_24h": proof_delivery.get("failed_24h", 0),
                "patreon_s2s_ready": bool(s2s.get("ready")),
                "patreon_sync_worker_heartbeat_age_seconds": worker.get("latest_heartbeat_age_seconds"),
                "patreon_retention_job_status": worker.get("retention_job_status") or sync_queue.get("last_retention_completed_at"),
            },
        }

    @staticmethod
    def billing_worker_heartbeat_key(worker_id: str) -> str:
        """Return a billing-only Redis key for worker heartbeat metadata."""

        safe_worker = "".join(
            char if char.isalnum() or char in {"-", "_", ":"} else "_"
            for char in str(worker_id or "unknown")
        )[:128]
        return f"{constants.BILLING_SYNC_JOB_PREFIX}heartbeat:{safe_worker}"

    @staticmethod
    def record_billing_worker_heartbeat(
        worker_id: str,
        *,
        mode: str,
        counters: Dict[str, Any] | None = None,
        results: list[Dict[str, Any]] | None = None,
        ttl_seconds: int = 300,
    ) -> bool:
        """Record non-secret billing sync-worker heartbeat/counters in Redis."""

        try:
            allowed_counter_names = {
                "processed",
                "completed",
                "retry",
                "failed",
                "disabled",
                "noop",
                "claim_failed",
                "decrypt_failures",
                "webhook_delivery_rows_purged",
                "raw_payload_rows_purged",
            }
            safe_counters = {
                str(key): SystemMetrics._safe_int(value, 0)
                for key, value in dict(counters or {}).items()
                if str(key) in allowed_counter_names
            }
            safe_results: list[dict[str, Any]] = []
            for item in results or []:
                if not isinstance(item, dict):
                    continue
                safe_results.append(
                    {
                        key: item.get(key)
                        for key in (
                            "status",
                            "provider",
                            "job_type",
                            "retry_after_seconds",
                            "reason",
                            "webhook_delivery_rows_purged",
                            "raw_payload_rows_purged",
                        )
                        if item.get(key) is not None
                    }
                )

            payload = {
                "worker_id": str(worker_id or "unknown")[:128],
                "mode": str(mode or "unknown")[:64],
                "recorded_at": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                "counters": safe_counters,
                "results": safe_results[:10],
            }
            return bool(
                redis_client.set(
                    SystemMetrics.billing_worker_heartbeat_key(worker_id),
                    json.dumps(payload, sort_keys=True, default=str),
                    ex=max(1, int(ttl_seconds)),
                )
            )
        except Exception:
            return False

    @staticmethod
    def get_billing_readiness_metrics() -> Dict[str, Any]:
        """Return additive generic billing readiness without exposing secrets."""

        try:
            billing_config = load_billing_config()
            stripe_readiness = validate_stripe_runtime_readiness(load_stripe_config())
            readiness = validate_billing_readiness(
                billing_config,
                provider_readinesses=[stripe_readiness.to_dict()],
            )
            return {
                "status": "healthy" if readiness.status == "ready" else readiness.status,
                "ready": bool(readiness.ready),
                "enabled": bool(readiness.enabled),
                "disabled": bool(billing_config.disabled),
                "missing": list(readiness.missing),
                "degraded": list(readiness.degraded),
                "s2s_ready": bool(readiness.s2s_ready),
                "checkout_ready": bool(readiness.checkout_ready),
                "portal_ready": bool(readiness.portal_ready),
                "sync_ready": bool(readiness.sync_ready),
                "feature_flags": dict(billing_config.primary_feature_flags),
                "retention": {
                    "webhook_delivery_retention_days": billing_config.webhook_delivery_retention_days,
                    "raw_payload_retention_days": billing_config.raw_payload_retention_days,
                    "entitlement_history": constants.BILLING_ENTITLEMENT_HISTORY_RETENTION,
                    "purchase_history": constants.BILLING_PURCHASE_HISTORY_RETENTION,
                },
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "not_ready",
                "ready": False,
                "enabled": False,
                "disabled": True,
                "error": sanitize_billing_sensitive_text(str(e)),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_billing_provider_stripe_health() -> Dict[str, Any]:
        """Return Stripe provider readiness with no raw Stripe IDs or secrets."""

        try:
            config = load_stripe_config()
            readiness = validate_stripe_runtime_readiness(config)

            # Per-group rollup: the env secret no longer gates readiness, so true operational state
            # comes from how many groups actually have active credentials. Counts/flags only.
            per_group: Dict[str, int] | None = None
            try:
                from src.Util.db import db_billing

                metrics_row = db_billing.get_billing_admin_metrics() or {}
                per_group = {
                    key: int(metrics_row.get(key) or 0)
                    for key in (
                        "groups_total",
                        "groups_active",
                        "credentials_active",
                        "credentials_absent",
                        "credentials_rotating",
                        "credentials_revoked",
                        "groups_with_webhook_secret",
                        "webhook_secret_missing_active_groups",
                    )
                }
            except Exception:
                per_group = None

            status = "healthy" if readiness.status == "ready" else readiness.status
            reason: Optional[str] = None
            if readiness.enabled and per_group is not None:
                if per_group["groups_total"] > 0 and per_group["credentials_active"] == 0:
                    status, reason = "not_ready", "no_group_credentials_active"
                elif (
                    config.webhooks_enabled
                    and per_group["webhook_secret_missing_active_groups"] > 0
                    and status == "healthy"
                ):
                    status, reason = "degraded", "group_webhook_secret_missing"

            payload: Dict[str, Any] = {
                "status": status,
                "provider": constants.STRIPE_PROVIDER_NAME,
                "ready": bool(readiness.ready),
                "enabled": bool(readiness.enabled),
                "sdk_version": readiness.sdk_version,
                "api_version": readiness.api_version,
                "missing": list(readiness.missing),
                "degraded": list(readiness.degraded),
                "critical_mismatches": list(readiness.critical_mismatches),
                "capabilities": dict(readiness.capabilities),
                "allowed_webhook_event_count": len(config.allowed_webhook_events),
                "per_group": per_group or {},
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
            if reason:
                payload["reason"] = reason
            return payload
        except Exception as e:
            return {
                "status": "not_ready",
                "provider": constants.STRIPE_PROVIDER_NAME,
                "ready": False,
                "enabled": False,
                "error": sanitize_billing_sensitive_text(str(e)),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_billing_webhook_metrics() -> Dict[str, Any]:
        """Return safe Stripe webhook signature, lag, duplicate, and conflict metrics."""

        try:
            config = load_stripe_config()
            if not config.webhooks_enabled:
                return {
                    "status": "disabled",
                    "enabled": False,
                    "signature_failure_count": 0,
                    "signature_failure_bucket_count": 0,
                    "signature_failure_window_seconds": constants.DEFAULT_STRIPE_WEBHOOK_SIGNATURE_FAILURE_RATE_WINDOW_SECONDS,
                    "signature_failure_alert_limit": constants.DEFAULT_STRIPE_WEBHOOK_SIGNATURE_FAILURE_RATE_LIMIT,
                    "signature_failure_rate_per_minute": 0,
                    "max_delivery_lag_seconds": 0,
                    "retrying_deliveries": 0,
                    "duplicate_events_24h": 0,
                    "idempotency_conflicts_24h": 0,
                    "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            redis_counts = SystemMetrics._redis_count_for_prefix(constants.STRIPE_WEBHOOK_SIGNATURE_FAILURE_RATE_PREFIX)
            failure_window_seconds = constants.DEFAULT_STRIPE_WEBHOOK_SIGNATURE_FAILURE_RATE_WINDOW_SECONDS
            failure_limit = constants.DEFAULT_STRIPE_WEBHOOK_SIGNATURE_FAILURE_RATE_LIMIT
            signature_failures = 0
            max_lag_seconds = 0
            duplicate_events_24h = 0
            idempotency_conflicts_24h = 0
            retrying_deliveries = 0

            try:
                row = SystemMetrics._fetch_one_metric_row(
                    """
                    SELECT
                        SUM(CASE WHEN signature_valid = 0 THEN 1 ELSE 0 END) AS signature_failures,
                        SUM(CASE WHEN status IN ('failed','processing','resync_required') OR retry_after_at IS NOT NULL THEN 1 ELSE 0 END) AS retrying_deliveries,
                        MAX(TIMESTAMPDIFF(SECOND, received_at, COALESCE(processed_at, UTC_TIMESTAMP()))) AS max_delivery_lag_seconds
                    FROM billing_webhook_deliveries
                    WHERE received_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL %s SECOND)
                    """,
                    (max(1, int(failure_window_seconds)),),
                ) or {}
                signature_failures = SystemMetrics._safe_int(row.get("signature_failures"), 0)
                retrying_deliveries = SystemMetrics._safe_int(row.get("retrying_deliveries"), 0)
                max_lag_seconds = SystemMetrics._safe_int(row.get("max_delivery_lag_seconds"), 0)
            except Exception:
                signature_failures = 0
                retrying_deliveries = 0
                max_lag_seconds = 0

            try:
                duplicate_row = SystemMetrics._fetch_one_metric_row(
                    """
                    SELECT SUM(CASE WHEN status = 'replay' THEN 1 ELSE 0 END) AS duplicate_events
                    FROM billing_webhook_deliveries
                    WHERE received_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR)
                    """,
                ) or {}
                duplicate_events_24h = SystemMetrics._safe_int(duplicate_row.get("duplicate_events"), 0)
            except Exception:
                duplicate_events_24h = 0

            try:
                idem_row = SystemMetrics._fetch_one_metric_row(
                    """
                    SELECT COUNT(*) AS idempotency_conflicts
                    FROM billing_checkout_intents
                    WHERE status = 'conflict'
                      AND created_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR)
                    """,
                ) or {}
                idempotency_conflicts_24h = SystemMetrics._safe_int(idem_row.get("idempotency_conflicts"), 0)
            except Exception:
                idempotency_conflicts_24h = 0

            signature_failure_count = max(
                SystemMetrics._safe_int(redis_counts.get("event_count"), 0),
                signature_failures,
            )
            degraded = signature_failure_count >= max(1, failure_limit)
            status = "degraded" if degraded else ("disabled" if not config.webhooks_enabled else "healthy")
            return {
                "status": status,
                "enabled": bool(config.webhooks_enabled),
                "signature_failure_count": signature_failure_count,
                "signature_failure_bucket_count": redis_counts.get("bucket_count", 0),
                "signature_failure_window_seconds": failure_window_seconds,
                "signature_failure_alert_limit": failure_limit,
                "signature_failure_rate_per_minute": round(
                    signature_failure_count / max(1, failure_window_seconds / 60),
                    4,
                ),
                "max_delivery_lag_seconds": max_lag_seconds,
                "retrying_deliveries": retrying_deliveries,
                "duplicate_events_24h": duplicate_events_24h,
                "idempotency_conflicts_24h": idempotency_conflicts_24h,
                "retry_after_seconds": redis_counts.get("max_ttl_seconds"),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "enabled": False,
                "signature_failure_count": 0,
                "signature_failure_rate_per_minute": 0,
                "max_delivery_lag_seconds": 0,
                "duplicate_events_24h": 0,
                "idempotency_conflicts_24h": 0,
                "error": sanitize_billing_sensitive_text(str(e)),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_billing_snapshot_metrics() -> Dict[str, Any]:
        """Return safe aggregate billing snapshot freshness metrics."""

        try:
            row = SystemMetrics._fetch_one_metric_row(
                """
                SELECT
                    COUNT(*) AS current_snapshot_count,
                    SUM(CASE WHEN stale_after IS NOT NULL AND stale_after < UTC_TIMESTAMP() THEN 1 ELSE 0 END) AS stale_snapshot_count,
                    MAX(CASE WHEN stale_after IS NOT NULL AND stale_after < UTC_TIMESTAMP()
                        THEN TIMESTAMPDIFF(SECOND, stale_after, UTC_TIMESTAMP()) ELSE 0 END) AS max_stale_age_seconds,
                    MAX(CASE WHEN last_synced_at IS NOT NULL
                        THEN TIMESTAMPDIFF(SECOND, last_synced_at, UTC_TIMESTAMP()) ELSE NULL END) AS oldest_snapshot_age_seconds
                FROM billing_entitlements_current
                """
            ) or {}
            stale_count = SystemMetrics._safe_int(row.get("stale_snapshot_count"), 0)
            return {
                "status": "degraded" if stale_count else "healthy",
                "current_snapshot_count": SystemMetrics._safe_int(row.get("current_snapshot_count"), 0),
                "stale_snapshot_count": stale_count,
                "max_stale_age_seconds": SystemMetrics._safe_int(row.get("max_stale_age_seconds"), 0),
                "oldest_snapshot_age_seconds": row.get("oldest_snapshot_age_seconds"),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "current_snapshot_count": 0,
                "stale_snapshot_count": 0,
                "max_stale_age_seconds": None,
                "error": sanitize_billing_sensitive_text(str(e)),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_billing_worker_metrics() -> Dict[str, Any]:
        """Return billing sync-worker heartbeat/counter visibility."""

        try:
            billing_config = load_billing_config()
            stripe_config = load_stripe_config()
            sync_enabled = bool(billing_config.sync_enabled or stripe_config.sync_enabled)
            if not sync_enabled:
                return {
                    "status": "disabled",
                    "sync_enabled": False,
                    "heartbeat_count": 0,
                    "latest_heartbeat": None,
                    "latest_heartbeat_age_seconds": None,
                    "latest_mode": None,
                    "counters": {},
                    "decrypt_failures": 0,
                    "retention_job_status": None,
                    "retention_purged": {"webhook_delivery_rows": 0, "raw_payload_rows": 0},
                    "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                }
            heartbeats = []
            for key in redis_client.scan_iter(match=f"{constants.BILLING_SYNC_JOB_PREFIX}heartbeat:*", count=100):
                raw = SystemMetrics._redis_string_value(key)
                if not raw:
                    continue
                try:
                    decoded = json.loads(raw)
                except json.JSONDecodeError:
                    continue
                if isinstance(decoded, dict):
                    heartbeats.append(decoded)
            latest = max((item.get("recorded_at", "") for item in heartbeats), default=None)
            latest_payload = max(heartbeats, key=lambda item: item.get("recorded_at", "")) if heartbeats else {}
            latest_age = SystemMetrics._seconds_since(latest)
            stale_after = 4 * 30
            has_stale_heartbeat = latest_age is not None and latest_age > stale_after
            status = "healthy" if heartbeats and not has_stale_heartbeat else (
                "stale" if heartbeats else ("disabled" if not sync_enabled else "unknown")
            )
            counters = latest_payload.get("counters") if isinstance(latest_payload.get("counters"), dict) else {}
            retention_results = [
                item for item in latest_payload.get("results", [])
                if isinstance(item, dict) and item.get("job_type") == "retention"
            ] if isinstance(latest_payload.get("results"), list) else []
            return {
                "status": status,
                "sync_enabled": sync_enabled,
                "heartbeat_count": len(heartbeats),
                "latest_heartbeat": latest,
                "latest_heartbeat_age_seconds": latest_age,
                "latest_mode": latest_payload.get("mode"),
                "counters": counters,
                "decrypt_failures": SystemMetrics._safe_int(counters.get("decrypt_failures"), 0),
                "retention_job_status": retention_results[-1].get("status") if retention_results else None,
                "retention_purged": {
                    "webhook_delivery_rows": SystemMetrics._safe_int(counters.get("webhook_delivery_rows_purged"), 0),
                    "raw_payload_rows": SystemMetrics._safe_int(counters.get("raw_payload_rows_purged"), 0),
                },
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "heartbeat_count": 0,
                "latest_heartbeat": None,
                "decrypt_failures": 0,
                "error": sanitize_billing_sensitive_text(str(e)),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_billing_sync_queue_metrics() -> Dict[str, Any]:
        """Return aggregate billing sync queue retry/backlog/failure metrics."""

        try:
            row = SystemMetrics._fetch_one_metric_row(
                """
                SELECT
                    SUM(CASE WHEN status = 'pending' THEN 1 ELSE 0 END) AS pending_jobs,
                    SUM(CASE WHEN status = 'running' THEN 1 ELSE 0 END) AS running_jobs,
                    SUM(CASE WHEN status = 'retry' THEN 1 ELSE 0 END) AS retry_jobs,
                    SUM(CASE WHEN status = 'failed' THEN 1 ELSE 0 END) AS failed_jobs,
                    SUM(CASE WHEN status = 'failed' AND updated_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR) THEN 1 ELSE 0 END) AS failed_jobs_24h,
                    SUM(CASE WHEN last_error_redacted LIKE '%decrypt%' AND updated_at >= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 24 HOUR) THEN 1 ELSE 0 END) AS decrypt_failures_24h,
                    MAX(CASE WHEN status IN ('pending','retry') THEN TIMESTAMPDIFF(SECOND, created_at, UTC_TIMESTAMP()) ELSE NULL END) AS oldest_pending_age_seconds,
                    MAX(CASE WHEN job_type = 'retention' THEN completed_at ELSE NULL END) AS last_retention_completed_at
                FROM billing_sync_jobs
                """
            ) or {}
            retry_jobs = SystemMetrics._safe_int(row.get("retry_jobs"), 0)
            failed_jobs = SystemMetrics._safe_int(row.get("failed_jobs"), 0)
            return {
                "status": "degraded" if failed_jobs else ("retrying" if retry_jobs else "healthy"),
                "pending_jobs": SystemMetrics._safe_int(row.get("pending_jobs"), 0),
                "running_jobs": SystemMetrics._safe_int(row.get("running_jobs"), 0),
                "retry_jobs": retry_jobs,
                "failed_jobs": failed_jobs,
                "failed_jobs_24h": SystemMetrics._safe_int(row.get("failed_jobs_24h"), 0),
                "decrypt_failures_24h": SystemMetrics._safe_int(row.get("decrypt_failures_24h"), 0),
                "oldest_pending_age_seconds": row.get("oldest_pending_age_seconds"),
                "last_retention_completed_at": row.get("last_retention_completed_at"),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "pending_jobs": 0,
                "running_jobs": 0,
                "retry_jobs": 0,
                "failed_jobs": 0,
                "failed_jobs_24h": 0,
                "decrypt_failures_24h": 0,
                "error": sanitize_billing_sensitive_text(str(e)),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_billing_retention_health() -> Dict[str, Any]:
        """Return bounded retention health; normalized history remains indefinite."""

        try:
            webhook_row = SystemMetrics._fetch_one_metric_row(
                """
                SELECT COUNT(*) AS overdue_webhook_rows
                FROM billing_webhook_deliveries
                WHERE expires_at <= UTC_TIMESTAMP()
                   OR received_at <= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 90 DAY)
                """
            ) or {}
            raw_row = SystemMetrics._fetch_one_metric_row(
                """
                SELECT COUNT(*) AS overdue_raw_payload_rows
                FROM billing_raw_payload_quarantine
                WHERE purged_at IS NULL
                  AND (purge_at <= UTC_TIMESTAMP()
                       OR received_at <= DATE_SUB(UTC_TIMESTAMP(), INTERVAL 30 DAY))
                """
            ) or {}
            overdue_webhook = SystemMetrics._safe_int(webhook_row.get("overdue_webhook_rows"), 0)
            overdue_raw = SystemMetrics._safe_int(raw_row.get("overdue_raw_payload_rows"), 0)
            return {
                "status": "degraded" if (overdue_webhook or overdue_raw) else "healthy",
                "webhook_delivery_retention_days": constants.DEFAULT_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS,
                "raw_payload_retention_days": constants.DEFAULT_BILLING_RAW_PAYLOAD_RETENTION_DAYS,
                "overdue_webhook_delivery_rows": overdue_webhook,
                "overdue_raw_payload_rows": overdue_raw,
                "entitlement_history": constants.BILLING_ENTITLEMENT_HISTORY_RETENTION,
                "purchase_history": constants.BILLING_PURCHASE_HISTORY_RETENTION,
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }
        except Exception as e:
            return {
                "status": "unknown",
                "webhook_delivery_retention_days": constants.DEFAULT_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS,
                "raw_payload_retention_days": constants.DEFAULT_BILLING_RAW_PAYLOAD_RETENTION_DAYS,
                "overdue_webhook_delivery_rows": 0,
                "overdue_raw_payload_rows": 0,
                "entitlement_history": constants.BILLING_ENTITLEMENT_HISTORY_RETENTION,
                "purchase_history": constants.BILLING_PURCHASE_HISTORY_RETENTION,
                "error": sanitize_billing_sensitive_text(str(e)),
                "last_check": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
            }

    @staticmethod
    def get_billing_sync_metrics() -> Dict[str, Any]:
        """Return worker and queue metrics grouped for `/system/health`."""

        worker = SystemMetrics.get_billing_worker_metrics()
        sync_enabled = bool(worker.get("sync_enabled"))
        if not sync_enabled:
            return {
                "status": "disabled",
                "enabled": False,
                "worker": worker,
                "queue": {
                    "status": "disabled",
                    "pending_jobs": 0,
                    "running_jobs": 0,
                    "retry_jobs": 0,
                    "failed_jobs": 0,
                    "failed_jobs_24h": 0,
                    "decrypt_failures_24h": 0,
                    "oldest_pending_age_seconds": None,
                },
                "pending_jobs": 0,
                "running_jobs": 0,
                "retry_jobs": 0,
                "failed_jobs": 0,
                "failed_jobs_24h": 0,
                "oldest_pending_age_seconds": None,
                "decrypt_failures_24h": 0,
            }

        queue = SystemMetrics.get_billing_sync_queue_metrics()
        if any(item in {"degraded", "stale", "retrying", "unknown"} for item in (worker.get("status"), queue.get("status"))):
            status = "degraded" if queue.get("status") != "retrying" else "retrying"
        else:
            status = "healthy"
        return {
            "status": status,
            "enabled": sync_enabled,
            "worker": worker,
            "queue": queue,
            "pending_jobs": queue.get("pending_jobs", 0),
            "running_jobs": queue.get("running_jobs", 0),
            "retry_jobs": queue.get("retry_jobs", 0),
            "failed_jobs": queue.get("failed_jobs", 0),
            "failed_jobs_24h": queue.get("failed_jobs_24h", 0),
            "oldest_pending_age_seconds": queue.get("oldest_pending_age_seconds"),
            "decrypt_failures_24h": queue.get("decrypt_failures_24h", 0),
        }

    @staticmethod
    def get_billing_metrics() -> Dict[str, Any]:
        """Return additive billing/Stripe operational metrics for health/readiness."""

        readiness = SystemMetrics.get_billing_readiness_metrics()
        provider = SystemMetrics.get_billing_provider_stripe_health()

        if readiness.get("disabled") and provider.get("status") == "disabled":
            webhooks = {
                "status": "disabled",
                "enabled": False,
                "signature_failure_count": 0,
                "signature_failure_rate_per_minute": 0,
                "max_delivery_lag_seconds": 0,
                "duplicate_events_24h": 0,
                "idempotency_conflicts_24h": 0,
            }
            snapshots = {
                "status": "disabled",
                "current_snapshot_count": 0,
                "stale_snapshot_count": 0,
                "max_stale_age_seconds": 0,
            }
            sync = {
                "status": "disabled",
                "enabled": False,
                "pending_jobs": 0,
                "running_jobs": 0,
                "retry_jobs": 0,
                "failed_jobs": 0,
                "failed_jobs_24h": 0,
                "oldest_pending_age_seconds": None,
                "decrypt_failures_24h": 0,
            }
            retention = {
                "status": "disabled",
                "webhook_delivery_retention_days": constants.DEFAULT_BILLING_WEBHOOK_DELIVERY_RETENTION_DAYS,
                "raw_payload_retention_days": constants.DEFAULT_BILLING_RAW_PAYLOAD_RETENTION_DAYS,
                "overdue_webhook_delivery_rows": 0,
                "overdue_raw_payload_rows": 0,
                "entitlement_history": constants.BILLING_ENTITLEMENT_HISTORY_RETENTION,
                "purchase_history": constants.BILLING_PURCHASE_HISTORY_RETENTION,
            }
            return {
                "status": "disabled",
                "readiness": readiness,
                "provider_stripe": provider,
                "webhooks": webhooks,
                "snapshots": snapshots,
                "sync": sync,
                "retention": retention,
                "metrics": {
                    "billing_ready": False,
                    "billing_disabled": True,
                    "stripe_ready": False,
                    "stripe_webhook_signature_failure_rate_per_minute": 0,
                    "stripe_webhook_max_delivery_lag_seconds": 0,
                    "stripe_webhook_duplicate_events_24h": 0,
                    "billing_idempotency_conflicts_24h": 0,
                    "billing_stale_snapshot_count": 0,
                    "billing_sync_pending_jobs": 0,
                    "billing_sync_failed_jobs_24h": 0,
                    "billing_decrypt_failures_24h": 0,
                    "billing_retention_overdue_webhook_delivery_rows": 0,
                    "billing_retention_overdue_raw_payload_rows": 0,
                },
            }

        webhooks = SystemMetrics.get_billing_webhook_metrics()
        snapshots = SystemMetrics.get_billing_snapshot_metrics()
        sync = SystemMetrics.get_billing_sync_metrics()
        retention = SystemMetrics.get_billing_retention_health()

        if any(
            item in {"degraded", "stale", "retrying", "unknown", "not_ready"}
            for item in (
                readiness.get("status"),
                provider.get("status"),
                webhooks.get("status"),
                snapshots.get("status"),
                sync.get("status"),
                retention.get("status"),
            )
        ):
            status = "degraded"
        else:
            status = "healthy"

        return {
            "status": status,
            "readiness": readiness,
            "provider_stripe": provider,
            "webhooks": webhooks,
            "snapshots": snapshots,
            "sync": sync,
            "retention": retention,
            "metrics": {
                "billing_ready": bool(readiness.get("ready")),
                "billing_disabled": bool(readiness.get("disabled")),
                "stripe_ready": bool(provider.get("ready")),
                "stripe_webhook_signature_failure_rate_per_minute": webhooks.get("signature_failure_rate_per_minute"),
                "stripe_webhook_max_delivery_lag_seconds": webhooks.get("max_delivery_lag_seconds"),
                "stripe_webhook_duplicate_events_24h": webhooks.get("duplicate_events_24h", 0),
                "billing_idempotency_conflicts_24h": webhooks.get("idempotency_conflicts_24h", 0),
                "billing_stale_snapshot_count": snapshots.get("stale_snapshot_count", 0),
                "billing_sync_pending_jobs": sync.get("pending_jobs", 0),
                "billing_sync_failed_jobs_24h": sync.get("failed_jobs_24h", 0),
                "billing_decrypt_failures_24h": sync.get("decrypt_failures_24h", 0),
                "billing_retention_overdue_webhook_delivery_rows": retention.get("overdue_webhook_delivery_rows", 0),
                "billing_retention_overdue_raw_payload_rows": retention.get("overdue_raw_payload_rows", 0),
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


def get_patreon_metrics() -> Dict[str, Any]:
    """Get Patreon readiness, health, and sync-worker metrics without secrets."""
    return system_metrics.get_patreon_metrics()


def get_billing_metrics() -> Dict[str, Any]:
    """Get billing/Stripe readiness, health, and sync-worker metrics without secrets."""
    return system_metrics.get_billing_metrics()
