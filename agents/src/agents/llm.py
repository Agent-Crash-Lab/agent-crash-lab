"""Explicit OpenAI calls with a durable, conservative experiment budget."""

import json
import sqlite3
import time
from pathlib import Path
from uuid import uuid4

from openai import AsyncOpenAI
from pydantic import ValidationError

# Standard text pricing per million tokens, checked 2026-10-20 against OpenAI model docs.
# GPT-4o mini: official model page checked 2026-10-22.
# https://developers.openai.com/api/docs/models/gpt-4o-mini
PRICES = {
    "gpt-4o-mini-2024-07-18": (0.15, 0.60),
    "gpt-5-nano-2025-08-07": (0.05, 0.40),
    "gpt-5.4-nano-2026-03-17": (0.20, 1.25),
    "gpt-5.4-mini-2026-03-17": (0.75, 4.50),
}
STAGES = {"smoke": 0.10, "compare": 0.50, "repeat": 0.20}
TOTAL_BUDGET = 0.80  # Leave $0.20 of the authorized $1 untouched for billing variance.
MAX_OUTPUT = 2048


class ModelError(Exception):
    """Only fixed, credential-free codes may leave the model boundary."""


def resolve_model(name):
    aliases = {model.rsplit("-", 3)[0]: model for model in PRICES}
    model = aliases.get(name, name)
    if model not in PRICES:
        raise ModelError("UNPRICED_MODEL")
    return model


def inference_options(model):
    if model == "gpt-4o-mini-2024-07-18":
        return {"temperature": 0}
    if model == "gpt-5-nano-2025-08-07":
        return {"reasoning": {"effort": "minimal"}}
    return {"reasoning": {"effort": "none"}, "temperature": 0}


def inference_signature(model):
    effort = (
        "unsupported;temperature=0"
        if model == "gpt-4o-mini-2024-07-18"
        else "minimal;temperature=default"
        if model == "gpt-5-nano-2025-08-07"
        else "none;temperature=0"
    )
    return f"reasoning={effort};max_output_tokens={MAX_OUTPUT}"


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

    def reserve(self, stage, model, input_bound, max_output_tokens=MAX_OUTPUT):
        incoming, outgoing = PRICES[model]
        amount = (input_bound * incoming + max_output_tokens * outgoing) / 1_000_000
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
    def __init__(self, settings, ctx, model, schema, max_output_tokens=MAX_OUTPUT):
        self.settings, self.ctx, self.model, self.schema = settings, ctx, model, schema
        if max_output_tokens not in {1024, 2048, 4096}:
            raise ModelError("INVALID_OUTPUT_BUDGET")
        self.max_output_tokens = max_output_tokens
        self.budget = Budget(
            settings.llm_budget_path or settings.agent_state_dir / "llm-budget.sqlite"
        )

    async def generate(self, prompt, context):
        # Byte count is a conservative token bound, including schema and message overhead.
        data = json.dumps(context, ensure_ascii=False, sort_keys=True)
        response_schema = self.schema.model_json_schema()
        if "allowed_actions" in context and "action" in response_schema.get("properties", {}):
            # Constrain decoding as well as validating the chosen action in application code.
            response_schema["properties"]["action"]["enum"] = context["allowed_actions"]
        # Restrict design decoding to declared tools and retrieved citation IDs.
        # Application and Harness checks still validate each selected risk and policy.
        if "proposals" in response_schema.get("properties", {}):
            if context.get("repair_proposal_ids"):
                count = len(context["repair_proposal_ids"])
                response_schema["properties"]["proposals"].update(minItems=count, maxItems=count)
            tools = context.get("analysis", {}).get("write_tools", [])
            risks = [risk["risk_key"] for risk in context.get("selected_risks", [])]
            citations = [source["document_id"] for source in context.get("sources", [])]
            for definition in response_schema.get("$defs", {}).values():
                fields = definition.get("properties", {})
                if {"tool_name", "risk_key", "evidence_ids"} <= fields.keys():
                    if context.get("generation_contract", {}).get("structured_data_output"):
                        fields["test_data_json"] = context["generation_contract"]["scenario_schema"]
                    if context.get("repair_proposal_ids"):
                        fields["proposal_id"]["enum"] = context["repair_proposal_ids"]
                    if tools:
                        fields["tool_name"]["enum"] = tools
                    if risks:
                        fields["risk_key"]["enum"] = risks
                    if citations:
                        fields["evidence_ids"]["items"]["enum"] = citations
                    if "morphology_id" in fields:
                        fields["morphology_id"]["enum"] = [
                            c["candidate_id"]
                            for c in context.get("morphology", {}).get("candidates", [])
                        ]
                    if "exception_ids" in fields:
                        fields["exception_ids"]["items"]["enum"] = [
                            e["exception_id"]
                            for e in context.get("morphology", {}).get("exception_catalog", [])
                            if e["risk_key"] in risks
                        ]
        if "reviews" in response_schema.get("properties", {}):
            proposal_ids = [proposal["proposal_id"] for proposal in context.get("proposals", [])]
            if proposal_ids:
                response_schema["properties"]["reviews"].update(
                    minItems=len(proposal_ids), maxItems=len(proposal_ids)
                )
            for definition in response_schema.get("$defs", {}).values():
                fields = definition.get("properties", {})
                if proposal_ids and {"proposal_id", "policy_alignment"} <= fields.keys():
                    fields["proposal_id"]["enum"] = proposal_ids
                    if "evidence_ids" in fields and context.get("review_stage"):
                        fields["evidence_ids"]["items"]["enum"] = [
                            source["document_id"]
                            for source in context.get("sources", [])
                            if context["review_stage"] in source.get("evidence_domains", [])
                        ]
        schema = json.dumps(response_schema, ensure_ascii=False)
        bound = len((prompt + data + schema).encode("utf-8")) + 1024
        if bound > 64000:
            raise ModelError("LLM_INPUT_LIMIT")
        call_id, reserved = self.budget.reserve(
            self.ctx.store.get(self.ctx.run_id)["budget_stage"],
            self.model,
            bound,
            self.max_output_tokens,
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
                    **inference_options(self.model),
                    max_output_tokens=self.max_output_tokens,
                    text={
                        "format": {
                            "type": "json_schema",
                            "name": self.schema.__name__,
                            "strict": True,
                            "schema": response_schema,
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
                if tokens_in > bound or tokens_out > self.max_output_tokens:
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
            output = json.loads(response.output_text)
            if context.get("generation_contract", {}).get("structured_data_output"):
                for proposal in output.get("proposals", []):
                    if isinstance(proposal.get("test_data_json"), dict):
                        proposal["test_data_json"] = json.dumps(
                            proposal["test_data_json"], ensure_ascii=False
                        )
            result = self.schema.model_validate(output)
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
