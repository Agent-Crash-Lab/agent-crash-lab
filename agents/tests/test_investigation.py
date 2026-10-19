from copy import deepcopy

import pytest
from conftest import settled

from agents.graph.investigation import FixtureReportModel
from agents.models import StartRequest
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
