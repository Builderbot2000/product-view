"""One door to the language model, whichever provider is behind it.

Every step of the issue stage calls `LLM.chat(system, user, schema, tier)` and
gets back a dict that matches `schema`. Which model answers is configuration
(`llm:` in config.yaml), so moving from the local model to an API model is a
config change, not a code change.

- `ollama`: a local model served by Ollama (no key; review text stays on the
  machine). Calls run one at a time: a laptop GPU gains nothing from more.
- `openai`: the OpenAI Chat Completions API with structured outputs. The key
  comes from OPENAI_API_KEY (environment or `.env`), never from config.
  Calls run in parallel up to `max_workers`.

Two tiers, as in LLooM: `fast` for the high-volume calls (distill, score,
breadth, area) and `strong` for writing concepts (synthesize).

Every answer is cached in cache.db by its full request (model, prompts,
schema), so an interrupted run resumes where it stopped and a repeated run is
free. Changing the model or a prompt simply misses the cache.
"""

from __future__ import annotations

import hashlib
import json
import logging
import os
import sqlite3
import threading
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

ENV_OPENAI_KEY = "OPENAI_API_KEY"
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}


class LLMError(RuntimeError):
    pass


def obj(props: dict) -> dict:
    """A strict JSON-schema object: every property required, nothing extra.
    OpenAI's strict structured outputs require exactly this shape."""
    return {"type": "object", "properties": props, "required": list(props),
            "additionalProperties": False}


def arr(item: dict) -> dict:
    return {"type": "array", "items": item}


def enum(*values: str) -> dict:
    return {"type": "string", "enum": list(values)}


@dataclass
class LLMConfig:
    provider: str = "ollama"                 # ollama | openai
    fast: str = "qwen3.5:9b"
    strong: str = "qwen3.5:9b"
    base_url: str | None = None              # None: the provider's default
    max_workers: int = 1
    temperature: float | None = 0.0          # None: leave it out (some API models only take the default)
    seed: int | None = 0
    timeout: float = 600.0
    retries: int = 5
    options: dict = field(default_factory=dict)   # extra request fields, passed through as given

    @classmethod
    def from_config(cls, section: dict) -> "LLMConfig":
        models = section.get("models") or {}
        return cls(
            provider=section["provider"],
            fast=models.get("fast"),
            strong=models.get("strong") or models.get("fast"),
            base_url=section.get("base_url"),
            max_workers=int(section.get("max_workers") or 1),
            temperature=section.get("temperature"),
            seed=section.get("seed"),
            timeout=float(section.get("timeout") or 600),
            retries=int(section.get("retries") or 5),
            options=dict(section.get("options") or {}),
        )


