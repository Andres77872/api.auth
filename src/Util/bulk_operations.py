"""
Bulk Operations Utility

Provides bulk operations for users, groups, permissions, and other entities
in the authentication system for efficient mass management.
"""

import logging
from typing import List, Dict, Any

from src.Util.activity_logger import log_activity, ActivityType
from src.Util.db import (
    get_user_by_hash, update_user, delete_user, get_project_by_hash
)
from src.Util.db.db_global_roles import assign_role_to_user
from src.Util.db_config import get_connection

# Configure logging
logger = logging.getLogger(__name__)

_UNSUPPORTED_FORCED_PASSWORD_FIELDS = {"force_password_reset", "must_change_on_login"}


def _unsupported_forced_password_fields(updates: Dict[str, Any]) -> List[str]:
    return [
        field
        for field in sorted(_UNSUPPORTED_FORCED_PASSWORD_FIELDS)
        if field in updates and updates.get(field) is not None
    ]


class BulkOperations:
    """
    Bulk operations for efficient mass management
    """

    @staticmethod
    def bulk_update_users(user_updates: List[Dict[str, Any]], updated_by: int = None) -> Dict[str, Any]:
        """
        Update multiple users in a single operation
        
        Args:
            user_updates: List of user update dictionaries
            updated_by: ID of user performing the operation
            
        Returns:
            Operation results with success/failure counts
        """
        results = {
            "total_requested": len(user_updates),
            "successful": 0,
            "failed": 0,
            "errors": [],
            "updated_users": [],
            "success_count": 0,
            "error_count": 0,
            "skipped_count": 0,
            "results": []
        }

        try:
            with get_connection() as con:
                con.begin()

                for update_data in user_updates:
                    try:
                        user_hash = update_data.get('user_hash')
                        if not user_hash:
                            results["errors"].append({"user": "unknown", "error": "Missing user_hash"})
                            results["failed"] += 1
                            results["error_count"] += 1
                            results["results"].append({
                                "user_hash": "unknown",
                                "success": False,
                                "error": "Missing user_hash"
                            })
                            continue

                        # Get user
                        user = get_user_by_hash(user_hash)
                        if not user:
                            results["errors"].append({"user": user_hash, "error": "User not found"})
                            results["failed"] += 1
                            results["error_count"] += 1
                            results["results"].append({
                                "user_hash": user_hash,
                                "success": False,
                                "error": "User not found"
                            })
                            continue

                        # Prepare update fields. The active route passes
                        # {"user_hash": ..., "updates": {...}}; keep support for
                        # the older flat template shape for callers that still use it.
                        requested_updates = dict(update_data.get('updates') or {})
                        requested_updates.update({
                            key: value
                            for key, value in update_data.items()
                            if key not in {'user_hash', 'updates'}
                        })

                        unsupported_force_fields = _unsupported_forced_password_fields(requested_updates)
                        if unsupported_force_fields:
                            error_message = (
                                "Unsupported forced password-change field; use reset-link password recovery "
                                "or /auth/password/change"
                            )
                            results["errors"].append({
                                "user": user_hash,
                                "error": error_message,
                                "fields": unsupported_force_fields,
                            })
                            results["failed"] += 1
                            results["error_count"] += 1
                            results["results"].append({
                                "user_hash": user_hash,
                                "success": False,
                                "error": error_message,
                            })
                            continue

                        username = requested_updates.get('username')
                        email = requested_updates.get('email')
                        password = requested_updates.get('password')
                        user_type = requested_updates.get('user_type')
                        is_active = requested_updates.get('is_active')

                        profile_update_requested = any(
                            value is not None
                            for value in (username, email, password, user_type)
                        )
                        status_update_requested = 'is_active' in requested_updates

                        if not profile_update_requested and not status_update_requested:
                            results["errors"].append({"user": user_hash, "error": "No supported update fields"})
                            results["failed"] += 1
                            results["error_count"] += 1
                            results["results"].append({
                                "user_hash": user_hash,
                                "success": False,
                                "error": "No supported update fields"
                            })
                            continue

                        updated_user = user
                        if profile_update_requested:
                            updated_user = update_user(
                                user.id,
                                username=username,
                                email=email,
                                password=password,
                                user_type=user_type
                            )

                        status_updated = True
                        if status_update_requested and is_active != getattr(user, 'is_active', None):
                            status_updated = BulkOperations._update_user_status(user.id, is_active)

                        if updated_user and status_updated:
                            if status_update_requested and is_active is False:
                                try:
                                    from src.Util.auth_lifecycle import revoke_user_auth_state

                                    revoke_user_auth_state(str(user.id), reason="bulk_user_deactivated")
                                except Exception as revoke_error:
                                    results["errors"].append({"user": user_hash, "error": f"Auth revocation failed: {revoke_error}"})
                                    results["failed"] += 1
                                    results["error_count"] += 1
                                    results["results"].append({
                                        "user_hash": user_hash,
                                        "success": False,
                                        "user_id": str(user.id),
                                        "error": "Auth revocation failed"
                                    })
                                    logger.error(f"Bulk auth revocation error for user {user_hash}: {revoke_error}")
                                    continue

                            results["successful"] += 1
                            results["success_count"] += 1
                            results["updated_users"].append({
                                "user_hash": user_hash,
                                "username": updated_user.username,
                                "changes": {k: v for k, v in requested_updates.items() if v is not None}
                            })
                            results["results"].append({
                                "user_hash": user_hash,
                                "success": True,
                                "user_id": str(user.id)
                            })

                            # Log the update
                            log_activity(
                                user_id=updated_by,
                                activity_type=ActivityType.USER_UPDATE.value,
                                details={
                                    "action": "bulk_update_user",
                                    "target_user_hash": user_hash,
                                    "changes": requested_updates
                                },
                                target_user_id=user.id
                            )
                        else:
                            results["errors"].append({"user": user_hash, "error": "Update failed"})
                            results["failed"] += 1
                            results["error_count"] += 1
                            results["results"].append({
                                "user_hash": user_hash,
                                "success": False,
                                "user_id": str(user.id),
                                "error": "Update failed"
                            })

                    except Exception as e:
                        results["errors"].append({
                            "user": update_data.get('user_hash', 'unknown'),
                            "error": str(e)
                        })
                        results["failed"] += 1
                        results["error_count"] += 1
                        results["results"].append({
                            "user_hash": update_data.get('user_hash', 'unknown'),
                            "success": False,
                            "error": str(e)
                        })
                        logger.error(f"Bulk update error for user {update_data.get('user_hash')}: {e}")

                con.commit()

        except Exception as e:
            logger.error(f"Bulk update users error: {e}")
            results["errors"].append({"operation": "bulk_update", "error": str(e)})
            results["failed"] += 1
            results["error_count"] += 1

        return results

    @staticmethod
    def bulk_delete_users(user_hashes: List[str], deleted_by: int = None) -> Dict[str, Any]:
        """
        Delete multiple users in a single operation
        
        Args:
            user_hashes: List of user hashes to delete
            deleted_by: ID of user performing the operation
            
        Returns:
            Operation results with success/failure counts
        """
        results = {
            "total_requested": len(user_hashes),
            "successful": 0,
            "failed": 0,
            "errors": [],
            "deleted_users": []
        }

        try:
            with get_connection() as con:
                con.begin()

                for user_hash in user_hashes:
                    try:
                        # Get user
                        user = get_user_by_hash(user_hash)
                        if not user:
                            results["errors"].append({"user": user_hash, "error": "User not found"})
                            results["failed"] += 1
                            continue

                        # Prevent deletion of root users in bulk
                        if user.user_type == 'root':
                            results["errors"].append({"user": user_hash, "error": "Cannot bulk delete root users"})
                            results["failed"] += 1
                            continue

                        # Delete user
                        if delete_user(user.id, deleted_by=deleted_by):
                            results["successful"] += 1
                            results["deleted_users"].append({
                                "user_hash": user_hash,
                                "username": user.username,
                                "user_type": user.user_type
                            })

                            # Log the deletion
                            log_activity(
                                user_id=deleted_by,
                                activity_type=ActivityType.USER_STATUS_CHANGE.value,
                                details={
                                    "action": "bulk_delete_user",
                                    "target_user_hash": user_hash,
                                    "username": user.username
                                },
                                target_user_id=user.id
                            )
                        else:
                            results["errors"].append({"user": user_hash, "error": "Delete failed"})
                            results["failed"] += 1

                    except Exception as e:
                        results["errors"].append({"user": user_hash, "error": str(e)})
                        results["failed"] += 1
                        logger.error(f"Bulk delete error for user {user_hash}: {e}")

                con.commit()

        except Exception as e:
            logger.error(f"Bulk delete users error: {e}")
            results["errors"].append({"operation": "bulk_delete", "error": str(e)})

        return results

    @staticmethod
    def bulk_assign_roles(project_hash: str, role_assignments: List[Dict[str, Any]], assigned_by: int = None) -> Dict[
        str, Any]:
        """
        Assign roles to multiple users in a project
        
        Args:
            project_hash: Project identifier
            role_assignments: List of {"user_hash": str, "role_id": int} assignments
            assigned_by: ID of user performing the operation
            
        Returns:
            Operation results with success/failure counts
        """
        results = {
            "total_requested": len(role_assignments),
            "successful": 0,
            "failed": 0,
            "errors": [],
            "assignments": []
        }

        try:
            # Get project
            project = get_project_by_hash(project_hash)
            if not project:
                results["errors"].append({"operation": "bulk_assign_roles", "error": "Project not found"})
                return results

            for assignment in role_assignments:
                try:
                    user_hash = assignment.get('user_hash')
                    role_id = assignment.get('role_id')

                    if not user_hash or not role_id:
                        results["errors"].append({
                            "assignment": assignment,
                            "error": "Missing user_hash or role_id"
                        })
                        results["failed"] += 1
                        continue

                    # Get user
                    user = get_user_by_hash(user_hash)
                    if not user:
                        results["errors"].append({
                            "user": user_hash,
                            "error": "User not found"
                        })
                        results["failed"] += 1
                        continue

                    # Assign role (global role system - project-agnostic)
                    assignment_result = assign_role_to_user(
                        user_id=user.id,
                        role_id=role_id
                    )

                    if assignment_result:
                        results["successful"] += 1
                        results["assignments"].append({
                            "user_hash": user_hash,
                            "username": user.username,
                            "role_id": role_id,
                            "project_hash": project_hash
                        })

                        # Log the assignment
                        log_activity(
                            user_id=assigned_by,
                            activity_type=ActivityType.PERMISSION_GRANT.value,
                            details={
                                "action": "bulk_assign_role",
                                "target_user_hash": user_hash,
                                "role_id": role_id,
                                "project_hash": project_hash
                            },
                            project_id=project.id,
                            target_user_id=user.id
                        )
                    else:
                        results["errors"].append({
                            "user": user_hash,
                            "error": "Role assignment failed"
                        })
                        results["failed"] += 1

                except Exception as e:
                    results["errors"].append({
                        "assignment": assignment,
                        "error": str(e)
                    })
                    results["failed"] += 1
                    logger.error(f"Bulk role assignment error: {e}")

        except Exception as e:
            logger.error(f"Bulk assign roles error: {e}")
            results["errors"].append({"operation": "bulk_assign_roles", "error": str(e)})

        return results

    @staticmethod
    def bulk_add_users_to_group(user_group_hash: str, user_hashes: List[str], assigned_by: int = None) -> Dict[
        str, Any]:
        """
        Add multiple users to a user group
        
        Args:
            user_group_hash: User group identifier
            user_hashes: List of user hashes to add
            assigned_by: ID of user performing the operation
            
        Returns:
            Operation results with success/failure counts
        """
        results = {
            "total_requested": len(user_hashes),
            "successful": 0,
            "failed": 0,
            "errors": [],
            "assignments": []
        }

        try:
            # Get user group
            from src.Util.db import get_user_group_by_hash, assign_user_to_user_group

            user_group = get_user_group_by_hash(user_group_hash)
            if not user_group:
                results["errors"].append({"operation": "bulk_add_to_group", "error": "User group not found"})
                return results

            for user_hash in user_hashes:
                try:
                    # Get user
                    user = get_user_by_hash(user_hash)
                    if not user:
                        results["errors"].append({"user": user_hash, "error": "User not found"})
                        results["failed"] += 1
                        continue

                    # Add to group
                    assignment_result = assign_user_to_user_group(
                        user.id,
                        user_group.id,
                        assigned_by=assigned_by
                    )

                    if assignment_result:
                        results["successful"] += 1
                        results["assignments"].append({
                            "user_hash": user_hash,
                            "username": user.username,
                            "group_name": user_group.group_name
                        })

                        # Log the assignment
                        log_activity(
                            user_id=assigned_by,
                            activity_type=ActivityType.USER_GROUP_ASSIGN.value,
                            details={
                                "action": "bulk_add_to_group",
                                "target_user_hash": user_hash,
                                "group_hash": user_group_hash,
                                "group_name": user_group.group_name
                            },
                            target_user_id=user.id
                        )
                    else:
                        results["errors"].append({"user": user_hash, "error": "Group assignment failed"})
                        results["failed"] += 1

                except Exception as e:
                    results["errors"].append({"user": user_hash, "error": str(e)})
                    results["failed"] += 1
                    logger.error(f"Bulk group assignment error for user {user_hash}: {e}")

        except Exception as e:
            logger.error(f"Bulk add to group error: {e}")
            results["errors"].append({"operation": "bulk_add_to_group", "error": str(e)})

        return results

    @staticmethod
    def _update_user_status(user_id: str, is_active: bool) -> bool:
        """Helper method to update user active status"""
        try:
            with get_connection() as con:
                cur = con.cursor()
                cur.execute("""
                            UPDATE users
                            SET is_active  = %s,
                                updated_at = NOW()
                            WHERE id = %s
                            """, [is_active, user_id])

                success = cur.rowcount > 0
                if success:
                    con.commit()
                return success

        except Exception as e:
            logger.error(f"Error updating user status: {e}")
            return False

    @staticmethod
    def get_bulk_operation_template() -> Dict[str, Any]:
        """
        Get a template for bulk operations
        
        Returns:
            Template structure for bulk operations
        """
        return {
            "bulk_update_users": {
                "description": "Update multiple users",
                "format": [
                    {
                        "user_hash": "usr-12345...",
                        "username": "new_username",
                        "email": "new_email@example.com",
                        "user_type": "consumer|admin|root",
                        "is_active": True
                    }
                ]
            },
            "bulk_delete_users": {
                "description": "Delete multiple users",
                "format": ["usr-12345...", "usr-67890..."]
            },
            "bulk_assign_roles": {
                "description": "Assign roles to multiple users in a project",
                "format": [
                    {
                        "user_hash": "usr-12345...",
                        "role_id": 1
                    }
                ]
            },
            "bulk_add_to_group": {
                "description": "Add multiple users to a user group",
                "format": ["usr-12345...", "usr-67890..."]
            }
        }


# Global instance
bulk_operations = BulkOperations()


# Convenience functions
def bulk_update_users(user_updates: List[Dict[str, Any]], updated_by: int = None) -> Dict[str, Any]:
    """Bulk update users"""
    return bulk_operations.bulk_update_users(user_updates, updated_by)


def bulk_delete_users(user_hashes: List[str], deleted_by: int = None) -> Dict[str, Any]:
    """Bulk delete users"""
    return bulk_operations.bulk_delete_users(user_hashes, deleted_by)


def bulk_assign_roles(project_hash: str, role_assignments: List[Dict[str, Any]], assigned_by: int = None) -> Dict[
    str, Any]:
    """Bulk assign roles"""
    return bulk_operations.bulk_assign_roles(project_hash, role_assignments, assigned_by)


def bulk_add_users_to_group(user_group_hash: str, user_hashes: List[str], assigned_by: int = None) -> Dict[str, Any]:
    """Bulk add users to group"""
    return bulk_operations.bulk_add_users_to_group(user_group_hash, user_hashes, assigned_by)


def get_bulk_operation_template() -> Dict[str, Any]:
    """Get bulk operation template"""
    return bulk_operations.get_bulk_operation_template()
