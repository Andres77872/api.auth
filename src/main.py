from fastapi import FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, PlainTextResponse
from starlette.responses import RedirectResponse
from pathlib import Path
from typing import Optional
from enum import Enum
import os

from src.middleware.error_handler import register_exception_handlers
from src.middleware.auth_context import AuthContextMiddleware
from src.middleware.api_audit import APIAuditMiddleware
from src.middleware.request_validation import RequestValidationMiddleware
from src.routes import (
    auth, users, user_types_auth, projects,
    admin_user_groups, admin_project_groups, admin_dashboard, system, bulk_operations, global_roles, permission_assignments,
    audit_logs, api_keys, user_api_keys,
)
from src.Util.documentation_renderer import DocumentationRenderer, get_documentation_files

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
# NOTE: user_api_keys must be registered BEFORE users to avoid /users/{user_hash}
# catching /users/api-keys as a user_hash parameter
app.include_router(user_api_keys.router, tags=["API Keys - User"])
app.include_router(users.router, tags=['User Management'])
app.include_router(user_types_auth.router, tags=['User Type Management'])
app.include_router(projects.router, tags=['Project Management'])
app.include_router(admin_user_groups.router, tags=['Admin - User Groups'])
app.include_router(admin_project_groups.router, tags=['Admin - Project Groups'])
app.include_router(admin_dashboard.router, tags=['Admin Dashboard'])
app.include_router(system.router, tags=['System Information'])
app.include_router(bulk_operations.router, tags=['Bulk Operations'])
app.include_router(global_roles.router, tags=['Global Role System'])
app.include_router(permission_assignments.router, tags=['Permission Assignments'])
app.include_router(audit_logs.router, tags=['Audit Logs'])
app.include_router(api_keys.router, tags=["API Keys - Admin"])

# CORS configuration — explicit browser clients only.
_allowed_origins = os.environ.get(
    "ALLOWED_ORIGINS",
    "http://localhost:3000,http://localhost:5173,http://localhost:4173,https://auth-ui.arz.ai",
)
ALLOWED_ORIGINS = [o.strip() for o in _allowed_origins.split(",") if o.strip()]

app.add_middleware(
    CORSMiddleware,
    allow_origins=ALLOWED_ORIGINS,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Add Request Validation Middleware (validates requests, tracks time, logs activity)
app.add_middleware(RequestValidationMiddleware)

# Add API Audit Logging Middleware (logs all requests as background tasks)
app.add_middleware(APIAuditMiddleware)

# Add Auth Context Middleware (extracts user context for audit logging)
app.add_middleware(AuthContextMiddleware)


# Documentation base path
DOCS_BASE_PATH = Path(__file__).parent.parent / "docs"
DOCS_BASE_URL = "/documentation"


class DocFormat(str, Enum):
    """Documentation output format"""
    html = "html"
    raw = "raw"
    md = "md"
    markdown = "markdown"


@app.get("/documentation", response_class=HTMLResponse, tags=["Documentation"])
async def documentation_index(
    format: Optional[DocFormat] = Query(None, description="Output format: html (default), raw/md/markdown for raw markdown")
):
    """
    Documentation home page.
    
    - **format**: Output format
        - `html` (default): Rendered HTML with styling
        - `raw`, `md`, `markdown`: Raw markdown content (for LLM/API consumption)
    """
    usage_files = get_documentation_files(DOCS_BASE_PATH, "USAGE")
    
    # Return raw list for LLM consumption
    if format in [DocFormat.raw, DocFormat.md, DocFormat.markdown]:
        file_list = "# API Documentation\n\n## Available Guides\n\n"
        for f in usage_files:
            file_list += f"- [{f.title}]({DOCS_BASE_URL}/USAGE/{f.name})\n"
        file_list += "\n## API Documentation\n\n"
        file_list += "- [OpenAPI/Swagger](/docs)\n"
        file_list += "- [ReDoc](/redoc)\n"
        return PlainTextResponse(file_list, media_type="text/markdown; charset=utf-8")
    
    return HTMLResponse(DocumentationRenderer.render_home(usage_files, DOCS_BASE_URL))


@app.get("/documentation/{path:path}", tags=["Documentation"])
async def serve_documentation(
    path: str,
    format: Optional[DocFormat] = Query(None, description="Output format: html (default), raw/md/markdown for raw markdown"),
    raw: bool = Query(False, description="Deprecated: Use format=raw instead")
):
    """
    Serve documentation markdown files.
    
    - **path**: Path to the markdown file (e.g., USAGE/authentication-usage-cases.md)
    - **format**: Output format
        - `html` (default): Rendered HTML with modern dark theme styling
        - `raw`, `md`, `markdown`: Raw markdown content (for LLM/API consumption)
    - **raw**: Deprecated - use `format=raw` instead
    
    **LLM Usage**: Add `?format=raw` to get plain markdown text suitable for AI/LLM processing.
    
    **Examples**:
    - `/documentation/USAGE/authentication-usage-cases.md` - Rendered HTML
    - `/documentation/USAGE/authentication-usage-cases.md?format=raw` - Raw markdown for LLMs
    """
    # Normalize path
    file_path = DOCS_BASE_PATH / path
    
    # Security check - ensure we're still within docs directory
    try:
        file_path = file_path.resolve()
        if not str(file_path).startswith(str(DOCS_BASE_PATH.resolve())):
            raise HTTPException(status_code=403, detail="Access denied")
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid path")
    
    # Check if file exists
    if not file_path.exists():
        raise HTTPException(status_code=404, detail=f"Documentation not found: {path}")
    
    # Determine if raw output is requested
    is_raw = raw or format in [DocFormat.raw, DocFormat.md, DocFormat.markdown]
    
    # If it's a directory, list contents
    if file_path.is_dir():
        files = get_documentation_files(DOCS_BASE_PATH, path)
        
        if is_raw:
            # Raw format for LLM consumption
            content = f"# {path}\n\n## Files\n\n"
            for f in files:
                content += f"- [{f.title}]({DOCS_BASE_URL}/{f.path})\n"
            return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")
        
        return HTMLResponse(DocumentationRenderer.render_index(path, files, DOCS_BASE_URL))
    
    # Read file content
    try:
        content = file_path.read_text(encoding='utf-8')
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error reading file: {str(e)}")
    
    # Return raw markdown for LLM consumption
    if is_raw or not path.endswith('.md'):
        return PlainTextResponse(content, media_type="text/markdown; charset=utf-8")
    
    # Render as HTML
    title = path.replace(".md", "").replace("-", " ").replace("/", " - ").title()
    return HTMLResponse(DocumentationRenderer.render_page(content, title, path, DOCS_BASE_URL))


@app.get("/docs/USAGE/{filename:path}", include_in_schema=False)
async def serve_usage_docs_legacy(
    filename: str,
    format: Optional[DocFormat] = Query(None),
    raw: bool = Query(False)
):
    """
    Legacy route for /docs/USAGE/* - serves documentation from /documentation/USAGE/*
    """
    return await serve_documentation(f"USAGE/{filename}", format=format, raw=raw)


@app.get('/ping', status_code=204)
def ping():
    """Health check endpoint"""
    pass


@app.get("/", include_in_schema=False)
async def root():
    response = RedirectResponse(url='/docs')
    return response
