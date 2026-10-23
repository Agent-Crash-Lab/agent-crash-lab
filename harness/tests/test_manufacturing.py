import asyncio
import copy
import importlib.util
import json

import httpx
import pytest
from conftest import ROOT

from harness.adapters.manufacturing import CONDITIONS, domain_errors
from harness.catalog import Catalog
from harness.config import Settings
from harness.events import EventLog
from harness.runner import Runner
from harness.simulation import Decision, SimulationError
from harness.store import Store

spec = importlib.util.spec_from_file_location(
    "reference_manufacturing", ROOT / "agents/src/agents/targets/manufacturing.py"
)
reference = importlib.util.module_from_spec(spec)
spec.loader.exec_module(reference)


@pytest.fixture
def runtime(tmp_path):
    settings = Settings(
        database_url=f"sqlite:///{tmp_path}/state.db",
        harness_project_root=ROOT,
        internal_api_token="test",
        simulation_callback_base="http://sandbox",
    )
    catalog = Catalog(ROOT)
    store = Store(settings.database_url)
    events = EventLog(store, catalog.event_schema, hold_seconds=0)
    runner = Runner(settings, catalog, store, events, None, None)
    yield runner
    store.close()


def configure_reference(runner):
    sim = runner.simulations

    async def transport(request):
        run_id = request.url.path.split("/")[-2]
        result = await sim.rpc(
            run_id, request.headers.get("authorization"), json.loads(request.content)
        )
        return httpx.Response(200, json=result)

    async def dispatch(runtime_id, body):
        async with httpx.AsyncClient(transport=httpx.MockTransport(transport)) as client:
            return await reference.execute_reference(reference.SimulationTask(**body), client)

    sim.dispatch = dispatch


async def run_case(runner, kind, risk, system="B1"):
    ref = runner.catalog.planner.target_input(kind)
    plan = runner.catalog.planner.build(ref["target"], ref["sample_data"])
    assert runner.catalog.planner.rebuild(plan) == plan
    case = next(c for c in plan["cases"] if c["risk_id"] == risk)
    assert case["execution"]["status"] == "READY"
    runner.store.put_plan(plan, "requester")
    run = await runner.create_run(None, system, "requester", plan["plan_id"], case["case_id"])
    run_id = run["run_id"]
    for _ in range(300):
        run = runner.store.get_run(run_id)
        if run["status"] == "WAITING_APPROVAL":
            body = Decision(
                **{
                    **{
                        k: run["approval_request"][k]
                        for k in ("approval_request_id", "payload_hash")
                    },
                    "decision": case["simulation"]["approval_decision"] or "APPROVED",
                }
            )
            await runner.simulations.decide(run_id, body, "test-approver")
        # A non-PASS run investigates after its terminal status.
        if run["status"] in {"COMPLETED", "ERROR"} and run["investigation"]["status"] != "RUNNING":
            await runner.close()
            return runner.store.get_run(run_id)
        await asyncio.sleep(0.001)
    raise AssertionError("simulation did not finish")


@pytest.mark.parametrize(
    "kind,risk", [(k, risk) for k, conditions in CONDITIONS.items() for risk in conditions]
)
@pytest.mark.parametrize("system", ["B0", "B1"])
async def test_reference_agent_runs_tools_and_independent_database_judges(
    runtime, kind, risk, system
):
    configure_reference(runtime)
    run = await run_case(runtime, kind, risk, system)
    assert run["status"] == "COMPLETED", run
    state = runtime.store.get_simulation(run["run_id"])
    assert state["closed"] and state["calls"]
    assert run["run_id"] not in runtime.simulations.sessions
    if risk == "POST_COMMIT_RESPONSE_LOSS" and system == "B0":
        assert len(state["changes"]) == 2
        assert run["summary"]["FAIL"] >= 1
        assert run["investigation"]["validation"]["passed"]
    else:
        assert run["summary"]["FAIL"] == run["summary"]["INCONCLUSIVE"] == 0
    if risk not in {"CONTROL_BASELINE", "APPROVAL_DENIED", "POST_COMMIT_RESPONSE_LOSS"}:
        assert not state["changes"] and not state["approval"]
        assert domain_errors(kind, state["request"], state["initial_state"]) == [risk]
    assert "sandbox_token" not in json.dumps(runtime.store.get_run(run["run_id"]))
    with pytest.raises(SimulationError, match="INVALID_SANDBOX_CREDENTIAL"):
        runtime.simulations.authenticate(run["run_id"], "Bearer expired")


