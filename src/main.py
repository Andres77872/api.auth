from fastapi import FastAPI, Query, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse, Response
from starlette.responses import RedirectResponse
from contextlib import asynccontextmanager, suppress
from pathlib import Path
from typing import Optional
from enum import Enum
import asyncio
import gzip
import os

from src.middleware.error_handler import register_exception_handlers
from src.middleware.auth_context import AuthContextMiddleware
from src.middleware.api_audit import APIAuditMiddleware
from src.middleware.request_validation import RequestValidationMiddleware
from src.routes import (
    auth, auth_google, auth_oauth, auth_patreon, email_webhooks, patreon_webhooks,
    stripe_webhooks, internal_patreon, internal_billing, internal_email, users, user_types_auth, projects,
    admin_user_groups, admin_project_groups, admin_dashboard, admin_patreon, system, bulk_operations, global_roles, permission_assignments,
    audit_logs, api_keys, user_api_keys, email_templates, admin_billing, admin_oauth, assistant,
)
from src.Util.api_key_expiry import run_api_key_expiry_sweeper
from src.assistant.readiness import warn_if_websocket_transport_missing
from src.Util.auth_constants import DEFAULT_ALLOWED_ORIGINS
from src.Util import docs_site
from src.Util.oauth.registry import register_default_adapters
from src.Util.openapi_metadata import OPENAPI_TAGS, SWAGGER_UI_PARAMETERS, install_openapi_metadata

# The OpenAPI description is src/README.md, resolved relative to this file so
# the app does not depend on the working directory it is started from.
description = (Path(__file__).parent / "README.md").read_text(encoding="utf-8")

@asynccontextmanager
async def lifespan(application: FastAPI):
    application.state.assistant_websocket_ready = warn_if_websocket_transport_missing()
    # Keeps `is_active` of expired API keys in step with `expires_at` (see api_key_expiry).
    api_key_expiry_sweeper = asyncio.create_task(run_api_key_expiry_sweeper())
    yield
    api_key_expiry_sweeper.cancel()
    with suppress(asyncio.CancelledError):
        await api_key_expiry_sweeper
    await assistant.shutdown_assistant(application)


app = FastAPI(
    lifespan=lifespan,
    title='Group-Based Multi-Project Authentication API',
    summary='Authentication, authorization, OAuth sign-in, API keys, transactional email, '
            'and billing/entitlement facts for multi-project products.',
    description=description,
    version='2.2.0',
    contact={
        "name": "Andrés",
        "url": "https://arizmendi.io",
        "email": "andres@arz.ai",
    },
    openapi_tags=OPENAPI_TAGS,
    swagger_ui_parameters=SWAGGER_UI_PARAMETERS,
)
install_openapi_metadata(app)

# Register exception handlers for enhanced error handling
register_exception_handlers(app)

# OAuth provider adapters are registered explicitly at start-up (no import-time side effects).
register_default_adapters()

# ROUTES
# Each router declares its own OpenAPI tag; tag descriptions and ordering live in
# src/Util/openapi_metadata.py.
app.include_router(auth.router)
app.include_router(auth_oauth.router)
app.include_router(auth_google.router)
app.include_router(auth_patreon.router)
app.include_router(email_webhooks.router)
app.include_router(patreon_webhooks.router)
app.include_router(stripe_webhooks.router)
# NOTE: user_api_keys must be registered BEFORE users to avoid /users/{user_hash}
# catching /users/api-keys as a user_hash parameter
app.include_router(user_api_keys.router)
app.include_router(users.router)
app.include_router(user_types_auth.router)
app.include_router(projects.router)
app.include_router(admin_user_groups.router)
app.include_router(admin_project_groups.router)
app.include_router(admin_dashboard.router)
app.include_router(admin_patreon.router)
app.include_router(admin_billing.router)
app.include_router(admin_oauth.router)
app.include_router(email_templates.router)
app.include_router(system.router)
app.include_router(internal_patreon.router)
app.include_router(internal_billing.router)
app.include_router(internal_email.router)
app.include_router(bulk_operations.router)
app.include_router(global_roles.router)
app.include_router(permission_assignments.router)
app.include_router(audit_logs.router)
app.include_router(api_keys.router)
app.include_router(assistant.router)


# CORS configuration — explicit browser clients only.
_allowed_origins = os.environ.get("ALLOWED_ORIGINS", DEFAULT_ALLOWED_ORIGINS)
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
# IMPORTANT: AuthContextMiddleware MUST be the innermost middleware (registered LAST)
# so that it executes BEFORE route handlers and their decorators.
# This ensures request.state.session_validation is populated before
# @log_and_handle_errors reads it (Phase 2.2 dependency).
app.add_middleware(AuthContextMiddleware)


# Documentation wiki (docs/ rendered at /documentation; see src/Util/docs_site)
DOCS_BASE_PATH = Path(__file__).parent.parent / "docs"
DOCS_BASE_URL = "/documentation"


