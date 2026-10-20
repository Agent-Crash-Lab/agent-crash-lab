"""Opt-in real Harness/Agent/MCP tests; existing runs and volumes are preserved."""

import asyncio
import json
import os
from contextlib import asynccontextmanager

import httpx
import pytest

HARNESS_URL = os.environ.get("HARNESS_INTEGRATION_URL", "").rstrip("/")
MCP_URL = os.environ.get("MCP_INTEGRATION_URL", "").rstrip("/")
pytestmark = [
    pytest.mark.asyncio,
    pytest.mark.skipif(
        not HARNESS_URL or not MCP_URL,
        reason="Set HARNESS_INTEGRATION_URL and MCP_INTEGRATION_URL for real service tests",
    ),
]


def checked(response, status=200):
    # Response bodies might contain credentials; do not include them in failures.
    assert response.status_code == status, (
        f"{response.request.url.path}: HTTP {response.status_code}"
    )
    return response.json()


@asynccontextmanager
async def clients():
    token = os.environ.get("INTERNAL_API_TOKEN")
    assert token, "Set INTERNAL_API_TOKEN to the shared service token"
    headers = {
        "X-Internal-Token": token,
        "X-User-Id": "requester-01",
        "X-User-Roles": "REQUESTER",
    }
    async with (
        httpx.AsyncClient(base_url=HARNESS_URL, headers=headers, timeout=30) as harness,
        httpx.AsyncClient(base_url=MCP_URL, timeout=30) as mcp,
    ):
        yield harness, mcp


async def wait_for(harness, run_id, *, approval=False):
    async with asyncio.timeout(90):
        while True:
            run = checked(await harness.get(f"/api/runs/{run_id}"))
            if run["status"] == "ERROR":
                pytest.fail(f"{run_id} ended with {run.get('status_reason')}")
            if approval and run["status"] == "WAITING_APPROVAL":
                return run
            if not approval and run["status"] == "COMPLETED":
                if run["investigation"]["status"] != "RUNNING":
                    return run
            await asyncio.sleep(0.2)


async def events(harness, run_id):
    streamed, ended = [], False
    async with (
        asyncio.timeout(20),
        harness.stream(
            "GET", f"/api/runs/{run_id}/events", headers={"Accept": "text/event-stream"}
        ) as response,
    ):
        assert response.status_code == 200
        kind = ""
        async for line in response.aiter_lines():
            if line.startswith("event: "):
                kind = line[7:]
            elif line.startswith("data: "):
                payload = json.loads(line[6:])
                if kind == "run_event":
                    streamed.append(payload)
                elif kind == "run_end":
                    assert payload == {"run_id": run_id, "status": "COMPLETED"}
                    ended = True
    assert ended
    data = checked(await harness.get(f"/api/runs/{run_id}/events", params={"limit": 1000}))
    assert not data["has_more"]
    stored = data["events"]
    assert stored == streamed
    assert all(event["run_id"] == run_id for event in stored)
    assert [event["sequence"] for event in stored] == list(range(1, len(stored) + 1))
    assert len({event["event_id"] for event in stored}) == len(stored)
    after = len(stored) // 2
    replay = checked(
        await harness.get(
            f"/api/runs/{run_id}/events", params={"after_sequence": after, "limit": 1000}
        )
    )
    assert replay["events"] == stored[after:]
    assert not replay["has_more"]
    return stored


def no_credentials(data, *secrets):
    if any(secret and secret in json.dumps(data) for secret in secrets):
        pytest.fail("A credential appeared in a public run or event response")
    forbidden = {"agent_token", "agent_tokens", "access_token", "api_key", "authorization"}

    def walk(value):
        if isinstance(value, dict):
            assert not forbidden.intersection(key.lower() for key in value)
            for item in value.values():
                walk(item)
        elif isinstance(value, list):
            for item in value:
                walk(item)

    walk(data)


