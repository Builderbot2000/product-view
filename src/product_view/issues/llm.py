"""One door to the language model, whichever provider is behind it.

Every step of the issue stage calls `LLM.chat(system, user, schema, tier)`, or
`LLM.run([Req, ...])` for many calls at once, and gets back dicts that match
`schema`. Which model answers is configuration (`llm:` in config.yaml), so
moving from the local model to an API model is a config change, not a code
change.

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

Cost control:
- `batch: true` (openai) sends the uncached requests of each `run` through
  the Batch API: half price, answers within 24 hours. They land in the same
  cache; a request the batch fails is retried live.
- Tokens are counted from every reply. With `prices` (USD per 1M tokens, per
  model) the spend is known, and `budget_usd` stops the run before a call or
  a wave of batch jobs that would start past it. A stopped run resumes from
  the cache.
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
import uuid
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Iterable, NamedTuple, TypeVar

log = logging.getLogger(__name__)

T = TypeVar("T")
R = TypeVar("R")

ENV_OPENAI_KEY = "OPENAI_API_KEY"
OPENAI_URL = "https://api.openai.com/v1"
RETRY_STATUS = {408, 409, 429, 500, 502, 503, 504}
BATCH_DISCOUNT = 0.5           # the Batch API's price, as a share of the live price
BATCH_DONE = {"completed", "failed", "expired", "cancelled"}


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


class Req(NamedTuple):
    """One model call, as `LLM.run` takes it."""
    system: str
    user: str
    schema: dict
    tier: str = "fast"


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
    batch: bool = False                      # openai: uncached requests go through the Batch API
    batch_requests: int = 10000              # requests per batch job
    batch_jobs: int = 4                      # batch jobs in flight at once
    poll_seconds: float = 30.0
    prices: dict = field(default_factory=dict)   # model -> (input, output) USD per 1M tokens
    budget_usd: float | None = None          # stop before spending past this

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
            batch=bool(section.get("batch")),
            batch_requests=int(section.get("batch_requests") or 10000),
            batch_jobs=int(section.get("batch_jobs") or 4),
            poll_seconds=float(section.get("poll_seconds") or 30),
            prices={m: tuple(float(x) for x in v) for m, v in (section.get("prices") or {}).items()},
            budget_usd=section.get("budget_usd"),
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
        self.tokens_in = self.tokens_out = 0
        self.spent = 0.0          # USD at the configured prices
        if cfg.provider == "openai":
            from ..publish.confluence import load_dotenv

            load_dotenv()
            self._key = os.environ.get(ENV_OPENAI_KEY)
            self._base = (cfg.base_url or OPENAI_URL).rstrip("/")
            self._url = self._base + "/chat/completions"
        else:
            self._key = None
            self._url = (cfg.base_url or "http://127.0.0.1:11434").rstrip("/") + "/api/chat"

    def model(self, tier: str) -> str:
        return self.cfg.strong if tier == "strong" else self.cfg.fast

    @property
    def batching(self) -> bool:
        return self.cfg.batch and self.cfg.provider == "openai"

    def describe(self) -> str:
        same = self.cfg.fast == self.cfg.strong
        return (f"{self.cfg.provider}: {self.cfg.fast}"
                + ("" if same else f" (fast) + {self.cfg.strong} (strong)")
                + (", batch API" if self.batching else ""))

    def check(self) -> None:
        """Fail early, before a long run, when the provider can't be used."""
        if self.cfg.provider == "openai" and not self._key:
            raise LLMError(f"llm.provider is openai but {ENV_OPENAI_KEY} is not set "
                           "(set it in the environment or in .env)")
        missing = sorted({self.cfg.fast, self.cfg.strong} - set(self.cfg.prices))
        if self.cfg.budget_usd is not None and self.cfg.provider == "openai" and missing:
            raise LLMError(f"llm.budget_usd is set but llm.prices has no price for {', '.join(missing)}")

    # --- spend ---------------------------------------------------------------

    def cost(self, model: str, tokens_in: float, tokens_out: float, batch: bool | None = None) -> float:
        """USD at the configured prices; batch defaults to whether batching is on."""
        p_in, p_out = self.cfg.prices.get(model, (0.0, 0.0))
        batch = self.batching if batch is None else batch
        return (tokens_in * p_in + tokens_out * p_out) / 1e6 * (BATCH_DISCOUNT if batch else 1.0)

    def _charge(self, model: str, usage: dict, batch: bool = False) -> None:
        t_in, t_out = int(usage.get("in") or 0), int(usage.get("out") or 0)
        with self._lock:
            self.tokens_in += t_in
            self.tokens_out += t_out
            self.spent += self.cost(model, t_in, t_out, batch)

    def _within_budget(self) -> None:
        if self.cfg.budget_usd is not None and self.spent >= self.cfg.budget_usd:
            raise LLMError(f"budget reached: ${self.spent:.2f} spent of llm.budget_usd "
                           f"${self.cfg.budget_usd:.2f}. The answers so far are cached: raise "
                           "the budget and run again to continue")

    def spend(self) -> str:
        out = f"{self.tokens_in:,} tokens in, {self.tokens_out:,} out"
        if self.cfg.prices:
            out += f", ${self.spent:.2f}"
            if self.cfg.budget_usd is not None:
                out += f" of a ${self.cfg.budget_usd:.2f} budget"
        return out

    # --- calls ---------------------------------------------------------------

    def _key_of(self, model: str, system: str, user: str, schema: dict) -> str:
        # Request options (reasoning effort, ...) change the answer, so they are part of
        # the key; left out when empty, so keys from before they were added still match.
        parts = [self.cfg.provider, model, system, user, schema]
        if self.cfg.options:
            parts.append(self.cfg.options)
        return hashlib.sha256(json.dumps(parts, sort_keys=True).encode()).hexdigest()

    def _cached(self, key: str) -> dict | None:
        with self._lock:
            row = self._db.execute("SELECT out FROM llm_calls WHERE key = ?", (key,)).fetchone()
        return json.loads(row[0]) if row else None

    def _store(self, key: str, model: str, out: dict) -> None:
        with self._lock:
            self._db.execute("INSERT OR REPLACE INTO llm_calls VALUES (?,?,?,datetime('now'))",
                             (key, model, json.dumps(out, ensure_ascii=False)))
            self._db.commit()

    def chat(self, system: str, user: str, schema: dict, tier: str = "fast") -> dict:
        model = self.model(tier)
        key = self._key_of(model, system, user, schema)
        if (out := self._cached(key)) is not None:
            with self._lock:
                self.hits += 1
            return out
        self._within_budget()
        t0 = time.time()
        out, usage = self._request(model, system, user, schema)
        self._charge(model, usage)
        with self._lock:
            self.seconds += time.time() - t0
            self.calls += 1
        self._store(key, model, out)
        return out

    def run(self, reqs: list[Req], label: str = "", every: int = 200) -> list[dict]:
        """Many calls, answers in input order. With batching on, the uncached ones go
        through the Batch API first, so the calls below are answered from the cache."""
        if self.batching:
            self._batch(reqs, label)
        return self.map(lambda r: self.chat(*r), reqs, label=label, every=every)

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

    def _openai_body(self, model: str, system: str, user: str, schema: dict) -> dict:
        body: dict[str, Any] = {
            "model": model,
            "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}],
            "response_format": {"type": "json_schema",
                                "json_schema": {"name": "answer", "schema": schema, "strict": True}},
        }
        if self.cfg.temperature is not None:
            body["temperature"] = self.cfg.temperature
        if self.cfg.seed is not None:
            body["seed"] = self.cfg.seed
        body.update(self.cfg.options)
        return body

    def _request(self, model: str, system: str, user: str, schema: dict) -> tuple[dict, dict]:
        """One live call: (answer, {"in": tokens, "out": tokens})."""
        if self.cfg.provider == "ollama":
            options = {k: v for k, v in (("temperature", self.cfg.temperature),
                                         ("seed", self.cfg.seed)) if v is not None}
            body: dict[str, Any] = {
                "model": model, "format": schema, "stream": False, "think": False, "options": options,
                "messages": [{"role": "system", "content": system}, {"role": "user", "content": user}]}
            body.update(self.cfg.options)
            headers = {"Content-Type": "application/json"}
        else:
            body = self._openai_body(model, system, user, schema)
            headers = {"Content-Type": "application/json", "Authorization": f"Bearer {self._key}"}

        for attempt in range(self.cfg.retries + 1):
            req = urllib.request.Request(self._url, json.dumps(body).encode(), headers)
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                    data = json.loads(resp.read())
                if self.cfg.provider == "ollama":
                    text = data["message"]["content"]
                    usage = {"in": data.get("prompt_eval_count"), "out": data.get("eval_count")}
                else:
                    text = data["choices"][0]["message"]["content"]
                    u = data.get("usage") or {}
                    usage = {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens")}
                return json.loads(text), usage
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

    # --- Batch API (openai) ----------------------------------------------------

    def _api(self, method: str, path: str, body: bytes | None = None,
             content_type: str = "application/json") -> bytes:
        headers = {"Authorization": f"Bearer {self._key}", "Content-Type": content_type}
        for attempt in range(self.cfg.retries + 1):
            req = urllib.request.Request(self._base + path, body, headers, method=method)
            try:
                with urllib.request.urlopen(req, timeout=self.cfg.timeout) as resp:
                    return resp.read()
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", "replace")[:300]
                if exc.code not in RETRY_STATUS or attempt == self.cfg.retries:
                    raise LLMError(f"openai {method} {path}: HTTP {exc.code}: {detail}") from None
            except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
                if attempt == self.cfg.retries:
                    raise LLMError(f"openai {method} {path}: {exc}") from None
            time.sleep(min(60, 2 ** attempt))
        raise AssertionError("unreachable")

    def _upload(self, lines: list[dict]) -> str:
        """A JSONL file of requests, uploaded for the Batch API; returns its file id."""
        boundary = f"pv{uuid.uuid4().hex}"
        jsonl = "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in lines).encode()
        head = (f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="purpose"\r\n\r\nbatch\r\n'
                f"--{boundary}\r\n"
                'Content-Disposition: form-data; name="file"; filename="requests.jsonl"\r\n'
                "Content-Type: application/jsonl\r\n\r\n").encode()
        body = head + jsonl + f"\r\n--{boundary}--\r\n".encode()
        return json.loads(self._api("POST", "/files", body,
                                    f"multipart/form-data; boundary={boundary}"))["id"]

    def _batch(self, reqs: list[Req], label: str) -> None:
        """Answer every uncached request through the Batch API, into the cache."""
        todo: dict[str, tuple[str, dict]] = {}
        for r in reqs:
            model = self.model(r.tier)
            key = self._key_of(model, r.system, r.user, r.schema)
            if key not in todo and self._cached(key) is None:
                todo[key] = (model, self._openai_body(model, r.system, r.user, r.schema))
        if not todo:
            return
        lines = [{"custom_id": k, "method": "POST", "url": "/v1/chat/completions", "body": b}
                 for k, (_, b) in todo.items()]
        size = self.cfg.batch_requests
        chunks = [lines[i:i + size] for i in range(0, len(lines), size)]
        print(f"    {label or 'batch'}: {len(lines)} requests in {len(chunks)} batch job(s)", flush=True)
        # In waves of batch_jobs, so the budget is checked between them.
        for w in range(0, len(chunks), self.cfg.batch_jobs):
            self._within_budget()
            pending = set()
            for chunk in chunks[w:w + self.cfg.batch_jobs]:
                job = json.loads(self._api("POST", "/batches", json.dumps(
                    {"input_file_id": self._upload(chunk), "endpoint": "/v1/chat/completions",
                     "completion_window": "24h"}).encode()))
                pending.add(job["id"])
            t0 = time.time()
            while pending:
                time.sleep(self.cfg.poll_seconds)
                for jid in sorted(pending):
                    job = json.loads(self._api("GET", f"/batches/{jid}"))
                    n = job.get("request_counts") or {}
                    print(f"    batch {jid}: {job['status']} {n.get('completed', 0)}/{n.get('total', '?')}"
                          f"  {time.time() - t0:.0f}s", flush=True)
                    if job["status"] in BATCH_DONE:
                        pending.discard(jid)
                        self._collect(job, todo)

    def _collect(self, job: dict, todo: dict[str, tuple[str, dict]]) -> None:
        """Cache a finished job's answers. A failed request is left out: run() retries it live."""
        failed = 0
        if job.get("output_file_id"):
            raw = self._api("GET", f"/files/{job['output_file_id']}/content").decode("utf-8")
            for line in raw.splitlines():
                if not line.strip():
                    continue
                row = json.loads(line)
                key, resp = row["custom_id"], row.get("response") or {}
                try:
                    if resp.get("status_code") != 200:
                        raise KeyError("status_code")
                    data = resp["body"]
                    out = json.loads(data["choices"][0]["message"]["content"])
                except (KeyError, IndexError, TypeError, json.JSONDecodeError):
                    failed += 1
                    continue
                model = todo[key][0]
                u = data.get("usage") or {}
                self._charge(model, {"in": u.get("prompt_tokens"), "out": u.get("completion_tokens")},
                             batch=True)
                with self._lock:
                    self.calls += 1
                self._store(key, model, out)
        failed += int((job.get("request_counts") or {}).get("failed") or 0)
        if failed or job["status"] != "completed":
            log.warning("batch %s %s: %d request(s) failed; they will be retried live",
                        job["id"], job["status"], failed)

    def close(self) -> None:
        self._db.close()
