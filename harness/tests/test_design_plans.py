import pytest
from conftest import ROOT, wait_for

from harness.design_reviews import validate_staged_review
from harness.planning import QaPlanner, fingerprint


@pytest.mark.parametrize(
    "mutation", ["none", "missing-stage", "wrong-domain", "overridden-rejection", "score-total", "score-gate"]
)
def test_harness_independently_enforces_two_review_gates(mutation):
    import copy

    proposal = {
        "proposal_id": "P1",
        "risk_key": "RESOURCE_CONSTRAINT",
        "evidence_ids": ["MF:p0", "AG:p0"],
    }
    records = {
        sid: {"sha256": sid, "risk_types": ["RESOURCE_CONSTRAINT"], "evidence_domains": [domain]}
        for sid, domain in (("MF", "MANUFACTURING"), ("AG", "AGENTIC"))
    }
    sources = {sid + ":p0": {"source_id": sid, "version": sid} for sid in records}
    review = {
        "method": "TWO_STAGE_SEMANTIC_V1",
        "decision": "ACCEPT_FOR_BINDING",
        "stages": [
            {
                "stage": domain,
                "status": "COMPLETED",
                "decision": "ACCEPT_FOR_BINDING",
                "evidence_ids": [sid + ":p0"],
                "scores": {
                    "domain_fit_score": 2,
                    "causal_path_score": 2,
                    "constraint_score": 2,
                    "evidence_score": 2,
                },
                "score_reasons": {
                    "domain_fit_score": "업무 관련 문헌을 확인함",
                    "causal_path_score": "조건에서 결과로 이어지는 경로를 확인함",
                    "constraint_score": "운영 제약을 확인함",
                    "evidence_score": "단계에 맞는 출처를 확인함",
                },
                "score_total": 8,
                "score_max": 8,
                "assessment": {
                    "policy_alignment": "ALIGNED",
                    "evidence_relevance": "SUPPORTED",
                    "scenario_consistency": "COHERENT",
                },
            }
            for sid, domain in (("MF", "MANUFACTURING"), ("AG", "AGENTIC"))
        ],
    }
    changed = copy.deepcopy(review)
    if mutation == "missing-stage":
        changed["stages"].pop()
    elif mutation == "wrong-domain":
        changed["stages"][1]["evidence_ids"] = ["MF:p0"]
    elif mutation == "overridden-rejection":
        changed["stages"][1]["assessment"]["evidence_relevance"] = "IRRELEVANT"
        changed["stages"][1]["decision"] = "REJECT"
    elif mutation == "score-total":
        changed["stages"][1]["score_total"] = 7
    elif mutation == "score-gate":
        changed["stages"][1]["scores"]["evidence_score"] = 0
        changed["stages"][1]["score_total"] = 6
    if mutation == "none":
        validate_staged_review(changed, proposal, sources, records)
    else:
        with pytest.raises(ValueError):
            validate_staged_review(changed, proposal, sources, records)


def design(planner):
    source = {
        "document_id": "PROJECT-IDEMPOTENCY:p0",
        "version": "v1",
        "source_id": "PROJECT-IDEMPOTENCY",
        "location": "summary",
        "title": "Safe retries",
        "content_kind": "CURATED_SUMMARY",
        "source_url": "https://example.org",
        "matched_text": "same request",
        "scope": "Project policy",
    }
    return {
        "design_id": "DESIGN-TEST",
        "sources": [source],
        "model_kind": "offline",
        "version": "1.0.0",
        "analysis": {"target_type": "PURCHASE"},
        "trace": [],
        "retrieval": [],
        "proposals": [
            {
                "proposal_id": "BOUNDARY",
                "tool_name": "create_purchase_order",
                "risk_type": "RESPONSE_LOSS",
                "data_strategy": "SHORTAGE_BOUNDARY",
                "title": "Boundary retry",
                "failure_mode": "Duplicate after timeout",
                "rationale": "Write tool and bounded retries",
                "test_data_json": "{}",
                "expected_behavior": "one commit",
                "evidence_ids": [source["document_id"]],
            }
        ],
    }


