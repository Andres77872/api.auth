import secrets
from typing import List, Optional
from fastapi import APIRouter, Form, HTTPException, Depends
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials

from src.Util.db import (
    enhanced_login, enhanced_register, check_username_email_available,
    validate_session, create_project, get_project_by_hash, get_project_by_id,
    list_all_projects, count_projects, update_project, delete_project,
    search_projects, get_project_stats, grant_user_project_access, 
    get_user_by_credentials, get_user_projects, get_user_groups_in_project,
    get_user_permissions_in_project, get_user_project_access
)
from src.Util.Models import EnhancedUserLogin

router = APIRouter()
security = HTTPBearer()


def get_current_user(credentials: HTTPAuthorizationCredentials = Depends(security)) -> EnhancedUserLogin:
    """Dependency to get current authenticated user"""
    if not credentials or not credentials.credentials:
        raise HTTPException(status_code=401, detail="Missing authentication token")
    
    user = validate_session(credentials.credentials)
    if not user:
        raise HTTPException(status_code=401, detail="Invalid or expired token")
    
    return user


@router.post("/login")
async def login(
    username: str = Form(),
    password: str = Form(),
    project_hash: str = Form(),
):
    """
    ## Enhanced Multi-Project Login
    
    Authenticate a user for a specific project. The user must have been granted access to the project.
    
    **Features:**
    - Global user credentials across projects
    - Project-specific isolation and permissions
    - Group-based access control
    - Returns user's available projects and permissions
    
    **Response includes:**
    - Session token (JWT-like)
    - User and project information
    - User's groups and permissions in the project
    - List of all projects user has access to
    """
    user_login = enhanced_login(username, password, project_hash)
    
    if user_login:
        return {
            'success': True,
            'session_token': user_login.session_token,
            'user': {
                'user_hash': user_login.user_hash,
                'user_id': user_login.user_id,
                'user_project_id': user_login.user_project_id,
                'user_project_hash': user_login.user_project_hash
            },
            'project': {
                'project_hash': user_login.project_hash,
                'project_name': user_login.project_name,
                'project_id': user_login.project_id
            },
            'access': {
                'groups': user_login.groups,
                'permissions': user_login.permissions
            },
            'available_projects': [
                {
                    'project_hash': proj.project_hash,
                    'project_name': proj.project_name,
                    'project_description': proj.project_description
                }
                for proj in user_login.available_projects
            ]
        }
    else:
        raise HTTPException(
            status_code=401, 
            detail='Invalid credentials or user does not have access to this project'
        )


@router.post("/register")
async def register(
    username: str = Form(),
    password: str = Form(),
    project_hash: str = Form(),
    email: str = Form(None),
):
    """
    ## Enhanced Multi-Project Registration
    
    Register a new user or grant an existing user access to a project.
    
    **Behavior:**
    - If user doesn't exist globally: creates new global user + project access
    - If user exists but no project access: grants access to the project
    - If user exists with project access: returns error (user already registered)
    
    **Features:**
    - Global user identity
    - Project-specific access grants
    - Automatic assignment to default 'user' group
    - Returns same response as login
    """
    # Check if project exists
    project = get_project_by_hash(project_hash)
    if not project:
        raise HTTPException(status_code=404, detail='Project not found')
    
    user_login = enhanced_register(username, password, email, project_hash)
    
    if user_login:
        return {
            'success': True,
            'session_token': user_login.session_token,
            'user': {
                'user_hash': user_login.user_hash,
                'user_id': user_login.user_id,
                'user_project_id': user_login.user_project_id,
                'user_project_hash': user_login.user_project_hash
            },
            'project': {
                'project_hash': user_login.project_hash,
                'project_name': user_login.project_name,
                'project_id': user_login.project_id
            },
            'access': {
                'groups': user_login.groups,
                'permissions': user_login.permissions
            },
            'available_projects': [
                {
                    'project_hash': proj.project_hash,
                    'project_name': proj.project_name,
                    'project_description': proj.project_description
                }
                for proj in user_login.available_projects
            ]
        }
    else:
        raise HTTPException(
            status_code=409,
            detail='User already exists in this project or registration failed'
        )


