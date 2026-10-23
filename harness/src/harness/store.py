"""Run and event records in the harness schema (harness_app). Never touches sandbox data."""

import json
from pathlib import Path

from sqlalchemy import (
    Column,
    Integer,
    MetaData,
    String,
    Table,
    Text,
    UniqueConstraint,
    create_engine,
    func,
    insert,
    select,
    update,
)
from sqlalchemy.exc import IntegrityError

from harness.config import sqlalchemy_url

metadata = MetaData()
runs = Table(
    "harness_run",
    metadata,
    Column("run_id", String(128), primary_key=True),
    Column("status", String(32), nullable=False),
    Column("created_at", String(40), nullable=False),
    Column("body", Text, nullable=False),
)
events = Table(
    "harness_event",
    metadata,
    Column("run_id", String(128), primary_key=True),
    Column("sequence", Integer, primary_key=True),
    Column("event_id", String(128), nullable=False),
    Column("body", Text, nullable=False),
    UniqueConstraint("run_id", "event_id"),
)
plans = Table(
    "harness_qa_plan",
    metadata,
    Column("plan_id", String(128), primary_key=True),
    Column("created_by", String(128), primary_key=True),
    Column("body", Text, nullable=False),
)

registrations = Table(
    "harness_qa_target",
    metadata,
    Column("profile_id", String(128), primary_key=True),
    Column("created_by", String(128), primary_key=True),
    Column("created_at", String(40), nullable=False),
    Column("body", Text, nullable=False),
)

batches = Table(
    "harness_qa_batch",
    metadata,
    Column("batch_id", String(128), primary_key=True),
    Column("created_by", String(128), nullable=False),
    Column("body", Text, nullable=False),
)


simulations = Table(
    "harness_simulation",
    metadata,
    Column("run_id", String(128), primary_key=True),
    Column("body", Text, nullable=False),
)


class DuplicateEvent(Exception):
    pass


