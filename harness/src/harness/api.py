"""Harness HTTP API: public /api/** (via Spring) and internal /internal/runs/** (from MCP)."""

import json
import secrets
from contextlib import asynccontextmanager
from typing import Annotated

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.exceptions import HTTPException as StarletteHTTPException

from harness.catalog import Catalog
from harness.clients import AgentClient, McpClient
from harness.compare import NotComparable, compare
from harness.config import Settings
from harness.events import EventLog, InvalidEvent
from harness.runner import Runner, RunnerError
from harness.store import Store

DEV_USER = ("requester-01", ["REQUESTER"])
TERMINAL = {"COMPLETED", "ERROR"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message or code


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_id: str = Field(min_length=1)
    system_id: str | None = None


class ResumeBody(BaseModel):
    model_config = ConfigDict(extra="forbid")
    approval_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    decision: str = Field(pattern="^(APPROVED|REJECTED)$")
    approver_id: str = Field(min_length=1)
    decided_at: str = Field(min_length=1)
    payload_hash: str = Field(pattern="^[0-9a-f]{64}$")


def _error(status: int, code: str, message: str = "") -> JSONResponse:
    return JSONResponse(
        status_code=status, content={"error": {"code": code, "message": message or code}}
    )


def public_view(run: dict) -> dict:
    return {
        **{k: v for k, v in run.items() if k != "observation"},
        "observed_order_count": (
            len(run["observation"].get("orders", [])) if run.get("observation") is not None else None
        ),
    }


def create_app(settings: Settings | None = None, mcp=None, agents=None) -> FastAPI:
    settings = settings or Settings()

    @asynccontextmanager
    async def lifespan(app):
        token = settings.internal_api_token.get_secret_value()
        catalog = Catalog(settings.harness_project_root)
        store = Store(settings.database_url)
        events = EventLog(store, catalog.event_schema, settings.events_hold_seconds)
        events.start()
        mcp_client = mcp or McpClient(settings.mcp_url, token)
        agent_client = agents or AgentClient(settings.agent_url, token)
        runner = Runner(settings, catalog, store, events, mcp_client, agent_client)
        runner.recover()
        app.state.catalog, app.state.store, app.state.events = catalog, store, events
        app.state.runner = runner
        try:
            yield
        finally:
            await runner.close()
            await events.close()
            if mcp is None:
                await mcp_client.close()
            if agents is None:
                await agent_client.close()
            store.close()

    app = FastAPI(title="Agent Crash Lab — Harness", lifespan=lifespan)

    @app.exception_handler(ApiError)
    async def api_error(request, exc: ApiError):
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RunnerError)
    async def runner_error(request, exc: RunnerError):
        return _error(exc.status, exc.code, exc.message)

    @app.exception_handler(RequestValidationError)
    async def validation_error(request, exc):
        loc = ".".join(str(x) for x in exc.errors()[0]["loc"]) if exc.errors() else ""
        return _error(400, "VALIDATION_ERROR", f"invalid {loc}")

    @app.exception_handler(StarletteHTTPException)
    async def http_error(request, exc):
        return _error(exc.status_code, "NOT_FOUND" if exc.status_code == 404 else "ERROR")

    # auth

    def _token_ok(value: str | None) -> bool:
        expected = settings.internal_api_token.get_secret_value()
        if not expected:
            raise ApiError(503, "INTERNAL_API_TOKEN_NOT_CONFIGURED")
        return bool(value) and secrets.compare_digest(value.encode(), expected.encode())

    def internal(x_internal_token: str | None = Header(default=None)):
        if not _token_ok(x_internal_token):
            raise ApiError(401, "UNAUTHORIZED", "invalid internal token")

    def user(
        x_internal_token: str | None = Header(default=None),
        x_user_id: str | None = Header(default=None),
        x_user_roles: str | None = Header(default=None),
    ) -> tuple[str, list[str]]:
        if x_internal_token is None and settings.harness_dev_auth:
            return DEV_USER
        if not _token_ok(x_internal_token) or not x_user_id:
            raise ApiError(401, "UNAUTHORIZED", "gateway headers required")
        roles = [r.strip() for r in (x_user_roles or "").split(",") if r.strip()]
        return x_user_id, roles

    User = Annotated[tuple[str, list[str]], Depends(user)]

    def runner(request: Request) -> Runner:
        return request.app.state.runner

    def get_run(request: Request, run_id: str) -> dict:
        run = request.app.state.store.get_run(run_id)
        if run is None:
            raise ApiError(404, "NOT_FOUND", f"run {run_id}")
        return run

    # health

    @app.get("/health")
    async def health():
        return {"status": "UP"}

    # public API (HARNESS_SPEC §1)

    @app.get("/api/scenarios")
    async def scenarios(request: Request, _: User):
        return request.app.state.catalog.scenarios_response()

    @app.post("/api/runs", status_code=202)
    async def create_run(body: CreateRun, request: Request, who: User):
        user_id, roles = who
        if "REQUESTER" not in roles:
            raise ApiError(403, "PERMISSION_DENIED", "REQUESTER role required")
        run = await runner(request).create_run(body.test_id, body.system_id, user_id)
        return {
            "run_id": run["run_id"],
            "status": run["status"],
            "events_url": f"/api/runs/{run['run_id']}/events",
        }

    @app.get("/api/runs")
    async def list_runs(request: Request, _: User, limit: int = Query(50, ge=1, le=200)):
        return {
            "runs": [
                {
                    k: run.get(k)
                    for k in ("run_id", "test_id", "system_id", "status", "summary", "created_at")
                }
                for run in request.app.state.store.list_runs(limit)
            ]
        }

    @app.get("/api/runs/{run_id}")
    async def run_detail(run_id: str, request: Request, _: User):
        return public_view(get_run(request, run_id))

    @app.get("/api/runs/{run_id}/events")
    async def run_events(
        run_id: str,
        request: Request,
        _: User,
        after_sequence: int = Query(0, ge=0),
        limit: int = Query(200, ge=1, le=1000),
        last_event_id: str | None = Header(default=None),
        accept: str = Header(default="application/json"),
    ):
        get_run(request, run_id)
        store, log = request.app.state.store, request.app.state.events
        if "text/event-stream" not in accept:
            items = store.list_events(run_id, after_sequence, limit + 1)
            run = get_run(request, run_id)
            return {
                "events": items[:limit],
                "has_more": len(items) > limit,
                "is_final": (
                    run["status"] in TERMINAL
                    and run["investigation"]["status"] != "RUNNING"
                    and not log.pending(run_id)
                ),
            }

        start = int(last_event_id) if last_event_id and last_event_id.isdigit() else after_sequence

        async def stream():
            after = start
            while True:
                for event in store.list_events(run_id, after):
                    after = event["sequence"]
                    data = json.dumps(event, ensure_ascii=False)
                    yield f"id: {after}\nevent: run_event\ndata: {data}\n\n"
                run = store.get_run(run_id)
                done = (
                    run["status"] in TERMINAL
                    and run["investigation"]["status"] != "RUNNING"
                    and not log.pending(run_id)
                )
                if done and not store.list_events(run_id, after, 1):
                    end = {"run_id": run_id, "status": run["status"]}
                    yield f"event: run_end\ndata: {json.dumps(end)}\n\n"
                    return
                if await request.is_disconnected():
                    return
                before = after
                await log.wait(run_id, settings.sse_keepalive_seconds)
                if not store.list_events(run_id, before, 1) and not done:
                    yield ": keep-alive\n\n"

        return StreamingResponse(stream(), media_type="text/event-stream")

    @app.get("/api/comparisons")
    async def comparisons(
        request: Request, _: User, left: str = Query(...), right: str = Query(...)
    ):
        try:
            return compare(get_run(request, left), get_run(request, right))
        except NotComparable as exc:
            raise ApiError(422, exc.code) from exc

    # internal API for mcp-server (HARNESS_SPEC §4)

    @app.post("/internal/runs/{run_id}/resume", status_code=202, dependencies=[Depends(internal)])
    async def resume(run_id: str, body: ResumeBody, request: Request):
        await runner(request).resume(run_id, body.model_dump())
        return {"run_id": run_id, "accepted": True}

    @app.post("/internal/runs/{run_id}/events", status_code=202, dependencies=[Depends(internal)])
    async def submit_event(run_id: str, request: Request):
        get_run(request, run_id)
        try:
            event = await request.json()
        except ValueError as exc:
            raise ApiError(400, "VALIDATION_ERROR", "body is not JSON") from exc
        if not isinstance(event, dict) or not event.get("event_id"):
            raise ApiError(400, "VALIDATION_ERROR", "event_id required")
        event = {k: v for k, v in event.items() if k not in {"run_id", "sequence"}}
        try:
            sequence = await request.app.state.events.append(run_id, event)
        except InvalidEvent as exc:
            raise ApiError(400, "VALIDATION_ERROR", str(exc)) from exc
        return {"event_id": event["event_id"], "sequence": sequence}

    @app.get("/internal/runs/{run_id}/checks", dependencies=[Depends(internal)])
    async def internal_checks(run_id: str, request: Request, verdicts: str = "FAIL,INCONCLUSIVE"):
        wanted = {v.strip() for v in verdicts.split(",") if v.strip()}
        return {"checks": [c for c in get_run(request, run_id)["checks"] if c["verdict"] in wanted]}

    @app.get("/internal/runs/{run_id}/events", dependencies=[Depends(internal)])
    async def internal_events(run_id: str, request: Request):
        get_run(request, run_id)
        await request.app.state.events.flush(run_id, force=True)
        return {"events": request.app.state.store.list_events(run_id)}

    return app


app = create_app()
