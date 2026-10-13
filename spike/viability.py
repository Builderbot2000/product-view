"""Viability test for the LLooM spike (llm-trials.md, "Viability test").

    sheet DIR   write DIR/label-sheet.md: the live concepts and every complaint point,
                without the model's matches, for blind labelling
    score DIR   compare DIR/labels.txt with the model's matches; print gates G1-G6
    prod        write the production baseline sheet for V1 (out/llm-spike/viab-prod-sheet.md)
    prod-score  score out/llm-spike/viab-prod-labels.txt (gate G7)

labels.txt, one entry per line ('#' starts a comment):
    concept C001 specific|broad|general     how a concept is judged
    dup C014 C017                            two live issue concepts that are the same issue
    12 C001 C014                             point 12 fits these concepts
    13 G | U | N                             general opinion | specific but uncovered | not a complaint

    .venv/Scripts/python.exe -X utf8 spike/viability.py sheet out/llm-spike/viab-v1
"""
from __future__ import annotations

import json
import sqlite3
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "out" / "llm-spike"


def load(d: Path):
    bullets = {b["id"]: b for b in map(json.loads, (d / "bullets.jsonl").open(encoding="utf-8"))}
    order = json.loads((d / "scores-complaint.json").read_text(encoding="utf-8"))["bullets"]
    points = [bullets[i] for i in order]
    concepts = json.loads((d / "concepts.json").read_text(encoding="utf-8"))
    return points, [c for c in concepts if c["status"] == "live"], bullets


def texts() -> dict[str, tuple[str, int]]:
    db = sqlite3.connect(ROOT / "data" / "reviews.db")
    db.execute("ATTACH ? AS cache", (str(ROOT / "data" / "cache.db"),))
    return {a: (b, c) for a, b, c in db.execute(
        "SELECT r.review_id, COALESCE(t.content_en, r.content), r.score "
        "FROM reviews r LEFT JOIN cache.translations t USING (review_id)")}


def sheet(d: Path) -> None:
    points, live, _ = load(d)
    text = texts()
    L = [f"# Label sheet: {d.name}", "", "## Concepts", ""]
    for c in live:
        tag = " (carried)" if c.get("carried") else ""
        L.append(f"- **{c['id']}** {c['name']}{tag} [{c['kind']}]: {c['criterion']}")
    L += ["", "## Points", ""]
    last = None
    for n, b in enumerate(points, 1):
        if b["review_id"] != last:
            last = b["review_id"]
            body, stars = text[last]
            L.append(f"\n**Review {stars}★:** {' '.join(body.split())[:600]}")
        L.append(f"{n}. {b['bullet']}  ·  \"{b['quote']}\"")
    (d / "label-sheet.md").write_text("\n".join(L) + "\n", encoding="utf-8")
    print(d / "label-sheet.md", len(points), "points", len(live), "concepts")


def parse(path: Path):
    judged, dups, gold = {}, [], {}
    for line in path.read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].split()
        if not line:
            continue
        if line[0] == "concept":
            judged[line[1]] = line[2]
        elif line[0] == "dup":
            dups.append(tuple(line[1:3]))
        else:
            gold[int(line[0])] = set(line[1:])
    return judged, dups, gold


