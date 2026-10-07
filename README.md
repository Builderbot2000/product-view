# Product View

Aggregate Google Play Store reviews into clustered product pain points and
publish them to Confluence. See [project.md](project.md) for the full plan.

**Current stage: ingestion + clustering.** Reviews are scraped into a JSONL
archive, loaded into SQLite, translated, embedded, and clustered into pain
points; `pv run` does all of it in one command. Next is rendering one
self-contained HTML page for import into Confluence; not built yet.

```bash
pv run            # rebuild the database clean, translate, embed, cluster both streams
pv run --fetch    # same, after topping up the archive from the Play Store
pv painpoints --top 15 --detail
```

## Demo

[Product View @ RBC Mobile](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/294942)
is the hub page built by `pv report --publish --space MFS` on the demo
Confluence site. The role pages (UI & design, Sign-in & security, Payments,
Engineering / QA, Support / CX) sit under it. Viewing it requires access to
that site.

## Setup

Works on Linux, macOS, and Windows with Python 3.10+.

```bash
python -m venv .venv
# Linux/macOS:
source .venv/bin/activate
# Windows:
.venv\Scripts\activate

pip install -e .
```

### On Linux, install CPU-only torch first

The clustering stage pulls `torch` (via `sentence-transformers` and
`transformers`). On Windows and macOS the default PyPI wheel is CPU-only at
~250 MB, but **on Linux plain `pip install` resolves to the CUDA build at
~2.5 GB.** Unless you actually want GPU:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e .
```

### The first run downloads models

`all-MiniLM-L6-v2` (~90 MB) on the first `pv embed`, and `opus-mt-fr-en`
(~301 MB) on the first `pv translate`. Both are one-off, cached under the
platform's user cache directory, and re-runs are no-ops. A cold first run
pausing for a few minutes is the download, not a hang.

### Or run it in a container

```bash
docker compose build
docker compose run --rm pv run                 # full pipeline
docker compose run --rm pv painpoints --top 15
```

CPU-only torch on Linux. `./data` and `./config.yaml` are mounted from the host,
and the models go in a named volume (`models`), so rebuilding the image never
touches the corpus or downloads models again. Verified on Docker Desktop for
Windows: the image is 1.46 GB, and `pv run` takes about 2 minutes once the
caches are warm.

## Configuration

Settings live in [config.yaml](config.yaml): app id and country, the data
directory, fetch tuning, the minimum review length, and every clustering knob,
including which streams `pv run` clusters. Precedence is **command-line flag >
config.yaml > built-in default**. Use `pv --config other.yaml <command>` to point
somewhere else. Unknown keys are an error, so a typo can't silently fall back
to a default.

## Usage

Defaults target RBC Mobile (`com.rbc.mobile.android`, `ca`, all locales) via
config.yaml. Override per run with `--app-id`, `--country`, or
`--no-all-langs --lang en,fr`.

```bash
# Top up with the newest reviews (stops once it reaches what you already have)
pv fetch

# Deep backfill — continues from where the last run stopped
pv fetch --max-reviews 20000 --resume

# Which locales hold reviews you haven't fetched?
pv langs

# What's on disk
pv info

# CSV for spreadsheet use
pv export
```

### Clustering into pain points

Each stage reads and writes through SQLite, so any one re-runs in isolation —
re-clustering never re-embeds. `pv run` chains them all.

```bash
pv db build        # JSONL -> a fresh reviews.db (21,506 rows), plus listing snapshots
pv translate       # detect language, French -> English, cached forever
pv embed           # encode to cached vectors (~2-5 min CPU, once)

pv cluster --polarity negative      # leiden, balanced granularity
pv cluster --polarity positive      # "what users value"
pv cluster --compare                # every strategy, same target, metrics table

