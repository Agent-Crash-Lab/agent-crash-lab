import time

from conftest import GATEWAY, ROOT, TOKEN, done, wait_for
from fastapi.testclient import TestClient

from harness.api import create_app
from harness.config import Settings
from harness.events import occurred_epoch

INTERNAL = {"X-Internal-Token": TOKEN}


def mcp_event(event_id, event_type="TOOL_CALLED"):
    return {
        "event_id": event_id,
        "event_type": event_type,
        "actor_id": "business_server",
        "node_id": "mcp",
        "producer": "mcp-server",
        "occurred_at": "2026-10-20T01:23:45Z",
        "parent_event_id": None,
        "tool_call_id": "TC-001",
        "evidence_ids": [],
        "payload": {"tool": "get_inventory"},
    }


def test_health(client):
    assert client.get("/health").json() == {"status": "UP"}


def test_internal_api_requires_token(client):
    assert client.get("/internal/runs/RUN-001/checks").status_code == 401
    wrong = client.get("/internal/runs/RUN-001/checks", headers={"X-Internal-Token": "x"})
    assert wrong.status_code == 401
    assert wrong.json()["error"]["code"] == "UNAUTHORIZED"


def test_unconfigured_token_is_503(tmp_path, fakes):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path}/h.sqlite",
        harness_project_root=ROOT,
    )
    with TestClient(create_app(settings, mcp=fakes[0], agents=fakes[1])) as c:
        assert c.get("/api/scenarios").status_code == 503


def test_gateway_headers_and_roles(tmp_path, fakes):
    settings = Settings(
        _env_file=None,
        database_url=f"sqlite:///{tmp_path}/h.sqlite",
        internal_api_token=TOKEN,
        harness_project_root=ROOT,
    )
    with TestClient(create_app(settings, mcp=fakes[0], agents=fakes[1])) as c:
        assert c.get("/api/scenarios").status_code == 401
        assert c.get("/api/scenarios", headers=GATEWAY).status_code == 200
        approver = {**GATEWAY, "X-User-Id": "approver-01", "X-User-Roles": "APPROVER"}
        denied = c.post("/api/runs", json={"test_id": "PA01"}, headers=approver)
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "PERMISSION_DENIED"


def test_create_run_validation(client):
    assert client.post("/api/runs", json={"test_id": "S09"}).status_code == 400
    missing = client.post("/api/runs", json={"test_id": "S01"})
    assert missing.status_code == 400 and missing.json()["error"]["code"] == "VALIDATION_ERROR"
    assert client.get("/api/runs/RUN-404").status_code == 404


def test_mcp_events_share_sequence_and_are_idempotent(client):
    run_id = client.post("/api/runs", json={"test_id": "S01", "system_id": "B0"}).json()["run_id"]
    wait_for(client, run_id, lambda r: r["status"] == "WAITING_APPROVAL")
    url = f"/internal/runs/{run_id}/events"
    first = client.post(url, json=mcp_event("EVT-900"), headers=INTERNAL)
    assert first.status_code == 202
    assert first.json()["event_id"] == "EVT-900"
    assert client.post(url, json=mcp_event("EVT-900"), headers=INTERNAL).status_code == 202
    time.sleep(0.3)
    stored = client.post(url, json=mcp_event("EVT-900"), headers=INTERNAL).json()["sequence"]

    events = client.get(f"/api/runs/{run_id}/events").json()["events"]
    assert [e["sequence"] for e in events if e["event_id"] == "EVT-900"] == [stored]
    sequences = [e["sequence"] for e in events]
    assert sequences == list(range(1, len(events) + 1))
    producers = {e["producer"] for e in events}
    assert producers == {"harness", "agents", "mcp-server"}
    assert all(e["run_id"] == run_id for e in events)

    bad = mcp_event("EVT-901")
    bad["node_id"] = "L3.business_db"
    rejected = client.post(url, json=bad, headers=INTERNAL)
    assert rejected.status_code == 400
    assert (
        client.post(
            "/internal/runs/RUN-404/events", json=mcp_event("E"), headers=INTERNAL
        ).status_code
        == 404
    )


def test_event_replay_and_sse(client):
    run_id = client.post("/api/runs", json={"test_id": "PA02"}).json()["run_id"]
    wait_for(client, run_id, done)
    page = client.get(f"/api/runs/{run_id}/events?after_sequence=0&limit=3").json()
    assert len(page["events"]) == 3 and page["has_more"] is True
    assert isinstance(page["is_final"], bool)

    with client.stream(
        "GET",
        f"/api/runs/{run_id}/events",
        headers={"Accept": "text/event-stream", "Last-Event-ID": "2"},
    ) as response:
        text = "".join(response.iter_text())
    assert text.startswith("id: 3\nevent: run_event\n")
    assert text.rstrip().endswith('"status": "COMPLETED"}')
    assert "event: run_end" in text


def test_run_list(client):
    run_id = client.post("/api/runs", json={"test_id": "PA01"}).json()["run_id"]
    wait_for(client, run_id, done)
    runs = client.get("/api/runs").json()["runs"]
    assert runs[0]["run_id"] == run_id
    assert runs[0]["summary"]["PASS"] == 4  # PA01-R1~R3 + R10


def mcp_event_at(event_id, occurred_at):
    return {**mcp_event(event_id), "occurred_at": occurred_at}


def test_events_are_numbered_by_occurrence_not_arrival(client):
    run_id = client.post("/api/runs", json={"test_id": "S01", "system_id": "B0"}).json()["run_id"]
    wait_for(client, run_id, lambda r: r["status"] == "WAITING_APPROVAL")
    client.app.state.events.hold = 1.0  # the production hold, so all three wait together
    url = f"/internal/runs/{run_id}/events"
    # Arrive late-first, as when a polled Agent event lands after a pushed MCP event.
    client.post(url, json=mcp_event_at("LATE", "2030-01-01T00:00:00.000002900Z"), headers=INTERNAL)
    client.post(
        url, json=mcp_event_at("EARLY", "2030-01-01T00:00:00.000001+00:00"), headers=INTERNAL
    )
    client.post(url, json=mcp_event_at("FIRST", "2029-12-31T23:59:59.5Z"), headers=INTERNAL)
    time.sleep(1.5)
    events = client.get(f"/internal/runs/{run_id}/events", headers=INTERNAL).json()["events"]
    order = [e["event_id"] for e in events if e["event_id"] in {"LATE", "EARLY", "FIRST"}]
    assert order == ["FIRST", "EARLY", "LATE"]


def test_occurred_epoch_formats():
    nanos = occurred_epoch("2026-10-20T01:08:28.606747925Z")
    micros = occurred_epoch("2026-10-20T01:08:28.614915+00:00")
    assert nanos is not None and micros is not None and nanos < micros
    assert occurred_epoch("2026-10-20T01:08:28") is None
    assert occurred_epoch("not a time") is None


def test_public_order_count_does_not_expose_observation():
    from harness.api import public_view

    assert public_view({"observation": None})["observed_order_count"] is None
    result = public_view({"observation": {"orders": [{"order_id": "PO-1"}, {"order_id": "PO-2"}]}})
    assert result["observed_order_count"] == 2
    assert "observation" not in result
