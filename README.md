# Product View

Group Google Play Store reviews into product issues with a language model,
and publish them to Confluence. See [project.md](docs/Project.md) for the full plan.

Reviews are scraped into a JSONL archive, loaded into SQLite and translated;
a language model then picks out what each review complains about or praises
and groups those points into issues, kept in a codebook so each issue means
the same thing from one run to the next. `pv report` turns the issues into
periodic Confluence pages.

```bash
pv run            # rebuild reviews.db, translate, bring the issues up to date
pv run --fetch    # same, after topping up the archive from the Play Store
pv issues show --detail
pv report --publish --space MFS
```

## Demo

[Product View @ RBC Mobile](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/294942)
is the hub page built by `pv report --publish --space MFS` on the demo
Confluence site. The role pages (UI & design, Sign-in & security, Payments,
Engineering / QA, Support / CX) sit under it. The live pages still come from
the earlier clustering; the next `pv report --publish` after the first issue
build replaces them (the Payments page becomes Product features). Viewing it requires access to
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

Translation and the issue stage pull `torch` (via `sentence-transformers` and
`transformers`). On Windows and macOS the default PyPI wheel is CPU-only at
~250 MB, but **on Linux plain `pip install` resolves to the CUDA build at
~2.5 GB.** Unless you actually want GPU:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e .
```

### The first run downloads models

`all-MiniLM-L6-v2` (~90 MB) on the first `pv issues`, and `opus-mt-fr-en`
(~301 MB) on the first `pv translate`. Both are one-off, cached under the
platform's user cache directory, and re-runs are no-ops. A cold first run
pausing for a few minutes is the download, not a hang.

### Or run it in a container

```bash
docker compose build
docker compose run --rm pv run                 # full pipeline
docker compose run --rm pv issues show
```

CPU-only torch on Linux. `./data` and `./config.yaml` are mounted from the host,
and the models go in a named volume (`models`), so rebuilding the image never
touches the corpus or downloads models again. Verified on Docker Desktop for
Windows (before the issue stage replaced clustering). The image has no local
model, so in a container use `llm.provider: openai`, with the key in `.env`.

## Configuration

Settings live in [config.yaml](config.yaml): app id and country, the data
directory, fetch tuning, the minimum review length, the issue stage's
settings and the language model (`llm:`). Precedence is **command-line flag >
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

### Grouping reviews into issues

Each stage reads and writes through SQLite, so any one re-runs in isolation.
`pv run` chains them all.

```bash
pv db build        # JSONL -> a fresh reviews.db (21,506 rows), plus listing snapshots
pv translate       # detect language, French -> English, cached forever
pv issues          # distill, score against the codebook, form new issues from what's left
pv issues show --detail   # the codebook's live issues, criteria and example quotes
```

`pv issues` uses a language model (see "Choosing the model" below). Its
method, and the test it passed, are in [llm-trials.md](trials/llm-trials.md)
("Viability test"):

1. **Distill.** The model reads each review in the window (default: the last
   12 months, `issues.window_months`) and lists every complaint and every
   piece of praise as an exact quote, each restated as a short neutral
   point. Star rating doesn't decide the side: a complaint in a 4-star review
   is a complaint.
2. **Score against the codebook.** Every point is checked against every live
   issue's one-sentence definition. Live issues never change, so a new month
   is counted against the same issues as the last.
3. **Form new issues from what's left.** Points no issue covers are
   clustered; the model names each specific problem in a cluster with a
   definition; a breadth check drops catch-alls ("app is buggy") and sends
   opinions ("frustrating") to general sentiment; a candidate that means the
   same as a live issue joins it instead; and a selection step keeps the new
   issues that cover the most points with the least overlap. Each new issue
   is filed under one area from [curation.yaml](curation.yaml), whose areas
   apply to any app.
4. **Parent links** are recorded where one issue's matches contain most of
   another's. They are reported, never merged.

Every model answer is cached, so an interrupted run resumes and a repeated
run is free; a monthly run distills only new reviews and forms issues only
from what the existing ones don't cover.

### Choosing the model

Set in the `llm:` section of config.yaml. The model is a setting, never code.

| Provider | Setup | Speed |
|---|---|---|
| `ollama` (default) | Ollama running locally with `qwen3.5:9b` pulled. Review text stays on the machine | One call at a time; about an hour per 100 reviews on a laptop GPU |
| `openai` | `OPENAI_API_KEY` in the environment or `.env` (never config.yaml) | Parallel (`max_workers`); minutes per 100 reviews |

To switch to OpenAI's small models, as planned in llm-trials.md decision 7:

```yaml
llm:
  provider: openai
  models: {fast: gpt-5.4-nano, strong: gpt-5.4-mini}   # fast: most calls; strong: naming issues
  max_workers: 16
  temperature: null                  # some API models only accept the default
  options: {reasoning_effort: none}  # any extra request fields, passed through as given
  batch: true                        # Batch API: half price, answers within 24 hours
  prices: {gpt-5.4-nano: [0.20, 1.25], gpt-5.4-mini: [0.75, 4.50]}   # USD per 1M tokens
  budget_usd: 20                     # stop before spending past this
