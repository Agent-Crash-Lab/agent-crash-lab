"""Agent-only internal API draft. Harness ownership/auth checks remain external."""

import secrets
from contextlib import asynccontextmanager

from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from agents.config import Settings
from agents.models import ResumeRequest, StartRequest
from agents.runtime import RunError, Runtime


def create_app(settings=None, model=None):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        runtime = await Runtime(settings, model=model).open()
        app.state.runtime = runtime
        try:
            yield
        finally:
            await runtime.close()

    app = FastAPI(title="Agent Crash Lab — Agents", lifespan=lifespan)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        # FastAPI's default includes raw input, which can contain bearer tokens.
        return JSONResponse(
            status_code=422,
            content={
                "detail": [
                    {"loc": list(error["loc"]), "type": error["type"], "msg": "Invalid input"}
                    for error in exc.errors()
                ]
            },
        )

    @app.exception_handler(RunError)
    async def run_error(request, exc):
        return JSONResponse(status_code=exc.status, content={"detail": exc.code})

    def authorize(x_internal_token: str | None = Header(default=None)):
        expected = settings.internal_api_token.get_secret_value()
        if not expected:
            raise HTTPException(503, "INTERNAL_API_TOKEN is not configured")
        if not x_internal_token or not secrets.compare_digest(
            x_internal_token.encode(), expected.encode()
        ):
            raise HTTPException(401, "Invalid internal token")

    @app.get("/health")
    async def health():
        return {"status": "ok"}

    prefix = "/internal/agent-runs"

    @app.post(prefix, status_code=202, dependencies=[Depends(authorize)])
    async def start(body: StartRequest, request: Request):
        return await request.app.state.runtime.start(body)

    @app.get(prefix + "/{run_id}", dependencies=[Depends(authorize)])
    async def status(run_id: str, request: Request):
        return request.app.state.runtime.status(run_id)

    @app.post(prefix + "/{run_id}/resume", status_code=202, dependencies=[Depends(authorize)])
    async def resume(run_id: str, body: ResumeRequest, request: Request):
        return await request.app.state.runtime.resume(run_id, body)

    @app.get(prefix + "/{run_id}/events", dependencies=[Depends(authorize)])
    async def events(run_id: str, request: Request, after_sequence: int = Query(0, ge=0)):
        runtime = request.app.state.runtime
        runtime.status(run_id)
        return {
            "events": runtime.store.events(run_id, after_sequence),
            "sequence_scope": "AGENT_LOCAL",
        }

    return app


app = create_app()
