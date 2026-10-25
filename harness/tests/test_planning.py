"""QA planning must follow the target, preserve evidence boundaries, and gate execution."""

import copy
import json

import pytest
from conftest import ROOT, wait_for
from jsonschema import Draft202012Validator
from jsonschema.exceptions import ValidationError

from harness.planning import QaPlanner


def test_reference_plan_has_executable_cases_and_explicit_coverage_gap():
    plan = QaPlanner(ROOT).build()
    ready = [c for c in plan["cases"] if c["execution"]["status"] == "READY"]
    assert {c["execution"]["registered_test_id"] for c in ready} == {"S01", "S02", "S03", "S04"}
    stale = next(c for c in plan["cases"] if c["risk_id"] == "STALE_APPROVAL")
    assert stale["execution"]["status"] == "UNSUPPORTED"
    assert "request_change_after_approval" in stale["execution"]["missing_capabilities"]
    assert all(c["actual_result"] is None for c in plan["cases"])


def test_non_purchase_target_generates_its_own_test_data_without_purchase_fields():
    target = {
        "target_id": "maintenance-example",
        "target_version": "1",
        "task": "확인된 설비 정비 작업을 시작한다",
        "industry_context": "제조 설비 정비",
        "simulation_adapter": "not-registered",
        "tools": [{"name": "start_work", "effect": "WRITE", "input_schema": {"type": "object"}}],
        "policies": {"approval_required": True, "max_write_retries": 0},
        "business_input_schema": {
            "type": "object",
            "required": ["equipment_id"],
            "properties": {"equipment_id": {"type": "string"}},
        },
    }
    data = {
        "business_input": {"equipment_id": "EQ-007"},
        "initial_state": {"equipment": {"equipment_id": "EQ-007", "isolated": False}},
    }
    original = copy.deepcopy(data)
    plan = QaPlanner(ROOT).build(target, data)
    assert plan["cases"]
    assert all(c["business_input"] == data["business_input"] for c in plan["cases"])
    assert all(c["execution"]["status"] == "UNSUPPORTED" for c in plan["cases"])
    lost = next(c for c in plan["cases"] if c["risk_id"] == "POST_COMMIT_RESPONSE_LOSS")
    assert lost["simulation"]["fault"]["tool_name"] == "start_work"
    assert "request_id" not in lost["business_input"]
    assert data == original


def test_claiming_reference_adapter_does_not_authorize_changed_target_or_data():
    planner = QaPlanner(ROOT)
    target = copy.deepcopy(planner.reference_target)
    data = copy.deepcopy(planner.reference_sample)
    target["task"] = "A different agent pretending to be the reference"
    plan = planner.build(target, data)
    assert all(c["execution"]["status"] == "UNSUPPORTED" for c in plan["cases"])
    data["business_input"] = {**data["business_input"], "quantity": 200}
    plan = planner.build(planner.reference_target, data)
    assert all(c["execution"]["registered_test_id"] is None for c in plan["cases"])


def test_custom_target_requires_its_own_data_and_valid_business_input():
    planner = QaPlanner(ROOT)
    with pytest.raises(ValueError):
        planner.build(planner.reference_target)
    with pytest.raises(ValueError):
        planner.build(sample=planner.reference_sample)
    data = copy.deepcopy(planner.reference_sample)
    del data["business_input"]["part_id"]
    with pytest.raises(ValidationError):
        planner.build(planner.reference_target, data)


def test_plan_identity_changes_with_input_but_is_stable_without_changes():
    planner = QaPlanner(ROOT)
    one = planner.build()
    assert one["plan_id"] == planner.build()["plan_id"]
    data = copy.deepcopy(planner.reference_sample)
    data["initial_state"]["parts"][0]["inventory"] = 30
    two = planner.build(planner.reference_target, data)
    assert one["plan_id"] != two["plan_id"]


