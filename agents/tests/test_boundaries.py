import asyncio
import json
from contextlib import asynccontextmanager
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import ROOT, TOKEN, approval, purchase, settled
from pydantic import SecretStr

import agents.runtime as runtime_module
import agents.tools.mcp as mcp_module
from agents.models import StartRequest
from agents.runtime import RunError, Runtime
from agents.tools.errors import ToolError
from agents.tools.mcp import McpTools
from agents.tools.mock import MockTools


@pytest.mark.asyncio
async def test_mcp_handshake_headers_and_request(monkeypatch):
    recorded = {}
    session = SimpleNamespace(
        initialize=AsyncMock(),
        call_tool=AsyncMock(
            return_value=SimpleNamespace(
                content=[SimpleNamespace(text='{"request_id":"REQ-1","orders":[]}')], isError=False
            )
        ),
    )

    @asynccontextmanager
    async def transport(url, **kwargs):
        recorded.update(url=url, **kwargs)
        yield ("read", "write", lambda: "session-id")

    @asynccontextmanager
    async def client(read, write, **kwargs):
        assert (read, write) == ("read", "write")
        yield session

    monkeypatch.setattr(mcp_module, "streamablehttp_client", transport)
    monkeypatch.setattr(mcp_module, "ClientSession", client)
    async with McpTools("http://mcp-server:8081/mcp", "test-bearer", 10) as tools:
        assert (await tools.call("get_order_by_request", {"request_id": "REQ-1"}))["orders"] == []
    assert recorded["headers"] == {"Authorization": "Bearer test-bearer"}
    assert recorded["timeout"] == recorded["sse_read_timeout"] == 10
    session.initialize.assert_awaited_once()
    session.call_tool.assert_awaited_once_with("get_order_by_request", {"request_id": "REQ-1"})


@pytest.mark.asyncio
async def test_read_timeout_retries_once(runtime, monkeypatch):
    original = MockTools.call
    attempts = []

    async def call(self, name, arguments):
        if name == "get_inventory":
            attempts.append(name)
            await asyncio.sleep(0.03)
        return await original(self, name, arguments)

    runtime.policy["tool_timeout_seconds"] = 0.005
    monkeypatch.setattr(MockTools, "call", call)
    body = purchase()
    await runtime.start(body)
    done = await settled(runtime, body.run_id)
    assert done["result"]["outcome"] == "FAILED" and len(attempts) == 2
    assert not done.get("write_started")


@pytest.mark.asyncio
async def test_active_timeout_cancels_call(runtime, monkeypatch):
    original = MockTools.call

    async def call(self, name, arguments):
        await asyncio.sleep(0.1)
        return await original(self, name, arguments)

    runtime.policy["max_active_seconds_per_agent"] = 0.01
    monkeypatch.setattr(MockTools, "call", call)
    body = purchase()
    await runtime.start(body)
    done = await settled(runtime, body.run_id)
    assert done["status"] == "ERROR" and done["reason"] == "ACTIVE_OR_TOTAL_TIMEOUT"
    assert not done.get("write_started")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("tool", "change", "expected"),
    [
        ("get_inventory", {"available_quantity": 100}, "NEEDS_INPUT"),
        ("get_inventory", {"available_quantity": "20"}, "FAILED"),
        ("get_supplier", {"status": "INACTIVE"}, "FAILED"),
        ("create_purchase_order", {"order_id": ""}, "UNKNOWN"),
        ("create_purchase_order", {"committed_version": 2}, "UNKNOWN"),
    ],
)
async def test_bad_replies_and_sufficient_stock(runtime, monkeypatch, tool, change, expected):
    original = MockTools.call

    async def call(self, name, arguments):
        result = await original(self, name, arguments)
        return {**result, **change} if name == tool else result

    monkeypatch.setattr(MockTools, "call", call)
    body = purchase()
    await runtime.start(body)
    done = await settled(runtime, body.run_id)
    if done["status"] == "WAITING_APPROVAL":
        await runtime.resume(body.run_id, approval(body))
        done = await settled(runtime, body.run_id)
    assert done["result"]["outcome"] == expected


