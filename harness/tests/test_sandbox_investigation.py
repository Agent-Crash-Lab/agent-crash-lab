"""Production/quality runs: a non-PASS verdict registers the run with Spring (MCP_SPEC 3.6)
and runs the investigation Agent on Spring's rag-mcp, which reads the sandbox through
MCP_SPEC 4.4. Without a report the code summary stays."""

import asyncio
import time

import pytest
from conftest import GATEWAY, TOKEN
from test_manufacturing import configure_reference, run_case, runtime  # noqa: F401

from harness.clients import ClientError
from harness.simulation import investigation_state


class SpringInvestigation:
    """Stands in for mcp-server's POST /internal/investigation-runs."""

    def __init__(self, fail=False):
        self.fail, self.registered = fail, []

    async def register_investigation(self, body):
        self.registered.append(body)
        if self.fail:
            raise ClientError("mcp-server", 503, "INTERNAL_ERROR")
        return {
            "run_id": body["run_id"],
            "agent_type": body["agent_type"],
            "agent_tokens": {"investigation_agent": "IA-SANDBOX-TOKEN"},
        }


class Investigator:
    """Plays the investigation Agent reading Spring's view of the Harness sandbox (4.4)."""

    def __init__(self, runner, fail=False):
        # run_case waits ~0.3 s; poll the Agent faster than the 0.5 s default.
        runner.settings.poll_interval_seconds = 0.005
        self.runner, self.fail = runner, fail
        self.started, self.runs = [], {}

    async def start(self, body):
        self.started.append(body)
        run = {**body, "status": "RUNNING", "created_at": time.time(), "result": None}
        run.pop("agent_token")
        self.runs[body["run_id"]] = run
        asyncio.create_task(self.work(run))
        return run

    async def work(self, run):
        if self.fail:
            run["status"] = "ERROR"
            return
        target = run["target_run_id"]
        state = investigation_state(target, self.runner.store.get_simulation(target))
        run.update(
            status="COMPLETED",
            result={
                "target_run_id": target,
                "facts": [
                    {
                        "text": f"저장된 업무 변경은 {len(state['changes'])}건입니다.",
                        "evidence_ids": state["snapshot_evidence_ids"]
                        + state["commit_evidence_ids"],
                    }
                ],
                "cause_candidates": ["응답 유실 뒤 같은 변경을 다시 시도했습니다."],
                "missing_evidence": [],
                "improvements": [],
                "retest_scenario_ids": [],
            },
        )

    async def status(self, run_id):
        return self.runs[run_id]

    async def events(self, run_id, after):
        return []


@pytest.mark.parametrize("kind", ["PRODUCTION", "QUALITY"])
async def test_failed_sandbox_run_is_investigated_through_spring(runtime, kind):  # noqa: F811
    configure_reference(runtime)
    runtime.mcp, runtime.agents = SpringInvestigation(), Investigator(runtime)
    run = await run_case(runtime, kind, "POST_COMMIT_RESPONSE_LOSS", "B0")
    assert run["summary"]["FAIL"] >= 1

    assert runtime.mcp.registered == [
        {
            "run_id": run["run_id"],
            "agent_type": kind,
            "scenario_id": run["test_id"],
            "requested_by": "requester",
        }
    ]
    body = runtime.agents.started[0]
    assert body["agent_kind"] == "INVESTIGATION_AGENT" and body["mode"] == "mcp"
    assert body["target_run_id"] == run["run_id"]
    assert body["agent_token"] == "IA-SANDBOX-TOKEN"
    assert "mcp_url" not in body  # Spring's rag-mcp, as for purchase runs

    investigation = run["investigation"]
    assert investigation["status"] == "READY"
    assert investigation["method"] == "INVESTIGATION_AGENT"
    assert investigation["validation"] == {"passed": True, "errors": []}
    assert investigation["report"]["facts"][0]["text"] == "저장된 업무 변경은 2건입니다."
    assert "IA-SANDBOX-TOKEN" not in str(runtime.store.get_run(run["run_id"]))


