import json

import pytest
from conftest import ROOT, TOKEN
from fastapi.testclient import TestClient
from test_design import found

from agents.scenario.design import DesignRequest, OfflineDesigner, OfflineReviewer, design_qa
from agents.server import create_app


class NovelModel:
    """A model double: output is not an installed risk fixture or a live LLM call."""

    async def generate(self, prompt, context):
        assert "MODEL_GENERATED" in prompt
        assert "Domain-specific tests use UNCHANGED" not in prompt
        assert context["base_sample"]["business_input"]["machine_id"] == "M1"
        operations = context["analysis"]["manufacturing_context"]
        assert operations["domain_id"] == "MANUFACTURING_OPERATIONS"
        assert len(operations["features"]) == 4
        assert len(operations["scenario_examples"]) == 2
        assert any("millisecond" in s for s in operations["generation_rules_en"])
        assert context["generation_contract"]["state_schema"]["properties"]["machine_status"]
        assert all("payload" not in example for example in operations["scenario_examples"])
        assert all("test_data" not in risk for risk in context["selected_risks"])
        assert context["generation_contract"]["fixed_identity"]["machine_id"] == "M1"
        resource_options = context["evidence_options"]["RESOURCE_CONSTRAINT"]
        assert resource_options["MANUFACTURING"]
        assert resource_options["AGENTIC"]
        assert not set(resource_options["PROJECT_POLICY"]) & set(
            resource_options["MANUFACTURING"] + resource_options["AGENTIC"]
        )
        example_context = {
            **context,
            "selected_risks": [{**risk, "test_data": {}} for risk in context["selected_risks"]],
        }
        base = await OfflineDesigner().generate(prompt, example_context)
        item = next(p for p in base["proposals"] if p["risk_key"] == "RESOURCE_CONSTRAINT")
        item.update(
            proposal_id="NOVEL_AFTER_APPROVAL",
            exception_ids=[
                e["exception_id"]
                for e in context["morphology"]["exception_catalog"]
                if e["condition"] in {"MAINTENANCE", "PREDECESSOR_DELAY"}
                and e["phase"] == "AFTER_APPROVAL_BEFORE_WRITE"
            ],
            data_strategy="MODEL_GENERATED",
            title="승인 직후 정비·선행 공정 지연이 동시에 발생",
            test_data_json=json.dumps(
                {
                    "business_input_patch": {"start_min": 731, "end_min": 797},
                    "initial_state_patch": {"scheduled_jobs": [], "predecessor_end_min": 730},
                    "approval_decision": "APPROVED",
                    "fault": "NONE",
                    "interventions": [
                        {
                            "phase": "AFTER_APPROVAL_BEFORE_WRITE",
                            "state_patch": {
                                "machine_status": "MAINTENANCE",
                                "predecessor_end_min": 740,
                            },
                        }
                    ],
                }
            ),
        )
        item.pop("risk_type")
        return {"proposals": [item]}


def production():
    item = json.loads((ROOT / "qa/examples/manufacturing-targets.json").read_text())["PRODUCTION"]
    return DesignRequest(**{k: item[k] for k in ("target", "sample_data")}, generation_mode="llm")


@pytest.mark.asyncio
async def test_llm_data_is_retained_and_reviewed_with_real_retrieval_contract(settings):
    class Reviewer(OfflineReviewer):
        async def generate(self, prompt, context):
            assert context["base_sample"] == production().sample_data
            assert context["generation_contract"]["supported_interventions"]
            return await super().generate(prompt, context)

    result = await design_qa(
        settings, production(), model=NovelModel(), search=found, reviewer=Reviewer()
    )
    assert result["version"] == "4.0.0"
    assert result["model_kind"] == "injected_model" and not result["llm_usage"]
    assert result["data_generation"] == "MODEL_AUTHORED_PATCHES"
    assert result["proposals"][0]["risk_type"] == "DOMAIN_CONSTRAINT"
    assert result["reviews"][0]["decision"] == "ACCEPT_FOR_BINDING"
    assert len(result["proposals"][0]["exception_ids"]) == 2
    assert result["agent_roles"]["designer"] == "SCENARIO_AGENT"
    payload = json.loads(result["proposals"][0]["test_data_json"])
    assert payload["business_input_patch"]["start_min"] == 731
    assert payload["interventions"][0]["state_patch"]["predecessor_end_min"] == 740