@router.post("/check-availability", status_code=200)
async def check_username_availability(
    username_or_email: str = Form(),
):
    """
    ## Check Username/Email Availability
    
    Check if a username or email is available globally across all projects.
    
    **Returns:**
    - `available: true` if username/email is available
    - `available: false` if username/email is taken
    """
    available = check_username_email_available(username_or_email)
    return {
        'available': available,
        'username_or_email': username_or_email
    }


@router.get("/profile")
async def get_user_profile(current_user: EnhancedUserLogin = Depends(get_current_user)):
    """
    ## Get User Profile
    
    Get the current user's profile information including:
    - User details
    - Current project information
    - Groups and permissions in current project
    - All accessible projects
    """
    return {
        'user': {
            'user_hash': current_user.user_hash,
            'user_id': current_user.user_id,
            'user_project_id': current_user.user_project_id,
            'user_project_hash': current_user.user_project_hash
        },
        'current_project': {
            'project_hash': current_user.project_hash,
            'project_name': current_user.project_name,
            'project_id': current_user.project_id
        },
        'access': {
            'groups': current_user.groups,
            'permissions': current_user.permissions
        },
        'available_projects': [
            {
                'project_hash': proj.project_hash,
                'project_name': proj.project_name,
                'project_description': proj.project_description
            }
            for proj in current_user.available_projects
        ]
    }


@router.post("/switch-project")
async def switch_project(
    project_hash: str = Form(),
    current_user: EnhancedUserLogin = Depends(get_current_user)
):
    """
    ## Switch to Different Project
    
    Switch the user's session to a different project they have access to.
    Returns a new session token for the target project.
    """
    # Check if user has access to the target project
    target_project = None
    for proj in current_user.available_projects:
        if proj.project_hash == project_hash:
            target_project = proj
            break
    
    if not target_project:
        raise HTTPException(
            status_code=403,
            detail='User does not have access to the specified project'
        )
    
    # Get user by their global credentials (we need to re-authenticate)
    # For security, we'll create a new login session
    user_login = validate_session(current_user.session_token)
    if not user_login:
        raise HTTPException(status_code=401, detail='Invalid session')
    
    # Generate new session for the target project
    from src.Util.db import get_user_project_access, get_user_groups_in_project, get_user_permissions_in_project
    import json
    from src.Util.db import client
    
    user_project = get_user_project_access(current_user.user_id, target_project.id)
    if not user_project:
        raise HTTPException(status_code=403, detail='Access denied to target project')
    
    # Create new session
    session_token = secrets.token_hex(32).upper()
    session_length = 60 * 60 * 24 * 3  # 3 days
    
    # Get fresh groups and permissions for target project
    groups = get_user_groups_in_project(user_project.id)
    permissions = get_user_permissions_in_project(user_project.id)
    
    # Store new session in Redis
    session_data = {
        'user_id': current_user.user_id,
        'user_hash': current_user.user_hash,
        'project_id': target_project.id,
        'project_hash': target_project.project_hash,
        'user_project_id': user_project.id,
        'user_project_hash': user_project.user_project_hash,
        'groups': [g.group_name for g in groups],
        'permissions': permissions
    }
    
    client.set(f"session:{session_token}", json.dumps(session_data), ex=session_length)
    
    return {
        'success': True,
        'session_token': session_token,
        'project': {
            'project_hash': target_project.project_hash,
            'project_name': target_project.project_name,
            'project_id': target_project.id
        },
        'access': {
            'groups': [g.group_name for g in groups],
            'permissions': permissions
        }
    }


