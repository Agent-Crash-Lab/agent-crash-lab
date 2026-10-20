"""Agent-local call budgets and observations; this is not the Harness Runner."""

import asyncio
import json
from uuid import uuid4

from jsonschema import validate

from agents.config import redact
from agents.tools.business import ToolError
from agents.tools.mcp import INVESTIGATION_TOOLS, PURCHASE_TOOLS


class ExecutionLimit(Exception):
    pass


class Context:
    def __init__(self, store, run_id, tools, policy, schemas, secrets=()):
        self.store, self.run_id, self.tools = store, run_id, tools
        self.policy, self.schemas, self.secrets = policy, schemas, secrets

    @property
    def tool_wait_seconds(self):
        mode = self.store.get(self.run_id)["mode"]
        key = "agent_tool_wait_seconds" if mode == "mcp" else "tool_timeout_seconds"
        return self.policy[key]

    def event(self, kind, payload=None):
        self.store.event(self.run_id, kind, redact(payload or {}, self.secrets))

    def step(self, name):
        run = self.store.get(self.run_id)
        if run["turns"] >= self.policy["max_agent_turns"]:
            raise ExecutionLimit("TURN_LIMIT")
        run["turns"] += 1
        self.store.put(run)
        self.event("AGENT_STEP", {"node": name})

    def count(self, name, arguments):
        run = self.store.get(self.run_id)
        if run["tool_calls"] >= self.policy["max_tool_calls"]:
            raise ExecutionLimit("TOOL_CALL_LIMIT")
        run["tool_calls"] += 1
        if name == "create_purchase_order":
            if (
                run.get("write_attempts", 0)
                >= 1 + self.policy["write_retries_after_ambiguous_error"]
            ):
                raise ExecutionLimit("WRITE_CALL_LIMIT")
            run["write_started"] = True
            run["write_attempts"] = run.get("write_attempts", 0) + 1
        self.store.put(run)
        call_id = str(uuid4())
        self.event(
            "AGENT_TOOL_CALLED",
            {
                "agent_call_id": call_id,
                "tool": name,
                "arguments": arguments,
            },
        )
        return call_id

    async def call(self, name, arguments):
        run = self.store.get(self.run_id)
        allowed = PURCHASE_TOOLS if run["agent_kind"] == "PURCHASE_AGENT" else INVESTIGATION_TOOLS
        if name not in allowed:
            raise ToolError("PERMISSION_DENIED")
        validate(arguments, self.schemas[name])
        write = name == "create_purchase_order"
        retries = self.policy[
            "write_retries_after_ambiguous_error" if write else "read_retries_after_transient_error"
        ]
        for attempt in range(retries + 1):
            call_id = self.count(name, arguments)
            try:
                async with asyncio.timeout(self.tool_wait_seconds):
                    data = await self.tools.call(name, arguments)
                if not isinstance(data, dict) or len(json.dumps(data)) > 64000:
                    raise ToolError("INVALID_RESPONSE")
                self.event("AGENT_TOOL_RESPONDED", {"agent_call_id": call_id, "status": "OK"})
                return redact(data, self.secrets)
            except TimeoutError:
                error = ToolError("TOOL_TIMEOUT", retryable=True)
            except ToolError as exc:
                error = exc
            except Exception:
                error = ToolError("ADAPTER_ERROR")
            ambiguous = error.code in {"TOOL_TIMEOUT", "INTERNAL_ERROR", "TRANSPORT_ERROR"}
            if write and ambiguous:
                run = self.store.get(self.run_id)
                run["write_ambiguous"] = True
                self.store.put(run)
            self.event(
                "AGENT_TOOL_RESPONDED",
                {
                    "agent_call_id": call_id,
                    "status": "ERROR",
                    "code": error.code,
                },
            )
            if not (error.retryable and ambiguous and attempt < retries):
                raise error

    async def resource(self, uri):
        run = self.store.get(self.run_id)
        if run["agent_kind"] != "INVESTIGATION_AGENT" or not uri.startswith("guide://"):
            raise ToolError("PERMISSION_DENIED")
        for attempt in range(self.policy["read_retries_after_transient_error"] + 1):
            call_id = self.count("read_resource", {"uri": uri})
            try:
                async with asyncio.timeout(self.tool_wait_seconds):
                    text = await self.tools.resource(uri)
                if not isinstance(text, str) or len(text) > 64000:
                    raise ToolError("INVALID_RESPONSE")
                self.event("AGENT_TOOL_RESPONDED", {"agent_call_id": call_id, "status": "OK"})
                return redact(text, self.secrets)
            except TimeoutError:
                error = ToolError("TOOL_TIMEOUT", retryable=True)
            except ToolError as exc:
                error = exc
            except Exception:
                error = ToolError("ADAPTER_ERROR")
            self.event(
                "AGENT_TOOL_RESPONDED",
                {
                    "agent_call_id": call_id,
                    "status": "ERROR",
                    "code": error.code,
                },
            )
            if not (
                error.retryable
                and error.code in {"TOOL_TIMEOUT", "INTERNAL_ERROR", "TRANSPORT_ERROR"}
                and attempt < self.policy["read_retries_after_transient_error"]
            ):
                raise error
