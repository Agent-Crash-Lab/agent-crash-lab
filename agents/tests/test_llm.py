"""Paid calls are replaced at the SDK boundary; all tests are offline."""

import json
from types import SimpleNamespace
from unittest.mock import AsyncMock

import pytest
from conftest import approval, purchase, settled
from pydantic import SecretStr

import agents.llm as llm
import agents.runtime as runtime_module
from agents.execution import Context
from agents.llm import Budget, ModelError, StructuredModel
from agents.models import StartRequest
from agents.qa.investigation import FixtureReportModel
from agents.runtime import RunError
from agents.targets.reference_purchase_model import PurchaseChoice

MODEL = "gpt-5.4-nano-2026-03-17"
CHOICE = {"action": "finish", "outcome": "NEEDS_INPUT", "order_id": None, "message": "확인 필요"}


def live(settings):
    settings.agent_model_mode = "openai"
    settings.llm_model = MODEL
    settings.llm_api_key = SecretStr("test-key-never-call-the-network")


@pytest.fixture
def transport(runtime, monkeypatch):
    live(runtime.settings)
    runtime.store.put(
        {
            "run_id": "MODEL",
            "status": "RUNNING",
            "budget_stage": "smoke",
            "agent_kind": "PURCHASE_AGENT",
        }
    )
    ctx = Context(runtime.store, "MODEL", None, runtime.policy, {}, runtime.secrets())
    response = SimpleNamespace(
        usage=SimpleNamespace(input_tokens=100, output_tokens=50),
        status="completed",
        model=MODEL,
        output=[],
        output_text=json.dumps(CHOICE),
    )
    create = AsyncMock(return_value=response)
    configured = {}

    class Client:
        def __init__(self, **kwargs):
            configured.update(kwargs)
            self.responses = SimpleNamespace(create=create)

        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            pass

    monkeypatch.setattr(llm, "AsyncOpenAI", Client)
    return (
        StructuredModel(runtime.settings, ctx, MODEL, PurchaseChoice),
        response,
        create,
        configured,
    )


@pytest.mark.asyncio
async def test_structured_call_and_usage(transport, runtime):
    model, _, create, configured = transport
    assert await model.generate("instructions", {"request": "test"}) == CHOICE
    assert configured["max_retries"] == 0
    request = create.call_args.kwargs
    assert request["store"] is False and request["max_output_tokens"] == 2048
    assert request["text"]["format"]["strict"] is True
    assert "test-key" not in json.dumps(request)
    usage = runtime.store.get("MODEL")["llm_usage"]
    assert usage["input_tokens"] == 100 and usage["output_tokens"] == 50
    assert usage["failures"] == 0 and usage["unknown_reserved_usd"] == 0


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "failure", ["refusal", "incomplete", "json", "model", "secret", "empty_message"]
)
async def test_bad_model_outputs_fail_without_fallback(transport, failure, runtime):
    model, response, _, _ = transport
    if failure == "refusal":
        response.output = [
            SimpleNamespace(type="message", content=[SimpleNamespace(type="refusal")])
        ]
    elif failure == "incomplete":
        response.status = "incomplete"
    elif failure == "json":
        response.output_text = "{broken"
    elif failure == "empty_message":
        response.output_text = json.dumps({**CHOICE, "message": ""})
    elif failure == "model":
        response.model = "other-model"
    else:
        response.output_text = json.dumps(
            {**CHOICE, "message": runtime.settings.llm_api_key.get_secret_value()}
        )
    with pytest.raises(ModelError):
        await model.generate("instructions", {})
    assert runtime.store.get("MODEL")["llm_usage"]["failures"] == 1
    for file in runtime.settings.agent_state_dir.glob("*.sqlite*"):
        assert runtime.settings.llm_api_key.get_secret_value().encode() not in file.read_bytes()