def test_plan_api_does_not_execute_target_and_rejects_invalid_input(client, fakes):
    response = client.post("/api/qa/plans", json={})
    assert response.status_code == 200
    assert fakes[0].calls == [] and fakes[1].runs == {}
    invalid = client.post("/api/qa/plans", json={"target": {"target_id": "incomplete"}})
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "INVALID_QA_INPUT"


def test_execution_records_selected_plan_and_uses_its_fault(client, fakes):
    plan = client.post("/api/qa/plans", json={}).json()
    response = client.post(
        "/api/runs", json={"test_id": "S03", "system_id": "B1", "plan_id": plan["plan_id"]}
    )
    assert response.status_code == 202
    run_id = response.json()["run_id"]
    run = wait_for(client, run_id, lambda r: r["status"] == "WAITING_APPROVAL")
    case = run["qa_case"]
    assert case["risk_id"] == "POST_COMMIT_RESPONSE_LOSS"
    init = next(body for name, body in fakes[0].calls if name == "initialize")
    fault = {k: v for k, v in init["faults"][0].items() if k != "fault_id"}
    assert fault == case["simulation"]["fault"]
    assert run["manifest"]["qa_plan_id"] == plan["plan_id"]
    # The target only receives the business request, never QA hypotheses or expected verdicts.
    assert "qa_case" not in fakes[1].runs[run_id]