def test_designed_boundary_is_a_new_executable_case_and_rebuilds_without_a_model():
    planner = QaPlanner(ROOT)
    proposal = design(planner)
    plan = planner.build_designed(planner.reference_target, planner.reference_sample, proposal)
    case = plan["cases"][-1]
    assert case["business_input"]["quantity"] == 21
    assert planner.reference_sample["business_input"]["quantity"] == 100
    assert case["execution"]["registered_test_id"] == "S03"
    assert case["data_hash"] == fingerprint(
        {k: case[k] for k in ("business_input", "initial_state")}
    )
    assert case["design_basis"]["changes"] == [{"field": "quantity", "before": 100, "after": 21}]
    assert (
        planner.build_designed(planner.reference_target, planner.reference_sample, plan["design"])
        == plan
    )


def test_domain_rules_and_missing_sources_cannot_become_executable_by_model_claims():
    planner = QaPlanner(ROOT)
    candidate = design(planner)
    candidate["proposals"][0]["risk_type"] = "DOMAIN_CONSTRAINT"
    candidate["proposals"][0]["test_data_json"] = '{"create_anyway":true}'
    plan = planner.build_designed(planner.reference_target, planner.reference_sample, candidate)
    case = plan["cases"][-1]
    assert case["execution"]["status"] == "UNSUPPORTED"
    assert case["design_basis"]["verdict_authority"] == "DRAFT_POLICY_NOT_ADOPTED"
    assert not case["design_basis"]["proposed_data_applied"]
    candidate = design(planner)
    candidate["proposals"][0]["evidence_ids"] = []
    assert (
        planner.build_designed(planner.reference_target, planner.reference_sample, candidate)[
            "cases"
        ][-1]["execution"]["status"]
        == "UNSUPPORTED"
    )
    candidate["proposals"][0]["evidence_ids"] = ["FABRICATED"]
    with pytest.raises(ValueError, match="Unretrieved"):
        planner.build_designed(planner.reference_target, planner.reference_sample, candidate)


def test_design_api_saves_compiled_case_and_supplies_only_business_input_at_execution(
    client, fakes
):
    planner = QaPlanner(ROOT)

    async def generate(body):
        return design(planner)

    fakes[1].design = generate
    response = client.post("/api/qa/design", json={})
    assert response.status_code == 200
    plan = response.json()
    assert fakes[0].calls == [] and fakes[1].runs == {}
    assert client.get(f"/api/qa/plans/{plan['plan_id']}").json() == plan
    case = plan["cases"][-1]
    started = client.post(
        "/api/runs",
        json={"plan_id": plan["plan_id"], "case_id": case["case_id"], "system_id": "B1"},
    )
    assert started.status_code == 202
    run = wait_for(client, started.json()["run_id"], lambda r: r["status"] == "WAITING_APPROVAL")
    assert run["request"]["quantity"] == 21
    assert run["manifest"]["data_hash"] == case["data_hash"]
    assert "design" not in fakes[1].runs[run["run_id"]]
    assert "sources" not in fakes[1].runs[run["run_id"]]


def test_manufacturing_reference_inputs_have_registered_execution(client):
    planner = QaPlanner(ROOT)
    for kind in ("PRODUCTION", "QUALITY"):
        body = client.get(f"/api/qa/target?target_type={kind}").json()
        plan = planner.build(body["target"], body["sample_data"])
        assert any(c["execution"]["status"] == "READY" for c in plan["cases"])


