import copy

from conftest import GATEWAY, ROOT, wait_for
from test_design_plans import design

from harness.planning import QaPlanner
from harness.scenarios import case_fingerprint, register
from harness.store import Store

OTHER = {**GATEWAY, "X-User-Id": "other-requester"}


def designed_case(planner):
    plan = planner.build_designed(
        planner.reference_target, planner.reference_sample, design(planner)
    )
    return plan, plan["cases"][-1]


def test_fingerprint_ignores_prose_and_ids_but_not_conditions():
    planner = QaPlanner(ROOT)
    _, case = designed_case(planner)
    reworded = copy.deepcopy(case)
    reworded.update(case_id="OTHER-ID", hypothesis="다르게 쓴 가정")
    reworded["design_basis"]["failure_mode"] = "다르게 쓴 실패 설명"
    reworded["execution"]["rule_ids"] = list(reversed(case["execution"]["rule_ids"]))
    reworded["execution"]["reason"] = "다른 설명"
    assert case_fingerprint(reworded) == case_fingerprint(case)

    for change in (
        lambda c: c["simulation"].update(approval_decision="REJECTED"),
        lambda c: c["simulation"].update(fault=None),
        lambda c: c["business_input"].update(quantity=c["business_input"]["quantity"] + 1),
        lambda c: c.update(risk_id="OTHER_RISK"),
    ):
        changed = copy.deepcopy(case)
        change(changed)
        assert case_fingerprint(changed) != case_fingerprint(case)


def test_library_keeps_first_entry_per_target_and_condition(tmp_path):
    store = Store(f"sqlite:///{tmp_path}/library.sqlite")
    planner = QaPlanner(ROOT)
    plan, case = designed_case(planner)
    first = register(store, plan, case, "requester-01", "2026-10-22T00:00:00Z")
    again = register(
        store, {**plan, "plan_id": "QAP-LATER"}, case, "other-requester", "2026-10-23T00:00:00Z"
    )
    assert again == first
    assert again["first_plan_id"] == plan["plan_id"]
    assert again["created_by"] == "requester-01"

    other_target = {**plan, "target_hash": "f" * 64}
    separate = register(store, other_target, case, "requester-01", "2026-10-23T00:00:00Z")
    assert separate["scenario_id"] != first["scenario_id"]
    assert len(store.list_scenarios(plan["target_hash"])) == 1

    unsupported = copy.deepcopy(case)
    unsupported["execution"]["status"] = "UNSUPPORTED"
    assert register(store, plan, unsupported, "requester-01", "2026-10-23T00:00:00Z") is None
    store.close()


def reworded_design(planner, title):
    result = design(planner)
    result["design_id"] = "DESIGN-" + title
    result["proposals"][0].update(title=title, failure_mode=title + " 실패", rationale=title)
    return result


def test_regenerated_case_is_existing_and_hides_other_users_content(client, fakes):
    planner = QaPlanner(ROOT)
    titles = iter(["첫 생성", "다시 생성", "다른 사용자"])

    async def generate(body):
        return reworded_design(planner, next(titles))

    fakes[1].design = generate
    first = client.post("/api/qa/design", json={}).json()
    second = client.post("/api/qa/design", json={}).json()
    assert first["plan_id"] != second["plan_id"]
    assert "scenarios" not in second

    first_rows = client.get(f"/api/qa/plans/{first['plan_id']}/scenarios").json()["scenarios"]
    second_rows = client.get(f"/api/qa/plans/{second['plan_id']}/scenarios").json()["scenarios"]
    assert {row["status"] for row in first_rows} == {"NEW"}
    case_id = first["cases"][-1]["case_id"]
    original = next(row for row in first_rows if row["case_id"] == case_id)
    repeat = next(row for row in second_rows if row["case_id"] == case_id)
    assert repeat["status"] == "EXISTING" and repeat["owned"]
    assert repeat["scenario_id"] == original["scenario_id"]
    assert repeat["first_plan_id"] == first["plan_id"]

    third = client.post("/api/qa/design", json={}, headers=OTHER).json()
    rows = client.get(f"/api/qa/plans/{third['plan_id']}/scenarios", headers=OTHER).json()
    hidden = next(row for row in rows["scenarios"] if row["case_id"] == case_id)
    assert hidden == {
        "case_id": case_id,
        "scenario_id": original["scenario_id"],
        "status": "EXISTING",
        "owned": False,
    }
    assert (
        client.get(f"/api/qa/plans/{first['plan_id']}/scenarios", headers=OTHER).status_code == 404
    )


def test_runs_of_a_scenario_are_grouped_across_plans_for_their_owner_only(client, fakes):
    planner = QaPlanner(ROOT)
    titles = iter(["첫 생성", "다시 생성"])

    async def generate(body):
        return reworded_design(planner, next(titles))

    fakes[1].design = generate
    first = client.post("/api/qa/design", json={}).json()
    second = client.post("/api/qa/design", json={}).json()
    case = second["cases"][-1]
    started = client.post(
        "/api/runs",
        json={"plan_id": second["plan_id"], "case_id": case["case_id"], "system_id": "B1"},
    )
    assert started.status_code == 202
    run = wait_for(client, started.json()["run_id"], lambda r: r["status"] == "WAITING_APPROVAL")

    rows = client.get(f"/api/qa/plans/{first['plan_id']}/scenarios").json()["scenarios"]
    scenario_id = next(r for r in rows if r["case_id"] == case["case_id"])["scenario_id"]
    assert run["qa_scenario_id"] == scenario_id

    history = client.get(f"/api/qa/scenarios/{scenario_id}/runs").json()
    assert history["owned"] and history["condition"]["risk_id"] == case["risk_id"]
    assert [r["run_id"] for r in history["runs"]] == [run["run_id"]]
    assert history["runs"][0]["plan_id"] == second["plan_id"]

    hidden = client.get(f"/api/qa/scenarios/{scenario_id}/runs", headers=OTHER).json()
    assert hidden["runs"] == [] and "condition" not in hidden and not hidden["owned"]
    assert client.get("/api/qa/scenarios/SCN-missing/runs").status_code == 404


def test_reference_runs_without_a_plan_join_the_library(client):
    started = client.post("/api/runs", json={"test_id": "S03", "system_id": "B0"})
    assert started.status_code == 202
    run = wait_for(client, started.json()["run_id"], lambda r: r["status"] == "WAITING_APPROVAL")
    assert run["qa_scenario_id"].startswith("SCN-")
    plan = client.post("/api/qa/plans", json={}).json()
    rows = client.get(f"/api/qa/plans/{plan['plan_id']}/scenarios").json()["scenarios"]
    assert run["qa_scenario_id"] in {row["scenario_id"] for row in rows}
