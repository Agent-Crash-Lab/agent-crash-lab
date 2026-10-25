import copy
import json

import pytest
from conftest import ROOT, TOKEN
from fastapi.testclient import TestClient

from agents.llm import ModelError
from agents.scenario.design import DesignRequest, analyze, design_qa, screen_risks
from agents.server import create_app


def reference():
    profile = json.loads((ROOT / "qa/examples/targets/agents.json").read_text())["agents"][
        "PURCHASE"
    ]
    return DesignRequest(target=profile["target"], sample_data=profile["sample_data"])


async def found(query):
    rows = json.loads((ROOT / "qa/knowledge/sources-collected.json").read_text())["records"]
    eligible = [
        r
        for r in rows
        if (query["source_type"] == "ALL" or r["source_type"] == query["source_type"])
        and (
            not query.get("evidence_domain")
            or query["evidence_domain"] in r.get("evidence_domains", [])
        )
        and query["risk_type"] in r["risk_types"]
        and (
            query["target_type"] == "COMMON"
            or "COMMON" in r["roles"]
            or query["target_type"] in r["roles"]
        )
    ]
    return {
        "index_version": "index-v1",
        "results": [
            {
                "document_id": r["source_id"] + ":p0",
                "source_id": r["source_id"],
                "version": r["sha256"],
                "location": "Curated source summary",
                "source_url": r["url"],
                "title": r["title"],
                "content_kind": r["content_kind"],
                "scope": r["scope"],
                "matched_text": r["text_en"],
                "source_type": r["source_type"],
                "risk_types": r["risk_types"],
                "evidence_domains": r.get("evidence_domains", []),
                "claim_role": r["claim_role"],
                "policy_status": r.get("policy_status"),
                "adopted_adapters": r.get("adopted_adapters", []),
            }
            for r in eligible[: query["limit"]]
        ],
    }


@pytest.mark.asyncio
async def test_design_uses_target_features_and_records_queries_citations_and_stages(settings):
    result = await design_qa(settings, reference(), search=found)
    assert result["analysis"]["target_type"] == "PURCHASE"
    assert result["analysis"]["write_tools"] == ["create_purchase_order"]
    assert len(result["retrieval"]) == 18
    duplicate = next(p for p in result["proposals"] if p["risk_key"] == "AMBIGUOUS_WRITE")
    assert duplicate["data_strategy"] == "SHORTAGE_BOUNDARY"
    assert "PROJECT-IDEMPOTENCY:p0" in duplicate["evidence_ids"]
    assert {p["risk_key"] for p in result["proposals"]} == {
        "AMBIGUOUS_WRITE",
        "APPROVAL_BYPASS",
        "SUPPLIER_QUALIFICATION",
    }
    assert [x["stage"] for x in result["trace"]] == [
        "ANALYZE_TARGET",
        "BUILD_NORMAL_USE_SCENARIOS",
        "RETRIEVE_EVIDENCE",
        "DERIVE_EXCEPTION_OPTIONS",
        "PROPOSE_TESTS",
        "VALIDATE_PROPOSALS",
        "REVIEW_MANUFACTURING",
        "REVIEW_AGENTIC",
    ]
    assert result["model_kind"] == "offline" and not result["llm_usage"]


@pytest.mark.parametrize("kind", ["PRODUCTION", "QUALITY"])
@pytest.mark.asyncio
async def test_domain_examples_produce_domain_data_not_purchase_data(settings, kind):
    example = json.loads((ROOT / "qa/examples/targets/agents.json").read_text())["agents"][kind]
    result = await design_qa(
        settings, DesignRequest(**{k: example[k] for k in ("target", "sample_data")}), search=found
    )
    assert result["analysis"]["target_type"] == kind
    assert len(result["proposals"]) == 3
    assert result["proposals"][0]["risk_type"] == "DOMAIN_CONSTRAINT"
    assert all(p["data_strategy"] == "UNCHANGED" for p in result["proposals"])