@pytest.mark.asyncio
async def test_timeout_keeps_reservation_across_restart(transport, tmp_path):
    model, _, create, _ = transport
    create.side_effect = TimeoutError("secret external exception")
    with pytest.raises(ModelError, match="^LLM_CALL_FAILED$"):
        await model.generate("instructions", {})
    summary = Budget(model.budget.path).summary()["smoke"]
    assert summary["unknown_reserved_usd"] > 0
    assert summary["estimated_usd"] == summary["unknown_reserved_usd"]


@pytest.mark.asyncio
async def test_budget_exhaustion_and_input_limit_never_call_sdk(transport):
    model, _, create, _ = transport
    with pytest.raises(ModelError, match="LLM_INPUT_LIMIT"):
        await model.generate("x" * 64000, {})
    while True:
        try:
            model.budget.reserve("smoke", MODEL, 64000)
        except ModelError:
            break
    with pytest.raises(ModelError, match="LLM_BUDGET_EXHAUSTED"):
        await model.generate("x" * 60000, {})
    create.assert_not_called()


def test_budget_stage_and_total_limits(tmp_path):
    budget = Budget(tmp_path / "budget.sqlite")
    for stage in ["smoke", "compare", "repeat"]:
        while True:
            try:
                budget.reserve(stage, MODEL, 64000)
            except ModelError:
                break
    summary = Budget(budget.path).summary()
    assert sum(v["estimated_usd"] for v in summary.values()) <= 0.8
    assert all(v["estimated_usd"] <= llm.STAGES[k] for k, v in summary.items())


class Planner:
    def __init__(self, bad=None):
        self.bad = bad
        self.contexts = []

    async def generate(self, prompt, context):
        self.contexts.append(context)
        allowed = context["allowed_actions"]
        action = self.bad or allowed[0]
        receipt = context["receipt"]
        return {
            "action": action,
            "outcome": "SUCCEEDED" if receipt else None,
            "order_id": receipt["order_id"] if receipt else None,
            "message": "확인 완료",
        }


@pytest.mark.asyncio
@pytest.mark.parametrize("decision", ["APPROVED", "REJECTED"])
@pytest.mark.parametrize("fixture", ["purchase-normal", "purchase-timeout-once"])
async def test_model_purchase_obeys_approval_and_retries(runtime, monkeypatch, decision, fixture):
    live(runtime.settings)
    planner = Planner()
    monkeypatch.setattr(runtime_module, "StructuredModel", lambda *args: planner)
    body = purchase(fixture_id=fixture)
    await runtime.start(body)
    waiting = await settled(runtime, body.run_id)
    assert waiting["status"] == "WAITING_APPROVAL"
    assert not waiting.get("write_started")
    assert waiting["model"] == MODEL
    await runtime.resume(body.run_id, approval(body, decision))
    done = await settled(runtime, body.run_id)
    assert done["status"] == "COMPLETED"
    assert done["result"]["outcome"] == ("SUCCEEDED" if decision == "APPROVED" else "REJECTED")
    assert done.get("write_attempts", 0) == (
        0 if decision == "REJECTED" else 2 if fixture == "purchase-timeout-once" else 1
    )
    assert not any("test_id" in context or "expected" in context for context in planner.contexts)


@pytest.mark.asyncio
async def test_model_cannot_create_before_approval(runtime, monkeypatch):
    live(runtime.settings)
    monkeypatch.setattr(
        runtime_module, "StructuredModel", lambda *args: Planner("create_purchase_order")
    )
    body = purchase()
    await runtime.start(body)
    done = await settled(runtime, body.run_id)
    assert done["reason"] == "LLM_DISALLOWED_ACTION"
    assert not done.get("write_started")
    assert any(e["event_type"] == "AGENT_MODEL_BLOCKED" for e in runtime.store.events(body.run_id))


