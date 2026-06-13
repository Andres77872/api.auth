"""
Enhanced Multi-Project Authentication - User Group Management

This module handles all user group-related database operations in the new
hierarchical access control system where:
- Users belong to User Groups (global)
- User Groups define which projects users can access
- Permissions are defined at the project level through Project Groups
"""

import secrets
from datetime import datetime
from typing import List, Optional, Tuple

import pymysql

from src.Util.Models import (
    User, UserGroup, UserGroupMember, ProjectSummary
)
from src.Util.db_config import get_connection
from src.Util.uuid_generator import generate_user_group_id, generate_user_group_project_id, \
    generate_user_group_member_id
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.error_handler import ValidationError, NotFoundError, ErrorCode, mask_uuid


# =================== USER GROUP MANAGEMENT ===================

def create_user_group(group_name: str, group_description: str = None, created_by: str = None) -> UserGroup:
    """
    Create a new global user group.
    
    Args:
        group_name: Name of the group (must be unique)
        group_description: Optional description
        created_by: User ID who created the group
        
    Returns:
        Created UserGroup object
        
    Raises:
        ConflictError: If group name already exists
        DatabaseError: On database operation errors
    """
    def _create():
        group_hash = secrets.token_hex(32).upper()
        group_id = generate_user_group_id()
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_create_user_group', [group_id, group_hash, group_name, group_description, None, created_by])
            con.commit()

            return UserGroup(
                id=group_id,
                group_hash=group_hash,
                group_name=group_name,
                group_description=group_description,
                created_at=datetime.now(),
                is_active=True
            )
    
    return handle_db_operation(
        _create,
        error_context=f"create_user_group(group_name='{group_name}')"
    )


def get_user_group_by_id(group_id: str) -> Optional[UserGroup]:
    """
    Get user group by ID.
    
    Args:
        group_id: Group ID to retrieve
        
    Returns:
        UserGroup object if found, None if not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_group_by_id', [group_id])
            result = cur.fetchone()
            if result:
                # SP returns: id, group_hash, group_name, group_description, parent_group_id, created_at, updated_at, created_by, is_active
                return UserGroup(
                    id=result[0],
                    group_hash=result[1],
                    group_name=result[2],
                    group_description=result[3],
                    created_at=result[5],
                    updated_at=result[6],
                    is_active=bool(result[8])
                )
            return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_group_by_id(group_id={group_id})"
    )


def get_user_group_by_hash(group_hash: str) -> Optional[UserGroup]:
    """
    Get user group by hash.
    
    Args:
        group_hash: Group hash to retrieve
        
    Returns:
        UserGroup object if found, None if not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_group_by_hash', [group_hash])
            result = cur.fetchone()
            if result:
                # SP returns: id, group_hash, group_name, group_description, parent_group_id, created_at, updated_at, created_by, is_active
                return UserGroup(
                    id=result[0],
                    group_hash=result[1],
                    group_name=result[2],
                    group_description=result[3],
                    created_at=result[5],
                    updated_at=result[6],
                    is_active=bool(result[8])
                )
            return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_group_by_hash(group_hash={mask_uuid(group_hash)})"
    )


def get_user_group_by_name(group_name: str) -> Optional[UserGroup]:
    """
    Get user group by name.
    
    Args:
        group_name: Group name to retrieve
        
    Returns:
        UserGroup object if found, None if not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_group_by_name', [group_name])
            result = cur.fetchone()
            if result:
                # SP returns: id, group_hash, group_name, group_description, parent_group_id, created_at, updated_at, created_by, is_active
                return UserGroup(
                    id=result[0],
                    group_hash=result[1],
                    group_name=result[2],
                    group_description=result[3],
                    created_at=result[5],
                    updated_at=result[6],
                    is_active=bool(result[8])
                )
            return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_group_by_name(group_name='{group_name}')"
    )


def list_all_user_groups(limit: int = 100, offset: int = 0, sort_by: str = 'group_name', sort_order: str = 'asc',
                         search: str = None) -> List[UserGroup]:
    """
    List all active user groups with pagination, sorting and search.
    
    Args:
        limit: Maximum number of groups to return
        offset: Number of groups to skip
        sort_by: Field to sort by (group_name, created_at, updated_at, id)
        sort_order: Sort direction (asc or desc)
        search: Optional search term for group name
        
    Returns:
        List of UserGroup objects
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _list():
        # Validate sort parameters to prevent SQL injection
        valid_sort_fields = ['group_name', 'created_at', 'updated_at', 'id']
        validated_sort_by = sort_by if sort_by in valid_sort_fields else 'group_name'

        # Validate sort order
        sort_direction = sort_order.lower()

        with get_connection() as con:
            cur = con.cursor()

            # Use stored procedure for dynamic list with sorting
            cur.callproc('sp_list_all_user_groups', [limit, offset, validated_sort_by, sort_direction, search])

            results = []
            for row in cur.fetchall():
                # SP returns: id, group_hash, group_name, group_description, parent_group_id, created_at, updated_at, is_active
                results.append(UserGroup(
                    id=row[0],
                    group_hash=row[1],
                    group_name=row[2],
                    group_description=row[3],
                    created_at=row[5],
                    updated_at=row[6],
                    is_active=bool(row[7])
                ))
            return results
    
    return handle_db_operation(
        _list,
        error_context=f"list_all_user_groups(limit={limit}, offset={offset}, search='{search}')"
    )