@pytest.mark.asyncio
async def test_unretrieved_citations_cannot_leave_the_designer(settings):
    class InventingModel:
        async def generate(self, prompt, context):
            from agents.scenario.design import OfflineDesigner

            result = await OfflineDesigner().generate(prompt, context)
            result["proposals"][0]["evidence_ids"] = ["UNSEEN-DOCUMENT"]
            return result

    with pytest.raises(ModelError, match="DESIGN_UNRETRIEVED_SOURCE"):
        await design_qa(settings, reference(), model=InventingModel(), search=found)


def test_unknown_or_conflicting_classification_does_not_default_to_procurement():
    body = reference()
    mixed = {
        "business_input": {
            **body.sample_data["business_input"],
            "machine_id": "M1",
            "operation_id": "O1",
        }
    }
    assert analyze(body.target, mixed)["target_type"] == "PURCHASE"
    undeclared = {k: v for k, v in body.target.items() if k != "agent_type"}
    assert analyze(undeclared, mixed)["target_type"] == "COMMON"


def test_design_endpoint_requires_internal_auth_and_never_executes_target(settings):
    with TestClient(create_app(settings, design_search=found)) as client:
        body = reference().model_dump()
        assert client.post("/internal/qa/design", json=body).status_code == 401
        response = client.post(
            "/internal/qa/design", headers={"X-Internal-Token": TOKEN}, json=body
        )
        assert response.status_code == 200
        assert response.json()["proposals"]
        assert client.portal.call(client.app.state.runtime.store.all) == []


def test_curated_scope_expectations_for_ten_target_variants():
    fixture = json.loads((ROOT / "qa/examples/scenarios/design-review-cases.json").read_text())
    library = json.loads((ROOT / "qa/knowledge/risk-library.json").read_text())
    examples = json.loads((ROOT / "qa/examples/targets/agents.json").read_text())["agents"]
    for case in fixture["cases"]:
        body = (
            reference()
            if case["target"] == "PURCHASE"
            else DesignRequest(
                **{k: examples[case["target"]][k] for k in ("target", "sample_data")}
            )
        )
        target = copy.deepcopy(body.target)
        mutation = case["mutation"]
        if mutation == "READ_ONLY":
            target.pop("qa_scope")
            target["tools"] = [t for t in target["tools"] if t["effect"] == "READ"]
        elif mutation == "NO_SCOPE":
            target.pop("qa_scope")
        elif mutation == "NO_RETRY":
            target["policies"]["max_write_retries"] = 0
        elif mutation == "NO_APPROVAL":
            target["policies"]["approval_required"] = False
        elif mutation == "NO_RETRY_OR_APPROVAL":
            target["policies"].update(max_write_retries=0, approval_required=False)
        elif mutation == "NO_EXCLUSIONS":
            target["qa_scope"]["excluded_capabilities"] = []
        elif mutation == "BAD_BINDING":
            target["qa_scope"]["capabilities"].append(
                {
                    "name": "inspection_read",
                    "tool_name": "create_purchase_order",
                    "basis": "DECLARED",
                }
            )
        if case.get("reject_input"):
            with pytest.raises(ValueError):
                screen_risks(target, analyze(target, body.sample_data), library)
        else:
            _, rows = screen_risks(target, analyze(target, body.sample_data), library)
            assert {r["risk_key"]: r["status"] for r in rows} == case["expected"], case["case_id"]


@pytest.mark.asyncio
async def test_independent_critic_can_withhold_a_well_formed_proposal(settings):
    class Critic:
        async def generate(self, prompt, context):
            assert context["test_policy"] and context["proposals"]
            return {
                "reviews": [
                    {
                        "proposal_id": p["proposal_id"],
                        "policy_alignment": "ALIGNED",
                        "evidence_ids": [
                            s["document_id"]
                            for s in context["sources"]
                            if context["review_stage"] in s.get("evidence_domains", [])
                            and s["document_id"] in p["evidence_ids"]
                        ][:1],
                        "evidence_relevance": "IRRELEVANT",
                        "scenario_consistency": "COHERENT",
                        "domain_fit_score": 2,
                        "causal_path_score": 2,
                        "constraint_score": 2,
                        "evidence_score": 2,
                        "score_reasons": {
                            "domain_fit_score": "업무 범위가 맞습니다.",
                            "causal_path_score": "조건과 결과가 연결됩니다.",
                            "constraint_score": "운영 제약을 반영했습니다.",
                            "evidence_score": "인용 자료가 근거를 제공합니다.",
                        },
                        "reasons": ["문헌의 업무 적용 범위를 재검토하세요."],
                    }
                    for p in context["proposals"]
                ]
            }

    result = await design_qa(settings, reference(), search=found, reviewer=Critic())
    assert all(r["decision"] == "REJECT" for r in result["reviews"])
    assert result["strategy"] == "USE_SCENARIOS_THEN_EXCEPTIONS_THEN_TWO_STAGE_REVIEW"
    assert not result["llm_usage"]


