"""
Slice 23 (Strategy Slice 11) — Soft-delete cascade verification

Test that soft-deleting a user_group revokes access for all members.
Test that soft-deleting a project_group revokes access for all linked user_groups.
Test that soft-deleting a project revokes access.

Proof layer: Layer 4 (real DB integration)
Trace: SQL architecture RISK 3, RISK 4, GAP 3
"""

import pymysql
import pytest

from src.Util.db.db_user_groups import get_user_accessible_projects
from unittest.mock import patch
from tests.integration.conftest import _REAL_DB_CONFIG


def _mock_get_connection():
    """Return a non-DictCursor connection for the DB layer."""
    cfg = {**_REAL_DB_CONFIG}
    cfg.pop("cursorclass", None)
    return pymysql.connect(**cfg)


def _get_accessible(user_id):
    """Call get_user_accessible_projects with patched connection."""
    with patch("src.Util.db.db_user_groups.get_connection", _mock_get_connection):
        return get_user_accessible_projects(user_id)


@pytest.mark.real_db
def test_soft_delete_user_group_revokes_member_access(real_db_conn, real_factory):
    """Soft-deleting a user_group must revoke project access for all its members."""
    chain = real_factory.create_full_chain(
        username="sd_ug_user",
        group_name="sd_ug",
        pg_name="sd_pg",
        project_name="sd_proj",
    )

    # Verify access exists
    projects = _get_accessible(chain["user"]["id"])
    assert len(projects) >= 1, "User should have access before soft-delete"

    # Soft-delete the user group
    with real_db_conn.cursor() as cur:
        cur.execute(
            "UPDATE user_groups SET is_active = 0 WHERE id = %s",
            (chain["user_group"]["id"],),
        )
    real_db_conn.commit()

    # Verify access is revoked
    projects = _get_accessible(chain["user"]["id"])
    project_ids = [p.id for p in projects]
    assert chain["project"]["id"] not in project_ids, (
        f"Access should be revoked after user_group soft-delete. Got: {project_ids}"
    )


@pytest.mark.real_db
def test_soft_delete_project_group_revokes_all_user_group_access(real_db_conn, real_factory):
    """Soft-deleting a project_group must revoke access for all user groups linked to it."""
    # Create two users in different user groups, both linked to the same project_group
    user1 = real_factory.create_user(username="sd_pg_user1")
    user2 = real_factory.create_user(username="sd_pg_user2")
    ug1 = real_factory.create_user_group(group_name="sd_pg_ug1")
    ug2 = real_factory.create_user_group(group_name="sd_pg_ug2")
    pg = real_factory.create_project_group(group_name="sd_pg")
    proj = real_factory.create_project(project_name="sd_pg_proj")

    real_factory.link_user_to_group(user1["id"], ug1["id"])
    real_factory.link_user_to_group(user2["id"], ug2["id"])
    real_factory.link_project_to_group(proj["id"], pg["id"])
    real_factory.link_user_group_to_project_group(ug1["id"], pg["id"])
    real_factory.link_user_group_to_project_group(ug2["id"], pg["id"])

    # Both users should have access
    p1 = _get_accessible(user1["id"])
    p2 = _get_accessible(user2["id"])
    assert any(p.id == proj["id"] for p in p1), "User1 should have access"
    assert any(p.id == proj["id"] for p in p2), "User2 should have access"

    # Soft-delete the project group
    with real_db_conn.cursor() as cur:
        cur.execute(
            "UPDATE project_groups SET is_active = 0 WHERE id = %s",
            (pg["id"],),
        )
    real_db_conn.commit()

    # Both users should lose access
    p1 = _get_accessible(user1["id"])
    p2 = _get_accessible(user2["id"])
    p1_ids = [p.id for p in p1]
    p2_ids = [p.id for p in p2]
    assert proj["id"] not in p1_ids, f"User1 should lose access after project_group soft-delete. Got: {p1_ids}"
    assert proj["id"] not in p2_ids, f"User2 should lose access after project_group soft-delete. Got: {p2_ids}"


