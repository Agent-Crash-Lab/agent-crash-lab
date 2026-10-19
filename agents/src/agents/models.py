"""Internal types; external MCP/Harness schemas will be mapped at the boundary."""

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PurchaseRequest(Model):
    run_id: str = Field(min_length=1)
    request_id: str = Field(min_length=1)
    part_id: str = Field(min_length=1)
    supplier_id: str = Field(min_length=1)
    quantity: int = Field(gt=0, strict=True)


class ApprovalDecision(Model):
    request_id: str = Field(min_length=1)
    decision: Literal["APPROVED", "REJECTED"]
    approval_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def require_approval_id(self) -> "ApprovalDecision":
        if self.decision == "APPROVED" and not self.approval_id:
            raise ValueError("APPROVED requires a server-issued approval_id")
        return self


class OrderReceipt(Model):
    request_id: str = Field(min_length=1)
    order_id: str = Field(min_length=1)


class PurchaseResult(Model):
    request_id: str
    outcome: Literal["SUCCEEDED", "REJECTED", "FAILED", "NEEDS_INPUT", "UNKNOWN"]
    order_id: str | None = None
    message: str