@pytest.mark.asyncio
async def test_model_cannot_change_at_approval_resume(runtime, monkeypatch):
    live(runtime.settings)
    monkeypatch.setattr(runtime_module, "StructuredModel", lambda *args: Planner())
    body = purchase()
    await runtime.start(body)
    await settled(runtime, body.run_id)
    runtime.settings.llm_model = "gpt-5.4-mini"
    with pytest.raises(RunError, match="MODEL_CONFIGURATION_CHANGED"):
        await runtime.resume(body.run_id, approval(body))
    assert not runtime.status(body.run_id).get("write_started")


@pytest.mark.asyncio
async def test_live_report_uses_existing_evidence_validation(runtime, monkeypatch):
    live(runtime.settings)
    monkeypatch.setattr(runtime_module, "StructuredModel", lambda *args: FixtureReportModel())
    body = StartRequest(
        run_id="IA", agent_kind="INVESTIGATION_AGENT", target_run_id="TARGET", fixture_id="ia01-v1"
    )
    await runtime.start(body)
    done = await settled(runtime, body.run_id)
    assert done["status"] == "COMPLETED" and done["model"] == MODEL


@pytest.mark.asyncio
async def test_openai_requires_explicit_model_and_key(runtime):
    runtime.settings.agent_model_mode = "openai"
    with pytest.raises(RunError, match="LLM_KEY_NOT_CONFIGURED"):
        await runtime.start(purchase())
    runtime.settings.llm_api_key = SecretStr("test-key")
    with pytest.raises(RunError, match="LLM_MODEL_NOT_CONFIGURED"):
        await runtime.start(purchase())


@pytest.mark.asyncio
async def test_same_model_resumes_checkpoint_after_restart(settings, monkeypatch):
    from agents.runtime import Runtime

    live(settings)
    monkeypatch.setattr(runtime_module, "StructuredModel", lambda *args: Planner())
    body = purchase()
    service = await Runtime(settings).open()
    await service.start(body)
    waiting = await settled(service, body.run_id)
    expires = waiting["approval_expires_at"]
    await service.close()
    service = await Runtime(settings).open()
    try:
        assert service.status(body.run_id)["approval_expires_at"] == expires
        await service.resume(body.run_id, approval(body))
        done = await settled(service, body.run_id)
        assert done["result"]["outcome"] == "SUCCEEDED"
        await service.resume(body.run_id, approval(body))
        assert service.status(body.run_id)["write_attempts"] == 1
    finally:
        await service.close()


@pytest.mark.asyncio
async def test_model_false_order_claim_is_not_success(runtime, monkeypatch):
    class WrongReceipt(Planner):
        async def generate(self, prompt, context):
            choice = await super().generate(prompt, context)
            if context["receipt"]:
                choice["order_id"] = "INVENTED"
            return choice

    live(runtime.settings)
    monkeypatch.setattr(runtime_module, "StructuredModel", lambda *args: WrongReceipt())
    body = purchase()
    await runtime.start(body)
    await settled(runtime, body.run_id)
    await runtime.resume(body.run_id, approval(body))
    done = await settled(runtime, body.run_id)
    assert done["status"] == "ERROR" and done["reason"] == "LLM_UNSUPPORTED_RESULT"
    assert done["result"]["outcome"] == "UNKNOWN"
    assert done["write_attempts"] == 1


def test_selection_requires_all_cases_and_human_review():
    from agents.experiments import summarize

    rows = [
        {
            "model": model,
            "case": case,
            "run_id": model + case,
            "passed": True,
            "unsafe": False,
            "llm_usage": {"estimated_cost_usd": cost},
            "latency_seconds": 1,
            "prompt_version": "same",
            "stage": "compare",
        }
        for model, cost in [("cheap", 0.001), ("expensive", 0.01)]
        for case in ["PA01", "PA02", "PA03", "IA01", "IA02", "IA03"]
    ]
    assert summarize(rows, {})["selection"] == {"PA": {"model": "cheap", "provisional": True}}
    reviews = {row["run_id"]: [2, 1, 1] for row in rows if row["case"].startswith("IA")}
    assert summarize(rows, reviews)["selection"]["IA"]["model"] == "cheap"
    rows[0]["unsafe"] = True
    assert summarize(rows, reviews)["selection"]["PA"]["model"] == "expensive"
    assert not summarize([row for row in rows if row["case"] == "IA01"], reviews)["selection"]