```

The OpenAI connector works against the live API (live calls and Batch API
jobs), but the method **fails validation on GPT-5.4 nano and mini**: their
scoring matches too much, and a first run built a catch-all issue that
crowded out the specific ones (llm-trials.md, "OpenAI models, first check").
Use the local model. Sending review text to OpenAI also still needs sign-off
(llm-trials.md decision 7).

**Cost.** `pv issues --estimate` prints the calls, tokens and cost a run would
take, from the codebook's state and rates measured in the trials (about 2x
either way). With the settings above, about $8 for the 12-month window and
$80 for the whole archive. Scoring is nearly all of it. Forming new issues
works on a sample of at most `issues.mint_sample` points, so cost grows with
the corpus rather than its square (about $3,500 for the whole archive
without it). Token use is counted from every reply, and `budget_usd` stops a
run before it spends past the limit; answers already paid for stay cached.
Three cheaper scoring settings exist but failed validation and are off:
`compact_scores`, `batch: 30` and `nearest: 10` (llm-trials.md, "Cost
controls"). The cache is keyed
by model, so switching models re-runs every call instead of mixing answers;
points are re-distilled too, and an existing codebook keeps its issues and
re-scores the new points against them.

### What is kept, and what is rebuilt

| File | Lifetime |
|---|---|
| `data/raw/`, `data/meta/`, `data/export/` | **Source.** Never deleted by the pipeline |
| `data/reviews.db` | Deleted and rebuilt from `data/raw/` on every `pv db build` / `pv run` |
| `data/cache.db` | Translations and every model answer. Kept across rebuilds; delete it only to force a redo |
| `data/issues.db` | **The issue codebook.** Issues, the points each review made, and their raw scores. Kept: an issue's identity across runs is the point. Delete it only to start the issues over |

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
and the pipeline read them merged and deduped. Alongside each, a
`*.state.json` holds that locale's resume checkpoint.

`data/meta/{app_id}_{country}.jsonl` accumulates store-listing snapshots (displayed
score, total ratings, text-review count, rating histogram). The dashboard needs these
as honest denominators — see the caveat below.

Reviewer names and avatar URLs are **not** stored. Grouping reviews into
issues never needs reviewer identity, and not collecting it beats justifying its retention later.

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
docs/      the plan (Project.md), requirements.xlsx, report and old clustering design
trials/    every experiment: the trial log (llm-trials.md), scripts by trial, runs/ (output, gitignored)
src/       the pv package, below
```

```
src/product_view/
├── cli.py              # argument parsing; fetch / export / info / langs
├── commands.py         # db build / translate / issues / run
├── config.py           # config.yaml: defaults, validation, flag precedence
├── models.py           # Review — the contract between ingestion and the rest
├── archive.py          # JSONL archive + resume state
├── store.py            # SQLite: reviews.db (rebuilt each run) + attached cache.db
├── ingest/
│   ├── base.py         # ReviewSource protocol ← the swap point
│   └── play_store.py   # google-play-scraper implementation
├── lang/
│   ├── detect.py       # py3langid; Play's `lang` is NOT the review's language
│   └── translate.py    # MarianMT fr→en, cached
├── embed/
│   └── encoder.py      # all-MiniLM-L6-v2, L2-normalized (clusters points in the issue stage)
├── issues/
│   ├── llm.py          # model connectors: ollama, openai; cached, parallel
│   ├── prompts.py      # the validated prompts
│   ├── codebook.py     # issues.db: issues, points, raw scores, runs
│   └── pipeline.py     # distill, score, cluster, name, screen, select, file
├── render/             # pv report: Confluence storage format + SVG charts
└── publish/            # pv publish: Confluence REST
```

`models.Review` is the contract between ingestion and everything downstream.
When reviews arrive from an internal feed instead of the Play Store, only
`ingest/` changes.

JSONL stays the raw landing zone. `data/reviews.db` is rebuilt from it every
run and `data/cache.db` only holds model output, so losing either never loses
data. `data/issues.db` is the one file worth backing up besides the archive.

## Trends: always divide by the corpus

October 2024 alone holds 1,663 negative reviews, 35× the ~48/month baseline,
so on raw counts every issue spikes that month. The report counts each issue
per period against its own usual level and tests the change, rather than
comparing raw counts across months.
