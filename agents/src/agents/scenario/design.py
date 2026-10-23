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
from agents.scenario.analysis import analyze as analyze
from agents.scenario.analysis import analyze_description as analyze_description
from agents.scenario.analysis import screen_risks as screen_risks
from agents.scenario.morphology import build_field
from agents.scenario.proposals import (
    GENERATIVE_PROMPT,
    PROMPT,
    REPAIR_PROMPT,
    GeneratedProposals,
    OfflineDesigner,
    Proposal,
    Proposals,
)
from agents.scenario.review import (
    REVIEW_PROMPT,
    STAGE_PROMPTS,
    OfflineReviewer,
    StageReviews,
    combine_stages,
    evidence_options,
    review_prerequisites,
    review_stage,
)
from agents.scenario.scenario_schema import output_schema


class DesignState(TypedDict, total=False):
    analysis: dict
    sources: list
    retrieval: list
    proposals: list
    selected_risks: list
    reviews: list
    morphology: dict
    manufacturing_reviews: list


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
    profiles = json.loads((root / "qa/examples/targets/agents.json").read_text())["agents"]
    scenario_model = next(
        (
            profile["scenario_model"]
            for profile in profiles.values()
            if profile["target"] == body.target
        ),
        None,
    )
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
                schema=StageReviews,
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
        applicable = {
            r["risk_key"] for r in analysis["risk_screening"] if r["status"] == "APPLICABLE"
        }
        morphology = build_field(
            body.target,
            analysis,
            [r for r in library["risks"] if r["risk_key"] in applicable],
            scenario_model,
        )
        trace.append({"stage": "BUILD_NORMAL_USE_SCENARIOS"})
        return {"analysis": analysis, "morphology": morphology}

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
            (risk, category, domain)
            for risk in selected
            for category, domain in (
                ("RESEARCH", None),
                ("INCIDENT", None),
                ("TECHNICAL", None),
                ("PROJECT_POLICY", None),
                ("ALL", "MANUFACTURING"),
                ("ALL", "AGENTIC"),
            )
        ]
        semaphore = asyncio.Semaphore(4)

        async def retrieve(job):
            risk, category, domain = job
            async with semaphore:
                query = {
                    "query": risk["query_en"],
                    "target_type": analysis["target_type"],
                    "limit": 2 if category == "PROJECT_POLICY" or domain else 1,
                    "source_type": category,
                    "risk_type": risk["risk_key"],
                }
                if domain:
                    query["evidence_domain"] = domain
                return await search(query) if search else await http_search(client, query)

        base = str(settings.mcp_url).removesuffix("/").removesuffix("/mcp")
        async with httpx.AsyncClient(base_url=base, timeout=10) as client:
            results = await asyncio.gather(*(retrieve(job) for job in jobs))
        for (risk, category, domain), result in zip(jobs, results, strict=True):
            versions.add(result["index_version"])
            for source in result["results"]:
                if (
                    (category != "ALL" and source["source_type"] != category)
                    or (domain and domain not in source.get("evidence_domains", []))
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
                found[source["document_id"]]["matched_text"] = source["matched_text"][:1200]
                found[source["document_id"]]["evidence_domains"] = source.get(
                    "evidence_domains", []
                )
            requests.append(
                {
                    "query": risk["query_en"],
                    "risk_key": risk["risk_key"],
                    "source_type": category,
                    "evidence_domain": domain,
                    "index_version": result["index_version"],
                    "document_ids": [s["document_id"] for s in result["results"]],
                }
            )
        if body.repair and versions != {body.repair.index_version}:
            raise ModelError("REPAIR_EVIDENCE_CHANGED")
        if len(versions) > 1:
            raise ValueError("Knowledge index changed during design; retry")
        trace.append({"stage": "RETRIEVE_EVIDENCE", "searches": requests})
        morphology = state["morphology"]
        mapped = (
            {
                e["risk_key"]
                for e in morphology.get("exception_catalog", [])
                if e["execution_support"] == "SUPPORTED"
            }
            if morphology["candidates"]
            else set()
        )
        morphology["unmapped_risks"] = [
            r["risk_key"] for r in selected if r["risk_key"] not in mapped
        ]
        trace.append({"stage": "DERIVE_EXCEPTION_OPTIONS"})
        return {
            "sources": list(found.values()),
            "retrieval": requests,
            "selected_risks": [r for r in selected if r["risk_key"] in mapped],
            "morphology": morphology,
        }

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
            "morphology": state["morphology"],
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

    async def manufacturing_node(state):
        context = proposal_context(state)
        blocked, eligible = [], []
        for proposal in state["proposals"]:
            issue = review_prerequisites(proposal, context)
            if issue:
                blocked.append(issue)
            else:
                eligible.append(proposal)
        rows = await review_stage("MANUFACTURING", eligible, context, reviewer, generative)
        trace.append({"stage": "REVIEW_MANUFACTURING", "reviews": rows})
        return {"reviews": blocked, "manufacturing_reviews": rows}

    async def agentic_node(state):
        first = {r["proposal_id"]: r for r in state["manufacturing_reviews"]}
        eligible = [
            p
            for p in state["proposals"]
            if first.get(p["proposal_id"], {}).get("decision") == "ACCEPT_FOR_BINDING"
        ]
        rows = await review_stage(
            "AGENTIC", eligible, proposal_context(state), reviewer, generative
        )
        second = {r["proposal_id"]: r for r in rows}
        combined = {r["proposal_id"]: r for r in state["reviews"]}
        method = "TWO_STAGE_SEMANTIC_V1" if generative else "OFFLINE_METADATA_CHECK"
        for pid, manufacturing in first.items():
            stages = [manufacturing]
            if pid in second:
                stages.append(second[pid])
            else:
                stages.append(
                    {
                        "proposal_id": pid,
                        "stage": "AGENTIC",
                        "status": "SKIPPED",
                        "decision": "NEEDS_INFORMATION",
                        "method": method,
                        "evidence_ids": [],
                        "scores": None,
                        "score_reasons": None,
                        "score_total": None,
                        "score_max": 8,
                        "reasons": ["제조업 검토 통과 후 진행합니다."],
                    }
                )
            combined[pid] = combine_stages(pid, stages, method)
        trace.append({"stage": "REVIEW_AGENTIC", "reviews": rows})
        return {"reviews": [combined[p["proposal_id"]] for p in state["proposals"]]}

    graph = StateGraph(DesignState)
    for name, node in (
        ("analyze", analysis_node),
        ("retrieve", retrieve_node),
        ("propose", propose_node),
        ("validate", validate_node),
        ("manufacturing_review", manufacturing_node),
        ("agentic_review", agentic_node),
    ):
        graph.add_node(name, node)
    graph.add_edge(START, "analyze")
    for left, right in (("analyze", "retrieve"), ("retrieve", "propose"), ("propose", "validate")):
        graph.add_edge(left, right)
    graph.add_edge("validate", "manufacturing_review")
    graph.add_edge("manufacturing_review", "agentic_review")
    graph.add_edge("agentic_review", END)
    compiled = graph.compile()
    result = await asyncio.wait_for(compiled.ainvoke({}), timeout=80)
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
        "strategy": "USE_SCENARIOS_THEN_EXCEPTIONS_THEN_TWO_STAGE_REVIEW",
        "agent_roles": {
            "designer": "SCENARIO_AGENT",
            "executor_and_reporter": "QA_AGENT",
            "target": "MANUFACTURING_OPERATION_AGENT",
        },
        "morphology": result["morphology"],
        "risk_library_version": library["version"],
        "risk_library_hash": library_hash,
        "model_kind": "injected_model" if injected and generative else mode,
        "data_generation": "MODEL_AUTHORED_PATCHES" if generative else "REGISTERED_RECIPES",
        "generation_model": getattr(model, "model", None),
        "review_model": getattr(reviewer, "model", None),
        "review_method": "TWO_STAGE_SEMANTIC_V1" if generative else "OFFLINE_METADATA_CHECK",
        "review_pipeline": "MANUFACTURING_THEN_AGENTIC_V1",
        "review_prompt_version": hashlib.sha256(
            (REVIEW_PROMPT + "".join(STAGE_PROMPTS.values())).encode()
        ).hexdigest(),
        "generation_schema_version": hashlib.sha256(
            json.dumps(
                {
                    "scenario": generation_contract["scenario_schema"],
                    "proposal": response_type.model_json_schema(),
                    "morphology_version": result["morphology"].get("version"),
                },
                sort_keys=True,
            ).encode()
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
            "오프라인은 출처 태그 검사입니다. LLM 검토도 안전 보증이 아닌 검토 의견입니다.",
            "분류·도구 효과·정책은 제공된 메타데이터 기준입니다.",
        ],
    }
