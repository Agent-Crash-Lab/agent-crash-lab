"""Model-selected purchase steps; approval, arguments and retry policy stay in code."""

from pathlib import Path

from agents.llm import ModelError, PurchaseChoice
from agents.models import PurchaseRequest

PROMPT = (Path(__file__).parents[1] / "prompts/purchase.txt").read_text()


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
        "result": {
            "request_id": request.request_id,
            "outcome": expected,
            "order_id": order_id,
            "message": choice.message,
        }
    }


async def prepare(ctx, model, state, valid_inventory, valid_supplier):
    request = PurchaseRequest.model_validate(state["request"])
    observations = {}
    for _ in range(3):
        inventory = observations.get("get_inventory")
        supplier = observations.get("get_supplier")
        enough = inventory is not None and inventory["available_quantity"] >= request.quantity
        invalid = supplier is not None and not valid_supplier(supplier, request)
        allowed = (
            ["finish"]
            if enough or invalid
            else [name for name in ["get_inventory", "get_supplier"] if name not in observations]
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
        data = await ctx.call(choice.action, arguments)
        if choice.action == "get_inventory" and not valid_inventory(data, request):
            raise ModelError("INVALID_INVENTORY")
        observations[choice.action] = data
    raise ModelError("LLM_DECISION_LIMIT")
