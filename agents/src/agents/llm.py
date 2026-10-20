"""Explicit OpenAI calls with a durable, conservative experiment budget."""

import json
import sqlite3
import time
from pathlib import Path
from typing import Literal
from uuid import uuid4

from openai import AsyncOpenAI
from pydantic import BaseModel, ConfigDict, ValidationError

# Standard text pricing per million tokens, checked 2026-10-20 against OpenAI model docs.
PRICES = {
    "gpt-5.4-nano-2026-03-17": (0.20, 1.25),
    "gpt-5.4-mini-2026-03-17": (0.75, 4.50),
}
STAGES = {"smoke": 0.10, "compare": 0.50, "repeat": 0.20}
TOTAL_BUDGET = 0.80  # Leave $0.20 of the authorized $1 untouched for billing variance.
MAX_OUTPUT = 2048


class ModelError(Exception):
    """Only fixed, credential-free codes may leave the model boundary."""


class PurchaseChoice(BaseModel):
    model_config = ConfigDict(extra="forbid")
    action: Literal[
        "get_inventory", "get_supplier", "request_approval", "create_purchase_order", "finish"
    ]
    outcome: Literal["SUCCEEDED", "REJECTED", "FAILED", "NEEDS_INPUT", "UNKNOWN"] | None
    order_id: str | None
    message: str


def resolve_model(name):
    aliases = {model.removesuffix("-2026-03-17"): model for model in PRICES}
    model = aliases.get(name, name)
    if model not in PRICES:
        raise ModelError("UNPRICED_MODEL")
    return model


class Budget:
    def __init__(self, path: Path):
        self.path = path
        path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.execute("""CREATE TABLE IF NOT EXISTS llm_calls (
                id TEXT PRIMARY KEY, stage TEXT NOT NULL, model TEXT NOT NULL,
                reserved REAL NOT NULL, charged REAL, status TEXT NOT NULL)""")

    def connect(self):
        return sqlite3.connect(self.path, timeout=5)

    def reserve(self, stage, model, input_bound):
        incoming, outgoing = PRICES[model]
        amount = (input_bound * incoming + MAX_OUTPUT * outgoing) / 1_000_000
        call_id = uuid4().hex
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            total, phase = db.execute(
                "SELECT COALESCE(SUM(COALESCE(charged,reserved)),0), "
                "COALESCE(SUM(CASE WHEN stage=? THEN COALESCE(charged,reserved) ELSE 0 END),0) "
                "FROM llm_calls",
                (stage,),
            ).fetchone()
            if total + amount > TOTAL_BUDGET or phase + amount > STAGES[stage]:
                raise ModelError("LLM_BUDGET_EXHAUSTED")
            db.execute(
                "INSERT INTO llm_calls VALUES (?,?,?,?,NULL,'RESERVED')",
                (call_id, stage, model, amount),
            )
        return call_id, amount

    def settle(self, call_id, charged):
        with self.connect() as db:
            db.execute(
                "UPDATE llm_calls SET charged=?,status='COUNTED' WHERE id=?", (charged, call_id)
            )

    def summary(self):
        with self.connect() as db:
            rows = db.execute(
                "SELECT stage, COUNT(*), SUM(COALESCE(charged,reserved)), "
                "SUM(CASE WHEN charged IS NULL THEN reserved ELSE 0 END) "
                "FROM llm_calls GROUP BY stage"
            ).fetchall()
        return {
            stage: {"calls": n, "estimated_usd": cost, "unknown_reserved_usd": unknown}
            for stage, n, cost, unknown in rows
        }


class StructuredModel:
    def __init__(self, settings, ctx, model, schema):
        self.settings, self.ctx, self.model, self.schema = settings, ctx, model, schema
        self.budget = Budget(
            settings.llm_budget_path or settings.agent_state_dir / "llm-budget.sqlite"
        )

    async def generate(self, prompt, context):
        # Byte count is a conservative token bound, including schema and message overhead.
        data = json.dumps(context, ensure_ascii=False, sort_keys=True)
        schema = json.dumps(self.schema.model_json_schema(), ensure_ascii=False)
        bound = len((prompt + data + schema).encode("utf-8")) + 1024
        if bound > 64000:
            raise ModelError("LLM_INPUT_LIMIT")
        call_id, reserved = self.budget.reserve(
            self.ctx.store.get(self.ctx.run_id)["budget_stage"], self.model, bound
        )
        started, completed = time.monotonic(), False
        usage = {
            "calls": 1,
            "input_tokens": 0,
            "output_tokens": 0,
            "estimated_cost_usd": reserved,
            "unknown_reserved_usd": reserved,
            "failures": 1,
        }
        try:
            async with AsyncOpenAI(
                api_key=self.settings.llm_api_key.get_secret_value(),
                max_retries=0,
                timeout=30,
                base_url="https://api.openai.com/v1",
            ) as client:
                response = await client.responses.create(
                    model=self.model,
                    instructions=prompt,
                    input=data,
                    store=False,
                    service_tier="default",
                    reasoning={"effort": "none"},
                    temperature=0,
                    max_output_tokens=MAX_OUTPUT,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": self.schema.__name__,
                            "strict": True,
                            "schema": self.schema.model_json_schema(),
                        }
                    },
                )
            if response.usage is not None:
                incoming, outgoing = PRICES[self.model]
                tokens_in, tokens_out = response.usage.input_tokens, response.usage.output_tokens
                if (
                    type(tokens_in) is not int
                    or type(tokens_out) is not int
                    or min(tokens_in, tokens_out) < 0
                ):
                    raise ModelError("LLM_INVALID_USAGE")
                cost = (tokens_in * incoming + tokens_out * outgoing) / 1_000_000
                self.budget.settle(call_id, cost)
                usage.update(
                    input_tokens=tokens_in,
                    output_tokens=tokens_out,
                    estimated_cost_usd=cost,
                    unknown_reserved_usd=0,
                )
                if tokens_in > bound or tokens_out > MAX_OUTPUT:
                    raise ModelError("LLM_USAGE_EXCEEDED_RESERVATION")
            if response.status != "completed":
                raise ModelError("LLM_INCOMPLETE")
            if response.model != self.model:
                raise ModelError("LLM_MODEL_MISMATCH")
            if any(
                part.type == "refusal"
                for item in response.output
                if item.type == "message"
                for part in item.content
            ):
                raise ModelError("LLM_REFUSED")
            result = self.schema.model_validate_json(response.output_text)
            encoded = result.model_dump_json()
            if any(secret and secret in encoded for secret in self.ctx.secrets):
                raise ModelError("LLM_CREDENTIAL_IN_OUTPUT")
            self.ctx.event("AGENT_MODEL_RESPONDED", {"model": self.model, "status": "OK"})
            completed = True
            usage["failures"] = 0
            return result.model_dump()
        except ModelError:
            raise
        except ValidationError:
            raise ModelError("LLM_INVALID_OUTPUT") from None
        except Exception:
            raise ModelError("LLM_CALL_FAILED") from None
        finally:
            usage["latency_seconds"] = time.monotonic() - started
            run = self.ctx.store.get(self.ctx.run_id)
            previous = run.get("llm_usage", {})
            run["llm_usage"] = {key: previous.get(key, 0) + value for key, value in usage.items()}
            self.ctx.store.put(run)
            if not completed:
                self.ctx.event("AGENT_MODEL_RESPONDED", {"model": self.model, "status": "ERROR"})
