"""Independent read of the business DB as oracle_ro (HARNESS_SPEC §6).

The Oracle does not trust the MCP finalize response or the Agent's report: it reads the
sandbox rows itself, in one read-only REPEATABLE READ transaction so every table is seen
at the same moment.
"""

import hashlib
import json
from dataclasses import dataclass, field

from sqlalchemy import create_engine, text

from harness.config import sqlalchemy_url


def payload_hash(payload: dict) -> str:
    """MCP_SPEC 0.1 / config canonical_payload: sort_keys, ensure_ascii=false, no whitespace."""
    canonical = json.dumps(payload, sort_keys=True, ensure_ascii=False, separators=(",", ":"))
    return hashlib.sha256(canonical.encode()).hexdigest()


@dataclass(frozen=True)
class Observation:
    run_id: str
    request_id: str
    finalized: bool  # MCP finalize (3.4) ran; the purchase token is revoked
    snapshot_complete: bool  # finalized with no in-flight tool call
    pending_tool_calls: int
    latest_request_version: int | None
    snapshot_evidence_ids: list[str]
    # oracle-observation rows plus payload_hash, tool_call_id, commit_evidence_id
    orders: list[dict]
    approvals: list[dict]
    # Purchase Agent tool calls in call order, blocked ones included (R05)
    tool_calls: list[dict]
    faults: list[dict]
    evidence: dict[str, dict] = field(default_factory=dict)  # evidence_id → {kind, refs}
    # idempotent-v1 replay record: request_id → order_id
    replayed_orders: dict[str, str] = field(default_factory=dict)

    request_payload: dict | None = None
    suppliers: list[dict] | None = None
    supply_sources: list[dict] | None = None

    def approval(self, approval_id: str | None) -> dict | None:
        return next((a for a in self.approvals if a["approval_id"] == approval_id), None)

    def order(self, order_id: str | None) -> dict | None:
        return next((o for o in self.orders if o["order_id"] == order_id), None)

    def create_calls(self) -> list[dict]:
        return [c for c in self.tool_calls if c["tool"] == "create_purchase_order"]


def _rows(conn, sql: str, **params) -> list[dict]:
    return [dict(row._mapping) for row in conn.execute(text(sql), params)]


def observe(database_url: str, run_id: str, request_id: str) -> Observation:
    if not database_url:
        raise RuntimeError("ORACLE_DATABASE_URL is not configured")
    engine = create_engine(sqlalchemy_url(database_url))
    try:
        with engine.connect().execution_options(
            isolation_level="REPEATABLE READ", postgresql_readonly=True
        ) as conn:
            return _read(conn, run_id, request_id)
    finally:
        engine.dispose()


def _read(conn, run_id: str, request_id: str) -> Observation:
    keys = {"run_id": run_id, "request_id": request_id}
    context = _rows(
        conn,
        "SELECT finalized_at, snapshot_complete, pending_tool_calls"
        " FROM sandbox.run_context WHERE run_id = :run_id",
        **keys,
    )
    if not context:
        raise RuntimeError(f"run {run_id} is not in the business DB")
    context = context[0]
    latest = _rows(
        conn,
        "SELECT max(request_version) AS v FROM sandbox.purchase_request"
        " WHERE run_id = :run_id AND request_id = :request_id",
        **keys,
    )[0]["v"]
    request_rows = _rows(
        conn,
        "SELECT payload FROM sandbox.purchase_request WHERE run_id=:run_id "
        "AND request_id=:request_id ORDER BY request_version DESC LIMIT 1",
        **keys,
    )
    suppliers = _rows(
        conn, "SELECT supplier_id, status FROM sandbox.supplier WHERE run_id=:run_id", **keys
    )
    supply_sources = _rows(
        conn,
        "SELECT part_id, supplier_id, plant_id, purchasing_org_id, allowed, policy_version "
        "FROM sandbox.approved_supply_source WHERE run_id=:run_id",
        **keys,
    )
    orders = _rows(
        conn,
        """SELECT order_id, run_id, request_id, approval_id, payload, payload_hash,
                  commit_sequence, committed_at, tool_call_id, commit_evidence_id
           FROM sandbox.purchase_order WHERE run_id = :run_id AND request_id = :request_id
           ORDER BY commit_sequence""",
        **keys,
    )
    approvals = _rows(
        conn,
        """SELECT approval_id, run_id, request_id, request_version, approver_id, decision,
                  payload, payload_hash, revoked, decision_sequence, authority_valid, decided_at
           FROM sandbox.approval WHERE run_id = :run_id AND request_id = :request_id
           ORDER BY decision_sequence""",
        **keys,
    )
    tool_calls = _rows(
        conn,
        """SELECT tool_call_id, tool, arguments, status, is_error, error_code,
                  fault_injected, idempotent_replay, started_at, finished_at
           FROM sandbox.tool_call WHERE run_id = :run_id AND agent_kind = 'PURCHASE_AGENT'
           ORDER BY started_at, tool_call_id""",
        **keys,
    )
    faults = _rows(
        conn,
        """SELECT fault_id, tool_name, trigger, target_error_code, status,
                  applied_count, max_applied_count,
                  related_tool_call_id, related_order_id, evidence_id
           FROM sandbox.fault_rule WHERE run_id = :run_id ORDER BY fault_id""",
        **keys,
    )
    evidence = _rows(
        conn,
        "SELECT evidence_id, kind, refs, created_at FROM sandbox.evidence"
        " WHERE run_id = :run_id ORDER BY created_at, evidence_id",
        **keys,
    )
    replayed = _rows(
        conn,
        "SELECT request_id, order_id FROM sandbox.idempotency_record WHERE run_id = :run_id",
        **keys,
    )
    for row in orders + approvals:
        row["payload_hash"] = row["payload_hash"].strip()
    return Observation(
        run_id=run_id,
        request_id=request_id,
        finalized=context["finalized_at"] is not None,
        snapshot_complete=bool(context["snapshot_complete"]),
        pending_tool_calls=context["pending_tool_calls"] or 0,
        latest_request_version=latest,
        request_payload=request_rows[0]["payload"] if request_rows else None,
        suppliers=suppliers,
        supply_sources=supply_sources,
        snapshot_evidence_ids=[
            e["evidence_id"] for e in evidence if e["kind"] == "BUSINESS_SNAPSHOT"
        ],
        orders=orders,
        approvals=approvals,
        tool_calls=tool_calls,
        faults=faults,
        evidence={e["evidence_id"]: {"kind": e["kind"], "refs": e["refs"]} for e in evidence},
        replayed_orders={r["request_id"]: r["order_id"] for r in replayed},
    )
