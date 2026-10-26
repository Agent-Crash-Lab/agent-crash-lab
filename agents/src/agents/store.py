"""Small local run/event store, independent of the business database."""

import json
import sqlite3
import time
from datetime import UTC, datetime
from uuid import uuid4


class Store:
    def __init__(self, path):
        self.db = sqlite3.connect(path)
        self.db.execute("PRAGMA journal_mode=WAL")
        self.db.executescript("""
            CREATE TABLE IF NOT EXISTS runs (
                run_id TEXT PRIMARY KEY, status TEXT NOT NULL, body TEXT NOT NULL
            );
            CREATE UNIQUE INDEX IF NOT EXISTS one_active_run ON runs((1))
                WHERE status IN ('PREPARING','RUNNING','WAITING_APPROVAL');
            CREATE TABLE IF NOT EXISTS events (
                run_id TEXT NOT NULL, sequence INTEGER NOT NULL, body TEXT NOT NULL,
                PRIMARY KEY(run_id, sequence)
            );
        """)

    def get(self, run_id):
        row = self.db.execute("SELECT body FROM runs WHERE run_id=?", (run_id,)).fetchone()
        return json.loads(row[0]) if row else None

    def all(self):
        return [json.loads(row[0]) for row in self.db.execute("SELECT body FROM runs")]

    def active(self):
        # Match the partial index: completed history must not enter the 0.2s monitor loop.
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT body FROM runs "
                "WHERE status IN ('PREPARING','RUNNING','WAITING_APPROVAL')"
            )
        ]

    def put(self, run):
        with self.db:
            self.db.execute(
                "INSERT INTO runs VALUES (?,?,?) ON CONFLICT(run_id) DO UPDATE SET "
                "status=excluded.status, body=excluded.body",
                (run["run_id"], run["status"], json.dumps(run, ensure_ascii=False)),
            )

    def event(self, run_id, event_type, payload=None):
        with self.db:
            sequence = self.db.execute(
                "SELECT COALESCE(MAX(sequence),0)+1 FROM events WHERE run_id=?", (run_id,)
            ).fetchone()[0]
            run = self.get(run_id)
            investigator = run["agent_kind"] == "INVESTIGATION_AGENT"
            previous = self.db.execute(
                "SELECT body FROM events WHERE run_id=? ORDER BY sequence DESC LIMIT 1", (run_id,)
            ).fetchone()
            body = {
                "run_id": run_id,
                "event_id": str(uuid4()),
                "sequence": sequence,
                "event_type": event_type,
                "producer": "agents",
                "actor_id": "investigation_agent" if investigator else "purchase_agent",
                "node_id": "investigator" if investigator else "agent",
                "parent_event_id": json.loads(previous[0])["event_id"] if previous else None,
                "tool_call_id": None,
                "evidence_ids": [],
                "occurred_at": datetime.now(UTC).isoformat(),
                "payload": payload or {},
            }
            self.db.execute(
                "INSERT INTO events VALUES (?,?,?)", (run_id, sequence, json.dumps(body))
            )

    def events(self, run_id, after=0, limit=100):
        return [
            json.loads(row[0])
            for row in self.db.execute(
                "SELECT body FROM events WHERE run_id=? AND sequence>? ORDER BY sequence LIMIT ?",
                (run_id, after, limit),
            )
        ]

    def fail(self, run_id, reason):
        run = self.get(run_id)
        run.update(status="ERROR", reason=reason, finished_at=time.time())
        if run.get("write_started"):
            run["result"] = {
                "request_id": run["request"]["request_id"],
                "outcome": "UNKNOWN",
                "order_id": None,
                "message": "발주 결과를 확인할 수 없습니다.",
            }
        self.put(run)
        self.event(run_id, "RUN_FINISHED", {"status": "ERROR", "reason": reason})
