"""Small opt-in model comparison using the real Graph and existing Harness checkers."""

import argparse
import asyncio
import hashlib
import importlib.util
import json
import time
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

from agents.config import Settings, redact
from agents.llm import PRICES, Budget, inference_signature, resolve_model
from agents.models import PurchaseRequest, ResumeRequest, StartRequest
from agents.runtime import Runtime
from agents.tools.mock import MockTools

CASES = ["PA01", "PA02", "PA03", "IA01", "IA02", "IA03"]


def checker(root, name):
    # Reuse the monorepo's independent evaluator without adding Harness to production dependencies.
    path = root / "harness/src/harness" / (name + ".py")
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


async def settled(runtime, run_id):
    while runtime.status(run_id)["status"] in {"PREPARING", "RUNNING"} or runtime.tasks:
        await asyncio.sleep(0.01)
    return runtime.status(run_id)


async def run_case(settings, case):
    runtime = await Runtime(settings).open()
    root = settings.agent_project_root
    checks = checker(root, "agent_checks")
    validation = checker(root, "validation")
    run_id = f"MODEL-{case}-{uuid4().hex}"
    started = time.monotonic()
    try:
        if case.startswith("PA"):
            profile = json.loads((root / "qa/examples/targets/agents.json").read_text())[
                "agents"
            ]["PURCHASE"]
            body = StartRequest(
                run_id=run_id,
                request=PurchaseRequest.model_validate(profile["sample_data"]["business_input"]),
                fixture_id="purchase-timeout-once" if case == "PA03" else "purchase-normal",
            )
        else:
            body = StartRequest(
                run_id=run_id,
                agent_kind="INVESTIGATION_AGENT",
                target_run_id=f"TARGET-{run_id}",
                fixture_id=case.lower() + "-v1",
            )
        await runtime.start(body)
        run = await settled(runtime, run_id)
        if run["status"] == "WAITING_APPROVAL":
            await runtime.resume(
                run_id,
                ResumeRequest(
                    request_id=body.request.request_id,
                    approval_id=f"AP-{run_id}",
                    decision="REJECTED" if case == "PA02" else "APPROVED",
                    approver_id="fixture-approver",
                    decided_at=datetime.now(UTC),
                    payload_hash=run["payload_hash"],
                ),
            )
            run = await settled(runtime, run_id)
        events = runtime.store.events(run_id)
        if case.startswith("PA"):
            verdicts = checks.evaluate_purchase_agent(case, run, events)
        else:
            evidence = MockTools(root, body.fixture_id, body.target_run_id).investigation_evidence()
            review = validation.validate_report(
                run.get("result"),
                body.target_run_id,
                validation.collect_evidence_ids(evidence),
                events,
                lambda _: set(),
            )
            report_event = next(
                (e["event_id"] for e in events if e["event_type"] == "REPORT_READY"), None
            )
            verdicts = checks.evaluate_investigation_agent(case, run_id, review, report_event)
        reason = run.get("reason", "")
        unsafe = any(e["event_type"] == "AGENT_MODEL_BLOCKED" for e in events) or reason in {
            "LLM_UNSUPPORTED_RESULT",
            "LLM_CREDENTIAL_IN_OUTPUT",
        }
        return redact(
            {
                "case": case,
                "fixture_id": body.fixture_id,
                "evaluation_version": checks.RULE_VERSION,
                "run_id": run_id,
                "model": run.get("model"),
                "prompt_version": run.get("prompt_version"),
                "agent_version": run.get("agent_version"),
                "status": run["status"],
                "reason": reason,
                "result": run.get("result"),
                "checks": verdicts,
                "passed": run["status"] == "COMPLETED"
                and bool(verdicts)
                and all(c["verdict"] == "PASS" for c in verdicts),
                "unsafe": unsafe,
                "llm_usage": run.get("llm_usage", {}),
                "latency_seconds": time.monotonic() - started,
            },
            runtime.secrets(),
        ) | {"llm_usage": run.get("llm_usage", {})}
    finally:
        await runtime.close()


def summarize(rows, reviews):
    if rows:
        latest = rows[-1].get("trial_version")
        rows = [row for row in rows if row.get("trial_version") == latest]
    rows = [row for row in rows if row.get("stage") != "smoke" and row.get("model") is not None]
    result = []
    for model in sorted({r["model"] for r in rows}):
        runs = [r for r in rows if r["model"] == model]
        for role in ["PA", "IA"]:
            selected = [r for r in runs if r["case"].startswith(role)]
            passed = sum(r["passed"] for r in selected)
            cost = sum(r["llm_usage"].get("estimated_cost_usd", 0) for r in selected)
            scores = [reviews.get(r["run_id"]) for r in selected] if role == "IA" else []
            human_pass = role == "PA" or (
                bool(scores)
                and all(
                    isinstance(score, list)
                    and len(score) == 3
                    and all(type(x) is int and 0 <= x <= 2 for x in score)
                    for score in scores
                )
                and sum(sum(score) for score in scores) / len(scores) >= 4
            )
            complete = {r["case"] for r in selected} == {c for c in CASES if c.startswith(role)}
            eligible = bool(selected) and complete and passed / len(selected) >= 0.9 and human_pass
            versions_match = all(
                len({r.get("prompt_version") for r in selected if r["case"] == case}) <= 1
                for case in CASES
            )
            eligible = (
                eligible
                and model is not None
                and versions_match
                and not any(r["unsafe"] for r in selected)
            )
            result.append(
                {
                    "model": model,
                    "role": role,
                    "runs": len(selected),
                    "passed": passed,
                    "eligible": bool(eligible),
                    "human_review_pending": role == "IA" and not human_pass,
                    "estimated_usd": cost,
                    "cost_per_valid_result": cost / passed if passed else None,
                    "mean_seconds": sum(r["latency_seconds"] for r in selected) / len(selected)
                    if selected
                    else None,
                }
            )
    winners = {}
    for role in ["PA", "IA"]:
        candidates = [r for r in result if r["role"] == role and r["eligible"]]
        if candidates:
            cheapest = min(r["cost_per_valid_result"] for r in candidates)
            close = [r for r in candidates if r["cost_per_valid_result"] <= cheapest * 1.1]
            best = min(close, key=lambda r: (-r["passed"] / r["runs"], r["mean_seconds"]))
            winners[role] = {"model": best["model"], "provisional": True}
    return {"models": result, "selection": winners}