class Store:
    def __init__(self, database_url: str):
        url = sqlalchemy_url(database_url)
        if url.startswith("sqlite:///"):
            Path(url.removeprefix("sqlite:///")).parent.mkdir(parents=True, exist_ok=True)
        self.engine = create_engine(url, pool_pre_ping=True)
        metadata.create_all(self.engine)

    def close(self):
        self.engine.dispose()

    def put_simulation(self, run_id, body):
        values = {"body": json.dumps(body, ensure_ascii=False)}
        with self.engine.begin() as db:
            changed = db.execute(
                update(simulations).where(simulations.c.run_id == run_id).values(**values)
            ).rowcount
            if not changed:
                db.execute(insert(simulations).values(run_id=run_id, **values))

    def get_simulation(self, run_id):
        with self.engine.connect() as db:
            row = db.execute(
                select(simulations.c.body).where(simulations.c.run_id == run_id)
            ).first()
        return json.loads(row[0]) if row else None

    def put_plan(self, plan: dict, user_id: str):
        """Only server-built plans are stored; a plan's identity is immutable."""
        if self.get_plan(plan["plan_id"], user_id) is not None:
            return
        try:
            with self.engine.begin() as db:
                db.execute(
                    insert(plans).values(
                        plan_id=plan["plan_id"],
                        created_by=user_id,
                        body=json.dumps(plan, ensure_ascii=False),
                    )
                )
        except IntegrityError:
            if self.get_plan(plan["plan_id"], user_id) != plan:
                raise

    def get_plan(self, plan_id: str, user_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(
                select(plans.c.body).where(
                    plans.c.plan_id == plan_id, plans.c.created_by == user_id
                )
            ).first()
        return json.loads(row[0]) if row else None

    def put_registration(self, profile, owner):
        try:
            with self.engine.begin() as db:
                db.execute(
                    insert(registrations).values(
                        profile_id=profile["profile_id"],
                        created_by=owner,
                        created_at=profile["created_at"],
                        body=json.dumps(profile, ensure_ascii=False),
                    )
                )
        except IntegrityError:
            if self.get_registration(profile["profile_id"], owner) is None:
                raise
        return self.get_registration(profile["profile_id"], owner)

    def get_registration(self, profile_id, owner):
        with self.engine.connect() as db:
            row = db.execute(
                select(registrations.c.body).where(
                    registrations.c.profile_id == profile_id, registrations.c.created_by == owner
                )
            ).first()
        return json.loads(row[0]) if row else None

    def list_registrations(self, owner):
        with self.engine.connect() as db:
            rows = db.execute(
                select(registrations.c.body)
                .where(registrations.c.created_by == owner)
                .order_by(registrations.c.created_at.desc(), registrations.c.profile_id)
                .limit(50)
            )
            return [json.loads(row[0]) for row in rows]

    def put_batch(self, batch):
        values = {"created_by": batch["created_by"], "body": json.dumps(batch, ensure_ascii=False)}
        with self.engine.begin() as db:
            changed = db.execute(
                update(batches).where(batches.c.batch_id == batch["batch_id"]).values(**values)
            ).rowcount
            if not changed:
                db.execute(insert(batches).values(batch_id=batch["batch_id"], **values))

    def get_batch(self, batch_id, owner):
        with self.engine.connect() as db:
            row = db.execute(
                select(batches.c.body).where(
                    batches.c.batch_id == batch_id, batches.c.created_by == owner
                )
            ).first()
        return json.loads(row[0]) if row else None

    def all_batches(self):
        with self.engine.connect() as db:
            return [json.loads(row[0]) for row in db.execute(select(batches.c.body)).all()]

    # runs

    def put_run(self, run: dict):
        body = json.dumps(run, ensure_ascii=False)
        with self.engine.begin() as db:
            changed = db.execute(
                update(runs)
                .where(runs.c.run_id == run["run_id"])
                .values(status=run["status"], body=body)
            ).rowcount
            if not changed:
                db.execute(
                    insert(runs).values(
                        run_id=run["run_id"],
                        status=run["status"],
                        created_at=run["created_at"],
                        body=body,
                    )
                )

    def get_run(self, run_id: str) -> dict | None:
        with self.engine.connect() as db:
            row = db.execute(select(runs.c.body).where(runs.c.run_id == run_id)).first()
        return json.loads(row[0]) if row else None

    def list_runs(self, limit: int = 50) -> list[dict]:
        with self.engine.connect() as db:
            rows = db.execute(
                select(runs.c.body).order_by(runs.c.created_at.desc()).limit(limit)
            ).all()
        return [json.loads(row[0]) for row in rows]

    def all_runs(self) -> list[dict]:
        with self.engine.connect() as db:
            return [json.loads(row[0]) for row in db.execute(select(runs.c.body)).all()]

    def count_runs(self, prefix: str) -> int:
        with self.engine.connect() as db:
            return db.execute(
                select(func.count()).select_from(runs).where(runs.c.run_id.like(prefix + "%"))
            ).scalar_one()

    # events

    def add_event(self, run_id: str, event: dict) -> tuple[int, bool]:
        """Store an event with the next run-wide sequence. Returns (sequence, created)."""
        existing = self.event_sequence(run_id, event["event_id"])
        if existing is not None:
            return existing, False
        for _ in range(3):
            with self.engine.begin() as db:
                sequence = (
                    db.execute(
                        select(func.coalesce(func.max(events.c.sequence), 0)).where(
                            events.c.run_id == run_id
                        )
                    ).scalar_one()
                    + 1
                )
                body = {**event, "run_id": run_id, "sequence": sequence}
                try:
                    db.execute(
                        insert(events).values(
                            run_id=run_id,
                            sequence=sequence,
                            event_id=event["event_id"],
                            body=json.dumps(body, ensure_ascii=False),
                        )
                    )
                    return sequence, True
                except IntegrityError:
                    pass
            existing = self.event_sequence(run_id, event["event_id"])
            if existing is not None:
                return existing, False
        raise DuplicateEvent(event["event_id"])

    def event_sequence(self, run_id: str, event_id: str) -> int | None:
        with self.engine.connect() as db:
            row = db.execute(
                select(events.c.sequence).where(
                    events.c.run_id == run_id, events.c.event_id == event_id
                )
            ).first()
        return row[0] if row else None

    def list_events(
        self, run_id: str, after_sequence: int = 0, limit: int | None = None, types=None
    ) -> list[dict]:
        query = (
            select(events.c.body)
            .where(events.c.run_id == run_id, events.c.sequence > after_sequence)
            .order_by(events.c.sequence)
        )
        if limit is not None:
            query = query.limit(limit)
        with self.engine.connect() as db:
            items = [json.loads(row[0]) for row in db.execute(query).all()]
        if types:
            items = [item for item in items if item["event_type"] in types]
        return items

    def runs_citing(self, evidence_id: str) -> set[str]:
        """Runs whose stored events cite the evidence ID (used to tell foreign from unknown)."""
        needle = json.dumps(evidence_id, ensure_ascii=False)
        with self.engine.connect() as db:
            rows = db.execute(
                select(events.c.run_id, events.c.body).where(events.c.body.contains(needle))
            ).all()
        return {
            run_id
            for run_id, body in rows
            if evidence_id in json.loads(body).get("evidence_ids", [])
        }