@router.post("/create-project")
async def create_new_project(
    project_name: str = Form(),
    project_description: str = Form(None),
    current_user: EnhancedUserLogin = Depends(get_current_user)
):
    """
    ## Create New Project
    
    Create a new project and automatically grant the current user admin access.
    Only users with 'admin' permission in their current project can create new projects.
    """
    # Check if user has admin permissions
    if 'admin' not in current_user.permissions:
        raise HTTPException(
            status_code=403,
            detail='Insufficient permissions. Admin access required to create projects.'
        )
    
    # Create the new project
    new_project = create_project(project_name, project_description)
    
    # Grant the current user admin access to the new project
    user_project = grant_user_project_access(
        current_user.user_id, 
        new_project.id, 
        granted_by=current_user.user_id
    )
    
    # Assign user to admin group in the new project
    from src.Util.db import get_connection
    with get_connection() as con:
        cur = con.cursor()
        # Get admin group ID for the new project
        cur.execute("""
            SELECT id FROM user_groups 
            WHERE project_id = %s AND group_name = 'admin' AND is_active = 1
        """, [new_project.id])
        
        admin_group = cur.fetchone()
        if admin_group:
            # Remove from default 'user' group
            cur.execute("""
                UPDATE user_project_groups 
                SET is_active = 0 
                WHERE user_project_id = %s
            """, [user_project.id])
            
            # Add to admin group
            cur.execute("""
                INSERT INTO user_project_groups (user_project_id, group_id, assigned_at, assigned_by)
                VALUES (%s, %s, NOW(), %s)
            """, [user_project.id, admin_group[0], current_user.user_id])
            
            con.commit()
    
    return {
        'success': True,
        'project': {
            'project_hash': new_project.project_hash,
            'project_name': new_project.project_name,
            'project_description': new_project.project_description,
            'project_id': new_project.id
        },
        'user_project': {
            'user_project_id': user_project.id,
            'user_project_hash': user_project.user_project_hash,
            'role': 'admin'
        }
    }


@router.post("/grant-access")
async def grant_user_access(
    username: str = Form(),
    target_project_hash: str = Form(),
    current_user: EnhancedUserLogin = Depends(get_current_user)
):
    """
    ## Grant User Access to Project
    
    Grant an existing global user access to a project.
    Only users with 'admin' or 'manage_users' permission can grant access.
    """
    # Check permissions
    if not any(perm in current_user.permissions for perm in ['admin', 'manage_users']):
        raise HTTPException(
            status_code=403,
            detail='Insufficient permissions. Admin or manage_users permission required.'
        )
    
    # Get the target project
    target_project = get_project_by_hash(target_project_hash)
    if not target_project:
        raise HTTPException(status_code=404, detail='Target project not found')
    
    # Find the global user
    from src.Util.db import get_connection
    with get_connection() as con:
        cur = con.cursor()
        cur.execute("""
            SELECT id FROM users 
            WHERE username = %s AND is_active = 1
        """, [username])
        
        user_result = cur.fetchone()
        if not user_result:
            raise HTTPException(status_code=404, detail='User not found')
        
        target_user_id = user_result[0]
    
    # Check if user already has access
    from src.Util.db import get_user_project_access
    existing_access = get_user_project_access(target_user_id, target_project.id)
    if existing_access:
        raise HTTPException(
            status_code=409,
            detail='User already has access to this project'
        )
    
    # Grant access
    user_project = grant_user_project_access(
        target_user_id,
        target_project.id,
        granted_by=current_user.user_id
    )
    
    return {
        'success': True,
        'message': f'Access granted to user {username} for project {target_project.project_name}',
        'user_project': {
            'user_project_id': user_project.id,
            'user_project_hash': user_project.user_project_hash,
            'granted_by': current_user.user_id
        }
    }


@router.get("/validate")
async def validate_token(current_user: EnhancedUserLogin = Depends(get_current_user)):
    """
    ## Validate Session Token
    
    Validate the current session token and return user information.
    This endpoint can be used for token verification by other services.
    """
    return {
        'valid': True,
        'user': {
            'user_hash': current_user.user_hash,
            'user_id': current_user.user_id,
            'user_project_id': current_user.user_project_id
        },
        'project': {
            'project_hash': current_user.project_hash,
            'project_name': current_user.project_name,
            'project_id': current_user.project_id
        },
        'permissions': current_user.permissions,
        'groups': current_user.groups
    }


