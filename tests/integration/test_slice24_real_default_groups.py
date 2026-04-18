"""
Slice 24 (Strategy Slice 12) — create_default_groups() with real MySQL

Call `create_default_groups(project_id)` against real MySQL. Verify:
  (a) project_group created
  (b) project linked to it
  (c) 3 user groups created (admin, user, readonly)
  (d) each user group linked to project_group
  (e) re-running for same project does NOT create duplicates (idempotency)

Proof layer: Layer 4 (real DB integration)
Trace: explore.md RISK 2, Gap 4
"""

import pymysql
import pytest
from unittest.mock import patch

from src.Util.db.db_user_groups import get_user_groups_for_project
from tests.integration.conftest import _REAL_DB_CONFIG


def _get_tuple_connection():
    """Return a non-DictCursor connection for the DB layer."""
    cfg = {**_REAL_DB_CONFIG}
    cfg.pop("cursorclass", None)
    return pymysql.connect(**cfg)


# Patch locations — each module that imports get_connection
_DB_PATCHES = {
    "src.Util.db_config.get_connection": _get_tuple_connection,
    "src.Util.db.db_projects.get_connection": _get_tuple_connection,
    "src.Util.db.db_users.get_connection": _get_tuple_connection,
    "src.Util.db.db_user_groups.get_connection": _get_tuple_connection,
}


def _all_db_patches():
    """Return a list of patch objects for all DB connections."""
    return [
        patch(loc, fn) for loc, fn in _DB_PATCHES.items()
    ]


from contextlib import contextmanager

@contextmanager
def _patch_all_db():
    """Context manager that patches all DB connections."""
    patches = [patch(loc, fn) for loc, fn in _DB_PATCHES.items()]
    for p in patches:
        p.start()
    try:
        yield
    finally:
        for p in patches:
            p.stop()


@pytest.mark.real_db
def test_create_default_groups_creates_project_group(real_db_conn, real_factory):
    """create_default_groups must create a project_group and link the project to it."""
    proj = real_factory.create_project(project_name="cdg_proj")

    with _patch_all_db():
        from src.Util.db.db_projects import create_default_groups
        create_default_groups(proj["id"])

    # Verify project_group_members has a row for this project
    with real_db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) as cnt FROM project_group_members WHERE project_id = %s AND is_active = 1",
            (proj["id"],),
        )
        result = cur.fetchone()
        assert result["cnt"] >= 1, "Project should be linked to at least one project_group"


@pytest.mark.real_db
def test_create_default_groups_creates_three_user_groups(real_db_conn, real_factory):
    """create_default_groups must create exactly 3 user groups: admin, user, readonly."""
    proj = real_factory.create_project(project_name="cdg_3groups_proj")

    with _patch_all_db():
        from src.Util.db.db_projects import create_default_groups
        create_default_groups(proj["id"])

        with patch("src.Util.db.db_user_groups.get_connection", _get_tuple_connection):
            groups = get_user_groups_for_project(proj["id"])
    group_names = [g.group_name for g in groups]

    # Should have admin, user, readonly groups (with project_id suffix)
    assert any("admin" in name for name in group_names), f"Should have admin group. Got: {group_names}"
    assert any("user" in name for name in group_names), f"Should have user group. Got: {group_names}"
    assert any("readonly" in name for name in group_names), f"Should have readonly group. Got: {group_names}"


@pytest.mark.real_db
def test_create_default_groups_links_user_groups_to_project_group(real_db_conn, real_factory):
    """Each user group created by create_default_groups must be linked to the project_group."""
    proj = real_factory.create_project(project_name="cdg_link_proj")

    with _patch_all_db():
        from src.Util.db.db_projects import create_default_groups
        create_default_groups(proj["id"])

    # Verify user_group_project_groups has links
    with real_db_conn.cursor() as cur:
        cur.execute(
            """SELECT COUNT(*) as cnt
               FROM user_group_project_groups ugpg
               JOIN project_group_members pgm ON ugpg.project_group_id = pgm.project_group_id
               WHERE pgm.project_id = %s AND ugpg.is_active = 1""",
            (proj["id"],),
        )
        result = cur.fetchone()
        assert result["cnt"] == 3, (
            f"Should have 3 user_group→project_group links. Got: {result['cnt']}"
        )


@pytest.mark.real_db
def test_create_default_groups_idempotent_no_duplicates(real_db_conn, real_factory):
    """Re-running create_default_groups for the same project must NOT create duplicate groups."""
    proj = real_factory.create_project(project_name="cdg_idem_proj")

    with _patch_all_db():
        from src.Util.db.db_projects import create_default_groups
        # Run once
        create_default_groups(proj["id"])
        with patch("src.Util.db.db_user_groups.get_connection", _get_tuple_connection):
            groups_after_first = get_user_groups_for_project(proj["id"])

        # Run again
        create_default_groups(proj["id"])
        with patch("src.Util.db.db_user_groups.get_connection", _get_tuple_connection):
            groups_after_second = get_user_groups_for_project(proj["id"])

    # Same number of groups (ON DUPLICATE KEY UPDATE reactivates, doesn't duplicate)
    assert len(groups_after_first) == len(groups_after_second), (
        f"Re-running should not change group count. First: {len(groups_after_first)}, "
        f"Second: {len(groups_after_second)}"
    )

    # Verify no duplicate project_group_members
    with real_db_conn.cursor() as cur:
        cur.execute(
            "SELECT COUNT(*) as cnt FROM project_group_members WHERE project_id = %s AND is_active = 1",
            (proj["id"],),
        )
        result = cur.fetchone()
        assert result["cnt"] == 1, (
            f"Should have exactly 1 active project_group_member. Got: {result['cnt']}"
        )


@pytest.mark.real_db
def test_create_default_groups_enables_user_access(real_db_conn, real_factory):
    """After create_default_groups, a user assigned to one of the default groups should have access."""
    proj = real_factory.create_project(project_name="cdg_access_proj")
    with _patch_all_db():
        from src.Util.db.db_projects import create_default_groups
        create_default_groups(proj["id"])

        # Get the admin user group for this project
        with patch("src.Util.db.db_user_groups.get_connection", _get_tuple_connection):
            groups = get_user_groups_for_project(proj["id"])
        admin_group = next(g for g in groups if "admin" in g.group_name)

    # Create a user and assign to the admin group
    user = real_factory.create_user(username="cdg_admin_user")
    real_factory.link_user_to_group(user["id"], admin_group.id)

    # Verify user has access to the project
    with patch("src.Util.db.db_user_groups.get_connection", _get_tuple_connection):
        from src.Util.db.db_user_groups import get_user_accessible_projects
        accessible = get_user_accessible_projects(user["id"])

    project_ids = [p.id for p in accessible]
    assert proj["id"] in project_ids, (
        f"User in default admin group should have access. Got: {project_ids}"
    )
