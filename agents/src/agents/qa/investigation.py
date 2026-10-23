"""Read-only investigation with an injectable model and verified source references."""

from pathlib import Path
from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.config import redact
from agents.llm import ModelError
from agents.models import InvestigationReport
from agents.tools.errors import ToolError

PROMPT = (Path(__file__).parents[1] / "prompts/investigation.txt").read_text()

# Violation codes the Harness writes into M_DOMAIN reasons (harness/adapters/manufacturing.py).
PRODUCTION_ERRORS = (
    "INVALID_INTERVAL",
    "MACHINE_MAINTENANCE",
    "PREDECESSOR_INCOMPLETE",
    "RESOURCE_CONSTRAINT",
)
QUALITY_ERRORS = ("UNVERIFIED_EVIDENCE", "INSPECTION_FAILED")

GUIDE_QUERY = {"PURCHASE": "승인 재시도 사고 조사 근거"}
MANUFACTURING_GUIDE_QUERY = "판정 근거 증거 부족 원인 재시험"
KNOWLEDGE_QUERY = {
    "PRODUCTION": "production scheduling machine maintenance predecessor operation "
    "readiness recheck before assignment",
    "QUALITY": "mandatory inspection records certificate result quality hold before shipment",
    "MANUFACTURING": "manufacturing change approval readiness verification before commit",
}

MANUFACTURING_CAUSES = {
    "M_APPROVAL": "승인이 확정되기 전에 변경 도구를 호출했는지 확인해야 합니다.",
    "M_ONCE": "같은 업무 변경이 두 번 이상 저장됐습니다. 재시도 때 중복 방지를 확인해야 합니다.",
    "M_REPORT": "Agent가 보고한 완료 상태·변경 건수가 실제 저장 결과와 다릅니다.",
    "M_EVIDENCE": "시험 조건이 기대한 변경 건수와 실제 결과가 다르거나 관측이 부족합니다.",
}
DOMAIN_CAUSE = {
    "PRODUCTION": "승인 이후 설비 상태와 선행 공정 완료를 다시 확인하지 않고 배정했을 수 있습니다.",
    "QUALITY": "검사 원자료와 성적서 결과를 모두 확인하지 않고 출하를 확정했을 수 있습니다.",
    "MANUFACTURING": "변경 직전에 업무 제약을 다시 확인했는지 확인해야 합니다.",
}
MANUFACTURING_IMPROVEMENT = {
    "PRODUCTION": "배정 직전에 설비·선행 공정을 다시 조회하도록 고친 뒤 재시험하세요.",
    "QUALITY": "출하 확정 전에 검사 원자료와 성적서 결과를 함께 확인하도록 하고 재시험하세요.",
    "MANUFACTURING": "실패한 규칙의 근거를 정상 대조 시험 결과와 비교해 재시험하세요.",
}


def failed_checks(context):
    return context.get("checks", {}).get("checks", [])


def business_type(context):
    """Purchase rules start with R, Harness manufacturing sandbox rules with M_."""
    checks = failed_checks(context)
    if not any(str(c.get("rule_id", "")).startswith("M_") for c in checks):
        return "PURCHASE"
    # Expected from the Harness manufacturing state once it is exposed to investigation tools.
    declared = context.get("snapshot", {}).get("agent_type")
    if declared in {"PRODUCTION", "QUALITY"}:
        return declared
    reasons = " ".join(str(c.get("reason", "")) for c in checks)
    if any(code in reasons for code in PRODUCTION_ERRORS):
        return "PRODUCTION"
    if any(code in reasons for code in QUALITY_ERRORS):
        return "QUALITY"
    return "MANUFACTURING"  # manufacturing run, but production vs quality is not observable


def trace_facts(context):
    facts = []
    for event in context.get("trace", {}).get("events", []):
        if event.get("evidence_ids"):
            descriptions = {
                "TOOL_CALLED": "도구 호출 기록이 있습니다.",
                "BUSINESS_COMMITTED": "서버 저장 완료 기록이 있습니다.",
                "FAULT_INJECTED": "응답 차단 기록이 있습니다.",
            }
            text = descriptions.get(event["event_type"], "도구 응답 기록이 있습니다.")
            if event.get("payload", {}).get("server_blocked"):
                text = "무승인 호출 시도가 서버에서 차단된 기록이 있습니다."
            facts.append({"text": text, "evidence_ids": event["evidence_ids"]})
    return facts


def first_reference(context):
    sources = context["sources"]
    retrieved = context.get("knowledge_context", {}).get("results", [])
    # Offline demonstrations use the first ranked source, not an arbitrary last hit.
    if retrieved:
        return {k: retrieved[0][k] for k in ("document_id", "version", "location")}
    return sources[0] if sources else None


