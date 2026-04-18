"""
Enhanced Multi-Project Authentication - Project Database Operations

This module handles all project-related database operations including:
- Project management (create, read, update, delete)
- Project search and statistics
- Project group management
- Default group creation
"""

import secrets
from datetime import datetime
from typing import List, Optional, Dict, Any, Tuple

from src.Util.Models import Project, LegacyUserGroup as UserGroup
from src.Util.db_config import get_connection
from src.Util.uuid_generator import generate_project_id, generate_user_group_id, generate_project_group_id, generate_project_group_member_id
from src.Util.db_error_wrapper import handle_db_operation
from src.Util.error_handler import mask_uuid


# =================== PROJECT MANAGEMENT ===================

def create_project(project_name: str, project_description: str = None, created_by: str = None, owner_id: str = None) -> Project:
    """
    Create a new project/application with RBAC initialization.
    
    Args:
        project_name: Unique project name
        project_description: Project description (optional)
        created_by: User ID of creator
        owner_id: User ID of project owner (defaults to created_by if not provided)
        
    Returns:
        Created Project object
        
    Raises:
        ConflictError: If project name already exists
        DatabaseError: On database operation errors
    """
    def _create():
        project_hash = secrets.token_hex(32).upper()
        project_id = generate_project_id()
        # Default owner_id to created_by if not provided
        effective_owner_id = owner_id if owner_id else created_by
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_create_project', [project_id, project_hash, project_name, project_description, created_by, effective_owner_id])
            con.commit()

            create_default_groups(project_id)

            return Project(
                id=project_id,
                project_hash=project_hash,
                project_name=project_name,
                project_description=project_description,
                project_created=datetime.now(),
                is_active=True
            )
    
    return handle_db_operation(
        _create,
        error_context=f"create_project(project_name='{project_name}')"
    )


def get_project_by_hash(project_hash: str) -> Optional[Project]:
    """
    Get project by project hash.
    
    Args:
        project_hash: Project hash to lookup
        
    Returns:
        Project object or None if not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_project_by_hash', [project_hash])
            result = cur.fetchone()
            if result:
                return Project(
                    id=result[0],
                    project_hash=result[1],
                    project_name=result[2],
                    project_description=result[3],
                    project_created=result[4],
                    is_active=bool(result[5])
                )
            return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_project_by_hash(project_hash='{mask_uuid(project_hash)}')"
    )


def get_project_by_id(project_id: str) -> Optional[Project]:
    """
    Get project by project ID.
    
    Args:
        project_id: Project ID to lookup
        
    Returns:
        Project object or None if not found
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_project_by_id', [project_id])
            result = cur.fetchone()
            if result:
                return Project(
                    id=result[0],
                    project_hash=result[1],
                    project_name=result[2],
                    project_description=result[3],
                    project_created=result[4],
                    is_active=bool(result[5])
                )
            return None
    
    return handle_db_operation(
        _get,
        error_context=f"get_project_by_id(project_id={project_id})"
    )


def list_all_projects(
    limit: int = 100, 
    offset: int = 0,
    sort_by: str = 'project_created',
    sort_order: str = 'DESC',
    search: str = None,
    include_archived: bool = False
) -> List[Project]:
    """
    List all active projects with pagination, sorting, and filtering.
    
    Args:
        limit: Maximum results to return
        offset: Offset for pagination
        sort_by: Column to sort by ('project_name', 'updated_at', 'project_created')
        sort_order: Sort direction ('ASC' or 'DESC')
        search: Search term to filter by name or description
        include_archived: If True, include archived projects
        
    Returns:
        List of Project objects
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _list():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_list_all_projects', [
                limit, 
                offset, 
                sort_by, 
                sort_order, 
                search, 
                include_archived
            ])
            results = []
            for row in cur.fetchall():
                results.append(Project(
                    id=row[0],
                    project_hash=row[1],
                    project_name=row[2],
                    project_description=row[3],
                    project_created=row[4],
                    is_active=bool(row[8]) if len(row) > 8 else True
                ))
            return results
    
    return handle_db_operation(
        _list,
        error_context=f"list_all_projects(limit={limit}, offset={offset}, sort_by={sort_by})"
    )


def count_projects(include_archived: bool = False) -> int:
    """
    Count total number of active projects.
    
    Args:
        include_archived: If True, include archived projects in count
    
    Returns:
        Count of active projects
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _count():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_count_projects', [include_archived])
            return cur.fetchone()[0]
    
    return handle_db_operation(
        _count,
        error_context=f"count_projects(include_archived={include_archived})"
    )