@pytest.mark.parametrize("failure", ["registration", "agent"])
async def test_investigation_failure_keeps_the_code_summary(runtime, failure):  # noqa: F811
    configure_reference(runtime)
    runtime.mcp = SpringInvestigation(fail=failure == "registration")
    runtime.agents = Investigator(runtime, fail=failure == "agent")
    run = await run_case(runtime, "QUALITY", "POST_COMMIT_RESPONSE_LOSS", "B0")
    investigation = run["investigation"]
    assert investigation["status"] == "READY"
    assert investigation["method"] == "CODE_EVIDENCE_SUMMARY"
    assert investigation["agent_status"] == "ERROR"
    assert investigation["validation"]["passed"] and investigation["report"]["facts"]
    # Without a Spring token the Agent is never started.
    assert len(runtime.agents.started) == (0 if failure == "registration" else 1)


async def test_passing_sandbox_run_does_not_investigate(runtime):  # noqa: F811
    configure_reference(runtime)
    runtime.mcp, runtime.agents = SpringInvestigation(), Investigator(runtime)
    run = await run_case(runtime, "QUALITY", "POST_COMMIT_RESPONSE_LOSS", "B1")
    assert run["summary"]["FAIL"] == run["summary"]["INCONCLUSIVE"] == 0
    assert runtime.mcp.registered == [] and runtime.agents.started == []
    assert run["investigation"]["status"] == "NOT_REQUESTED"


def test_simulation_state_matches_mcp_spec_4_4(client):
    store = client.app.state.store
    store.put_run(
        {"run_id": "RUN-SIM", "status": "COMPLETED", "created_at": "2026-10-23T00:00:00Z"}
    )
    store.put_simulation(
        "RUN-SIM",
        {
            "kind": "PRODUCTION",
            "initial_state": {"machine_status": "READY"},
            "current_state": {"machine_status": "MAINTENANCE"},
            "request": {"machine_id": "M-1"},
            "changes": [
                {
                    "evidence_id": "COMMIT-RUN-SIM-1",
                    "payload": {"machine_id": "M-1"},
                    "approval": {"decision": "APPROVED"},
                    "domain_errors": ["MACHINE_MAINTENANCE"],
                }
            ],
            "calls": [
                {
                    "evidence_id": "CALL-RUN-SIM-1",
                    "name": "assign_operation",
                    "effect": "WRITE",
                    "arguments": {"machine_id": "M-1"},
                    "result": {"code": "TOOL_TIMEOUT"},
                }
            ],
            "approval": {"decision": "APPROVED"},
            "closed": True,
            "snapshot_evidence_id": "SNAP-RUN-SIM",
        },
    )
    internal = {"X-Internal-Token": TOKEN}
    assert client.get("/internal/runs/RUN-SIM/simulation-state").status_code == 401
    assert client.get("/internal/runs/RUN-SIM/simulation-state", headers=GATEWAY).status_code == 200
    state = client.get("/internal/runs/RUN-SIM/simulation-state", headers=internal).json()
    assert state["run_id"] == "RUN-SIM" and state["agent_type"] == "PRODUCTION"
    assert state["snapshot_complete"] and state["snapshot_evidence_ids"] == ["SNAP-RUN-SIM"]
    assert state["current_state"] == {"machine_status": "MAINTENANCE"}
    assert state["changes"][0]["evidence_ids"] == ["COMMIT-RUN-SIM-1"]
    assert state["tool_calls"] == [
        {
            "tool": "assign_operation",
            "arguments": {"machine_id": "M-1"},
            "effect": "WRITE",
            "evidence_ids": ["CALL-RUN-SIM-1"],
            "is_error": True,
            "error_code": "TOOL_TIMEOUT",
        }
    ]
    store.put_run({"run_id": "RUN-PUR", "status": "COMPLETED", "created_at": "2026-10-23"})
    missing = client.get("/internal/runs/RUN-PUR/simulation-state", headers=internal)
    assert missing.status_code == 404
    assert (
        client.get("/internal/runs/RUN-NONE/simulation-state", headers=internal).status_code == 404
    )
