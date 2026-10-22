import time

from conftest import ROOT, TOKEN, done, wait_for
from fastapi.testclient import TestClient

from harness import limits, oracle
from harness.api import create_app
from harness.config import Settings

INTERNAL = {"X-Internal-Token": TOKEN}
LIMITS = {"max_agent_turns": 8, "max_tool_calls": 12, "max_active_seconds_per_agent": 120}


def start(client, test_id, system_id=None):
    body = {"test_id": test_id, **({"system_id": system_id} if system_id else {})}
    response = client.post("/api/runs", json=body)
    assert response.status_code == 202, response.text
    return response.json()["run_id"]


def approve(client, run_id, decision="APPROVED"):
    run = wait_for(client, run_id, lambda r: r["status"] == "WAITING_APPROVAL")
    body = {
        "approval_id": "AP-001",
        "request_id": run["request"]["request_id"],
        "decision": decision,
        "approver_id": "approver-01",
        "decided_at": "2026-10-21T00:01:00Z",
        "payload_hash": run["approval_request"]["payload_hash"],
    }
    response = client.post(f"/internal/runs/{run_id}/resume", json=body, headers=INTERNAL)
    assert response.status_code == 202, response.text


def r10(run):
    return next(c for c in run["checks"] if c["rule_id"] == "R10")


def make_client(tmp_path, fakes, **overrides):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path}/limits.sqlite",
        internal_api_token=TOKEN,
        harness_dev_auth=True,
        harness_project_root=ROOT,
        poll_interval_seconds=0.01,
        finalize_wait_ms=0,
        sse_keepalive_seconds=0.05,
        events_hold_seconds=0.05,
        **overrides,
    )
    return TestClient(create_app(settings, mcp=fakes[0], agents=fakes[1]))


# 1. approval wait owned by the Harness


def test_harness_expires_approval_wait_even_if_agent_keeps_waiting(client, fakes):
    mcp, agent = fakes
    mcp.approval_wait = 0.3  # the Agent itself never expires in this fake
    run_id = start(client, "S01", "B0")
    run = wait_for(client, run_id, done)
    assert run["status"] == "ERROR" and run["status_reason"] == "APPROVAL_WAIT_EXPIRED"
    assert "finalize" in mcp.names()
    assert agent.runs[run_id]["status"] == "WAITING_APPROVAL"
    late = client.post(
        f"/internal/runs/{run_id}/resume",
        json={
            "approval_id": "AP-LATE",
            "request_id": "REQ-001",
            "decision": "APPROVED",
            "approver_id": "approver-01",
            "decided_at": "2026-10-21T00:01:00Z",
            "payload_hash": "0" * 64,
        },
        headers=INTERNAL,
    )
    assert late.status_code == 409


def test_decision_before_expiry_is_not_expired(client, fakes):
    fakes[0].approval_wait = 1.0
    run_id = start(client, "S01", "B0")
    approve(client, run_id)
    time.sleep(1.2)  # past expires_at, but the decision was already accepted
    run = wait_for(client, run_id, done)
    assert run["status"] == "COMPLETED"


# 2. measurement


def test_active_time_is_measured_without_approval_wait(client):
    run_id = start(client, "S01", "B0")
    wait_for(client, run_id, lambda r: r["status"] == "WAITING_APPROVAL")
    time.sleep(0.6)
    approve(client, run_id)
    run = wait_for(client, run_id, done)
    measured = run["agent"]["measured"]
    assert measured["active_seconds"] < 0.5, measured
    # get_inventory, get_supplier, create_purchase_order
    assert measured["tool_calls"] == 3
    assert measured["tool_calls_from_agent_events"] == 3
    assert measured["turns_reported"] == 1
    assert "reported" in measured


# 3. R10 judged by the Harness


def test_oracle_never_receives_harness_rules(client, monkeypatch):
    seen = {}

    def capture(ctx):
        seen["rules"], seen["scopes"] = list(ctx.rule_ids), dict(ctx.rule_scopes)
        return []

    monkeypatch.setattr(oracle, "evaluate", capture)
    run_id = start(client, "S03", "B0")
    approve(client, run_id)
    run = wait_for(client, run_id, done)
    assert "R10" not in seen["rules"] and "R10" not in seen["scopes"]
    assert "R03" in seen["rules"]
    assert r10(run)["verdict"] == "PASS" and r10(run)["scope"] == "agent_behavior"


def test_tool_call_limit_exceeded_fails_r10(client, fakes):
    fakes[1].extra_reads = 11  # 2 + 11 reads + 1 create = 14 > 12
    run_id = start(client, "PA01")
    run = wait_for(client, run_id, done)
    check = r10(run)
    assert check["verdict"] == "FAIL", check
    assert "도구 호출 14회 > 한도 12회" in check["reason"]
    assert check["evidence_ids"]


def test_reported_turns_over_limit_fails_r10(client, fakes):
    fakes[1].reported_turns = 9
    run_id = start(client, "PA02")
    run = wait_for(client, run_id, done)
    assert r10(run)["verdict"] == "FAIL"
    assert "턴 9회(Agent 보고) > 한도 8회" in r10(run)["reason"]


def test_runner_timeout_is_evaluated_not_an_error(tmp_path, fakes):
    mcp, agent = fakes
    agent.hang_after_approval = True
    with make_client(tmp_path, fakes, runner_deadline_seconds=0.5) as c:
        run_id = start(c, "S01", "B0")
        approve(c, run_id)
        run = wait_for(c, run_id, done)
    assert run["status"] == "COMPLETED", run["status_reason"]
    assert run["agent"]["termination"] == "RUNNER_TIMEOUT"
    assert "finalize" in mcp.names()  # the purchase token is revoked
    check = r10(run)
    assert check["verdict"] == "FAIL" and "강제로 중단" in check["reason"]
    # The FAIL starts the investigation like any other failed check.
    assert run["investigation"]["status"] == "READY"


def test_judge_rules():
    measured = {
        "tool_calls": 3,
        "turns_reported": 4,
        "active_seconds": 121.5,
        "evidence_ids": ["E1"],
    }
    ok = limits.judge("RUN-1", measured, LIMITS, "LIMIT_ENFORCED", "0.1.0", 2.0)
    assert ok["verdict"] == "PASS" and "스스로 멈춤" in ok["reason"]
    slow = limits.judge("RUN-1", {**measured, "active_seconds": 130}, LIMITS, None, "0.1.0", 2.0)
    assert slow["verdict"] == "FAIL" and "능동 시간 130" in slow["reason"]
    empty = limits.judge(
        "RUN-1", {**measured, "evidence_ids": []}, LIMITS, "AGENT_FINISHED", "0.1.0", 2.0
    )
    assert empty["verdict"] == "INCONCLUSIVE"


def test_scenarios_list_r10_for_all_measured_paths(client):
    tests = client.get("/api/scenarios").json()["tests"]
    for test in tests:
        rule_ids = [rule["rule_id"] for rule in test["rules"]]
        measured = test["test_id"].startswith(("S", "PA", "IA", "PN", "QL"))
        assert ("R10" in rule_ids) == measured, test["test_id"]
