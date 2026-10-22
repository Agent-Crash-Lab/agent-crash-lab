"""Bounded QA design graph: analyze metadata → retrieve → propose → check citations.

This service never calls target business tools or decides a business verdict.
Offline mode is a transparent rule-based demonstration; OpenAI is opt-in.
"""

import asyncio
import copy
import hashlib
import json
from types import SimpleNamespace
from typing import Literal, TypedDict
from uuid import uuid4

import httpx
from jsonschema import Draft202012Validator
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, ConfigDict, Field

from agents.llm import ModelError, StructuredModel, resolve_model
from agents.qa.analysis import analyze as analyze
from agents.qa.analysis import analyze_description as analyze_description
from agents.qa.analysis import screen_risks as screen_risks
from agents.qa.proposals import (
    GENERATIVE_PROMPT,
    PROMPT,
    REPAIR_PROMPT,
    GeneratedProposals,
    OfflineDesigner,
    Proposal,
    Proposals,
)
from agents.qa.review import (
    REVIEW_PROMPT,
    OfflineReviewer,
    Reviews,
    evidence_options,
    review_prerequisites,
    scenario_preview,
)
from agents.qa.scenario_schema import output_schema


class DesignState(TypedDict, total=False):
    analysis: dict
    sources: list
    retrieval: list
    proposals: list
    selected_risks: list
    reviews: list


class RepairFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid")
    proposal_id: str = Field(min_length=1, max_length=64)
    reasons: list[str] = Field(min_length=1, max_length=6)


class RepairInput(BaseModel):
    model_config = ConfigDict(extra="forbid")
    previous_proposals: list[Proposal] = Field(min_length=1, max_length=3)
    feedback: list[RepairFeedback] = Field(min_length=1, max_length=3)
    index_version: str = Field(min_length=1, max_length=128)


class DesignRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    target: dict
    sample_data: dict
    generation_mode: Literal["configured", "llm", "offline"] = "configured"
    repair: RepairInput | None = None


class AnalyzeRequest(DesignRequest):
    unknown_policies: list[Literal["approval_required", "max_write_retries"]] = Field(
        default_factory=list, max_length=2
    )


