"""Read-only investigation with an injectable model and verified source references."""

from pathlib import Path
from typing import Any, Protocol, TypedDict

from langgraph.graph import END, START, StateGraph

from agents.config import redact
from agents.models import InvestigationReport
from agents.tools.business import ToolError

PROMPT = (Path(__file__).parents[1] / "prompts/investigation.txt").read_text()


class ReportModel(Protocol):
    async def generate(self, prompt: str, context: dict) -> dict: ...


class FixtureReportModel:
    """Deterministic offline response; this does not measure LLM reasoning quality."""

    async def generate(self, prompt, context):
        facts = []
        snapshot = context.get("snapshot", {})
        ids = snapshot.get("snapshot_evidence_ids", [])
        if ids and snapshot.get("snapshot_complete"):
            facts.append(
                {"text": f"조회된 발주는 {len(snapshot['orders'])}건입니다.", "evidence_ids": ids}
            )
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
        sources = context["sources"]
        return {
            "target_run_id": context["target_run_id"],
            "facts": facts,
            "cause_candidates": ["중복 방지 정책과 구현을 추가 확인해야 합니다."]
            if len(snapshot.get("orders", [])) > 1
            else [],
            "missing_evidence": context["missing"]
            or ([] if facts else ["유효한 업무 근거가 없습니다."]),
            "improvements": [
                {
                    "text": "조회 근거와 승인·재시도 정책을 대조해 재시험하세요.",
                    "sources": [sources[0]],
                }
            ]
            if sources
            else [],
            "retest_scenario_ids": ["S03"] if len(snapshot.get("orders", [])) > 1 else ["S02"],
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
        try:
            data = await ctx.call("search_failure_guides", {"query": "승인 재시도 사고 조사 근거"})
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
        if not context["sources"]:
            context["missing"].append("검색·원문 근거 없음")
        return {"context": context}

    async def report(state):
        ctx.step("investigation.report")
        context = state["context"]
        known = evidence_ids(context, state["target_run_id"])
        try:
            generated = redact(await model.generate(PROMPT, context), ctx.secrets)
        except Exception:
            raise ValueError("REPORT_GENERATION_ERROR") from None
        output = InvestigationReport.model_validate(generated)
        if output.target_run_id != state["target_run_id"]:
            raise ValueError("Report target mismatch")
        if any(not set(fact.evidence_ids) <= known for fact in output.facts):
            raise ValueError("Report cites unknown evidence")
        if any(
            source.model_dump() not in context["sources"]
            for item in output.improvements
            for source in item.sources
        ):
            raise ValueError("Report cites an unretrieved guide")
        if context["missing"] and not output.missing_evidence:
            raise ValueError("Report hides missing evidence")
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
