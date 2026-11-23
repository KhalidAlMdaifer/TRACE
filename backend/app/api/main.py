"""The api: `uvicorn app.api.main:app`. JSON everywhere, a session cookie, all routes under
/api, and no anonymous endpoint except the sign-in itself."""
from __future__ import annotations

from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from .. import config, db
from . import auth, cases, packs, stream
from .deps import ApiError
from .fitpool import FitPool


def _error(status: int, code: str, message: str) -> JSONResponse:
    return JSONResponse({"error": {"code": code, "message": message}}, status_code=status)


def create_app() -> FastAPI:
    config.load_dotenv()

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        db.init()
        conn = db.connect()
        try:
            auth.ensure_admin(conn)
        finally:
            conn.close()
        app.state.fitpool = FitPool()
        app.state.fitpool.start()
        yield
        app.state.fitpool.stop()

    # no interactive docs: they would be an anonymous endpoint describing the tool
    app = FastAPI(title="TRACE", lifespan=lifespan, docs_url=None, redoc_url=None, openapi_url=None)
    app.add_middleware(SessionMiddleware, secret_key=config.app_secret(), session_cookie="trace_session",
                       max_age=config.session_max_age_s(), same_site="lax", https_only=config.session_secure())

    @app.exception_handler(ApiError)
    async def _api_error(request: Request, e: ApiError):
        return _error(e.status, e.code, e.message)

    @app.exception_handler(RequestValidationError)
    async def _invalid(request: Request, e: RequestValidationError):
        first = e.errors()[0] if e.errors() else {}
        where = ".".join(str(x) for x in first.get("loc", []) if x not in ("body", "query"))
        return _error(422, "invalid_request", f"{where}: {first.get('msg', 'invalid')}" if where else first.get("msg", "invalid request"))

    @app.exception_handler(StarletteHTTPException)
    async def _http(request: Request, e: StarletteHTTPException):
        code = {404: "not_found", 405: "method_not_allowed", 413: "too_large"}.get(e.status_code, "error")
        return _error(e.status_code, code, str(e.detail))

    for r in (auth.router, cases.router, packs.router, stream.router):
        app.include_router(r)
    return app


def __getattr__(name: str):
    # built on first use, so importing this module does not need the environment
    if name == "app":
        return create_app()
    raise AttributeError(name)
