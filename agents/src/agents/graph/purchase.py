"""Deterministic purchase reference flow, independent of LLM and MCP transport."""

from typing import Any, TypedDict
from uuid import uuid4

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import ValidationError

from agents.models import ApprovalDecision, OrderReceipt, PurchaseRequest, PurchaseResult
from agents.tools.business import BusinessTools, ToolRejected


class PurchaseState(TypedDict, total=False):
    request: dict[str, Any]
    inventory: int
    approval: dict[str, Any]
    calls: list[dict[str, Any]]
    result: dict[str, Any]


def result(request: PurchaseRequest, outcome: str, message: str) -> dict[str, Any]:
    return PurchaseResult(
        request_id=request.request_id, outcome=outcome, message=message
    ).model_dump()


def build_purchase_graph(tools: BusinessTools, checkpointer: BaseCheckpointSaver):
    def prepare(state: PurchaseState) -> dict[str, Any]:
        request = PurchaseRequest.model_validate(state["request"])
        try:
            inventory = tools.get_inventory(request)
            if type(inventory) is not int or inventory < 0:
                raise ToolRejected("Invalid inventory response")
            if inventory >= request.quantity:
                return {
                    "inventory": inventory,
                    "result": result(
                        request, "NEEDS_INPUT", "재고가 충분합니다. 발주 필요 여부를 확인해주세요."
                    ),
                }
            supplier_available = tools.get_supplier(request)
            if type(supplier_available) is not bool or not supplier_available:
                raise ToolRejected("Supplier unavailable or invalid response")
        except (TimeoutError, ToolRejected):
            return {"result": result(request, "FAILED", "재고·공급업체 조회에 실패했습니다.")}
        return {"inventory": inventory}

    def approval(state: PurchaseState) -> dict[str, Any]:
        request = PurchaseRequest.model_validate(state["request"])
        # This node re-executes on resume. Keep all external effects in other nodes.
        decision = ApprovalDecision.model_validate(
            interrupt(
                {
                    "status": "WAITING_APPROVAL",
                    "proposal": request.model_dump(),
                    "inventory": state["inventory"],
                }
            )
        )
        if decision.request_id != request.request_id:
            raise ValueError("Approval request_id does not match the pending request")
        update: dict[str, Any] = {"approval": decision.model_dump()}
        if decision.decision == "REJECTED":
            update["result"] = result(request, "REJECTED", "담당자가 발주를 거절했습니다.")
        return update

    def create(state: PurchaseState) -> dict[str, Any]:
        request = PurchaseRequest.model_validate(state["request"])
        decision = ApprovalDecision.model_validate(state["approval"])
        if decision.decision != "APPROVED" or decision.approval_id is None:
            raise ValueError("Order creation requires approval")
        calls = []
        for attempt in range(2):
            call = {
                "tool_call_id": str(uuid4()),
                "tool": "create_purchase_order",
                "run_id": request.run_id,
                "request_id": request.request_id,
                "approval_id": decision.approval_id,
                "attempt": attempt + 1,
                "payload": request.model_dump(),
            }
            calls.append(call)
            try:
                receipt = OrderReceipt.model_validate(
                    tools.create_purchase_order(request, decision.approval_id)
                )
            except TimeoutError:
                call["status"] = "TIMEOUT"
                continue
            except ToolRejected:
                call["status"] = "REJECTED"
                # An earlier timeout may already have committed the order.
                outcome = "UNKNOWN" if attempt else "FAILED"
                return {
                    "calls": calls,
                    "result": result(
                        request,
                        outcome,
                        "발주 생성 요청이 거부되었습니다. "
                        "이전 타임아웃이 있다면 저장 여부는 미확정입니다.",
                    ),
                }
            except ValidationError:
                call["status"] = "INVALID_RECEIPT"
                return {
                    "calls": calls,
                    "result": result(
                        request,
                        "UNKNOWN",
                        "도구 응답 형식이 잘못되어 생성 결과를 확인할 수 없습니다.",
                    ),
                }
            if receipt.request_id != request.request_id:
                call["status"] = "INVALID_RECEIPT"
                return {
                    "calls": calls,
                    "result": result(
                        request,
                        "UNKNOWN",
                        "요청과 다른 생성 결과를 받아 완료 여부를 확인할 수 없습니다.",
                    ),
                }
            call["status"] = "SUCCEEDED"
            return {
                "calls": calls,
                "result": PurchaseResult(
                    request_id=request.request_id,
                    outcome="SUCCEEDED",
                    order_id=receipt.order_id,
                    message=f"승인된 부품 {request.quantity}개 발주를 확인했습니다.",
                ).model_dump(),
            }
        return {
            "calls": calls,
            "result": result(
                request, "UNKNOWN", "응답을 확인하지 못했습니다. 실제 발주 상태 확인이 필요합니다."
            ),
        }

    graph = StateGraph(PurchaseState)
    graph.add_node("prepare", prepare)
    graph.add_node("approval", approval)
    graph.add_node("create", create)
    graph.add_edge(START, "prepare")
    graph.add_conditional_edges("prepare", lambda state: END if "result" in state else "approval")
    graph.add_conditional_edges("approval", lambda state: END if "result" in state else "create")
    graph.add_edge("create", END)
    return graph.compile(checkpointer=checkpointer)


class PurchaseAgent:
    """Python entry point for serial local execution, not an authenticated API.

    The caller must obtain approval from the trusted server. An approval_id here
    is only a reference; validating approver identity/payload belongs to that server.
    """

    def __init__(self, tools: BusinessTools, checkpointer: BaseCheckpointSaver | None = None):
        # shortcut: local-only memory; inject a durable saver before deployed integration.
        self.graph = build_purchase_graph(
            tools, checkpointer if checkpointer is not None else InMemorySaver()
        )

    @staticmethod
    def _config(run_id: str) -> dict[str, Any]:
        if not run_id.strip():
            raise ValueError("run_id must not be empty")
        return {"configurable": {"thread_id": run_id}}

    def start(self, request: PurchaseRequest) -> dict[str, Any]:
        config = self._config(request.run_id)
        if self.graph.get_state(config).values:
            raise ValueError("run_id already exists; use resume for pending approval")
        self.graph.invoke({"request": request.model_dump(), "calls": []}, config)
        return self.status(request.run_id)

    def resume(self, run_id: str, decision: ApprovalDecision) -> dict[str, Any]:
        config = self._config(run_id)
        snapshot = self.graph.get_state(config)
        if snapshot.next != ("approval",):
            raise ValueError("Run is not waiting for approval")
        if decision.request_id != snapshot.values["request"]["request_id"]:
            raise ValueError("Approval request_id does not match the pending request")
        self.graph.invoke(Command(resume=decision.model_dump()), config)
        return self.status(run_id)

    def status(self, run_id: str) -> dict[str, Any]:
        snapshot = self.graph.get_state(self._config(run_id))
        if not snapshot.values:
            raise ValueError("Unknown run_id")
        state = snapshot.values
        status = (
            "COMPLETED"
            if "result" in state
            else ("WAITING_APPROVAL" if snapshot.next == ("approval",) else "ERROR")
        )
        return {
            "run_id": run_id,
            "status": status,
            "proposal": state["request"],
            "result": state.get("result"),
            "calls": state.get("calls", []),
        }
