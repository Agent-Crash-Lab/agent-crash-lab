import time

import pytest
from conftest import GATEWAY, ROOT, TOKEN
from test_design_plans import modern_design

from harness import oracle
from harness.evaluation import run_result, trial_count
from harness.planning import QaPlanner, fingerprint


def strategic_design(planner):
    d = modern_design(planner)
    d.update(
        version="3.0.0",
        test_policy_version=planner.test_policy["version"],
        test_policy_hash=fingerprint(planner.test_policy),
        reviews=[
            {"proposal_id": "BOUNDARY", "decision": "ACCEPT_FOR_BINDING", "reasons": ["reviewed"]}
        ],
    )
    d["proposals"][0]["assessment"] = {
        "priority": "P2",
        "trial_profile": "DETECT_10",
        "business_impact": "중복 발주 비용",
        "decision_basis": "명시된 상태 변경과 정책",
    }
    return d


def prepare(client, fakes, monkeypatch, failure=False, profile=None):
    planner = client.app.state.catalog.planner

    async def design(body):
        return strategic_design(planner)

    async def execution_profile():
        return profile or {"model_kind": "deterministic", "run_cost_upper_bound_usd": 0}

    fakes[1].design, fakes[1].execution_profile = design, execution_profile

    def judge(ctx):
        return [
            {
                "run_id": ctx.run_id,
                "check_id": f"{rule}:{scope}",
                "rule_id": rule,
                "rule_version": ctx.rule_version,
                "scope": scope,
                "verdict": "FAIL" if failure and ctx.test_id == "S03" and rule == "R03" else "PASS",
                "reason": "known test observation",
                "evidence_ids": ["EV-SNAPSHOT-001"],
            }
            for rule in ctx.rule_ids
            for scope in ctx.rule_scopes[rule]
        ]

    monkeypatch.setattr(oracle, "evaluate", judge)
    response = client.post("/api/qa/design", json={})
    assert response.status_code == 200, response.text
    return response.json()


def start(client, plan, **changes):
    case = next(c for c in plan["cases"] if c.get("design_basis"))
    body = {
        "request_id": "test-batch",
        "plan_id": plan["plan_id"],
        "case_ids": [case["case_id"]],
        "systems": ["B1"],
        "max_runs": 8,
        **changes,
    }
    response = client.post("/api/qa/batches", json=body)
    assert response.status_code == 202, response.text
    return response.json(), body


def follow(client, batch, before_approval=None):
    deadline = time.monotonic() + 6
    resumed = set()
    while time.monotonic() < deadline:
        b = client.get("/api/qa/batches/" + batch["batch_id"]).json()
        if b["status"] not in {"RUNNING", "WAITING_APPROVAL", "STOPPING"}:
            return b
        rid = b["active_run_id"]
        if rid:
            run = client.get("/api/runs/" + rid).json()
            if run["status"] == "WAITING_APPROVAL" and rid not in resumed:
                if before_approval:
                    before_approval(b, run)
                approval = run["approval_request"]
                response = client.post(
                    "/internal/runs/" + rid + "/resume",
                    headers={"X-Internal-Token": TOKEN},
                    json={
                        "approval_id": "AP-" + rid,
                        "request_id": run["request"]["request_id"],
                        "decision": "APPROVED",
                        "approver_id": "approver-01",
                        "decided_at": "2026-10-21T00:00:00Z",
                        "payload_hash": approval["payload_hash"],
                    },
                )
                assert response.status_code == 202, response.text
                resumed.add(rid)
        time.sleep(0.015)
    raise AssertionError(b)


def test_strategy_uses_policy_floor_and_same_input_control():
    p = QaPlanner(ROOT)
    d = strategic_design(p)
    plan = p.build_designed(p.reference_target, p.reference_sample, d)
    case = next(c for c in plan["cases"] if c.get("design_basis"))
    strategy = case["evaluation_strategy"]
    assert strategy["priority"] == "P0" and strategy["corrections"]
    assert strategy["trial_design"]["recommended_repetitions"] == 29
    control = next(c for c in plan["cases"] if c["case_id"] == strategy["control_case_id"])
    assert control["business_input"] == case["business_input"]
    assert control["initial_state"] == case["initial_state"]
    assert control["data_hash"] == case["data_hash"]
    assert control["simulation"]["fault"] is None
    assert case["simulation"]["fault"]
    d["reviews"][0]["decision"] = "REJECT"
    rejected = p.build_designed(p.reference_target, p.reference_sample, d)
    assert rejected["cases"][-1]["execution"]["status"] == "UNSUPPORTED"
    d["test_policy_hash"] = "stale"
    with pytest.raises(ValueError, match="Test policy changed"):
        p.build_designed(p.reference_target, p.reference_sample, d)


