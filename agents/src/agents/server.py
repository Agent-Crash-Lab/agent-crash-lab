"""Agent-only internal API draft. Harness ownership/auth checks remain external."""

import asyncio
import logging
import secrets
from contextlib import asynccontextmanager

import httpx
from fastapi import Depends, FastAPI, Header, HTTPException, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from jsonschema.exceptions import SchemaError, ValidationError
from referencing.exceptions import Unresolvable

from agents.config import Settings
from agents.llm import TOTAL_BUDGET, ModelError
from agents.models import ResumeRequest, StartRequest
from agents.qa.design import AnalyzeRequest, DesignRequest, analyze_description, design_qa
from agents.runtime import RunError, Runtime
from agents.targets.manufacturing import SimulationTask, run_reference


def create_app(
    settings=None, model=None, design_model=None, design_search=None, design_reviewer=None
):
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        runtime = await Runtime(settings, model=model).open()
        app.state.runtime = runtime
        app.state.design_lock = asyncio.Lock()
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

    @app.get("/internal/qa/execution-profile", dependencies=[Depends(authorize)])
    async def execution_profile(request: Request):
        metadata = request.app.state.runtime.model_metadata("PURCHASE_AGENT")
        live = metadata["model_kind"] == "openai"
        return {
            "runtime_id": "reference-purchase-v1",
            **metadata,
            "run_cost_upper_bound_usd": TOTAL_BUDGET if live else 0,
            "cost_bound_basis": "EXISTING_SHARED_DURABLE_LLM_BUDGET",
        }

    @app.post("/internal/qa/analyze", dependencies=[Depends(authorize)])
    async def analyze_target(body: AnalyzeRequest):
        try:
            return analyze_description(settings, body)
        except (ValueError, ValidationError, SchemaError, RecursionError, Unresolvable):
            raise HTTPException(422, "INVALID_TARGET_DESCRIPTION") from None

    @app.post("/internal/qa/design", dependencies=[Depends(authorize)])
    async def design(body: DesignRequest, request: Request):
        lock = request.app.state.design_lock
        if lock.locked():
            raise HTTPException(409, "QA_DESIGN_IN_PROGRESS")
        async with lock:
            try:
                return await design_qa(
                    settings,
                    body,
                    model=design_model,
                    search=design_search,
                    reviewer=design_reviewer,
                )
            except (ValueError, ValidationError, SchemaError, RecursionError, Unresolvable):
                raise HTTPException(422, "INVALID_DESIGN_INPUT_OR_OUTPUT") from None
            except ModelError as exc:
                code = str(exc)
                logging.getLogger(__name__).warning("QA design failed: %s", code)
                raise HTTPException(
                    503,
                    code
                    if code in {"LLM_KEY_NOT_CONFIGURED", "UNPRICED_MODEL", "LLM_BUDGET_EXHAUSTED"}
                    else "QA_DESIGN_UNAVAILABLE",
                ) from None
            except (httpx.HTTPError, TimeoutError):
                raise HTTPException(503, "QA_DESIGN_UNAVAILABLE") from None

    @app.post("/internal/qa/simulation-execute", dependencies=[Depends(authorize)])
    async def simulation_execute(body: SimulationTask):
        if not body.mcp_url.startswith(
            settings.simulation_callback_base.rstrip("/") + "/simulations/"
        ):
            raise HTTPException(422, "INVALID_SANDBOX_CALLBACK")
        try:
            return await run_reference(body)
        except (httpx.HTTPError, ValueError, KeyError):
            raise HTTPException(502, "SIMULATION_EXECUTION_FAILED") from None

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
