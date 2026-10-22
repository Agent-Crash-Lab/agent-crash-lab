import copy

import pytest
from conftest import GATEWAY, ROOT

from harness.planning import QaPlanner
from harness.registrations import Registration, profile, target_input


def declaration():
    sample = QaPlanner(ROOT).target_input("PURCHASE")
    target = sample["target"]
    return {
        "name": "새 구매 Agent",
        "version": "1.0.0",
        "agent_type": "PURCHASE",
        "task": target["task"],
        "industry_context": target["industry_context"],
        "tools": target["tools"],
        "policies": target["policies"],
        "business_input_schema": target["business_input_schema"],
        "sample_data": sample["sample_data"],
        "capability_bindings": [
            {**b, "basis": "DECLARED"} for b in target["qa_scope"]["capabilities"]
        ],
        "excluded_capabilities": target["qa_scope"]["excluded_capabilities"],
    }


def install_analysis(fakes):
    calls = []

    async def analyze(data):
        calls.append(copy.deepcopy(data))
        return {
            "risk_screening": [],
            "unknowns": [],
            "declared_policies": {
                k: None if k in data["unknown_policies"] else v
                for k, v in data["target"]["policies"].items()
            },
        }

    fakes[1].analyze = analyze
    return calls


def test_registration_is_persistent_private_and_cannot_impersonate_reference(client, fakes):
    calls = install_analysis(fakes)
    body = declaration()
    saved = client.post("/api/qa/registrations", json=body)
    assert saved.status_code == 200, saved.text
    saved = saved.json()
    assert saved["can_design"] and saved["execution_status"] == "ADAPTER_REQUIRED"
    assert calls[0]["target"]["simulation_adapter"] == "external-unbound"
    assert calls[0]["target"]["target_id"].startswith("registered-")
    assert {b["basis"] for b in calls[0]["target"]["qa_scope"]["capabilities"]} == {"DECLARED"}
    assert client.post("/api/qa/registrations", json=body).json() == saved
    assert client.get(f"/api/qa/registrations/{saved['profile_id']}").json() == saved
    assert len(client.get("/api/qa/registrations").json()["profiles"]) == 1
    other = {**GATEWAY, "X-User-Id": "other-requester"}
    assert (
        client.get(f"/api/qa/registrations/{saved['profile_id']}", headers=other).status_code == 404
    )
    assert client.get("/api/qa/registrations", headers=other).json()["profiles"] == []
    assert (
        client.post(
            f"/api/qa/registrations/{saved['profile_id']}/design", json={}, headers=other
        ).status_code
        == 404
    )
    assert fakes[0].calls == [] and fakes[1].runs == {}
    body["task"] += "改"
    assert (
        client.post("/api/qa/registrations", json=body).json()["profile_id"] != saved["profile_id"]
    )
    assert client.get(f"/api/qa/registrations/{saved['profile_id']}").json() == saved


def test_unknown_policy_is_saved_as_unknown_and_design_is_blocked(client, fakes):
    calls = install_analysis(fakes)
    body = declaration()
    body["policies"] = {"approval_required": None, "max_write_retries": None}
    saved = client.post("/api/qa/registrations", json=body).json()
    assert not saved["can_design"]
    assert saved["input"]["policies"]["approval_required"] is None
    assert saved["analysis"]["declared_policies"]["max_write_retries"] is None
    assert set(calls[0]["unknown_policies"]) == {"approval_required", "max_write_retries"}
    response = client.post(f"/api/qa/registrations/{saved['profile_id']}/design", json={})
    assert response.status_code == 422
    assert response.json()["error"]["code"] == "PROFILE_INFORMATION_REQUIRED"


@pytest.mark.parametrize(
    "mutation",
    [
        "basis",
        "adapter",
        "duplicate",
        "effect",
        "binding",
        "exclude",
        "remote",
        "schema",
        "sample",
        "policy_bool",
        "policy_retry",
        "too_large",
        "invalid_tool_schema",
        "cycle",
        "missing_ref",
    ],
)
def test_invalid_or_forged_declarations_never_reach_analysis(client, fakes, mutation):
    calls = install_analysis(fakes)
    body = declaration()
    if mutation == "basis":
        body["capability_bindings"][0]["basis"] = "EXECUTION_VERIFIED"
    elif mutation == "adapter":
        body["simulation_adapter"] = "reference-purchase-v1"
    elif mutation == "duplicate":
        body["tools"].append(copy.deepcopy(body["tools"][0]))
    elif mutation == "effect":
        body["tools"][0]["effect"] = "UNKNOWN"
    elif mutation == "binding":
        body["capability_bindings"][0]["tool_name"] = "missing"
    elif mutation == "exclude":
        body["excluded_capabilities"].append("inventory_read")
    elif mutation == "remote":
        body["business_input_schema"] = {"$ref": "http://127.0.0.1/secret"}
    elif mutation == "schema":
        body["business_input_schema"] = {"type": "nonsense"}
    elif mutation == "sample":
        body["sample_data"]["business_input"]["quantity"] = "wrong"
    elif mutation == "policy_bool":
        body["policies"]["approval_required"] = "true"
    elif mutation == "policy_retry":
        body["policies"]["max_write_retries"] = 1.5
    elif mutation == "too_large":
        body["sample_data"]["initial_state"]["extra"] = "x" * 100001
    elif mutation == "invalid_tool_schema":
        body["tools"][0]["input_schema"] = {"type": 42}
    elif mutation == "missing_ref":
        body["business_input_schema"] = {"$ref": "#/$defs/missing"}
    elif mutation == "cycle":
        body["business_input_schema"] = {"$ref": "#"}
    response = client.post("/api/qa/registrations", json=body)
    assert response.status_code == 400, response.text
    assert calls == [] and fakes[0].calls == []


