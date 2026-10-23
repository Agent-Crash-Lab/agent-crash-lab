"""Persisted sequential QA experiments. Approval stays with the existing human path."""

import asyncio
import hashlib
import time

from harness.evaluation import PRIORITY, run_result, summarize
from harness.events import now_iso
from harness.runner import RunnerError

ACTIVE = {"RUNNING", "WAITING_APPROVAL", "STOPPING"}


class Batches:
    def __init__(self, runner):
        self.runner, self.store = runner, runner.store
        self.policy = runner.catalog.planner.test_policy
        self.tasks = set()

    def recover(self):
        for batch in self.store.all_batches():
            if batch["status"] in ACTIVE:
                batch.update(
                    status="INTERRUPTED", stop_reason="HARNESS_RESTARTED", finished_at=now_iso()
                )
                self.save(batch)

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def save(self, batch):
        batch["report"] = summarize(batch, self.runs(batch))
        self.store.put_batch(batch)
        return batch

    def runs(self, batch):
        return [r for r in self.store.all_runs() if r.get("qa_batch_id") == batch["batch_id"]]

    def get(self, batch_id, owner):
        batch = self.store.get_batch(batch_id, owner)
        if batch is None:
            raise RunnerError(404, "QA_BATCH_NOT_FOUND")
        return batch

    async def create(self, body, owner, source_run_id=None):
        payload = body.model_dump()
        identity = hashlib.sha256((owner + ":" + body.request_id).encode()).hexdigest()[:24]
        batch_id = "QAB-" + identity
        existing = self.store.get_batch(batch_id, owner)
        if existing:
            if existing["request"] != payload or existing.get("source_run_id") != source_run_id:
                raise RunnerError(409, "QA_BATCH_REQUEST_CHANGED")
            return existing
        plan = self.store.get_plan(body.plan_id, owner)
        if plan is None:
            raise RunnerError(404, "QA_PLAN_NOT_FOUND")
        if plan.get("design", {}).get("version") not in {"3.0.0", "4.0.0"}:
            raise RunnerError(409, "QA_STRATEGY_REQUIRED", "새 정책으로 시험을 다시 설계해 주세요.")
        checked_profile = await self.runner.check_plan(plan)
        cases = {c["case_id"]: c for c in plan["cases"]}
        chosen = body.case_ids or [
            c["case_id"]
            for c in plan["cases"]
            if c.get("design_basis") and c["execution"]["status"] == "READY"
        ]
        if not chosen or len(chosen) != len(set(chosen)):
            raise RunnerError(400, "QA_BATCH_CASES_REQUIRED")
        for cid in list(chosen):
            c = cases.get(cid)
            if (
                c is None
                or c["execution"]["status"] != "READY"
                or not c.get("evaluation_strategy")
                or (not c.get("design_basis") and c["risk_id"] != "CONTROL_BASELINE")
            ):
                raise RunnerError(422, "UNSUPPORTED_SIMULATION")
            control = c["evaluation_strategy"].get("control_case_id")
            if control and control not in chosen:
                chosen.append(control)
        limits = self.policy["batch_limits"]
        if (
            body.max_runs > limits["max_runs"]
            or body.max_seconds > limits["max_seconds"]
            or body.max_cost_usd > limits["max_cost_usd"]
        ):
            raise RunnerError(400, "QA_BATCH_LIMIT_EXCEEDED")
        if any(s not in self.runner.catalog.systems for s in body.systems):
            raise RunnerError(400, "VALIDATION_ERROR")
        profile = checked_profile or await self.runner.plan_profile(plan)
        if body.mode == "RELIABILITY" and (
            profile["model_kind"] != "openai"
            or profile.get("runtime_id", "").startswith("external-")
        ):
            raise RunnerError(422, "RELIABILITY_REQUIRES_LLM")
        queue_cases = []
        for cid in sorted(
            chosen,
            key=lambda x: (
                cases[x]["risk_id"] != "CONTROL_BASELINE",
                PRIORITY[cases[x]["evaluation_strategy"]["priority"]],
                x,
            ),
        ):
            c = cases[cid]
            queue_cases.append(
                {
                    "case_id": cid,
                    "hypothesis": c["hypothesis"],
                    "risk_id": c["risk_id"],
                    "business_input": c["business_input"],
                    "priority": c["evaluation_strategy"]["priority"],
                    "required_rules": c["execution"]["rule_ids"],
                    "required_scopes": {
                        rule: self.runner.catalog.rule_scopes(rule)
                        for rule in c["execution"]["rule_ids"]
                    },
                    "repetitions": 1
                    if body.mode == "SMOKE"
                    else c["evaluation_strategy"]["trial_design"]["recommended_repetitions"],
                }
            )
        batch = {
            "batch_id": batch_id,
            "created_by": owner,
            "created_at": now_iso(),
            "created_epoch": time.time(),
            "finished_at": None,
            "plan_id": body.plan_id,
            "source_run_id": source_run_id,
            "request": payload,
            "mode": body.mode,
            "systems": body.systems,
            "cases": queue_cases,
            "planned_runs": sum(c["repetitions"] for c in queue_cases) * len(body.systems),
            "status": "RUNNING",
            "stop_reason": None,
            "stop_requested": False,
            "active_run_id": None,
            "slots": [],
            "cost_accounted_usd": 0,
            "execution_profile": profile,
            "policy": self.policy,
        }
        async with self.runner.lock:
            existing = self.store.get_batch(batch_id, owner)
            if existing:
                if existing["request"] != payload or existing.get("source_run_id") != source_run_id:
                    raise RunnerError(409, "QA_BATCH_REQUEST_CHANGED")
                return existing
            if self.runner.batch_owner or self.runner.busy():
                raise RunnerError(409, "RUN_IN_PROGRESS")
            self.runner.batch_owner = batch_id
            self.save(batch)
        task = asyncio.create_task(self.execute(batch_id, owner))
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)
        return batch

    def stop(self, batch_id, owner):
        batch = self.get(batch_id, owner)
        if batch["status"] in ACTIVE:
            batch.update(stop_requested=True, status="STOPPING", stop_reason="USER_STOP")
            self.save(batch)
        return batch

    async def execute(self, batch_id, owner):
        try:
            initial = self.get(batch_id, owner)
            for case in initial["cases"]:
                for system in initial["systems"]:
                    for repetition in range(case["repetitions"]):
                        b = self.get(batch_id, owner)
                        current_profile = await self.runner.plan_profile(
                            self.store.get_plan(initial["plan_id"], owner)
                        )
                        # Reload because a stop request may arrive during this network call.
                        b = self.get(batch_id, owner)
                        req = b["request"]
                        if current_profile != b["execution_profile"]:
                            self.finish(b, "STOPPED", "EXECUTION_PROFILE_CHANGED")
                            return
                        reserve = b["execution_profile"]["run_cost_upper_bound_usd"]
                        reason = self.stop_reason(b, reserve)
                        if reason:
                            self.finish(b, "STOPPED", reason)
                            return
                        # Persist intent before dispatch; never retry an ambiguous dispatch.
                        b["slots"].append(
                            {
                                "case_id": case["case_id"],
                                "system_id": system,
                                "repetition": repetition + 1,
                                "status": "DISPATCHING",
                                "run_id": None,
                            }
                        )
                        self.save(b)
                        run = await self.runner.create_run(
                            None, system, owner, b["plan_id"], case["case_id"], batch_id=batch_id
                        )
                        b = self.get(batch_id, owner)
                        b["slots"][-1].update(status="RUNNING", run_id=run["run_id"])
                        b["active_run_id"] = run["run_id"]
                        self.save(b)
                        while True:
                            run = self.store.get_run(run["run_id"])
                            b = self.get(batch_id, owner)
                            if (
                                run["status"] in {"COMPLETED", "ERROR"}
                                and run["investigation"]["status"] != "RUNNING"
                            ):
                                break
                            if time.time() - b["created_epoch"] >= req["max_seconds"]:
                                b.update(
                                    stop_requested=True, stop_reason="TIME_LIMIT", status="STOPPING"
                                )
                            elif not b["stop_requested"]:
                                b["status"] = (
                                    "WAITING_APPROVAL"
                                    if run["status"] == "WAITING_APPROVAL"
                                    else "RUNNING"
                                )
                            self.save(b)
                            await asyncio.sleep(self.runner.settings.poll_interval_seconds)
                        outcome = run_result(run, case["required_rules"], case["required_scopes"])
                        b["slots"][-1]["status"] = outcome
                        b["active_run_id"] = None
                        b["cost_accounted_usd"] += self.cost(run, reserve)
                        self.save(b)
                        if (
                            b["mode"] == "RELIABILITY"
                            and run["manifest"].get("model_kind") != "openai"
                        ):
                            self.finish(b, "STOPPED", "EXECUTION_PROFILE_CHANGED")
                            return
                        if any(not g["version_consistent"] for g in b["report"]["groups"]):
                            self.finish(b, "STOPPED", "EXECUTION_VERSION_CHANGED")
                            return
                        if outcome != "PASS":
                            self.finish(
                                b,
                                "STOPPED",
                                {
                                    "FAIL": "RULE_FAILURE",
                                    "ERROR": "RUN_ERROR",
                                    "INCONCLUSIVE": "INSUFFICIENT_OBSERVATION",
                                }[outcome],
                            )
                            return
            b = self.get(batch_id, owner)
            self.finish(b, "STOPPED" if b["stop_requested"] else "COMPLETED", b["stop_reason"])
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            b = self.get(batch_id, owner)
            self.finish(
                b, "ERROR", exc.code if isinstance(exc, RunnerError) else "BATCH_EXECUTION_ERROR"
            )
        finally:
            if self.runner.batch_owner == batch_id:
                self.runner.batch_owner = None

    @staticmethod
    def stop_reason(batch, reserve):
        limits = batch["request"]
        if batch["stop_requested"]:
            return batch["stop_reason"]
        if len(batch["slots"]) >= limits["max_runs"]:
            return "RUN_LIMIT"
        if time.time() - batch["created_epoch"] >= limits["max_seconds"]:
            return "TIME_LIMIT"
        if batch["cost_accounted_usd"] + reserve > limits["max_cost_usd"]:
            return "COST_LIMIT"
        return None

    @staticmethod
    def cost(run, reserve):
        if reserve == 0:
            return 0
        usage = (run.get("agent", {}).get("usage") or {}).get("llm")
        investigation = run.get("investigation", {})
        extra = investigation.get("llm_usage")
        if (
            not usage
            or run["status"] == "ERROR"
            or investigation.get("status") == "ERROR"
            or (investigation.get("status") == "READY" and not extra)
        ):
            return reserve
        return usage["estimated_cost_usd"] + (extra or {}).get("estimated_cost_usd", 0)

    def finish(self, batch, status, reason):
        batch.update(status=status, stop_reason=reason, finished_at=now_iso())
        return self.save(batch)
