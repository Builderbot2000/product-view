"""Spike, call 1 of 2: cut each review into its separate complaints.

Samples negative reviews, asks a local model (Ollama) for the complaints each
review contains, and caches the answers as JSONL keyed by review_id. This step
only cuts and rewrites; it does not filter. Run spike/llm_refine.py next to
apply the quality rules, then spike/llm_cluster.py to group the result.

    .venv/Scripts/python.exe -X utf8 spike/llm_extract.py --n 200 --recent
"""
from __future__ import annotations

import argparse
import json
import random
import sqlite3
import time
import urllib.request
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "llm-spike"
OLLAMA = "http://127.0.0.1:11434/api/chat"
PROMPT_VERSION = 4

SYSTEM = """You read Google Play reviews of a mobile banking app and cut each review into the separate complaints it contains. This is only the cutting step: a later step decides which complaints are worth keeping, so do not filter.

Rules:
- One entry per distinct complaint. A review can contain zero, one or several.
- Keep a complaint whole. If a cut piece would not make sense on its own (a cause without its effect, an error message without the action that triggered it), keep the pieces together as one entry. Never split one complaint into two.
- Never merge two unrelated complaints into one entry.
- Write each entry as a short neutral phrase (3-12 words) in your own words, e.g. "order tracking map does not update", "promo code rejected at checkout". Drop tone, insults and sarcasm; keep what the user says happened.
- Return an empty list only if the review contains no complaint at all.
- Pick the area that fits each complaint best from the list given.
- Write in English even if the review is not."""


def areas() -> dict[str, str]:
    cur = yaml.safe_load((ROOT / "curation.yaml").read_text(encoding="utf-8"))
    return {k: v["name"] for k, v in cur["areas"].items()} | {"other": "Other"}


def schema(area_ids: list[str]) -> dict:
    return {
        "type": "object",
        "properties": {
            "issues": {
                "type": "array",
                "items": {
                    "type": "object",
                    "properties": {
                        "problem": {"type": "string"},
                        "area": {"type": "string", "enum": area_ids},
                    },
                    "required": ["problem", "area"],
                },
            },
        },
        "required": ["issues"],
    }


def sample(n: int, seed: int, recent: bool = False) -> list[dict]:
    db = sqlite3.connect(ROOT / "data" / "reviews.db")
    db.execute("ATTACH ? AS cache", (str(ROOT / "data" / "cache.db"),))
    rows = db.execute(
        """SELECT r.review_id, COALESCE(t.content_en, r.content), r.score, r.created_at
           FROM reviews r LEFT JOIN cache.translations t USING (review_id)
           WHERE r.score <= 3 AND length(r.content) >= 20
           ORDER BY r.review_id"""
    ).fetchall()
    if recent:
        picked = sorted(rows, key=lambda r: r[3], reverse=True)[:n]
        return [dict(review_id=a, text=b, score=c, created_at=d) for a, b, c, d in picked]
    rng = random.Random(seed)
    incident = [r for r in rows if r[3].startswith("2024-10")]
    rest = [r for r in rows if not r[3].startswith("2024-10")]
    k = n // 3  # over-sample the October 2024 incident
    picked = rng.sample(incident, k) + rng.sample(rest, n - k)
    return [dict(review_id=a, text=b, score=c, created_at=d) for a, b, c, d in picked]


def extract(model: str, text: str, area_list: str, fmt: dict) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Areas:\n{area_list}\n\nReview:\n{text}"},
        ],
        "format": fmt,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "seed": 0},
    }
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(json.loads(resp.read())["message"]["content"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--n", type=int, default=300)
    ap.add_argument("--seed", type=int, default=7)
    ap.add_argument("--model", default="qwen3.5:9b")
    ap.add_argument("--recent", action="store_true", help="newest N reviews instead of a random sample")
    args = ap.parse_args()

    names = areas()
    area_list = "\n".join(f"- {k}: {v}" for k, v in names.items())
    fmt = schema(list(names))
    OUT.mkdir(parents=True, exist_ok=True)
    tag = "-recent" if args.recent else ""
    path = OUT / f"extract-{args.model.replace(':', '_')}-v{PROMPT_VERSION}{tag}.jsonl"
    done = set()
    if path.exists():
        done = {json.loads(line)["review_id"] for line in path.open(encoding="utf-8")}

    todo = [r for r in sample(args.n, args.seed, args.recent) if r["review_id"] not in done]
    print(f"{len(done)} cached, {len(todo)} to extract with {args.model}")
    t0 = time.time()
    with path.open("a", encoding="utf-8") as f:
        for i, r in enumerate(todo, 1):
            r["extraction"] = extract(args.model, r["text"], area_list, fmt)
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
            if i % 25 == 0 or i == len(todo):
                print(f"  {i}/{len(todo)}  {(time.time() - t0) / i:.2f}s/review")


if __name__ == "__main__":
    main()
