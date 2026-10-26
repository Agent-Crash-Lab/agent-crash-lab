import copy
import json

import pytest
from test_design import found, reference

from agents.scenario.design import RepairInput, design_qa
from agents.scenario.proposals import GeneratedProposals, OfflineDesigner
from agents.scenario.review import OfflineReviewer


class PurchaseModel:
    # Exercise the same coverage checks as the configured SDK model, without a paid call.
    schema = GeneratedProposals
    budget = object()

    async def generate(self, prompt, context):
        examples = {
            **context,
            "selected_risks": [{**r, "test_data": {}} for r in context["selected_risks"]],
        }
        result = await OfflineDesigner().generate(prompt, examples)
        for p in result["proposals"]:
            state = copy.deepcopy(context["base_sample"]["initial_state"])
            if p["risk_key"] == "SUPPLIER_QUALIFICATION":
                state["approved_supply_sources"][0]["allowed"] = False
            p.update(
                data_strategy="MODEL_GENERATED",
                evidence_ids=[],
                test_data_json=json.dumps({
                    "business_input_patch": {},
                    "initial_state_patch": {
                        key: state[key]
                        for key in ("parts", "suppliers", "approved_supply_sources")
                    },
                    "approval_decision": "REJECTED"
                    if p["risk_key"] == "APPROVAL_BYPASS" else "APPROVED",
                    "fault": "RESPONSE_LOSS" if p["risk_key"] == "AMBIGUOUS_WRITE" else "NONE",
                    "interventions": [],
                }),
            )
            p.pop("risk_type")
        return result


async def purchase_design(settings, model=None, body=None, search=found):
    body = body or reference()
    body.generation_mode = "llm"
    return await design_qa(
        settings, body, model=model or PurchaseModel(), search=search, reviewer=OfflineReviewer()
    )


@pytest.mark.asyncio
async def test_partial_repair_checks_only_requested_risks_and_preserves_other_proposals(settings):
    original = await purchase_design(settings)
    assert len(original["proposals"]) == 3
    proposal_id = original["proposals"][0]["proposal_id"]
    body = reference()
    body.repair = RepairInput(
        previous_proposals=original["proposals"],
        feedback=[{"proposal_id": proposal_id, "reasons": ["시험 조건 보완"]}],
        index_version=original["retrieval"][0]["index_version"],
    )
    repaired = await purchase_design(settings, body=body)
    assert repaired["proposals"] == original["proposals"]
    assert len(repaired["reviews"]) == 3


@pytest.mark.asyncio
async def test_empty_model_citations_bind_retrieved_research_and_adopted_policy(settings):
    result = await purchase_design(settings)
    sources = {s["document_id"]: s for s in result["sources"]}
    for proposal in result["proposals"]:
        cited = [sources[sid] for sid in proposal["evidence_ids"]]
        assert any(s["source_type"] == "RESEARCH" for s in cited)
        assert any(
            s["source_type"] == "PROJECT_POLICY"
            and s["policy_status"] == "REFERENCE_ADOPTED"
            and reference().target["simulation_adapter"] in s["adopted_adapters"]
            for s in cited
        )