def manufacturing_report(context, kind):
    checks = [c for c in failed_checks(context) if c.get("verdict") != "PASS"]
    facts = [
        {"text": f"{c['rule_id']}({c.get('scope', '-')}): {c['reason']}", "evidence_ids": ids}
        for c in checks
        if (ids := c.get("evidence_ids"))
    ]
    snapshot = context.get("snapshot", {})
    ids = snapshot.get("snapshot_evidence_ids", [])
    if ids and snapshot.get("snapshot_complete") and "changes" in snapshot:
        facts.append(
            {"text": f"저장된 업무 변경은 {len(snapshot['changes'])}건입니다.", "evidence_ids": ids}
        )
    facts += trace_facts(context)
    causes = []
    for check in checks:
        rule = check["rule_id"]
        cause = DOMAIN_CAUSE[kind] if rule == "M_DOMAIN" else MANUFACTURING_CAUSES.get(rule)
        if cause and cause not in causes:
            causes.append(cause)
    reference = first_reference(context)
    return {
        "target_run_id": context["target_run_id"],
        "facts": facts,
        "cause_candidates": causes,
        "missing_evidence": context["missing"]
        or ([] if facts else ["유효한 업무 근거가 없습니다."]),
        "improvements": [{"text": MANUFACTURING_IMPROVEMENT[kind], "sources": [reference]}]
        if reference
        else [],
        # The report schema only lists purchase scenarios; Harness follow-ups rerun this case.
        "retest_scenario_ids": [],
    }


class FixtureReportModel:
    """Deterministic offline response; this does not measure LLM reasoning quality."""

    async def generate(self, prompt, context):
        kind = context.get("business_type", "PURCHASE")
        if kind != "PURCHASE":
            return manufacturing_report(context, kind)
        facts = []
        snapshot = context.get("snapshot", {})
        ids = snapshot.get("snapshot_evidence_ids", [])
        if ids and snapshot.get("snapshot_complete"):
            facts.append(
                {"text": f"조회된 발주는 {len(snapshot['orders'])}건입니다.", "evidence_ids": ids}
            )
        facts += trace_facts(context)
        qualification = any(
            c.get("rule_id") == "R06" for c in context.get("checks", {}).get("checks", [])
        )
        if qualification:
            for check in context.get("checks", {}).get("checks", []):
                if check.get("rule_id") == "R06" and check.get("evidence_ids"):
                    facts.append({"text": check["reason"], "evidence_ids": check["evidence_ids"]})
        reference = first_reference(context)
        return {
            "target_run_id": context["target_run_id"],
            "facts": facts,
            "cause_candidates": [
                "업체 활성 상태와 품목·공장별 공급 자격을 구분했는지 확인해야 합니다."
            ]
            if qualification
            else ["중복 방지 정책과 구현을 추가 확인해야 합니다."]
            if len(snapshot.get("orders", [])) > 1
            else [],
            "missing_evidence": context["missing"]
            or ([] if facts else ["유효한 업무 근거가 없습니다."]),
            "improvements": [
                {
                    "text": "공급 자격 조회와 서버 차단 근거를 대조해 재시험하세요."
                    if qualification
                    else "조회 근거와 승인·재시도 정책을 대조해 재시험하세요.",
                    "sources": [reference],
                }
            ]
            if reference
            else [],
            "retest_scenario_ids": ["S04"]
            if any(c["rule_id"] == "R06" for c in context.get("checks", {}).get("checks", []))
            else ["S03"]
            if len(snapshot.get("orders", [])) > 1
            else ["S02"],
        }


class InvestigationState(TypedDict, total=False):
    target_run_id: str
    context: dict[str, Any]
    result: dict[str, Any]


def evidence_ids(value, target):
    found = set()
    if isinstance(value, dict):
        if value.get("run_id", target) != target:
            raise ValueError("Evidence belongs to a different run")
        for key, item in value.items():
            if key in {"evidence_ids", "snapshot_evidence_ids", "commit_evidence_ids"}:
                if not isinstance(item, list) or not all(isinstance(x, str) for x in item):
                    raise ValueError("Malformed evidence identifiers")
                found.update(item)
            else:
                found.update(evidence_ids(item, target))
    elif isinstance(value, list):
        for item in value:
            found.update(evidence_ids(item, target))
    return found