def test_a_plan_for_another_target_cannot_execute_reference_tests(client, fakes):
    response = client.post(
        "/api/runs", json={"test_id": "S01", "system_id": "B1", "plan_id": "QAP-another-target"}
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "QA_PLAN_CHANGED"
    assert fakes[0].calls == [] and fakes[1].runs == {}


def changed_sample(planner):
    sample = copy.deepcopy(planner.reference_sample)
    sample["business_input"].update(request_id="REQ-QA-200", quantity=200, unit_price_minor=15000)
    sample["initial_state"]["request"] = copy.deepcopy(sample["business_input"])
    sample["initial_state"]["parts"][0]["inventory"] = 35
    sample["initial_state"]["suppliers"][0]["unit_price_minor"] = 15000
    return sample


def test_saved_generated_case_supplies_real_input_to_sandbox_and_target(client, fakes):
    planner = QaPlanner(ROOT)
    sample = changed_sample(planner)
    response = client.post(
        "/api/qa/plans", json={"target": planner.reference_target, "sample_data": sample}
    )
    assert response.status_code == 200
    plan = response.json()
    assert client.get(f"/api/qa/plans/{plan['plan_id']}").json() == plan
    case = next(c for c in plan["cases"] if c["risk_id"] == "POST_COMMIT_RESPONSE_LOSS")
    assert case["execution"]["status"] == "READY"
    response = client.post(
        "/api/runs",
        json={"plan_id": plan["plan_id"], "case_id": case["case_id"], "system_id": "B1"},
    )
    assert response.status_code == 202
    rid = response.json()["run_id"]
    run = wait_for(client, rid, lambda r: r["status"] == "WAITING_APPROVAL")
    init = next(body for name, body in fakes[0].calls if name == "initialize")
    assert init["initial_state"] == sample["initial_state"]
    assert run["request"] == sample["business_input"]
    assert fakes[1].runs[rid]["request"] == sample["business_input"]
    assert run["manifest"]["data_hash"] == plan["data_hash"]
    assert run["manifest"]["qa_case_id"] == case["case_id"]
    assert "initial_state" not in fakes[1].runs[rid]
    assert "assertions" not in fakes[1].runs[rid]
    assert init["faults"][0]["trigger"] == case["simulation"]["fault"]["trigger"]


@pytest.mark.parametrize(
    "mutation", ["users", "supply_source", "mismatched_request", "enough_inventory"]
)
def test_unsupported_state_changes_never_start_a_trial(client, fakes, mutation):
    planner = QaPlanner(ROOT)
    sample = changed_sample(planner)
    if mutation == "users":
        sample["initial_state"]["users"][0]["roles"].append("APPROVER")
    elif mutation == "supply_source":
        sample["initial_state"]["approved_supply_sources"][0]["policy_version"] = 99
    elif mutation == "mismatched_request":
        sample["business_input"]["quantity"] += 1
    else:
        sample["initial_state"]["parts"][0]["inventory"] = 1000
    plan = client.post(
        "/api/qa/plans", json={"target": planner.reference_target, "sample_data": sample}
    ).json()
    assert all(c["execution"]["status"] == "UNSUPPORTED" for c in plan["cases"])
    response = client.post(
        "/api/runs",
        json={
            "plan_id": plan["plan_id"],
            "case_id": plan["cases"][0]["case_id"],
            "system_id": "B1",
        },
    )
    assert response.status_code == 422
    assert fakes[0].calls == [] and fakes[1].runs == {}


def test_saved_plan_is_private_to_creator(client):
    plan = client.post("/api/qa/plans", json={}).json()
    from conftest import TOKEN

    headers = {"X-Internal-Token": TOKEN, "X-User-Id": "other-user", "X-User-Roles": "REQUESTER"}
    assert client.get(f"/api/qa/plans/{plan['plan_id']}", headers=headers).status_code == 404
    response = client.post(
        "/api/runs",
        headers=headers,
        json={
            "plan_id": plan["plan_id"],
            "case_id": plan["cases"][0]["case_id"],
            "system_id": "B1",
        },
    )
    assert response.status_code == 404


def test_plan_survives_store_reopen(tmp_path):
    from harness.store import Store

    url = f"sqlite:///{tmp_path}/plans.sqlite"
    plan = QaPlanner(ROOT).build()
    store = Store(url)
    store.put_plan(plan, "owner")
    store.put_plan(plan, "owner")
    store.close()
    reopened = Store(url)
    try:
        assert reopened.get_plan(plan["plan_id"], "owner") == plan
        assert reopened.get_plan(plan["plan_id"], "other") is None
    finally:
        reopened.close()


def test_execution_rejects_ambiguous_case_selection(client):
    response = client.post(
        "/api/runs",
        json={"test_id": "S01", "plan_id": "QAP-x", "case_id": "some-case", "system_id": "B1"},
    )
    assert response.status_code == 400


@pytest.mark.parametrize("kind", ["PURCHASE", "PRODUCTION", "QUALITY"])
def test_plan_records_retrieved_evidence_without_exposing_it_to_target(client, fakes, kind):
    from harness.clients import ClientError

    async def search(body):
        assert body["target_type"] == kind
        return {
            "query": body["query"],
            "index_version": "corpus-v1",
            "model": "bge",
            "model_revision": "revision-v1",
            "results": [
                {
                    "document_id": "DOC:p2",
                    "source_id": "DOC",
                    "version": "v1",
                    "location": "PDF page 2",
                    "source_url": "https://example.org/report.pdf",
                    "content_kind": "PDF_TEXT",
                    "parent_text": "reference context only",
                }
            ],
        }

    fakes[0].search_knowledge = search
    response = client.post(
        "/api/qa/plans", json={"knowledge_query": "safe retries", "knowledge_target_type": kind}
    )
    assert response.status_code == 200
    plan = response.json()
    assert plan["knowledge_evidence"]["target_type"] == kind
    assert "parent_text" not in plan["knowledge_evidence"]["sources"][0]
    assert plan["plan_id"] != client.post("/api/qa/plans", json={}).json()["plan_id"]
    assert client.get(f"/api/qa/plans/{plan['plan_id']}").json() == plan
    assert fakes[0].calls == [] and fakes[1].runs == {}

    # A knowledge outage must not create a plan or start an experiment.
    async def unavailable(body):
        raise ClientError("mcp-server", 503, "KNOWLEDGE_UNAVAILABLE")

    fakes[0].search_knowledge = unavailable
    failed = client.post("/api/qa/plans", json={"knowledge_query": "safe retries"})
    assert failed.status_code == 503
    assert failed.json()["error"]["code"] == "KNOWLEDGE_UNAVAILABLE"
    assert fakes[0].calls == [] and fakes[1].runs == {}


def test_target_registry_distinguishes_design_from_real_execution(client):
    response = client.get("/api/qa/targets")
    assert response.status_code == 200
    types = {row["type_id"]: row for row in response.json()["types"]}
    assert {kind: row["execution"] for kind, row in types.items()} == {
        "PURCHASE": "READY",
        "PRODUCTION": "READY",
        "QUALITY": "READY",
    }
    for kind in types:
        reference = client.get("/api/qa/target", params={"target_type": kind}).json()
        assert set(reference) == {"target", "sample_data"}
        assert reference["target"]["agent_type"] == kind
        plan = client.post("/api/qa/plans", json=reference)
        assert plan.status_code == 200, plan.text


def test_design_preserves_model_input_limit_error(client, fakes):
    from harness.clients import ClientError

    async def oversized(body):
        raise ClientError("agents", 503, "LLM_INPUT_LIMIT")

    fakes[1].design = oversized
    reference = client.get("/api/qa/target").json()
    response = client.post("/api/qa/design", json=reference)
    assert response.status_code == 503
    assert response.json()["error"]["code"] == "LLM_INPUT_LIMIT"
    assert fakes[0].calls == [] and fakes[1].runs == {}


def test_qualification_recipe_changes_only_the_selected_flag():
    planner = QaPlanner(ROOT)
    plan = planner.build()
    risk = next(c for c in plan["cases"] if c["risk_id"] == "UNQUALIFIED_SUPPLIER")
    control = next(c for c in plan["cases"] if c["risk_id"] == "CONTROL_BASELINE")
    assert risk["execution"]["registered_test_id"] == "S04"
    assert risk["business_input"] == control["business_input"]
    restored = copy.deepcopy(risk["initial_state"])
    restored["approved_supply_sources"][0]["allowed"] = True
    assert restored == control["initial_state"]
    assert risk["initial_state"]["suppliers"][0]["status"] == "ACTIVE"
    assert risk["data_hash"] != control["data_hash"]
    rebuilt = planner.build(
        planner.reference_target, {k: risk[k] for k in ("business_input", "initial_state")}
    )
    assert (
        next(c for c in rebuilt["cases"] if c["risk_id"] == "CONTROL_BASELINE")["initial_state"]
        == control["initial_state"]
    )
    assert (
        next(c for c in rebuilt["cases"] if c["risk_id"] == "POST_COMMIT_RESPONSE_LOSS")[
            "execution"
        ]["status"]
        == "UNSUPPORTED"
    )


@pytest.mark.parametrize(
    "method", ["CODE_PREREQUISITES", "SEMANTIC_RUBRIC_V1", "OFFLINE_METADATA_CHECK"]
)
def test_stored_review_schema_separates_plan_review_from_agent_verdict(method):
    schema = json.loads((ROOT / "qa/contracts/qa.schema.json").read_text())
    plan = QaPlanner(ROOT).build()
    plan["design"] = {"reviews": [{
        "proposal_id": "example-1", "decision": "NEEDS_INFORMATION",
        "reasons": ["채택 정책을 확인해야 합니다."], "method": method,
    }]}
    validator = Draft202012Validator(schema)
    validator.validate(plan)
    plan["design"]["reviews"][0]["decision"] = "PASS"
    with pytest.raises(ValidationError):
        validator.validate(plan)
    plan["design"]["reviews"][0]["decision"] = "ACCEPT_FOR_BINDING"
    plan["design"]["reviews"][0]["assessment"] = {
        "policy_alignment": "ALIGNED", "evidence_relevance": "SUPPORTED",
        "scenario_consistency": "COHERENT",
    }
    validator.validate(plan)
    plan["design"]["reviews"][0]["assessment"]["policy_alignment"] = "PASS"
    with pytest.raises(ValidationError):
        validator.validate(plan)