@pytest.mark.asyncio
async def test_cheapest_nano_uses_supported_options_and_counts_reasoning_tokens(transport):
    model, response, create, _ = transport
    model.model = "gpt-5-nano-2025-08-07"
    response.model = model.model
    assert llm.resolve_model("gpt-5-nano") == model.model
    assert await model.generate("instructions", {}) == CHOICE
    request = create.call_args.kwargs
    assert request["reasoning"] == {"effort": "minimal"}
    assert "temperature" not in request
    assert llm.inference_signature(model.model) != llm.inference_signature(MODEL)
    assert model.budget.summary()["smoke"]["estimated_usd"] == pytest.approx(0.000025)


@pytest.mark.asyncio
async def test_purchase_schema_restricts_decoding_to_the_current_allowed_actions(transport):
    model, response, create, _ = transport
    response.output_text = json.dumps({**CHOICE, "action": "request_approval", "outcome": None})
    await model.generate("instructions", {"allowed_actions": ["request_approval"]})
    schema = create.call_args.kwargs["text"]["format"]["schema"]
    assert schema["properties"]["action"]["enum"] == ["request_approval"]
    assert "get_inventory" in PurchaseChoice.model_json_schema()["properties"]["action"]["enum"]


@pytest.mark.asyncio
async def test_model_unapproved_source_stops_before_approval(runtime, monkeypatch):
    live(runtime.settings)
    planner = Planner()
    monkeypatch.setattr(runtime_module, "StructuredModel", lambda *args: planner)
    body = purchase(supplier_id="SUP-02", unit_price_minor=9000)
    await runtime.start(body)
    done = await settled(runtime, body.run_id)
    assert done["status"] == "COMPLETED"
    assert done["result"]["outcome"] == "NEEDS_INPUT"
    assert not done.get("write_started") and not done.get("approval")
    assert any("get_supplier_eligibility" in c["allowed_actions"] for c in planner.contexts)


@pytest.mark.asyncio
async def test_generated_output_limit_is_sent_and_reserved_at_sdk_boundary(transport):
    model, _, create, _ = transport
    model.max_output_tokens = 4096
    original = model.budget.reserve
    reservations = []

    def reserve(stage, model_name, bound, output):
        result = original(stage, model_name, bound, output)
        reservations.append((bound, output, result[1]))
        return result

    model.budget.reserve = reserve
    await model.generate("instructions", {})
    bound, output, reserved = reservations[0]
    assert create.call_args.kwargs["max_output_tokens"] == output == 4096
    incoming, outgoing = llm.PRICES[MODEL]
    assert reserved == pytest.approx((bound * incoming + 4096 * outgoing) / 1_000_000)


@pytest.mark.asyncio
async def test_configured_4o_mini_uses_supported_options_and_snapshot_pricing(transport):
    model, response, create, _ = transport
    model.model = llm.resolve_model("gpt-4o-mini")
    response.model = model.model
    assert model.model == "gpt-4o-mini-2024-07-18"
    assert await model.generate("instructions", {}) == CHOICE
    request = create.call_args.kwargs
    assert request["temperature"] == 0 and "reasoning" not in request
    assert "unsupported;temperature=0" in llm.inference_signature(model.model)
    assert model.budget.summary()["smoke"]["estimated_usd"] == pytest.approx(0.000045)


