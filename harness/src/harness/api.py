"""Harness HTTP API: public /api/** (via Spring) and internal /internal/runs/** (from MCP)."""

import json
import secrets
from contextlib import asynccontextmanager
from typing import Annotated, Literal

from fastapi import Depends, FastAPI, Header, Query, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse, Response, StreamingResponse
from jsonschema.exceptions import SchemaError, ValidationError
from pydantic import BaseModel, ConfigDict, Field, model_validator
from referencing.exceptions import Unresolvable
from starlette.exceptions import HTTPException as StarletteHTTPException

from harness.batches import Batches
from harness.catalog import Catalog
from harness.clients import AgentClient, ClientError, McpClient
from harness.compare import NotComparable, compare
from harness.config import Settings
from harness.designing import design_with_repair
from harness.events import EventLog, InvalidEvent, now_iso
from harness.followups import recommendation
from harness.registrations import (
    CAPABILITY_OPTIONS,
    Registration,
    bind_runtime,
    library_hash,
    profile,
    target_input,
)
from harness.reporting import qa_report
from harness.runner import Runner, RunnerError
from harness.scenarios import index_plan
from harness.simulation import Decision, SimulationError, investigation_state
from harness.store import Store

DEV_USER = ("requester-01", ["REQUESTER"])
TERMINAL = {"COMPLETED", "ERROR"}


