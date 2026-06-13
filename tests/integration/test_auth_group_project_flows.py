"""
ASGI integration tests for clarified auth/group/project domain flows.

Covers:
- Registration rejected when group is missing (422).
- Registration succeeds when group exists but has no linked projects (200, project=null).
- Project-scoped login succeeds when user has at least one group linked to the
  requested project, even if another group has no linked projects.
- Project-scoped login denied when the requested project is not reachable through
  any of the user's groups.

Proof layer: Layer 3 (ASGI integration, mocked DB with fakeredis).
"""

from unittest.mock import patch, MagicMock

import pytest


# ─── Factories ───────────────────────────────────────────────────────────────

def _make_user(user_type="consumer", user_id="1", user_hash="usr-e2e-001",
               username="e2euser", email="e2e@test.com"):
    u = MagicMock()
    u.id = user_id
    u.user_hash = user_hash
    u.username = username
    u.email = email
    u.user_type = user_type
    u.is_active = True
    u.assigned_project_id = None
    return u


def _make_user_group(group_id="1", group_hash="grp-e2e-001", group_name="E2E Group"):
    g = MagicMock()
    g.id = group_id
    g.group_hash = group_hash
    g.group_name = group_name
    g.group_description = "An E2E test group"
    return g


def _make_project(project_id="1", project_hash="prj-e2e-001",
                  project_name="E2E Project", archived=False, is_active=True):
    p = MagicMock()
    p.id = project_id
    p.project_hash = project_hash
    p.project_name = project_name
    p.project_description = "An E2E test project"
    p.archived = archived
    p.is_active = is_active
    return p


def _make_register_result(user_hash="usr-new-001", username="newuser",
                          email="new@example.com", user_type="consumer",
                          session_token="e2e-session-token",
                          project_hash=None, project_name=None,
                          user_id="99"):
    r = MagicMock()
    r.user_hash = user_hash
    r.username = username
    r.email = email
    r.user_type = user_type
    r.session_token = session_token
    r.project_hash = project_hash
    r.project_name = project_name
    r.user_id = user_id
    return r


# ─── Registration: missing group ─────────────────────────────────────────────