class LLM:
    def __init__(self, cfg: LLMConfig, cache_path: Path) -> None:
        if cfg.provider not in ("ollama", "openai"):
            raise LLMError(f"unknown llm.provider {cfg.provider!r} (expected ollama or openai)")
        if not cfg.fast:
            raise LLMError("llm.models.fast is not set")
        self.cfg = cfg
        self._lock = threading.Lock()
        self._db = sqlite3.connect(cache_path, check_same_thread=False)
        self._db.execute("PRAGMA journal_mode=WAL")
        self._db.execute("CREATE TABLE IF NOT EXISTS llm_calls ("
                         "key TEXT PRIMARY KEY, model TEXT, out TEXT, at TEXT)")
        self._db.commit()
        self.calls = self.hits = 0
        self.seconds = 0.0
        if cfg.provider == "openai":
            from ..publish.confluence import load_dotenv

            load_dotenv()
            self._key = os.environ.get(ENV_OPENAI_KEY)
            self._url = (cfg.base_url or "https://api.openai.com/v1").rstrip("/") + "/chat/completions"
        else:
            self._key = None
            self._url = (cfg.base_url or "http://127.0.0.1:11434").rstrip("/") + "/api/chat"

    def model(self, tier: str) -> str:
        return self.cfg.strong if tier == "strong" else self.cfg.fast

    def describe(self) -> str:
        same = self.cfg.fast == self.cfg.strong
        return (f"{self.cfg.provider}: {self.cfg.fast}"
                + ("" if same else f" (fast) + {self.cfg.strong} (strong)"))

    def check(self) -> None:
        """Fail early, before a long run, when the provider can't be used."""
        if self.cfg.provider == "openai" and not self._key:
            raise LLMError(f"llm.provider is openai but {ENV_OPENAI_KEY} is not set "
                           "(set it in the environment or in .env)")

    # --- calls ---------------------------------------------------------------

    def chat(self, system: str, user: str, schema: dict, tier: str = "fast") -> dict:
        model = self.model(tier)
        key = hashlib.sha256(json.dumps([self.cfg.provider, model, system, user, schema],
                                        sort_keys=True).encode()).hexdigest()
        with self._lock:
            row = self._db.execute("SELECT out FROM llm_calls WHERE key = ?", (key,)).fetchone()
        if row:
            self.hits += 1
            return json.loads(row[0])
        t0 = time.time()
        out = self._request(model, system, user, schema)
        with self._lock:
            self.seconds += time.time() - t0
            self.calls += 1
            self._db.execute("INSERT OR REPLACE INTO llm_calls VALUES (?,?,?,datetime('now'))",
                             (key, model, json.dumps(out, ensure_ascii=False)))
            self._db.commit()
        return out

    def map(self, fn: Callable[[T], R], items: Iterable[T], label: str = "",
            every: int = 50) -> list[R]:
        """fn over items, in parallel up to max_workers; results in input order."""
        items = list(items)
        done = 0
        t0 = time.time()

        def run(item: T) -> R:
            nonlocal done
            out = fn(item)
            with self._lock:
                done += 1
                if label and (done % every == 0 or done == len(items)):
                    print(f"    {label} {done}/{len(items)}  {time.time() - t0:.0f}s", flush=True)
            return out

        if self.cfg.max_workers <= 1:
            return [run(i) for i in items]
        with ThreadPoolExecutor(self.cfg.max_workers) as pool:
            return list(pool.map(run, items))

    def _request(self, model: str, system: str, user: str, schema: dict) -> dict:
        messages = [{"role": "system", "content": system}, {"role": "user", "content": user}]
        if self.cfg.provider == "ollama":
            options = {k: v for k, v in (("temperature", self.cfg.temperature),
                                         ("seed", self.cfg.seed)) if v is not None}
            body: dict[str, Any] = {"model": model, "messages": messages, "format": schema,
                                    "stream": False, "think": False, "options": options}
            headers = {"Content-Type": "application/json"}
        else:
            body = {"model": model, "messages": messages,
                    "response_format": {"type": "json_schema",
                                        "json_schema": {"name": "answer", "schema": schema,
                                                        "strict": True}}}
            if self.cfg.temperature is not None:
                body["temperature"] = self.cfg.temperature
            if self.cfg.seed is not None:
                body["seed"] = self.cfg.seed
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"}
        body.update(self.cfg.options)

        for attempt in range(self.cfg.retries + 1):
            req = urllib.request.Request(self._url, json.dumps(body).encode(), headers)
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                    data = json.loads(resp.read())
                text = (data["message"]["content"] if self.cfg.provider == "ollama"
                        else data["choices"][0]["message"]["content"])
                return json.loads(text)
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                if exc.code not in RETRY_STATUS or attempt == self.cfg.retries:
                    raise LLMError(f"{self.cfg.provider} {model}: HTTP {exc.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt == self.cfg.retries:
                    raise LLMError(f"{self.cfg.provider} {model}: {exc} ({self._url})") from None
            except (KeyError, IndexError, json.JSONDecodeError) as exc:
                # A reply that doesn't parse: retried, since sampling may differ next time.
                if attempt == self.cfg.retries:
                    raise LLMError(f"{self.cfg.provider} {model}: unreadable reply ({exc})") from None
            wait = min(60, 2 ** attempt)
            log.warning("llm call failed (attempt %d), retrying in %ds", attempt + 1, wait)
            time.sleep(wait)
        raise AssertionError("unreachable")

    def close(self) -> None:
        self._db.close()
