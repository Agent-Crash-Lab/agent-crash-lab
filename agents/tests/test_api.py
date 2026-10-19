import json
import time

from conftest import TOKEN, approval, purchase
from fastapi.testclient import TestClient

from agents.models import StartRequest
from agents.server import create_app

PREFIX = "/internal/agent-runs"
HEADERS = {"X-Internal-Token": TOKEN}


def poll(client, run_id):
    for _ in range(200):
        response = client.get(f"{PREFIX}/{run_id}", headers=HEADERS)
        assert response.status_code == 200
        if response.json()["status"] not in {"PREPARING", "RUNNING"}:
            return response.json()
        time.sleep(0.01)
    raise AssertionError("API run timed out")


def test_api_start_resume_events_and_auth(settings):
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").json() == {"status": "ok"}
        assert client.get(f"{PREFIX}/missing").status_code == 401
        assert client.get(f"{PREFIX}/missing", headers=HEADERS).status_code == 404
        body = purchase()
        response = client.post(PREFIX, headers=HEADERS, json=body.model_dump(mode="json"))
        assert response.status_code == 202
        assert (
            client.post(PREFIX, headers=HEADERS, json=body.model_dump(mode="json")).status_code
            == 409
        )
        waiting = poll(client, body.run_id)
        assert waiting["status"] == "WAITING_APPROVAL"
        decision = approval(body).model_dump(mode="json")
        bad = {**decision, "payload_hash": "0" * 64}
        assert (
            client.post(f"{PREFIX}/{body.run_id}/resume", headers=HEADERS, json=bad).status_code
            == 422
        )
        assert (
            client.post(
                f"{PREFIX}/{body.run_id}/resume", headers=HEADERS, json=decision
            ).status_code
            == 202
        )
        assert poll(client, body.run_id)["result"]["outcome"] == "SUCCEEDED"
        assert (
            client.post(
                f"{PREFIX}/{body.run_id}/resume", headers=HEADERS, json=decision
            ).status_code
            == 202
        )
        events = client.get(f"{PREFIX}/{body.run_id}/events", headers=HEADERS).json()["events"]
        assert [e["sequence"] for e in events] == list(range(1, len(events) + 1))
        from conftest import ROOT
        from jsonschema import validate

        schema = json.loads(
            (ROOT / "contracts/drafts/manufacturing-qa/event.schema.json").read_text()
        )
        for event in events:
            validate(event, schema)
        assert (
            client.get(f"{PREFIX}/{body.run_id}/events", headers=HEADERS).json()["sequence_scope"]
            == "AGENT_LOCAL"
        )
        assert not {"BUSINESS_COMMITTED", "FAULT_INJECTED", "VERDICT_CREATED"} & {
            e["event_type"] for e in events
        }
        tail = client.get(f"{PREFIX}/{body.run_id}/events?after_sequence=2", headers=HEADERS).json()
        assert tail["events"] == events[2:]


def test_validation_errors_do_not_echo_secret_input(settings):
    with TestClient(create_app(settings)) as client:
        response = client.post(
            PREFIX,
            headers=HEADERS,
            json={
                "run_id": "BAD",
                "agent_kind": "invalid",
                "agent_token": "must-not-leak",
            },
        )
        assert response.status_code == 422 and "must-not-leak" not in response.text
        body = purchase(part_id=TOKEN)
        response = client.post(PREFIX, headers=HEADERS, json=body.model_dump(mode="json"))
        assert response.status_code == 422 and TOKEN not in response.text


def test_unconfigured_internal_token_disables_business_api(settings):
    from agents.config import Settings

    settings = Settings(**{**settings.model_dump(), "internal_api_token": ""})
    with TestClient(create_app(settings)) as client:
        assert client.get("/health").status_code == 200
        assert client.get(f"{PREFIX}/missing").status_code == 503


def test_api_checkpoint_survives_lifespan_restart(settings):
    body = purchase()
    with TestClient(create_app(settings)) as client:
        client.post(PREFIX, headers=HEADERS, json=body.model_dump(mode="json"))
        waiting = poll(client, body.run_id)
    with TestClient(create_app(settings)) as client:
        restored = client.get(f"{PREFIX}/{body.run_id}", headers=HEADERS).json()
        assert restored["approval_expires_at"] == waiting["approval_expires_at"]
        assert (
            client.post(
                f"{PREFIX}/{body.run_id}/resume",
                headers=HEADERS,
                json=approval(body).model_dump(mode="json"),
            ).status_code
            == 202
        )
        assert poll(client, body.run_id)["result"]["outcome"] == "SUCCEEDED"


def test_investigation_api(settings):
    with TestClient(create_app(settings)) as client:
        body = StartRequest(
            run_id="INV-1",
            agent_kind="INVESTIGATION_AGENT",
            target_run_id="TARGET-1",
            fixture_id="ia01-v1",
        )
        assert (
            client.post(PREFIX, headers=HEADERS, json=body.model_dump(mode="json")).status_code
            == 202
        )
        report = poll(client, body.run_id)
        assert report["status"] == "COMPLETED"
        assert report["result"]["target_run_id"] == "TARGET-1"
        assert report["result"]["facts"]
        assert TOKEN not in json.dumps(report)