@pytest.mark.asyncio
@pytest.mark.parametrize("mutation", ["unimplemented", "undeclared-compound"])
async def test_exception_support_and_declared_compound_are_checked_before_review(
    settings, mutation
):
    class InvalidException(NovelModel):
        async def generate(self, prompt, context):
            result = await super().generate(prompt, context)
            p = result["proposals"][0]
            if mutation == "unimplemented":
                p["exception_ids"] = [
                    e["exception_id"]
                    for e in context["morphology"]["exception_catalog"]
                    if e["risk_key"] == p["risk_key"] and e["condition"] == "STALE_TOOL_RESULT"
                ]
            else:
                p["exception_ids"] = p["exception_ids"][:1]
            return result

    class NeverReview:
        async def generate(self, *args):
            raise AssertionError("Invalid exception applications must not reach a paid review")

    result = await design_qa(
        settings, production(), model=InvalidException(), search=found, reviewer=NeverReview()
    )
    row = result["reviews"][0]
    assert row["decision"] == ("NEEDS_INFORMATION" if mutation == "unimplemented" else "REJECT")
    assert ("실행 미지원" if mutation == "unimplemented" else "실제 활성 조건") in " ".join(
        row["reasons"]
    )


def test_per_request_llm_mode_reports_missing_configuration_without_offline_fallback(settings):
    with TestClient(create_app(settings, design_search=found)) as client:
        response = client.post(
            "/internal/qa/design",
            headers={"X-Internal-Token": TOKEN},
            json=production().model_dump(),
        )
        assert response.status_code == 503 and response.json()["detail"] == "LLM_KEY_NOT_CONFIGURED"
        body = production().model_dump()
        body["generation_mode"] = "offline"
        result = client.post("/internal/qa/design", headers={"X-Internal-Token": TOKEN}, json=body)
        assert result.status_code == 200 and result.json()["model_kind"] == "offline"


@pytest.mark.asyncio
async def test_model_cannot_add_executable_code_to_the_scenario(settings):
    class Invalid(NovelModel):
        async def generate(self, prompt, context):
            output = await super().generate(prompt, context)
            payload = json.loads(output["proposals"][0]["test_data_json"])
            payload["execute_python"] = "print('untrusted')"
            output["proposals"][0]["test_data_json"] = json.dumps(payload)
            return output

    from jsonschema import ValidationError

    with pytest.raises(ValidationError):
        await design_qa(
            settings, production(), model=Invalid(), search=found, reviewer=OfflineReviewer()
        )


@pytest.mark.asyncio
async def test_parallel_retrieval_is_bounded_and_rejects_index_changes(settings):
    import asyncio

    active = peak = 0

    async def changing(query):
        nonlocal active, peak
        active += 1
        peak = max(peak, active)
        await asyncio.sleep(0.002)
        result = await found(query)
        active -= 1
        result["index_version"] = query["source_type"]
        return result

    body = production()
    body.generation_mode = "offline"
    with pytest.raises(ValueError, match="index changed"):
        await design_qa(settings, body, search=changing)
    assert 1 < peak <= 4


@pytest.mark.asyncio
async def test_no_applicable_risks_skips_generation_review_and_search(settings):
    class NeverCalled:
        async def generate(self, prompt, context):
            raise AssertionError("No relevant risks: no generation or review needed")

    async def no_search(query):
        raise AssertionError("No applicable risks: no retrieval needed")

    body = production()
    body.target.pop("qa_scope")
    body.target["tools"] = [t for t in body.target["tools"] if t["effect"] == "READ"]
    result = await design_qa(
        settings, body, model=NeverCalled(), reviewer=NeverCalled(), search=no_search
    )
    assert result["proposals"] == result["reviews"] == result["sources"] == []
    assert not result["llm_usage"]


@pytest.mark.asyncio
async def test_unmapped_morphological_dimensions_do_not_send_an_empty_enum_to_the_model(
    settings, monkeypatch
):
    import agents.scenario.design as module

    class NeverCalled:
        async def generate(self, *args):
            raise AssertionError("No supported combination should call a model")

    monkeypatch.setattr(module, "build_field", lambda *args: {"candidates": []})
    result = await design_qa(
        settings, production(), model=NeverCalled(), reviewer=NeverCalled(), search=found
    )
    assert result["proposals"] == result["reviews"] == []
    assert result["morphology"]["unmapped_risks"]