def update_user_group(group_id: str, group_name: str = None, group_description: str = None) -> Optional[UserGroup]:
    """
    Update user group information.
    
    Args:
        group_id: Group ID to update
        group_name: New group name (optional)
        group_description: New description (optional)
        
    Returns:
        Updated UserGroup object if successful, None if group not found
        
    Raises:
        ValidationError: If no fields provided for update
        ConflictError: If new group name already exists
        NotFoundError: If group not found
        DatabaseError: On database operation errors
    """
    if not group_name and group_description is None:
        raise ValidationError(
            message="At least one field must be provided for update",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"fields": ["group_name", "group_description"]}
        )

    def _update():
        with get_connection() as con:
            cur = con.cursor()

            # Use stored procedure for update (sp_update_user_group uses COALESCE for NULL params)
            cur.callproc('sp_update_user_group', [group_id, group_name, group_description])

            # Get the result
            result = cur.fetchone()
            rows_affected = result[0] if result else 0

            if rows_affected > 0:
                con.commit()
                return get_user_group_by_id(group_id)
            else:
                raise NotFoundError(
                    message=f"User group not found: {group_id}",
                    error_code=ErrorCode.NOT_FOUND
                )
    
    return handle_db_operation(
        _update,
        error_context=f"update_user_group(group_id={group_id})"
    )


def delete_user_group(group_id: str, deleted_by: str = None) -> bool:
    """
    Soft delete a user group and all related relationships.
    
    Args:
        group_id: Group ID to delete
        deleted_by: User ID who performed the deletion
        
    Returns:
        True if deleted successfully
        
    Raises:
        NotFoundError: If group not found
        DatabaseError: On database operation errors
    """
    def _delete():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_delete_user_group', [group_id, deleted_by])
            con.commit()
            return True
    
    return handle_db_operation(
        _delete,
        error_context=f"delete_user_group(group_id={group_id})"
    )


# =================== USER GROUP MEMBERSHIP ===================

def assign_user_to_group(user_id: str, user_group_id: str, assigned_by: str = None) -> Optional[UserGroupMember]:
    """
    Assign a user to a user group (or reactivate if already exists).
    
    Args:
        user_id: User ID to assign
        user_group_id: Group ID to assign to
        assigned_by: User ID who performed the assignment
        
    Returns:
        UserGroupMember object
        
    Raises:
        ConflictError: If assignment fails due to constraint violation
        DatabaseError: On database operation errors
        
    Note:
        Automatically reactivates membership if user was previously in group
    """
    def _assign():
        with get_connection() as con:
            cur = con.cursor()
            member_id = generate_user_group_member_id()
            try:
                cur.callproc('sp_assign_user_to_group', [member_id, user_id, user_group_id, assigned_by])
                while cur.nextset():
                    pass
                con.commit()

                return UserGroupMember(
                    id=member_id,
                    user_id=user_id,
                    user_group_id=user_group_id,
                    assigned_at=datetime.now(),
                    assigned_by=assigned_by,
                    is_active=True
                )

            except pymysql.IntegrityError:
                # User already in group, reactivate if needed
                cur.callproc('sp_reactivate_user_group_membership', [user_id, user_group_id, assigned_by])
                result = cur.fetchone()
                while cur.nextset():
                    pass

                rows_affected = result[0] if result else 0
                if rows_affected > 0:
                    con.commit()
                    return get_user_group_membership(user_id, user_group_id)

                return None
    
    return handle_db_operation(
        _assign,
        error_context=f"assign_user_to_group(user_id={user_id}, user_group_id={user_group_id})"
    )


