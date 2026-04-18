"""Unit tests for src/Util/uuid_generator.py — Slice 1.

Pure functions, zero external deps, zero env vars needed.
"""

import re
import uuid as uuid_mod

import pytest

from src.Util.uuid_generator import (
    generate_user_id,
    generate_project_id,
    generate_user_group_id,
    generate_permission_id,
    generate_permission_group_id,
    generate_project_group_id,
    generate_project_group_member_id,
    generate_user_group_member_id,
    generate_user_group_project_id,
    generate_permission_group_permission_id,
    generate_user_group_permission_group_id,
    generate_session_id,
    generate_audit_log_id,
    generate_activity_log_id,
    generate_bulk_operation_id,
    generate_hash,
    generate_user_hash,
    generate_project_hash,
    generate_user_group_hash,
    generate_permission_hash,
    generate_permission_group_hash,
)

UUID_PATTERN = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


def _assert_prefixed_uuid(value: str, prefix: str, *, hyphens: bool = True):
    """Assert value starts with prefix and contains a valid UUID."""
    assert value.startswith(f"{prefix}-"), f"Expected prefix '{prefix}-', got '{value}'"
    uuid_part = value[len(prefix) + 1 :]
    if hyphens:
        assert UUID_PATTERN.match(uuid_part), f"UUID part '{uuid_part}' is not valid"
    else:
        # Without hyphens: 32 hex chars
        assert re.match(r"^[0-9a-f]{32}$", uuid_part, re.IGNORECASE), (
            f"UUID part '{uuid_part}' is not 32 hex chars"
        )


# ─── Prefix-based generators ────────────────────────────────────────────────

class TestPrefixedUUIDGenerators:
    @pytest.mark.parametrize(
        "gen,prefix",
        [
            (generate_user_id, "usr"),
            (generate_project_id, "proj"),
            (generate_user_group_id, "ug"),
            (generate_permission_id, "perm"),
            (generate_permission_group_id, "pg"),
            (generate_project_group_id, "projg"),
            (generate_session_id, "ses"),
        ],
    )
    def test_prefixed_generator_returns_correct_format(self, gen, prefix):
        result = gen()
        _assert_prefixed_uuid(result, prefix)

    @pytest.mark.parametrize(
        "gen,prefix",
        [
            (generate_project_group_member_id, "pgm"),
            (generate_user_group_member_id, "ugm"),
            (generate_user_group_project_id, "ugp"),
            (generate_permission_group_permission_id, "pgp"),
            (generate_user_group_permission_group_id, "ugpg"),
            (generate_audit_log_id, "audit"),
            (generate_activity_log_id, "act"),
            (generate_bulk_operation_id, "bulk"),
        ],
    )
    def test_no_hyphen_generator_returns_correct_format(self, gen, prefix):
        result = gen()
        _assert_prefixed_uuid(result, prefix, hyphens=False)


# ─── Hash generators ────────────────────────────────────────────────────────

class TestHashGenerators:
    @pytest.mark.parametrize(
        "gen,prefix",
        [
            (generate_user_hash, "USR"),
            (generate_project_hash, "PROJ"),
            (generate_user_group_hash, "UG"),
            (generate_permission_hash, "PERM"),
            (generate_permission_group_hash, "PG"),
        ],
    )
    def test_hash_generator_returns_uppercase_prefix_and_hex(self, gen, prefix):
        result = gen()
        assert result.startswith(f"{prefix}-"), f"Expected '{prefix}-', got '{result}'"
        hex_part = result[len(prefix) + 1 :]
        assert re.match(r"^[0-9A-F]{32}$", hex_part), f"Hex part '{hex_part}' is not 32 uppercase hex"

    def test_generate_hash_custom_prefix(self):
        result = generate_hash("custom")
        assert result.startswith("CUSTOM-")
        hex_part = result[7:]
        assert re.match(r"^[0-9A-F]{32}$", hex_part)

    def test_generate_hash_single_char_prefix(self):
        result = generate_hash("x")
        assert result.startswith("X-")
        hex_part = result[2:]
        assert re.match(r"^[0-9A-F]{32}$", hex_part)

    def test_generate_hash_empty_prefix(self):
        result = generate_hash("")
        assert result.startswith("-")
        hex_part = result[1:]
        assert re.match(r"^[0-9A-F]{32}$", hex_part)


# ─── Uniqueness ──────────────────────────────────────────────────────────────

class TestUniqueness:
    @pytest.mark.parametrize(
        "gen",
        [
            generate_user_id,
            generate_project_id,
            generate_user_group_id,
            generate_permission_id,
            generate_permission_group_id,
            generate_project_group_id,
            generate_project_group_member_id,
            generate_user_group_member_id,
            generate_user_group_project_id,
            generate_permission_group_permission_id,
            generate_user_group_permission_group_id,
            generate_session_id,
            generate_audit_log_id,
            generate_activity_log_id,
            generate_bulk_operation_id,
            generate_user_hash,
            generate_project_hash,
            generate_user_group_hash,
            generate_permission_hash,
            generate_permission_group_hash,
        ],
    )
    def test_no_collisions_in_1000_iterations(self, gen):
        values = {gen() for _ in range(1000)}
        assert len(values) == 1000, f"{gen.__name__} produced collisions"
