from fastapi import FastAPI, Security
from fastapi.middleware.cors import CORSMiddleware
from starlette.responses import RedirectResponse

from src.Util.Seccurity import x_token_user, x_token_collection
from src.middleware.error_handler import register_exception_handlers
from src.middleware.auth_context import AuthContextMiddleware
from src.middleware.api_audit import APIAuditMiddleware
from src.middleware.request_validation import RequestValidationMiddleware
from src.routes import (
    Access, auth, users, user_types_auth, projects,
    admin_user_groups, admin_project_groups, admin_dashboard, analytics, system, bulk_operations, global_roles, permission_assignments
)

# Read description from README file
with open('./src/README.md', 'r', encoding='utf-8') as f:
    description = f.read()

app = FastAPI(
    title='3-Tier User Type Multi-Project Authentication API',
    description=description,
    version='2.2.0',
    contact={
        "name": "Andrés",
        "url": "https://arizmendi.io",
        "email": "andres@arz.ai",
    }
)

# Register exception handlers for enhanced error handling
register_exception_handlers(app)

# 3-TIER USER TYPE AUTHENTICATION ROUTES
app.include_router(auth.router, tags=['Authentication'])
app.include_router(users.router, tags=['User Management'])
app.include_router(user_types_auth.router, tags=['User Type Management'])
app.include_router(projects.router, tags=['Project Management'])
app.include_router(admin_user_groups.router, tags=['Admin - User Groups'])
app.include_router(admin_project_groups.router, tags=['Admin - Project Groups'])
app.include_router(admin_dashboard.router, tags=['Admin Dashboard'])
app.include_router(analytics.router, tags=['Analytics'])
app.include_router(system.router, tags=['System Information'])
app.include_router(bulk_operations.router, tags=['Bulk Operations'])
app.include_router(global_roles.router, tags=['Global Role System'])
app.include_router(permission_assignments.router, tags=['Permission Assignments'])

# ACCESS CONTROL (Legacy compatibility)
app.include_router(
    Access.router,
    prefix='/access',
    tags=['Access Control'],
    dependencies=[Security(x_token_user), Security(x_token_collection)]
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"]
)

# Add Request Validation Middleware (validates requests, tracks time, logs activity)
app.add_middleware(RequestValidationMiddleware)

# Add API Audit Logging Middleware (logs all requests as background tasks)
app.add_middleware(APIAuditMiddleware)

# Add Auth Context Middleware (extracts user context for audit logging)
app.add_middleware(AuthContextMiddleware)


@app.get('/ping', status_code=204)
def ping():
    """Health check endpoint"""
    pass


@app.get("/", include_in_schema=False)
async def root():
    response = RedirectResponse(url='/docs')
    return response
