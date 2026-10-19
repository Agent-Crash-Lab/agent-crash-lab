"""Behavior tests for the reference purchase Agent (PA01/02/03)."""

import pytest
from pydantic import ValidationError

from agents.graph.purchase import PurchaseAgent
from agents.models import ApprovalDecision, OrderReceipt, PurchaseRequest
from agents.tools.business import ToolRejected
from agents.tools.mock import MockBusinessTools


def request(run_id: str = "run-1") -> PurchaseRequest:
    return PurchaseRequest(
        run_id=run_id,
        request_id=f"req-{run_id}",
        part_id="PART-A",
        supplier_id="SUP-01",
        quantity=100,
    )


def approve(req: PurchaseRequest) -> ApprovalDecision:
    return ApprovalDecision(
        request_id=req.request_id, decision="APPROVED", approval_id="approval-1"
    )


def writes(tools: MockBusinessTools) -> list[dict]:
    return [call for call in tools.calls if call["tool"] == "create_purchase_order"]


def test_pa01_wait_then_approve_preserves_payload() -> None:
    tools = MockBusinessTools()
    agent = PurchaseAgent(tools)
    req = request()
    waiting = agent.start(req)
    assert waiting["status"] == "WAITING_APPROVAL"
    assert waiting["result"] is None
    assert waiting["proposal"] == req.model_dump()
    assert not writes(tools)
    done = agent.resume(req.run_id, approve(req))
    assert done["status"] == "COMPLETED"
    assert done["result"]["outcome"] == "SUCCEEDED"
    assert done["result"]["order_id"] == "mock-order-run-1"
    assert writes(tools) == [
        {"tool": "create_purchase_order", **req.model_dump(), "approval_id": "approval-1"}
    ]
    assert [call["tool"] for call in tools.calls] == [
        "get_inventory",
        "get_supplier",
        "create_purchase_order",
    ]
    assert done["calls"][0]["attempt"] == 1


def test_pa02_rejected_never_calls_create() -> None:
    tools = MockBusinessTools()
    agent = PurchaseAgent(tools)
    req = request()
    agent.start(req)
    done = agent.resume(
        req.run_id, ApprovalDecision(request_id=req.request_id, decision="REJECTED")
    )
    assert done["result"]["outcome"] == "REJECTED"
    assert done["result"]["order_id"] is None
    assert not writes(tools)


@pytest.mark.parametrize(
    ("responses", "expected", "count"),
    [
        ([TimeoutError()], "SUCCEEDED", 2),
        ([TimeoutError(), TimeoutError()], "UNKNOWN", 2),
        ([ToolRejected()], "FAILED", 1),
        ([TimeoutError(), ToolRejected()], "UNKNOWN", 2),
        ([OrderReceipt(request_id="wrong-request", order_id="order-1")], "UNKNOWN", 1),
    ],
)
def test_pa03_recovery_policy(responses: list, expected: str, count: int) -> None:
    tools = MockBusinessTools(responses=responses.copy())
    agent = PurchaseAgent(tools)
    req = request()
    agent.start(req)
    done = agent.resume(req.run_id, approve(req))
    assert done["result"]["outcome"] == expected
    assert len(writes(tools)) == count
    assert all(call == writes(tools)[0] for call in writes(tools))
    assert all(call["quantity"] == 100 for call in writes(tools))
    assert len({call["tool_call_id"] for call in done["calls"]}) == count
    assert [call["attempt"] for call in done["calls"]] == list(range(1, count + 1))
    if expected != "SUCCEEDED":
        assert done["result"]["order_id"] is None


def test_runs_are_isolated_and_wrong_approval_can_be_corrected() -> None:
    tools = MockBusinessTools()
    agent = PurchaseAgent(tools)
    first, second = request("first"), request("second")
    agent.start(first)
    agent.start(second)
    with pytest.raises(ValueError, match="request_id"):
        agent.resume(first.run_id, approve(second))
    assert not writes(tools)
    assert agent.status(first.run_id)["status"] == "WAITING_APPROVAL"
    agent.resume(second.run_id, approve(second))
    assert agent.status(first.run_id)["status"] == "WAITING_APPROVAL"
    agent.resume(first.run_id, ApprovalDecision(request_id=first.request_id, decision="REJECTED"))
    assert [call["run_id"] for call in writes(tools)] == [second.run_id]