class DocFormat(str, Enum):
    """Documentation output format"""
    html = "html"
    raw = "raw"
    md = "md"
    markdown = "markdown"


RAW_DOC_FORMATS = (DocFormat.raw, DocFormat.md, DocFormat.markdown)


def _docs_body(request: Request, body: str | bytes, media_type: str, status_code: int = 200,
               headers: Optional[dict] = None) -> Response:
    """Documentation payloads are large text; gzip them when the client accepts it."""
    data = body.encode("utf-8") if isinstance(body, str) else body
    headers = {**(headers or {}), "Vary": "Accept-Encoding"}
    if len(data) > 1024 and "gzip" in request.headers.get("accept-encoding", "").lower():
        data = gzip.compress(data, compresslevel=6)
        headers["Content-Encoding"] = "gzip"
    return Response(data, status_code=status_code, media_type=media_type, headers=headers)


def _docs_response(request: Request, result: docs_site.DocsResponse) -> Response:
    if result.kind == "redirect":
        return RedirectResponse(url=result.body, status_code=result.status)
    media_type = {
        "markdown": "text/markdown; charset=utf-8",
        "text": "text/plain; charset=utf-8",
    }.get(result.kind, "text/html; charset=utf-8")
    return _docs_body(request, result.body, media_type, result.status)


@app.get("/documentation", response_class=HTMLResponse, tags=["Documentation"])
async def documentation_index(
    request: Request,
    format: Optional[DocFormat] = Query(None, description="Output format: html (default), raw/md/markdown for a Markdown index")
):
    """
    Documentation home page.

    - **format**: Output format
        - `html` (default): the rendered documentation wiki
        - `raw`, `md`, `markdown`: a Markdown index of every page (for LLM/API consumption)
    """
    if format in RAW_DOC_FORMATS:
        index = docs_site.markdown_index(DOCS_BASE_PATH, base_url=DOCS_BASE_URL)
        return _docs_body(request, index, "text/markdown; charset=utf-8")
    home = docs_site.render_home_page(DOCS_BASE_PATH, base_url=DOCS_BASE_URL, version=app.version)
    return _docs_body(request, home, "text/html; charset=utf-8")


@app.get("/documentation/_search.json", include_in_schema=False)
async def documentation_search_index(request: Request):
    """Page and section index behind the documentation search palette."""
    return _docs_body(
        request,
        docs_site.search_index(DOCS_BASE_PATH, base_url=DOCS_BASE_URL),
        "application/json",
        headers={"Cache-Control": "public, max-age=300"},
    )


@app.get("/documentation/{path:path}", tags=["Documentation"])
async def serve_documentation(
    request: Request,
    path: str,
    format: Optional[DocFormat] = Query(None, description="Output format: html (default), raw/md/markdown for raw markdown"),
    raw: bool = Query(False, description="Deprecated: Use format=raw instead")
):
    """
    Serve documentation markdown files.

    - **path**: Path to the markdown file (e.g., USAGE/authentication-usage-cases.md).
      A directory redirects to its `README.md`.
    - **format**: Output format
        - `html` (default): Rendered page with navigation, search and outline
        - `raw`, `md`, `markdown`: Raw markdown content (for LLM/API consumption)
    - **raw**: Deprecated - use `format=raw` instead

    **LLM Usage**: Add `?format=raw` to get plain markdown text suitable for AI/LLM processing.

    **Examples**:
    - `/documentation/USAGE/authentication-usage-cases.md` - Rendered HTML
    - `/documentation/USAGE/authentication-usage-cases.md?format=raw` - Raw markdown for LLMs
    """
    result = docs_site.serve(
        DOCS_BASE_PATH,
        path,
        base_url=DOCS_BASE_URL,
        version=app.version,
        raw=raw or format in RAW_DOC_FORMATS,
    )
    return _docs_response(request, result)


@app.get("/docs/USAGE/{filename:path}", include_in_schema=False)
async def serve_usage_docs_legacy(
    filename: str,
    format: Optional[DocFormat] = Query(None),
    raw: bool = Query(False)
):
    """
    Legacy route for /docs/USAGE/* - redirects to /documentation/USAGE/*
    """
    target = f"{DOCS_BASE_URL}/USAGE/{filename}"
    if raw or format in RAW_DOC_FORMATS:
        target += "?format=raw"
    return RedirectResponse(url=target, status_code=308)


@app.get(
    '/ping',
    status_code=204,
    tags=["System Information"],
    responses={204: {"description": "The API process is up."}},
)
async def ping():
    """
    Public liveness probe.

    Returns `204 No Content`. The handler performs no database, Redis, or session
    checks, so it only proves the process is serving requests; use
    `GET /system/health` (access token required) for component health.
    """
    return Response(status_code=204)


@app.get("/", include_in_schema=False)
async def root():
    response = RedirectResponse(url='/docs')
    return response