@pytest.mark.real_db
def test_soft_delete_project_revokes_access(real_db_conn, real_factory):
    """Soft-deleting a project must make it invisible in accessible projects."""
    chain = real_factory.create_full_chain(
        username="sd_proj_user",
        group_name="sd_proj_ug",
        pg_name="sd_proj_pg",
        project_name="sd_proj",
    )

    # Verify access exists
    projects = _get_accessible(chain["user"]["id"])
    assert len(projects) >= 1, "User should have access before project soft-delete"

    # Soft-delete the project
    with real_db_conn.cursor() as cur:
        cur.execute(
            "UPDATE projects SET is_active = 0 WHERE id = %s",
            (chain["project"]["id"],),
        )
    real_db_conn.commit()

    # Verify project is not visible
    projects = _get_accessible(chain["user"]["id"])
    project_ids = [p.id for p in projects]
    assert chain["project"]["id"] not in project_ids, (
        f"Soft-deleted project should not appear. Got: {project_ids}"
    )


@pytest.mark.real_db
def test_soft_delete_one_user_group_preserves_other_group_access(real_db_conn, real_factory):
    """If a user is in two user groups, soft-deleting one should NOT revoke access if the other still grants it."""
    user = real_factory.create_user(username="sd_multi_ug_user")
    ug1 = real_factory.create_user_group(group_name="sd_multi_ug1")
    ug2 = real_factory.create_user_group(group_name="sd_multi_ug2")
    pg = real_factory.create_project_group(group_name="sd_multi_pg")
    proj = real_factory.create_project(project_name="sd_multi_proj")

    real_factory.link_user_to_group(user["id"], ug1["id"])
    real_factory.link_user_to_group(user["id"], ug2["id"])
    real_factory.link_project_to_group(proj["id"], pg["id"])
    real_factory.link_user_group_to_project_group(ug1["id"], pg["id"])
    real_factory.link_user_group_to_project_group(ug2["id"], pg["id"])

    # User has access
    projects = _get_accessible(user["id"])
    assert any(p.id == proj["id"] for p in projects), "User should have access"

    # Soft-delete ONE user group
    with real_db_conn.cursor() as cur:
        cur.execute(
            "UPDATE user_groups SET is_active = 0 WHERE id = %s",
            (ug1["id"],),
        )
    real_db_conn.commit()

    # User should STILL have access via ug2
    projects = _get_accessible(user["id"])
    project_ids = [p.id for p in projects]
    assert proj["id"] in project_ids, (
        f"User should still have access via ug2. Got: {project_ids}"
    )


@pytest.mark.real_db
def test_soft_delete_user_group_member_preserves_other_member_access(real_db_conn, real_factory):
    """If two users are in the same user group, soft-deleting one user's membership should NOT affect the other."""
    ug = real_factory.create_user_group(group_name="sd_member_ug")
    pg = real_factory.create_project_group(group_name="sd_member_pg")
    proj = real_factory.create_project(project_name="sd_member_proj")
    user1 = real_factory.create_user(username="sd_member_user1")
    user2 = real_factory.create_user(username="sd_member_user2")

    real_factory.link_user_to_group(user1["id"], ug["id"])
    real_factory.link_user_to_group(user2["id"], ug["id"])
    real_factory.link_project_to_group(proj["id"], pg["id"])
    real_factory.link_user_group_to_project_group(ug["id"], pg["id"])

    # Both users have access
    assert any(p.id == proj["id"] for p in _get_accessible(user1["id"]))
    assert any(p.id == proj["id"] for p in _get_accessible(user2["id"]))

    # Soft-delete user1's membership (not the user, just the membership)
    with real_db_conn.cursor() as cur:
        cur.execute(
            "UPDATE user_group_members SET is_active = 0 WHERE user_id = %s AND user_group_id = %s",
            (user1["id"], ug["id"]),
        )
    real_db_conn.commit()

    # User1 should lose access, user2 should still have it
    p1 = _get_accessible(user1["id"])
    p2 = _get_accessible(user2["id"])
    assert not any(p.id == proj["id"] for p in p1), "User1 should lose access"
    assert any(p.id == proj["id"] for p in p2), "User2 should still have access"