def test_trial_sizing_and_missing_observations_do_not_pass():
    assert [trial_count(p, 0.95) for p in (0.1, 0.05, 0.01)] == [29, 59, 299]
    run = {"status": "COMPLETED", "condition_met": True, "snapshot_complete": True, "checks": []}
    assert run_result(run, ["R01"]) == "INCONCLUSIVE"
    run["checks"] = [{"rule_id": "R01", "verdict": "FAIL"}]
    run["snapshot_complete"] = False
    assert run_result(run, ["R01"]) == "FAIL"


def test_batch_runs_matching_control_and_risk_and_is_owner_scoped(client, fakes, monkeypatch):
    plan = prepare(client, fakes, monkeypatch)
    batch, body = start(client, plan)
    assert client.post("/api/qa/batches", json=body).json()["batch_id"] == batch["batch_id"]
    other = {**GATEWAY, "X-User-Id": "other"}
    assert client.get("/api/qa/batches/" + batch["batch_id"], headers=other).status_code == 404
    assert client.get("/api/qa/batches", headers=other).json() == {"batches": []}
    assert client.post("/api/runs", json={"test_id": "S01", "system_id": "B1"}).status_code == 409
    done = follow(client, batch)
    assert done["status"] == "COMPLETED", done
    assert len(done["slots"]) == 2
    assert done["report"]["conclusion"] == "NO_VIOLATION_OBSERVED"
    assert all(g["conditional_zero_failure_upper_bound"] is None for g in done["report"]["groups"])
    seeds = [b["initial_state"] for name, b in fakes[0].calls if name == "initialize"]
    assert len(seeds) == 2 and seeds[0] == seeds[1]
    assert len({s["run_id"] for s in done["slots"]}) == 2
    assert client.post("/api/qa/batches", json={**body, "max_runs": 2}).status_code == 409


@pytest.mark.parametrize(
    "stop,reason", [("limit", "RUN_LIMIT"), ("failure", "RULE_FAILURE"), ("user", "USER_STOP")]
)
def test_stops_without_turning_partial_results_into_pass(client, fakes, monkeypatch, stop, reason):
    plan = prepare(client, fakes, monkeypatch, failure=stop == "failure")
    batch, _ = start(
        client,
        plan,
        max_runs=1 if stop == "limit" else 8,
        systems=["B0", "B1"] if stop == "failure" else ["B1"],
    )

    def stop_it(b, run):
        if stop == "user":
            client.post("/api/qa/batches/" + b["batch_id"] + "/stop", json={})

    done = follow(client, batch, stop_it)
    assert done["status"] == "STOPPED" and done["stop_reason"] == reason, done
    expected = "FAIL" if stop == "failure" else "INSUFFICIENT_EVIDENCE"
    assert done["report"]["conclusion"] == expected
    if stop != "failure":
        assert len(done["slots"]) == 1


def test_cost_reservation_blocks_before_dispatch_and_determinism_cannot_claim_reliability(
    client, fakes, monkeypatch
):
    plan = prepare(client, fakes, monkeypatch)
    denied = client.post(
        "/api/qa/batches",
        json={"request_id": "rel", "plan_id": plan["plan_id"], "mode": "RELIABILITY"},
    )
    assert denied.status_code == 422

    async def costly():
        return {"model_kind": "openai", "run_cost_upper_bound_usd": 0.8}

    fakes[1].execution_profile = costly
    batch, _ = start(client, plan, max_cost_usd=0.1)
    done = follow(client, batch)
    assert done["stop_reason"] == "COST_LIMIT" and not done["slots"]
    assert fakes[1].runs == {}
    assert done["report"]["conclusion"] == "INSUFFICIENT_EVIDENCE"


def test_repeat_schedule_resets_state_and_counts_each_condition(client, fakes, monkeypatch):
    # Test a short confidence setting in memory; the production policy stays at 95%.
    client.app.state.catalog.planner.test_policy["confidence"] = 0.2
    original = fakes[1].start

    async def model_start(body):
        await original(body)
        fakes[1].runs[body["run_id"]].update(
            model_kind="openai",
            model="test-model",
            prompt_version="test-prompt",
            agent_version="test-version",
        )
        return dict(fakes[1].runs[body["run_id"]])

    fakes[1].start = model_start
    plan = prepare(
        client, fakes, monkeypatch, profile={"model_kind": "openai", "run_cost_upper_bound_usd": 0}
    )
    batch, _ = start(client, plan, mode="RELIABILITY")
    done = follow(client, batch)
    assert done["status"] == "COMPLETED", done
    assert len(done["slots"]) == 4
    assert sorted(g["completed"] for g in done["report"]["groups"]) == [1, 3]
    assert all(g["completed"] == g["planned"] for g in done["report"]["groups"])
    assert (
        sum(g["conditional_zero_failure_upper_bound"] is not None for g in done["report"]["groups"])
        == 1
    )
    seeds = [b["initial_state"] for name, b in fakes[0].calls if name == "initialize"]
    assert len(seeds) == 4 and all(s == seeds[0] for s in seeds)
    assert len({s["run_id"] for s in done["slots"]}) == 4


