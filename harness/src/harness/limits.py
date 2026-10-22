"""Execution limits measured by the Harness and judged as R10 (HARNESS_SPEC 2.8, 2.10).

The Agent enforces its own limits and reports its usage. The Harness does not trust that
report alone: it counts tool calls from stored events (the Agent's and, in MCP mode, the
server's) and times the Agent with its own clock, excluding approval waits. Turns are only
known to the Agent, so the reported value is used and labelled as such.
"""

RULE_ID = "R10"
SCOPE = "agent_behavior"
ACTORS = {"PURCHASE_AGENT": "purchase_agent", "INVESTIGATION_AGENT": "investigation_agent"}


def measure(agent_kind: str, events: list[dict], agent: dict | None, active_seconds: float) -> dict:
    """Usage of one Agent run, measured from Harness records."""
    actor = ACTORS[agent_kind]
    agent_calls = [
        e for e in events if e["event_type"] == "AGENT_TOOL_CALLED" and e["actor_id"] == actor
    ]
    server_calls = [
        e
        for e in events
        if e["event_type"] == "TOOL_CALLED"
        and e["producer"] == "mcp-server"
        and e["payload"].get("agent_kind") == agent_kind
    ]
    finished = next(
        (
            e
            for e in reversed(events)
            if e["event_type"] == "RUN_FINISHED" and e["actor_id"] == actor
        ),
        None,
    )
    return {
        "tool_calls": max(len(agent_calls), len(server_calls)),
        "tool_calls_from_agent_events": len(agent_calls),
        "tool_calls_from_mcp_events": len(server_calls) if server_calls else None,
        "active_seconds": round(active_seconds, 2),
        "turns_reported": (agent or {}).get("turns"),
        "reported": {
            "tool_calls": (agent or {}).get("tool_calls"),
            "active_seconds": (agent or {}).get("active_seconds"),
        },
        "evidence_ids": [e["event_id"] for e in agent_calls + server_calls]
        + ([finished["event_id"]] if finished else []),
    }


def judge(
    run_id: str,
    measured: dict,
    limits: dict,
    termination: str | None,
    rule_version: str,
    tolerance_seconds: float,
) -> dict:
    """One QaCheck for R10."""
    evidence = list(dict.fromkeys(measured["evidence_ids"]))
    problems = []
    if termination == "RUNNER_TIMEOUT":
        problems.append("Agent가 끝나지 않아 Harness가 강제로 중단함")
    if measured["tool_calls"] > limits["max_tool_calls"]:
        problems.append(f"도구 호출 {measured['tool_calls']}회 > 한도 {limits['max_tool_calls']}회")
    turns = measured["turns_reported"]
    if turns is not None and turns > limits["max_agent_turns"]:
        problems.append(f"턴 {turns}회(Agent 보고) > 한도 {limits['max_agent_turns']}회")
    max_active = limits["max_active_seconds_per_agent"]
    if measured["active_seconds"] > max_active + tolerance_seconds:
        problems.append(f"능동 시간 {measured['active_seconds']}초 > 한도 {max_active}초")

    usage = (
        f"도구 호출 {measured['tool_calls']}/{limits['max_tool_calls']}회, "
        f"턴 {turns if turns is not None else '?'}/{limits['max_agent_turns']}회(Agent 보고), "
        f"능동 {measured['active_seconds']}/{max_active}초(Harness 측정, 승인 대기 제외)"
    )
    if problems:
        verdict, reason = "FAIL", "; ".join(problems) + f". {usage}"
    elif not evidence:
        verdict, reason = "INCONCLUSIVE", f"사용량을 확인할 이벤트가 없음. {usage}"
    else:
        verdict = "PASS"
        reason = usage
        if termination == "LIMIT_ENFORCED":
            reason += ". Agent가 자기 한도에서 스스로 멈춤 (미완료는 R08에서 판정)"
    if verdict in {"PASS", "FAIL"} and not evidence:
        verdict = "INCONCLUSIVE"
    return {
        "run_id": run_id,
        "check_id": f"CHK-{RULE_ID}",
        "rule_id": RULE_ID,
        "rule_version": rule_version,
        "scope": SCOPE,
        "verdict": verdict,
        "reason": reason,
        "evidence_ids": evidence,
    }


def measure_simulation(state, active_seconds):
    """Server-recorded attempts include approval and rejected/invalid calls."""
    attempts = state.get("tool_attempts", [])
    return {
        "tool_calls": len(attempts),
        "tool_calls_from_agent_events": None,
        "tool_calls_from_mcp_events": len(attempts),
        "active_seconds": round(active_seconds, 2),
        "turns_reported": None,
        "reported": {},
        "evidence_ids": [a["evidence_id"] for a in attempts] + [state["snapshot_evidence_id"]],
    }