# PROJECT CRUD ENDPOINTS

@router.get("/projects")
async def list_projects(
    limit: int = 100,
    offset: int = 0,
    search: str = None,
    current_user: EnhancedUserLogin = Depends(get_current_user)
):
    """
    ## List All Projects
    
    Get a paginated list of all projects. Supports search functionality.
    Only users with 'admin' permission can list all projects.
    """
    # Check permissions
    if 'admin' not in current_user.permissions:
        raise HTTPException(
            status_code=403,
            detail='Insufficient permissions. Admin access required to list all projects.'
        )
    
    if search:
        projects = search_projects(search, limit)
        total_count = len(projects)  # For search, we don't do separate count
    else:
        projects = list_all_projects(limit, offset)
        total_count = count_projects()
    
    return {
        'projects': [
            {
                'project_id': proj.id,
                'project_hash': proj.project_hash,
                'project_name': proj.project_name,
                'project_description': proj.project_description,
                'project_created': proj.project_created.isoformat() if proj.project_created else None,
                'is_active': proj.is_active
            }
            for proj in projects
        ],
        'pagination': {
            'limit': limit,
            'offset': offset,
            'total_count': total_count,
            'has_more': (offset + len(projects)) < total_count if not search else False
        }
    }


@router.get("/projects/{project_hash}")
async def get_project_details(
    project_hash: str,
    current_user: EnhancedUserLogin = Depends(get_current_user)
):
    """
    ## Get Project Details
    
    Get detailed information about a specific project by its hash.
    Users can only view projects they have access to, unless they have admin permissions.
    """
    project = get_project_by_hash(project_hash)
    if not project:
        raise HTTPException(status_code=404, detail='Project not found')
    
    # Check if user has access to this project or admin permissions
    has_access = False
    if 'admin' in current_user.permissions:
        has_access = True
    else:
        # Check if user has access to this specific project
        for user_project in current_user.available_projects:
            if user_project.project_hash == project_hash:
                has_access = True
                break
    
    if not has_access:
        raise HTTPException(
            status_code=403,
            detail='Access denied. You do not have permission to view this project.'
        )
    
    # Get project statistics if user has admin access to the project
    stats = None
    try:
        # Check if user has admin access to THIS specific project
        if project_hash == current_user.project_hash and 'admin' in current_user.permissions:
            stats = get_project_stats(project.id)
        elif 'admin' in current_user.permissions:  # Global admin
            stats = get_project_stats(project.id)
    except Exception as e:
        # Stats are optional, continue without them
        pass
    
    response = {
        'project_id': project.id,
        'project_hash': project.project_hash,
        'project_name': project.project_name,
        'project_description': project.project_description,
        'project_created': project.project_created.isoformat() if project.project_created else None,
        'is_active': project.is_active
    }
    
    if stats:
        response['statistics'] = stats
    
    return response


