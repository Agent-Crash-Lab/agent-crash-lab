import pytest
from conftest import TOKEN, done, wait_for

from harness import oracle

INTERNAL = {"X-Internal-Token": TOKEN}


def start(client, test_id, system_id=None):
    body = {"test_id": test_id, **({"system_id": system_id} if system_id else {})}
    response = client.post("/api/runs", json=body)
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def approve(client, run_id, decision="APPROVED", approval_id="AP-001"):
    run = wait_for(client, run_id, lambda r: r["status"] == "WAITING_APPROVAL")
    body = {
        "approval_id": approval_id,
        "request_id": run["request"]["request_id"],
        "decision": decision,
        "approver_id": "approver-01",
        "decided_at": "2026-10-20T00:01:00Z",
        "payload_hash": run["approval_request"]["payload_hash"],
    }
    response = client.post(f"/internal/runs/{run_id}/resume", json=body, headers=INTERNAL)
    assert response.status_code == 202, response.text
    return body


def verdicts(run):
    return {c["rule_id"]: c["verdict"] for c in run["checks"]}


def test_scenarios_lists_system_and_unit_tests(client):
    data = client.get("/api/scenarios").json()
    ids = [t["test_id"] for t in data["tests"]]
    assert ids == ["S01", "S02", "S03", "PA01", "PA02", "PA03", "IA01", "IA02", "IA03"]
    s02 = next(t for t in data["tests"] if t["test_id"] == "S02")
    assert s02["expected_approval"] == "REJECTED"
    assert {"rule_id": "R05", "name": "거절 이후 생성 시도 없음", "scopes": ["agent_behavior"]} in (
        s02["rules"]
    )
    assert {s["system_id"] for s in data["systems"]} == {"B0", "B1"}


@pytest.mark.parametrize("test_id", ["PA01", "PA02", "PA03"])
def test_purchase_unit_tests_pass(client, fakes, test_id):
    run_id = start(client, test_id)
    run = wait_for(client, run_id, done)
    assert run["status"] == "COMPLETED", run
    assert run["checks"] and all(c["verdict"] == "PASS" for c in run["checks"]), run["checks"]
    assert run["manifest"]["agent_mode"] == "mock"
    _, agent = fakes
    assert agent.runs[run_id]["mode"] == "mock"
    assert "agent_token" not in agent.runs[run_id]
    # Every check cites stored events.
    stored = {e["event_id"] for e in client.get(f"/api/runs/{run_id}/events").json()["events"]}
    assert all(set(c["evidence_ids"]) <= stored for c in run["checks"])


def test_pa03_counts_retry(client):
    run_id = start(client, "PA03")
    run = wait_for(client, run_id, done)
    reasons = {c["rule_id"]: c["reason"] for c in run["checks"]}
    assert "2건" in reasons["PA03-R2"]


def test_investigation_unit_test_validates_fixture_evidence(client):
    run_id = start(client, "IA01")
    run = wait_for(client, run_id, done)
    assert run["status"] == "COMPLETED"
    assert run["investigation"]["validation"] == {"passed": True, "errors": []}
    assert verdicts(run) == {"IA01-R1": "PASS", "IA01-R2": "PASS", "IA01-R3": "PASS", "R10": "PASS"}


def test_investigation_unknown_evidence_fails(client, fakes):
    fakes[1].report_evidence = ["NOT-REAL"]
    run_id = start(client, "IA01")
    run = wait_for(client, run_id, done)
    assert run["investigation"]["validation"]["errors"] == [
        {"type": "UNKNOWN_EVIDENCE", "value": "NOT-REAL"}
    ]
    assert verdicts(run)["IA01-R2"] == "FAIL"


