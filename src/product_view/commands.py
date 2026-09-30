"""Clustering-stage commands: db build, translate, embed, cluster, painpoints, run.

Separate from cli.py, which owns argument parsing and the ingest stage. Each
command reads and writes through the store, so any stage re-runs in isolation
-- re-clustering must never require re-embedding.

The database never accumulates history: `db build` (and so `run`) rebuilds
reviews.db from the JSONL archive, and `cluster` replaces the previous result
for its stream. Translations and embeddings live in cache.db and survive both.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

from . import config
from .archive import iter_corpus
from .store import SORTABLE, Store, reset

log = logging.getLogger(__name__)


def _db_path(args: argparse.Namespace) -> Path:
    return Path(args.data_dir) / "reviews.db"


def _open(args: argparse.Namespace) -> Store:
    return Store(_db_path(args))


# --- db build --------------------------------------------------------------

def cmd_db_build(args: argparse.Namespace) -> int:
    raw_dir = Path(args.data_dir) / "raw"
    # Clean every time: reviews.db is derived, and anything left over from an
    # earlier build or run is stale. The archive and cache.db are untouched.
    # Opening first lets a pre-split database hand its translations and
    # embeddings to cache.db before the file is deleted.
    _open(args).close()
    reset(_db_path(args))
    with _open(args) as store:
        rows = iter_corpus(raw_dir, args.app_id, args.country)
        n = store.upsert_reviews(rows)

        meta_path = Path(args.data_dir) / "meta" / f"{args.app_id}_{args.country}.jsonl"
        snaps = 0
        if meta_path.exists():
            with meta_path.open(encoding="utf-8") as fh:
                snaps = store.upsert_app_metadata(
                    json.loads(line) for line in fh if line.strip()
                )

        print(f"reviews:       {store.count('reviews')} ({n} written)")
        print(f"app_metadata:  {store.count('app_metadata')} snapshots ({snaps} written)")
        print(f"database:      {_db_path(args)} (rebuilt clean)")
        print(f"cache:         {store.cache_path} "
              f"({store.count('translations')} translations, "
              f"{store.count('segments')} segment vectors kept)")
    return 0


# --- translate -------------------------------------------------------------

def cmd_translate(args: argparse.Namespace) -> int:
    from .lang import detect, translate as mt

    with _open(args) as store:
        pending = store.untranslated(min_chars=args.min_chars)
        if not pending:
            print("nothing to translate — every review is already routed")
            return 0

        print(f"routing {len(pending)} reviews by detected language...")
        passthrough: list[tuple] = []
        to_translate: list[tuple] = []
        dropped: list[tuple] = []
        now = datetime.now(timezone.utc).isoformat()

        for row in pending:
            lang, confidence, action = detect.route(row["content"])
            if action == "drop":
                dropped.append((row["review_id"], lang, confidence, None, None, now))
            elif action == "translate":
                to_translate.append((row["review_id"], lang, confidence, row["content"]))
            else:
                passthrough.append(
                    (row["review_id"], lang, confidence, row["content"], None, now)
                )

        print(f"  english / passthrough : {len(passthrough)}")
        print(f"  french   -> translate : {len(to_translate)}")
        print(f"  non-latin -> dropped  : {len(dropped)}")

        store.save_translations(passthrough)
        store.save_translations(dropped)

        if to_translate:
            # Persist each batch as it lands rather than buffering the run.
            # Beam-search decoding on CPU takes tens of minutes at this scale,
            # and an interrupted run should keep what it already produced:
            # re-running then translates only the remainder, because
            # `untranslated()` skips whatever is already stored.
            total = len(to_translate)
            done = 0
            for indices, batch in mt.translate_batches([r[3] for r in to_translate]):
                store.save_translations(
                    [
                        (
                            to_translate[i][0],   # review_id
                            to_translate[i][1],   # detected lang
                            to_translate[i][2],   # confidence
                            english,
                            mt.MODEL_NAME,
                            now,
                        )
                        for i, english in zip(indices, batch)
                    ]
                )
                done += len(batch)
                print(f"    translated {done}/{total}", flush=True)

        # Dropping the non-Latin reviews is the right trade; dropping them
        # silently would be the actual mistake.
        if dropped:
            print(f"\nDROPPED {len(dropped)} non-Latin-script reviews "
                  f"(no translation model): they are excluded from clustering.")
        print("\ndetected languages:")
        for row in store.translation_summary()[:10]:
            note = f"  ({row['dropped']} dropped)" if row["dropped"] else ""
            print(f"  {row['detected_lang'] or '?':<6} {row['n']:>6}{note}")
    return 0


# --- embed -----------------------------------------------------------------

def cmd_embed(args: argparse.Namespace) -> int:
    """Split each review into fine segments and encode every segment.

    Segments, not whole reviews, because clustering runs on complaint units
    built from them (see embed/segment.py and cluster/units.py).
    """
    from .embed import encoder, segment

    with _open(args) as store:
        pending = store.unsegmented(encoder.MODEL_NAME, segment.SPLITTER_VERSION)
        if not pending:
            print(f"all segments cached for {encoder.MODEL_NAME} "
                  f"(splitter v{segment.SPLITTER_VERSION}) — nothing to do")
            return 0

        print(f"segmenting and encoding {len(pending)} reviews with {encoder.MODEL_NAME}")
        # Chunked by review so an interrupted run keeps what it encoded and
        # memory stays bounded; re-running then encodes only the remainder,
        # since `unsegmented()` skips whatever is already cached.
        chunk = 2000
        total_segments = 0
        for start in range(0, len(pending), chunk):
            block = pending[start : start + chunk]
            pieces = [
                (r["review_id"], seq, text)
                for r in block
                for seq, text in enumerate(segment.split(r["content_en"]))
            ]
            vectors = encoder.encode([p[2] for p in pieces], show_progress=False)
            store.save_segments(
                encoder.MODEL_NAME, segment.SPLITTER_VERSION, encoder.DIM,
                [(rid, seq, text, encoder.to_blob(v))
                 for (rid, seq, text), v in zip(pieces, vectors)],
            )
            total_segments += len(pieces)
            print(f"    {min(start + chunk, len(pending))}/{len(pending)} reviews "
                  f"({total_segments} segments)", flush=True)
        print(f"segments: {store.count('segments')} cached")
    return 0


# --- cluster ---------------------------------------------------------------

def _config_from(args: argparse.Namespace):
    from .cluster.pipeline import ClusterConfig

    # "30-40" means an explicit target band; anything else is a preset name.
    granularity = args.granularity
    if "-" in granularity:
        lo, _, hi = granularity.partition("-")
        granularity = (int(lo), int(hi))

    min_cluster_size = args.min_cluster_size
    if min_cluster_size is None:
        min_cluster_size = config.min_cluster_size(args.config, args.polarity)

    return ClusterConfig(
        polarity=args.polarity,
        algorithm=args.algorithm,
        granularity=granularity,
        min_cluster_size=min_cluster_size,
        cohesion_floor=args.cohesion_floor,
        knn_k=args.knn_k,
        seed=args.seed,
        min_chars=args.min_chars,
        merge_threshold=args.merge_threshold,
        tau_days=args.tau_days,
        momentum_window_days=args.momentum_window,
        native_override=args.native_override,
    )


def cmd_cluster(args: argparse.Namespace) -> int:
    from .cluster import pipeline

    cfg = _config_from(args)
    with _open(args) as store:
        if args.compare:
            rows = pipeline.compare(store, cfg, app_id=args.app_id)
            print(f"\n{'strategy':<15} {'knob':<28} {'clusters':>8} {'noise%':>7} "
                  f"{'cohesion':>9} {'silhouette':>11}")
            for r in rows:
                flag = "" if r["converged"] else "  (did not converge)"
                print(f"{r['strategy']:<15} {r['knob']:<28} {r['clusters']:>8} "
                      f"{r['noise_pct']:>6.1f}% {r['cohesion']:>9.3f} "
                      f"{r['silhouette']:>11.3f}{flag}")
            return 0

        replaced = store.clear_polarity(cfg.polarity)
        if replaced:
            print(f"replacing {replaced} earlier {cfg.polarity} run(s)")
        summary = pipeline.run(store, cfg, app_id=args.app_id)
        print(f"\nrun:          {summary['run_id']}")
        print(f"stream:       {summary['stream_size']} reviews -> "
              f"{summary['unit_count']} complaint units")
        print(f"clusters:     {summary['clusters']}  "
              f"({summary['knob']}={summary['native_param']:.4g})")
        print(f"clustered:    {summary['members']} units")
        print(f"unclustered:  {summary['unclustered']} units "
              f"({100 * summary['unclustered'] / summary['unit_count']:.1f}%); "
              f"{summary['uncovered_reviews']} reviews in no pain point "
              f"({100 * summary['uncovered_reviews'] / summary['stream_size']:.1f}%)")
        if not summary["converged"]:
            print("WARNING: granularity search did not land in the target band")
        print(f"\ninspect with: pv painpoints --top 15")
    return 0


# --- run -------------------------------------------------------------------

def cmd_run(args: argparse.Namespace) -> int:
    """The whole pipeline over a clean database: [fetch ->] db build ->
    translate -> embed -> cluster each configured stream.

    Translate and embed are cache hits for every review already seen, so a
    run costs seconds plus whatever is genuinely new.
    """
    if args.fetch:
        from .cli import cmd_fetch

        args.resume = False   # a top-up, never a backfill
        args.full = False
        print("== fetch")
        if rc := cmd_fetch(args):
            return rc

    for name, step in (("db build", cmd_db_build),
                       ("translate", cmd_translate),
                       ("embed", cmd_embed)):
        print(f"\n== {name}")
        if rc := step(args):
            return rc

    args.compare = False
    for polarity in config.get(args.config, "cluster.polarities"):
        print(f"\n== cluster {polarity}")
        args.polarity = polarity
        if rc := cmd_cluster(args):
            return rc
    return 0


# --- painpoints ------------------------------------------------------------

def cmd_painpoints(args: argparse.Namespace) -> int:
    from .models import PainPoint

    with _open(args) as store:
        if args.run_id:
            run = store.conn.execute(
                "SELECT * FROM runs WHERE run_id = ?", (args.run_id,)
            ).fetchone()
        else:
            run = store.latest_run(args.polarity)
        if run is None:
            print("no clustering runs yet — run `pv cluster` first", file=sys.stderr)
            return 1

        rows = store.pain_points(
            run["run_id"], sort=args.sort, desc=not args.asc, limit=args.top
        )
        corpus_monthly = json.loads(run["corpus_monthly_json"] or "{}")

        print(f"run {run['run_id']}  |  {run['algorithm']}  |  "
              f"{run['stream_size']} reviews, {run['unit_count']} complaint units  |  "
              f"{len(rows)} shown, sorted by {args.sort} {'asc' if args.asc else 'desc'}")
        print(f"uncovered: {run['uncovered_reviews']} reviews "
              f"({100 * run['uncovered_reviews'] / run['stream_size']:.1f}% of the stream "
              f"are in no pain point); {run['unclustered']} units unclustered")
        print("size counts reviews, so one review can count toward several pain points; "
              "sole = share of them where it is the only one\n")

        header = (f"{'#':>3}  {'impact':>6} {'size':>6} {'%str':>6} {'sole':>5} {'mean':>5} "
                  f"{'1star%':>7} {'thumbs':>7} {'coh':>5} {'peak':>8} {'365d':>6}  title")
        print(header)
        print("-" * len(header))
        for i, row in enumerate(rows, 1):
            pp = PainPoint.from_row(row)
            print(f"{i:>3}  {pp.impact:>6.1f} {pp.size:>6} {pp.pct_of_stream:>5.1f}% "
                  f"{pp.sole_share:>5.2f} {pp.mean_score:>5.2f} {pp.pct_one_star:>6.1f}% "
                  f"{pp.thumbs_up_total:>7} {pp.cohesion:>5.2f} {pp.peak_month or '-':>8} "
                  f"{pp.count_365d:>6}  {pp.title[:70]}")

        if args.detail:
            for i, row in enumerate(rows, 1):
                pp = PainPoint.from_row(row)
                print(f"\n{'=' * 78}\n{i}. {pp.title}   [{pp.pain_point_id}]")
                print(f"   impact {pp.impact:.1f}  =  "
                      f"recency {pp.impact_components['recency_volume']:.2f} · "
                      f"severity {pp.impact_components['severity']:.2f} · "
                      f"momentum {pp.impact_components['momentum']:.2f} · "
                      f"endorsement {pp.impact_components['endorsement']:.2f}")
                print(f"   {pp.size} reviews ({pp.pct_of_stream:.1f}%), "
                      f"{pp.unit_count} units  sole {pp.sole_share:.2f}  "
                      f"mean {pp.mean_score:.2f}  cohesion {pp.cohesion:.2f}  "
                      f"{pp.first_seen} .. {pp.last_seen}")
                print(f"   keywords: {', '.join(pp.keywords[:6])}")
                print(f"\n   MESSAGE: {pp.message[:600]}")
                print(f"\n   {_sparkline(pp.monthly_counts, corpus_monthly)}")
                canonical = store.reviews_by_id([pp.canonical_review_id])
                if canonical:
                    c = canonical[0]
                    tag = " [auto-translated from fr]" if c["detected_lang"] == "fr" else ""
                    print(f"\n   CANONICAL (medoid){tag}:")
                    print(f"     {c['score']}* {(c['created_at'] or '')[:10]}  "
                          f"{' '.join((pp.canonical_text or c['content'] or '').split())[:240]}")

                # The MMR picks, not the most central members: these span the
                # range of phrasing, where the five nearest the centroid are
                # near-identical restatements of the canonical quote.
                # MMR's first pick is argmax(relevance), which is the medoid by
                # definition -- so it is always the canonical quote. Skip it
                # here rather than distorting the stored selection.
                reps = store.reviews_by_id(
                    [r for r in pp.representative_review_ids
                     if r != pp.canonical_review_id]
                )
                if reps:
                    # The unit, not the whole review: in a review raising four
                    # problems, only one sentence is about this pain point.
                    units = store.unit_texts(
                        pp.run_id, pp.pain_point_id, [m["review_id"] for m in reps])
                    print("\n   supporting quotes (MMR-selected):")
                    for m in reps:
                        tag = " [translated]" if m["detected_lang"] == "fr" else ""
                        quote = units.get(m["review_id"]) or m["content"] or ""
                        text = " ".join(quote.split())[:180]
                        print(f"     {m['score']}* {(m['created_at'] or '')[:10]}{tag}  {text}")
    return 0


def _sparkline(monthly: dict, corpus_monthly: dict, width: int = 48) -> str:
    """Yearly concentration, shown as raw count and share of that year's stream.

    Both are needed. October 2024 alone holds 35x the monthly baseline, so on
    raw counts every cluster spikes there; only the share says whether this
    pain point drove the event or was carried along by it.
    """
    if not monthly:
        return "(no dates)"
    by_year: dict[str, int] = {}
    corpus_year: dict[str, int] = {}
    for month, n in monthly.items():
        by_year[month[:4]] = by_year.get(month[:4], 0) + n
    for month, n in corpus_monthly.items():
        corpus_year[month[:4]] = corpus_year.get(month[:4], 0) + n

    years = sorted(corpus_year)
    peak = max(by_year.values()) if by_year else 1
    bars = "".join(
        " ▁▂▃▄▅▆▇█"[min(8, round(8 * by_year.get(y, 0) / peak))] for y in years
    )
    hot = sorted(by_year.items(), key=lambda kv: -kv[1])[:3]
    detail = "  ".join(
        f"{y}:{n}({100 * n / max(corpus_year.get(y, 1), 1):.0f}% of yr)" for y, n in hot
    )
    return f"{years[0]}|{bars}|{years[-1]}   peak years  {detail}"


def add_parsers(sub, common, add_fetch_options) -> None:
    """Register the clustering-stage subcommands onto the existing parser."""
    p_db = sub.add_parser("db", help="database maintenance")
    db_sub = p_db.add_subparsers(dest="db_command", required=True)
    p_build = db_sub.add_parser(
        "build", help="rebuild reviews.db clean from the JSONL archive")
    common(p_build)
    p_build.set_defaults(func=cmd_db_build)

    p_tr = sub.add_parser("translate", help="detect language, translate French to English")
    common(p_tr)
    p_tr.add_argument("--min-chars", type=int)
    p_tr.set_defaults(func=cmd_translate)

    p_emb = sub.add_parser("embed", help="encode reviews to cached vectors")
    common(p_emb)
    p_emb.set_defaults(func=cmd_embed)

    p_cl = sub.add_parser(
        "cluster", help="cluster one stream into pain points (replaces its previous run)")
    common(p_cl)
    p_cl.add_argument("--polarity", choices=["negative", "positive"], default="negative")
    add_cluster_options(p_cl)
    p_cl.add_argument("--compare", action="store_true",
                      help="run every available strategy at the same target band")
    p_cl.set_defaults(func=cmd_cluster)

    p_run = sub.add_parser(
        "run", help="full pipeline on a clean database: db build, translate, "
                    "embed, cluster every stream in config")
    common(p_run)
    p_run.add_argument("--fetch", action="store_true",
                       help="top up the archive from the Play Store first")
    add_fetch_options(p_run)
    add_cluster_options(p_run)
    p_run.set_defaults(func=cmd_run)

    p_pp = sub.add_parser("painpoints", help="inspect ranked pain points")
    common(p_pp)
    p_pp.add_argument("--top", type=int, default=20)
    p_pp.add_argument("--sort", default="impact", choices=list(SORTABLE))
    p_pp.add_argument("--asc", action="store_true", help="ascending instead of descending")
    p_pp.add_argument("--polarity", choices=["negative", "positive"], default=None)
    p_pp.add_argument("--run-id", default=None)
    p_pp.add_argument("--detail", action="store_true",
                      help="full message, trend and example reviews per pain point")
    p_pp.set_defaults(func=cmd_painpoints)


def add_cluster_options(p: argparse.ArgumentParser) -> None:
    """Clustering knobs. Unset flags take their value from config.yaml."""
    p.add_argument("--algorithm", choices=["leiden", "agglomerative", "hdbscan"])
    p.add_argument("--granularity",
                   help="broad | balanced | fine, or MIN-MAX (e.g. 30-40)")
    p.add_argument("--min-cluster-size", type=int,
                   help="overrides the per-stream value in config")
    p.add_argument("--cohesion-floor", type=float)
    p.add_argument("--knn-k", type=int)
    p.add_argument("--seed", type=int)
    p.add_argument("--min-chars", type=int)
    p.add_argument("--merge-threshold", type=float,
                   help="cosine at which adjacent segments of a review join one complaint")
    p.add_argument("--tau-days", type=float,
                   help="recency decay constant: weight = exp(-age_days / tau)")
    p.add_argument("--momentum-window", type=float)
    p.add_argument("--native-override", type=float,
                   help="set the strategy's native knob directly, skipping the search")
