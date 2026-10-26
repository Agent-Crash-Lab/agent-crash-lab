"""Single-process local execution, durable approval waits, and bounded async work."""

import asyncio
import hashlib
import json
import sqlite3
import time
from contextlib import AsyncExitStack, nullcontext
from importlib.metadata import version

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.types import Command

from agents.config import redact
from agents.execution import Context, ExecutionLimit
from agents.llm import (
    ModelError,
    StructuredModel,
    inference_signature,
    resolve_model,
)
from agents.models import ApprovalDecision, InvestigationReport, PurchaseRequest
from agents.qa.investigation import PROMPT as INVESTIGATION_PROMPT
from agents.qa.investigation import FixtureReportModel, build_investigation_graph
from agents.store import Store
from agents.targets.reference_purchase import build_reference_target_graph
from agents.targets.reference_purchase_model import PROMPT as PURCHASE_PROMPT
from agents.targets.reference_purchase_model import PurchaseChoice
from agents.tools.mcp import McpTools
from agents.tools.mock import MockTools


class RunError(Exception):
    def __init__(self, status, code):
        self.status, self.code = status, code


class Runtime:
    def __init__(self, settings, model=None):
        self.settings = settings
        self.model = model or FixtureReportModel()
        root = settings.agent_project_root
        config = json.loads((root / "config/qa-runtime.json").read_text())
        self.policy = {
            **config["execution"],
            **config["approval"],
        }
        self.schemas = {}
        for reference in ["tool_contracts", "investigation_tools"]:
            for tool in json.loads((root / config["references"][reference]).read_text())["tools"]:
                self.schemas[tool["name"]] = tool["input_schema"]
        self.lock = asyncio.Lock()
        self.tasks = set()
        self.tokens = {}
        self.stack = AsyncExitStack()

    async def open(self):
        path = self.settings.agent_state_dir
        path.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.store = Store(path / "runs.sqlite")
        self.saver = await self.stack.enter_async_context(
            AsyncSqliteSaver.from_conn_string(str(path / "checkpoints.sqlite"))
        )
        await self.saver.setup()
        for run in self.store.active():
            if run["status"] in {"PREPARING", "RUNNING"}:
                self.store.fail(run["run_id"], "PROCESS_INTERRUPTED")
        self.expire()
        self.monitor = asyncio.create_task(self.watch())
        return self

    async def close(self):
        self.monitor.cancel()
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(self.monitor, *self.tasks, return_exceptions=True)
        await self.stack.aclose()
        self.store.db.close()

    def expire(self):
        now = time.time()
        for run in self.store.active():
            if run["status"] == "WAITING_APPROVAL":
                reason = None
                if now >= run["created_at"] + self.policy["max_total_run_seconds"]:
                    reason = "TOTAL_RUN_TIMEOUT"
                elif now >= run["approval_expires_at"]:
                    reason = "APPROVAL_WAIT_EXPIRED"
                if reason:
                    self.store.fail(run["run_id"], reason)

    async def watch(self):
        while True:
            await asyncio.sleep(0.2)
            async with self.lock:
                self.expire()

    def status(self, run_id):
        self.expire()
        run = self.store.get(run_id)
        if run is None:
            raise RunError(404, "RUN_NOT_FOUND")
        return run

    def secrets(self, token=""):
        return (
            self.settings.internal_api_token.get_secret_value(),
            self.settings.llm_api_key.get_secret_value(),
            token,
        )

    def reject_credentials(self, data, token=""):
        text = json.dumps(data)
        if any(secret and secret in text for secret in self.secrets(token)):
            raise RunError(422, "CREDENTIAL_IN_PAYLOAD")

    def launch(self, run_id, approval=None):
        task = asyncio.create_task(self.execute(run_id, approval))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def model_metadata(self, kind):
        live = self.settings.agent_model_mode == "openai"
        purchase = kind == "PURCHASE_AGENT"
        prompt = PURCHASE_PROMPT if purchase else INVESTIGATION_PROMPT
        model = None
        if live:
            if not self.settings.llm_api_key.get_secret_value():
                raise RunError(503, "LLM_KEY_NOT_CONFIGURED")
            selected = (
                self.settings.purchase_llm_model
                if purchase
                else self.settings.investigation_llm_model
            ) or self.settings.llm_model
            if not selected:
                raise RunError(503, "LLM_MODEL_NOT_CONFIGURED")
            try:
                model = resolve_model(selected)
            except ModelError as exc:
                raise RunError(503, str(exc)) from None
        return {
            "model_kind": "openai" if live else "deterministic" if purchase else "fixture",
            "model": model,
            "prompt_version": hashlib.sha256(
                (
                    prompt
                    + json.dumps(
                        (PurchaseChoice if purchase else InvestigationReport).model_json_schema(),
                        sort_keys=True,
                    )
                    + inference_signature(model)
                ).encode()
            ).hexdigest(),
            "agent_version": version("crashlab-agents"),
            "budget_stage": self.settings.llm_budget_stage if live else None,
        }

    async def start(self, body):
        async with self.lock:
            self.expire()
            if self.store.get(body.run_id):
                raise RunError(409, "RUN_EXISTS")
            if self.store.active():
                raise RunError(409, "AGENT_BUSY")
            token = body.agent_token.get_secret_value() if body.agent_token else ""
            public = body.model_dump(mode="json")
            self.reject_credentials(public, token)
            run = {
                **public,
                "fixture_id": body.fixture_id
                or ("purchase-normal" if body.mode == "mock" else None),
                "status": "PREPARING",
                "created_at": time.time(),
                "turns": 0,
                "tool_calls": 0,
                "active_seconds": 0,
                "result": None,
                **self.model_metadata(body.agent_kind),
            }
            try:
                self.store.put(run)
            except sqlite3.IntegrityError as exc:
                raise RunError(409, "AGENT_BUSY") from exc
            if token:
                self.tokens[body.run_id] = token
            self.store.event(body.run_id, "RUN_STARTED", {"mode": body.mode})
            self.launch(body.run_id)
            return run

    async def resume(self, run_id, body):
        async with self.lock:
            run = self.status(run_id)
            approval = ApprovalDecision.model_validate(body.model_dump(mode="json")).model_dump(
                mode="json"
            )
            token = body.agent_token.get_secret_value() if body.agent_token else ""
            self.reject_credentials(approval, token)
            previous = run.get("accepted_approval")
            if previous:
                if previous == approval:
                    return run
                raise RunError(409, "APPROVAL_ALREADY_HANDLED")
            if run["status"] != "WAITING_APPROVAL":
                raise RunError(409, "NOT_WAITING_APPROVAL")
            request = PurchaseRequest.model_validate(run["request"])
            if body.request_id != request.request_id or body.payload_hash != request.payload_hash():
                raise RunError(422, "APPROVAL_PAYLOAD_MISMATCH")
            if run["mode"] == "mcp" and not token:
                raise RunError(422, "AGENT_TOKEN_REQUIRED")
            expected = self.model_metadata(run["agent_kind"])
            if run.get("model") is not None and any(run.get(k) != v for k, v in expected.items()):
                raise RunError(409, "MODEL_CONFIGURATION_CHANGED")
            if run.get("model") is None and expected["model"] is not None:
                raise RunError(409, "MODEL_CONFIGURATION_CHANGED")
            run.update(status="RUNNING", accepted_approval=approval)
            self.store.put(run)
            if token:
                self.tokens[run_id] = token
            self.store.event(run_id, "AGENT_APPROVAL_RECEIVED", {"decision": body.decision})
            self.launch(run_id, approval)
            return run

    async def execute(self, run_id, approval):
        started = time.monotonic()
        run = self.store.get(run_id)
        run["status"] = "RUNNING"
        self.store.put(run)
        token = self.tokens.get(run_id, "")
        ctx = None
        try:
            remaining = min(
                self.policy["max_active_seconds_per_agent"] - run["active_seconds"],
                self.policy["max_total_run_seconds"] - (time.time() - run["created_at"]),
            )
            if remaining <= 0:
                raise ExecutionLimit("ACTIVE_OR_TOTAL_TIMEOUT")
            tools = (
                nullcontext(
                    MockTools(
                        self.settings.agent_project_root,
                        run["fixture_id"],
                        run.get("target_run_id"),
                    )
                )
                if run["mode"] == "mock"
                else McpTools(
                    str(self.settings.mcp_url), token, self.policy["tool_timeout_seconds"]
                )
            )
            async with asyncio.timeout(remaining), tools as connection:
                ctx = Context(
                    self.store, run_id, connection, self.policy, self.schemas, self.secrets(token)
                )
                config = {"configurable": {"thread_id": run_id}, "recursion_limit": 20}
                purchase = run["agent_kind"] == "PURCHASE_AGENT"
                model = None
                if run.get("model"):
                    model = StructuredModel(
                        self.settings,
                        ctx,
                        run["model"],
                        PurchaseChoice if purchase else InvestigationReport,
                    )
                if purchase:
                    graph = build_reference_target_graph(ctx, self.saver, model)
                    inputs = Command(resume=approval) if approval else {"request": run["request"]}
                else:
                    graph = build_investigation_graph(ctx, self.saver, model or self.model)
                    inputs = {"target_run_id": run["target_run_id"]}
                await graph.ainvoke(inputs, config)
                state = await graph.aget_state(config)
                run = self.store.get(run_id)
                if state.next == ("approval",):
                    request = PurchaseRequest.model_validate(run["request"])
                    run.update(
                        status="WAITING_APPROVAL",
                        payload_hash=request.payload_hash(),
                        approval_expires_at=time.time() + self.policy["wait_timeout_seconds"],
                    )
                    event_type = "AGENT_WAITING_APPROVAL"
                    event_payload = {"payload_hash": run["payload_hash"]}
                else:
                    run.update(
                        status="COMPLETED",
                        result=redact(state.values["result"], self.secrets(token)),
                        finished_at=time.time(),
                    )
                    event_type = "RUN_FINISHED"
                    event_payload = {"status": "COMPLETED"}
                self.store.put(run)
                ctx.event(event_type, event_payload)
        except asyncio.CancelledError:
            self.store.fail(run_id, "PROCESS_INTERRUPTED")
            raise
        except TimeoutError:
            self.store.fail(run_id, "ACTIVE_OR_TOTAL_TIMEOUT")
        except ModelError as exc:
            self.store.fail(run_id, str(exc))
        except ExecutionLimit as exc:
            self.store.fail(run_id, str(exc))
        except Exception:
            # Raw external errors may contain credentials. Keep only a safe reason.
            if self.store.get(run_id)["status"] != "COMPLETED":
                self.store.fail(run_id, "AGENT_EXECUTION_ERROR")
        finally:
            run = self.store.get(run_id)
            run["active_seconds"] += time.monotonic() - started
            self.store.put(run)
            self.tokens.pop(run_id, None)