@pytest.mark.asyncio
async def test_critic_cannot_omit_or_duplicate_proposals(settings):
    class MissingCritic:
        async def generate(self, prompt, context):
            return {"reviews": []}

    with pytest.raises(ModelError, match="REVIEW_COVERAGE"):
        await design_qa(settings, reference(), search=found, reviewer=MissingCritic())


def test_description_preflight_uses_same_scope_engine_and_marks_unknown_policies(settings):
    from agents.scenario.design import AnalyzeRequest, analyze_description

    declared = reference().model_dump()
    body = AnalyzeRequest(**declared, unknown_policies=["approval_required", "max_write_retries"])
    result = analyze_description(settings, body)
    rows = {r["risk_key"]: r for r in result["risk_screening"]}
    assert rows["AMBIGUOUS_WRITE"]["status"] == "NEEDS_INFORMATION"
    assert rows["APPROVAL_BYPASS"]["status"] == "NEEDS_INFORMATION"
    assert result["declared_policies"] == {"approval_required": None, "max_write_retries": None}
    assert analyze_description(settings, reference())["risk_screening"] != result["risk_screening"]


def test_analyze_endpoint_never_calls_model_or_search_and_requires_auth(settings):
    def unexpected(*args, **kwargs):
        raise AssertionError("Preflight must not call model or search")

    app = create_app(settings, design_model=unexpected, design_search=unexpected)
    with TestClient(app) as client:
        body = reference().model_dump()
        assert client.post("/internal/qa/analyze", json=body).status_code == 401
        response = client.post(
            "/internal/qa/analyze", json=body, headers={"X-Internal-Token": TOKEN}
        )
        assert response.status_code == 200
        assert response.json()["write_tools"] == ["create_purchase_order"]
        body["target"]["business_input_schema"] = {"$ref": "https://example.org/schema"}
        assert (
            client.post(
                "/internal/qa/analyze", json=body, headers={"X-Internal-Token": TOKEN}
            ).status_code
            == 422
        )


def test_design_preserves_input_limit_error(settings):
    class Oversized:
        async def generate(self, prompt, context):
            raise ModelError("LLM_INPUT_LIMIT")

    with TestClient(create_app(settings, design_model=Oversized(), design_search=found)) as client:
        response = client.post(
            "/internal/qa/design", json=reference().model_dump(), headers={"X-Internal-Token": TOKEN}
        )
        assert response.status_code == 503
        assert response.json()["detail"] == "LLM_INPUT_LIMIT"


@pytest.mark.parametrize(
    "alignment,evidence,consistency,decision",
    [
        ("ALIGNED", "SUPPORTED", "COHERENT", "ACCEPT_FOR_BINDING"),
        ("CONFLICT", "SUPPORTED", "COHERENT", "REJECT"),
        ("ALIGNED", "IRRELEVANT", "COHERENT", "REJECT"),
        ("ALIGNED", "SUPPORTED", "CONTRADICTORY", "REJECT"),
        ("ALIGNED", "UNCLEAR", "COHERENT", "NEEDS_INFORMATION"),
        ("UNCLEAR", "SUPPORTED", "COHERENT", "NEEDS_INFORMATION"),
        ("CONFLICT", "UNCLEAR", "COHERENT", "REJECT"),
    ],
)
def test_review_criteria_determine_decision_without_a_model_supplied_verdict(
    alignment, evidence, consistency, decision
):
    from agents.scenario.review import ReviewItem

    item = ReviewItem(
        proposal_id="TEST",
        policy_alignment=alignment,
        evidence_relevance=evidence,
        scenario_consistency=consistency,
        domain_fit_score=2,
        causal_path_score=2,
        constraint_score=2,
        evidence_score=2,
        score_reasons={
            "domain_fit_score": "업무 범위가 맞습니다.",
            "causal_path_score": "조건과 결과가 연결됩니다.",
            "constraint_score": "운영 제약을 반영했습니다.",
            "evidence_score": "인용 자료가 근거를 제공합니다.",
        },
        reasons=["기대 행동과 채택 정책을 대조했습니다."],
    )
    assert item.verdict()["decision"] == decision
    assert item.verdict()["assessment"]["policy_alignment"] == alignment