def test_duplicate_start_and_resume_do_not_repeat_writes() -> None:
    tools = MockBusinessTools()
    agent = PurchaseAgent(tools)
    req = request()
    agent.start(req)
    with pytest.raises(ValueError, match="already exists"):
        agent.start(req)
    agent.resume(req.run_id, approve(req))
    with pytest.raises(ValueError, match="not waiting"):
        agent.resume(req.run_id, approve(req))
    with pytest.raises(ValueError, match="already exists"):
        agent.start(req)
    assert len(writes(tools)) == 1


def test_unknown_run_cannot_resume() -> None:
    agent = PurchaseAgent(MockBusinessTools())
    with pytest.raises(ValueError, match="not waiting"):
        agent.resume("missing", approve(request()))
    with pytest.raises(ValueError, match="Unknown"):
        agent.status("missing")


@pytest.mark.parametrize("quantity", [0, -1, True, "100"])
def test_invalid_quantity_rejected(quantity: object) -> None:
    with pytest.raises(ValidationError):
        PurchaseRequest(**{**request().model_dump(), "quantity": quantity})


@pytest.mark.parametrize("approval_id", [None, "", " "])
def test_approval_id_required(approval_id: str | None) -> None:
    with pytest.raises(ValidationError):
        ApprovalDecision(request_id="req-1", decision="APPROVED", approval_id=approval_id)


@pytest.mark.parametrize("inventory", [100, 101])
def test_sufficient_inventory_requests_clarification(inventory: int) -> None:
    tools = MockBusinessTools(inventory=inventory)
    done = PurchaseAgent(tools).start(request())
    assert done["result"]["outcome"] == "NEEDS_INPUT"
    assert not writes(tools)


@pytest.mark.parametrize("inventory", [-1, True, "20"])
def test_invalid_inventory_never_reaches_approval(inventory: object) -> None:
    tools = MockBusinessTools(inventory=inventory)
    done = PurchaseAgent(tools).start(request())
    assert done["result"]["outcome"] == "FAILED"
    assert not writes(tools)


def test_unavailable_supplier_prevents_create() -> None:
    tools = MockBusinessTools(supplier_available=False)
    done = PurchaseAgent(tools).start(request())
    assert done["result"]["outcome"] == "FAILED"
    assert not writes(tools)


def test_invalid_receipt_does_not_report_success_or_retry() -> None:
    class MalformedTools(MockBusinessTools):
        def create_purchase_order(self, req, approval_id):
            super().create_purchase_order(req, approval_id)
            return {"request_id": req.request_id, "order_id": ""}

    tools = MalformedTools()
    agent = PurchaseAgent(tools)
    req = request()
    agent.start(req)
    done = agent.resume(req.run_id, approve(req))
    assert done["result"]["outcome"] == "UNKNOWN"
    assert len(writes(tools)) == 1


@pytest.mark.parametrize("failure", [TimeoutError(), ToolRejected()])
def test_lookup_failure_does_not_create(failure: Exception) -> None:
    class FailingLookup(MockBusinessTools):
        def get_inventory(self, req):
            raise failure

    tools = FailingLookup()
    done = PurchaseAgent(tools).start(request())
    assert done["result"]["outcome"] == "FAILED"
    assert not writes(tools)


def test_unexpected_tool_error_is_not_reported_as_waiting_approval() -> None:
    tools = MockBusinessTools(responses=[RuntimeError("adapter bug")])
    agent = PurchaseAgent(tools)
    req = request()
    agent.start(req)
    with pytest.raises(RuntimeError, match="adapter bug"):
        agent.resume(req.run_id, approve(req))
    assert agent.status(req.run_id)["status"] == "ERROR"
    with pytest.raises(ValueError, match="not waiting"):
        agent.resume(req.run_id, approve(req))
    assert len(writes(tools)) == 1


def test_injected_checkpointer_can_resume_in_rebuilt_agent() -> None:
    from langgraph.checkpoint.memory import InMemorySaver

    saver = InMemorySaver()
    tools = MockBusinessTools()
    req = request()
    PurchaseAgent(tools, checkpointer=saver).start(req)
    rebuilt = PurchaseAgent(tools, checkpointer=saver)
    done = rebuilt.resume(req.run_id, approve(req))
    assert done["result"]["outcome"] == "SUCCEEDED"
    assert len(tools.calls) == 3
