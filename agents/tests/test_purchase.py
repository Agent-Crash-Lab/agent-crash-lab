import asyncio
import json

import pytest
from conftest import approval, purchase, settled
from pydantic import ValidationError

from agents.models import PurchaseRequest, PurchaseResult
from agents.runtime import RunError, Runtime
from agents.tools.errors import ToolError
from agents.tools.mock import MockTools


@pytest.mark.asyncio
async def test_pa01_manual_approval_preserves_payload(runtime):
    body = purchase()
    await runtime.start(body)
    waiting = await settled(runtime, body.run_id)
    assert waiting["status"] == "WAITING_APPROVAL"
    assert not waiting.get("write_started")
    assert waiting["payload_hash"] == body.request.payload_hash()
    await runtime.resume(body.run_id, approval(body))
    done = await settled(runtime, body.run_id)
    assert done["result"]["outcome"] == "SUCCEEDED"
    events = runtime.store.events(body.run_id)
    calls = [e["payload"] for e in events if e["event_type"] == "AGENT_TOOL_CALLED"]
    assert [call["tool"] for call in calls] == [
        "get_inventory",
        "get_supplier",
        "get_supplier_eligibility",
        "create_purchase_order",
    ]
    assert calls[-1]["arguments"] == {
        "request": body.request.model_dump(),
        "approval_id": "AP-TEST",
    }


@pytest.mark.asyncio
async def test_pa02_rejection_never_creates(runtime):
    body = purchase()
    await runtime.start(body)
    await settled(runtime, body.run_id)
    await runtime.resume(body.run_id, approval(body, "REJECTED"))
    done = await settled(runtime, body.run_id)
    assert done["result"]["outcome"] == "REJECTED"
    assert not done.get("write_started")


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("fixture", "expected"),
    [
        ("purchase-timeout-once", "SUCCEEDED"),
        ("purchase-timeout-always", "UNKNOWN"),
    ],
)
async def test_pa03_retry_is_bounded_and_identical(runtime, fixture, expected):
    body = purchase(fixture_id=fixture)
    await runtime.start(body)
    await settled(runtime, body.run_id)
    await runtime.resume(body.run_id, approval(body))
    done = await settled(runtime, body.run_id)
    assert done["result"]["outcome"] == expected
    assert done["write_attempts"] == 2
    calls = [
        e["payload"]
        for e in runtime.store.events(body.run_id)
        if e["event_type"] == "AGENT_TOOL_CALLED"
        and e["payload"]["tool"] == "create_purchase_order"
    ]
    assert calls[0]["arguments"] == calls[1]["arguments"]
    assert calls[0]["agent_call_id"] != calls[1]["agent_call_id"]


@pytest.mark.asyncio
async def test_timeout_then_rejection_remains_unknown(runtime, monkeypatch):
    original = MockTools.call

    async def call(self, name, arguments):
        if name == "create_purchase_order":
            self.create_count += 1
            raise ToolError(
                "TOOL_TIMEOUT" if self.create_count == 1 else "APPROVAL_REJECTED",
                retryable=self.create_count == 1,
            )
        return await original(self, name, arguments)

    monkeypatch.setattr(MockTools, "call", call)
    body = purchase()
    await runtime.start(body)
    await settled(runtime, body.run_id)
    await runtime.resume(body.run_id, approval(body))
    assert (await settled(runtime, body.run_id))["result"]["outcome"] == "UNKNOWN"


@pytest.mark.asyncio
async def test_duplicate_and_concurrent_resume_write_once(runtime):
    body = purchase()
    await runtime.start(body)
    await settled(runtime, body.run_id)
    decision = approval(body)
    await asyncio.gather(
        runtime.resume(body.run_id, decision), runtime.resume(body.run_id, decision)
    )
    done = await settled(runtime, body.run_id)
    assert done["write_attempts"] == 1
    assert (await runtime.resume(body.run_id, decision))["status"] == "COMPLETED"
    with pytest.raises(RunError) as error:
        await runtime.resume(body.run_id, approval(body, "REJECTED"))
    assert error.value.status == 409


@pytest.mark.asyncio
async def test_duplicate_start_busy_and_run_isolation(runtime):
    first, second = purchase(), purchase("RUN-SECOND", request_id="REQ-SECOND")
    await runtime.start(first)
    for body in (first, second):
        with pytest.raises(RunError) as error:
            await runtime.start(body)
        assert error.value.status == 409
    await settled(runtime, first.run_id)
    with pytest.raises(RunError):
        await runtime.resume(first.run_id, approval(second))
    await runtime.resume(first.run_id, approval(first, "REJECTED"))
    await settled(runtime, first.run_id)
    await runtime.start(second)
    assert (await settled(runtime, second.run_id))["status"] == "WAITING_APPROVAL"
    assert runtime.status(first.run_id)["result"]["outcome"] == "REJECTED"