def test_system_run_full_flow(client, fakes):
    mcp, agent = fakes
    run_id = start(client, "S03", "B0")
    approve(client, run_id)
    run = wait_for(client, run_id, done)

    assert run["status"] == "COMPLETED", run
    assert mcp.names() == ["initialize", "request_approval", "finalize", "faults"]
    init = mcp.calls[0][1]
    assert init["scenario_id"] == "S03" and init["server_policy_version"] == "baseline-v1"
    assert init["requested_by"] == "requester-01"
    assert init["faults"][0]["trigger"] == "AFTER_FIRST_SUCCESSFUL_COMMIT_BEFORE_RESPONSE"
    # The Agent got the MCP request and both tokens at the right moments.
    assert agent.runs[run_id]["request"] == mcp.request
    assert agent.resumes[0][1]["agent_token"] == "PA-TOKEN"
    assert run["approval"]["approval_id"] == "AP-001"
    assert run["approval"]["payload"] == mcp.request
    assert run["fault"]["status"] == "APPLIED"
    assert run["agent"]["termination"] == "AGENT_FINISHED"
    assert run["agent"]["result"]["outcome"] == "SUCCEEDED"
    assert run["snapshot_complete"] is True
    # The Oracle stub returns no checks; only the Harness-judged R10 remains, and it passes.
    assert verdicts(run) == {"R10": "PASS"}
    assert run["investigation"]["status"] == "NOT_REQUESTED"
    assert "observation" not in run


def test_failed_checks_trigger_investigation(client, fakes, monkeypatch):
    from harness.runner import Runner

    original = Runner._set_status
    reserved = []

    async def check_completion(self, run, status, reason=None):
        if status == "COMPLETED":
            reserved.append(run["investigation"]["status"])
        await original(self, run, status, reason)

    monkeypatch.setattr(Runner, "_set_status", check_completion)

    def fail_duplicate(ctx):
        return [
            {
                "run_id": ctx.run_id,
                "check_id": "CHK-DUPLICATE",
                "rule_id": "R03",
                "rule_version": ctx.rule_version,
                "scope": "business_state",
                "verdict": "FAIL",
                "reason": "중복",
                "evidence_ids": ["EV-SNAPSHOT-001"],
            }
        ]

    monkeypatch.setattr(oracle, "evaluate", fail_duplicate)
    run_id = start(client, "S03", "B0")
    approve(client, run_id)
    run = wait_for(client, run_id, done)

    assert run["investigation"]["status"] == "READY"
    assert reserved == ["RUNNING"]
    assert run["investigation"]["validation"]["passed"] is True
    _, agent = fakes
    inv = agent.runs[f"INV-{run_id}"]
    assert inv["mode"] == "mcp" and inv["target_run_id"] == run_id
    failed = client.get(f"/internal/runs/{run_id}/checks", headers=INTERNAL).json()["checks"]
    assert [c["rule_id"] for c in failed] == ["R03"]
    types = [e["event_type"] for e in client.get(f"/api/runs/{run_id}/events").json()["events"]]
    assert "VERDICT_CREATED" in types and types[-2:] == ["RUN_FINISHED", "REPORT_VALIDATED"]


def test_unexpected_decision_keeps_fail_and_downgrades_pass(client, monkeypatch):
    def checks(ctx):
        base = {"run_id": ctx.run_id, "rule_version": "0.1.0", "evidence_ids": ["EV-SNAPSHOT-001"]}
        return [
            {
                **base,
                "check_id": "A",
                "rule_id": "R01",
                "scope": "business_state",
                "verdict": "PASS",
                "reason": "ok",
            },
            {
                **base,
                "check_id": "B",
                "rule_id": "R05",
                "scope": "agent_behavior",
                "verdict": "FAIL",
                "reason": "bad",
            },
        ]

    monkeypatch.setattr(oracle, "evaluate", checks)
    run_id = start(client, "S02", "B0")
    approve(client, run_id, decision="APPROVED")  # S02 expects REJECTED
    run = wait_for(client, run_id, done)
    assert run["condition_met"] is False
    assert verdicts(run) == {"R01": "INCONCLUSIVE", "R05": "FAIL", "R10": "INCONCLUSIVE"}


def test_approval_expiry_ends_run_with_error(client, fakes):
    mcp, agent = fakes
    agent.expire_approval = True
    run_id = start(client, "S01", "B0")
    run = wait_for(client, run_id, done)
    assert run["status"] == "ERROR" and run["status_reason"] == "APPROVAL_WAIT_EXPIRED"
    assert "finalize" in mcp.names()


