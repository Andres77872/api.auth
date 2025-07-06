"""
UUID Generator Utility

Centralized UUID generation for database entities to ensure consistent formatting
across the application.
"""

import uuid


def generate_user_id() -> str:
    """Generate a unique user ID with 'usr-' prefix."""
    return f"usr-{str(uuid.uuid4())}"


def generate_project_id() -> str:
    """Generate a unique project ID with 'proj-' prefix."""
    return f"proj-{str(uuid.uuid4())}"


def generate_user_group_id() -> str:
    """Generate a unique user group ID with 'ug-' prefix."""
    return f"ug-{str(uuid.uuid4())}"


def generate_permission_id() -> str:
    """Generate a unique permission ID with 'perm-' prefix."""
    return f"perm-{str(uuid.uuid4())}"


def generate_permission_group_id() -> str:
    """Generate a unique permission group ID with 'pg-' prefix."""
    return f"pg-{str(uuid.uuid4())}"


def generate_user_group_member_id() -> str:
    """Generate a unique user group member ID."""
    return f"ugm-{str(uuid.uuid4()).replace('-', '')}"


def generate_user_group_project_id() -> str:
    """Generate a unique user group project ID."""
    return f"ugp-{str(uuid.uuid4()).replace('-', '')}"


def generate_permission_group_permission_id() -> str:
    """Generate a unique permission group permission ID."""
    return f"pgp-{str(uuid.uuid4()).replace('-', '')}"


def generate_user_group_permission_group_id() -> str:
    """Generate a unique user group permission group assignment ID."""
    return f"ugpg-{str(uuid.uuid4()).replace('-', '')}"


def generate_session_id() -> str:
    """Generate a unique session ID."""
    return f"ses-{str(uuid.uuid4())}"


def generate_audit_log_id() -> str:
    """Generate a unique audit log ID."""
    return f"audit-{str(uuid.uuid4()).replace('-', '')}"


def generate_activity_log_id() -> str:
    """Generate a unique activity log ID."""
    return f"act-{str(uuid.uuid4()).replace('-', '')}"


def generate_bulk_operation_id() -> str:
    """Generate a unique bulk operation ID."""
    return f"bulk-{str(uuid.uuid4()).replace('-', '')}"


def generate_hash(prefix: str) -> str:
    """Generate a hash with custom prefix."""
    return f"{prefix.upper()}-{str(uuid.uuid4()).replace('-', '').upper()}"


def generate_user_hash() -> str:
    """Generate a unique user hash."""
    return generate_hash("usr")


def generate_project_hash() -> str:
    """Generate a unique project hash."""
    return generate_hash("proj")


def generate_user_group_hash() -> str:
    """Generate a unique user group hash."""
    return generate_hash("ug")


def generate_permission_hash() -> str:
    """Generate a unique permission hash."""
    return generate_hash("perm")


def generate_permission_group_hash() -> str:
    """Generate a unique permission group hash."""
    return generate_hash("pg") 