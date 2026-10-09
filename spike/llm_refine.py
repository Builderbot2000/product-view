"""Spike: apply the quality rules to extracted problems, one statement per call.

llm_extract.py only cuts and rewrites. This step judges each statement on its
own, so the model never juggles cutting and filtering at once. For each
statement it sees the review and that one statement, and states the feature
the statement is about and what goes wrong with it. A statement missing either
is dropped to "no specific problem"; that decision is made here in code from
the two fields, not by the model.

    .venv/Scripts/python.exe -X utf8 spike/llm_refine.py out/llm-spike/extract-qwen3.5_9b-v4-recent.jsonl

Writes <input>-refined-v<RULES_VERSION>.jsonl, same shape as the input, with
`issues` holding only kept statements (plus `feature`/`failure`) and `dropped`
holding the rest.
"""
from __future__ import annotations

import argparse
import json
import time
import urllib.request
from pathlib import Path

OLLAMA = "http://127.0.0.1:11434/api/chat"
RULES_VERSION = 2

SYSTEM = """You check one complaint taken from a review of a mobile banking app.

You are given the review and one complaint written about it. Answer two questions about the complaint.

feature: what the complaint is about. It can be a feature, a screen, an action (signing in, sending a payment, uploading a photo), a named error message, or a named device, operating system or platform (a tablet model, a phone OS). Write it in 1-5 words. Write an empty string only when the complaint is about the app, the bank or the company as a whole, with nothing narrower named (\"the app\", \"customer service is bad\", \"on my device\" with no device named).

failure: what is wrong. Any specific fault counts: it crashes, loops, is rejected, never arrives, is missing, is unsupported, is unavailable, cannot be done, was removed, charges too much, is too slow at one named step. Write it in 1-8 words. Write an empty string only when the complaint is just an opinion or a feeling with no specific fault named (\"buggy\", \"unreliable\", \"terrible\", \"clunky\", \"frustrating\", \"many problems\", \"poor\").

Examples from another domain:
- \"recipe app is not supported on smart fridges\" -> feature \"smart fridges\", failure \"not supported\"
- \"unable to save a recipe to favourites\" -> feature \"saving to favourites\", failure \"unable to save\"
- \"no vegetarian filter\" -> feature \"vegetarian filter\", failure \"missing\"
- \"the recipe app is buggy and slow\" -> feature \"\", failure \"\"
- \"search is bad\" -> feature \"search\", failure \"\"

Answer from the complaint and the review only. Do not invent a feature or fault the review does not support."""

SCHEMA = {
    "type": "object",
    "properties": {"feature": {"type": "string"}, "failure": {"type": "string"}},
    "required": ["feature", "failure"],
}


def judge(model: str, review: str, problem: str) -> dict:
    body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": f"Review:\n{review}\n\nComplaint:\n{problem}"},
        ],
        "format": SCHEMA,
        "stream": False,
        "think": False,
        "options": {"temperature": 0, "seed": 0},
    }
    req = urllib.request.Request(OLLAMA, json.dumps(body).encode(), {"Content-Type": "application/json"})
    with urllib.request.urlopen(req, timeout=300) as resp:
        return json.loads(json.loads(resp.read())["message"]["content"])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("jsonl", type=Path)
    ap.add_argument("--model", default="qwen3.5:9b")
    args = ap.parse_args()

    out = args.jsonl.with_name(f"{args.jsonl.stem}-refined-v{RULES_VERSION}.jsonl")
    rows = [json.loads(line) for line in args.jsonl.open(encoding="utf-8")]
    done = {}
    if out.exists():
        done = {r["review_id"]: r for r in map(json.loads, out.open(encoding="utf-8"))}
    todo = [r for r in rows if r["review_id"] not in done]
    print(f"{len(done)} cached, {len(todo)} to judge")

    t0 = time.time()
    calls = 0
    with out.open("a", encoding="utf-8") as f:
        for r in todo:
            kept, dropped = [], []
            for issue in r["extraction"]["issues"]:
                verdict = judge(args.model, r["text"], issue["problem"])
                calls += 1
                feature, failure = verdict["feature"].strip(), verdict["failure"].strip()
                item = issue | {"feature": feature, "failure": failure}
                (kept if feature and failure else dropped).append(item)
            r = dict(r, extraction={"issues": kept, "dropped": dropped})
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
            f.flush()
    print(f"{calls} calls, {(time.time() - t0) / max(calls, 1):.2f}s each -> {out}")


if __name__ == "__main__":
    main()
