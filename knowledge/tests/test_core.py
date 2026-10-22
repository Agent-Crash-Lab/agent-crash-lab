import hashlib
import json
import re
import tempfile
import threading
import unittest
from collections import OrderedDict
from pathlib import Path
from types import SimpleNamespace

import numpy as np

from knowledge.catalog import add_record
from knowledge.embedding import Embedder, windows
from knowledge.index import prepare


class Words:
    def encode(self, text, **kwargs):
        return SimpleNamespace(offsets=[m.span() for m in re.finditer(r"\S+", text)])


class ChunkTests(unittest.TestCase):
    def test_same_query_reuses_embedding_but_document_embedding_stays_separate(self):
        model = object.__new__(Embedder)
        model.lock, model.query_cache = threading.Lock(), OrderedDict()
        calls = []
        model.tokenizer = SimpleNamespace(
            encode_batch=lambda texts: [
                SimpleNamespace(ids=[1], attention_mask=[1], type_ids=[0])
                for _ in texts
            ]
        )

        def infer(names, values):
            calls.append(values)
            return [np.ones((len(values["input_ids"]), 384))]

        model.session = SimpleNamespace(
            get_inputs=lambda: [SimpleNamespace(name="input_ids")], run=infer
        )
        first = model.encode(["machine availability"], query=True)
        again = model.encode(["machine availability"], query=True)
        self.assertEqual(len(calls), 1)
        self.assertIs(first, again)
        self.assertFalse(first.flags.writeable)
        model.encode(["machine availability"], query=False)
        self.assertEqual(len(calls), 2)

    def test_child_windows_preserve_source_text_and_overlap(self):
        text = "one two three four five six seven"
        self.assertEqual(
            list(windows(text, Words(), 4, 1)),
            ["one two three four", "four five six seven"],
        )
        with self.assertRaises(ValueError):
            list(windows(text, Words(), 4, 4))

    def test_children_remain_inside_their_identified_parent(self):
        source = {
            "source_id": "S",
            "content_kind": "CURATED_SUMMARY",
            "text_en": " ".join(f"word{i}" for i in range(1200)),
        }
        _, parents, children = prepare(
            {"documents": [source]}, Path("/unused"), Words()
        )
        mapping = {p[0]: p for p in parents}
        self.assertEqual(len(parents), 2)
        self.assertGreater(len(children), len(parents))
        self.assertTrue(all(c[2] in mapping[c[1]][3] for c in children))
        self.assertTrue(all(p[2] == 0 for p in parents))
        self.assertEqual(
            prepare({"documents": [source]}, Path("/unused"), Words())[1:],
            (parents, children),
        )

    def test_import_does_not_allow_paths_outside_the_corpus(self):
        source = {
            "source_id": "BAD",
            "content_kind": "PDF_TEXT",
            "file": "../private.pdf",
        }
        with self.assertRaisesRegex(ValueError, "escapes"):
            prepare({"documents": [source]}, Path("/corpus"), Words())

    def test_registered_source_is_idempotent_hash_checked_and_ready_for_chunking(self):
        record = {
            "source_id": "TEAM-REPORT",
            "title": "Reviewed manufacturing source",
            "url": "https://example.org/report",
            "attribution": "Test publisher",
            "source_version": "v1",
            "source_locator": "Section 2",
            "scope": "Synthetic test",
            "source_facts_en": "Factory resources are finite.",
            "qa_transfer_en": "Test overlap.",
            "text_en": "Finite manufacturing resources motivate a scheduling overlap test.",
            "content_kind": "CURATED_SUMMARY",
            "source_type": "TECHNICAL",
            "evidence_domains": ["MANUFACTURING"],
            "roles": ["PRODUCTION"],
            "risk_types": ["RESOURCE_CONSTRAINT"],
            "mapping_review": "TEAM_REVIEWED",
            "rights": {"license": "SELF_WRITTEN_SUMMARY_OF_LINKED_SOURCE"},
        }
        with tempfile.TemporaryDirectory() as directory:
            manifest, source = (
                Path(directory) / "corpus.json",
                Path(directory) / "record.json",
            )
            manifest.write_text('{"documents": []}')
            source.write_text(json.dumps(record))
            self.assertEqual(
                add_record(manifest, source, {"RESOURCE_CONSTRAINT"})["status"],
                "REGISTERED",
            )
            before = manifest.read_bytes()
            self.assertEqual(
                add_record(manifest, source, {"RESOURCE_CONSTRAINT"})["status"],
                "UNCHANGED",
            )
            documents, parents, children = prepare(
                json.loads(before), Path(directory), Words()
            )
            self.assertEqual(
                documents[0]["sha256"],
                hashlib.sha256(record["text_en"].encode()).hexdigest(),
            )
            self.assertTrue(parents and children)
            for mutation in (
                {"mapping_review": "DRAFT"},
                {"source_type": "PROJECT_POLICY"},
                {"sha256": "incorrect"},
                {"risk_types": ["INVENTED_RISK"]},
            ):
                source.write_text(json.dumps({**record, **mutation}))
                with self.assertRaises(ValueError):
                    add_record(manifest, source, {"RESOURCE_CONSTRAINT"}, replace=True)
                self.assertEqual(manifest.read_bytes(), before)


if __name__ == "__main__":
    unittest.main()
