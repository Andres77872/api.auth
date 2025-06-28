from fastapi import FastAPI, Request, Security, BackgroundTasks
from fastapi.middleware.cors import CORSMiddleware

from starlette.responses import RedirectResponse

from src.Util.logger_ws import logger
from src.routes import Access, User

import time

from src.Util.Seccurity import returnJson_422, returnJson_413, x_token_user, x_token_collection

description = open('./src/README.md').read()

app = FastAPI(title='API for findit.moe',
              description=description,
              version='0.3.0',
              contact={
                  "name": "Andrés",
                  "url": "https://arizmendi.io",
                  "email": "andres@arz.ai",
              })

# app.include_router(Pic2Encoder_picsearch.router,
#                    prefix='/pic2encoder',
#                    tags=['encoders'])

app.include_router(User.router,
                   prefix='/user',
                   tags=['User login/register'])

# app.include_router(UserControl.router,
#                    prefix='/user',
#                    tags=['User control'],
#                    dependencies=[Security(x_token_user), Security(x_token_collection)])

app.include_router(Access.router,
                   prefix='/access',
                   tags=['Access control by token'],
                   dependencies=[Security(x_token_user), Security(x_token_collection)])

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
        if int(request.headers['content-length']) > 8388608:
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
    pass


@app.get("/", include_in_schema=False)
async def root():
    response = RedirectResponse(url='/docs')
    return response
