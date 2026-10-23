"""Model-selected purchase steps; approval, arguments and retry policy stay in code."""

from pathlib import Path
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from agents.llm import ModelError
from agents.models import PurchaseRequest, PurchaseResult

PROMPT = (Path(__file__).parents[1] / "prompts/purchase.txt").read_text()


class PurchaseChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "get_inventory",
        "get_supplier",
        "get_supplier_eligibility",
        "request_approval",
        "create_purchase_order",
        "finish",
    ]
    outcome: Literal["SUCCEEDED", "REJECTED", "FAILED", "NEEDS_INPUT", "UNKNOWN"] | None
    order_id: str | None
    message: str = Field(min_length=1)


async def choose(ctx, model, state, allowed, receipt=None):
    ctx.step("purchase.decide")
    choice = PurchaseChoice.model_validate(
        await model.generate(
            PROMPT,
            {
                "request": state["request"],
                "observations": state.get("observations", {}),
                "approval": state.get("approval"),
                "receipt": receipt,
                "allowed_actions": allowed,
            },
        )
    )
    if choice.action not in allowed:
        ctx.event("AGENT_MODEL_BLOCKED", {"action": choice.action, "reason": "DISALLOWED_ACTION"})
        raise ModelError("LLM_DISALLOWED_ACTION")
    return choice


def result(ctx, request, choice, expected, order_id=None):
    if choice.outcome != expected or choice.order_id != order_id:
        ctx.event(
            "AGENT_MODEL_BLOCKED",
            {
                "reason": "UNSUPPORTED_RESULT",
                "claimed_outcome": choice.outcome,
                "claimed_order_id": choice.order_id,
                "required_outcome": expected,
                "observed_order_id": order_id,
            },
        )
        raise ModelError("LLM_UNSUPPORTED_RESULT")
    return {
        "result": PurchaseResult(
            request_id=request.request_id,
            outcome=expected,
            order_id=order_id,
            message=choice.message,
        ).model_dump()
    }


async def prepare(
    ctx,
    model,
    state,
    valid_inventory,
    valid_supplier,
    valid_eligibility,
    eligibility_arguments,
    qualification_hold,
):
    request = PurchaseRequest.model_validate(state["request"])
    observations = {}
    for _ in range(4):
        inventory = observations.get("get_inventory")
        supplier = observations.get("get_supplier")
        eligibility = observations.get("get_supplier_eligibility")
        if eligibility is not None and not eligibility["allowed"]:
            return qualification_hold(request)
        enough = inventory is not None and inventory["available_quantity"] >= request.quantity
        invalid = supplier is not None and not valid_supplier(supplier, request)
        allowed = (
            ["finish"]
            if enough or invalid
            else [
                name
                for name in ["get_inventory", "get_supplier", "get_supplier_eligibility"]
                if name not in observations
            ]
        )
        if not allowed:
            allowed = ["request_approval"]
        choice = await choose(ctx, model, {**state, "observations": observations}, allowed)
        if choice.action == "finish":
            return result(ctx, request, choice, "NEEDS_INPUT" if enough else "FAILED")
        if choice.action == "request_approval":
            return {"inventory": inventory["available_quantity"], "observations": observations}
        arguments = (
            {"part_id": request.part_id, "plant_id": request.plant_id}
            if choice.action == "get_inventory"
            else {"supplier_id": request.supplier_id}
        )
        if choice.action == "get_supplier_eligibility":
            arguments = eligibility_arguments(request)
        data = await ctx.call(choice.action, arguments)
        if choice.action == "get_supplier_eligibility" and not valid_eligibility(data, request):
            raise ModelError("INVALID_ELIGIBILITY")
        if choice.action == "get_inventory" and not valid_inventory(data, request):
            raise ModelError("INVALID_INVENTORY")
        observations[choice.action] = data
    raise ModelError("LLM_DECISION_LIMIT")
