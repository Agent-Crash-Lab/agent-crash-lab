import re
import unittest
from pathlib import Path
from types import SimpleNamespace

from knowledge.embedding import windows
from knowledge.index import prepare


class Words:
    def encode(self, text, **kwargs):
        return SimpleNamespace(offsets=[m.span() for m in re.finditer(r"\S+", text)])


class ChunkTests(unittest.TestCase):
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


if __name__ == "__main__":
    unittest.main()
