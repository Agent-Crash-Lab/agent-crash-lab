import asyncio
import json

import pytest
from conftest import ROOT
from sqlalchemy.exc import OperationalError

from harness.events import EventLog, now_iso
from harness.store import Store


def event(event_id):
    return {
        "event_id": event_id,
        "event_type": "TOOL_CALLED",
        "actor_id": "business_server",
        "node_id": "mcp",
        "producer": "mcp-server",
        "occurred_at": now_iso(),
        "parent_event_id": None,
        "tool_call_id": "TC-001",
        "evidence_ids": [],
        "payload": {"tool": "get_inventory"},
    }


@pytest.fixture
def event_log(tmp_path):
    store = Store(f"sqlite:///{tmp_path}/events.sqlite")
    schema = json.loads((ROOT / "qa/contracts/event.schema.json").read_text())
    yield EventLog(store, schema)
    store.close()


@pytest.mark.parametrize("failure_at", [1, 2])
async def test_failed_flush_preserves_unstored_events_and_retries_in_order(
    event_log, monkeypatch, failure_at
):
    for event_id in ("FIRST", "SECOND"):
        await event_log.append("RUN-RETRY", event(event_id))
    original = event_log.store.add_event
    attempts = 0

    def fail_once(run_id, body):
        nonlocal attempts
        attempts += 1
        if attempts == failure_at:
            raise OperationalError("insert", {}, RuntimeError("temporary outage"))
        return original(run_id, body)

    monkeypatch.setattr(event_log.store, "add_event", fail_once)
    with pytest.raises(OperationalError):
        await event_log.flush("RUN-RETRY", force=True)
    assert event_log.pending("RUN-RETRY")
    await event_log.flush("RUN-RETRY", force=True)
    stored = event_log.store.list_events("RUN-RETRY")
    assert [item["event_id"] for item in stored] == ["FIRST", "SECOND"]
    assert [item["sequence"] for item in stored] == [1, 2]
    assert not event_log.pending("RUN-RETRY")


async def test_background_flush_recovers_from_a_temporary_database_outage(event_log, monkeypatch):
    original = event_log.store.add_event
    failed = False

    def fail_once(run_id, body):
        nonlocal failed
        if not failed:
            failed = True
            raise OperationalError("insert", {}, RuntimeError("temporary outage"))
        return original(run_id, body)

    monkeypatch.setattr(event_log.store, "add_event", fail_once)
    event_log.hold = 0.001
    await event_log.append("RUN-BACKGROUND", event("RECOVERED"))
    event_log.start()
    try:
        async with asyncio.timeout(1):
            while not event_log.store.list_events("RUN-BACKGROUND"):
                await asyncio.sleep(0.01)
        assert failed and not event_log.task.done()
        assert not event_log.pending("RUN-BACKGROUND")
    finally:
        await event_log.close()
