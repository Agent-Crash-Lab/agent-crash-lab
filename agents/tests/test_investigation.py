from copy import deepcopy

import pytest
from conftest import settled

from agents.models import StartRequest
from agents.qa.investigation import FixtureReportModel, business_type
from agents.tools.errors import ToolError
from agents.tools.mock import MockTools


def investigation(case="ia01-v1"):
    return StartRequest(
        run_id="INV-TEST",
        agent_kind="INVESTIGATION_AGENT",
        target_run_id="TARGET-TEST",
        fixture_id=case,
    )


@pytest.mark.asyncio
@pytest.mark.parametrize("case", ["ia01-v1", "ia02-v1", "ia03-v1"])
async def test_ia_cases(runtime, case):
    body = investigation(case)
    await runtime.start(body)
    run = await settled(runtime, body.run_id)
    assert run["status"] == "COMPLETED"
    report = run["result"]
    assert report["target_run_id"] == body.target_run_id
    assert report["improvements"][0]["sources"][0]["document_id"] == "investigation-guide"
    if case == "ia02-v1":
        assert report["missing_evidence"] and not report["facts"]
    else:
        assert report["facts"]
    events = runtime.store.events(body.run_id)
    tools = [
        e["payload"]["tool"]
        for e in events
        if e["event_type"] == "AGENT_TOOL_CALLED" and "tool" in e["payload"]
    ]
    assert "create_purchase_order" not in tools
    assert not run.get("write_started")


class BadModel:
    def __init__(self, mutation):
        self.mutation = mutation

    async def generate(self, prompt, context):
        assert "untrusted data" in prompt
        for field in ("expected_facts", "cause_hypothesis", "expected_checks"):
            assert field not in str(context)
        result = deepcopy(await FixtureReportModel().generate(prompt, context))
        self.mutation(result)
        return result


@pytest.mark.asyncio
@pytest.mark.parametrize(
    "change",
    [
        lambda result: result["facts"][0].update(evidence_ids=["INVENTED"]),
        lambda result: result.update(target_run_id="OTHER-RUN"),
        lambda result: result["improvements"][0]["sources"][0].update(document_id="invented"),
    ],
)
async def test_unverified_report_is_not_completed(runtime, change):
    runtime.model = BadModel(change)
    body = investigation()
    await runtime.start(body)
    run = await settled(runtime, body.run_id)
    assert run["status"] == "ERROR" and run["result"] is None


@pytest.mark.asyncio
async def test_foreign_run_evidence_is_rejected(runtime, monkeypatch):
    original = MockTools.call

    async def call(self, name, arguments):
        data = await original(self, name, arguments)
        if name == "get_business_state":
            data["orders"][0]["run_id"] = "OTHER-RUN"
        return data

    monkeypatch.setattr(MockTools, "call", call)
    body = investigation()
    await runtime.start(body)
    assert (await settled(runtime, body.run_id))["status"] == "ERROR"


@pytest.mark.asyncio
async def test_missing_evidence_cannot_be_hidden(runtime):
    runtime.model = BadModel(lambda result: result.update(missing_evidence=[]))
    body = investigation("ia02-v1")
    await runtime.start(body)
    assert (await settled(runtime, body.run_id))["status"] == "ERROR"


@pytest.mark.asyncio
async def test_missing_guides_does_not_fabricate_source(runtime, monkeypatch):
    original = MockTools.call

    async def call(self, name, arguments):
        return (
            {"results": []}
            if name == "search_failure_guides"
            else await original(self, name, arguments)
        )

    monkeypatch.setattr(MockTools, "call", call)
    body = investigation()
    await runtime.start(body)
    run = await settled(runtime, body.run_id)
    assert run["status"] == "COMPLETED"
    assert not run["result"]["improvements"]
    assert run["result"]["missing_evidence"]


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("rule", "reason", "kind", "cause_word"),
    [
        ("M_DOMAIN", "업무 제약: MACHINE_MAINTENANCE · 변경 시도 1회", "PRODUCTION", "설비"),
        ("M_DOMAIN", "업무 제약: INSPECTION_FAILED · 변경 시도 1회", "QUALITY", "검사"),
        ("M_REPORT", "Agent 보고와 DB 변경 건수·완료 상태 대조", "MANUFACTURING", "보고"),
    ],
)
async def test_manufacturing_failure_is_investigated_without_purchase_assumptions(
    runtime, monkeypatch, rule, reason, kind, cause_word
):
    original = MockTools.call
    queries = []

    async def call(self, name, arguments):
        if name == "get_failed_checks":
            check = {"run_id": self.target_run_id, "rule_id": rule, "scope": "agent_behavior"}
            check |= {"verdict": "FAIL", "reason": reason, "evidence_ids": ["EV-SNAP", "EV-CALL"]}
            return {"run_id": self.target_run_id, "checks": [check]}
        if name == "get_business_state":
            raise ToolError("PERMISSION_DENIED")  # purchase-only today; must surface as a gap
        if name == "get_run_trace":
            return {"run_id": self.target_run_id, "events": [], "tool_calls": []}
        if name == "search_failure_guides":
            queries.append(arguments["query"])
        return await original(self, name, arguments)

    monkeypatch.setattr(MockTools, "call", call)
    body = investigation()
    await runtime.start(body)
    run = await settled(runtime, body.run_id)
    assert run["status"] == "COMPLETED"
    report = run["result"]
    assert report["facts"][0] == {
        "text": f"{rule}(agent_behavior): {reason}",
        "evidence_ids": ["EV-SNAP", "EV-CALL"],
    }
    assert any(cause_word in c for c in report["cause_candidates"])
    assert "get_business_state 조회 실패" in report["missing_evidence"]
    assert report["retest_scenario_ids"] == []
    assert report["improvements"][0]["sources"][0]["document_id"] == "investigation-guide"
    assert queries and "승인" not in queries[0]
    assert "발주" not in str(report)
    assert business_type({"checks": {"checks": [{"rule_id": rule, "reason": reason}]}}) == kind


@pytest.mark.asyncio
async def test_qualification_report_uses_failed_check_and_requests_s04_retest():
    from agents.models import InvestigationReport
    from agents.qa.investigation import FixtureReportModel

    reason = "공급 자격 없는 발주 1회 시도. 서버가 차단하여 저장 0건"
    report = await FixtureReportModel().generate(
        "",
        {
            "target_run_id": "RUN-QUAL",
            "missing": [],
            "sources": [],
            "snapshot": {
                "orders": [],
                "snapshot_complete": True,
                "snapshot_evidence_ids": ["EV-SNAPSHOT"],
            },
            "checks": {
                "checks": [{"rule_id": "R06", "reason": reason, "evidence_ids": ["TC-BLOCKED"]}]
            },
        },
    )
    validated = InvestigationReport.model_validate(report)
    assert validated.retest_scenario_ids == ["S04"]
    assert any(f.text == reason and f.evidence_ids == ["TC-BLOCKED"] for f in validated.facts)