def test_resume_is_idempotent_and_guarded(client):
    run_id = start(client, "S01", "B0")
    body = approve(client, run_id)
    again = client.post(f"/internal/runs/{run_id}/resume", json=body, headers=INTERNAL)
    assert again.status_code == 202
    wait_for(client, run_id, done)
    other = client.post(
        f"/internal/runs/{run_id}/resume", json={**body, "approval_id": "AP-002"}, headers=INTERNAL
    )
    assert other.status_code == 409
    assert other.json()["error"]["code"] == "NOT_WAITING_APPROVAL"


def test_one_active_run(client):
    run_id = start(client, "S01", "B0")
    wait_for(client, run_id, lambda r: r["status"] == "WAITING_APPROVAL")
    busy = client.post("/api/runs", json={"test_id": "PA01"})
    assert busy.status_code == 409 and busy.json()["error"]["code"] == "RUN_IN_PROGRESS"


def test_comparison_of_b0_and_b1(client, fakes):
    mcp, _ = fakes
    mcp.orders = 2
    left = start(client, "S03", "B0")
    approve(client, left)
    wait_for(client, left, done)
    mcp.orders = 1
    right = start(client, "S03", "B1")
    approve(client, right)
    wait_for(client, right, done)

    data = client.get(f"/api/comparisons?left={left}&right={right}").json()
    assert {"field": "server_policy_version", "left": "baseline-v1", "right": "idempotent-v1"} in (
        data["changed"]
    )
    assert data["fixed_conditions"]["test_id"] == "S03"
    assert data["actual"]["left"]["order_count"] == 2
    assert data["actual"]["right"]["order_count"] == 1

    pa = start(client, "PA01")
    wait_for(client, pa, done)
    bad = client.get(f"/api/comparisons?left={left}&right={pa}")
    assert bad.status_code == 422 and bad.json()["error"]["code"] == "NOT_COMPARABLE"


def test_resume_retry_after_agent_failure(client, fakes):
    """mcp-server retries resume up to 3 times (MCP_SPEC 5.3); a failed try must not stick."""
    _, agent = fakes
    agent.fail_resume = 1
    run_id = start(client, "S01", "B0")
    run = wait_for(client, run_id, lambda r: r["status"] == "WAITING_APPROVAL")
    body = {
        "approval_id": "AP-001",
        "request_id": run["request"]["request_id"],
        "decision": "APPROVED",
        "approver_id": "approver-01",
        "decided_at": "2026-10-20T00:01:00Z",
        "payload_hash": run["approval_request"]["payload_hash"],
    }
    url = f"/internal/runs/{run_id}/resume"
    first = client.post(url, json=body, headers=INTERNAL)
    assert first.status_code == 502
    assert client.get(f"/api/runs/{run_id}").json()["status"] == "WAITING_APPROVAL"
    assert client.post(url, json=body, headers=INTERNAL).status_code == 202
    run = wait_for(client, run_id, done)
    assert run["status"] == "COMPLETED" and run["approval"]["approval_id"] == "AP-001"
    assert len(agent.resumes) == 1


def test_agent_model_metadata_and_usage_are_preserved(client, fakes, monkeypatch):
    agent = fakes[1]
    original = agent.start
    metadata = {
        "model_kind": "openai",
        "model": "gpt-5.4-nano-2026-03-17",
        "prompt_version": "prompt-hash",
        "agent_version": "0.1.0",
    }

    async def start_with_metadata(body):
        response = await original(body)
        response.update(metadata)
        agent.runs[body["run_id"]].update(metadata)
        agent.runs[body["run_id"]]["llm_usage"] = {"input_tokens": 50, "output_tokens": 20}
        return response

    monkeypatch.setattr(agent, "start", start_with_metadata)
    run_id = start(client, "PA01")
    run = wait_for(client, run_id, done)
    assert all(run["manifest"][key] == value for key, value in metadata.items())
    assert run["agent"]["usage"]["llm"] == {"input_tokens": 50, "output_tokens": 20}