def test_restart_marks_interrupted_without_replaying_dispatch(client, fakes, monkeypatch):
    plan = prepare(client, fakes, monkeypatch)
    batch, _ = start(client, plan)
    deadline = time.monotonic() + 3
    while time.monotonic() < deadline:
        saved = client.get("/api/qa/batches/" + batch["batch_id"]).json()
        if saved["active_run_id"]:
            break
        time.sleep(0.01)
    client.portal.call(client.app.state.batches.close)
    client.portal.call(client.app.state.runner.close)
    before = len(fakes[1].runs)
    client.app.state.runner.recover()
    client.app.state.batches.recover()
    saved = client.get("/api/qa/batches/" + batch["batch_id"]).json()
    assert saved["status"] == "INTERRUPTED"
    assert saved["stop_reason"] == "HARNESS_RESTARTED"
    assert len(fakes[1].runs) == before
    assert saved["report"]["conclusion"] == "INSUFFICIENT_EVIDENCE"


def test_stop_during_profile_lookup_cannot_dispatch_a_run(client, fakes, monkeypatch):
    import asyncio
    from threading import Event

    plan = prepare(client, fakes, monkeypatch)
    entered, release = Event(), Event()
    calls = 0

    async def paused_profile():
        nonlocal calls
        calls += 1
        if calls == 2:
            entered.set()
            await asyncio.to_thread(release.wait, 3)
        return {"model_kind": "deterministic", "run_cost_upper_bound_usd": 0}

    fakes[1].execution_profile = paused_profile
    batch, _ = start(client, plan)
    try:
        assert entered.wait(3), "Worker did not reach profile lookup"
        stopped = client.post("/api/qa/batches/" + batch["batch_id"] + "/stop", json={})
        assert stopped.status_code == 200
    finally:
        release.set()
    done = follow(client, batch)
    assert done["stop_reason"] == "USER_STOP"
    assert done["slots"] == [] and fakes[1].runs == {}


def test_completed_runs_with_different_versions_cannot_claim_no_violation():
    from harness.evaluation import summarize

    batch = {
        "mode": "SMOKE",
        "policy": {"confidence": 0.95},
        "systems": ["B1"],
        "cases": [
            {
                "case_id": "risk",
                "risk_id": "RISK",
                "priority": "P0",
                "required_rules": ["R03"],
                "repetitions": 2,
            }
        ],
    }
    runs = [
        {
            "run_id": str(i),
            "qa_batch_case_id": "risk",
            "system_id": "B1",
            "status": "COMPLETED",
            "condition_met": True,
            "snapshot_complete": True,
            "checks": [{"rule_id": "R03", "verdict": "PASS"}],
            "manifest": {"agent_version": str(i)},
        }
        for i in range(2)
    ]
    report = summarize(batch, runs)
    assert not report["groups"][0]["version_consistent"]
    assert report["groups"][0]["result"] == "INSUFFICIENT_EVIDENCE"
    assert report["conclusion"] == "INSUFFICIENT_EVIDENCE"


async def test_investigation_followup_uses_original_plan_and_enforces_owner(
    client, fakes, monkeypatch
):
    from conftest import GATEWAY

    from harness.followups import recommendation

    plan = prepare(client, fakes, monkeypatch, failure=True)
    case = next(c for c in plan["cases"] if c.get("design_basis"))
    source = {
        "run_id": "RUN-SOURCE",
        "created_at": "2026-10-22T00:00:00Z",
        "created_by": "requester-01",
        "test_kind": "SYSTEM",
        "status": "COMPLETED",
        "system_id": "B1",
        "qa_batch_id": None,
        "manifest": {"qa_plan_id": plan["plan_id"], "qa_case_id": case["case_id"]},
        "checks": [{"rule_id": "R03", "verdict": "FAIL", "evidence_ids": ["EV-SOURCE"]}],
        "investigation": {"status": "READY", "report": {"retest_scenario_ids": ["S03"]}},
    }
    store = client.app.state.store
    store.put_run(source)
    proposed = recommendation(source, store, "requester-01")
    assert proposed["status"] == "READY" and proposed["max_runs"] == 2
    assert proposed["evidence_ids"] == ["EV-SOURCE"]
    assert proposed["case_ids"] == [case["case_id"]]
    wrong_owner = {**GATEWAY, "X-User-Id": "another-user"}
    assert (
        client.post("/api/qa/runs/RUN-SOURCE/follow-up", headers=wrong_owner, json={}).status_code
        == 404
    )
    first = client.post("/api/qa/runs/RUN-SOURCE/follow-up", json={})
    assert first.status_code == 202, first.text
    second = client.post("/api/qa/runs/RUN-SOURCE/follow-up", json={})
    assert second.json()["batch_id"] == first.json()["batch_id"]
    assert first.json()["planned_runs"] == 2
    child = {**source, "qa_batch_id": first.json()["batch_id"]}
    assert recommendation(child, store, "requester-01")["status"] == "UNAVAILABLE"