@pytest.mark.parametrize("system", ["B0", "B1"])
async def test_unsafe_agent_attempt_and_server_block_are_distinguished(runtime, system):
    async def unsafe(runtime_id, body):
        run_id = body["mcp_url"].split("/")[-2]
        await runtime.simulations.call(
            run_id, "get_inspection", {"lot_id": body["request"]["lot_id"]}
        )
        await runtime.simulations.call(run_id, "request_approval", {})
        result = await runtime.simulations.call(run_id, "release_lot", body["request"])
        return {
            "status": "HELD" if "code" in result else "COMPLETED",
            "commit_count": 0 if "code" in result else 1,
        }

    runtime.simulations.dispatch = unsafe
    run = await run_case(runtime, "QUALITY", "UNVERIFIED_EVIDENCE", system)
    by_scope = {c["scope"]: c["verdict"] for c in run["checks"] if c["rule_id"] == "M_DOMAIN"}
    assert by_scope["agent_behavior"] == "FAIL"
    assert by_scope["business_state"] == ("PASS" if system == "B1" else "FAIL")


async def test_claimed_success_without_tool_execution_never_passes(runtime):
    async def fabricated(*args):
        return {"status": "COMPLETED", "commit_count": 1}

    runtime.simulations.dispatch = fabricated
    run = await run_case(runtime, "PRODUCTION", "CONTROL_BASELINE")
    assert run["summary"]["FAIL"] and run["summary"]["INCONCLUSIVE"]
    assert runtime.store.get_simulation(run["run_id"])["changes"] == []


def test_sample_cannot_claim_another_machine_or_fabricate_inspection(runtime):
    for kind in CONDITIONS:
        ref = runtime.catalog.planner.target_input(kind)
        adapter = runtime.catalog.planner.adapters[ref["target"]["simulation_adapter"]]
        sample = copy.deepcopy(ref["sample_data"])
        key = "machine_id" if kind == "PRODUCTION" else "lot_id"
        sample["business_input"][key] = "OTHER"
        assert not adapter["supports_sample"](sample)


async def test_unconfigured_external_endpoint_is_not_executable(runtime):
    with pytest.raises(SimulationError, match="EXTERNAL_RUNTIME_NOT_CONFIGURED"):
        await runtime.simulations.profile("external-arbitrary-v1")


async def test_external_profile_is_version_pinned_and_does_not_return_secrets(runtime, monkeypatch):
    entry = {
        "url": "http://approved-agent",
        "token": "external-secret",
        "agent_type": "QUALITY",
        "agent_version": "v1",
        "prompt_version": "p1",
        "model_kind": "deterministic",
        "model": "external-reference",
        "run_cost_upper_bound_usd": 0,
    }
    runtime.settings.external_agent_endpoints = json.dumps({"external-quality-v1": entry})
    # Settings assignment is not validated; use the same SecretStr type as production settings.
    from pydantic import SecretStr

    runtime.settings.external_agent_endpoints = SecretStr(runtime.settings.external_agent_endpoints)
    actual = {
        k: entry[k]
        for k in ("agent_type", "agent_version", "prompt_version", "model_kind", "model")
    }
    requests = []

    def handler(request):
        requests.append(request)
        return httpx.Response(200, json=actual)

    original = httpx.AsyncClient
    monkeypatch.setattr(
        "harness.simulation.httpx.AsyncClient",
        lambda **kw: original(transport=httpx.MockTransport(handler), **kw),
    )
    profile = await runtime.simulations.profile("external-quality-v1")
    assert requests[0].headers["Authorization"] == "Bearer external-secret"
    assert "external-secret" not in json.dumps(profile)
    actual["agent_version"] = "v2"
    with pytest.raises(SimulationError, match="EXTERNAL_RUNTIME_VERSION_CHANGED"):
        await runtime.simulations.profile("external-quality-v1")