def remove_user_from_group(user_id: str, user_group_id: str, removed_by: str = None) -> bool:
    """
    Remove a user from a user group (soft delete).
    
    Args:
        user_id: User ID to remove
        user_group_id: Group ID to remove from
        removed_by: User ID who performed the removal
        
    Returns:
        True if removed successfully, False if membership not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _remove():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_remove_user_from_group', [user_id, user_group_id, removed_by])
            con.commit()
            return True
    
    return handle_db_operation(
        _remove,
        error_context=f"remove_user_from_group(user_id={user_id}, user_group_id={user_group_id})"
    )


def get_user_group_membership(user_id: str, user_group_id: str) -> Optional[UserGroupMember]:
    """
    Get specific user group membership.
    
    Args:
        user_id: User ID to check
        user_group_id: Group ID to check
        
    Returns:
        UserGroupMember object if found, None if not found or if SP is missing
        
    Raises:
        DatabaseError: On database operation errors (other than missing SP)
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            try:
                cur.callproc('sp_get_user_group_membership', [user_id, user_group_id])
            except pymysql.err.OperationalError as e:
                error_code = e.args[0] if e.args else None
                if error_code == 1305:
                    return None
                raise
            result = cur.fetchone()
            if result:
                return UserGroupMember(
                    id=result[0],
                    user_id=result[1],
                    user_group_id=result[2],
                    assigned_at=result[3],
                    assigned_by=result[4],
                    removed_at=result[5],
                    removed_by=result[6],
                    is_active=bool(result[7])
                )
            return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_group_membership(user_id={user_id}, user_group_id={user_group_id})"
    )


def get_user_groups_for_user(user_id: str) -> List[UserGroup]:
    """
    Get all user groups a user belongs to.

    Args:
        user_id: User ID to get groups for

    Returns:
        List of UserGroup objects with joined_at attribute set

    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_groups_for_user', [user_id])
            groups = []
            for row in cur.fetchall():
                # Stored procedure returns: id, group_hash, group_name, group_description,
                # parent_group_id, created_at, updated_at, is_active, joined_at
                group = UserGroup(
                    id=row[0],
                    group_hash=row[1],
                    group_name=row[2],
                    group_description=row[3],
                    created_at=row[5],  # Index 5 after parent_group_id
                    updated_at=row[6],
                    is_active=bool(row[7])
                )
                # Add joined_at from membership record (assigned_at in the SP)
                group.joined_at = row[8] if len(row) > 8 else None
                groups.append(group)

            return groups

    return handle_db_operation(
        _get,
        error_context=f"get_user_groups_for_user(user_id={user_id})"
    )


def get_users_in_group(user_group_id: str) -> List[User]:
    """
    Get all users in a user group.
    
    Args:
        user_group_id: Group ID to get users for
        
    Returns:
        List of User objects with assigned_at attribute set
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_users_in_group', [user_group_id])
            users = []
            for row in cur.fetchall():
                # Stored procedure returns: id, user_hash, username, email, user_type, 
                # role_id, created_at, updated_at, is_active, assigned_at, assigned_by
                user = User(
                    id=row[0],
                    user_hash=row[1],
                    username=row[2],
                    email=row[3],
                    password_hash="",  # Not returned by stored procedure for security
                    user_type=row[4],
                    assigned_project_id=None,
                    created_at=row[6],
                    updated_at=row[7],
                    last_login=None,
                    is_active=bool(row[8])
                )
                # Add assigned_at from membership record (index 9)
                # This is when the user joined the group
                user.assigned_at = row[9] if len(row) > 9 else None
                users.append(user)

            return users
    
    return handle_db_operation(
        _get,
        error_context=f"get_users_in_group(user_group_id={user_group_id})"
    )


# ===================================================================================
# PROJECT ACCESS VIA PROJECT GROUPS (Groups-of-Groups Architecture)
# ===================================================================================
# Direct user group → project access is NOT supported.
# Access is managed through PROJECT GROUPS:
#
#   USER → USER_GROUP → PROJECT_GROUP → PROJECT
#
# To grant a user group access to projects:
#   1. Use grant_user_group_project_group_access() to link user group to project group
#   2. Projects in that project group become accessible to all users in the user group
#
# See: db_project_groups.py for project group management
# ===================================================================================


