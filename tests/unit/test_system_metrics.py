"""Unit tests for src/Util/system_metrics.py — Slice 10.

Focus on calculate_health_score (pure arithmetic).
Other methods require psutil/DB/Redis and are deferred.
"""

import pytest

from src.Util.system_metrics import SystemMetrics


# ─── calculate_health_score ─────────────────────────────────────────────────

class TestCalculateHealthScore:
    def _make_health(self, status="healthy", response_time_ms=10):
        return {"status": status, "response_time_ms": response_time_ms}

    def test_all_healthy_max_score(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=50,
            db_health=self._make_health(),
            redis_health=self._make_health(),
        )
        assert score == 100

    def test_cpu_above_60_penalty_10(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=65,
            memory_percent=50,
            db_health=self._make_health(),
            redis_health=self._make_health(),
        )
        assert score == 90  # 100 - 10

    def test_cpu_above_80_penalty_20(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=85,
            memory_percent=50,
            db_health=self._make_health(),
            redis_health=self._make_health(),
        )
        assert score == 80  # 100 - 20

    def test_memory_above_75_penalty_10(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=80,
            db_health=self._make_health(),
            redis_health=self._make_health(),
        )
        assert score == 90  # 100 - 10

    def test_memory_above_90_penalty_20(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=95,
            db_health=self._make_health(),
            redis_health=self._make_health(),
        )
        assert score == 80  # 100 - 20

    def test_db_unhealthy_penalty_30(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=50,
            db_health={"status": "unhealthy", "response_time_ms": 10},
            redis_health=self._make_health(),
        )
        assert score == 70  # 100 - 30

    def test_db_slow_penalty_10(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=50,
            db_health={"status": "healthy", "response_time_ms": 1500},
            redis_health=self._make_health(),
        )
        assert score == 90  # 100 - 10

    def test_redis_unhealthy_penalty_20(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=50,
            db_health=self._make_health(),
            redis_health={"status": "unhealthy", "response_time_ms": 10},
        )
        assert score == 80  # 100 - 20

    def test_redis_slow_penalty_5(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=50,
            db_health=self._make_health(),
            redis_health={"status": "healthy", "response_time_ms": 600},
        )
        assert score == 95  # 100 - 5

    def test_multiple_penalties_stack(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=85,       # -20
            memory_percent=95,    # -20
            db_health={"status": "unhealthy", "response_time_ms": 10},  # -30
            redis_health={"status": "unhealthy", "response_time_ms": 10},  # -20
        )
        assert score == 10  # 100 - 20 - 20 - 30 - 20 = 10

    def test_db_health_missing_status_treated_as_unhealthy(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=50,
            db_health={"response_time_ms": 10},  # no "status" key
            redis_health=self._make_health(),
        )
        assert score == 70  # 100 - 30 (db unhealthy)

    def test_redis_health_missing_status_treated_as_unhealthy(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=50,
            db_health=self._make_health(),
            redis_health={"response_time_ms": 10},  # no "status" key
        )
        assert score == 80  # 100 - 20 (redis unhealthy)

    def test_boundary_cpu_exactly_60_no_penalty(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=60,
            memory_percent=50,
            db_health=self._make_health(),
            redis_health=self._make_health(),
        )
        assert score == 100

    def test_boundary_cpu_exactly_80_penalty_20(self):
        # cpu_percent > 80, so 80 is NOT > 80, but 80 > 60 → -10
        score = SystemMetrics.calculate_health_score(
            cpu_percent=80,
            memory_percent=50,
            db_health=self._make_health(),
            redis_health=self._make_health(),
        )
        assert score == 90  # 100 - 10 (60 < 80 <= 80)

    def test_boundary_memory_exactly_75_no_penalty(self):
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=75,
            db_health=self._make_health(),
            redis_health=self._make_health(),
        )
        assert score == 100

    def test_boundary_memory_exactly_90_penalty_20(self):
        # memory_percent > 90, so 90 is NOT > 90, but 90 > 75 → -10
        score = SystemMetrics.calculate_health_score(
            cpu_percent=30,
            memory_percent=90,
            db_health=self._make_health(),
            redis_health=self._make_health(),
        )
        assert score == 90  # 100 - 10