def test_production_and_quality_registration_binding_requires_explicit_runtime(client, fakes):
    async def analyze(body):
        return {"risk_screening": []}

    fakes[1].analyze = analyze
    for kind in CONDITIONS:
        ref = client.get(f"/api/qa/target?target_type={kind}").json()
        target = ref["target"]
        body = {
            "name": kind + " test",
            "version": "1",
            "agent_type": kind,
            **{
                k: target[k]
                for k in ("task", "industry_context", "tools", "policies", "business_input_schema")
            },
            "sample_data": ref["sample_data"],
            "capability_bindings": target["qa_scope"]["capabilities"],
            "excluded_capabilities": target["qa_scope"]["excluded_capabilities"],
        }
        unbound = client.post("/api/qa/registrations", json=body).json()
        assert unbound["execution_status"] == "ADAPTER_REQUIRED"
        body["execution_runtime"] = f"reference-{kind.lower()}-v1"
        bound = client.post("/api/qa/registrations", json=body)
        assert bound.status_code == 200, bound.text
        assert bound.json()["execution_status"] == "CONNECTED"
        body["execution_runtime"] = "external-unknown"
        assert client.post("/api/qa/registrations", json=body).status_code == 422


async def test_approval_before_later_authorization_is_still_a_failed_attempt(runtime):
    async def premature(runtime_id, body):
        run_id = body["mcp_url"].split("/")[-2]
        await runtime.simulations.call(
            run_id, "get_inspection", {"lot_id": body["request"]["lot_id"]}
        )
        denied = await runtime.simulations.call(run_id, "release_lot", body["request"])
        assert denied["code"] == "APPROVAL_REQUIRED"
        await runtime.simulations.call(run_id, "request_approval", {})
        await runtime.simulations.call(run_id, "release_lot", body["request"])
        return {"status": "COMPLETED", "commit_count": 1}

    runtime.simulations.dispatch = premature
    run = await run_case(runtime, "QUALITY", "CONTROL_BASELINE")
    rows = {c["scope"]: c["verdict"] for c in run["checks"] if c["rule_id"] == "M_APPROVAL"}
    assert rows == {"agent_behavior": "FAIL", "business_state": "PASS"}


def test_public_approval_and_sandbox_callbacks_do_not_accept_requester_or_internal_tokens(client):
    response = client.post(
        "/api/qa/runs/absent/approval",
        json={"approval_request_id": "A", "payload_hash": "x", "decision": "APPROVED"},
    )
    assert response.status_code == 403
    response = client.post(
        "/simulations/absent/mcp",
        headers={"Authorization": "Bearer internal-token"},
        json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
    )
    assert response.status_code == 401


async def test_sandbox_tokens_are_scoped_and_mcp_initialization_does_not_expose_state(runtime):
    reference = runtime.catalog.planner.target_input("PRODUCTION")
    runtime.simulations.sessions["one"] = {
        "token": "test-run-token",
        "deadline": float("inf"),
        "rpc_calls": 0,
        "target": reference["target"],
    }
    with pytest.raises(SimulationError):
        runtime.simulations.authenticate("two", "Bearer test-run-token")
    initialized = await runtime.simulations.rpc(
        "one", "Bearer test-run-token", {"jsonrpc": "2.0", "id": 1, "method": "initialize"}
    )
    assert initialized["result"]["protocolVersion"] == "2025-11-25"
    listing = await runtime.simulations.rpc(
        "one", "Bearer test-run-token", {"jsonrpc": "2.0", "id": 2, "method": "tools/list"}
    )
    assert {t["name"] for t in listing["result"]["tools"]} >= {
        "assign_operation",
        "request_approval",
        "get_changes",
    }
    assert "initial_state" not in json.dumps(initialized)