async def design_qa(settings, body, model=None, search=None, reviewer=None):
    root = settings.agent_project_root
    library = json.loads((root / "qa/knowledge/risk-library.json").read_text())
    library_hash = hashlib.sha256(
        json.dumps(library, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    analysis = analyze_description(settings, body, library=library)
    test_policy = json.loads((root / "qa/knowledge/test-policy.json").read_text())
    trace, usage_record = [], {"budget_stage": settings.llm_budget_stage}
    ctx = SimpleNamespace(
        run_id="DESIGN-" + uuid4().hex,
        store=SimpleNamespace(get=lambda _: usage_record, put=lambda r: None),
        secrets=[
            settings.llm_api_key.get_secret_value(),
            settings.internal_api_token.get_secret_value(),
        ],
        event=lambda name, payload=None: trace.append({"stage": name, "details": payload or {}}),
    )
    mode = (
        settings.qa_design_model_mode
        if body.generation_mode == "configured"
        else "openai"
        if body.generation_mode == "llm"
        else "offline"
    )
    injected = model is not None
    generative = mode == "openai"
    response_type = GeneratedProposals if generative else Proposals
    contract = json.loads((root / "qa/contracts/qa.schema.json").read_text())
    generation_contract = {
        "scenario_schema": contract["$defs"]["generated_scenario"],
        "fixed_identity": {
            key: value
            for key, value in body.sample_data["business_input"].items()
            if key.endswith("_id") and key != "request_id"
        },
        "state_schema": contract["$defs"].get(body.target.get("agent_type", "").lower() + "_state"),
        "sandbox_semantics": {
            "approval_decision": "Decision only if requested; not preapproved.",
            "initial_violation": "A static violation may require hold before requesting approval.",
            "interventions": "Optional after-approval changes; not required for static faults.",
            "business_write": "A declared WRITE tool records the requested business change.",
            "resource_variants": "Maintenance, overlap and predecessor delay are alternatives.",
        },
        "supported_interventions": ["AFTER_APPROVAL_BEFORE_WRITE"]
        if body.target["simulation_adapter"] in {"reference-production-v1", "reference-quality-v1"}
        else [],
        "limits": (
            "Existing IDs only. Purchase supports shortage quantities, inventory, prices and "
            "selected source eligibility; users and existing transactions cannot change. "
            "Post-approval changes are production/quality only."
        ),
    }
    bounded_schema = output_schema(body.target, body.sample_data, contract) if generative else None
    if bounded_schema:
        generation_contract["scenario_schema"] = bounded_schema
        generation_contract["structured_data_output"] = True
    if model is None:
        if mode == "openai":
            if not settings.llm_api_key.get_secret_value():
                raise ModelError("LLM_KEY_NOT_CONFIGURED")
            model = StructuredModel(
                settings,
                ctx,
                resolve_model(settings.qa_design_llm_model or settings.llm_model),
                response_type,
                max_output_tokens=4096,
            )
        else:
            model = OfflineDesigner()

    if reviewer is None:
        reviewer = (
            StructuredModel(
                settings,
                ctx,
                resolve_model(
                    settings.qa_review_llm_model
                    or settings.qa_design_llm_model
                    or settings.llm_model
                ),
                schema=Reviews,
                max_output_tokens=1024,
            )
            if mode == "openai"
            else OfflineReviewer()
        )

    async def http_search(client, query):
        response = await client.post(
            "/internal/knowledge/search",
            json=query,
            headers={"X-Internal-Token": settings.internal_api_token.get_secret_value()},
        )
        response.raise_for_status()
        return response.json()

    async def analysis_node(state):
        trace.append({"stage": "ANALYZE_TARGET"})
        return {"analysis": analysis}

    async def retrieve_node(state):
        analysis = state["analysis"]
        applicable = {
            r["risk_key"] for r in analysis["risk_screening"] if r["status"] == "APPLICABLE"
        }
        selected = sorted(
            [r for r in library["risks"] if r["risk_key"] in applicable],
            key=lambda r: (r["priority"], r["risk_key"]),
        )[:3]
        found, requests, versions = {}, [], set()
        jobs = [
            (risk, category)
            for risk in selected
            for category in ("RESEARCH", "INCIDENT", "TECHNICAL", "PROJECT_POLICY")
        ]
        semaphore = asyncio.Semaphore(4)

        async def retrieve(job):
            risk, category = job
            async with semaphore:
                query = {
                    "query": risk["query_en"],
                    "target_type": analysis["target_type"],
                    "limit": 2 if category == "PROJECT_POLICY" else 1,
                    "source_type": category,
                    "risk_type": risk["risk_key"],
                }
                return await search(query) if search else await http_search(client, query)

        base = str(settings.mcp_url).removesuffix("/").removesuffix("/mcp")
        async with httpx.AsyncClient(base_url=base, timeout=10) as client:
            results = await asyncio.gather(*(retrieve(job) for job in jobs))
        for (risk, category), result in zip(jobs, results, strict=True):
            versions.add(result["index_version"])
            for source in result["results"]:
                if (
                    source["source_type"] != category
                    or risk["risk_key"] not in source["risk_types"]
                ):
                    raise ValueError(
                        "Search returned evidence outside the requested category or risk"
                    )
                found[source["document_id"]] = {
                    k: source[k]
                    for k in (
                        "document_id",
                        "source_id",
                        "version",
                        "location",
                        "source_url",
                        "title",
                        "content_kind",
                        "scope",
                        "matched_text",
                        "source_type",
                        "risk_types",
                        "claim_role",
                        "policy_status",
                        "adopted_adapters",
                    )
                }
                found[source["document_id"]]["matched_text"] = source["matched_text"][:700]
            requests.append(
                {
                    "query": risk["query_en"],
                    "risk_key": risk["risk_key"],
                    "source_type": category,
                    "index_version": result["index_version"],
                    "document_ids": [s["document_id"] for s in result["results"]],
                }
            )
        if body.repair and versions != {body.repair.index_version}:
            raise ModelError("REPAIR_EVIDENCE_CHANGED")
        if len(versions) > 1:
            raise ValueError("Knowledge index changed during design; retry")
        trace.append({"stage": "RETRIEVE_EVIDENCE", "searches": requests})
        return {"sources": list(found.values()), "retrieval": requests, "selected_risks": selected}

    def proposal_context(state):
        analysis = copy.deepcopy(state["analysis"])
        risks = copy.deepcopy(state["selected_risks"])
        if generative:
            # Preserve risk descriptions without encouraging copies of fixture numbers or patches.
            for example in analysis["manufacturing_context"]["scenario_examples"]:
                example.pop("payload", None)
            for risk in risks:
                risk.pop("test_data", None)
        return {
            "target": body.target,
            "analysis": analysis,
            "sources": state["sources"],
            "selected_risks": risks,
            "test_policy": test_policy,
            "base_sample": body.sample_data,
            "generation_contract": generation_contract,
            "evidence_options": evidence_options(
                state["selected_risks"], state["sources"], body.target["simulation_adapter"]
            ),
        }

    async def propose_node(state):
        if not state["selected_risks"]:
            trace.append({"stage": "PROPOSE_TESTS", "skipped": "NO_APPLICABLE_RISKS"})
            return {"proposals": []}
        context = proposal_context(state)
        trace.append({"stage": "PROPOSE_TESTS"})
        prompt = GENERATIVE_PROMPT if generative else PROMPT
        if body.repair:
            if not generative:
                raise ModelError("REPAIR_REQUIRES_GENERATIVE_MODE")
            previous = {p.proposal_id: p.model_dump() for p in body.repair.previous_proposals}
            ids = {f.proposal_id for f in body.repair.feedback}
            if len(previous) != len(body.repair.previous_proposals) or not ids <= previous.keys():
                raise ModelError("INVALID_REPAIR_IDENTITY")
            context["repair_proposal_ids"] = sorted(ids)
            context["repair_feedback"] = [f.model_dump() for f in body.repair.feedback]
            context["previous_proposals"] = [previous[pid] for pid in sorted(ids)]
            context["selected_risks"] = [
                risk
                for risk in context["selected_risks"]
                if risk["risk_key"] in {previous[pid]["risk_key"] for pid in ids}
            ]
            prompt += REPAIR_PROMPT
        generated = response_type.model_validate(await model.generate(prompt, context))
        proposals = [p.model_dump() for p in generated.proposals]
        if generative:
            recipes = {risk["risk_key"]: risk["recipe"] for risk in state["selected_risks"]}
            for proposal in proposals:
                if proposal["risk_key"] not in recipes:
                    raise ModelError("DESIGN_RISK_OUTSIDE_SCOPE")
                proposal["risk_type"] = recipes[proposal["risk_key"]]
        if body.repair:
            replacements = {p["proposal_id"]: p for p in proposals}
            if len(replacements) != len(proposals) or replacements.keys() != ids:
                raise ModelError("REPAIR_COVERAGE_MISMATCH")
            for pid, replacement in replacements.items():
                if any(replacement[k] != previous[pid][k] for k in ("risk_key", "tool_name")):
                    raise ModelError("REPAIR_SCOPE_CHANGED")
            proposals = [
                replacements.get(p.proposal_id, p.model_dump())
                for p in body.repair.previous_proposals
            ]
            trace.append({"stage": "REPAIR_WITH_FEEDBACK", "proposal_ids": sorted(ids)})
        return {"proposals": proposals}

    async def validate_node(state):
        known = {s["document_id"]: s for s in state["sources"]}
        allowed = {r["risk_key"]: r for r in state["selected_risks"]}
        tools = set(state["analysis"]["write_tools"])
        ids = set()
        scenario_validator = Draft202012Validator(contract["$defs"]["generated_scenario"])
        for proposal in state["proposals"]:
            if proposal["proposal_id"] in ids:
                raise ModelError("DESIGN_DUPLICATE_PROPOSAL")
            if proposal["tool_name"] not in tools:
                raise ModelError("DESIGN_INVALID_TOOL")
            ids.add(proposal["proposal_id"])
            if not set(proposal["evidence_ids"]) <= known.keys():
                raise ModelError("DESIGN_UNRETRIEVED_SOURCE")
            risk = allowed.get(proposal["risk_key"])
            if risk is None or risk["recipe"] != proposal["risk_type"]:
                raise ModelError("DESIGN_RISK_OUTSIDE_SCOPE")
            if any(
                proposal["risk_key"] not in known[sid]["risk_types"]
                for sid in proposal["evidence_ids"]
            ):
                raise ModelError("DESIGN_EVIDENCE_RISK_MISMATCH")
            data = json.loads(proposal["test_data_json"])
            if proposal["data_strategy"] == "MODEL_GENERATED":
                scenario_validator.validate(data)
            if not isinstance(data, dict):
                raise ValueError("Test data must be a JSON object")
        trace.append({"stage": "VALIDATE_PROPOSALS"})
        return {}

    async def review_node(state):
        if not state["proposals"]:
            trace.append({"stage": "CRITIQUE_TEST_PLAN", "skipped": "NO_PROPOSALS"})
            return {"reviews": []}
        context = {**proposal_context(state), "proposals": state["proposals"]}
        cited = {sid for proposal in state["proposals"] for sid in proposal["evidence_ids"]}
        context["sources"] = [s for s in state["sources"] if s["document_id"] in cited]
        context["analysis"] = {
            k: state["analysis"][k]
            for k in ("target_type", "write_tools", "capabilities", "declared_policies")
        }
        context["evidence_checks"] = {
            proposal["proposal_id"]: evidence_options(
                [
                    risk
                    for risk in state["selected_risks"]
                    if risk["risk_key"] == proposal["risk_key"]
                ],
                [s for s in context["sources"] if s["document_id"] in proposal["evidence_ids"]],
                body.target["simulation_adapter"],
            )[proposal["risk_key"]]
            for proposal in state["proposals"]
        }
        blocked, eligible = [], []
        for proposal in state["proposals"]:
            issue = review_prerequisites(proposal, context)
            if issue:
                blocked.append(issue)
            else:
                eligible.append(proposal)
        eligible_ids = {proposal["proposal_id"] for proposal in eligible}
        eligible_risks = {proposal["risk_key"] for proposal in eligible}
        eligible_sources = {sid for proposal in eligible for sid in proposal["evidence_ids"]}
        context["evidence_checks"] = {
            key: value for key, value in context["evidence_checks"].items() if key in eligible_ids
        }
        context["sources"] = [s for s in context["sources"] if s["document_id"] in eligible_sources]
        context["selected_risks"] = [
            risk for risk in context["selected_risks"] if risk["risk_key"] in eligible_risks
        ]
        context["evidence_options"] = {
            key: value
            for key, value in context["evidence_options"].items()
            if key in eligible_risks
        }
        context["proposals"] = [
            {
                **{
                    k: v
                    for k, v in proposal.items()
                    if k not in {"failure_mode", "expected_behavior", "test_data_json"}
                },
                "unsafe_behavior_to_detect": proposal["failure_mode"],
                "expected_safe_behavior": proposal["expected_behavior"],
                "proposed_situation": scenario_preview(proposal, body.sample_data),
            }
            for proposal in eligible
        ]
        rows = []
        if eligible:
            reviewed = Reviews.model_validate(await reviewer.generate(REVIEW_PROMPT, context))
            rows = [
                {
                    **r.verdict(),
                    "method": "SEMANTIC_RUBRIC_V1" if generative else "OFFLINE_METADATA_CHECK",
                }
                for r in reviewed.reviews
            ]
            if len(rows) != len(eligible) or {r["proposal_id"] for r in rows} != {
                p["proposal_id"] for p in eligible
            }:
                raise ModelError("DESIGN_REVIEW_COVERAGE_MISMATCH")
        by_id = {row["proposal_id"]: row for row in rows + blocked}
        rows = [by_id[p["proposal_id"]] for p in state["proposals"]]
        trace.append({"stage": "CRITIQUE_TEST_PLAN", "reviews": rows})
        return {"reviews": rows}

    graph = StateGraph(DesignState)
    for name, node in (
        ("analyze", analysis_node),
        ("retrieve", retrieve_node),
        ("propose", propose_node),
        ("validate", validate_node),
        ("review", review_node),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "analyze")
    for left, right in (("analyze", "retrieve"), ("retrieve", "propose"), ("propose", "validate")):
        graph.add_edge(left, right)
    graph.add_edge("validate", "review")
    graph.add_edge("review", END)
    compiled = graph.compile()
    result = await asyncio.wait_for(compiled.ainvoke({}), timeout=45)
    return {
        "design_id": ctx.run_id,
        "version": "4.0.0" if generative else "3.0.0",
        "test_policy_version": test_policy["version"],
        "test_policy_hash": hashlib.sha256(
            json.dumps(
                test_policy, ensure_ascii=False, sort_keys=True, separators=(",", ":")
            ).encode()
        ).hexdigest(),
        "reviews": result["reviews"],
        "strategy": "PLAN_THEN_CRITIQUE_THEN_CODE_BINDING",
        "risk_library_version": library["version"],
        "risk_library_hash": library_hash,
        "model_kind": "injected_model" if injected and generative else mode,
        "data_generation": "MODEL_AUTHORED_PATCHES" if generative else "REGISTERED_RECIPES",
        "generation_model": getattr(model, "model", None),
        "review_model": getattr(reviewer, "model", None),
        "review_method": "SEMANTIC_RUBRIC_V1" if generative else "OFFLINE_METADATA_CHECK",
        "review_prompt_version": hashlib.sha256(REVIEW_PROMPT.encode()).hexdigest(),
        "generation_schema_version": hashlib.sha256(
            json.dumps(generation_contract["scenario_schema"], sort_keys=True).encode()
        ).hexdigest(),
        "generation_prompt_version": hashlib.sha256(
            (
                (GENERATIVE_PROMPT if generative else PROMPT)
                + (REPAIR_PROMPT if body.repair else "")
            ).encode()
        ).hexdigest(),
        "analysis": result["analysis"],
        "sources": result["sources"],
        "retrieval": result["retrieval"],
        "proposals": result["proposals"],
        "trace": trace,
        "llm_usage": usage_record.get("llm_usage", {}),
        "limitations": [
            "출처 식별자 확인은 의미적 적합성 검증이 아닙니다.",
            "분류·도구 효과·정책은 제공된 메타데이터 기준입니다.",
        ],
    }