@pytest.mark.asyncio
async def test_generated_test_without_any_citation_is_rejected_before_review(settings):
    from pydantic import ValidationError

    class Uncited(NovelModel):
        async def generate(self, prompt, context):
            result = await super().generate(prompt, context)
            result["proposals"][0]["evidence_ids"] = []
            return result

    class NeverReview:
        async def generate(self, prompt, context):
            raise AssertionError("Uncited generated data must not reach review")

    with pytest.raises(ValidationError):
        await design_qa(
            settings, production(), model=Uncited(), search=found, reviewer=NeverReview()
        )


@pytest.mark.asyncio
@pytest.mark.parametrize("review_model", ["", "gpt-5.4-mini-2026-03-17"])
async def test_configured_live_design_constructs_both_models_with_valid_budgets(
    settings, monkeypatch, review_model
):
    from pydantic import SecretStr

    import agents.scenario.design as module

    settings.llm_api_key = SecretStr("test-key-never-call-network")
    settings.llm_model = "gpt-4o-mini"
    settings.qa_review_llm_model = review_model
    calls = []

    def model_factory(settings, context, model, schema, max_output_tokens=2048):
        assert max_output_tokens in {1024, 2048, 4096}
        calls.append((schema, max_output_tokens))
        instance = NovelModel() if schema is module.GeneratedProposals else OfflineReviewer()
        instance.model = model
        return instance

    monkeypatch.setattr(module, "StructuredModel", model_factory)
    result = await design_qa(settings, production(), search=found)
    assert calls == [(module.GeneratedProposals, 4096), (module.StageReviews, 1024)]
    assert result["generation_model"] == "gpt-4o-mini-2024-07-18"
    assert result["review_model"] == (review_model or "gpt-4o-mini-2024-07-18")
    assert len(result["generation_prompt_version"]) == 64
    assert result["reviews"][0]["decision"] == "ACCEPT_FOR_BINDING"


@pytest.mark.asyncio
async def test_missing_adopted_policy_skips_semantic_review(settings):
    async def no_policy(query):
        result = await found(query)
        if query["source_type"] == "PROJECT_POLICY":
            result["results"] = []
        return result

    class NeverReview:
        async def generate(self, prompt, context):
            raise AssertionError("Missing policy must be handled before semantic review")

    result = await design_qa(
        settings, production(), model=NovelModel(), search=no_policy, reviewer=NeverReview()
    )
    assert result["reviews"][0]["decision"] == "NEEDS_INFORMATION"
    assert result["reviews"][0]["method"] == "CODE_PREREQUISITES"


@pytest.mark.asyncio
async def test_invented_entity_is_rejected_before_semantic_review(settings):
    class UnknownMachine(NovelModel):
        async def generate(self, prompt, context):
            result = await super().generate(prompt, context)
            item = result["proposals"][0]
            payload = json.loads(item["test_data_json"])
            payload["business_input_patch"]["machine_id"] = "NOT-REGISTERED"
            item["test_data_json"] = json.dumps(payload)
            return result

    class NeverReview:
        async def generate(self, prompt, context):
            raise AssertionError("Invented identities must not reach semantic review")

    result = await design_qa(
        settings, production(), model=UnknownMachine(), search=found, reviewer=NeverReview()
    )
    assert result["reviews"][0]["decision"] == "REJECT"
    assert result["reviews"][0]["method"] == "CODE_PREREQUISITES"


@pytest.mark.asyncio
async def test_review_sees_only_eligible_materialized_proposals(settings):
    import copy

    class Mixed(NovelModel):
        async def generate(self, prompt, context):
            result = await super().generate(prompt, context)
            invalid = copy.deepcopy(result["proposals"][0])
            invalid["proposal_id"] = "INVALID_MACHINE"
            payload = json.loads(invalid["test_data_json"])
            payload["business_input_patch"]["machine_id"] = "NOT-REGISTERED"
            invalid["test_data_json"] = json.dumps(payload)
            result["proposals"].append(invalid)
            return result

    class InspectReview(OfflineReviewer):
        async def generate(self, prompt, context):
            assert "evidence_options" not in context
            assert context["review_stage"] in {"MANUFACTURING", "AGENTIC"}
            assert len(context["proposals"]) == 1
            proposal = context["proposals"][0]
            assert "test_data_json" not in proposal
            preview = proposal["proposed_situation"]
            assert preview["initial_state"]["machine_status"] == "READY"
            assert preview["after_approval"][0]["state"]["machine_status"] == "MAINTENANCE"
            assert not preview["executed"]
            return await super().generate(prompt, context)

    result = await design_qa(
        settings, production(), model=Mixed(), search=found, reviewer=InspectReview()
    )
    assert [r["decision"] for r in result["reviews"]] == ["ACCEPT_FOR_BINDING", "REJECT"]


