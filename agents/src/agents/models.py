"""Business payload follows contracts and MCP spec v0.2; APIs remain a draft."""

import hashlib
import json
from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, SecretStr, model_validator


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, str_strip_whitespace=True)


class PurchaseRequest(Model):
    request_id: str = Field(min_length=1)
    request_version: int = Field(ge=1, strict=True)
    part_id: str = Field(min_length=1)
    quantity: int = Field(gt=0, strict=True)
    unit_price_minor: int = Field(ge=0, strict=True)
    currency: Literal["KRW"]
    supplier_id: str = Field(min_length=1)
    plant_id: str = Field(min_length=1)
    purchasing_org_id: str = Field(min_length=1)

    def payload_hash(self) -> str:
        encoded = json.dumps(
            self.model_dump(), sort_keys=True, ensure_ascii=False, separators=(",", ":")
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()


class ApprovalDecision(Model):
    request_id: str = Field(min_length=1)
    approval_id: str = Field(min_length=1)
    decision: Literal["APPROVED", "REJECTED"]
    payload_hash: str = Field(pattern=r"^[0-9a-f]{64}$")
    approver_id: str = Field(min_length=1)
    decided_at: datetime

    @model_validator(mode="after")
    def require_timezone(self):
        if self.decided_at.tzinfo is None:
            raise ValueError("decided_at must include a timezone")
        return self


class ResumeRequest(ApprovalDecision):
    agent_token: SecretStr | None = Field(default=None, exclude=True)


class StartRequest(Model):
    run_id: str = Field(min_length=1, max_length=128)
    agent_kind: Literal["PURCHASE_AGENT", "INVESTIGATION_AGENT"] = "PURCHASE_AGENT"
    mode: Literal["mock", "mcp"] = "mock"
    request: PurchaseRequest | None = None
    target_run_id: str | None = Field(default=None, min_length=1)
    fixture_id: (
        Literal[
            "purchase-normal",
            "purchase-timeout-once",
            "purchase-timeout-always",
            "ia01-v1",
            "ia02-v1",
            "ia03-v1",
        ]
        | None
    ) = None
    agent_token: SecretStr | None = Field(default=None, exclude=True)

    @model_validator(mode="after")
    def check_kind(self):
        if self.agent_kind == "PURCHASE_AGENT":
            if self.request is None or self.target_run_id is not None:
                raise ValueError("Purchase runs require request and no target_run_id")
            if self.fixture_id and not self.fixture_id.startswith("purchase-"):
                raise ValueError("Invalid purchase fixture")
        else:
            if self.request is not None or not self.target_run_id:
                raise ValueError("Investigation runs require target_run_id and no request")
            if self.mode == "mock" and self.fixture_id not in {"ia01-v1", "ia02-v1", "ia03-v1"}:
                raise ValueError("Select an investigation fixture")
        if self.mode == "mcp" and (self.fixture_id or not self.agent_token):
            raise ValueError("MCP mode requires agent_token and does not accept fixtures")
        return self


class PurchaseResult(Model):
    request_id: str = Field(min_length=1)
    outcome: Literal["SUCCEEDED", "REJECTED", "FAILED", "NEEDS_INPUT", "UNKNOWN"]
    order_id: str | None = Field(default=None, min_length=1)
    message: str = Field(min_length=1)

    @model_validator(mode="after")
    def require_consistent_order(self):
        if self.outcome == "SUCCEEDED" and self.order_id is None:
            raise ValueError("Success requires a confirmed order_id")
        if self.outcome == "REJECTED" and self.order_id is not None:
            raise ValueError("Rejected results cannot claim an order_id")
        return self


class Fact(Model):
    text: str = Field(min_length=1)
    evidence_ids: list[str] = Field(min_length=1)


class Source(Model):
    document_id: str
    version: str
    location: str


class Improvement(Model):
    text: str = Field(min_length=1)
    sources: list[Source] = Field(min_length=1)


class InvestigationReport(Model):
    target_run_id: str
    facts: list[Fact]
    cause_candidates: list[str]
    missing_evidence: list[str]
    improvements: list[Improvement]
    retest_scenario_ids: list[Literal["S01", "S02", "S03", "S04"]]

    @model_validator(mode="after")
    def require_findings_or_missing(self):
        if not self.facts and not self.missing_evidence:
            raise ValueError("A report needs findings or an explicit evidence gap")
        return self