def get_projects_for_user_group(user_group_id: str) -> List[Tuple[int, str, str]]:
    """
    Get all projects accessible by a user group.
    
    Args:
        user_group_id: Group ID to get projects for
        
    Returns:
        List of tuples (project_id, project_hash, project_name, project_description)
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_projects_for_user_group', [user_group_id])
            return cur.fetchall()
    
    return handle_db_operation(
        _get,
        error_context=f"get_projects_for_user_group(user_group_id={user_group_id})"
    )


def get_user_groups_for_project(project_id: str) -> List[UserGroup]:
    """
    Get all user groups that have access to a project.
    
    Args:
        project_id: Project ID to get groups for
        
    Returns:
        List of UserGroup objects with member_count
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_groups_for_project', [project_id])
            groups = []
            for row in cur.fetchall():
                groups.append(UserGroup(
                    id=row[0],
                    group_hash=row[1],
                    group_name=row[2],
                    group_description=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                    is_active=bool(row[6]),
                    member_count=row[7]
                ))

            return groups
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_groups_for_project(project_id={project_id})"
    )


# =================== UTILITIES ===================

def get_user_accessible_projects(user_id: str) -> List[ProjectSummary]:
    """
    Get all projects accessible by a user through their group memberships.
    
    Args:
        user_id: User ID to get accessible projects for
        
    Returns:
        List of ProjectSummary objects
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()

            # Call stored procedure to obtain projects
            cur.callproc('sp_get_user_accessible_projects', [user_id])

            projects: List[ProjectSummary] = []
            for row in cur.fetchall():
                projects.append(
                    ProjectSummary(
                        id=row[0],
                        project_hash=row[1],
                        project_name=row[2],
                        project_description=row[3],
                        project_group_name="",  # Not provided in new SP
                        permissions=[],  # Permissions not part of this query
                    )
                )

            # Clean up additional result-sets (just in case)
            while cur.nextset():
                pass

            return projects
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_accessible_projects(user_id={user_id})"
    )


def count_user_groups() -> int:
    """
    Count total number of active user groups.
    
    Returns:
        Count of active user groups
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _count():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_count_user_groups', [])
            return cur.fetchone()[0]
    
    return handle_db_operation(
        _count,
        error_context="count_user_groups()"
    )


def get_total_user_groups_count() -> int:
    """
    Get total count of active user groups.
    
    Returns:
        Count of active user groups
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _count():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_count_user_groups', [])
            return cur.fetchone()[0]
    
    return handle_db_operation(
        _count,
        error_context="get_total_user_groups_count()"
    )


def get_user_groups_in_project(user_id: str, project_id: str) -> List[UserGroup]:
    """
    Get user groups that a user belongs to AND that have access to a specific project.
    
    This function returns the intersection of:
    - User groups the user is a member of
    - User groups that have access to the specified project
    
    Args:
        user_id: The user ID
        project_id: The project ID
        
    Returns:
        List of UserGroup objects that the user belongs to and that have access to the project
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_groups_in_project', [user_id, project_id])
            groups = []
            for row in cur.fetchall():
                groups.append(UserGroup(
                    id=row[0],
                    group_hash=row[1],
                    group_name=row[2],
                    group_description=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                    is_active=bool(row[6])
                ))

            return groups
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_groups_in_project(user_id={user_id}, project_id={project_id})"
    )