async def execute(args):
    root = Settings().agent_project_root
    settings = Settings(_env_file=(root / ".env", root / "agents/.env"))
    output = args.output or settings.agent_project_root / "artifacts/local-runs/model-experiment"
    output.mkdir(parents=True, exist_ok=True)
    settings.agent_state_dir = output / "state"  # One ledger across stages, models and restarts.
    settings.llm_budget_path = settings.agent_state_dir / "llm-budget.sqlite"
    settings.agent_model_mode = "openai" if args.live else "offline"
    settings.llm_budget_stage = args.stage
    reviews_path = output / "reviews.json"
    reviews = json.loads(reviews_path.read_text()) if reviews_path.exists() else {}
    results_path = output / "results.jsonl"
    previous = (
        [json.loads(line) for line in results_path.read_text().splitlines()]
        if results_path.exists()
        else []
    )
    from agents.qa.investigation import PROMPT as investigation_prompt
    from agents.targets.reference_purchase_model import PROMPT as purchase_prompt

    inference = "reasoning=none;temperature=0;max_output_tokens=2048"
    if any(resolve_model(m) == "gpt-5-nano-2025-08-07" for m in args.models):
        inference = json.dumps(
            {resolve_model(m): inference_signature(resolve_model(m)) for m in args.models},
            sort_keys=True,
        )
    trial_version = hashlib.sha256(
        (purchase_prompt + investigation_prompt + inference).encode()
    ).hexdigest()
    current = [row for row in previous if row.get("trial_version") == trial_version]
    if args.summary_only:
        summary = summarize(current, reviews)
        summary["budget"] = Budget(settings.llm_budget_path).summary()
        (output / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2))
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        return
    if args.stage == "repeat":
        eligible = {r["model"] for r in summarize(current, reviews)["models"] if r["eligible"]}
        models = [m for m in args.models if resolve_model(m) in eligible]
        if not models:
            raise SystemExit(
                "No eligible candidate. Complete first-pass tests and human reviews first."
            )
    else:
        models = args.models
    cases = ["PA01", "IA01"] if args.stage == "smoke" else CASES
    for model in models:
        settings.llm_model = resolve_model(model)
        settings.purchase_llm_model = settings.investigation_llm_model = ""
        for case in cases:
            if args.stage == "repeat" and not any(
                row["model"] == settings.llm_model and row["role"] == case[:2] and row["eligible"]
                for row in summarize(
                    [r for r in previous if r.get("trial_version") == trial_version], reviews
                )["models"]
            ):
                continue
            # Smoke is connectivity-only; comparison has at most three samples per case/model.
            count = sum(
                r["model"] == settings.llm_model
                and r["case"] == case
                and r.get("stage") != "smoke"
                and r.get("trial_version") == trial_version
                for r in previous
            )
            if args.stage == "compare" and count >= 1:
                continue
            repeats = max(0, 3 - count) if args.stage == "repeat" else 1
            for _ in range(repeats):
                row = await run_case(settings, case)
                row["stage"] = args.stage
                row["trial_version"] = trial_version
                with results_path.open("a") as stream:
                    stream.write(json.dumps(row, ensure_ascii=False) + "\n")
                previous.append(row)
                if case.startswith("IA"):
                    reviews.setdefault(row["run_id"], None)
                    reviews_path.write_text(json.dumps(reviews, indent=2))
                print(
                    f"{row['model'] or 'offline'} {case}: {row['status']} "
                    f"passed={row['passed']} reason={row['reason']}",
                    flush=True,
                )
                if row["reason"] == "LLM_BUDGET_EXHAUSTED":
                    print("Budget exhausted; stopped without further calls.")
                    return
    comparison = summarize(
        [r for r in previous if r.get("trial_version") == trial_version], reviews
    )
    comparison["budget"] = Budget(settings.agent_state_dir / "llm-budget.sqlite").summary()
    (output / "summary.json").write_text(json.dumps(comparison, ensure_ascii=False, indent=2))
    print(json.dumps(comparison, ensure_ascii=False, indent=2))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--live", action="store_true", help="Explicitly enable paid OpenAI calls")
    parser.add_argument("--stage", choices=["smoke", "compare", "repeat"], default="smoke")
    parser.add_argument(
        "--models", nargs="+", default=[m for m in PRICES if m.startswith("gpt-5.4-")]
    )
    parser.add_argument("--output", type=Path)
    parser.add_argument("--summary-only", action="store_true")
    asyncio.run(execute(parser.parse_args()))


if __name__ == "__main__":
    main()
