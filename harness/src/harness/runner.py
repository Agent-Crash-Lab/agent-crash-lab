"""Harness Runner: one run from preparation to verdicts (HARNESS_SPEC §2.1-2.2, §3-§5)."""

import asyncio
import logging
import time

from harness import agent_checks, oracle
from harness.catalog import Catalog, TestSpec
from harness.clients import AgentClient, ClientError, McpClient
from harness.config import Settings
from harness.events import EventLog, epoch_iso, now_iso
from harness.store import Store
from harness.validation import collect_evidence_ids, validate_report

log = logging.getLogger(__name__)

ACTIVE = {"PREPARING", "RUNNING", "WAITING_APPROVAL", "EVALUATING"}
LIMIT_REASONS = {
    "TURN_LIMIT",
    "TOOL_CALL_LIMIT",
    "WRITE_CALL_LIMIT",
    "ACTIVE_OR_TOTAL_TIMEOUT",
    "TOTAL_RUN_TIMEOUT",
}


class RunnerError(Exception):
    def __init__(self, status: int, code: str, message: str = ""):
        super().__init__(message or code)
        self.status, self.code, self.message = status, code, message or code


class RunFailed(Exception):
    def __init__(self, reason: str):
        super().__init__(reason)
        self.reason = reason


class Runner:
    def __init__(
        self,
        settings: Settings,
        catalog: Catalog,
        store: Store,
        events: EventLog,
        mcp: McpClient,
        agents: AgentClient,
    ):
        self.settings, self.catalog, self.store, self.events = settings, catalog, store, events
        self.mcp, self.agents = mcp, agents
        self.lock = asyncio.Lock()
        self.tasks: set[asyncio.Task] = set()
        # Agent tokens live only in memory (HARNESS_SPEC 3.1).
        self.tokens: dict[str, dict[str, str]] = {}
        # Agent run → (Harness run that stores its events, last Agent-local sequence).
        self.agent_cursor: dict[str, int] = {}

    # lifecycle

    def recover(self):
        for run in self.store.all_runs():
            if run["status"] in ACTIVE:
                run.update(status="ERROR", status_reason="HARNESS_RESTARTED", finished_at=now_iso())
            if run.get("investigation", {}).get("status") == "RUNNING":
                run["investigation"]["status"] = "ERROR"
            self.store.put_run(run)

    async def close(self):
        for task in self.tasks:
            task.cancel()
        await asyncio.gather(*self.tasks, return_exceptions=True)

    def busy(self) -> bool:
        return any(
            run["status"] in ACTIVE or run.get("investigation", {}).get("status") == "RUNNING"
            for run in self.store.all_runs()
        )

    # public operations

    async def create_run(self, test_id: str, system_id: str | None, user_id: str) -> dict:
        test = self.catalog.tests.get(test_id)
        if test is None:
            raise RunnerError(400, "VALIDATION_ERROR", f"unknown test_id {test_id}")
        if test.test_kind == "SYSTEM":
            if system_id not in self.catalog.systems:
                raise RunnerError(400, "VALIDATION_ERROR", "SYSTEM tests need system_id B0 or B1")
        else:
            system_id = None
        async with self.lock:
            if self.busy():
                raise RunnerError(409, "RUN_IN_PROGRESS")
            run_id = f"RUN-{self.store.count_runs('RUN-') + 1:03d}"
            run = {
                "run_id": run_id,
                "test_id": test.test_id,
                "test_kind": test.test_kind,
                "system_id": system_id,
                "status": "PREPARING",
                "status_reason": None,
                "created_by": user_id,
                "created_at": now_iso(),
                "finished_at": None,
                "manifest": self.catalog.manifest(test, system_id),
                "request": None,
                "approval_request": None,
                "approval": None,
                "fault": None,
                "agent": {"run_id": run_id, "result": None, "termination": None, "usage": None},
                "observation": None,
                "snapshot_complete": None,
                "condition_met": True,
                "checks": [],
                "summary": {"PASS": 0, "FAIL": 0, "INCONCLUSIVE": 0},
                "investigation": {"status": "NOT_REQUESTED", "report": None, "validation": None},
            }
            self.store.put_run(run)
        self._spawn(self._execute(run_id, test))
        return run

    async def resume(self, run_id: str, body: dict):
        """MCP → Harness resume (HARNESS_SPEC 4.1)."""
        async with self.lock:
            run = self._run(run_id)
            approval = run.get("approval")
            if approval and approval["approval_id"] == body["approval_id"]:
                return
            if run["status"] != "WAITING_APPROVAL":
                raise RunnerError(409, "NOT_WAITING_APPROVAL")
            test = self.catalog.tests[run["test_id"]]
            if test.expected_approval and body["decision"] != test.expected_approval:
                run["condition_met"] = False
            token = self.tokens.get(run_id, {}).get("purchase_agent")
            try:
                await self.agents.resume(run_id, {**body, "agent_token": token})
            except ClientError as exc:
                raise RunnerError(502, "AGENT_RESUME_FAILED", exc.code) from exc
            run["approval"] = {**body, "payload": run["request"]}
            await self._set_status(run, "RUNNING")

    def failed_checks(self, run_id: str, verdicts: set[str]) -> list[dict]:
        return [c for c in self._run(run_id).get("checks", []) if c["verdict"] in verdicts]

    # execution

    def _spawn(self, coro):
        task = asyncio.create_task(coro)
        self.tasks.add(task)
        task.add_done_callback(self.tasks.discard)

    def _run(self, run_id: str) -> dict:
        run = self.store.get_run(run_id)
        if run is None:
            raise RunnerError(404, "NOT_FOUND", f"run {run_id}")
        return run

    async def _set_status(self, run: dict, status: str, reason: str | None = None):
        previous = run["status"]
        run["status"] = status
        if reason:
            run["status_reason"] = reason
        if status in {"COMPLETED", "ERROR"}:
            run["finished_at"] = now_iso()
        self.store.put_run(run)
        await self.events.harness_event(
            run["run_id"],
            "RUN_STATUS_CHANGED",
            "harness",
            {"from": previous, "to": status, "reason": reason},
        )

    async def _execute(self, run_id: str, test: TestSpec):
        try:
            if test.test_kind == "SYSTEM":
                await self._system(run_id, test)
            elif test.test_kind == "PURCHASE_AGENT":
                await self._purchase_unit(run_id, test)
            else:
                await self._investigation_unit(run_id, test)
        except RunFailed as exc:
            run = self._run(run_id)
            if exc.reason == "RUN_TIMEOUT":
                run["agent"]["termination"] = "RUNNER_TIMEOUT"
            await self._set_status(run, "ERROR", exc.reason)
        except asyncio.CancelledError:
            raise
        except Exception:
            log.exception("run %s failed", run_id)
            run = self._run(run_id)
            if run["status"] in ACTIVE:
                await self._set_status(run, "ERROR", "AGENT_SERVER_ERROR")
        finally:
            self.tokens.pop(run_id, None)
            await self.events.flush(run_id, force=True)

    async def _system(self, run_id: str, test: TestSpec):
        run = self._run(run_id)
        manifest = run["manifest"]
        try:
            init = await self.mcp.initialize(
                {
                    "run_id": run_id,
                    "scenario_id": test.test_id,
                    "server_policy_version": manifest["server_policy_version"],
                    "fixture_id": manifest["fixture_id"],
                    "requested_by": run["created_by"],
                    "faults": manifest["faults"],
                }
            )
            self.tokens[run_id] = init["agent_tokens"]
            run["request"] = init["request"]
            self.store.put_run(run)
            await self._start_agent(
                run_id,
                {
                    "run_id": run_id,
                    "agent_kind": "PURCHASE_AGENT",
                    "mode": "mcp",
                    "request": init["request"],
                    "agent_token": init["agent_tokens"]["purchase_agent"],
                },
            )
        except ClientError as exc:
            log.warning("init failed for %s: %s", run_id, exc)
            raise RunFailed("INIT_FAILED") from exc
        await self._set_status(self._run(run_id), "RUNNING")

        try:
            agent = await self._follow_agent(run_id, run_id, self._register_approval)
        except (RunFailed, ClientError):
            await self._finalize_quietly(run_id)
            raise
        termination = await self._agent_finished(run_id, agent)

        run = self._run(run_id)
        try:
            observation = await self.mcp.finalize(run_id, self.settings.finalize_wait_ms)
            run["observation"] = observation
            run["snapshot_complete"] = observation.get("snapshot_complete", False)
        except ClientError:
            run["snapshot_complete"] = False
        if termination is None:  # Agent error reason → run error, after finalize
            self.store.put_run(run)
            raise RunFailed(run["status_reason"])
        await self._set_status(run, "EVALUATING")

        run = self._run(run_id)
        if manifest["faults"]:
            try:
                faults = await self.mcp.faults(run_id)
            except ClientError as exc:
                raise RunFailed("AGENT_SERVER_ERROR") from exc
            run["fault"] = faults[0] if faults else None
            if run["fault"] and run["fault"]["status"] == "INJECTION_ERROR":
                self.store.put_run(run)
                raise RunFailed("INJECTION_ERROR")
            self.store.put_run(run)
        try:
            checks = oracle.evaluate(
                oracle.OracleContext(
                    run_id=run_id,
                    test_id=test.test_id,
                    request_id=run["request"]["request_id"],
                    rule_ids=test.rule_ids,
                    rule_version=manifest["rule_version"],
                    rule_scopes={r: self.catalog.rule_scopes(r) for r in test.rule_ids},
                    snapshot_complete=bool(run["snapshot_complete"]),
                    faults=[run["fault"]] if run["fault"] else [],
                    agent_result=run["agent"]["result"],
                    agent_termination=termination,
                    oracle_database_url=self.settings.oracle_database_url,
                )
            )
        except Exception as exc:
            log.exception("oracle failed for %s", run_id)
            raise RunFailed("ORACLE_ERROR") from exc
        await self._save_checks(run_id, checks)
        await self._set_status(self._run(run_id), "COMPLETED")

        run = self._run(run_id)
        if any(c["verdict"] in {"FAIL", "INCONCLUSIVE"} for c in run["checks"]):
            await self._investigate(run_id, "mcp", run_id, None)

    async def _purchase_unit(self, run_id: str, test: TestSpec):
        try:
            await self._start_agent(
                run_id,
                {
                    "run_id": run_id,
                    "agent_kind": "PURCHASE_AGENT",
                    "mode": "mock",
                    "fixture_id": test.agent_fixture_id,
                    "request": self.catalog.seed_request,
                },
            )
        except ClientError as exc:
            raise RunFailed("INIT_FAILED") from exc
        run = self._run(run_id)
        run["request"] = self.catalog.seed_request
        self.store.put_run(run)
        await self._set_status(run, "RUNNING")

        async def fixed_approval(agent):
            body = {
                "approval_id": "AP-FIXTURE",
                "request_id": agent["request"]["request_id"],
                "decision": test.fixture_decision,
                "approver_id": "approver-01",
                "decided_at": now_iso(),
                "payload_hash": agent["payload_hash"],
            }
            await self.agents.resume(run_id, body)
            run = self._run(run_id)
            run["approval"] = {**body, "payload": agent["request"]}
            self.store.put_run(run)

        agent = await self._follow_agent(run_id, run_id, fixed_approval)
        termination = await self._agent_finished(run_id, agent)
        if termination is None:
            raise RunFailed(self._run(run_id)["status_reason"])
        await self._set_status(self._run(run_id), "EVALUATING")
        await self.events.flush(run_id, force=True)
        events = [e for e in self.store.list_events(run_id) if e["producer"] == "agents"]
        checks = agent_checks.evaluate_purchase_agent(test.test_id, agent, events)
        await self._save_checks(run_id, checks)
        await self._set_status(self._run(run_id), "COMPLETED")

    async def _investigation_unit(self, run_id: str, test: TestSpec):
        await self._set_status(self._run(run_id), "RUNNING")
        validation, report_event = await self._investigate(
            run_id, "mock", test.target_run_id, test.agent_fixture_id
        )
        await self._set_status(self._run(run_id), "EVALUATING")
        checks = agent_checks.evaluate_investigation_agent(
            test.test_id, run_id, validation, report_event
        )
        await self._save_checks(run_id, checks)
        await self._set_status(self._run(run_id), "COMPLETED")

    async def _investigate(self, run_id, mode, target_run_id, fixture_id):
        """Run the investigation Agent; its events go to the Harness run `run_id`."""
        run = self._run(run_id)
        run["investigation"]["status"] = "RUNNING"
        self.store.put_run(run)
        agent_run_id = f"INV-{run_id}"
        body = {
            "run_id": agent_run_id,
            "agent_kind": "INVESTIGATION_AGENT",
            "mode": mode,
            "target_run_id": target_run_id,
        }
        if mode == "mcp":
            body["agent_token"] = self.tokens.get(run_id, {}).get("investigation_agent")
        else:
            body["fixture_id"] = fixture_id
        try:
            await self._start_agent(run_id, body)
            agent = await self._follow_agent(run_id, agent_run_id, None)
        except (ClientError, RunFailed):
            agent = None
        run = self._run(run_id)
        run["investigation"]["investigation_id"] = agent_run_id
        if not agent or agent["status"] != "COMPLETED":
            run["investigation"]["status"] = "ERROR"
            self.store.put_run(run)
            return None, None

        report = agent["result"]
        await self.events.flush(run_id, force=True)
        all_events = self.store.list_events(run_id)
        agent_events = [
            e
            for e in all_events
            if e["producer"] == "agents" and e["actor_id"] == "investigation_agent"
        ]
        if mode == "mcp":
            known = collect_evidence_ids(all_events) | collect_evidence_ids(run.get("checks"))
            known |= collect_evidence_ids(run.get("observation") or {})
        else:
            known = collect_evidence_ids(self.catalog.cases[run["test_id"]]["evidence"])
        validation = validate_report(
            report, target_run_id, known, agent_events, self.store.runs_citing
        )
        report_ready = next(
            (e for e in reversed(agent_events) if e["event_type"] == "REPORT_READY"), None
        )
        run["investigation"].update(status="READY", report=report, validation=validation)
        self.store.put_run(run)
        await self.events.harness_event(
            run_id,
            "REPORT_VALIDATED",
            "harness",
            {"investigation_id": agent_run_id, "validation": validation},
            parent_event_id=report_ready["event_id"] if report_ready else None,
        )
        return validation, report_ready["event_id"] if report_ready else None

    # Agent polling

    async def _start_agent(self, run_id: str, body: dict):
        agent = await self.agents.start(body)
        self.agent_cursor[body["run_id"]] = 0
        run = self._run(run_id)
        if body["agent_kind"] == "PURCHASE_AGENT":
            run["manifest"]["model_kind"] = agent.get("model_kind")
        self.store.put_run(run)

    async def _follow_agent(self, run_id: str, agent_run_id: str, on_waiting) -> dict:
        """Poll the Agent until it ends; ingest its events into Harness run `run_id`."""
        deadline = time.monotonic() + self.settings.runner_deadline_seconds
        handled_waiting = False
        while True:
            agent = await self.agents.status(agent_run_id)
            await self._ingest(run_id, agent_run_id)
            if agent["status"] in {"COMPLETED", "ERROR"}:
                await self._ingest(run_id, agent_run_id)
                return agent
            if agent["status"] == "WAITING_APPROVAL" and not handled_waiting and on_waiting:
                handled_waiting = True
                await on_waiting(agent)
            if time.monotonic() > deadline:
                raise RunFailed("RUN_TIMEOUT")
            await asyncio.sleep(self.settings.poll_interval_seconds)

    async def _ingest(self, run_id: str, agent_run_id: str):
        while True:
            after = self.agent_cursor.get(agent_run_id, 0)
            batch = await self.agents.events(agent_run_id, after)
            for event in batch:
                self.agent_cursor[agent_run_id] = max(after, event["sequence"])
                after = self.agent_cursor[agent_run_id]
                # The stream run_id and sequence are the Harness run's (HARNESS_SPEC 2.9).
                stored = {k: v for k, v in event.items() if k not in {"run_id", "sequence"}}
                await self.events.append(run_id, stored)
            if len(batch) < 100:
                return

    async def _register_approval(self, agent: dict):
        run_id = agent["run_id"]
        try:
            approval_request = await self.mcp.request_approval(run_id, agent["request"])
        except ClientError as exc:
            await self._finalize_quietly(run_id)
            raise RunFailed("AGENT_SERVER_ERROR") from exc
        if approval_request["payload_hash"] != agent["payload_hash"]:
            await self._finalize_quietly(run_id)
            raise RunFailed("AGENT_SERVER_ERROR")
        run = self._run(run_id)
        run["approval_request"] = approval_request
        await self._set_status(run, "WAITING_APPROVAL")

    async def _finalize_quietly(self, run_id: str):
        try:
            await self.mcp.finalize(run_id, self.settings.finalize_wait_ms)
        except ClientError:
            pass

    async def _agent_finished(self, run_id: str, agent: dict) -> str | None:
        """Record the Agent outcome. Returns termination, or None when the run must ERROR."""
        run = self._run(run_id)
        run["agent"].update(
            result=agent.get("result"),
            usage={
                "turns": agent.get("turns"),
                "tool_calls": agent.get("tool_calls"),
                "active_seconds": agent.get("active_seconds"),
            },
            started_at=epoch_iso(agent.get("created_at")),
            finished_at=epoch_iso(agent.get("finished_at")),
        )
        termination = None
        if agent["status"] == "COMPLETED":
            termination = "AGENT_FINISHED"
        elif agent.get("reason") in LIMIT_REASONS:
            termination = "LIMIT_ENFORCED"
        elif agent.get("reason") == "APPROVAL_WAIT_EXPIRED":
            run["status_reason"] = "APPROVAL_WAIT_EXPIRED"
        else:
            run["status_reason"] = "AGENT_SERVER_ERROR"
        run["agent"]["termination"] = termination
        self.store.put_run(run)
        return termination

    async def _save_checks(self, run_id: str, checks: list[dict]):
        run = self._run(run_id)
        if not run["condition_met"]:
            # A test whose condition was not met must not PASS (config manual_decision_mismatch).
            checks = [
                {**c, "verdict": "INCONCLUSIVE", "reason": c["reason"] + " (시험 조건 미성립)"}
                if c["verdict"] == "PASS"
                else c
                for c in checks
            ]
        run["checks"] = checks
        run["summary"] = {
            verdict: sum(c["verdict"] == verdict for c in checks)
            for verdict in ("PASS", "FAIL", "INCONCLUSIVE")
        }
        self.store.put_run(run)
        for check in checks:
            await self.events.harness_event(
                run_id,
                "VERDICT_CREATED",
                "oracle",
                check,
                actor_id="oracle",
                evidence_ids=check["evidence_ids"],
            )