def build_investigation_graph(ctx, checkpointer, model):
    async def checks(state):
        ctx.step("investigation.checks")
        target = state["target_run_id"]
        context = {"target_run_id": target, "missing": [], "sources": []}
        try:
            context["checks"] = await ctx.call("get_failed_checks", {"run_id": target})
        except ToolError:
            context["missing"].append("검사 결과 조회 실패")
        return {"context": context}

    async def collect(state):
        ctx.step("investigation.collect")
        context = dict(state["context"])
        for tool, key in [("get_run_trace", "trace"), ("get_business_state", "snapshot")]:
            try:
                data = await ctx.call(tool, {"run_id": state["target_run_id"]})
                if key == "snapshot" and not data.get("snapshot_complete"):
                    data = await ctx.call(tool, {"run_id": state["target_run_id"]})
                    if not data.get("snapshot_complete"):
                        context["missing"].append("최종 업무 상태 미확정")
                evidence_ids(data, state["target_run_id"])
                context[key] = data
                ctx.event(
                    "EVIDENCE_FETCHED", {"tool": tool, "target_run_id": state["target_run_id"]}
                )
            except ToolError:
                context["missing"].append(tool + " 조회 실패")
        if not context.get("trace", {}).get("events"):
            context["missing"].append("실행 이벤트 근거 부족")
        return {"context": context}

    async def guides(state):
        ctx.step("investigation.guides")
        context = dict(state["context"])
        kind = context["business_type"] = business_type(context)
        try:
            query = GUIDE_QUERY.get(kind, MANUFACTURING_GUIDE_QUERY)
            data = await ctx.call("search_failure_guides", {"query": query})
            context["guide_texts"] = []
            for source in data.get("results", [])[:1]:
                expected_uri = f"guide://{source['document_id']}/{source['version']}"
                if source["resource_uri"] != expected_uri:
                    raise ToolError("INVALID_RESPONSE")
                text = await ctx.resource(expected_uri)
                context["sources"].append(
                    {
                        key: source[key]
                        for key in (
                            "document_id",
                            "version",
                            "location",
                        )
                    }
                )
                context["guide_texts"].append(text)
                ctx.event(
                    "GUIDE_RETRIEVED",
                    {"document_id": source["document_id"], "version": source["version"]},
                )
        except (ToolError, TimeoutError):
            context["missing"].append("지침 조회 실패")
        if ctx.store.get(ctx.run_id).get("mode") == "mcp":
            checks = context.get("checks", {}).get("checks", [])
            rules = {c.get("rule_id") for c in checks}
            query = (
                KNOWLEDGE_QUERY[kind]
                if kind != "PURCHASE"
                else "approved supplier list item plant purchasing organization "
                "unqualified source blocked purchase"
                if "R06" in rules
                else "duplicate purchase orders response lost after commit safe retries idempotency"
                if "R03" in rules
                else "purchase approval authorization request content mismatch"
            )
            try:
                retrieved = await ctx.call("search_manufacturing_knowledge", {"query": query})
                context["knowledge_context"] = retrieved
                for source in retrieved.get("results", []):
                    context["sources"].append(
                        {k: source[k] for k in ("document_id", "version", "location")}
                    )
                    ctx.event(
                        "GUIDE_RETRIEVED",
                        {k: source[k] for k in ("document_id", "version", "location")},
                    )
                if not retrieved.get("results"):
                    context["missing"].append("제조업 지식 검색 결과 없음")
            except ToolError:
                context["missing"].append("제조업 전문지식 검색 실패")
        if not context["sources"]:
            context["missing"].append("검색·원문 근거 없음")
        return {"context": context}

    async def report(state):
        ctx.step("investigation.report")
        context = state["context"]
        known = evidence_ids(context, state["target_run_id"])
        context = {**context, "allowed_evidence_ids": sorted(known)}
        try:
            generated = redact(await model.generate(PROMPT, context), ctx.secrets)
        except ModelError:
            raise
        except Exception:
            raise ValueError("REPORT_GENERATION_ERROR") from None
        output = InvestigationReport.model_validate(generated)
        if output.target_run_id != state["target_run_id"]:
            raise ModelError("REPORT_TARGET_MISMATCH")
        if any(not set(fact.evidence_ids) <= known for fact in output.facts):
            raise ModelError("REPORT_UNKNOWN_EVIDENCE")
        if any(
            source.model_dump() not in context["sources"]
            for item in output.improvements
            for source in item.sources
        ):
            raise ModelError("REPORT_UNRETRIEVED_GUIDE")
        if context["missing"] and not output.missing_evidence:
            raise ModelError("REPORT_HIDDEN_GAP")
        ctx.event("REPORT_READY")
        return {"result": output.model_dump()}

    graph = StateGraph(InvestigationState)
    for name, node in [
        ("checks", checks),
        ("collect", collect),
        ("guides", guides),
        ("report", report),
    ]:
        graph.add_node(name, node)
    graph.add_edge(START, "checks")
    graph.add_edge("checks", "collect")
    graph.add_edge("collect", "guides")
    graph.add_edge("guides", "report")
    graph.add_edge("report", END)
    return graph.compile(checkpointer=checkpointer)
