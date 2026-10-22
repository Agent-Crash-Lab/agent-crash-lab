"""Pinned official BGE ONNX: CLS pooling, unit normalization, query instruction."""

import hashlib
import os
import threading
import urllib.request
from collections import OrderedDict
from pathlib import Path

import numpy as np
import onnxruntime as ort
from tokenizers import Tokenizer

MODEL = "BAAI/bge-small-en-v1.5"
REVISION = "5c38ec7c405ec4b44b94cc5a9bb96e735b38267a"
DIMENSION = 384
INSTRUCTION = "Represent this sentence for searching relevant passages: "


class Embedder:
    def __init__(self):
        directory = Path(os.environ.get("MODEL_DIR", "/models")) / REVISION
        directory.mkdir(parents=True, exist_ok=True)
        for filename in ("tokenizer.json", "onnx/model.onnx", "README.md"):
            target = directory / filename
            if not target.is_file():
                target.parent.mkdir(parents=True, exist_ok=True)
                url = f"https://huggingface.co/{MODEL}/resolve/{REVISION}/{filename}"
                temporary = target.with_suffix(target.suffix + ".download")
                with (
                    urllib.request.urlopen(url, timeout=90) as response,
                    temporary.open("wb") as out,
                ):
                    while block := response.read(1024 * 1024):
                        out.write(block)
                temporary.replace(target)
        self.model_sha256 = hashlib.sha256(
            (directory / "onnx/model.onnx").read_bytes()
        ).hexdigest()
        self.splitter = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer = Tokenizer.from_file(str(directory / "tokenizer.json"))
        self.tokenizer.enable_truncation(max_length=512)
        self.tokenizer.enable_padding(pad_id=0, pad_token="[PAD]")
        options = ort.SessionOptions()
        options.intra_op_num_threads = int(os.environ.get("EMBEDDING_THREADS", "2"))
        options.inter_op_num_threads = 1
        self.session = ort.InferenceSession(
            str(directory / "onnx/model.onnx"),
            sess_options=options,
            providers=["CPUExecutionProvider"],
        )
        self.lock = threading.Lock()
        self.query_cache = OrderedDict()

    def encode(self, texts, query=False):
        with self.lock:
            key = texts[0] if query and len(texts) == 1 else None
            if key in self.query_cache:
                self.query_cache.move_to_end(key)
                return self.query_cache[key]
            encoded = self.tokenizer.encode_batch(
                [INSTRUCTION + t if query else t for t in texts]
            )
            available = {
                "input_ids": [e.ids for e in encoded],
                "attention_mask": [e.attention_mask for e in encoded],
                "token_type_ids": [e.type_ids for e in encoded],
            }
            inputs = {
                item.name: np.asarray(available[item.name], dtype=np.int64)
                for item in self.session.get_inputs()
            }
            output = self.session.run(None, inputs)[0]
            vectors = output[:, 0, :] if output.ndim == 3 else output
            if vectors.shape[1] != DIMENSION:
                raise ValueError("Unexpected embedding dimension")
            normalized = vectors / np.maximum(
                np.linalg.norm(vectors, axis=1, keepdims=True), 1e-12
            )
            if key is not None:
                normalized.setflags(write=False)
                self.query_cache[key] = normalized
                if len(self.query_cache) > 128:
                    self.query_cache.popitem(last=False)
            return normalized


def windows(text, tokenizer, size, overlap=0):
    """Use tokenizer offsets so returned passages remain exact substrings of the source."""
    offsets = tokenizer.encode(text, add_special_tokens=False).offsets
    if not 0 <= overlap < size:
        raise ValueError("Invalid token overlap")
    for start in range(0, len(offsets), size - overlap):
        end = min(start + size, len(offsets))
        yield text[offsets[start][0] : offsets[end - 1][1]]
        if end == len(offsets):
            break


if __name__ == "__main__":
    model = Embedder()
    print(
        {
            "model": MODEL,
            "revision": REVISION,
            "dimension": DIMENSION,
            "sha256": model.model_sha256,
        }
    )
