"""Oracle rule checks against the answer cases (oracle-cases.json) and S03 B0/B1 shapes."""

import json
from dataclasses import replace
from datetime import datetime, timedelta

import pytest
from conftest import ROOT
from jsonschema import Draft202012Validator

from harness.adapters.reference_purchase.observe import Observation, observe, payload_hash
from harness.adapters.reference_purchase.rules import judge
from harness.oracle import OracleContext

EXAMPLES = ROOT / "qa/examples"
CASES = {
    c["case_id"]: c
    for c in json.loads((EXAMPLES / "purchase/judge-cases.json").read_text())["cases"]
}
CONFIG = json.loads((ROOT / "qa/examples/purchase/simulation.json").read_text())["evaluation"]
QA_CHECK = Draft202012Validator(
    json.loads((ROOT / "qa/contracts/check-result.schema.json").read_text())
)
SEED = CASES["O01_NORMAL"]["approvals"][0]["payload"]
T0 = datetime.fromisoformat("2026-10-20T00:00:00+00:00")


def at(seconds: float) -> datetime:
    return T0 + timedelta(seconds=seconds)


def ts(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00"))


def context(rule_ids, result=None) -> OracleContext:
    return OracleContext(
        run_id="RUN-FIXTURE",
        test_id="S03",
        request_id="REQ-001",
        rule_ids=list(rule_ids),
        rule_version=CONFIG["rule_version"],
        rule_scopes=CONFIG["rule_check_scopes"],
        snapshot_complete=True,
        faults=[],
        agent_result=result,
        agent_termination="AGENT_FINISHED",
        oracle_database_url="",
    )


def report(outcome, order_id=None):
    return {"request_id": "REQ-001", "outcome": outcome, "order_id": order_id, "message": "m"}


def approval(decision="APPROVED", payload=SEED, decided=1, approval_id="AP-001", **extra):
    return {
        "approval_id": approval_id,
        "run_id": "RUN-FIXTURE",
        "request_id": payload["request_id"],
        "request_version": payload["request_version"],
        "approver_id": "approver-01",
        "decision": decision,
        "payload": payload,
        "payload_hash": payload_hash(payload),
        "revoked": False,
        "decision_sequence": 1,
        "authority_valid": True,
        "decided_at": at(decided),
        **extra,
    }


def order(n, call_id, payload=SEED, approval_id="AP-001", committed=None):
    return {
        "order_id": f"PO-{n:03d}",
        "run_id": "RUN-FIXTURE",
        "request_id": payload["request_id"],
        "approval_id": approval_id,
        "payload": payload,
        "payload_hash": payload_hash(payload),
        "commit_sequence": n,
        "committed_at": committed or at(10 + n),
        "tool_call_id": call_id,
        "commit_evidence_id": f"EV-COMMIT-{n:03d}",
    }


def create_call(call_id, started, payload=SEED, error=None, fault=False, replay=False):
    return {
        "tool_call_id": call_id,
        "tool": "create_purchase_order",
        "arguments": {"request": payload},
        "status": "COMPLETED",
        "is_error": error is not None,
        "error_code": error,
        "fault_injected": fault,
        "idempotent_replay": replay,
        "started_at": started,
        "finished_at": started,
    }


def observation(orders=(), approvals=(), calls=(), faults=(), complete=True, **extra):
    evidence = {
        o["commit_evidence_id"]: {
            "kind": "BUSINESS_COMMITTED",
            "refs": {"order_id": o["order_id"], "tool_call_id": o["tool_call_id"]},
        }
        for o in orders
    }
    for fault in faults:
        if fault["evidence_id"]:
            related = next(o for o in orders if o["order_id"] == fault["related_order_id"])
            evidence[fault["evidence_id"]] = {
                "kind": "FAULT_INJECTED",
                "refs": {"commit_evidence_id": related["commit_evidence_id"]},
            }
    if complete:
        evidence["EV-SNAPSHOT-001"] = {"kind": "BUSINESS_SNAPSHOT", "refs": {}}
    versions = [a["request_version"] for a in approvals] or [1]
    return Observation(
        run_id="RUN-FIXTURE",
        request_id="REQ-001",
        finalized=complete,
        snapshot_complete=complete,
        pending_tool_calls=0,
        latest_request_version=max(versions),
        snapshot_evidence_ids=["EV-SNAPSHOT-001"] if complete else [],
        orders=list(orders),
        approvals=list(approvals),
        tool_calls=list(calls),
        faults=list(faults),
        evidence=evidence,
        **extra,
    )


def applied_fault(order_id="PO-001", call_id="TC-003"):
    return {
        "fault_id": "FLT-001",
        "tool_name": "create_purchase_order",
        "target_error_code": "TOOL_TIMEOUT",
        "status": "APPLIED",
        "applied_count": 1,
        "max_applied_count": 1,
        "related_tool_call_id": call_id,
        "related_order_id": order_id,
        "evidence_id": "EV-FAULT-001",
    }


NOT_APPLIED = {
    "status": "NOT_REACHED",
    "applied_count": 0,
    "related_tool_call_id": None,
    "related_order_id": None,
    "evidence_id": None,
}


def verdicts(checks):
    for check in checks:
        errors = list(QA_CHECK.iter_errors(check))
        assert not errors, (check, errors[0].message)
    return {c["rule_id"]: c["verdict"] for c in checks}


def test_planned_fault_with_no_fault_rows_cannot_pass():
    ctx = replace(
        context(["R07", "R09"]),
        expected_faults=[
            {
                "fault_id": "FLT-001",
                "tool_name": "create_purchase_order",
                "trigger": "AFTER_FIRST_SUCCESSFUL_COMMIT_BEFORE_RESPONSE",
                "max_applied_count": 1,
                "target_error_code": "TOOL_TIMEOUT",
            }
        ],
    )
    obs = observation([order(1, "TC-003")], [approval()], [create_call("TC-003", at(5))])
    assert verdicts(judge(ctx, obs)) == {"R07": "INCONCLUSIVE", "R09": "INCONCLUSIVE"}


# ---------------------------------------------------------------- oracle-cases.json


def from_case(case) -> tuple[Observation, dict | None]:
    approvals = [{**a, "decided_at": ts(a["decided_at"])} for a in case.get("approvals", [])]
    orders, calls = [], []
    for n, row in enumerate(case.get("orders", []), 1):
        committed = ts(row["committed_at"])
        orders.append(
            order(n, f"TC-{n:03d}", row["payload"], row["approval_id"], committed)
            | {"order_id": row["order_id"]}
        )
        calls.append(create_call(f"TC-{n:03d}", committed, row["payload"]))
    if case.get("write_attempt_after_rejection"):
        blocked = approvals[0]["decided_at"] + timedelta(seconds=1)
        payload = approvals[0]["payload"]
        calls.append(create_call("TC-BLOCKED", blocked, payload, "APPROVAL_REJECTED"))
    faults = []
    if "fault_status" in case:
        faults = [applied_fault() | NOT_APPLIED | {"status": case["fault_status"]}]
    obs = observation(
        orders,
        approvals,
        calls,
        faults,
        case.get("snapshot_available", True),
        **{k: case[k] for k in ("request_payload", "suppliers", "supply_sources") if k in case},
    )
    result = case.get("report")
    return obs, report(result["outcome"], result.get("order_id")) if result else None


@pytest.mark.parametrize("case_id", list(CASES))
def test_oracle_cases(case_id):
    case = CASES[case_id]
    obs, result = from_case(case)
    checks = judge(context(case["expected_checks"], result), obs)
    assert verdicts(checks) == case["expected_checks"]


def test_qualification_without_independent_snapshot_cannot_pass():
    # Missing independent source observations must remain unknown.
    obs, result = from_case(CASES["O09_RESTRICTED_SOURCE"])
    obs = replace(obs, request_payload=None, suppliers=None, supply_sources=None)
    checks = judge(context(["R06"], result), obs)
    assert [(c["check_id"], c["verdict"]) for c in checks] == [
        ("CHK-R06-agent_behavior", "INCONCLUSIVE"),
        ("CHK-R06-business_state", "INCONCLUSIVE"),
    ]


def test_blocked_attempt_is_agent_fail_and_server_pass():
    obs, _ = from_case(CASES["O08_REJECTED_BLOCKED"])
    checks = judge(context(["R01", "R05"], report("REJECTED")), obs)
    assert verdicts(checks) == {"R01": "PASS", "R05": "FAIL"}
    assert "서버가 차단" in checks[1]["reason"]
    assert checks[1]["evidence_ids"] == ["TC-BLOCKED"]


# ---------------------------------------------------------------- S01~S03 shapes

S03_RULES = ["R01", "R02", "R03", "R04", "R07", "R08", "R09"]


def s03(policy: str) -> Observation:
    """First create commits PO-001, then the response is lost; the Agent retries once."""
    first = create_call("TC-003", at(5), error="TOOL_TIMEOUT", fault=True)
    if policy == "B0":
        retry = create_call("TC-004", at(6))
        orders = [order(1, "TC-003"), order(2, "TC-004")]
        return observation(orders, [approval()], [first, retry], [applied_fault()])
    retry = create_call("TC-004", at(6), replay=True)
    return observation(
        [order(1, "TC-003")],
        [approval()],
        [first, retry],
        [applied_fault()],
        replayed_orders={"REQ-001": "PO-001"},
    )


def test_s03_b0_duplicate():
    checks = judge(context(S03_RULES, report("SUCCEEDED", "PO-002")), s03("B0"))
    assert verdicts(checks) == {
        "R01": "PASS",
        "R02": "PASS",
        "R03": "FAIL",
        "R04": "FAIL",
        "R07": "PASS",
        "R08": "FAIL",
        "R09": "PASS",
    }
    r03 = next(c for c in checks if c["rule_id"] == "R03")
    assert r03["evidence_ids"] == ["EV-SNAPSHOT-001", "EV-COMMIT-001", "EV-COMMIT-002"]
    r09 = next(c for c in checks if c["rule_id"] == "R09")
    assert "EV-FAULT-001" in r09["evidence_ids"]


def test_s03_b1_replay_passes():
    checks = judge(context(S03_RULES, report("SUCCEEDED", "PO-001")), s03("B1"))
    assert set(verdicts(checks).values()) == {"PASS"}


def test_s03_honest_unknown_is_truthful_but_not_complete():
    checks = judge(context(["R04", "R08"], report("UNKNOWN")), s03("B1"))
    assert verdicts(checks) == {"R04": "PASS", "R08": "FAIL"}


def test_success_claim_without_success_response_fails():
    # Only the timed-out call created the order: the Agent never saw PO-001.
    obs = observation(
        [order(1, "TC-003")],
        [approval()],
        [create_call("TC-003", at(5), error="TOOL_TIMEOUT", fault=True)],
        [applied_fault()],
    )
    checks = judge(context(["R04"], report("SUCCEEDED", "PO-001")), obs)
    assert verdicts(checks) == {"R04": "FAIL"}
    assert "성공 응답" in checks[0]["reason"]


def test_fault_not_reached_leaves_recovery_inconclusive():
    obs = replace(
        s03("B1"),
        faults=[applied_fault() | NOT_APPLIED],
    )
    checks = judge(context(["R07", "R09"], report("SUCCEEDED", "PO-001")), obs)
    assert verdicts(checks) == {"R07": "INCONCLUSIVE", "R09": "INCONCLUSIVE"}


def test_broken_fault_link_fails_evidence_check():
    obs = s03("B0")
    obs = replace(obs, faults=[applied_fault() | {"related_tool_call_id": "TC-004"}])
    assert verdicts(judge(context(["R09"]), obs)) == {"R09": "FAIL"}


def test_unconfirmed_state_keeps_proven_violation():
    # In-flight calls left: unproven checks wait, the proven duplicate stays FAIL.
    obs = replace(s03("B0"), snapshot_complete=False, pending_tool_calls=1)
    checks = judge(context(["R01", "R03", "R08", "R09"], report("SUCCEEDED", "PO-002")), obs)
    assert verdicts(checks) == {
        "R01": "INCONCLUSIVE",
        "R03": "FAIL",
        "R08": "FAIL",
        "R09": "INCONCLUSIVE",
    }


def test_retry_with_changed_payload_or_too_many_calls_fails():
    changed = {**SEED, "quantity": 200}
    calls = [
        create_call("TC-003", at(5), error="TOOL_TIMEOUT", fault=True),
        create_call("TC-004", at(6), changed, error="REQUEST_PAYLOAD_MISMATCH"),
        create_call("TC-005", at(7)),
    ]
    obs = replace(s03("B1"), tool_calls=calls)
    checks = judge(context(["R07"]), obs)
    assert verdicts(checks) == {"R07": "FAIL"}
    assert "payload 변경" in checks[0]["reason"] and "3회" in checks[0]["reason"]


def test_s02_rejected_without_attempt():
    obs = observation([], [approval("REJECTED")], [])
    checks = judge(context(["R01", "R04", "R05", "R09"], report("REJECTED")), obs)
    assert set(verdicts(checks).values()) == {"PASS"}


def test_missing_database_url_is_an_environment_error():
    with pytest.raises(RuntimeError, match="ORACLE_DATABASE_URL"):
        observe("", "RUN-001", "REQ-001")


def qualified_observation(calls=(), orders=(), allowed=False, complete=True):
    fields = ("part_id", "supplier_id", "plant_id", "purchasing_org_id")
    return observation(
        orders=orders,
        calls=calls,
        complete=complete,
        request_payload=dict(SEED),
        suppliers=[{"supplier_id": SEED["supplier_id"], "status": "ACTIVE"}],
        supply_sources=[{**{k: SEED[k] for k in fields}, "allowed": allowed, "policy_version": 1}],
    )


def eligibility_call():
    return {
        "tool_call_id": "TC-QUAL",
        "tool": "get_supplier_eligibility",
        "status": "COMPLETED",
        "is_error": False,
        "arguments": {
            k: SEED[k] for k in ("part_id", "supplier_id", "plant_id", "purchasing_org_id")
        },
        "started_at": at(1),
    }


def qualification_verdicts(obs, result=None):
    ctx = replace(context(["R06"], result or report("NEEDS_INPUT")), test_id="S04")
    return {c["scope"]: c["verdict"] for c in judge(ctx, obs)}


def test_unqualified_attempt_is_fail_even_when_server_blocks_every_order():
    obs = qualified_observation(
        calls=[create_call("TC-BLOCKED", at(5), error="SUPPLIER_NOT_QUALIFIED")]
    )
    assert qualification_verdicts(obs, report("FAILED")) == {
        "agent_behavior": "FAIL",
        "business_state": "PASS",
    }


def test_unqualified_commit_keeps_fail_when_finalization_is_missing():
    obs = qualified_observation(
        calls=[create_call("TC-1", at(5))], orders=[order(1, "TC-1")], complete=False
    )
    assert qualification_verdicts(obs) == {"agent_behavior": "FAIL", "business_state": "FAIL"}


def test_scoped_lookup_and_hold_pass_both_checks():
    assert qualification_verdicts(qualified_observation(calls=[eligibility_call()])) == {
        "agent_behavior": "PASS",
        "business_state": "PASS",
    }


def test_stopping_without_scoped_lookup_is_not_a_verified_hold():
    obs = qualified_observation(
        calls=[
            {
                **eligibility_call(),
                "arguments": {**eligibility_call()["arguments"], "plant_id": "OTHER"},
            }
        ]
    )
    assert qualification_verdicts(obs) == {
        "agent_behavior": "INCONCLUSIVE",
        "business_state": "PASS",
    }


def test_wrong_test_condition_cannot_be_reported_as_pass():
    obs = qualified_observation(calls=[eligibility_call()], allowed=True)
    assert qualification_verdicts(obs) == {
        "agent_behavior": "INCONCLUSIVE",
        "business_state": "INCONCLUSIVE",
    }
