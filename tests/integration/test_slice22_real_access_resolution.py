"""
Slice 22 (Strategy Slice 9) — get_user_accessible_projects with real MySQL

The LINCHPIN TEST. Create a full chain (user → user_group → project_group → project),
call get_user_accessible_projects(user_id), verify it returns the correct project.

Then test:
  (a) user in multiple groups
  (b) project in multiple project_groups
  (c) soft-deleted user_group does NOT grant access
  (d) soft-deleted project does NOT appear

Proof layer: Layer 4 (real DB integration)
Trace: explore.md RISK 3 (CRITICAL), Gap 5, SQL architecture GAP 2
"""

import pymysql
import pytest

# Import the real DB function under test
from src.Util.db.db_user_groups import get_user_accessible_projects


# ─── Helper: Call the SP directly to bypass the DB layer wrapper ─────────────

def _call_accessible_projects_sp(conn, user_id: str):
    """Call sp_get_user_accessible_projects directly and return results."""
    with conn.cursor() as cur:
        cur.callproc("sp_get_user_accessible_projects", [user_id])
        results = cur.fetchall()
        # Clean up additional result sets
        while cur.nextset():
            pass
        return results


# ─── Tests ───────────────────────────────────────────────────────────────────

@pytest.mark.real_db
def test_accessible_projects_returns_project_via_full_chain(real_db_conn, real_factory):
    """User → UserGroup → ProjectGroup → Project: user should see the project."""
    chain = real_factory.create_full_chain(
        username="chain_user",
        group_name="chain_ug",
        pg_name="chain_pg",
        project_name="chain_project",
    )

    results = _call_accessible_projects_sp(real_db_conn, chain["user"]["id"])

    assert len(results) >= 1, "User should have access to at least one project"
    project_ids = [r["id"] for r in results]
    assert chain["project"]["id"] in project_ids, (
        f"Project {chain['project']['id']} should be accessible. Got: {project_ids}"
    )


@pytest.mark.real_db
def test_accessible_projects_user_in_multiple_groups(real_db_conn, real_factory):
    """User in two user groups, each linked to different project groups with different projects."""
    user = real_factory.create_user(username="multi_group_user")
    ug1 = real_factory.create_user_group(group_name="multi_ug_1")
    ug2 = real_factory.create_user_group(group_name="multi_ug_2")
    pg1 = real_factory.create_project_group(group_name="multi_pg_1")
    pg2 = real_factory.create_project_group(group_name="multi_pg_2")
    proj1 = real_factory.create_project(project_name="multi_proj_1")
    proj2 = real_factory.create_project(project_name="multi_proj_2")

    real_factory.link_user_to_group(user["id"], ug1["id"])
    real_factory.link_user_to_group(user["id"], ug2["id"])
    real_factory.link_project_to_group(proj1["id"], pg1["id"])
    real_factory.link_project_to_group(proj2["id"], pg2["id"])
    real_factory.link_user_group_to_project_group(ug1["id"], pg1["id"])
    real_factory.link_user_group_to_project_group(ug2["id"], pg2["id"])

    results = _call_accessible_projects_sp(real_db_conn, user["id"])

    project_ids = [r["id"] for r in results]
    assert proj1["id"] in project_ids, f"Project 1 should be accessible. Got: {project_ids}"
    assert proj2["id"] in project_ids, f"Project 2 should be accessible. Got: {project_ids}"


@pytest.mark.real_db
def test_accessible_projects_project_in_multiple_project_groups(real_db_conn, real_factory):
    """Project in two project groups, each linked to different user groups with same user."""
    user = real_factory.create_user(username="multi_pg_user")
    ug = real_factory.create_user_group(group_name="multi_pg_ug")
    pg1 = real_factory.create_project_group(group_name="multi_pg_a")
    pg2 = real_factory.create_project_group(group_name="multi_pg_b")
    proj = real_factory.create_project(project_name="multi_pg_project")

    real_factory.link_user_to_group(user["id"], ug["id"])
    real_factory.link_project_to_group(proj["id"], pg1["id"])
    real_factory.link_project_to_group(proj["id"], pg2["id"])
    real_factory.link_user_group_to_project_group(ug["id"], pg1["id"])
    real_factory.link_user_group_to_project_group(ug["id"], pg2["id"])

    results = _call_accessible_projects_sp(real_db_conn, user["id"])

    project_ids = [r["id"] for r in results]
    assert proj["id"] in project_ids, f"Project should be accessible. Got: {project_ids}"
    # Should appear only once (no duplicates)
    assert project_ids.count(proj["id"]) == 1, "Project should appear exactly once"