@pytest.mark.parametrize("test_id", ["PA01", "PA02", "PA03", "IA01", "IA02", "IA03"])
async def test_real_harness_individual(test_id):
    async with clients() as (harness, _):
        created = checked(await harness.post("/api/runs", json={"test_id": test_id}), 202)
        run_id = created["run_id"]
        run = await wait_for(harness, run_id)
        assert run["checks"]
        assert all(check["verdict"] == "PASS" for check in run["checks"])
        if test_id.startswith("IA"):
            assert run["investigation"]["status"] == "READY"
            assert run["investigation"]["validation"] == {"passed": True, "errors": []}
        else:
            expected = "REJECTED" if test_id == "PA02" else "SUCCEEDED"
            assert run["agent"]["result"]["outcome"] == expected
        stored = await events(harness, run_id)
        ids = {event["event_id"] for event in stored}
        assert all(set(check["evidence_ids"]) <= ids for check in run["checks"])
        no_credentials([run, stored], os.environ["INTERNAL_API_TOKEN"])


@pytest.mark.parametrize("scenario", ["S01", "S02", "S03"])
async def test_real_harness_system(scenario):
    async with clients() as (harness, mcp):
        login = checked(
            await mcp.post(
                "/api/auth/login",
                json={
                    "user_id": "approver-01",
                    "password": os.environ.get("DEMO_USER_PASSWORD", "crashlab"),
                },
            )
        )
        user_token, runs = login["access_token"], []
        for system in ["B0", "B1"]:
            created = checked(
                await harness.post(
                    "/api/runs",
                    json={
                        "test_id": scenario,
                        "system_id": system,
                    },
                ),
                202,
            )
            run_id = created["run_id"]
            waiting = await wait_for(harness, run_id, approval=True)
            checked(await harness.post("/api/runs", json={"test_id": "PA01"}), 409)
            pending = waiting["approval_request"]
            decision = "REJECTED" if scenario == "S02" else "APPROVED"
            # Only MCP's real callback resumes the Agent; no direct Agent resume here.
            approval = checked(
                await mcp.post(
                    f"/api/runs/{run_id}/approval",
                    headers={"Authorization": f"Bearer {user_token}"},
                    json={
                        "approval_request_id": pending["approval_request_id"],
                        "decision": decision,
                        "payload_hash": pending["payload_hash"],
                    },
                )
            )
            # Repeat the Harness callback to verify idempotency.
            checked(
                await harness.post(
                    f"/internal/runs/{run_id}/resume",
                    json={
                        **approval,
                        "payload_hash": pending["payload_hash"],
                    },
                ),
                202,
            )
            run = await wait_for(harness, run_id)
            assert run["approval"]["approval_id"] == approval["approval_id"]
            assert run["approval"]["decision"] == decision
            assert run["agent"]["termination"] == "AGENT_FINISHED"
            assert run["agent"]["result"]["outcome"] == (
                "REJECTED" if scenario == "S02" else "SUCCEEDED"
            )
            assert run["snapshot_complete"] is True
            assert run["checks"]  # Oracle is now implemented on main.
            if any(c["verdict"] in {"FAIL", "INCONCLUSIVE"} for c in run["checks"]):
                assert run["investigation"]["status"] == "READY"
                assert run["investigation"]["validation"]["passed"] is True
            if scenario == "S03":
                assert run["fault"]["status"] == "APPLIED"
                assert run["fault"]["applied_count"] == 1
            stored = await events(harness, run_id)
            expected = 0 if scenario == "S02" else 2 if scenario == "S03" and system == "B0" else 1
            assert sum(e["event_type"] == "BUSINESS_COMMITTED" for e in stored) == expected
            assert {"harness", "agents", "mcp-server"} <= {e["producer"] for e in stored}
            no_credentials([run, stored], os.environ["INTERNAL_API_TOKEN"], user_token)
            runs.append(run_id)
        comparison = checked(
            await harness.get(
                "/api/comparisons",
                params={
                    "left": runs[0],
                    "right": runs[1],
                },
            )
        )
        assert comparison["actual"]["left"]["order_count"] == (
            0 if scenario == "S02" else 2 if scenario == "S03" else 1
        )
        assert comparison["actual"]["right"]["order_count"] == (0 if scenario == "S02" else 1)
        assert {item["field"] for item in comparison["changed"]} == {
            "system_id",
            "server_policy_version",
        }
