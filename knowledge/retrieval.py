"""Small-child retrieval + reciprocal-rank fusion + original parent expansion."""

import os
from contextlib import contextmanager

import psycopg
from psycopg.rows import dict_row

from knowledge.embedding import MODEL, REVISION

DDL = """
CREATE TABLE IF NOT EXISTS knowledge.index_state (
 id int PRIMARY KEY CHECK (id=1), manifest_hash text NOT NULL, model text NOT NULL,
 revision text NOT NULL, model_sha256 text NOT NULL, indexed_at timestamptz NOT NULL DEFAULT now());
CREATE TABLE IF NOT EXISTS knowledge.document (
 id text PRIMARY KEY, title text NOT NULL, version text NOT NULL, roles text[] NOT NULL,
 metadata jsonb NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge.parent (
 id text PRIMARY KEY, document_id text NOT NULL REFERENCES knowledge.document(id) ON DELETE CASCADE,
 page int NOT NULL, body text NOT NULL);
CREATE TABLE IF NOT EXISTS knowledge.child (
 id text PRIMARY KEY, parent_id text NOT NULL REFERENCES knowledge.parent(id) ON DELETE CASCADE,
 body text NOT NULL, embedding vector(384) NOT NULL,
 keywords tsvector GENERATED ALWAYS AS (to_tsvector('english',body)) STORED);
CREATE INDEX IF NOT EXISTS knowledge_child_keywords ON knowledge.child USING gin(keywords);
"""


@contextmanager
def connection():
    with psycopg.connect(
        os.environ["KNOWLEDGE_DATABASE_URL"],
        row_factory=dict_row,
        options="-c search_path=knowledge,public",
    ) as db:
        yield db


def vector_literal(vector):
    return "[" + ",".join(str(float(n)) for n in vector) + "]"


def status():
    with connection() as db:
        db.execute(DDL)
        state = db.execute("SELECT * FROM knowledge.index_state WHERE id=1").fetchone()
        counts = {
            kind: db.execute(f"SELECT count(*) AS n FROM knowledge.{kind}").fetchone()[
                "n"
            ]
            for kind in ("document", "parent", "child")
        }
        source_counts = db.execute(
            "SELECT COALESCE(metadata->>'source_type','REFERENCE') AS kind, count(*) AS n FROM knowledge.document GROUP BY 1"
        ).fetchall()
    return {
        "source_counts": {row["kind"]: row["n"] for row in source_counts},
        "indexed": bool(state),
        "index": state,
        "counts": counts,
        "language": "en",
        "retrieval": "BGE dense + PostgreSQL full-text / RRF + parent expansion",
        "reranker": "not_enabled",
    }


def search(
    embedder, query, target_type="COMMON", limit=3, source_type="ALL", risk_type=None,
    evidence_domain=None,
):
    embedding = vector_literal(embedder.encode([query], query=True)[0])
    with connection() as db:
        db.execute("SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY")
        try:
            state = db.execute("SELECT * FROM knowledge.index_state WHERE id=1").fetchone()
        except psycopg.errors.UndefinedTable:
            raise ValueError("KNOWLEDGE_NOT_INDEXED") from None
        if not state or state["model"] != MODEL or state["revision"] != REVISION:
            raise ValueError("KNOWLEDGE_NOT_INDEXED")
        if state["model_sha256"] != embedder.model_sha256:
            raise ValueError("EMBEDDING_VERSION_MISMATCH")
        select = """SELECT c.id,c.parent_id,c.body,p.page,p.body AS parent_text,
          d.id AS source_id,d.title,d.version,d.metadata,
          1-(c.embedding <=> %s::vector) AS similarity
          FROM knowledge.child c JOIN knowledge.parent p ON p.id=c.parent_id
          JOIN knowledge.document d ON d.id=p.document_id
          WHERE (%s='COMMON' OR %s=ANY(d.roles) OR 'COMMON'=ANY(d.roles))
          AND (%s='ALL' OR d.metadata->>'source_type'=%s)
          AND (%s::text IS NULL OR COALESCE(d.metadata->'risk_types','[]'::jsonb) ? %s::text)
          AND (%s::text IS NULL OR COALESCE(d.metadata->'evidence_domains','[]'::jsonb) ? %s::text)"""
        filters = (
            embedding,
            target_type,
            target_type,
            source_type,
            source_type,
            risk_type,
            risk_type,
            evidence_domain,
            evidence_domain,
        )
        vector_hits = db.execute(
            select + " ORDER BY c.embedding <=> %s::vector,c.id LIMIT 30",
            (*filters, embedding),
        ).fetchall()
        lexical_hits = db.execute(
            select + " AND c.keywords @@ plainto_tsquery('english',%s)"
            " ORDER BY ts_rank_cd(c.keywords,plainto_tsquery('english',%s)) DESC,c.id LIMIT 30",
            (*filters, query, query),
        ).fetchall()
    scores, hits = {}, {}
    for group in (vector_hits, lexical_hits):
        for rank, item in enumerate(group, 1):
            hits[item["id"]] = item
            scores[item["id"]] = scores.get(item["id"], 0) + 1 / (60 + rank)
    results, parents = [], set()
    for cid in sorted(scores, key=lambda k: (-scores[k], k)):
        hit = hits[cid]
        if hit["parent_id"] in parents:
            continue
        parents.add(hit["parent_id"])
        meta = hit["metadata"]
        results.append(
            {
                "document_id": hit["parent_id"],
                "source_id": hit["source_id"],
                "version": hit["version"],
                "title": hit["title"],
                "location": f"PDF page {hit['page']}"
                if hit["page"]
                else "Curated source summary",
                "page": hit["page"],
                "source_url": meta["url"],
                "content_kind": meta["content_kind"],
                "scope": meta["scope"],
                "source_type": meta.get("source_type", "REFERENCE"),
                "risk_types": meta.get("risk_types", []),
                "evidence_domains": meta.get("evidence_domains", []),
                "claim_role": meta.get("claim_role", "REFERENCE_CONTEXT"),
                "policy_status": meta.get("policy_status"),
                "adopted_adapters": meta.get("adopted_adapters", []),
                "source_locator": meta.get("source_locator"),
                "attribution": meta["attribution"],
                "rights": meta["rights"],
                "matched_child_id": cid,
                "matched_text": hit["body"],
                "parent_text": hit["parent_text"],
                "vector_similarity": float(hit["similarity"]),
                "rrf_score": scores[cid],
            }
        )
        if len(results) >= limit:
            break
    return {
        "query": query,
        "target_type": target_type,
        "source_type": source_type,
        "risk_type": risk_type,
        "evidence_domain": evidence_domain,
        "language": "en",
        "results": results,
        "index_version": state["manifest_hash"],
        "model": MODEL,
        "model_revision": REVISION,
        "ranking": "RRF(vector+fulltext), child search, parent deduplication",
        "note": "Retrieved context is reference material, not a business verdict.",
    }
