"""Download only the four versioned PDF sources approved in the corpus manifest."""

import argparse
import hashlib
import json
import sys
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def main():
    parser = argparse.ArgumentParser(
        description="Download pinned PDFs or add a reviewed source summary"
    )
    parser.add_argument(
        "--record", type=Path, help="Register one reviewed English JSON source record"
    )
    parser.add_argument(
        "--replace",
        action="store_true",
        help="Explicitly replace an existing source version",
    )
    args = parser.parse_args()
    if args.record:
        sys.path.insert(0, str(ROOT))
        from knowledge.catalog import add_record

        risks = json.loads((ROOT / "qa/knowledge/risk-library.json").read_text())
        try:
            result = add_record(
                ROOT / "qa/knowledge/corpus.json",
                args.record,
                {r["risk_key"] for r in risks["risks"]},
                replace=args.replace,
            )
        except (ValueError, TypeError, OSError) as exc:
            parser.error(str(exc))
        print(json.dumps(result))
        return
    if args.replace:
        parser.error("--replace requires --record")
    corpus = json.loads((ROOT / "qa/knowledge/corpus.json").read_text())
    notes = json.loads((ROOT / "qa/knowledge/literature.json").read_text())
    sources = {s["source_id"]: s for s in notes["sources"]}
    directory = ROOT / "artifacts/local-runs/knowledge/raw"
    directory.mkdir(parents=True, exist_ok=True)
    for doc in corpus["documents"]:
        if doc["content_kind"] != "PDF_TEXT":
            continue
        path = (directory / doc["file"]).resolve()
        if not path.is_relative_to(directory.resolve()):
            raise ValueError("Invalid corpus path")
        if (
            path.exists()
            and hashlib.sha256(path.read_bytes()).hexdigest() == doc["sha256"]
        ):
            print(doc["source_id"], "verified cached PDF", flush=True)
            continue
        source = sources[doc["source_id"]]
        if source["sha256"] != doc["sha256"]:
            raise ValueError("Source manifest hash mismatch")
        request = urllib.request.Request(
            source["download_url"],
            headers={"User-Agent": "AgentCrashLab research corpus"},
        )
        with urllib.request.urlopen(request, timeout=60) as response:
            data = response.read(25_000_001)
        if not data.startswith(b"%PDF-") or len(data) > 25_000_000:
            raise ValueError("Not a supported PDF")
        if hashlib.sha256(data).hexdigest() != doc["sha256"]:
            raise ValueError(
                "Publisher content changed; review before accepting a new source version"
            )
        temporary = path.with_suffix(".download")
        temporary.write_bytes(data)
        temporary.replace(path)
        print(doc["source_id"], "downloaded and verified", flush=True)


if __name__ == "__main__":
    main()
