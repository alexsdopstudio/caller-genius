from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.responses import RedirectResponse, JSONResponse
from app.database import init_db, engine
from app.config import get_settings
from app.routers import audit, demo, tools, admin


@asynccontextmanager
async def lifespan(app):
    await init_db()
    yield
    await engine.dispose()


app = FastAPI(title='Caller Genius — Audit-to-Demo', lifespan=lifespan,
              docs_url=None, redoc_url=None, openapi_url=None)
# Same-origin UI: no wildcard CORS, no browser access to authenticated tools.


@app.middleware('http')
async def security_headers(request: Request, call_next):
    try:
        size = int(request.headers.get('content-length', '0') or '0')
    except ValueError:
        return JSONResponse({'detail': 'Invalid Content-Length'}, status_code=400)
    if size > 2_000_000:
        return JSONResponse({'detail': 'Payload too large'}, status_code=413)
    if request.method in {'POST', 'PUT', 'DELETE', 'PATCH'} and request.headers.get('origin'):
        if request.headers['origin'].rstrip('/') != get_settings().public_base_url:
            return JSONResponse({'detail': 'Origin non consentita'}, status_code=403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['Referrer-Policy'] = 'no-referrer'
    response.headers['Cache-Control'] = 'no-store'
    response.headers['X-Frame-Options'] = 'DENY'
    return response


@app.get('/health')
async def health():
    return {'status': 'ok', 'mock': get_settings().simulated}


@app.get('/')
async def root():
    return RedirectResponse('/admin/prospects')


for router in [audit.router, demo.router, tools.router, admin.router]:
    app.include_router(router)