@pytest.mark.asyncio
async def test_no_credentials_in_checkpoints_events_or_api_state(settings, monkeypatch):
    agent_secret = "private-agent-token-for-test-only"
    settings.llm_api_key = SecretStr("private-llm-key-for-test-only")

    class Transport:
        def __init__(self, url, token, timeout):
            assert token == agent_secret
            self.mock = MockTools(settings.agent_project_root, "ia01-v1", "TARGET-SECRET-TEST")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def call(self, name, arguments):
            data = await self.mock.call(name, arguments)
            data["debug"] = {"agent_token": agent_secret, "message": agent_secret + TOKEN}
            return data

        async def resource(self, uri):
            return await self.mock.resource(uri) + agent_secret

    monkeypatch.setattr(runtime_module, "McpTools", Transport)
    runtime = await Runtime(settings).open()
    try:
        body = StartRequest(
            run_id="INV-SECRET",
            agent_kind="INVESTIGATION_AGENT",
            mode="mcp",
            target_run_id="TARGET-SECRET-TEST",
            agent_token=agent_secret,
        )
        await runtime.start(body)
        done = await settled(runtime, body.run_id)
        assert done["status"] == "COMPLETED"
        assert not runtime.tokens
        assert "agent_token" not in str(done)
    finally:
        await runtime.close()
    for file in settings.agent_state_dir.iterdir():
        data = file.read_bytes()
        for value in [agent_secret, TOKEN, settings.llm_api_key.get_secret_value()]:
            assert value.encode() not in data


@pytest.mark.asyncio
async def test_external_exception_secret_does_not_reach_checkpoint(runtime, monkeypatch):
    original = MockTools.call
    secret = runtime.settings.internal_api_token.get_secret_value()

    async def call(self, name, arguments):
        if name == "create_purchase_order":
            raise RuntimeError("Adapter failed with credential " + secret)
        return await original(self, name, arguments)

    monkeypatch.setattr(MockTools, "call", call)
    body = purchase()
    await runtime.start(body)
    await settled(runtime, body.run_id)
    await runtime.resume(body.run_id, approval(body))
    done = await settled(runtime, body.run_id)
    assert done["result"]["outcome"] == "UNKNOWN"
    for file in runtime.settings.agent_state_dir.iterdir():
        assert secret.encode() not in file.read_bytes()


@pytest.mark.asyncio
async def test_live_resume_requires_fresh_token(runtime, monkeypatch):
    class Transport:
        def __init__(self, *args):
            self.mock = MockTools(runtime.settings.agent_project_root, "purchase-normal")

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

        async def call(self, name, arguments):
            return await self.mock.call(name, arguments)

    monkeypatch.setattr(runtime_module, "McpTools", Transport)
    body = StartRequest(
        run_id="LIVE", request=purchase().request, mode="mcp", agent_token="fresh-token"
    )
    await runtime.start(body)
    assert (await settled(runtime, body.run_id))["status"] == "WAITING_APPROVAL"
    assert not runtime.tokens
    with pytest.raises(RunError) as error:
        await runtime.resume(body.run_id, approval(body))
    assert error.value.code == "AGENT_TOKEN_REQUIRED"
    await runtime.resume(body.run_id, approval(body, agent_token="fresh-token"))
    assert (await settled(runtime, body.run_id))["result"]["outcome"] == "SUCCEEDED"


@pytest.mark.asyncio
async def test_mock_uses_configured_business_state_and_rejects_unknown_entities(tmp_path):
    data = json.loads((ROOT / "qa/examples/targets/agents.json").read_text())
    seed = data["agents"]["PURCHASE"]["sample_data"]["initial_state"]
    seed["parts"][0]["inventory"] = 150
    seed["suppliers"][0]["unit_price_minor"] = 15000
    file = tmp_path / "qa/examples/targets/agents.json"
    file.parent.mkdir(parents=True)
    file.write_text(json.dumps(data))
    tools = MockTools(tmp_path, "purchase-normal")
    inventory = await tools.call("get_inventory", {"part_id": "PART-A", "plant_id": "PLANT-A"})
    supplier = await tools.call("get_supplier", {"supplier_id": "SUP-01"})
    assert inventory["available_quantity"] == 150
    assert supplier["unit_price_minor"] == 15000
    for tool, args in [
        ("get_inventory", {"part_id": "UNKNOWN", "plant_id": "PLANT-A"}),
        ("get_supplier", {"supplier_id": "UNKNOWN"}),
    ]:
        with pytest.raises(ToolError) as error:
            await tools.call(tool, args)
        assert error.value.code == "VALIDATION_ERROR"