class ApiError(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(code)
        self.status, self.code, self.message = status, code, message or code


class CreateRun(BaseModel):
    model_config = ConfigDict(extra="forbid")
    test_id: str | None = Field(default=None, min_length=1)
    system_id: str | None = None
    plan_id: str | None = None
    case_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def select_execution(self):
        if self.case_id is not None:
            if not self.plan_id or self.test_id is not None:
                raise ValueError("Use plan_id + case_id, without test_id")
        elif self.test_id is None:
            raise ValueError("Select test_id or plan_id + case_id")
        return self


class PlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: dict | None = None
    sample_data: dict | None = None
    knowledge_query: str | None = Field(default=None, min_length=2, max_length=1000)
    knowledge_target_type: Literal["COMMON", "PURCHASE", "PRODUCTION", "QUALITY"] = "COMMON"


class DesignOptions(BaseModel):
    model_config = ConfigDict(extra="forbid")
    generation_mode: Literal["configured", "llm", "offline"] = "configured"


class DesignPlanRequest(DesignOptions):
    model_config = ConfigDict(extra="forbid")
    target: dict | None = None
    sample_data: dict | None = None


class BatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    request_id: str = Field(pattern=r"^[A-Za-z0-9_-]{1,64}$")
    plan_id: str = Field(min_length=1, max_length=128)
    case_ids: list[str] = Field(default_factory=list, max_length=10)
    systems: list[Literal["B0", "B1"]] = Field(default=["B0", "B1"], min_length=1, max_length=2)
    mode: Literal["SMOKE", "RELIABILITY"] = "SMOKE"
    max_runs: int = Field(default=8, ge=1, le=300)
    max_seconds: int = Field(default=900, ge=1, le=3600)
    max_cost_usd: float = Field(default=1.0, ge=0, le=1.0, allow_inf_nan=False)

    @model_validator(mode="after")
    def unique_systems(self):
        if len(self.systems) != len(set(self.systems)):
            raise ValueError("Duplicate systems")
        return self


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
        "qa_report": qa_report(run) if run.get("run_id") and run.get("status") else None,
        **{k: v for k, v in run.items() if k != "observation"},
        "observed_change_count": (
            len(run["observation"].get("changes", run["observation"].get("orders", [])))
            if run.get("observation") is not None
            else None
        ),
        "observed_order_count": (
            len(run["observation"].get("orders", []))
            if run.get("observation") is not None
            else None
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
        app.state.batches = Batches(runner)
        app.state.batches.recover()
        app.state.catalog, app.state.store, app.state.events = catalog, store, events
        app.state.runner = runner
        try:
            yield
        finally:
            await app.state.batches.close()
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

    @app.exception_handler(SimulationError)
    async def simulation_error(request, exc):
        return _error(exc.status, exc.code)

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

    def save_plan(request: Request, plan: dict, owner: str) -> dict:
        """Store the plan unchanged and register its executable cases in the library."""
        store = request.app.state.store
        store.put_plan(plan, owner)
        index_plan(store, plan, owner, now_iso())
        return plan

    # health

    @app.get("/health")
    async def health():
        return {"status": "UP"}

    # public API (HARNESS_SPEC §1)

    @app.get("/api/scenarios")
    async def scenarios(request: Request, _: User):
        return request.app.state.catalog.scenarios_response()

    @app.get("/api/qa/targets")
    async def target_types(request: Request, _: User):
        return {"types": request.app.state.catalog.planner.target_types()}

    @app.get("/api/qa/target")
    async def reference_target(
        request: Request,
        _: User,
        target_type: Literal["PURCHASE", "PRODUCTION", "QUALITY"] = "PURCHASE",
    ):
        planner = request.app.state.catalog.planner
        return planner.target_input(target_type)

    @app.post("/api/qa/plans")
    async def plan_qa(body: PlanRequest, request: Request, who: User):
        if "REQUESTER" not in who[1]:
            raise ApiError(403, "PERMISSION_DENIED", "REQUESTER role required")
        try:
            context = None
            if body.knowledge_query:
                try:
                    result = await request.app.state.runner.mcp.search_knowledge(
                        {
                            "query": body.knowledge_query,
                            "target_type": body.knowledge_target_type,
                            "limit": 3,
                        }
                    )
                except ClientError:
                    raise ApiError(503, "KNOWLEDGE_UNAVAILABLE") from None
                context = {
                    "query": result["query"],
                    "target_type": body.knowledge_target_type,
                    "index_version": result["index_version"],
                    "model": result["model"],
                    "model_revision": result["model_revision"],
                    "sources": [
                        {
                            k: s[k]
                            for k in (
                                "document_id",
                                "source_id",
                                "version",
                                "location",
                                "source_url",
                                "content_kind",
                            )
                        }
                        for s in result["results"]
                    ],
                }
            plan = request.app.state.catalog.planner.build(body.target, body.sample_data, context)
            return save_plan(request, plan, who[0])
        except (ValidationError, SchemaError, ValueError, Unresolvable, RecursionError) as exc:
            raise ApiError(
                400, "INVALID_QA_INPUT", "Invalid target description or sample data"
            ) from exc

    def registration_view(saved):
        runtime_id = saved.get("execution_binding", {}).get("runtime_id", "")
        if runtime_id.startswith("external-") and runtime_id not in json.loads(
            settings.external_agent_endpoints.get_secret_value()
        ):
            return {**saved, "execution_status": "ADAPTER_REQUIRED"}
        return saved

    @app.get("/api/qa/registrations")
    async def registrations(request: Request, who: User):
        return {
            "profiles": [
                registration_view(p) for p in request.app.state.store.list_registrations(who[0])
            ],
            "execution_runtimes": [
                {"runtime_id": key, "name": "외부 " + value["agent_type"] + " · " + key}
                for key, value in json.loads(
                    settings.external_agent_endpoints.get_secret_value()
                ).items()
            ],
            "capabilities": CAPABILITY_OPTIONS,
        }

    @app.get("/api/qa/registrations/{profile_id}")
    async def registration(profile_id: str, request: Request, who: User):
        result = request.app.state.store.get_registration(profile_id, who[0])
        if result is None:
            raise ApiError(404, "QA_TARGET_NOT_FOUND")
        return registration_view(result)

    @app.post("/api/qa/registrations")
    async def register(body: Registration, request: Request, who: User):
        if "REQUESTER" not in who[1]:
            raise ApiError(403, "PERMISSION_DENIED")
        try:
            agents = request.app.state.runner.agents
            binding = bind_runtime(
                body,
                request.app.state.catalog.planner,
                await request.app.state.runner.execution_profile(body.execution_runtime)
                if body.execution_runtime
                else {},
            )
            saved = profile(body, None, settings.harness_project_root, binding)
            existing = request.app.state.store.get_registration(saved["profile_id"], who[0])
            if existing is not None:
                return existing
            saved["analysis"] = await agents.analyze(target_input(body))
            return request.app.state.store.put_registration(saved, who[0])
        except ClientError:
            raise ApiError(503, "QA_ANALYSIS_UNAVAILABLE") from None
        except (ValidationError, SchemaError, ValueError, KeyError, RecursionError) as exc:
            code = (
                "INCOMPATIBLE_EXECUTION_TARGET" if body.execution_runtime else "INVALID_QA_TARGET"
            )
            raise ApiError(400, code, str(exc)[:250] if body.execution_runtime else code) from None

    @app.post("/api/qa/registrations/{profile_id}/design")
    async def design_registered(
        profile_id: str, request: Request, who: User, options: DesignOptions
    ):
        if "REQUESTER" not in who[1]:
            raise ApiError(403, "PERMISSION_DENIED")
        saved = await registration(profile_id, request, who)
        if not saved["can_design"]:
            raise ApiError(422, "PROFILE_INFORMATION_REQUIRED")
        if saved["risk_library_hash"] != library_hash(settings.harness_project_root):
            raise ApiError(409, "PROFILE_ANALYSIS_CHANGED")
        try:
            planner = request.app.state.catalog.planner
            body = Registration(**saved["input"])
            data = target_input(body)
            data.pop("unknown_policies")
            binding = saved.get("execution_binding")
            if binding:
                current = bind_runtime(
                    body,
                    planner,
                    await request.app.state.runner.execution_profile(body.execution_runtime),
                )
                if current != binding:
                    raise ApiError(
                        409, "TARGET_RUNTIME_CHANGED", "실행기가 바뀌었습니다. 다시 등록하세요."
                    )
                data["target"] = planner.target_input(body.agent_type)["target"]
            designed = await design_with_repair(
                request.app.state.runner.agents,
                planner,
                {**data, "generation_mode": options.generation_mode},
            )
            designed["registration"] = {
                k: saved[k]
                for k in ("profile_id", "profile_hash", "name", "assurance", "risk_library_hash")
            }
            if binding:
                designed["registration"]["execution_binding"] = binding
            plan = planner.build_designed(data["target"], data["sample_data"], designed)
            if not binding and any(c["execution"]["status"] == "READY" for c in plan["cases"]):
                raise ValueError("Unbound registrations cannot acquire execution support")
            return save_plan(request, plan, who[0])
        except ClientError as exc:
            raise ApiError(
                503,
                exc.code
                if exc.code in {"LLM_KEY_NOT_CONFIGURED", "UNPRICED_MODEL", "LLM_BUDGET_EXHAUSTED", "LLM_INPUT_LIMIT"}
                else "QA_DESIGN_UNAVAILABLE",
            ) from None
        except (ValidationError, SchemaError, ValueError, KeyError, RecursionError):
            raise ApiError(400, "INVALID_QA_DESIGN") from None

    @app.post("/api/qa/design")
    async def design_plan(body: DesignPlanRequest, request: Request, who: User):
        if "REQUESTER" not in who[1]:
            raise ApiError(403, "PERMISSION_DENIED", "REQUESTER role required")
        planner = request.app.state.catalog.planner
        try:
            # Validate input locally before contacting the design service.
            planner.build(body.target, body.sample_data)
            target = body.target if body.target is not None else planner.reference_target
            sample = body.sample_data if body.sample_data is not None else planner.reference_sample
            designed = await design_with_repair(
                request.app.state.runner.agents,
                planner,
                {"target": target, "sample_data": sample, "generation_mode": body.generation_mode},
            )
            plan = planner.build_designed(target, sample, designed)
            return save_plan(request, plan, who[0])
        except ClientError as exc:
            raise ApiError(
                503,
                exc.code
                if exc.code in {"LLM_KEY_NOT_CONFIGURED", "UNPRICED_MODEL", "LLM_BUDGET_EXHAUSTED", "LLM_INPUT_LIMIT"}
                else "QA_DESIGN_UNAVAILABLE",
            ) from None
        except (ValidationError, SchemaError, ValueError, KeyError, Unresolvable, RecursionError):
            raise ApiError(400, "INVALID_QA_DESIGN") from None

    @app.get("/api/qa/plans/{plan_id}")
    async def saved_plan(plan_id: str, request: Request, who: User):
        plan = request.app.state.store.get_plan(plan_id, who[0])
        if plan is None:
            raise ApiError(404, "QA_PLAN_NOT_FOUND")
        return plan

    @app.get("/api/qa/plans/{plan_id}/scenarios")
    async def plan_scenarios(plan_id: str, request: Request, who: User):
        """Each executable case of the plan against the target's scenario library."""
        plan = request.app.state.store.get_plan(plan_id, who[0])
        if plan is None:
            raise ApiError(404, "QA_PLAN_NOT_FOUND")
        rows = index_plan(request.app.state.store, plan, who[0], now_iso())
        return {"plan_id": plan_id, "target_id": plan["target_id"], "scenarios": rows}

    @app.get("/api/qa/scenarios/{scenario_id}/runs")
    async def scenario_runs(scenario_id: str, request: Request, who: User):
        """The requester's own runs of one scenario, from any plan. Others' runs stay hidden."""
        store = request.app.state.store
        entry = store.get_scenario(scenario_id)
        if entry is None:
            raise ApiError(404, "QA_SCENARIO_NOT_FOUND")
        owned = entry["created_by"] == who[0]
        runs = sorted(
            (
                run
                for run in store.all_runs()
                if run.get("qa_scenario_id") == scenario_id and run.get("created_by") == who[0]
            ),
            key=lambda run: run["created_at"],
            reverse=True,
        )
        return {
            "scenario_id": scenario_id,
            "target_id": entry["target_id"],
            "owned": owned,
            **({"condition": entry["condition"]} if owned else {}),
            "runs": [
                {
                    "run_id": run["run_id"],
                    "plan_id": run["manifest"].get("qa_plan_id"),
                    "case_id": run["manifest"].get("qa_case_id"),
                    "system_id": run.get("system_id"),
                    "status": run["status"],
                    "summary": run.get("summary"),
                    "created_at": run["created_at"],
                    "finished_at": run.get("finished_at"),
                }
                for run in runs
            ],
        }

    @app.post("/api/qa/batches", status_code=202)
    async def create_batch(body: BatchRequest, request: Request, who: User):
        if "REQUESTER" not in who[1]:
            raise ApiError(403, "PERMISSION_DENIED")
        try:
            return await request.app.state.batches.create(body, who[0])
        except ClientError:
            raise ApiError(503, "AGENT_PROFILE_UNAVAILABLE") from None
        except (ValidationError, ValueError, KeyError):
            raise ApiError(409, "INVALID_QA_STRATEGY") from None

    @app.get("/api/qa/batches/{batch_id}")
    async def batch_detail(batch_id: str, request: Request, who: User):
        return request.app.state.batches.get(batch_id, who[0])

    @app.get("/api/qa/batches")
    async def batch_list(request: Request, who: User):
        return {
            "batches": [
                b
                for b in sorted(
                    request.app.state.store.all_batches(),
                    key=lambda b: b["created_at"],
                    reverse=True,
                )
                if b["created_by"] == who[0]
            ][:30]
        }

    @app.post("/api/qa/batches/{batch_id}/stop")
    async def stop_batch(batch_id: str, request: Request, who: User):
        if "REQUESTER" not in who[1]:
            raise ApiError(403, "PERMISSION_DENIED")
        return request.app.state.batches.stop(batch_id, who[0])

    @app.post("/api/runs", status_code=202)
    async def create_run(body: CreateRun, request: Request, who: User):
        user_id, roles = who
        if "REQUESTER" not in roles:
            raise ApiError(403, "PERMISSION_DENIED", "REQUESTER role required")
        run = await runner(request).create_run(
            body.test_id, body.system_id, user_id, body.plan_id, body.case_id
        )
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

    @app.get("/api/qa/approver/runs")
    async def approver_runs(request: Request, who: User):
        if "APPROVER" not in who[1]:
            raise ApiError(403, "PERMISSION_DENIED")
        store = request.app.state.store
        recent = store.list_runs(200)
        # Keep every pending decision visible even when newer QA runs fill the history.
        pending = [r for r in store.all_runs() if r.get("status") == "WAITING_APPROVAL"]
        runs = {r["run_id"]: r for r in [*recent, *pending]}
        fields = ("run_id", "test_id", "system_id", "status", "created_at", "created_by",
                  "request", "approval_request", "approval", "summary")
        return {"runs": [
            {**{k: r.get(k) for k in fields},
             "simulation": bool((r.get("manifest") or {}).get("state_store")),
             "qa_report": qa_report(r) if r.get("status") == "COMPLETED" else None}
            for r in sorted(runs.values(), key=lambda r: r.get("created_at", ""), reverse=True)
        ]}

    @app.get("/api/runs/{run_id}")
    async def run_detail(run_id: str, request: Request, who: User):
        run = get_run(request, run_id)
        return public_view(
            {**run, "follow_up": recommendation(run, request.app.state.store, who[0])}
        )

    @app.post("/api/qa/runs/{run_id}/follow-up", status_code=202)
    async def follow_up(run_id: str, request: Request, who: User):
        if "REQUESTER" not in who[1]:
            raise ApiError(403, "PERMISSION_DENIED")
        run = get_run(request, run_id)
        if run.get("created_by") != who[0]:
            raise ApiError(404, "NOT_FOUND")
        proposal = recommendation(run, request.app.state.store, who[0])
        if proposal["status"] != "READY":
            raise ApiError(422, "FOLLOW_UP_UNAVAILABLE", proposal["reason"])
        batch = await request.app.state.batches.create(
            BatchRequest(
                request_id="followup-" + run_id,
                plan_id=proposal["plan_id"],
                case_ids=proposal["case_ids"],
                systems=proposal["systems"],
                mode="SMOKE",
                max_runs=2,
                max_seconds=900,
                max_cost_usd=1.0,
            ),
            who[0],
            source_run_id=run_id,
        )
        run["follow_up_batch_id"] = batch["batch_id"]
        request.app.state.store.put_run(run)
        return {**batch, "source_run_id": run_id, "experiment_question": proposal["question"]}

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

    @app.post("/api/qa/runs/{run_id}/approval")
    async def simulation_approval(run_id: str, body: Decision, request: Request, who: User):
        if "APPROVER" not in who[1]:
            raise ApiError(403, "PERMISSION_DENIED")
        if get_run(request, run_id)["created_by"] == who[0]:
            raise ApiError(403, "SELF_APPROVAL_DENIED")
        return await runner(request).simulations.decide(run_id, body, who[0])

    @app.post("/simulations/{run_id}/mcp")
    async def simulation_mcp(
        run_id: str, request: Request, authorization: str | None = Header(default=None)
    ):
        raw = await request.body()
        if len(raw) > 100_000:
            raise ApiError(413, "REQUEST_TOO_LARGE")
        try:
            body = json.loads(raw)
        except ValueError:
            raise ApiError(400, "INVALID_JSON_RPC") from None
        result = await runner(request).simulations.rpc(run_id, authorization, body)
        return Response(status_code=202) if result is None else JSONResponse(result)

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

    @app.get("/internal/runs/{run_id}/simulation-state", dependencies=[Depends(internal)])
    async def internal_simulation_state(run_id: str, request: Request):
        """MCP_SPEC 4.4: the production/quality sandbox, read by Spring's investigation tools."""
        get_run(request, run_id)
        state = request.app.state.store.get_simulation(run_id)
        if state is None:
            raise ApiError(404, "SIMULATION_NOT_FOUND", f"run {run_id}")
        return investigation_state(run_id, state)

    return app


app = create_app()