@router.put("/projects/{project_hash}")
async def update_project_details(
    project_hash: str,
    project_name: str = Form(None),
    project_description: str = Form(None),
    current_user: EnhancedUserLogin = Depends(get_current_user)
):
    """
    ## Update Project Details
    
    Update project name and/or description.
    Only users with 'admin' permission in the specific project can update it.
    """
    project = get_project_by_hash(project_hash)
    if not project:
        raise HTTPException(status_code=404, detail='Project not found')
    
    # Check if user has admin access to this specific project
    has_admin_access = False
    if project_hash == current_user.project_hash and 'admin' in current_user.permissions:
        has_admin_access = True
    elif 'admin' in current_user.permissions:  # Global admin check
        # Verify if this user has admin access to the target project
        from src.Util.db import get_user_project_access, get_user_permissions_in_project
        user_project = get_user_project_access(current_user.user_id, project.id)
        if user_project:
            permissions = get_user_permissions_in_project(user_project.id)
            if 'admin' in permissions:
                has_admin_access = True
    
    if not has_admin_access:
        raise HTTPException(
            status_code=403,
            detail='Insufficient permissions. Admin access to this project required.'
        )
    
    if not project_name and project_description is None:
        raise HTTPException(
            status_code=400,
            detail='At least one field (project_name or project_description) must be provided'
        )
    
    updated_project = update_project(
        project.id, 
        project_name, 
        project_description, 
        updated_by=current_user.user_id
    )
    
    if updated_project:
        return {
            'success': True,
            'project': {
                'project_id': updated_project.id,
                'project_hash': updated_project.project_hash,
                'project_name': updated_project.project_name,
                'project_description': updated_project.project_description,
                'project_created': updated_project.project_created.isoformat() if updated_project.project_created else None,
                'is_active': updated_project.is_active
            }
        }
    else:
        raise HTTPException(status_code=500, detail='Failed to update project')


@router.delete("/projects/{project_hash}")
async def delete_project_endpoint(
    project_hash: str,
    current_user: EnhancedUserLogin = Depends(get_current_user)
):
    """
    ## Delete Project
    
    Soft delete a project and all related data (user access, groups, sessions).
    Only users with 'admin' permission in the specific project can delete it.
    
    **Warning:** This action cannot be undone and will revoke access for all users.
    """
    project = get_project_by_hash(project_hash)
    if not project:
        raise HTTPException(status_code=404, detail='Project not found')
    
    # Check if user has admin access to this specific project
    has_admin_access = False
    if project_hash == current_user.project_hash and 'admin' in current_user.permissions:
        has_admin_access = True
    elif 'admin' in current_user.permissions:  # Global admin check
        # Verify if this user has admin access to the target project
        from src.Util.db import get_user_project_access, get_user_permissions_in_project
        user_project = get_user_project_access(current_user.user_id, project.id)
        if user_project:
            permissions = get_user_permissions_in_project(user_project.id)
            if 'admin' in permissions:
                has_admin_access = True
    
    if not has_admin_access:
        raise HTTPException(
            status_code=403,
            detail='Insufficient permissions. Admin access to this project required.'
        )
    
    success = delete_project(project.id, deleted_by=current_user.user_id)
    
    if success:
        return {
            'success': True,
            'message': f'Project "{project.project_name}" has been deleted successfully',
            'deleted_project': {
                'project_hash': project.project_hash,
                'project_name': project.project_name
            }
        }
    else:
        raise HTTPException(status_code=500, detail='Failed to delete project')


@router.get("/projects/{project_hash}/stats")
async def get_project_statistics(
    project_hash: str,
    current_user: EnhancedUserLogin = Depends(get_current_user)
):
    """
    ## Get Project Statistics
    
    Get detailed statistics for a project including user counts, active sessions, and group distribution.
    Only users with 'admin' permission in the specific project can view statistics.
    """
    project = get_project_by_hash(project_hash)
    if not project:
        raise HTTPException(status_code=404, detail='Project not found')
    
    # Check if user has admin access to this specific project
    has_admin_access = False
    if project_hash == current_user.project_hash and 'admin' in current_user.permissions:
        has_admin_access = True
    elif 'admin' in current_user.permissions:  # Global admin check
        # Verify if this user has admin access to the target project
        from src.Util.db import get_user_project_access, get_user_permissions_in_project
        user_project = get_user_project_access(current_user.user_id, project.id)
        if user_project:
            permissions = get_user_permissions_in_project(user_project.id)
            if 'admin' in permissions:
                has_admin_access = True
    
    if not has_admin_access:
        raise HTTPException(
            status_code=403,
            detail='Insufficient permissions. Admin access to this project required.'
        )
    
    stats = get_project_stats(project.id)
    
    return {
        'project': {
            'project_hash': project.project_hash,
            'project_name': project.project_name
        },
        'statistics': stats
    } 