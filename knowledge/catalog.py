"""Register an operator-reviewed English summary in the existing corpus manifest.

No network fetch or policy adoption. Indexing remains an explicit atomic DB job.
"""

import fcntl
import hashlib
import json
import os
import re
import tempfile
from pathlib import Path
from urllib.parse import urlsplit


def validate_record(record, risk_keys):
    if not isinstance(record, dict):
        raise TypeError("A source record must be one JSON object")
    if record.get("content_kind") != "CURATED_SUMMARY":
        raise ValueError(
            "New entries require a reviewed CURATED_SUMMARY; PDF download remains separate"
        )
    for key in (
        "source_id",
        "title",
        "url",
        "attribution",
        "source_version",
        "source_locator",
        "scope",
        "source_facts_en",
        "qa_transfer_en",
        "text_en",
    ):
        if not isinstance(record.get(key), str) or not record[key].strip():
            raise ValueError("Missing source field: " + key)
    if not re.fullmatch(r"[A-Z][A-Z0-9-]{1,80}", record["source_id"]):
        raise ValueError("Invalid source ID")
    url = urlsplit(record["url"])
    if url.scheme != "https" or not url.hostname or url.username or url.password:
        raise ValueError("An attributed HTTPS source URL is required")
    if record.get("source_type") not in {"RESEARCH", "INCIDENT", "TECHNICAL"}:
        raise ValueError("This importer cannot add or adopt project policy")
    for key, allowed in (
        ("roles", {"COMMON", "PURCHASE", "PRODUCTION", "QUALITY"}),
        ("risk_types", set(risk_keys)),
        ("evidence_domains", {"MANUFACTURING", "AGENTIC"}),
    ):
        values = record.get(key)
        if (
            not isinstance(values, list)
            or not values
            or any(not isinstance(v, str) for v in values)
            or not set(values) <= allowed
        ):
            raise ValueError("Invalid source tags: " + key)
    if len(record["evidence_domains"]) != 1:
        raise ValueError(
            "Choose one review domain per source to keep the gates separate"
        )
    if record.get("mapping_review") != "TEAM_REVIEWED":
        raise ValueError("A person must review the source-to-risk mapping first")
    if record.get("policy_status") or record.get("adopted_adapters"):
        raise ValueError("Source import cannot adopt policy")
    if not isinstance(record.get("rights"), dict) or not record["rights"].get(
        "license"
    ):
        raise ValueError("Source rights must be recorded")
    digest = hashlib.sha256(record["text_en"].encode()).hexdigest()
    if record.get("sha256", digest) != digest:
        raise ValueError("Summary hash mismatch")
    return {
        **record,
        "sha256": digest,
        "summary_sha256": digest,
        "claim_role": "HISTORICAL_NON_AI_ANALOGY"
        if record["source_type"] == "INCIDENT"
        else "RESEARCH_FAILURE_OR_METHOD"
        if record["source_type"] == "RESEARCH"
        else "OFFICIAL_TECHNICAL_GUIDANCE",
    }


def add_record(manifest_path, record_path, risk_keys, *, replace=False):
    with Path(record_path).open("rb") as incoming:
        raw = incoming.read(64_001)
    if len(raw) > 64_000:
        raise ValueError("Source record exceeds 64 KB")
    record = validate_record(json.loads(raw), risk_keys)
    path = Path(manifest_path).resolve()
    lock_name = hashlib.sha256(str(path).encode()).hexdigest()
    with (
        Path(tempfile.gettempdir()) / ("crashlab-corpus-" + lock_name + ".lock")
    ).open("a") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        manifest = json.loads(path.read_text())
        documents = {d["source_id"]: d for d in manifest["documents"]}
        previous = documents.get(record["source_id"])
        if previous == record:
            return {"status": "UNCHANGED", "source_id": record["source_id"]}
        if previous and not replace:
            raise ValueError("Source ID exists; review a replacement and use --replace")
        if previous and previous.get("source_type") == "PROJECT_POLICY":
            raise ValueError("Source import cannot replace project policy")
        documents[record["source_id"]] = record
        manifest["documents"] = list(documents.values())
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w", dir=path.parent, delete=False
            ) as out:
                temporary = Path(out.name)
                out.write(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
                out.flush()
                os.fsync(out.fileno())
            os.replace(temporary, path)
        finally:
            if temporary and temporary.exists():
                temporary.unlink()
    return {
        "status": "REGISTERED",
        "source_id": record["source_id"],
        "next": "make knowledge-index (new vectors only; old index survives failures)",
    }
