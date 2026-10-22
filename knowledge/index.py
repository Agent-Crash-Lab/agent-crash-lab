"""Explicit local indexing job. Never accepts a document URL/path from an API caller."""

import hashlib
import json
import os
import re
from pathlib import Path

from psycopg.types.json import Jsonb
from pypdf import PdfReader

from knowledge.embedding import MODEL, REVISION, Embedder, windows
from knowledge.retrieval import DDL, connection, vector_literal


def prepare(manifest, raw_dir, tokenizer):
    documents, parents, children = [], [], []
    for source in manifest["documents"]:
        pages = []
        if source["content_kind"] == "PDF_TEXT":
            path = (raw_dir / source["file"]).resolve()
            if not path.is_relative_to(raw_dir.resolve()):
                raise ValueError("Source escapes corpus directory")
            if hashlib.sha256(path.read_bytes()).hexdigest() != source["sha256"]:
                raise ValueError("Source hash mismatch")
            reader = PdfReader(path)
            for number, page in enumerate(reader.pages, 1):
                text = (
                    (page.extract_text() or "")
                    .replace("\x00", "")
                    .replace("\u00ad", "")
                )
                text = re.sub(r"(?<=\w)-\n(?=\w)", "", text)
                if text.strip():
                    pages.append((number, text.strip()))
        else:
            text = source["text_en"]
            if (
                source.get("sha256")
                and hashlib.sha256(text.encode()).hexdigest() != source["sha256"]
            ):
                raise ValueError("Summary hash mismatch")
            pages = [(0, text)]
        documents.append(source)
        for number, text in pages:
            for part, parent in enumerate(windows(text, tokenizer, 900)):
                digest = hashlib.sha256(parent.encode()).hexdigest()[:16]
                pid = f"{source['source_id']}:p{number}:{part}:{digest}"
                parents.append((pid, source["source_id"], number, parent))
                for ordinal, child in enumerate(windows(parent, tokenizer, 240, 40)):
                    children.append((f"{pid}:c{ordinal}", pid, child))
    return documents, parents, children


def main():
    manifest_path = Path(
        os.environ.get("CORPUS_MANIFEST", "/project/qa/knowledge/corpus.json")
    )
    raw_dir = Path(os.environ.get("CORPUS_RAW_DIR", "/data/raw"))
    raw = manifest_path.read_bytes()
    manifest = json.loads(raw)
    fingerprint = hashlib.sha256(
        raw + f"{MODEL}:{REVISION}:parent900:child240:overlap40".encode()
    ).hexdigest()
    model = Embedder()
    with connection() as db:
        db.execute(DDL)
        state = db.execute("SELECT * FROM knowledge.index_state WHERE id=1").fetchone()
    if (
        state
        and state["manifest_hash"] == fingerprint
        and state["model_sha256"] == model.model_sha256
    ):
        print(
            "Index already matches corpus and embedding version; unchanged.", flush=True
        )
        return
    documents, parents, children = prepare(manifest, raw_dir, model.splitter)
    # Compute outside the DB transaction; a failed job leaves the old index intact.
    cached = {}
    if state and state["model_sha256"] == model.model_sha256 and state["model"] == MODEL and state["revision"] == REVISION:
        with connection() as db:
            cached = {row["id"]: (row["body"], row["embedding"]) for row in db.execute(
                "SELECT id, body, embedding::text AS embedding FROM knowledge.child"
            ).fetchall()}
    vectors = {}
    pending = []
    for row in children:
        existing = cached.get(row[0])
        if existing and existing[0] == row[2]:
            vectors[row[0]] = existing[1]
        else:
            pending.append(row)
    for offset in range(0, len(pending), 8):
        batch = pending[offset : offset + 8]
        for row, vector in zip(batch, model.encode([row[2] for row in batch]), strict=True):
            vectors[row[0]] = vector_literal(vector)
    print(f"Embedded {len(pending)} changed children; reused {len(children) - len(pending)}", flush=True)
    with connection() as db:
        db.execute("SELECT pg_advisory_xact_lock(7812345)")
        db.execute("DELETE FROM knowledge.document")
        with db.cursor() as cur:
            cur.executemany(
                "INSERT INTO knowledge.document VALUES (%s,%s,%s,%s,%s)",
                [
                    (s["source_id"], s["title"], s["sha256"], s["roles"], Jsonb(s))
                    for s in documents
                ],
            )
            cur.executemany(
                "INSERT INTO knowledge.parent VALUES (%s,%s,%s,%s)", parents
            )
            cur.executemany(
                "INSERT INTO knowledge.child (id,parent_id,body,embedding) VALUES (%s,%s,%s,%s::vector)",
                [
                    (*row, vectors[row[0]])
                    for row in children
                ],
            )
        db.execute(
            """INSERT INTO knowledge.index_state VALUES (1,%s,%s,%s,%s,now())
                   ON CONFLICT(id) DO UPDATE SET manifest_hash=excluded.manifest_hash,model=excluded.model,
                   revision=excluded.revision,model_sha256=excluded.model_sha256,indexed_at=now()""",
            (fingerprint, MODEL, REVISION, model.model_sha256),
        )
    print(
        json.dumps(
            {
                "documents": len(documents),
                "parents": len(parents),
                "children": len(children),
                "index_version": fingerprint,
            }
        ),
        flush=True,
    )


if __name__ == "__main__":
    main()
