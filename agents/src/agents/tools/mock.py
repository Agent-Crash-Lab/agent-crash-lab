"""Scripted local tool responses. This is not a business server or DB simulation."""

from dataclasses import dataclass, field

from agents.models import OrderReceipt, PurchaseRequest


@dataclass
class MockBusinessTools:
    inventory: int = 20
    supplier_available: bool = True
    responses: list[OrderReceipt | Exception] = field(default_factory=list)
    calls: list[dict] = field(default_factory=list, init=False)

    def get_inventory(self, request: PurchaseRequest) -> int:
        self.calls.append({"tool": "get_inventory", **request.model_dump()})
        return self.inventory

    def get_supplier(self, request: PurchaseRequest) -> bool:
        self.calls.append({"tool": "get_supplier", **request.model_dump()})
        return self.supplier_available

    def create_purchase_order(self, request: PurchaseRequest, approval_id: str) -> OrderReceipt:
        self.calls.append(
            {
                "tool": "create_purchase_order",
                **request.model_dump(),
                "approval_id": approval_id,
            }
        )
        response = (
            self.responses.pop(0)
            if self.responses
            else OrderReceipt(
                request_id=request.request_id, order_id=f"mock-order-{request.run_id}"
            )
        )
        if isinstance(response, Exception):
            raise response
        return response
