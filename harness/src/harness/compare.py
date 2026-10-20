"""B0/B1 comparison of two completed SYSTEM runs (HARNESS_SPEC 1.7)."""

FIXED_FIELDS_ORDER = (
    "test_id",
    "test_version",
    "fixture_id",
    "agent_version",
    "prompt_version",
    "model_kind",
    "model",
    "rule_version",
    "config_version",
    "limits",
    "retry_policy",
    "faults",
    "system_id",
    "server_policy_version",
    "mcp_version",
)


class NotComparable(Exception):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def compare(left: dict, right: dict) -> dict:
    if left["test_kind"] != "SYSTEM" or right["test_kind"] != "SYSTEM":
        raise NotComparable("NOT_COMPARABLE")
    if left["test_id"] != right["test_id"]:
        raise NotComparable("NOT_COMPARABLE")
    if left["status"] != "COMPLETED" or right["status"] != "COMPLETED":
        raise NotComparable("RUN_NOT_COMPLETED")

    fixed, changed = {}, []
    for key in FIXED_FIELDS_ORDER:
        a, b = left["manifest"].get(key), right["manifest"].get(key)
        if a == b:
            fixed[key] = a
        else:
            changed.append({"field": key, "left": a, "right": b})

    def actual(run):
        observation = run.get("observation") or {}
        fault = run.get("fault") or {}
        return {
            "order_count": len(observation.get("orders", [])) if observation else None,
            "fault_status": fault.get("status"),
        }

    def verdicts(run):
        return {(c["rule_id"], c["scope"]): c["verdict"] for c in run.get("checks", [])}

    a, b = verdicts(left), verdicts(right)
    checks = [
        {"rule_id": rule_id, "scope": scope, "left": a.get(key), "right": b.get(key)}
        for key in sorted(set(a) | set(b))
        for rule_id, scope in [key]
    ]
    return {
        "left": {k: left[k] for k in ("run_id", "system_id", "status")},
        "right": {k: right[k] for k in ("run_id", "system_id", "status")},
        "fixed_conditions": fixed,
        "changed": changed,
        "actual": {"left": actual(left), "right": actual(right)},
        "checks": checks,
    }