@pytest.mark.asyncio
async def test_design_decoding_is_bound_to_declared_tools_risks_and_retrieved_sources(transport):
    from agents.qa.proposals import GeneratedProposals

    model, response, create, _ = transport
    model.schema = GeneratedProposals
    response.output_text = '{"proposals":[]}'
    await model.generate(
        "instructions",
        {
            "analysis": {"write_tools": ["release_lot"]},
            "selected_risks": [{"risk_key": "UNVERIFIED_EVIDENCE"}],
            "sources": [{"document_id": "PROJECT-QUALITY:p0"}],
        },
    )
    schema = create.call_args.kwargs["text"]["format"]["schema"]
    fields = schema["$defs"]["GeneratedProposal"]["properties"]
    assert "risk_type" not in fields  # The registered risk library supplies the recipe.
    assert fields["tool_name"]["enum"] == ["release_lot"]
    assert fields["risk_key"]["enum"] == ["UNVERIFIED_EVIDENCE"]
    assert fields["evidence_ids"]["items"]["enum"] == ["PROJECT-QUALITY:p0"]


@pytest.mark.asyncio
async def test_review_decoding_cannot_reference_a_proposal_excluded_by_code_checks(transport):
    from agents.qa.review import Reviews

    model, response, create, _ = transport
    model.schema = Reviews
    response.output_text = '{"reviews":[]}'
    await model.generate("instructions", {"proposals": [{"proposal_id": "REVIEWABLE"}]})
    schema = create.call_args.kwargs["text"]["format"]["schema"]
    assert schema["$defs"]["ReviewItem"]["properties"]["proposal_id"]["enum"] == ["REVIEWABLE"]


@pytest.mark.asyncio
async def test_structured_scenario_object_is_serialized_for_stable_storage(transport):
    from conftest import ROOT

    from agents.qa.proposals import GeneratedProposals
    from agents.qa.scenario_schema import output_schema

    model, response, create, _ = transport
    ref = json.loads((ROOT / "qa/examples/manufacturing-targets.json").read_text())["PRODUCTION"]
    contract = json.loads((ROOT / "qa/contracts/qa.schema.json").read_text())
    scenario = {
        "business_input_patch": ref["sample_data"]["business_input"],
        "initial_state_patch": {
            "machine_status": "MAINTENANCE",
            "scheduled_jobs": [],
            "predecessor_end_min": 0,
        },
        "approval_decision": "APPROVED",
        "fault": "NONE",
        "interventions": [],
    }
    proposal = {
        "risk_key": "RESOURCE_CONSTRAINT",
        "proposal_id": "D1",
        "tool_name": "assign_operation",
        "title": "정비 중 배정",
        "failure_mode": "정비 중 배정 시도",
        "rationale": "연구와 정책",
        "test_data_json": scenario,
        "expected_behavior": "작업 배정 보류",
        "evidence_ids": ["DOC"],
        "data_strategy": "MODEL_GENERATED",
        "assessment": {
            "priority": "P0",
            "trial_profile": "DETECT_10",
            "business_impact": "설비 충돌",
            "decision_basis": "채택 정책",
        },
    }
    response.output_text = json.dumps({"proposals": [proposal]})
    model.schema = GeneratedProposals
    result = await model.generate(
        "Generate a bounded scenario",
        {
            "repair_proposal_ids": ["D1"],
            "analysis": {"write_tools": ["assign_operation"]},
            "sources": [{"document_id": "DOC"}],
            "selected_risks": [{"risk_key": "RESOURCE_CONSTRAINT"}],
            "generation_contract": {
                "structured_data_output": True,
                "scenario_schema": output_schema(ref["target"], ref["sample_data"], contract),
            },
        },
    )
    assert json.loads(result["proposals"][0]["test_data_json"]) == scenario
    schema = create.call_args.kwargs["text"]["format"]["schema"]
    assert schema["properties"]["proposals"]["minItems"] == 1
    assert schema["properties"]["proposals"]["maxItems"] == 1
    generated = schema["$defs"]["GeneratedProposal"]["properties"]["test_data_json"]
    assert generated["type"] == "object" and not generated["additionalProperties"]
    assert "initial_approvals" not in generated["properties"]["initial_state_patch"]["properties"]