class TestRegistrationMissingGroup:
    """E2E: Registration MUST require a user_group_hash."""

    @pytest.mark.asyncio
    async def test_register_without_group_hash_rejected(
        self, client, fake_redis, patched_cache_manager, patched_activity_logger,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        """POST /auth/register without user_group_hash → 422."""
        response = await client.post(
            "/auth/register",
            data={
                "username": "nogroupuser",
                "password": "SecureP@ss123",
            },
            headers={"User-Agent": "e2e-test-client"},
        )

        # FastAPI Form validation rejects missing required fields
        assert response.status_code in (422, 400)


# ─── Registration: group with no linked projects ─────────────────────────────

class TestRegistrationGroupNoProjects:
    """E2E: Registration into a group with no linked projects MUST succeed."""

    @pytest.mark.asyncio
    async def test_register_group_no_projects_succeeds(
        self, client, fake_redis, patched_cache_manager, patched_activity_logger,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        """Register into a group that has zero linked projects → 200, project=null."""
        group = _make_user_group()
        result = _make_register_result(project_hash=None, project_name=None)

        with patch("src.routes.auth.check_username_email_available", return_value=True), \
             patch("src.routes.auth.get_user_group_by_hash", return_value=group), \
             patch("src.routes.auth.get_projects_for_user_group", return_value=[]), \
             patch("src.routes.auth.enhanced_register", return_value=result):
            response = await client.post(
                "/auth/register",
                data={
                    "username": "batchuser",
                    "password": "SecureP@ss123",
                    "user_group_hash": "grp-e2e-001",
                },
                headers={"User-Agent": "e2e-test-client"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["project"] is None
        assert data["session_token"] is None
        assert "session_token" not in response.cookies


# ─── Login: project-scoped with multi-group resilience ───────────────────────

class TestLoginProjectScopedMultiGroup:
    """E2E: Project-scoped login with multi-group scenarios.

    Domain rule: If one of the user's groups is detached from a project,
    login may still work for ANOTHER project through another linked group.
    """

    @pytest.mark.asyncio
    async def test_login_succeeds_when_one_group_has_project_access(
        self, client, fake_redis, patched_cache_manager, patched_activity_logger,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        """User belongs to two groups: one with projects, one without.
        Login to the project accessible via the linked group → 200.
        """
        user = _make_user(user_type="consumer")
        project = _make_project(project_hash="prj-e2e-linked")
        group_with_projects = _make_user_group(
            group_id="1", group_hash="grp-linked", group_name="Linked Group"
        )
        group_without_projects = _make_user_group(
            group_id="2", group_hash="grp-orphan", group_name="Orphan Group"
        )

        # accessible projects only come from the linked group
        with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
             patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
             patch("src.routes.auth.get_project_by_hash", return_value=project), \
             patch("src.routes.auth.get_user_groups_for_user",
                   return_value=[group_with_projects, group_without_projects]):
            response = await client.post(
                "/auth/login",
                data={
                    "username": "multiuser",
                    "password": "correctpass",
                    "project_hash": "prj-e2e-linked",
                },
                headers={"User-Agent": "e2e-test-client"},
            )

        assert response.status_code == 200
        data = response.json()
        assert data["success"] is True
        assert data["project"]["project_hash"] == "prj-e2e-linked"
        # Both groups should appear in the response
        assert len(data["user_groups"]) == 2
        assert "granting_user_group" not in data
        assert "granting_project_group" not in data
        assert "access_path" not in data

    @pytest.mark.asyncio
    async def test_login_denied_when_project_not_reachable_via_any_group(
        self, client, fake_redis, patched_cache_manager, patched_activity_logger,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        """User belongs to groups, but none link to the requested project.
        Login to that project → 403.
        """
        user = _make_user(user_type="consumer")
        accessible_project = _make_project(project_hash="prj-e2e-other")
        group = _make_user_group()

        with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
             patch("src.routes.auth.get_user_accessible_projects", return_value=[accessible_project]), \
             patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
            response = await client.post(
                "/auth/login",
                data={
                    "username": "multiuser",
                    "password": "correctpass",
                    "project_hash": "prj-e2e-unreachable",
                },
                headers={"User-Agent": "e2e-test-client"},
            )

        assert response.status_code == 403
        data = response.json()
        assert data["status"] == "error"
        assert "prj-e2e-unreachable" not in str(data)
        assert "granting_user_group" not in str(data)
        assert "access_path" not in str(data)

    @pytest.mark.asyncio
    async def test_login_without_project_hash_rejected_for_non_root(
        self, client, fake_redis, patched_cache_manager, patched_activity_logger,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        """Non-root user login without project_hash → 400/422.
        Auto-selection is no longer supported; project_hash is mandatory.
        """
        user = _make_user(user_type="consumer")
        project_a = _make_project(project_hash="prj-e2e-a", project_name="Project A")
        project_b = _make_project(project_hash="prj-e2e-b", project_name="Project B")

        with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
             patch("src.routes.auth.get_user_accessible_projects", return_value=[project_a, project_b]):
            response = await client.post(
                "/auth/login",
                data={
                    "username": "multiuser",
                    "password": "correctpass",
                    # NO project_hash
                },
                headers={"User-Agent": "e2e-test-client"},
            )

        assert response.status_code in (400, 422)
        data = response.json()
        assert data["status"] == "error"


class TestLoginProjectGroupCrossLoginHardening:
    """Regression tests for the project-group cross-login hardening contract."""

    @pytest.mark.asyncio
    async def test_explicit_user_group_b_project_group_b_project_a_login_succeeds(
        self, client, fake_redis, patched_cache_manager, patched_activity_logger,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        """Consumer in user_group_b may login to project_a through project_group_b."""
        user = _make_user(user_type="consumer", user_id="usr-b", username="consumer_b")
        project_a = _make_project(project_id="prj-a-id", project_hash="project-a-hash", project_name="Project A")
        user_group_b = _make_user_group(group_id="ug-b", group_hash="user-group-b", group_name="User Group B")

        with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
             patch("src.routes.auth.get_user_accessible_projects", return_value=[project_a]), \
             patch("src.routes.auth.get_project_by_hash", return_value=project_a), \
             patch("src.routes.auth.get_user_groups_for_user", return_value=[user_group_b]):
            response = await client.post(
                "/auth/login",
                data={
                    "username": "consumer_b",
                    "password": "correctpass",
                    "project_hash": "project-a-hash",
                },
            )

        assert response.status_code == 200
        data = response.json()
        assert data["project"]["project_hash"] == "project-a-hash"
        assert len([p for p in data["accessible_projects"] if p["project_hash"] == "project-a-hash"]) == 1
        assert "project_group_b" not in str(data)
        assert "access_path" not in str(data)

    @pytest.mark.asyncio
    async def test_consumer_login_to_archived_project_is_denied(
        self, client, fake_redis, patched_cache_manager, patched_activity_logger,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        user = _make_user(user_type="consumer")
        archived_project = _make_project(project_hash="archived-project-hash", archived=True)
        group = _make_user_group()

        with patch("src.routes.auth.get_user_by_credentials", return_value=user), \
             patch("src.routes.auth.get_user_accessible_projects", return_value=[archived_project]), \
             patch("src.routes.auth.get_project_by_hash", return_value=archived_project), \
             patch("src.routes.auth.get_user_groups_for_user", return_value=[group]):
            response = await client.post(
                "/auth/login",
                data={
                    "username": "archiveduser",
                    "password": "correctpass",
                    "project_hash": "archived-project-hash",
                },
            )

        assert response.status_code == 403
        data = response.json()
        assert data["status"] == "error"
        assert "archived-project-hash" not in str(data)

    @pytest.mark.asyncio
    async def test_root_login_to_archived_project_is_denied(
        self, client, fake_redis, patched_cache_manager, patched_activity_logger,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        root_user = _make_user(user_type="root", user_id="root-1", username="root")
        archived_project = _make_project(project_hash="root-archived-project", archived=True)

        with patch("src.routes.auth.get_user_by_credentials", return_value=root_user), \
             patch("src.routes.auth.get_project_by_hash", return_value=archived_project), \
             patch("src.routes.auth.get_user_accessible_projects", return_value=[]):
            response = await client.post(
                "/auth/login",
                data={
                    "username": "root",
                    "password": "correctpass",
                    "project_hash": "root-archived-project",
                },
            )

        assert response.status_code == 403
        assert "root-archived-project" not in str(response.json())

    @pytest.mark.asyncio
    async def test_admin_group_chain_without_assignment_is_denied(
        self, client, fake_redis, patched_cache_manager, patched_activity_logger,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        admin_user = _make_user(user_type="admin", user_id="admin-1", username="admin")
        project = _make_project(project_id="project-only-via-group", project_hash="admin-chain-project")
        admin_group = _make_user_group(group_name="Some Consumer-Like Group")

        with patch("src.routes.auth.get_user_by_credentials", return_value=admin_user), \
             patch("src.routes.auth.get_project_by_hash", return_value=project), \
             patch("src.routes.auth.get_user_accessible_projects", return_value=[project]), \
             patch("src.routes.auth.get_user_groups_for_user", return_value=[admin_group]), \
             patch("src.routes.auth.check_admin_multi_project_access", return_value=False, create=True), \
             patch("src.routes.auth.get_admin_project_assignments_with_details", return_value=[], create=True):
            response = await client.post(
                "/auth/login",
                data={
                    "username": "admin",
                    "password": "correctpass",
                    "project_hash": "admin-chain-project",
                },
            )

        assert response.status_code == 403
        assert "access_path" not in str(response.json())

    @pytest.mark.asyncio
    async def test_switch_project_to_archived_project_is_denied(
        self, client, fake_redis, patched_cache_manager, patched_activity_logger,
        patched_audit_logger, patched_audit_ids, patched_db_connection,
        patched_db_error_logger,
    ):
        from src.Util.Models import EnhancedUserLogin

        archived_project = _make_project(project_hash="switch-archived-project", archived=True)
        current_session = EnhancedUserLogin(
            user_hash="usr-switch",
            project_hash="current-project",
            project_name="Current Project",
            user_project_hash="",
            session_token="current.access.token",
            session_length=900,
            user_id="usr-switch-id",
            project_id="current-project-id",
            groups=["Consumers"],
            permissions=[],
            user_type="consumer",
        )

        with patch("src.routes.auth.JWTTokenHandler.decode_access_token", return_value={"family_id": "fam-switch"}), \
             patch("src.routes.auth.validate_access_session", return_value=current_session), \
             patch("src.routes.auth.get_project_by_hash", return_value=archived_project), \
             patch("src.routes.auth.get_user_accessible_projects", return_value=[archived_project]):
            response = await client.post(
                "/auth/switch-project",
                data={"project_hash": "switch-archived-project", "refresh_token": "refresh.token"},
                headers={"Authorization": "Bearer current.access.token"},
            )

        assert response.status_code == 403
        assert "switch-archived-project" not in str(response.json())
