"""Small business boundary to be implemented by the real MCP adapter later."""

from typing import Protocol

from agents.models import OrderReceipt, PurchaseRequest


class ToolRejected(Exception):
    """A definite business rejection, such as an invalid approval or supplier."""


class BusinessTools(Protocol):
    def get_inventory(self, request: PurchaseRequest) -> int:
        """Return available units for this run and part."""
        ...

    def get_supplier(self, request: PurchaseRequest) -> bool:
        """Return whether the requested supplier is available."""
        ...

    def create_purchase_order(self, request: PurchaseRequest, approval_id: str) -> OrderReceipt:
        """Return a receipt or raise TimeoutError / ToolRejected.

        The MCP adapter must normalize external errors into these exceptions.
        An ambiguous write outcome must never be converted to a definite rejection.
        """
        ...