def update_project(project_id: str, project_name: str = None, project_description: str = None,
                   updated_by: str = None) -> Optional[Project]:
    """
    Update project information.
    
    Args:
        project_id: Project ID to update
        project_name: New project name (optional)
        project_description: New description (optional)
        updated_by: User ID who performed update
        
    Returns:
        Updated Project object or None if no fields provided
        
    Raises:
        ConflictError: If project name already exists
        DatabaseError: On database operation errors
    """
    if not project_name and project_description is None:
        from src.Util.error_handler import ValidationError, ErrorCode
        raise ValidationError(
            message="At least one field must be provided to update",
            error_code=ErrorCode.INVALID_INPUT,
            details={"project_id": project_id}
        )
    
    def _update():
        with get_connection() as con:
            cur = con.cursor()
            
            # Use stored procedure for update (sp_update_project uses COALESCE for NULL params)
            cur.callproc('sp_update_project', [project_id, project_name, project_description])
            
            # Get the result
            result = cur.fetchone()
            rows_affected = result[0] if result else 0
            
            if rows_affected > 0:
                con.commit()
                return get_project_by_id(project_id)
            else:
                from src.Util.error_handler import NotFoundError, ErrorCode
                raise NotFoundError(
                    message=f"Project not found: {project_id}",
                    error_code=ErrorCode.PROJECT_NOT_FOUND
                )
    
    return handle_db_operation(
        _update,
        error_context=f"update_project(project_id={project_id}, project_name='{project_name}')"
    )


def delete_project(project_id: str, deleted_by: str = None) -> bool:
    """
    Soft delete a project and all related data.
    
    Args:
        project_id: Project ID to delete
        deleted_by: User ID who performed deletion
        
    Returns:
        True if deleted successfully
        
    Raises:
        NotFoundError: If project not found
        DatabaseError: On database operation errors
    """
    def _delete():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_delete_project', [project_id, deleted_by])
            con.commit()
            return True
    
    return handle_db_operation(
        _delete,
        error_context=f"delete_project(project_id={project_id})"
    )


def search_projects(search_term: str, limit: int = 50) -> List[Project]:
    """
    Search projects by name or description.
    
    Args:
        search_term: Search query to match against project name/description
        limit: Maximum number of results to return
        
    Returns:
        List of matching projects
        
    Raises:
        ValidationError: If search_term is empty or invalid
        DatabaseError: On database operation errors
    """
    from src.Util.error_handler import ValidationError, ErrorCode
    
    if not search_term or not search_term.strip():
        raise ValidationError(
            message="Search term cannot be empty",
            error_code=ErrorCode.MISSING_REQUIRED_FIELD,
            details={"field": "search_term"}
        )
    
    def _search():
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_search_projects', [search_term, limit])
            results = []
            for row in cur.fetchall():
                results.append(Project(
                    id=row[0],
                    project_hash=row[1],
                    project_name=row[2],
                    project_description=row[3],
                    project_created=row[4],
                    is_active=bool(row[5])
                ))

            return results
    
    return handle_db_operation(
        _search,
        error_context=f"search_projects(search_term='{search_term[:50]}...', limit={limit})"
    )


