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
from typing import List, Optional

from src.Util.Models import Project, LegacyUserGroup as UserGroup
from src.Util.db_config import get_connection


# =================== PROJECT MANAGEMENT ===================

def create_project(project_name: str, project_description: str = None, created_by: str = None) -> Project:
    """Create a new project/application with RBAC initialization"""
    project_hash = secrets.token_hex(32).upper()

    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    INSERT INTO projects (project_hash, project_name, project_description, project_created, created_by)
                    VALUES (%s, %s, %s, NOW(), %s)
                    """, [project_hash, project_name, project_description, created_by])

        project_id = con.insert_id()
        con.commit()

        # Create default user group for this project (legacy)
        create_default_groups(project_id)

        # NEW: Initialize RBAC for this project
        try:
            from src.Util.db.db_rbac_permissions import initialize_project_rbac
            rbac_result = initialize_project_rbac(project_id, created_by)
            print(f"RBAC initialized for project {project_name}: {rbac_result}")
        except Exception as e:
            print(f"Warning: Could not initialize RBAC for project {project_name}: {e}")

        return Project(
            id=project_id,
            project_hash=project_hash,
            project_name=project_name,
            project_description=project_description,
            project_created=datetime.now(),
            is_active=True
        )


def get_project_by_hash(project_hash: str) -> Optional[Project]:
    """Get project by project hash"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id, project_hash, project_name, project_description, project_created, is_active
                    FROM projects
                    WHERE project_hash = %s
                      AND is_active = 1
                    """, [project_hash])

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


def get_project_by_id(project_id: str) -> Optional[Project]:
    """Get project by project ID"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id, project_hash, project_name, project_description, project_created, is_active
                    FROM projects
                    WHERE id = %s
                      AND is_active = 1
                    """, [project_id])

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


def list_all_projects(limit: int = 100, offset: int = 0) -> List[Project]:
    """List all active projects with pagination"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id, project_hash, project_name, project_description, project_created, is_active
                    FROM projects
                    WHERE is_active = 1
                    ORDER BY project_created DESC
                        LIMIT %s
                    OFFSET %s
                    """, [limit, offset])

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


def count_projects() -> int:
    """Count total number of active projects"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("SELECT COUNT(*) FROM projects WHERE is_active = 1")
        return cur.fetchone()[0]


def update_project(project_id: str, project_name: str = None, project_description: str = None,
                   updated_by: str = None) -> Optional[Project]:
    """Update project information"""
    if not project_name and project_description is None:
        return None

    with get_connection() as con:
        cur = con.cursor()

        # Build dynamic update query
        update_fields = []
        update_values = []

        if project_name:
            update_fields.append("project_name = %s")
            update_values.append(project_name)

        if project_description is not None:
            update_fields.append("project_description = %s")
            update_values.append(project_description)

        update_fields.append("updated_at = NOW()")
        update_values.append(project_id)

        query = f"""
            UPDATE projects 
            SET {', '.join(update_fields)}
            WHERE id = %s AND is_active = 1
        """

        cur.execute(query, update_values)

        if cur.rowcount > 0:
            con.commit()
            return get_project_by_id(project_id)
        else:
            return None


def delete_project(project_id: str, deleted_by: str = None) -> bool:
    """Soft delete a project and all related data"""
    with get_connection() as con:
        cur = con.cursor()

        try:
            # Start transaction
            con.begin()

            # Soft delete the project
            cur.execute("""
                        UPDATE projects
                        SET is_active  = 0,
                            updated_at = NOW()
                        WHERE id = %s
                          AND is_active = 1
                        """, [project_id])

            if cur.rowcount == 0:
                con.rollback()
                return False

            # Soft delete all user-project relationships
            cur.execute("""
                        UPDATE user_projects
                        SET is_active  = 0,
                            revoked_at = NOW(),
                            revoked_by = %s
                        WHERE project_id = %s
                          AND is_active = 1
                        """, [deleted_by, project_id])

            # Soft delete all project groups
            cur.execute("""
                        UPDATE user_groups
                        SET is_active  = 0,
                            updated_at = NOW()
                        WHERE project_id = %s
                          AND is_active = 1
                        """, [project_id])

            # Soft delete all user-project-group relationships for this project
            cur.execute("""
                        UPDATE user_project_groups upg
                            INNER JOIN user_projects up
                        ON upg.user_project_id = up.id
                            SET upg.is_active = 0, upg.removed_at = NOW(), upg.removed_by = %s
                        WHERE up.project_id = %s AND upg.is_active = 1
                        """, [deleted_by, project_id])

            # Soft delete all sessions for this project
            cur.execute("""
                        UPDATE user_sessions us
                            INNER JOIN user_projects up
                        ON us.user_project_id = up.id
                            SET us.is_active = 0
                        WHERE up.project_id = %s AND us.is_active = 1
                        """, [project_id])

            con.commit()
            return True

        except Exception as e:
            con.rollback()
            print(f"Error deleting project: {e}")
            return False


def search_projects(search_term: str, limit: int = 50) -> List[Project]:
    """Search projects by name or description"""
    with get_connection() as con:
        cur = con.cursor()
        search_pattern = f"%{search_term}%"

        cur.execute("""
                    SELECT id, project_hash, project_name, project_description, project_created, is_active
                    FROM projects
                    WHERE is_active = 1
                      AND (project_name LIKE %s OR project_description LIKE %s)
                    ORDER BY project_name ASC
                        LIMIT %s
                    """, [search_pattern, search_pattern, limit])

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


