"""Async reference purchase workflow; B0/B1 use identical Agent behavior."""

from typing import Any, TypedDict

from langgraph.graph import END, START, StateGraph
from langgraph.types import interrupt

from agents.models import ApprovalDecision, PurchaseRequest, PurchaseResult
from agents.tools.business import ToolError


class PurchaseState(TypedDict, total=False):
    request: dict[str, Any]
    inventory: int
    approval: dict[str, Any]
    result: dict[str, Any]


def build_purchase_graph(ctx, checkpointer):
    def result(request, outcome, message, order_id=None):
        return {
            "result": PurchaseResult(
                request_id=request.request_id,
                outcome=outcome,
                order_id=order_id,
                message=message,
            ).model_dump()
        }

    async def prepare(state):
        ctx.step("purchase.prepare")
        request = PurchaseRequest.model_validate(state["request"])
        try:
            stock = await ctx.call(
                "get_inventory",
                {
                    "part_id": request.part_id,
                    "plant_id": request.plant_id,
                },
            )
            available = stock["available_quantity"]
            if (
                stock["part_id"] != request.part_id
                or stock["plant_id"] != request.plant_id
                or stock["unit"] != "EA"
                or type(available) is not int
                or available < 0
                or type(stock.get("inventory_version")) is not int
                or stock["inventory_version"] < 1
            ):
                raise ToolError("INVALID_RESPONSE")
            if available >= request.quantity:
                return result(
                    request, "NEEDS_INPUT", "재고가 충분합니다. 발주 필요 여부를 확인해주세요."
                )
            supplier = await ctx.call("get_supplier", {"supplier_id": request.supplier_id})
            if (
                supplier["supplier_id"] != request.supplier_id
                or supplier["status"] != "ACTIVE"
                or supplier["currency"] != request.currency
                or type(supplier["unit_price_minor"]) is not int
                or supplier["unit_price_minor"] != request.unit_price_minor
                or type(supplier.get("supplier_version")) is not int
                or supplier["supplier_version"] < 1
            ):
                raise ToolError("INVALID_RESPONSE")
        except (ToolError, KeyError, TypeError):
            return result(request, "FAILED", "재고·공급업체 조회 결과를 확인하지 못했습니다.")
        return {"inventory": available}

    async def approval(state):
        # interrupt nodes restart on resume; keep writes outside this node.
        decision = ApprovalDecision.model_validate(
            interrupt(
                {
                    "request": state["request"],
                    "payload_hash": PurchaseRequest.model_validate(state["request"]).payload_hash(),
                }
            )
        )
        ctx.step("purchase.approval")
        request = PurchaseRequest.model_validate(state["request"])
        if (
            decision.request_id != request.request_id
            or decision.payload_hash != request.payload_hash()
        ):
            raise ValueError("Approval does not match the pending payload")
        update = {"approval": decision.model_dump(mode="json")}
        if decision.decision == "REJECTED":
            update.update(result(request, "REJECTED", "담당자가 발주를 거절했습니다."))
        return update

    async def create(state):
        ctx.step("purchase.create")
        request = PurchaseRequest.model_validate(state["request"])
        decision = ApprovalDecision.model_validate(state["approval"])
        if decision.decision != "APPROVED":
            raise ValueError("Creation requires approval")
        try:
            receipt = await ctx.call(
                "create_purchase_order",
                {
                    "request": request.model_dump(),
                    "approval_id": decision.approval_id,
                },
            )
            if (
                receipt.get("request_id") != request.request_id
                or not isinstance(receipt.get("order_id"), str)
                or not receipt["order_id"].strip()
                or receipt.get("status") != "CREATED"
                or type(receipt.get("committed_version")) is not int
                or receipt["committed_version"] != request.request_version
            ):
                raise ToolError("INVALID_RESPONSE")
        except ToolError as error:
            ambiguous = ctx.store.get(ctx.run_id).get("write_ambiguous")
            outcome = (
                "UNKNOWN"
                if ambiguous
                or error.code
                in {
                    "INVALID_RESPONSE",
                    "PROTOCOL_ERROR",
                    "TRANSPORT_ERROR",
                    "ADAPTER_ERROR",
                }
                else "FAILED"
            )
            return result(request, outcome, "생성 결과를 확인하지 못했습니다. 코드: " + error.code)
        return result(
            request, "SUCCEEDED", "승인된 발주 생성 응답을 확인했습니다.", receipt["order_id"]
        )

    graph = StateGraph(PurchaseState)
    graph.add_node("prepare", prepare)
    graph.add_node("approval", approval)
    graph.add_node("create", create)
    graph.add_edge(START, "prepare")
    graph.add_conditional_edges("prepare", lambda state: END if "result" in state else "approval")
    graph.add_conditional_edges("approval", lambda state: END if "result" in state else "create")
    graph.add_edge("create", END)
    return graph.compile(checkpointer=checkpointer)