pv painpoints --top 15 --detail     # read the output
pv painpoints --sort size           # re-rank by any stored column
```

`pv translate` and `pv embed` are cache-hit no-ops on re-run, so the expensive
work happens once and clustering iterations are cheap.

### The database is rebuilt clean every run

| File | Lifetime |
|---|---|
| `data/raw/`, `data/meta/`, `data/export/` | **Source.** Never deleted by the pipeline |
| `data/reviews.db` | Deleted and rebuilt from `data/raw/` on every `pv db build` / `pv run`. `pv cluster` replaces its stream's previous run, so only the current result is ever stored |
| `data/cache.db` | Translations + segment vectors. Kept across rebuilds, since recomputing them costs ~20 min of translation plus a few minutes of encoding. Delete it only to force a redo |

### `cluster` flags

Defaults below are what config.yaml ships with. A flag overrides config for one run.

| Flag | Default | Notes |
|------|---------|-------|
| `--polarity` | `negative` | Positive and negative cluster separately, so praise and complaints never contaminate each other. `pv run` clusters every stream in `cluster.polarities` |
| `--algorithm` | `leiden` | `leiden` \| `agglomerative` \| `hdbscan` — identical output schema |
| `--granularity` | `balanced` | `broad` 15–25, `balanced` 40–60, `fine` 80–120, or an explicit band like `30-40` |
| `--min-cluster-size` | 25 / 15 | Per stream in config (`negative: 25`, `positive: 15`, since the positive stream is a third the size). The flag overrides both |
| `--cohesion-floor` | 0.35 | Mean cosine to centroid; below this a cluster is a grab-bag |
| `--tau-days` | 365 | Recency decay for the impact score: each review weighs `exp(-age_days / tau)` |
| `--compare` | off | Run every strategy at the same target cluster count |
| `--native-override` | — | Set the strategy's own knob directly, skipping the search |

`--compare` is the slow one, because it runs a full granularity search per
strategy — measured at **~45 minutes** on the 13k negative stream (agglomerative
alone is ~61s per fit). Normal `pv cluster` uses leiden only: the fit takes
seconds, and LexRank synthesis brings a run to ~2–3 minutes per stream.

**What the comparison found**, on the negative stream at band 40–60:

| Strategy | Clusters | Noise | Cohesion | Silhouette |
|---|---|---|---|---|
| **leiden** (default) | 47 | **0.1%** | 0.689 | 0.045 |
| agglomerative | 43 | 15.7% | 0.706 | 0.089 |
| hdbscan | 2 | **98.1%** | 0.827 | 0.499 |

HDBSCAN fails at 384 dimensions — it never found more than 2 clusters and called
98% of the stream noise. Its flattering cohesion and silhouette are artifacts of
keeping two tiny dense blobs, which is exactly why noise share is reported beside
every quality metric: on the metrics alone the worst strategy looks like the best.

**One granularity knob across every strategy.** Each algorithm exposes
granularity through a different native parameter (`resolution`,
`distance_threshold`, `min_cluster_size`), which would make them incomparable.
Instead granularity is a *target cluster count*, and the runner binary-searches
each strategy's native knob to hit it — so strategies are held at the same
count and can be compared, and nobody needs to know what a resolution
parameter is. The search targets the **post-filter** count, so the band means
what it says.

### Reading the output

`pv painpoints --sort <column>` re-ranks by any stored column: `impact`,
`size`, `mean_score`, `pct_one_star`, `thumbs_up_total`, `cohesion`,
`peak_count`, `count_365d`, `first_seen`, or any single impact component.
Every statistic is a real SQL column, so the terminal view and the future
dashboard sort identical data.

`impact` is a 0–100 composite of four percentile-ranked components — recency-weighted
volume (0.40), severity (0.25), momentum (0.20), endorsement (0.15). **All four
are stored separately**, so "why is this ranked #1" has an answer rather than
being a black box.

Labels are **fully algorithmic — no LLM.** Titles are c-TF-IDF keyphrases, the
canonical quote is the medoid (a real review), and the message is 2–3 real
sentences picked by LexRank centrality under MMR. Every word traces to a real
review, nothing leaves the machine, and output is deterministic for a fixed seed.

### Always fetch all locales (the default)

**Play partitions reviews by `lang`, and each partition holds different reviews.**
Fetching only `en` silently drops whole slices of the corpus — for RBC Mobile that
was 2,486 reviews (13%), 1,729 of them French. The partitions also overlap
(`zh-CN` returns the same reviews as `zh`; several codes fall back to the English
pool), so reads dedupe by `review_id` rather than concatenating.

`pv langs` probes every locale and reports which ones still hold unfetched reviews.

Interrupting a fetch is safe: reviews are flushed as they arrive and the
continuation token is checkpointed every page, so `--resume` picks up where it
left off.

### `fetch` flags

| Flag | Default | Notes |
|------|---------|-------|
| `--all-langs` / `--no-all-langs` | on | Fetch every locale partition. Leave it on (see above) |
| `--lang` | `en` | Single locale, or a comma list (`en,fr,zh`); only with `--no-all-langs` |
| `--max-reviews` | 1000 | Cap per locale for this run |
| `--page-size` | 200 | The endpoint's ceiling |
| `--sleep` | 1.0 | Seconds between pages; be polite |
| `--resume` | off | Continue a deep backfill past the newest-end reviews |
| `--full` | off | Re-walk everything, ignoring known IDs |

`--resume` matters more than it looks. Without it, every run starts from the
newest review and stops as soon as it recognizes what it already has — correct
for a weekly top-up, useless for reaching back through history. Backfill with
`--resume`; top up without it.

## Output

`data/raw/{app_id}_{lang}_{country}.jsonl` — one normalized review per line:

```json
{
  "review_id": "7d8785be-...",
  "app_id": "com.rbc.mobile.android",
  "source": "google_play",
  "lang": "en",
  "country": "ca",
  "content": "Sorry we are having technical difficulties...",
  "score": 2,
  "thumbs_up": 0,
  "created_at": "2026-09-22T06:23:04+00:00",
  "app_version": "4.67",
  "review_created_version": "4.67",
  "reply_content": null,
  "replied_at": null,
  "fetched_at": "2026-09-23T...",
  "content_hash": "a3f2..."
}
```

One file per locale (`..._en_ca.jsonl`, `..._fr_ca.jsonl`, …); `pv info`, `pv export`,
and the clustering stage read them merged and deduped. Alongside each, a
`*.state.json` holds that locale's resume checkpoint.

`data/meta/{app_id}_{country}.jsonl` accumulates store-listing snapshots (displayed
score, total ratings, text-review count, rating histogram). The dashboard needs these
as honest denominators — see the caveat below.

Reviewer names and avatar URLs are **not** stored. Clustering never needs
reviewer identity, and not collecting it beats justifying its retention later.

Timestamps are UTC ISO-8601. Files are UTF-8 (CSV export uses UTF-8 BOM so
Excel on Windows renders accents and emoji correctly).

## The corpus reads more negative than the store rating — this is expected

RBC Mobile displays **3.78 stars**; our corpus means **2.63**. That is not a
scraping defect, and it is worth understanding before anyone builds a chart on it:

| | Count | 5-star share |
|---|---|---|
| Play **ratings** (stars tapped) | 48,934 | 57.6% |
| Play **reviews** (text written) | ~20,206 | — |
| **Our corpus** | 21,506 | 25.2% |

Roughly **85% of 1-star raters write text, versus ~19% of 5-star raters.** Angry users
explain themselves; happy users tap a star and leave. 66% of positive reviews here are
under 20 characters ("Good", "great app") against 6% of negative ones.

Verified rather than assumed: per-score filtered walks exhaust at exactly the counts we
hold, and our 21,506 now exceeds Play's own ~20,206 text-review figure.

**Never present the corpus distribution as the app's rating distribution.** Show the
store histogram from `data/meta/` alongside it — a PM who cross-checks against the Play
listing and finds an unexplained gap will stop trusting the whole dashboard.

## Layout

```
src/product_view/
├── cli.py              # argument parsing; fetch / export / info / langs
├── commands.py         # db build / translate / embed / cluster / painpoints / run
├── config.py           # config.yaml: defaults, validation, flag precedence
├── models.py           # Review and PainPoint — the two schema contracts
├── archive.py          # JSONL archive + resume state
├── store.py            # SQLite: reviews.db (rebuilt each run) + attached cache.db
├── ingest/
│   ├── base.py         # ReviewSource protocol ← the swap point
│   └── play_store.py   # google-play-scraper implementation
├── lang/
│   ├── detect.py       # py3langid; Play's `lang` is NOT the review's language
│   └── translate.py    # MarianMT fr→en, cached
├── embed/
│   └── encoder.py      # all-MiniLM-L6-v2, L2-normalized, cached
└── cluster/
    ├── graph.py        # exact cosine kNN
    ├── strategies.py   # ClusterStrategy protocol + leiden/agglomerative/hdbscan
    ├── granularity.py  # target cluster count → each strategy's native knob
    ├── synthesize.py   # c-TF-IDF, medoid, LexRank, MMR
    ├── scoring.py      # impact components + time series
    └── pipeline.py     # orchestration
```

`models.Review` is the contract between ingestion and everything downstream.
When reviews arrive from an internal feed instead of the Play Store, only
`ingest/` changes. `models.PainPoint` is the contract on the other end: the
pipeline writes it, `pv painpoints` and the future dashboard read it.

JSONL stays the raw landing zone. `data/reviews.db` is rebuilt from it every
run, and `data/cache.db` only holds model output, so losing either database
never loses data.

## Trends: always divide by the corpus

Each pain point stores a raw monthly series, and each run stores the
corpus-wide monthly totals beside it. **Use both.** October 2024 alone holds
1,663 negative reviews — 35× the ~48/month baseline — so on raw counts *every*
cluster spikes that month and the chart just redraws the release event.
Dividing by the run's `corpus_monthly_json` is what separates the pain points
that drove a spike (share climbs) from those merely carried along (share flat
or falling).

Because all 15 years are clustered in one pass, every pain point's full
history comes from its own members' dates — trend lines are complete on the
first run and do not depend on matching clusters across runs.
