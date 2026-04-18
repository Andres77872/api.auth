"""Unit tests for src/Util/Models.py — Slice 11.

Key request/response models validation. There are 80+ models; we test the
most critical ones for auth flows.
"""

import pytest
from datetime import datetime, timezone
from pydantic import ValidationError

from src.Util.Models import (
    LoginRequest,
    RegisterRequest,
    SwitchProjectRequest,
    CheckAvailabilityRequest,
    UserUpdateRequest,
    ProjectCreateRequest,
    ProjectUpdateRequest,
    CreateRootUserRequest,
    CreateAdminUserRequest,
    UserLogin,
    EnhancedUserLogin,
    User,
    Project,
)


# ─── LoginRequest ───────────────────────────────────────────────────────────

class TestLoginRequest:
    def test_valid_login(self):
        """project_hash=None is valid at the model level.
        
        At the route level, non-root users MUST provide project_hash.
        The conditional enforcement happens in auth.py after credential verification.
        """
        req = LoginRequest(username="john", password="secret")
        assert req.username == "john"
        assert req.password == "secret"
        assert req.project_hash is None

    def test_login_with_project(self):
        req = LoginRequest(username="john", password="secret", project_hash="proj-abc")
        assert req.project_hash == "proj-abc"

    def test_missing_username_fails(self):
        with pytest.raises(ValidationError):
            LoginRequest(password="secret")  # type: ignore

    def test_missing_password_fails(self):
        with pytest.raises(ValidationError):
            LoginRequest(username="john")  # type: ignore


# ─── RegisterRequest ────────────────────────────────────────────────────────

class TestRegisterRequest:
    def test_valid_register(self):
        req = RegisterRequest(
            username="john",
            password="secret",
            email="john@example.com",
            user_group_hash="ug-abc",
        )
        assert req.username == "john"
        assert req.email == "john@example.com"
        assert req.user_group_hash == "ug-abc"

    def test_missing_required_field_fails(self):
        with pytest.raises(ValidationError):
            RegisterRequest(username="john", password="secret", email="john@example.com")  # type: ignore


# ─── SwitchProjectRequest ───────────────────────────────────────────────────

class TestSwitchProjectRequest:
    def test_valid_switch(self):
        req = SwitchProjectRequest(project_hash="proj-xyz")
        assert req.project_hash == "proj-xyz"

    def test_missing_project_hash_fails(self):
        with pytest.raises(ValidationError):
            SwitchProjectRequest()  # type: ignore


# ─── CheckAvailabilityRequest ───────────────────────────────────────────────

class TestCheckAvailabilityRequest:
    def test_check_username(self):
        req = CheckAvailabilityRequest(username="john")
        assert req.username == "john"
        assert req.email is None

    def test_check_email(self):
        req = CheckAvailabilityRequest(email="john@example.com")
        assert req.email == "john@example.com"
        assert req.username is None

    def test_both_fields(self):
        req = CheckAvailabilityRequest(username="john", email="john@example.com")
        assert req.username == "john"
        assert req.email == "john@example.com"

    def test_neither_field_valid(self):
        # Both optional, so empty is valid
        req = CheckAvailabilityRequest()
        assert req.username is None
        assert req.email is None


# ─── UserUpdateRequest ──────────────────────────────────────────────────────

class TestUserUpdateRequest:
    def test_all_fields_optional(self):
        req = UserUpdateRequest()
        assert req.username is None
        assert req.email is None
        assert req.password is None

    def test_partial_update(self):
        req = UserUpdateRequest(username="new_name")
        assert req.username == "new_name"
        assert req.email is None


# ─── ProjectCreateRequest ───────────────────────────────────────────────────

class TestProjectCreateRequest:
    def test_valid_create(self):
        req = ProjectCreateRequest(project_name="My Project")
        assert req.project_name == "My Project"
        assert req.project_description is None

    def test_with_description(self):
        req = ProjectCreateRequest(project_name="My Project", project_description="A test project")
        assert req.project_description == "A test project"

    def test_missing_name_fails(self):
        with pytest.raises(ValidationError):
            ProjectCreateRequest()  # type: ignore


# ─── ProjectUpdateRequest ───────────────────────────────────────────────────

class TestProjectUpdateRequest:
    def test_all_fields_optional(self):
        req = ProjectUpdateRequest()
        assert req.project_name is None
        assert req.project_description is None


# ─── CreateRootUserRequest ──────────────────────────────────────────────────

class TestCreateRootUserRequest:
    def test_valid_create(self):
        req = CreateRootUserRequest(username="root", password="secret")
        assert req.username == "root"
        assert req.password == "secret"
        assert req.email is None

    def test_with_email(self):
        req = CreateRootUserRequest(username="root", password="secret", email="root@example.com")
        assert req.email == "root@example.com"

    def test_missing_username_fails(self):
        with pytest.raises(ValidationError):
            CreateRootUserRequest(password="secret")  # type: ignore


# ─── CreateAdminUserRequest ─────────────────────────────────────────────────