def test_preview_applies_null_without_mutating_the_reference_sample():
    from agents.scenario.review import scenario_preview

    sample = json.loads((ROOT / "qa/examples/manufacturing-targets.json").read_text())["QUALITY"][
        "sample_data"
    ]
    proposal = {
        "data_strategy": "MODEL_GENERATED",
        "test_data_json": json.dumps(
            {
                "business_input_patch": {},
                "initial_state_patch": {"required_test_record": None},
                "approval_decision": "APPROVED",
                "fault": "NONE",
                "interventions": [],
            }
        ),
    }
    preview = scenario_preview(proposal, sample)
    assert preview["initial_state"]["required_test_record"] is None
    assert sample["initial_state"]["required_test_record"]["result"] == "PASS"
    assert not preview["executed"]


@pytest.mark.parametrize("fault", ["none", "new-id", "changed-risk", "changed-index"])
@pytest.mark.asyncio
async def test_repair_is_restricted_to_supplied_identity_and_same_evidence(settings, fault):
    import copy

    from agents.llm import ModelError
    from agents.scenario.design import RepairInput

    original = await design_qa(
        settings, production(), model=NovelModel(), search=found, reviewer=OfflineReviewer()
    )
    body = production()
    body.repair = RepairInput(
        previous_proposals=original["proposals"],
        feedback=[{"proposal_id": "NOVEL_AFTER_APPROVAL", "reasons": ["설비 상태 확인"]}],
        index_version="changed-index"
        if fault == "changed-index"
        else original["retrieval"][0]["index_version"],
    )

    class RepairModel:
        async def generate(self, prompt, context):
            assert context["repair_proposal_ids"] == ["NOVEL_AFTER_APPROVAL"]
            p = copy.deepcopy(original["proposals"][0])
            p.pop("risk_type")
            if fault == "new-id":
                p["proposal_id"] = "OTHER_ID"
            if fault == "changed-risk":
                p["risk_key"] = "APPROVAL_BYPASS"
            return {"proposals": [p]}

    async def invoke():
        return await design_qa(
            settings, body, model=RepairModel(), search=found, reviewer=OfflineReviewer()
        )

    if fault != "none":
        with pytest.raises(ModelError):
            await invoke()
    else:
        result = await invoke()
        assert result["proposals"] == original["proposals"]
        assert any(t["stage"] == "REPAIR_WITH_FEEDBACK" for t in result["trace"])


@pytest.mark.parametrize("kind", ["PURCHASE", "PRODUCTION", "QUALITY"])
def test_generation_schema_pins_business_identity_and_excludes_transaction_records(kind):
    from jsonschema import Draft202012Validator, ValidationError

    from agents.scenario.scenario_schema import output_schema

    example = json.loads((ROOT / "qa/examples/manufacturing-targets.json").read_text())[kind]
    if kind == "PURCHASE":
        from test_design import reference

        body = reference()
        target, sample = body.target, body.sample_data
    else:
        target, sample = example["target"], example["sample_data"]
    contract = json.loads((ROOT / "qa/contracts/qa.schema.json").read_text())
    schema = output_schema(target, sample, contract)
    Draft202012Validator.check_schema(schema)
    business = schema["properties"]["business_input_patch"]
    validator = Draft202012Validator(business)
    validator.validate(sample["business_input"])
    changed = dict(sample["business_input"])
    key = next(k for k in changed if k.endswith("_id") and k != "request_id")
    changed[key] = "INVENTED-ID"
    with pytest.raises(ValidationError):
        validator.validate(changed)
    assert "initial_approvals" not in schema["properties"]["initial_state_patch"]["properties"]
    assert schema["additionalProperties"] is False