def get_user_groups_in_project_by_hash(user_id: str, project_hash: str) -> List[UserGroup]:
    """
    Get user groups that a user belongs to AND that have access to a specific project (by project hash).
    
    This function returns the intersection of:
    - User groups the user is a member of
    - User groups that have access to the specified project
    
    Args:
        user_id: The user ID
        project_hash: The project hash
        
    Returns:
        List of UserGroup objects that the user belongs to and that have access to the project
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_user_groups_in_project_by_hash', [user_id, project_hash])
            groups = []
            for row in cur.fetchall():
                groups.append(UserGroup(
                    id=row[0],
                    group_hash=row[1],
                    group_name=row[2],
                    group_description=row[3],
                    created_at=row[4],
                    updated_at=row[5],
                    is_active=bool(row[6])
                ))

            return groups
    
    return handle_db_operation(
        _get,
        error_context=f"get_user_groups_in_project_by_hash(user_id={user_id}, project_hash={mask_uuid(project_hash)})"
    )


# =================== PROJECT GROUP ACCESS (Groups-of-Groups Architecture) ===================

def grant_user_group_project_group_access(user_group_id: str, project_group_id: str, granted_by: str = None) -> Optional[dict]:
    """
    Grant a user group access to a project group (groups-of-groups architecture).
    
    This is the correct way to grant project access in the groups-of-groups architecture:
    USER → USER_GROUP → PROJECT_GROUP → PROJECT
    
    Args:
        user_group_id: User group ID to grant access to
        project_group_id: Project group ID to grant access for
        granted_by: User ID who granted the access
        
    Returns:
        Dictionary with access details or None on failure
        
    Raises:
        ConflictError: If access already exists
        DatabaseError: On database operation errors
    """
    def _grant():
        with get_connection() as con:
            cur = con.cursor()
            access_id = generate_user_group_project_id()
            cur.callproc('sp_grant_user_group_project_group_access', [access_id, user_group_id, project_group_id, granted_by])
            con.commit()
            
            return {
                "access_id": access_id,
                "user_group_id": user_group_id,
                "project_group_id": project_group_id,
                "granted_by": granted_by,
                "granted_at": datetime.now()
            }
    
    return handle_db_operation(
        _grant,
        error_context=f"grant_user_group_project_group_access(user_group_id={user_group_id}, project_group_id={project_group_id})"
    )


def revoke_user_group_project_group_access(user_group_id: str, project_group_id: str, revoked_by: str = None) -> bool:
    """
    Revoke a user group's access to a project group.
    
    Args:
        user_group_id: User group ID to revoke access from
        project_group_id: Project group ID to revoke access for
        revoked_by: User ID who revoked the access
        
    Returns:
        True if revoked successfully, False if access not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _revoke():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_revoke_user_group_project_group_access', [user_group_id, project_group_id, revoked_by])
            result = cur.fetchone()
            while cur.nextset():
                pass
            rows_affected = result[0] if result else 0
            con.commit()
            return rows_affected > 0
    
    return handle_db_operation(
        _revoke,
        error_context=f"revoke_user_group_project_group_access(user_group_id={user_group_id}, project_group_id={project_group_id})"
    )


def get_project_groups_for_user_group(user_group_id: str) -> List[dict]:
    """
    Get all project groups that a user group has access to.
    
    This follows the groups-of-groups architecture:
    USER_GROUP → PROJECT_GROUP → PROJECT
    
    Args:
        user_group_id: User group ID to get project groups for
        
    Returns:
        List of dictionaries with project group info including:
        - group_id, group_hash, group_name, group_description
        - created_at, is_active, granted_at, granted_by
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_project_groups_for_user_group', [user_group_id])
            project_groups = []
            for row in cur.fetchall():
                # SP returns: pg.id, pg.group_hash, pg.group_name, pg.group_description,
                #             pg.created_at, pg.is_active, ugpg.granted_at, ugpg.granted_by
                project_groups.append({
                    "group_id": row[0],
                    "group_hash": row[1],
                    "group_name": row[2],
                    "group_description": row[3] if len(row) > 3 else None,
                    "created_at": row[4] if len(row) > 4 else None,
                    "is_active": bool(row[5]) if len(row) > 5 else True,
                    "granted_at": row[6] if len(row) > 6 else None,
                    "granted_by": row[7] if len(row) > 7 else None
                })
            return project_groups
    
    return handle_db_operation(
        _get,
        error_context=f"get_project_groups_for_user_group(user_group_id={user_group_id})"
    )


def check_user_group_project_group_access(user_group_id: str, project_group_id: str) -> bool:
    """
    Check if a user group has access to a project group.
    
    Args:
        user_group_id: User group ID to check
        project_group_id: Project group ID to check
        
    Returns:
        True if user group has access, False otherwise
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _check():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_check_user_group_project_group_access', [user_group_id, project_group_id])
            result = cur.fetchone()
            return bool(result[0]) if result else False
    
    return handle_db_operation(
        _check,
        error_context=f"check_user_group_project_group_access(user_group_id={user_group_id}, project_group_id={project_group_id})"
    )
