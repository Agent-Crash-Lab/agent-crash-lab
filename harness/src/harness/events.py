"""Run-wide event log: one sequence for MCP, Agent and Harness events (HARNESS_SPEC 2.9).

MCP events are pushed at once, Agent events are polled every 0.5s. To number them in the
order they happened, events wait in a per-run buffer for `hold_seconds` and are then stored
sorted by `occurred_at`. The stored sequence never changes once assigned.
"""

import asyncio
import re
import time
from collections import defaultdict
from datetime import UTC, datetime
from uuid import uuid4

from jsonschema import Draft202012Validator

from harness.store import Store

_FRACTION = re.compile(r"(\.\d{6})\d+")


class InvalidEvent(ValueError):
    pass


def now_iso() -> str:
    return datetime.now(UTC).isoformat().replace("+00:00", "Z")


def epoch_iso(value: float | None) -> str | None:
    if value is None:
        return None
    return datetime.fromtimestamp(value, UTC).isoformat().replace("+00:00", "Z")


def occurred_epoch(value: str) -> float | None:
    """RFC 3339 → epoch seconds. MCP sends nanoseconds and `Z`; the Agent `+00:00`."""
    try:
        parsed = datetime.fromisoformat(_FRACTION.sub(r"\1", value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.timestamp()


class EventLog:
    def __init__(self, store: Store, schema: dict, hold_seconds: float = 1.0):
        self.store = store
        self.hold = hold_seconds
        self.validator = Draft202012Validator(schema)
        self.changed: dict[str, asyncio.Condition] = defaultdict(asyncio.Condition)
        # run_id → event_id → (occurred epoch, arrival epoch, arrival order, event)
        self.buffer: dict[str, dict[str, tuple]] = defaultdict(dict)
        self.arrivals = 0
        self.lock = asyncio.Lock()
        self.task: asyncio.Task | None = None

    def start(self):
        self.task = asyncio.create_task(self._flush_loop())

    async def close(self):
        if self.task:
            self.task.cancel()
            await asyncio.gather(self.task, return_exceptions=True)
        for run_id in list(self.buffer):
            await self.flush(run_id, force=True)

    async def append(self, run_id: str, event: dict) -> int | None:
        """Validate and buffer. Returns the sequence if already stored, else None."""
        candidate = {**event, "run_id": run_id, "sequence": 1}
        errors = sorted(self.validator.iter_errors(candidate), key=lambda e: list(e.path))
        if errors:
            raise InvalidEvent(errors[0].message)
        stored = self.store.event_sequence(run_id, event["event_id"])
        if stored is not None:
            return stored
        arrival = time.time()
        occurred = occurred_epoch(event["occurred_at"])
        async with self.lock:
            if event["event_id"] not in self.buffer[run_id]:
                self.arrivals += 1
                self.buffer[run_id][event["event_id"]] = (
                    occurred if occurred is not None else arrival,
                    arrival,
                    self.arrivals,
                    event,
                )
        if self.hold <= 0:
            await self.flush(run_id, force=True)
            return self.store.event_sequence(run_id, event["event_id"])
        return None

    async def settle(self, run_id: str):
        """Wait one hold period so late senders catch up, then store everything buffered.

        mcp-server sends events from a background queue (MCP_SPEC 4.2), so its last events
        can still be in flight when finalize returns.
        """
        await asyncio.sleep(self.hold)
        await self.flush(run_id, force=True)

    def pending(self, run_id: str) -> bool:
        return bool(self.buffer.get(run_id))

    async def flush(self, run_id: str, force: bool = False):
        """Store buffered events in occurrence order.

        Only the oldest-first prefix of events whose wait is over is stored: an earlier event
        that is still waiting blocks later ones, so a straggler can never be numbered after
        an event that happened after it (it waits at most one hold period itself).
        """
        now = time.time()
        async with self.lock:
            waiting = self.buffer.get(run_id, {})
            ready = []
            for item in sorted(waiting.values(), key=lambda item: (item[0], item[2])):
                if not (force or item[0] <= now - self.hold or item[1] <= now - self.hold):
                    break
                ready.append(item)
            for item in ready:
                del waiting[item[3]["event_id"]]
                self.store.add_event(run_id, item[3])
            if not waiting:
                self.buffer.pop(run_id, None)
        if ready:
            await self.notify(run_id)

    async def _flush_loop(self):
        while True:
            await asyncio.sleep(min(0.2, max(self.hold / 4, 0.01)))
            for run_id in list(self.buffer):
                await self.flush(run_id)

    async def notify(self, run_id: str):
        condition = self.changed[run_id]
        async with condition:
            condition.notify_all()

    async def wait(self, run_id: str, timeout: float):
        condition = self.changed[run_id]
        async with condition:
            try:
                await asyncio.wait_for(condition.wait(), timeout)
            except TimeoutError:
                pass

    async def harness_event(
        self,
        run_id: str,
        event_type: str,
        node_id: str,
        payload: dict,
        *,
        actor_id: str = "harness_runner",
        parent_event_id: str | None = None,
        evidence_ids: list[str] | None = None,
    ) -> str:
        event_id = "HEV-" + uuid4().hex[:12].upper()
        await self.append(
            run_id,
            {
                "event_id": event_id,
                "event_type": event_type,
                "actor_id": actor_id,
                "node_id": node_id,
                "producer": "harness",
                "occurred_at": now_iso(),
                "parent_event_id": parent_event_id,
                "tool_call_id": None,
                "evidence_ids": list(dict.fromkeys(evidence_ids or [])),
                "payload": payload,
            },
        )
        return event_id
