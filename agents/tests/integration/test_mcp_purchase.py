"""Opt-in tests against a real MCP server/PostgreSQL; no Harness or LLM required."""

import asyncio
import json
import os
from contextlib import nullcontext
from uuid import uuid4

import httpx
import pytest
from conftest import ROOT

from agents.config import Settings
from agents.models import PurchaseRequest
from agents.server import create_app

MCP_URL = os.environ.get("MCP_INTEGRATION_URL", "").rstrip("/")
AGENT_URL = os.environ.get("AGENT_INTEGRATION_URL", "").rstrip("/")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(not MCP_URL, reason="Set MCP_INTEGRATION_URL to opt into real MCP tests"),
]


async def settled(client, run_id):
    async with asyncio.timeout(45):
        while True:
            response = await client.get(f"/internal/agent-runs/{run_id}")
            assert response.status_code == 200
            run = response.json()
            if run["status"] not in {"PREPARING", "RUNNING"}:
                return run
            await asyncio.sleep(0.05)


@pytest.mark.parametrize("policy", ["baseline-v1", "idempotent-v1"])
@pytest.mark.parametrize("scenario", ["S01", "S02", "S03"])
async def test_real_mcp_purchase(tmp_path, policy, scenario):
    token = os.environ.get("INTERNAL_API_TOKEN")
    assert token, "Set INTERNAL_API_TOKEN to match the MCP server"
    run_id = f"AGENT-IT-{scenario}-{uuid4().hex}"
    faults = (
        [
            {
                "fault_id": "F-RESPONSE-LOSS",
                "tool_name": "create_purchase_order",
                "trigger": "AFTER_FIRST_SUCCESSFUL_COMMIT_BEFORE_RESPONSE",
                "max_applied_count": 1,
                "target_error_code": "TOOL_TIMEOUT",
            }
        ]
        if scenario == "S03"
        else []
    )
    settings = Settings(
        _env_file=None,
        mcp_url=f"{MCP_URL}/mcp",
        internal_api_token=token,
        agent_state_dir=tmp_path,
        agent_project_root=ROOT,
    )
    app = None if AGENT_URL else create_app(settings)
    headers = {"X-Internal-Token": token}
    async with (
        httpx.AsyncClient(base_url=MCP_URL, headers=headers, timeout=40) as mcp,
        app.router.lifespan_context(app) if app else nullcontext(),
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app) if app else None,
            base_url=AGENT_URL or "http://agents",
            headers=headers,
        ) as agent,
    ):
        initialized = await mcp.post(
            "/internal/sandbox/runs",
            json={
                "run_id": run_id,
                "scenario_id": scenario,
                "server_policy_version": policy,
                "fixture_id": "fixture-v1",
                "requested_by": "requester-01",
                "faults": faults,
            },
        )
        assert initialized.status_code == 201
        setup = initialized.json()
        agent_token = setup["agent_tokens"]["purchase_agent"]
        request = PurchaseRequest.model_validate(setup["request"])
        started = await agent.post(
            "/internal/agent-runs",
            json={
                "run_id": run_id,
                "mode": "mcp",
                "request": request.model_dump(),
                "agent_token": agent_token,
            },
        )
        assert started.status_code == 202
        waiting = await settled(agent, run_id)
        assert waiting["status"] == "WAITING_APPROVAL"
        assert waiting["tool_calls"] == 2
        assert waiting["payload_hash"] == request.payload_hash()

        pending = await mcp.post(
            f"/internal/sandbox/runs/{run_id}/approval-requests",
            json={"request": request.model_dump()},
        )
        assert pending.status_code == 201
        login = await mcp.post(
            "/api/auth/login",
            json={
                "user_id": "approver-01",
                "password": os.environ.get("DEMO_USER_PASSWORD", "crashlab"),
            },
        )
        assert login.status_code == 200
        user_token = login.json()["access_token"]
        decision = "REJECTED" if scenario == "S02" else "APPROVED"
        decided = await mcp.post(
            f"/api/runs/{run_id}/approval",
            headers={"Authorization": f"Bearer {user_token}"},
            json={
                "approval_request_id": pending.json()["approval_request_id"],
                "decision": decision,
                "payload_hash": waiting["payload_hash"],
            },
        )
        # This run is not registered with Harness. New MCP versions report a saved
        # decision plus callback failure; forward only that confirmed decision.
        if decided.status_code == 503:
            error = decided.json()["error"]
            assert error["code"] == "HARNESS_RESUME_FAILED"
            assert error["details"]["decision_saved"] is True
            decision_body = error["details"]["approval"]
        else:
            assert decided.status_code == 200
            decision_body = decided.json()
        resume = {
            **decision_body,
            "payload_hash": waiting["payload_hash"],
            "agent_token": agent_token,
        }
        resumed = await agent.post(f"/internal/agent-runs/{run_id}/resume", json=resume)
        assert resumed.status_code == 202
        done = await settled(agent, run_id)
        assert done["status"] == "COMPLETED"
        assert done["result"]["outcome"] == ("REJECTED" if scenario == "S02" else "SUCCEEDED")
        duplicate = await agent.post(f"/internal/agent-runs/{run_id}/resume", json=resume)
        assert duplicate.status_code == 202

        final = await mcp.post(f"/internal/sandbox/runs/{run_id}/finalize", json={"wait_ms": 5000})
        assert final.status_code == 200
        observation = final.json()
        assert observation["snapshot_complete"] is True
        expected = (
            0 if scenario == "S02" else 2 if scenario == "S03" and policy == "baseline-v1" else 1
        )
        assert len(observation["orders"]) == expected
        assert len(observation["commit_evidence_ids"]) == expected
        assert all(order["payload"] == request.model_dump() for order in observation["orders"])
        assert done["tool_calls"] == (2 if scenario == "S02" else 4 if scenario == "S03" else 3)
        fault_state = await mcp.get(f"/internal/sandbox/runs/{run_id}/faults")
        assert fault_state.status_code == 200
        if scenario == "S03":
            assert fault_state.json()["faults"][0]["applied_count"] == 1
        events = await agent.get(f"/internal/agent-runs/{run_id}/events")
        saved = b"".join(file.read_bytes() for file in tmp_path.iterdir())
        returned = json.dumps(done) + events.text
        if any(
            secret in returned or secret.encode() in saved
            for secret in (token, agent_token, user_token)
        ):
            pytest.fail("A credential was returned or persisted")
