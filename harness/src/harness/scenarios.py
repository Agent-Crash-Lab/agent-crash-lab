"""Scenario library: one entry per distinct test condition of a target.

A plan bundles cases, and its ID hashes the whole plan including model-written text, so
regenerating a design can repeat an existing case under a new plan. The library keys a
case by its test condition only. Entries live beside plans: a duplicate link is never
written into a plan, because that would change the plan's content-derived ID.
"""

from harness.planning import fingerprint


def condition(case: dict) -> dict:
    """The fields that decide how a case runs and is judged. Prose and IDs are excluded."""
    simulation = case["simulation"]
    return {
        "risk_id": case["risk_id"],
        "business_input": case["business_input"],
        "initial_state": case["initial_state"],
        "simulation": {
            **simulation,
            "required_capabilities": sorted(simulation["required_capabilities"]),
        },
        "interventions": case.get("generated_scenario", {}).get("interventions", []),
        "assertions": sorted(case["assertions"]),
        "registered_test_id": case["execution"]["registered_test_id"],
        "rule_ids": sorted(case["execution"]["rule_ids"]),
    }


def case_fingerprint(case: dict) -> str:
    return fingerprint(condition(case))


def scenario_id(target_hash: str, case_fingerprint: str) -> str:
    return "SCN-" + fingerprint({"target_hash": target_hash, "fingerprint": case_fingerprint})[:24]


def register(store, plan: dict, case: dict, owner: str, now: str) -> dict | None:
    """Store the case's condition once per target. Returns the stored (possibly older) entry."""
    if case["execution"]["status"] != "READY":
        return None
    fp = case_fingerprint(case)
    return store.add_scenario(
        {
            "scenario_id": scenario_id(plan["target_hash"], fp),
            "target_id": plan["target_id"],
            "target_hash": plan["target_hash"],
            "fingerprint": fp,
            "created_by": owner,
            "created_at": now,
            "first_plan_id": plan["plan_id"],
            "first_case_id": case["case_id"],
            "condition": condition(case),
        }
    )


def view(entry: dict, plan: dict, case: dict, owner: str) -> dict:
    """What the requester may see. Another user's entry discloses only that it exists."""
    first = entry["first_plan_id"] == plan["plan_id"] and entry["first_case_id"] == case["case_id"]
    owned = entry["created_by"] == owner
    shown = {
        "case_id": case["case_id"],
        "scenario_id": entry["scenario_id"],
        "status": "NEW" if first and owned else "EXISTING",
        "owned": owned,
    }
    if owned and not first:
        shown.update(first_plan_id=entry["first_plan_id"], first_case_id=entry["first_case_id"])
    return shown


def index_plan(store, plan: dict, owner: str, now: str) -> list[dict]:
    """Register every executable case of a plan and describe each against the library."""
    rows = []
    for case in plan["cases"]:
        entry = register(store, plan, case, owner, now)
        if entry is not None:
            rows.append(view(entry, plan, case, owner))
    return rows
