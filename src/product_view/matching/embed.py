"""Embeddings for matching, cached in cache.db by (model, instruction, text).

Two models, both run in the container by default (`embed.backend: local`),
because the method's thresholds are calibrated to them:

- all-MiniLM-L6-v2 splits reviews into units (units.py).
- Qwen3-Embedding-0.6B with a fixed instruction places units and topic
  examples for the classifier. A different embedding model would silently
  move every threshold, so it is not configurable.

`embed.backend: ollama` asks an Ollama server for the same Qwen3 model
instead (`qwen3-embedding:0.6b`, much faster on a GPU). Its vectors agree with
the CPU build to a cosine of 0.9997, so both share one cache. MiniLM always
runs locally: it is small and fast.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import urllib.request
from functools import lru_cache
from pathlib import Path

import numpy as np

log = logging.getLogger(__name__)

QWEN = "Qwen/Qwen3-Embedding-0.6B"
QWEN_OLLAMA = "qwen3-embedding:0.6b"
MINILM = "all-MiniLM-L6-v2"
BACKENDS = ("local", "ollama")


class EmbedError(RuntimeError):
    pass


@lru_cache(maxsize=2)
def _model(name: str):
    from sentence_transformers import SentenceTransformer

    # The Hugging Face cache, so HF_HOME / XDG_CACHE_HOME place it and HF_ENDPOINT
    # can point an air-gapped host at an in-house mirror.
    log.info("loading %s (the first run downloads it)", name)
    return SentenceTransformer(name, device="cpu")


class Embedder:
    def __init__(self, cache_path: Path, backend: str = "local", base_url: str | None = None,
                 timeout: float = 600.0) -> None:
        if backend not in BACKENDS:
            raise EmbedError(f"unknown embed.backend {backend!r} (expected one of {BACKENDS})")
        self.backend = backend
        host = os.environ.get("OLLAMA_HOST", "127.0.0.1:11434")
        self.base_url = (base_url or (host if "://" in host else f"http://{host}")).rstrip("/")
        self.timeout = timeout
        self.computed = 0
        self._db = sqlite3.connect(cache_path)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS vectors (key TEXT PRIMARY KEY, vector BLOB)")
        self._db.commit()

    def close(self) -> None:
        self._db.close()

    def describe(self) -> str:
        return QWEN + (f" via Ollama at {self.base_url}" if self.backend == "ollama" else " (local)")

    def minilm(self, texts: list[str]) -> np.ndarray:
        return self._cached(MINILM, "", texts, self._minilm)

    def qwen(self, texts: list[str], instruction: str) -> np.ndarray:
        fn = self._qwen_ollama if self.backend == "ollama" else self._qwen_local
        return self._cached(QWEN, instruction, texts, lambda t: fn(t, instruction))

    # --- backends ------------------------------------------------------------

    @staticmethod
    def _minilm(texts: list[str]) -> np.ndarray:
        return _model(f"sentence-transformers/{MINILM}").encode(
            texts, batch_size=256, convert_to_numpy=True, normalize_embeddings=True,
            show_progress_bar=False)

    @staticmethod
    def _qwen_local(texts: list[str], instruction: str) -> np.ndarray:
        return _model(QWEN).encode(texts, prompt=f"Instruct: {instruction}\nQuery: ", batch_size=16,
                                   convert_to_numpy=True, normalize_embeddings=True,
                                   show_progress_bar=False)

    def _qwen_ollama(self, texts: list[str], instruction: str) -> np.ndarray:
        out = []
        for i in range(0, len(texts), 64):
            body = json.dumps({"model": QWEN_OLLAMA, "input": [
                f"Instruct: {instruction}\nQuery: {t}" for t in texts[i:i + 64]]}).encode()
            req = urllib.request.Request(f"{self.base_url}/api/embed", body,
                                         {"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=self.timeout) as resp:
                    out.append(np.array(json.load(resp)["embeddings"], dtype=np.float32))
            except (OSError, KeyError, ValueError) as exc:
                raise EmbedError(f"ollama embeddings at {self.base_url}: {exc}") from None
        v = np.vstack(out)
        return v / np.linalg.norm(v, axis=1, keepdims=True)

    # --- cache ---------------------------------------------------------------

    def _cached(self, model: str, instruction: str, texts: list[str], fn) -> np.ndarray:
        if not texts:
            return np.zeros((0, 0), dtype=np.float32)
        tag = f"{model}|{instruction}|"
        keys = [hashlib.sha1((tag + t).encode("utf-8")).hexdigest() for t in texts]
        have: dict[str, np.ndarray] = {}
        uniq = list(dict.fromkeys(keys))
        for i in range(0, len(uniq), 900):
            chunk = uniq[i:i + 900]
            for k, blob in self._db.execute(
                    f"SELECT key, vector FROM vectors WHERE key IN ({','.join('?' * len(chunk))})",
                    chunk):
                have[k] = np.frombuffer(blob, dtype=np.float32)
        todo = {k: t for k, t in zip(keys, texts) if k not in have}
        if todo:
            # Shortest first, as the trials embedded: batches of similar length pad less.
            order = sorted(todo, key=lambda k: len(todo[k]))
            vecs = np.asarray(fn([todo[k] for k in order]), dtype=np.float32)
            with self._db:
                self._db.executemany("INSERT OR REPLACE INTO vectors VALUES (?, ?)",
                                     [(k, v.tobytes()) for k, v in zip(order, vecs)])
            have.update(zip(order, vecs))
            self.computed += len(order)
        return np.ascontiguousarray(np.stack([have[k] for k in keys]), dtype=np.float32)