@pytest.mark.asyncio
async def test_checkpoint_survives_restart_with_same_expiry(settings):
    body = purchase()
    runtime = await Runtime(settings).open()
    await runtime.start(body)
    before = await settled(runtime, body.run_id)
    await runtime.close()
    rebuilt = await Runtime(settings).open()
    try:
        assert rebuilt.status(body.run_id)["approval_expires_at"] == before["approval_expires_at"]
        await rebuilt.resume(body.run_id, approval(body))
        done = await settled(rebuilt, body.run_id)
        assert done["result"]["outcome"] == "SUCCEEDED"
        assert done["tool_calls"] == 4
    finally:
        await rebuilt.close()


@pytest.mark.asyncio
async def test_wait_expiry_is_error_not_rejection(runtime):
    runtime.policy["wait_timeout_seconds"] = 0.01
    body = purchase()
    await runtime.start(body)
    await asyncio.sleep(0.1)
    done = runtime.status(body.run_id)
    assert done["status"] == "ERROR"
    assert done["reason"] == "APPROVAL_WAIT_EXPIRED"
    assert done["result"] is None
    with pytest.raises(RunError):
        await runtime.resume(body.run_id, approval(body))


@pytest.mark.asyncio
@pytest.mark.parametrize(
    ("policy", "value", "reason"),
    [
        ("max_tool_calls", 0, "TOOL_CALL_LIMIT"),
        ("max_agent_turns", 0, "TURN_LIMIT"),
        ("max_active_seconds_per_agent", 0, "ACTIVE_OR_TOTAL_TIMEOUT"),
    ],
)
async def test_limits_stop_without_success(runtime, policy, value, reason):
    runtime.policy[policy] = value
    body = purchase()
    await runtime.start(body)
    done = await settled(runtime, body.run_id)
    assert done["status"] == "ERROR" and done["reason"] == reason
    assert not done.get("write_started")


@pytest.mark.asyncio
async def test_interrupted_write_is_not_automatically_replayed(settings):
    runtime = await Runtime(settings).open()
    body = purchase()
    await runtime.start(body)
    await settled(runtime, body.run_id)
    row = runtime.store.get(body.run_id)
    row.update(status="RUNNING", write_started=True, write_attempts=1)
    runtime.store.put(row)
    await runtime.close()
    rebuilt = await Runtime(settings).open()
    try:
        done = rebuilt.status(body.run_id)
        assert done["status"] == "ERROR" and done["reason"] == "PROCESS_INTERRUPTED"
        assert done["result"]["outcome"] == "UNKNOWN"
        assert not rebuilt.tasks
    finally:
        await rebuilt.close()


@pytest.mark.parametrize("quantity", [0, -1, True, "100"])
def test_invalid_quantity(quantity):
    with pytest.raises(ValidationError):
        purchase(quantity=quantity)


def test_hash_matches_shared_fixture():
    from conftest import ROOT

    data = json.loads((ROOT / "qa/examples/investigation/cases.json").read_text())
    record = data["cases"][0]["evidence"][0]["payload"]["approvals"][0]
    assert PurchaseRequest(**record["payload"]).payload_hash() == record["payload_hash"]


@pytest.mark.parametrize(
    "change",
    [
        {"order_id": None},
        {"outcome": "REJECTED"},
        {"message": ""},
    ],
)
def test_purchase_result_rejects_contradictory_or_empty_claims(change):
    data = {"request_id": "REQ-1", "outcome": "SUCCEEDED", "order_id": "PO-1", "message": "완료"}
    with pytest.raises(ValidationError):
        PurchaseResult(**{**data, **change})


@pytest.mark.asyncio
async def test_active_but_unapproved_supplier_is_held_before_approval(runtime):
    body = purchase(supplier_id="SUP-02", unit_price_minor=9000)
    await runtime.start(body)
    done = await settled(runtime, body.run_id)
    assert done["status"] == "COMPLETED"
    assert done["result"]["outcome"] == "NEEDS_INPUT"
    assert "공급 자격" in done["result"]["message"]
    assert not done.get("write_started") and not done.get("approval")
    tools = [
        e["payload"]["tool"]
        for e in runtime.store.events(body.run_id)
        if e["event_type"] == "AGENT_TOOL_CALLED"
    ]
    assert "get_supplier_eligibility" in tools and "create_purchase_order" not in tools


@pytest.mark.asyncio
async def test_eligibility_for_a_different_plant_is_not_trusted(runtime, monkeypatch):
    original = MockTools.call

    async def wrong_plant(self, name, arguments):
        data = await original(self, name, arguments)
        return {**data, "plant_id": "OTHER-PLANT"} if name == "get_supplier_eligibility" else data

    monkeypatch.setattr(MockTools, "call", wrong_plant)
    body = purchase()
    await runtime.start(body)
    done = await settled(runtime, body.run_id)
    assert done["result"]["outcome"] == "FAILED"
    assert not done.get("write_started") and done["status"] != "WAITING_APPROVAL"
