from fastapi import FastAPI, Request, Security, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from starlette.responses import RedirectResponse

from src.Util.logger_ws import logger
from src.routes import (
    Access, auth, users, user_types_auth, projects, 
    admin_user_groups, admin_project_groups, system, rbac
)

import time

from src.Util.Seccurity import returnJson_422, returnJson_413, x_token_user, x_token_collection

# Read description from README file
with open('./src/README.md', 'r', encoding='utf-8') as f:
    description = f.read()

app = FastAPI(
    title='3-Tier User Type Multi-Project Authentication API',
    description=description,
    version='2.1.0',
    contact={
        "name": "Andrés",
        "url": "https://arizmendi.io",
        "email": "andres@arz.ai",
    }
)

# 3-TIER USER TYPE AUTHENTICATION ROUTES
app.include_router(auth.router, tags=['Authentication'])
app.include_router(users.router, tags=['User Management'])
app.include_router(user_types_auth.router, tags=['User Type Management'])
app.include_router(projects.router, tags=['Project Management'])
app.include_router(admin_user_groups.router, tags=['Admin - User Groups'])
app.include_router(admin_project_groups.router, tags=['Admin - Project Groups'])
app.include_router(rbac.router, tags=['RBAC Management'])
app.include_router(system.router, tags=['System'])

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


@app.middleware("http")
async def add_process_time_header(request: Request, call_next):
    start_time = time.time()

    if 'user-agent' not in request.headers:
        response = returnJson_422()
        process_time = time.time() - start_time
        response.headers["X-Process-Time"] = str(process_time)
        response.headers['Access-Control-Allow-Origin'] = '*'
        return response

    if request.method == 'POST':
        content_length = request.headers.get('content-length')
        if content_length and int(content_length) > 8388608:
            response = returnJson_413()
            process_time = time.time() - start_time
            response.headers["X-Process-Time"] = str(process_time)
            response.headers['Access-Control-Allow-Origin'] = '*'
            return response

    response = await call_next(request)

    process_time = time.time() - start_time
    response.headers["X-Process-Time"] = str(process_time)

    data = {
        'path': request.url.path,
        'host': request.url.hostname,
        'query': str(request.query_params),
        'method': request.method,
        'cl': request.headers['content-length'] if 'content-length' in request.headers else None,
        'ua': request.headers.get('user-agent'),
        'status': response.status_code,
        'time': process_time
    }

    try:
        data['ip'] = request.headers.get('x-forwarded-for').split(',')[0]
    except Exception:
        data['ip'] = 'localhost'

    background_task = BackgroundTasks()
    background_task.add_task(logger, data, 'auth', 'access')
    response.background = background_task

    return response


@app.get('/ping', status_code=204)
def ping():
    """Health check endpoint"""
    pass


@app.get("/", include_in_schema=False)
async def root():
    response = RedirectResponse(url='/docs')
    return response