@pytest.mark.real_db
def test_accessible_projects_soft_deleted_user_group_no_access(real_db_conn, real_factory):
    """Soft-deleting a user_group should revoke access for all its members."""
    chain = real_factory.create_full_chain(
        username="softdel_user",
        group_name="softdel_ug",
        pg_name="softdel_pg",
        project_name="softdel_project",
    )

    # Verify access exists
    results = _call_accessible_projects_sp(real_db_conn, chain["user"]["id"])
    assert len(results) >= 1, "User should have access before soft-delete"

    # Soft-delete the user group
    with real_db_conn.cursor() as cur:
        cur.execute(
            "UPDATE user_groups SET is_active = 0 WHERE id = %s",
            (chain["user_group"]["id"],),
        )
    real_db_conn.commit()

    # Verify access is revoked
    results = _call_accessible_projects_sp(real_db_conn, chain["user"]["id"])
    project_ids = [r["id"] for r in results]
    assert chain["project"]["id"] not in project_ids, (
        f"Project should NOT be accessible after user_group soft-delete. Got: {project_ids}"
    )


@pytest.mark.real_db
def test_accessible_projects_soft_deleted_project_not_visible(real_db_conn, real_factory):
    """Soft-deleting a project should make it invisible in accessible projects."""
    chain = real_factory.create_full_chain(
        username="softdel_proj_user",
        group_name="softdel_proj_ug",
        pg_name="softdel_proj_pg",
        project_name="softdel_project",
    )

    # Verify access exists
    results = _call_accessible_projects_sp(real_db_conn, chain["user"]["id"])
    assert len(results) >= 1, "User should have access before project soft-delete"

    # Soft-delete the project
    with real_db_conn.cursor() as cur:
        cur.execute(
            "UPDATE projects SET is_active = 0 WHERE id = %s",
            (chain["project"]["id"],),
        )
    real_db_conn.commit()

    # Verify project is not visible
    results = _call_accessible_projects_sp(real_db_conn, chain["user"]["id"])
    project_ids = [r["id"] for r in results]
    assert chain["project"]["id"] not in project_ids, (
        f"Soft-deleted project should NOT appear. Got: {project_ids}"
    )


@pytest.mark.real_db
def test_accessible_projects_no_groups_returns_empty(real_db_conn, real_factory):
    """User with no group memberships should have no accessible projects."""
    user = real_factory.create_user(username="lonely_user")

    results = _call_accessible_projects_sp(real_db_conn, user["id"])
    assert len(results) == 0, f"User with no groups should have 0 accessible projects. Got: {results}"


@pytest.mark.real_db
def test_accessible_projects_group_not_linked_to_project(real_db_conn, real_factory):
    """User in a user group that is NOT linked to any project group should have no access."""
    user = real_factory.create_user(username="unlinked_user")
    ug = real_factory.create_user_group(group_name="unlinked_ug")
    # Don't create any project group or link

    real_factory.link_user_to_group(user["id"], ug["id"])

    results = _call_accessible_projects_sp(real_db_conn, user["id"])
    assert len(results) == 0, (
        f"User in unlinked group should have 0 accessible projects. Got: {results}"
    )


@pytest.mark.real_db
def test_accessible_projects_db_layer_function(real_db_conn, real_factory):
    """Test the actual DB layer function get_user_accessible_projects (not just the SP).

    This test patches get_connection at the usage location since the DB layer
    reads from .env which points to port 3306, not our test port 3307.
    Uses a non-DictCursor connection since the DB layer expects tuple rows.
    """
    from unittest.mock import patch
    import pymysql

    chain = real_factory.create_full_chain(
        username="db_layer_user",
        group_name="db_layer_ug",
        pg_name="db_layer_pg",
        project_name="db_layer_project",
    )

    # Create a non-DictCursor connection for the DB layer (expects tuple rows)
    from tests.integration.conftest import _REAL_DB_CONFIG
    tuple_conn_config = {**_REAL_DB_CONFIG}
    tuple_conn_config.pop("cursorclass", None)  # Use default cursor

    def mock_get_connection():
        return pymysql.connect(**tuple_conn_config)

    # Patch get_connection at the USAGE location (where db_user_groups imports it)
    with patch("src.Util.db.db_user_groups.get_connection", mock_get_connection):
        # Call the actual DB layer function
        projects = get_user_accessible_projects(chain["user"]["id"])

    assert len(projects) >= 1, "DB layer should return at least one project"
    project_ids = [p.id for p in projects]
    assert chain["project"]["id"] in project_ids, (
        f"Project {chain['project']['id']} should be accessible via DB layer. Got: {project_ids}"
    )