class TestCreateAdminUserRequest:
    def test_valid_create(self):
        req = CreateAdminUserRequest(username="admin", password="secret", email="admin@example.com")
        assert req.username == "admin"

    def test_missing_email_fails(self):
        with pytest.raises(ValidationError):
            CreateAdminUserRequest(username="admin", password="secret")  # type: ignore


# ─── UserLogin (legacy) ─────────────────────────────────────────────────────

class TestUserLogin:
    def test_valid_user_login(self):
        login = UserLogin(
            user_session="ses-abc",
            user_session_length=3600,
            user_hash="USR-123",
            user_collection="proj-xyz",
            user_id="usr-123",
        )
        assert login.user_session == "ses-abc"
        assert login.user_session_length == 3600
        assert login.user_type == "consumer"  # default
        assert login.project_id is None
        assert login.groups == []

    def test_with_project(self):
        login = UserLogin(
            user_session="ses-abc",
            user_session_length=3600,
            user_hash="USR-123",
            user_collection="proj-xyz",
            user_id="usr-123",
            project_id="proj-123",
            user_type="admin",
        )
        assert login.project_id == "proj-123"
        assert login.user_type == "admin"

    def test_with_groups(self):
        login = UserLogin(
            user_session="ses-abc",
            user_session_length=3600,
            user_hash="USR-123",
            user_collection="proj-xyz",
            user_id="usr-123",
            groups=["admin_group", "editor_group"],
        )
        assert len(login.groups) == 2

    def test_missing_required_field_fails(self):
        with pytest.raises(ValidationError):
            UserLogin(
                user_session_length=3600,
                user_hash="USR-123",
                user_collection="proj-xyz",
                user_id="usr-123",
            )  # type: ignore — missing user_session


# ─── EnhancedUserLogin ──────────────────────────────────────────────────────

class TestEnhancedUserLogin:
    def test_valid_enhanced_login(self):
        login = EnhancedUserLogin(
            user_hash="USR-123",
            project_hash="proj-abc",
            project_name="My Project",
            session_token="tok-xyz",
            session_length=3600,
            user_id="usr-123",
        )
        assert login.user_hash == "USR-123"
        assert login.project_name == "My Project"
        assert login.user_type == "consumer"
        assert login.groups == []
        assert login.permissions == []
        assert login.available_projects == []

    def test_with_permissions(self):
        login = EnhancedUserLogin(
            user_hash="USR-123",
            project_hash="proj-abc",
            project_name="My Project",
            session_token="tok-xyz",
            session_length=3600,
            user_id="usr-123",
            permissions=["read", "write"],
        )
        assert login.permissions == ["read", "write"]

    def test_root_user_with_project(self):
        login = EnhancedUserLogin(
            user_hash="USR-root",
            project_hash="prj-test-001",
            project_name="Test Project",
            session_token="tok-root",
            session_length=259200,
            user_id="usr-root",
            project_id="1",
            user_type="root",
        )
        assert login.user_type == "root"
        assert login.project_hash == "prj-test-001"

    def test_missing_required_field_fails(self):
        with pytest.raises(ValidationError):
            EnhancedUserLogin(
                project_hash="proj-abc",
                project_name="My Project",
                session_token="tok-xyz",
                session_length=3600,
                user_id="usr-123",
            )  # type: ignore — missing user_hash


# ─── User entity ────────────────────────────────────────────────────────────

class TestUserEntity:
    def test_valid_user(self):
        now = datetime.now(timezone.utc)
        user = User(
            id="usr-123",
            user_hash="USR-abc",
            username="john",
            password_hash="$argon2id$...",
            created_at=now,
        )
        assert user.user_type == "consumer"  # default
        assert user.is_active is True
        assert user.email is None

    def test_user_with_all_fields(self):
        now = datetime.now(timezone.utc)
        user = User(
            id="usr-123",
            user_hash="USR-abc",
            username="john",
            email="john@example.com",
            password_hash="$argon2id$...",
            user_type="admin",
            assigned_project_id="proj-123",
            created_at=now,
            is_active=True,
        )
        assert user.email == "john@example.com"
        assert user.user_type == "admin"

    def test_missing_required_field_fails(self):
        with pytest.raises(ValidationError):
            User(
                user_hash="USR-abc",
                username="john",
                password_hash="hash",
                created_at=datetime.now(timezone.utc),
            )  # type: ignore — missing id


# ─── Project entity ─────────────────────────────────────────────────────────

class TestProjectEntity:
    def test_valid_project(self):
        now = datetime.now(timezone.utc)
        project = Project(
            id="proj-123",
            project_hash="PROJ-abc",
            project_name="My Project",
            project_created=now,
        )
        assert project.is_active is True
        assert project.project_description is None

    def test_project_with_description(self):
        now = datetime.now(timezone.utc)
        project = Project(
            id="proj-123",
            project_hash="PROJ-abc",
            project_name="My Project",
            project_description="A test project",
            project_created=now,
        )
        assert project.project_description == "A test project"
