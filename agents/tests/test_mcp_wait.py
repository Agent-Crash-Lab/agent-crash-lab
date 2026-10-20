"""The Agent must receive MCP's own timeout before applying its transport deadline."""

import asyncio

import pytest
from conftest import approval, purchase, settled

import agents.runtime as runtime_module
from agents.models import StartRequest
from agents.tools.business import ToolError
from agents.tools.mock import MockTools


@pytest.mark.asyncio
async def test_server_timeout_reaches_agent_before_local_deadline(runtime, monkeypatch):
    assert runtime.policy["tool_timeout_seconds"] == 10
    assert runtime.policy["agent_tool_wait_seconds"] == 12
    runtime.policy["tool_timeout_seconds"] = 0.005
    runtime.policy["agent_tool_wait_seconds"] = 0.1
    attempts = []

    class Transport:
        def __init__(self, url, token, timeout):
            assert timeout == 0.1
            self.mock = MockTools(runtime.settings.agent_project_root, "purchase-normal")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def call(self, name, arguments):
            await asyncio.sleep(0.02)
            if name == "create_purchase_order":
                attempts.append(arguments)
                if len(attempts) == 1:
                    raise ToolError("TOOL_TIMEOUT", retryable=True)
            return await self.mock.call(name, arguments)

    monkeypatch.setattr(runtime_module, "McpTools", Transport)
    body = StartRequest(
        run_id="MCP-WAIT", request=purchase().request, mode="mcp", agent_token="test-token"
    )
    await runtime.start(body)
    waiting = await settled(runtime, body.run_id)
    assert waiting["status"] == "WAITING_APPROVAL"
    assert waiting["tool_calls"] == 2
    await runtime.resume(body.run_id, approval(body, agent_token="test-token"))
    done = await settled(runtime, body.run_id)
    assert done["result"]["outcome"] == "SUCCEEDED"
    assert len(attempts) == 2 and attempts[0] == attempts[1]


@pytest.mark.asyncio
async def test_mcp_wait_still_stops_unresponsive_calls(runtime, monkeypatch):
    runtime.policy["agent_tool_wait_seconds"] = 0.005
    attempts = []

    class Transport:
        def __init__(self, *args):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def call(self, name, arguments):
            attempts.append(name)
            await asyncio.sleep(1)

    monkeypatch.setattr(runtime_module, "McpTools", Transport)
    body = StartRequest(
        run_id="MCP-NO-REPLY", request=purchase().request, mode="mcp", agent_token="test-token"
    )
    await runtime.start(body)
    done = await settled(runtime, body.run_id)
    assert done["result"]["outcome"] == "FAILED"
    assert attempts == ["get_inventory", "get_inventory"]
    assert not done.get("write_started")