def modern_design(planner):
    candidate = design(planner)
    candidate.update(
        version="2.0.0",
        risk_library_version=planner.risk_library["version"],
        risk_library_hash=fingerprint(planner.risk_library),
    )
    candidate["analysis"]["risk_screening"] = [
        {"risk_key": "AMBIGUOUS_WRITE", "status": "APPLICABLE"}
    ]
    candidate["sources"][0]["source_type"] = "PROJECT_POLICY"
    candidate["sources"].append(
        {
            **candidate["sources"][0],
            "source_id": "RES-AGENT-SAFETY",
            "document_id": "RES-AGENT-SAFETY:p0",
            "source_type": "RESEARCH",
        }
    )
    candidate["proposals"][0].update(
        risk_key="AMBIGUOUS_WRITE", evidence_ids=[s["document_id"] for s in candidate["sources"]]
    )
    return candidate


def test_modern_design_needs_research_and_canonically_adopted_policy():
    planner = QaPlanner(ROOT)
    candidate = modern_design(planner)
    case = planner.build_designed(planner.reference_target, planner.reference_sample, candidate)[
        "cases"
    ][-1]
    assert case["execution"]["status"] == "READY"
    assert case["design_basis"]["adopted_policy_ids"] == ["PROJECT-IDEMPOTENCY"]
    assert not case["design_basis"]["evidence_groups"]["INCIDENT"]
    candidate["proposals"][0]["evidence_ids"] = ["RES-AGENT-SAFETY:p0"]
    case = planner.build_designed(planner.reference_target, planner.reference_sample, candidate)[
        "cases"
    ][-1]
    assert case["execution"]["status"] == "UNSUPPORTED"
    assert "adopted_business_policy" in case["execution"]["missing_capabilities"]
    candidate = modern_design(planner)
    candidate["sources"][0]["source_type"] = "INCIDENT"
    with pytest.raises(ValueError, match="category"):
        planner.build_designed(planner.reference_target, planner.reference_sample, candidate)


def test_risk_library_changes_require_a_new_design():
    planner = QaPlanner(ROOT)
    candidate = modern_design(planner)
    candidate["risk_library_hash"] = "old-library"
    with pytest.raises(ValueError, match="Risk library changed"):
        planner.build_designed(planner.reference_target, planner.reference_sample, candidate)


@pytest.mark.parametrize("outcome", ["fixed", "still-invalid", "scope-change", "budget"])
async def test_repair_is_bounded_and_never_executes_or_substitutes_data(outcome):
    import copy
    import json
    from types import SimpleNamespace

    from test_generation import generated_design

    from harness.clients import ClientError
    from harness.designing import design_with_repair

    planner = QaPlanner(ROOT)
    ref = planner.target_input("PRODUCTION")
    original = generated_design(planner)
    original["retrieval"] = [{"index_version": "fixed-index"}]
    invalid = {
        "business_input_patch": {},
        "initial_state_patch": {},
        "approval_decision": "APPROVED",
        "fault": "NONE",
        "interventions": [],
    }
    original["proposals"][0]["test_data_json"] = json.dumps(invalid)
    calls = []

    async def invoke(data):
        calls.append(copy.deepcopy(data))
        if len(calls) == 1:
            return copy.deepcopy(original)
        assert len(calls) == 2 and data["repair"]["feedback"]
        if outcome == "budget":
            raise ClientError("agents", 503, "LLM_BUDGET_EXHAUSTED")
        result = (
            copy.deepcopy(original) if outcome == "still-invalid" else generated_design(planner)
        )
        if outcome == "scope-change":
            result["proposals"][0]["tool_name"] = "new_business_write"
        return result

    result = await design_with_repair(SimpleNamespace(design=invoke), planner, ref)
    assert len(calls) == 2 and result["repair"]["attempts"] == 1
    expected = {
        "fixed": "REPAIRED",
        "still-invalid": "NOT_REPAIRED",
        "scope-change": "INVALID_REPAIR",
        "budget": "BUDGET_EXHAUSTED",
    }
    assert result["repair"]["status"] == expected[outcome]
    final = planner.build_designed(ref["target"], ref["sample_data"], result)
    case = next(c for c in final["cases"] if c.get("design_basis"))
    assert (case["execution"]["status"] == "READY") == (outcome == "fixed")
    assert result["repair"]["original_proposals"] == original["proposals"]
    assert case["actual_result"] is None