def test_description_reaches_analysis_but_does_not_register_code():
    body = declaration()
    body["tools"][0]["description"] = "Only a claim, not execution proof"
    parsed = Registration(**body)
    canonical = target_input(parsed)
    assert canonical["target"]["tools"][0]["description"] == body["tools"][0]["description"]
    saved = profile(parsed, {}, ROOT)
    assert saved["assurance"] == "USER_DECLARED_NOT_EXECUTION_VERIFIED"


def test_registered_design_preserves_profile_and_is_not_executable(client, fakes):
    from test_design_plans import design

    install_analysis(fakes)
    saved = client.post("/api/qa/registrations", json=declaration()).json()
    planner = QaPlanner(ROOT)

    async def generate(data):
        assert data["target"]["simulation_adapter"] == "external-unbound"
        return design(planner)

    fakes[1].design = generate
    plan_response = client.post(f"/api/qa/registrations/{saved['profile_id']}/design", json={})
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()
    assert plan["design"]["registration"]["profile_hash"] == saved["profile_hash"]
    assert all(c["execution"]["status"] == "UNSUPPORTED" for c in plan["cases"])
    assert client.get(f"/api/qa/plans/{plan['plan_id']}").json() == plan
    case = plan["cases"][-1]
    started = client.post(
        "/api/runs",
        json={"plan_id": plan["plan_id"], "case_id": case["case_id"], "system_id": "B1"},
    )
    assert started.status_code == 422
    assert started.json()["error"]["code"] == "UNSUPPORTED_SIMULATION"
    assert fakes[0].calls == [] and fakes[1].runs == {}


def test_stale_analysis_requires_registration_again(client, fakes, monkeypatch):
    install_analysis(fakes)
    saved = client.post("/api/qa/registrations", json=declaration()).json()
    monkeypatch.setattr("harness.api.library_hash", lambda _: "changed")
    response = client.post(f"/api/qa/registrations/{saved['profile_id']}/design", json={})
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "PROFILE_ANALYSIS_CHANGED"


def test_approver_cannot_register(client, fakes):
    calls = install_analysis(fakes)
    response = client.post(
        "/api/qa/registrations", json=declaration(), headers={**GATEWAY, "X-User-Roles": "APPROVER"}
    )
    assert response.status_code == 403 and calls == []


def test_equivalent_tool_and_capability_order_does_not_create_new_registration(client, fakes):
    install_analysis(fakes)
    body = declaration()
    saved = client.post("/api/qa/registrations", json=body).json()
    body["tools"].reverse()
    body["capability_bindings"].reverse()
    body["excluded_capabilities"].reverse()
    assert client.post("/api/qa/registrations", json=body).json() == saved


@pytest.mark.parametrize("route", ["/api/qa/plans", "/api/qa/design"])
def test_raw_plan_endpoints_cannot_bypass_schema_import_guard(client, route):
    body = QaPlanner(ROOT).target_input("PURCHASE")
    body["target"]["business_input_schema"] = {"$ref": "http://127.0.0.1/private"}
    assert client.post(route, json=body).status_code == 400


def runtime_profile(**changes):
    return {
        "runtime_id": "reference-purchase-v1",
        "agent_version": "0.2.0",
        "prompt_version": "prompt-v1",
        "model_kind": "deterministic",
        "model": None,
        "run_cost_upper_bound_usd": 0,
        **changes,
    }


def install_runtime(fakes):
    state = runtime_profile()

    async def execution_profile():
        return dict(state)

    fakes[1].execution_profile = execution_profile
    return state