def score(d: Path) -> dict:
    points, live, everything = load(d)
    judged, dups, gold = parse(d / "labels.txt")
    missing = [n for n in range(1, len(points) + 1) if n not in gold]
    assert not missing, f"unlabelled points: {missing[:20]}"
    issue = [c for c in live if c["kind"] == "issue"]
    specific = {c["id"] for c in issue if judged.get(c["id"], "specific") == "specific"}
    hit = {c["id"]: {i + 1 for i in c["matches"]} for c in issue}

    pairs = [(n, cid) for cid, h in hit.items() for n in h]
    good = [(n, cid) for n, cid in pairs if cid in specific and cid in gold[n]]
    gold_issue = {n for n, g in gold.items() if g & set(hit)}
    found = {n for n in gold_issue if any(n in hit[c] for c in gold[n] & set(hit))}

    per = {}
    for c in issue:
        h = hit[c["id"]]
        ok = sum(1 for n in h if c["id"] in specific and c["id"] in gold[n])
        per[c["id"]] = (len(h), ok)
    low = [cid for cid, (k, ok) in per.items() if k >= 5 and ok / k < 0.5]  # reported (scorer errors)
    grab = [c["id"] for c in issue if c["id"] not in specific]                # G4 since 2026-10-13: broad, live

    new = {c["id"] for c in issue if not c.get("carried")}
    carried = {c["id"] for c in issue if c.get("carried")}
    dup_ids = {x for p in dups for x in p}
    g6 = [p for p in dups if (p[0] in new) != (p[1] in new)]

    every = list(everything.values())
    res = dict(
        slice=d.name, points=len(points),
        G1=sum(b["exact"] for b in every) / len(every),
        G2=len(good) / max(len(pairs), 1), pairs=len(pairs),
        G3=len(found) / max(len(gold_issue), 1), gold_issue=len(gold_issue),
        G4=len(grab), grab=grab, low_precision=low,
        G5=len(dup_ids) / max(len(issue), 1), dups=dups,
        G6=len(g6),
        issue_concepts=len(issue), new=len(new), carried=len(carried),
        broad=sorted(set(c["id"] for c in issue) - specific),
        labels=Counter(x for g in gold.values() for x in g if x in "GUN"),
        on_carried=sum(1 for n in found if any(n in hit[c] for c in gold[n] & carried)),
    )
    print(json.dumps(res, indent=1, default=list))
    print("\nper concept (matches, correct):")
    for c in issue:
        k, ok = per[c["id"]]
        flag = " BROAD" if c["id"] in grab else " LOW" if c["id"] in low else ""
        print(f"  {c['id']} {judged.get(c['id'], 'specific'):8} {k:3} {ok:3}  {c['name']}{flag}")
    (d / "gates.json").write_text(json.dumps(res, indent=1, default=list), encoding="utf-8")
    return res


# ---- production baseline (G7) ---------------------------------------------

def prod_rows(review_ids: set[str]):
    from product_view.render.issues import load_stream, load_taxonomy
    from product_view.store import Store

    store = Store(ROOT / "data" / "reviews.db")
    # the live report's settings (config.yaml report section: built-in defaults)
    stream = load_stream(store, "negative", load_taxonomy(ROOT / "curation.yaml"), 28, 6)
    owner = {pp.pain_point_id: i for i in stream.issues for pp in i.members}
    seen = set()
    rows = []
    for r in store.member_reviews(stream.run["run_id"]):
        rid, issue = r["review_id"], owner.get(r["pain_point_id"])
        if rid not in review_ids or issue is None or issue.kind == "mood" or (issue.label, rid) in seen:
            continue
        seen.add((issue.label, rid))  # the report quotes a review's most central unit only
        rows.append((issue.label, issue.kind, rid, " ".join((r["unit_text"] or "").split())))
    return sorted(rows)


def prod(sheet_only=True):
    points, _, _ = load(OUT / "viab-v1")
    rows = prod_rows({b["review_id"] for b in points})
    if sheet_only:
        L = ["# Production baseline sheet (V1 reviews, negative stream)", ""]
        last = None
        for n, (label, kind, rid, unit) in enumerate(rows, 1):
            if label != last:
                last = label
                L.append(f"\n## {label} [{kind}]")
            L.append(f"{n}. {unit}")
        (OUT / "viab-prod-sheet.md").write_text("\n".join(L) + "\n", encoding="utf-8")
        print(len(rows), "quotes", len({r[0] for r in rows}), "issues")
        return
    judged, quotes = {}, {}
    for line in (OUT / "viab-prod-labels.txt").read_text(encoding="utf-8").splitlines():
        line = line.split("#")[0].split()
        if not line:
            continue
        if line[0] == "issue":
            judged[" ".join(line[2:])] = line[1]
        else:
            quotes[int(line[0])] = line[1] == "y"
    # headings judged "exclude" (outcomes, support) are general in the LLooM run too, so neither side counts them
    kept = [(n, label) for n, (label, *_r) in enumerate(rows, 1) if judged.get(label, "specific") != "exclude"]
    ok = sum(1 for n, label in kept if judged.get(label, "specific") == "specific" and quotes[n])
    print(f"production: {ok}/{len(kept)} = {ok / len(kept):.0%} of quotes under a specific issue that fit it")


if __name__ == "__main__":
    cmd = sys.argv[1]
    if cmd == "sheet":
        sheet(Path(sys.argv[2]))
    elif cmd == "score":
        score(Path(sys.argv[2]))
    elif cmd == "prod":
        prod(True)
    elif cmd == "prod-score":
        prod(False)