def test_review_total_score_cannot_hide_a_missing_critical_basis():
    from agents.scenario.review import ReviewItem

    item = ReviewItem(
        proposal_id="LOW-EVIDENCE",
        policy_alignment="ALIGNED",
        evidence_relevance="SUPPORTED",
        scenario_consistency="COHERENT",
        domain_fit_score=2,
        causal_path_score=2,
        constraint_score=2,
        evidence_score=0,
        score_reasons={
            "domain_fit_score": "대상 업무가 일치합니다.",
            "causal_path_score": "조건과 결과가 연결됩니다.",
            "constraint_score": "제약을 구체화했습니다.",
            "evidence_score": "인용 근거가 없습니다.",
        },
        reasons=["근거가 충분하지 않습니다."],
    )
    verdict = item.verdict()
    assert verdict["score_total"] == 6
    assert verdict["decision"] == "NEEDS_INFORMATION"


@pytest.mark.asyncio
@pytest.mark.parametrize("rejected_stage", ["MANUFACTURING", "AGENTIC"])
async def test_two_gates_are_independent_and_a_failed_gate_blocks_binding(settings, rejected_stage):
    from agents.scenario.review import OfflineReviewer

    seen = []

    class Critic(OfflineReviewer):
        async def generate(self, prompt, context):
            stage = context["review_stage"]
            seen.append(stage)
            assert "manufacturing_reviews" not in context
            assert all(
                stage in s.get("evidence_domains", []) or s["source_type"] == "PROJECT_POLICY"
                for s in context["sources"]
            )
            result = await super().generate(prompt, context)
            if stage == rejected_stage:
                for row in result["reviews"]:
                    row["evidence_relevance"] = "IRRELEVANT"
                    row["reasons"] = ["제시한 문단이 이 단계의 위험을 뒷받침하지 않습니다."]
            return result

    result = await design_qa(settings, reference(), search=found, reviewer=Critic())
    assert seen == (
        ["MANUFACTURING"] if rejected_stage == "MANUFACTURING" else ["MANUFACTURING", "AGENTIC"]
    )
    assert all(r["decision"] == "REJECT" for r in result["reviews"])
    for row in result["reviews"]:
        assert [s["stage"] for s in row["stages"]] == ["MANUFACTURING", "AGENTIC"]
        assert row["stages"][1]["status"] == (
            "SKIPPED" if rejected_stage == "MANUFACTURING" else "COMPLETED"
        )


@pytest.mark.asyncio
async def test_missing_manufacturing_evidence_is_withheld_without_model_calls(settings):
    async def missing(query):
        result = await found(query)
        result["results"] = [
            s for s in result["results"] if "MANUFACTURING" not in s.get("evidence_domains", [])
        ]
        return result

    class NeverReview:
        async def generate(self, *args):
            raise AssertionError("Missing domain evidence must block paid review")

    result = await design_qa(settings, reference(), search=missing, reviewer=NeverReview())
    assert all(r["decision"] == "NEEDS_INFORMATION" for r in result["reviews"])


@pytest.mark.asyncio
async def test_reviewer_cannot_cite_the_other_gate_or_invent_evidence(settings):
    from agents.scenario.review import OfflineReviewer

    class Misattributing(OfflineReviewer):
        async def generate(self, prompt, context):
            result = await super().generate(prompt, context)
            result["reviews"][0]["evidence_ids"] = ["RES-AGENT-SAFETY:p0"]
            return result

    with pytest.raises(ModelError, match="REVIEW_EVIDENCE_MISMATCH"):
        await design_qa(settings, reference(), search=found, reviewer=Misattributing())