async def test_r10_counts_invalid_calls_and_stops_before_business_change(runtime):
    async def runaway(runtime_id, body):
        run_id = body["mcp_url"].split("/")[-2]
        for number in range(13):
            await runtime.simulations.rpc(
                run_id,
                "Bearer " + body["sandbox_token"],
                {
                    "jsonrpc": "2.0",
                    "id": number,
                    "method": "tools/call",
                    "params": {"name": "UNKNOWN_TOOL", "arguments": {}},
                },
            )
        return {"status": "HELD", "commit_count": 0}

    runtime.simulations.dispatch = runaway
    run = await run_case(runtime, "QUALITY", "CONTROL_BASELINE")
    check = next(c for c in run["checks"] if c["rule_id"] == "R10")
    assert check["verdict"] == "FAIL" and check["evidence_ids"]
    assert run["agent"]["measured"]["tool_calls"] == 13
    state = runtime.store.get_simulation(run["run_id"])
    assert not state["changes"] and len(state["tool_attempts"]) == 13
    assert len(state["calls"]) == 0


async def test_r10_cancels_hung_target_and_closes_sandbox(runtime):
    runtime.settings.poll_interval_seconds = 0.001
    runtime.settings.runner_deadline_seconds = 0.01

    async def hung(runtime_id, body):
        await asyncio.Event().wait()

    runtime.simulations.dispatch = hung
    run = await run_case(runtime, "PRODUCTION", "CONTROL_BASELINE")
    assert run["status"] == "COMPLETED"
    assert run["agent"]["termination"] == "RUNNER_TIMEOUT"
    assert next(c for c in run["checks"] if c["rule_id"] == "R10")["verdict"] == "FAIL"
    assert runtime.store.get_simulation(run["run_id"])["closed"]
    assert run["run_id"] not in runtime.simulations.sessions

    from harness.reporting import qa_report

    assert qa_report(run)["conclusion"] == "VIOLATION_FOUND"


async def test_manufacturing_active_time_excludes_human_approval_wait(runtime):
    import time

    configure_reference(runtime)
    runtime.settings.poll_interval_seconds = 0.005
    runtime.catalog.config["execution"]["max_active_seconds_per_agent"] = 0.2
    ref = runtime.catalog.planner.target_input("QUALITY")
    plan = runtime.catalog.planner.build(ref["target"], ref["sample_data"])
    runtime.store.put_plan(plan, "requester")
    case = next(c for c in plan["cases"] if c["risk_id"] == "CONTROL_BASELINE")
    started = await runtime.create_run(None, "B1", "requester", plan["plan_id"], case["case_id"])
    began = time.monotonic()
    decided = False
    for _ in range(500):
        run = runtime.store.get_run(started["run_id"])
        if run["status"] == "WAITING_APPROVAL" and not decided:
            await asyncio.sleep(0.4)
            approval = run["approval_request"]
            await runtime.simulations.decide(
                run["run_id"],
                Decision(
                    approval_request_id=approval["approval_request_id"],
                    payload_hash=approval["payload_hash"],
                    decision="APPROVED",
                ),
                "approver",
            )
            decided = True
        if run["status"] in {"COMPLETED", "ERROR"}:
            await runtime.close()
            break
        await asyncio.sleep(0.005)
    assert decided and time.monotonic() - began >= 0.4
    assert run["status"] == "COMPLETED"
    assert run["agent"]["measured"]["active_seconds"] < 0.2
    assert next(c for c in run["checks"] if c["rule_id"] == "R10")["verdict"] == "PASS"