@pytest.mark.asyncio
async def test_morphological_label_must_match_authored_condition_and_phase(settings):
    class Contradictory(NovelModel):
        async def generate(self, prompt, context):
            result = await super().generate(prompt, context)
            p = result["proposals"][0]
            data = json.loads(p["test_data_json"])
            data["interventions"] = []  # Label says post-approval maintenance; facts do not.
            p["test_data_json"] = json.dumps(data)
            return result

    class NeverReview:
        async def generate(self, *args):
            raise AssertionError("Contradictory morphology must be caught before review")

    result = await design_qa(
        settings, production(), model=Contradictory(), search=found, reviewer=NeverReview()
    )
    assert result["reviews"][0]["decision"] == "REJECT"
    assert "시점" in result["reviews"][0]["reasons"][0]
    candidates = result["morphology"]["candidates"]
    assert candidates and result["morphology"]["kind"] == "NORMAL_USE_SCENARIOS"
    assert not {"event", "phase", "business_condition"} & result["morphology"]["axes"].keys()
    assert all("risk_key" not in c and c["normal_goal"] for c in candidates)


@pytest.mark.asyncio
async def test_static_maintenance_with_denied_approval_is_rejected_before_review(settings):
    class Mismatched(NovelModel):
        async def generate(self, prompt, context):
            result = await super().generate(prompt, context)
            proposal = result["proposals"][0]
            proposal["exception_ids"] = [
                e["exception_id"]
                for e in context["morphology"]["exception_catalog"]
                if e["condition"] == "MAINTENANCE" and e["phase"] == "INITIAL"
            ]
            data = json.loads(proposal["test_data_json"])
            data["initial_state_patch"]["machine_status"] = "MAINTENANCE"
            data["interventions"] = []
            data["approval_decision"] = "REJECTED"
            proposal["test_data_json"] = json.dumps(data)
            return result

    class NeverReview:
        async def generate(self, *args):
            raise AssertionError("Contradictory approval must be caught before semantic review")

    result = await design_qa(
        settings, production(), model=Mismatched(), search=found, reviewer=NeverReview()
    )
    assert result["reviews"][0]["decision"] == "REJECT"
    assert "승인 조건" in result["reviews"][0]["reasons"][0]


@pytest.mark.asyncio
async def test_retrieved_manufacturing_source_must_be_cited_by_proposal(settings):
    class OmitsManufacturing(NovelModel):
        async def generate(self, prompt, context):
            result = await super().generate(prompt, context)
            manufacturing_ids = set(
                context["evidence_options"]["RESOURCE_CONSTRAINT"]["MANUFACTURING"]
            )
            proposal = result["proposals"][0]
            proposal["evidence_ids"] = [
                sid for sid in proposal["evidence_ids"] if sid not in manufacturing_ids
            ]
            return result

    class NeverReview:
        async def generate(self, *args):
            raise AssertionError("Uncited manufacturing evidence must block semantic review")

    result = await design_qa(
        settings, production(), model=OmitsManufacturing(), search=found, reviewer=NeverReview()
    )
    assert result["reviews"][0]["decision"] == "NEEDS_INFORMATION"
    assert "MANUFACTURING" in result["reviews"][0]["reasons"][0]
    assert "TECH-ISA95-MOM" in result["reviews"][0]["reasons"][0]


@pytest.mark.asyncio
@pytest.mark.parametrize("stage", ["MANUFACTURING", "AGENTIC"])
async def test_policy_only_reasons_cannot_claim_supported_domain_review(settings, stage):
    class PolicyOnlyReviewer(OfflineReviewer):
        async def generate(self, prompt, context):
            result = await super().generate(prompt, context)
            if context["review_stage"] == stage:
                for row in result["reviews"]:
                    row["reasons"] = ["PROJECT-APPROVAL 정책에 따라 변경을 보류합니다."]
            return result

    result = await design_qa(
        settings, production(), model=NovelModel(), search=found, reviewer=PolicyOnlyReviewer()
    )
    review = result["reviews"][0]
    assert review["decision"] == "NEEDS_INFORMATION"
    index = 0 if stage == "MANUFACTURING" else 1
    assert review["stages"][index]["assessment"]["evidence_relevance"] == "UNCLEAR"
    assert review["stages"][1]["status"] == ("SKIPPED" if stage == "MANUFACTURING" else "COMPLETED")