def get_project_stats(project_id: str) -> dict:
    """
    Get statistics for a project (group-based implementation).
    
    Args:
        project_id: Project ID to get statistics for
        
    Returns:
        Dictionary with project statistics:
        - total_users: Count of users with access via groups
        - active_sessions: Count of active sessions for this project
        - total_groups: Count of user groups providing access
        - group_distribution: Dict mapping group names to user counts
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get_stats():
        with get_connection() as con:
            cur = con.cursor()
            
            # Call stored procedure that returns multiple result sets
            cur.callproc('sp_get_project_statistics', [project_id])
            
            # Fetch each result set (handle None if no rows returned)
            row = cur.fetchone()
            total_users = row[0] if row else 0
            cur.nextset()
            
            row = cur.fetchone()
            active_sessions = row[0] if row else 0
            cur.nextset()
            
            row = cur.fetchone()
            total_groups = row[0] if row else 0
            cur.nextset()
            
            rows = cur.fetchall()
            group_distribution = {r[0]: r[1] for r in rows} if rows else {}

            return {
                "total_users": total_users,
                "active_sessions": active_sessions,
                "total_groups": total_groups,
                "group_distribution": group_distribution,
            }
    
    return handle_db_operation(
        _get_stats,
        error_context=f"get_project_stats(project_id={project_id})"
    )


def get_project_members_page(
    project_id: str,
    limit: int = 50,
    offset: int = 0,
    user_type: Optional[str] = None,
) -> Tuple[List[Dict[str, Any]], int]:
    """Get paginated project members through the DB layer."""
    def _get() -> Tuple[List[Dict[str, Any]], int]:
        with get_connection() as con:
            cur = con.cursor()
            cur.callproc('sp_get_project_members_paginated', [project_id, user_type, limit, offset])

            members = []
            for row in cur.fetchall():
                members.append({
                    "user_id": row[0],
                    "user_hash": row[1],
                    "username": row[2],
                    "email": row[3],
                    "user_type": row[4],
                    "is_active": bool(row[5]),
                    "created_at": row[6],
                    "granted_at": row[7],
                    "granted_by": row[8],
                })

            total_count = 0
            if cur.nextset():
                count_row = cur.fetchone()
                total_count = count_row[0] if count_row else 0

            while cur.nextset():
                pass

            return members, total_count

    return handle_db_operation(
        _get,
        error_context=(
            f"get_project_members_page(project_id={project_id}, limit={limit}, offset={offset}, user_type={user_type})"
        )
    )


# =================== PROJECT GROUP MANAGEMENT ===================

def create_default_groups(project_id: str):
    """
    Create default groups for a new project using the "Groups of Groups" architecture.

    The access model follows: User → User Group → Project Group → Project
    
    This function will:
    1. Create a default project group for this project in `project_groups`
    2. Link the project to the project group via `project_group_members`
    3. Create three default user groups (`admin`, `user`, `readonly`) in `user_groups`
    4. Link user groups to the project group via `user_group_project_groups`
       
    Args:
        project_id: Project ID to create default groups for
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _create_defaults():
        default_user_groups = [
            ("admin", "Project administrators"),
            ("user", "Regular users"),
            ("readonly", "Read-only users"),
        ]
        with get_connection() as con:
            cur = con.cursor()

            # Step 1: Create a default project group for this project.
            # Use a deterministic ID so re-runs are truly idempotent.
            project_group_id = f"pg-default-{project_id}"
            project_group_name = f"default_{project_id}"
            cur.execute(
                """
                INSERT INTO project_groups (id, group_hash, group_name, group_description, created_at, is_active)
                VALUES (%s, %s, %s, %s, NOW(), 1)
                ON DUPLICATE KEY UPDATE is_active = 1, updated_at = NOW()
                """,
                [project_group_id, f"PG-{secrets.token_hex(16).upper()}", project_group_name, f"Default project group for {project_id}"],
            )

            # Step 2: Add the project to the project group via project_group_members
            pgm_id = f"pgm-default-{project_id}"
            cur.execute(
                """
                INSERT INTO project_group_members (id, project_id, project_group_id, assigned_at, is_active)
                VALUES (%s, %s, %s, NOW(), 1)
                ON DUPLICATE KEY UPDATE is_active = 1, assigned_at = NOW()
                """,
                [pgm_id, project_id, project_group_id],
            )

            # Step 3: Create user groups and link them to the project group
            for base_name, description in default_user_groups:
                # Build a globally unique group name
                group_name = f"{base_name}_{project_id}"
                # Use deterministic IDs for idempotency
                group_id = f"ug-default-{base_name}-{project_id}"

                # Insert user group
                cur.execute(
                    """
                    INSERT INTO user_groups (id, group_hash, group_name, group_description, created_at, is_active)
                    VALUES (%s, %s, %s, %s, NOW(), 1)
                    ON DUPLICATE KEY UPDATE is_active = 1, updated_at = NOW()
                    """,
                    [group_id, f"UG-{secrets.token_hex(16).upper()}", group_name, description],
                )

                # Step 4: Link user group to project group via user_group_project_groups
                ugpg_id = f"ugpg-default-{base_name}-{project_id}"
                cur.execute(
                    """
                    INSERT INTO user_group_project_groups (id, user_group_id, project_group_id, granted_at, is_active)
                    VALUES (%s, %s, %s, NOW(), 1)
                    ON DUPLICATE KEY UPDATE is_active = 1, granted_at = NOW()
                    """,
                    [ugpg_id, group_id, project_group_id],
                )

            con.commit()
    
    return handle_db_operation(
        _create_defaults,
        error_context=f"create_default_groups(project_id={project_id})"
    )


def get_project_groups(project_id: str) -> List[UserGroup]:
    """
    Get all user groups that have access to a project.
    
    Args:
        project_id: Project ID to get groups for
        
    Returns:
        List of UserGroup objects that have access to the project
        
    Raises:
        DatabaseError: On database operation errors
    """
    def _get_groups():
        from src.Util.db.db_user_groups import get_user_groups_for_project
        return get_user_groups_for_project(project_id)
    
    return handle_db_operation(
        _get_groups,
        error_context=f"get_project_groups(project_id={project_id})"
    )