@pytest.mark.parametrize(
    "mutation", ["task", "type", "tools", "policies", "schema", "capabilities", "state", "runtime"]
)
def test_managed_runtime_requires_compatible_contract_and_state(client, fakes, mutation):
    calls = install_analysis(fakes)
    current = install_runtime(fakes)
    body = declaration()
    body["execution_runtime"] = "reference-purchase-v1"
    if mutation == "task":
        body["task"] = "Different business logic"
    elif mutation == "type":
        body["agent_type"] = "PRODUCTION"
    elif mutation == "tools":
        body["tools"][0]["input_schema"] = {"type": "object"}
    elif mutation == "policies":
        body["policies"]["approval_required"] = None
    elif mutation == "schema":
        body["business_input_schema"] = {"type": "object"}
    elif mutation == "capabilities":
        body["capability_bindings"].pop()
    elif mutation == "state":
        request = body["sample_data"]["initial_state"]["request"]
        body["sample_data"]["initial_state"]["request"] = {
            **request,
            "quantity": request["quantity"] + 1,
        }
    elif mutation == "runtime":
        current["runtime_id"] = "unknown-runtime"
    response = client.post("/api/qa/registrations", json=body)
    assert response.status_code == 400, response.text
    assert response.json()["error"]["code"] == "INCOMPATIBLE_EXECUTION_TARGET"
    assert calls == [] and fakes[0].calls == [] and fakes[1].runs == {}


def test_repeat_registration_reuses_saved_analysis(client, fakes):
    calls = install_analysis(fakes)
    body = declaration()
    first = client.post("/api/qa/registrations", json=body).json()
    assert client.post("/api/qa/registrations", json=body).json() == first
    assert len(calls) == 1


def connected_plan(client, fakes):
    from test_batches import strategic_design

    install_analysis(fakes)
    live = install_runtime(fakes)
    body = declaration()
    body["execution_runtime"] = "reference-purchase-v1"
    saved = client.post("/api/qa/registrations", json=body)
    assert saved.status_code == 200, saved.text
    saved = saved.json()
    assert saved["execution_status"] == "CONNECTED"
    planner = client.app.state.catalog.planner

    async def design(data):
        assert data["target"] == planner.reference_target
        return strategic_design(planner)

    fakes[1].design = design
    response = client.post(f"/api/qa/registrations/{saved['profile_id']}/design", json={})
    assert response.status_code == 200, response.text
    plan = response.json()
    assert plan["design"]["registration"]["execution_binding"] == saved["execution_binding"]
    assert client.app.state.catalog.planner.rebuild(plan) == plan
    return saved, plan, live


def test_explicit_managed_registration_runs_with_saved_provenance(client, fakes):
    saved, plan, _ = connected_plan(client, fakes)
    case = next(c for c in plan["cases"] if c.get("design_basis"))
    assert case["execution"]["status"] == "READY"
    response = client.post(
        "/api/runs",
        json={"plan_id": plan["plan_id"], "case_id": case["case_id"], "system_id": "B1"},
    )
    assert response.status_code == 202, response.text
    run = client.get("/api/runs/" + response.json()["run_id"]).json()
    assert run["manifest"]["registered_target"]["profile_id"] == saved["profile_id"]
    assert run["manifest"]["target_id"] == "reference-purchase"


def test_runtime_change_blocks_new_design_single_run_and_batch(client, fakes):
    saved, plan, live = connected_plan(client, fakes)
    live["agent_version"] = "changed"
    assert (
        client.post(f"/api/qa/registrations/{saved['profile_id']}/design", json={}).status_code
        == 409
    )
    case = next(c for c in plan["cases"] if c.get("design_basis"))
    for path, body in [
        ("/api/runs", {"plan_id": plan["plan_id"], "case_id": case["case_id"], "system_id": "B1"}),
        (
            "/api/qa/batches",
            {"request_id": "changed", "plan_id": plan["plan_id"], "case_ids": [case["case_id"]]},
        ),
    ]:
        response = client.post(path, json=body)
        assert response.status_code == 409, response.text
        assert response.json()["error"]["code"] == "TARGET_RUNTIME_CHANGED"
    assert fakes[0].calls == [] and fakes[1].runs == {}


def test_connected_registration_batch_uses_existing_execution_pipeline(client, fakes, monkeypatch):
    from harness import oracle

    _, plan, _ = connected_plan(client, fakes)
    monkeypatch.setattr(oracle, "evaluate", lambda ctx: [])
    case = next(c for c in plan["cases"] if c.get("design_basis"))
    response = client.post(
        "/api/qa/batches",
        json={
            "request_id": "connected",
            "plan_id": plan["plan_id"],
            "case_ids": [case["case_id"]],
            "systems": ["B1"],
            "max_runs": 2,
        },
    )
    assert response.status_code == 202, response.text
    assert response.json()["execution_profile"]["agent_version"] == "0.2.0"


def test_unavailable_runtime_blocks_dispatch_before_any_business_call(client, fakes):
    from harness.clients import ClientError

    _, plan, _ = connected_plan(client, fakes)

    async def offline():
        raise ClientError("agents", 503, "unavailable")

    fakes[1].execution_profile = offline
    case = next(c for c in plan["cases"] if c.get("design_basis"))
    response = client.post(
        "/api/runs",
        json={"plan_id": plan["plan_id"], "case_id": case["case_id"], "system_id": "B1"},
    )
    assert response.status_code == 503
    assert fakes[0].calls == [] and fakes[1].runs == {}