def get_project_stats(project_id: str) -> dict:
    """Get statistics for a project (group-based implementation)"""
    with get_connection() as con:
        cur = con.cursor()

        # ------------------------------------------------------------------
        # 1. Total distinct users that currently have access via groups
        # ------------------------------------------------------------------
        cur.execute(
            """
            SELECT COUNT(DISTINCT ugm.user_id)
            FROM user_group_members ugm
                     JOIN user_group_projects ugp
                          ON ugm.user_group_id = ugp.user_group_id
                         AND ugp.is_active = 1
            WHERE ugp.project_id = %s
              AND ugm.is_active = 1
            """,
            [project_id],
        )
        total_users = cur.fetchone()[0]

        # ------------------------------------------------------------------
        # 2. Active sessions for this project (uses simplified user_sessions)
        # ------------------------------------------------------------------
        cur.execute(
            """
            SELECT COUNT(*)
            FROM user_sessions
            WHERE project_id = %s
              AND is_active = 1
              AND expires_at > NOW()
            """,
            [project_id],
        )
        active_sessions = cur.fetchone()[0]

        # ------------------------------------------------------------------
        # 3. Total groups that currently grant access to this project
        # ------------------------------------------------------------------
        cur.execute(
            """
            SELECT COUNT(DISTINCT ugp.user_group_id)
            FROM user_group_projects ugp
            WHERE ugp.project_id = %s
              AND ugp.is_active = 1
            """,
            [project_id],
        )
        total_groups = cur.fetchone()[0]

        # ------------------------------------------------------------------
        # 4. Distribution of users per group
        # ------------------------------------------------------------------
        cur.execute(
            """
            SELECT ug.group_name, COUNT(DISTINCT ugm.user_id) AS user_count
            FROM user_groups ug
                     JOIN user_group_projects ugp
                          ON ug.id = ugp.user_group_id
                         AND ugp.is_active = 1
                     LEFT JOIN user_group_members ugm
                               ON ugm.user_group_id = ug.id
                              AND ugm.is_active = 1
            WHERE ugp.project_id = %s
              AND ug.is_active = 1
            GROUP BY ug.id, ug.group_name
            ORDER BY user_count DESC
            """,
            [project_id],
        )
        group_distribution = {row[0]: row[1] for row in cur.fetchall()}

        return {
            "total_users": total_users,
            "active_sessions": active_sessions,
            "total_groups": total_groups,
            "group_distribution": group_distribution,
        }


# =================== PROJECT GROUP MANAGEMENT ===================

def create_default_groups(project_id: str):
    """Create default groups for a new project using the *global* `user_groups` table.

    In the re-designed schema `user_groups` is no longer tied to a single project – the
    relation between a group and a project is expressed through the `user_group_projects`
    link table.  The legacy implementation inserted the groups with a `project_id` column
    that no longer exists which caused the "Unknown column 'project_id'" MySQL error.

    This refactor will:
    1. Insert (or re-activate) the three default groups (`admin`, `user`, `readonly`) in
       `user_groups`.  We make the names project-specific by prefixing them with the
       project id to avoid global name clashes while still keeping them human readable.
    2. Record the relationship between each created group and the new project in
       `user_group_projects` (ON DUPLICATE KEY to handle re-runs).
    """

    import secrets

    default_groups = [
        ("admin", "Project administrators", '["admin", "read", "write", "delete", "manage_users"]'),
        ("user", "Regular users", '["read", "write"]'),
        ("readonly", "Read-only users", '["read"]'),
    ]

    with get_connection() as con:
        cur = con.cursor()

        created_group_ids = []

        for base_name, description, permissions in default_groups:
            # Build a **globally unique** group name while retaining readability
            group_name = f"{base_name}_{project_id}"

            # Try to insert. If the name already exists we update `is_active` and fetch the id.
            cur.execute(
                """
                INSERT INTO user_groups (group_hash, group_name, group_description, created_at, is_active)
                VALUES (%s, %s, %s, NOW(), 1)
                ON DUPLICATE KEY UPDATE is_active = 1, updated_at = NOW()
                """,
                [f"UG-{secrets.token_hex(16).upper()}", group_name, description],
            )

            # `lastrowid` is only reliable when a new row was inserted.  When the row already
            # exists we need to fetch its id.
            group_id = cur.lastrowid
            if not group_id:
                cur.execute("SELECT id FROM user_groups WHERE group_name = %s", [group_name])
                group_id = cur.fetchone()[0]

            created_group_ids.append(group_id)

        # Link the (new or existing) groups with the project in user_group_projects
        for gid in created_group_ids:
            cur.execute(
                """
                INSERT INTO user_group_projects (user_group_id, project_id, granted_at, is_active)
                VALUES (%s, %s, NOW(), 1)
                ON DUPLICATE KEY UPDATE is_active = 1, granted_at = NOW()
                """,
                [gid, project_id],
            )

        con.commit()


def get_project_groups(project_id: str) -> List[UserGroup]:
    """Get all groups for a project"""
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
                    SELECT id, project_id, group_name, group_description, permissions, created_at, is_active
                    FROM user_groups
                    WHERE project_id = %s
                      AND is_active = 1
                    ORDER BY group_name ASC
                    """, [project_id])

        groups = []
        for row in cur.fetchall():
            groups.append(UserGroup(
                id=row[0],
                project_id=row[1],
                group_name=row[2],
                group_description=row[3],
                permissions=row[4],
                created_at=row[5],
                is_active=bool(row[6])
            ))

        return groups
