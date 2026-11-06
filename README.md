# Product View

Match Google Play Store reviews to the app features each team follows, and
publish an overview, a page per team and a report per team member to Confluence. See
[production-plan.md](docs/production-plan.md) for the service being built.

Reviews are scraped into a JSONL archive, loaded into SQLite and translated.
Complaints are then matched to a fixed list of topics from a team -> member ->
topic matrix (`matrix.yaml`, see [matrix.sample.yaml](matrix.sample.yaml)),
and `pv report` turns the matches into a Confluence page tree: an overview of
every team and topic, a page per team, and a report per member. `pv cycle` does all of it once and exits, for a scheduler
to start.

The [architecture page](docs/architecture.md) has two diagrams: the whole
system, and one real review followed from Google Play to the number on a
member's report. The [Q&A sheet](docs/qa.md) answers common questions about the
method, the report and running it at RBC, each with a link to the code.

```bash
pv cycle                    # fetch, build, translate, match, report, publish; then exit
pv cycle --no-fetch --no-publish   # the same on the archive as it is, pages to out/report
pv matrix                   # check the matrix file, and who owns what
```

## Demo

The demo pages are on the demo Confluence site, built by
`pv report --publish --space MFS` from the sample matrix (invented teams,
people and topics). Viewing them requires access to that site.

[Product View @ RBC Mobile](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144019) is the overview of every team and
topic. Each team page sits under it, and each member's report under their team
page, all from one template whatever the number of teams:

| Team page | Member reports |
|---|---|
| [Sign-in & security](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7013146) | [Alex Martin](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144136), [Priya Shah](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144163) |
| [Payments & transfers](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144200) | [Jordan Lee](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7111296), [Sophie Tremblay](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7078879) |
| [Accounts & settings](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7372840) | [Daniel Okafor](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7078920), [Maria Lopez](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144245) |
| [App platform (Engineering / QA)](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7078945) | [Chris Wong](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7013257), [Nadia Haddad](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7078994) |
| [Support / CX](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7013286) | [Sam Gagnon](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7079031) |

[Priya Shah's report](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144163) is the one traced step by step in the
[Q&A sheet](docs/qa.md#one-review-from-play-store-to-the-report) and the
[journey diagram](docs/architecture.md#one-review-from-play-store-to-the-report).

Pages left under the overview by teams or members no longer in the matrix are
listed after publishing, for archiving by hand.

## Documentation

| Document | What it holds |
|---|---|
| [architecture.md](docs/architecture.md) | The system diagram, and one review's journey from Google Play to a report. [architecture.html](docs/architecture.html) draws the same diagrams in a browser |
| [qa.md](docs/qa.md) | Answers to common questions about the method, pipeline, report and deployment, each linked to the code. Includes one review traced step by step |
| [report-design.md](docs/report-design.md) | Decisions behind the report: who it's for, Confluence building blocks, visual language, the pages |
| [production-plan.md](docs/production-plan.md) | The work from trial code to a portable, scheduled service |
| [topic-trials.md](trials/topic-trials.md) | The matching trials, round by round, and the held-out test |
| [llm-trials.md](trials/llm-trials.md) | Earlier trials of an AI model grouping reviews, before the fixed topic list, and the model decisions |
| [demo-notes.md](docs/demo-notes.md) | Notes for the senior manager walkthrough |
| [matrix.sample.yaml](matrix.sample.yaml) | The Ownership Matrix format, and how to write a topic's description |
| [legacy/](docs/legacy/) | Superseded documents, kept for history: the original pain-point clustering plan, old handoffs, the requirements workbook and the dropped pitch deck |

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

Translation and matching pull `torch` (via `sentence-transformers` and
`transformers`). On Windows and macOS the default PyPI wheel is CPU-only at
~250 MB, but **on Linux plain `pip install` resolves to the CUDA build at
~2.5 GB.** Unless you actually want GPU:

```bash
pip install torch --index-url https://download.pytorch.org/whl/cpu
pip install -e .
```

### The first run downloads models

`Qwen3-Embedding-0.6B` (~1.2 GB) and `all-MiniLM-L6-v2` (~90 MB) on the first
`pv match`, and `opus-mt-fr-en` (~301 MB) on the first `pv translate`. All are one-off, cached under the
platform's user cache directory, and re-runs are no-ops. A cold first run
pausing for a few minutes is the download, not a hang.

### Or run it in a container

```bash
docker compose build                           # --build-arg BAKE_MODELS=1: weights inside, for air-gapped hosts
docker compose run --rm pv                     # one cycle (pv cycle)
docker compose run --rm pv check-matching      # acceptance check for the configured models
docker compose run --rm pv cycle --no-fetch --space MFS
```

One image that runs one cycle and exits; the host's scheduler decides when
(docs/production-plan.md §0). CPU-only torch, pinned dependencies
(`requirements.lock`), a non-root user, and a read-only root filesystem: it
writes only to `/app/data` (the one persistent volume: archive, databases,
lock, built pages), `/cache` (model weights, about 1.6 GB, downloaded on first
use unless baked in) and `/tmp`. Configuration comes from mounts and the
environment only (the Dockerfile's header lists them): `config.yaml` as a mount,
the real matrix as a mount with `PV_MATRIX` pointing at it, secrets as
environment variables, `HTTPS_PROXY` and a CA bundle for corporate proxies,
`HF_ENDPOINT` for an in-house model mirror.

By default the container uses the Ollama on this machine at port 11600
(`PV_OLLAMA_HOST` changes it; Ollama must listen beyond 127.0.0.1, e.g.
`OLLAMA_HOST=0.0.0.0:11600`). `--profile ollama` runs Ollama in a container
instead, and `--profile scheduler` runs a cycle every `PV_EVERY_HOURS` (default
168) for hosts with no scheduler of their own.

### Matching reviews to topics

Topics, teams and members come from the matrix: `$PV_MATRIX` if set, else
`matrix.yaml` (the real one: confidential, gitignored, never committed), else
`matrix.sample.yaml` (invented content in the same format). How to write a
topic's description is in the sample's header; the description is part of the
matching.

```bash
pv matrix                   # check the matrix against its rules, list who owns what
pv match                    # match the reports' window: a new run in data/topics.db
pv report                   # overview, team pages and member reports -> out/report/
pv report --publish --space MFS
```

`pv match` takes the 1-3 star reviews in the reports' window (the reporting
period and the periods its trend and "usual" need) and matches them to the
topics (method M in [topic-trials.md](trials/topic-trials.md), validated at
precision 78%, recall 65%, false alarm 12% on a held-out sample):

1. Each review is split into units, one complaint each.
2. The model writes about 12 example complaints per topic from its name and
   description. A classifier trained on them puts each unit against every topic.
3. A clear match is taken as it is, a unit that matches nothing well is left
   without a topic, and the model decides the rest from up to 5 candidate
   topics, reading the whole review. About a third of units reach the model.

Every model answer and embedding is cached, so a weekly run pays only for new
reviews. Changing a topic's name or description re-matches everything.

Embeddings run in-process by default (`embed.backend: local`, CPU). With an
Ollama server that has `qwen3-embedding:0.6b`, `embed.backend: ollama` is much
faster on a GPU and gives the same vectors.

### Acceptance check for a deployment

```bash
pv check-matching                  # both windows; exit 0 on a pass, 1 on a fail
pv check-matching --window t1      # one window
```

Runs the configured chat and embedding models through the same matching code
as `pv match` on two fixed windows that ship with the package
(`src/product_view/matching/acceptance/`): the development window (294 complaint
reviews) and the held-out one (204), each with an answer key for 120 drawn
reviews, against the 22 topics the keys were written for (not the deployed
matrix). Pass: precision at least 70%, recall at least 60%, false alarm at most
25%, on both. Run it before go-live and after any model change; each run is
recorded in `data/checks/`. The fixtures are rebuilt from the trial data by
`trials/topics/fixture.py`.

### One cycle, for a scheduler

`pv cycle` runs fetch -> db build -> translate -> match -> report -> publish once
and exits: 0 on success, 1 when a step fails, 3 when another cycle holds the
lock (`data/pv-cycle.lock`). It prints a one-line summary and records the
cycle in `data/topics.db`. Nothing is published unless every earlier step
succeeded. It publishes when `confluence.space` is set, else it only writes
the pages. `PV_LOG_JSON=1` makes log lines JSON. Email to members (D21) is
deferred; until it lands, each member's report page is what they are sent to.

### Preparing reviews

Each stage reads and writes through SQLite, so any one re-runs in isolation;
`pv cycle` runs them in order.

```bash
pv db build        # JSONL -> a fresh reviews.db (21,506 rows), plus listing snapshots
pv translate       # detect language, French -> English, cached forever
```

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
  models: {fast: gpt-5.4-nano, strong: gpt-5.4-mini}   # matching uses only fast
  max_workers: 16
  temperature: null                  # some API models only accept the default
  options: {reasoning_effort: none}  # any extra request fields, passed through as given
  prices: {gpt-5.4-nano: [0.20, 1.25], gpt-5.4-mini: [0.75, 4.50]}   # USD per 1M tokens
  budget_usd: 20                     # stop before spending past this
```

The OpenAI connector works against the live API, but matching is validated
only on the local model: run `pv check-matching` before using any other. Sending review text to OpenAI also
still needs sign-off (llm-trials.md decision 7).

**Cost.** Token use is counted from every reply, and `budget_usd` stops a run
before it spends past the limit; answers already paid for stay cached. The
cache is keyed by model, so switching models re-runs every call instead of
mixing answers.

### What is kept, and what is rebuilt

| File | Lifetime |
|---|---|
| `data/raw/`, `data/meta/`, `data/export/` | **Source.** Never deleted by the pipeline |
| `data/reviews.db` | Deleted and rebuilt from `data/raw/` on every `pv db build` / `pv cycle` |
| `data/cache.db` | Translations, every model answer and every embedding. Kept across rebuilds; delete it only to force a redo |
| `data/topics.db` | Every matching run and what it matched (units, routes, matches), and every `pv cycle`. Kept; reports read the latest run |

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

Reviewer names and avatar URLs are **not** stored. Matching reviews to
topics never needs reviewer identity, and not collecting it beats justifying its retention later.

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
docs/      architecture diagrams, Q&A sheet, report design, production plan, demo notes; legacy/ for superseded documents
trials/    every experiment: the trial logs (topic-trials.md, llm-trials.md), scripts by trial, runs/ (output, gitignored)
src/       the pv package, below
```

```
src/product_view/
├── cli.py              # assembles the commands; each lives with the code it runs
├── config.py           # config.yaml: defaults, validation, flag precedence; .env
├── store.py            # SQLite: reviews.db (rebuilt each run) + attached cache.db
├── prepare.py          # pv db build, pv translate
├── matrix.py           # the team -> member -> topic matrix: load, validate, hash; pv matrix
├── periods.py          # reporting periods, "usual" and the change test
├── llm.py              # model connectors: ollama, openai-compatible; cached, parallel
├── cycle.py            # pv cycle: one full cycle, a lock, a run record, exit codes
├── ingest/
│   ├── models.py       # Review — the contract between ingestion and the rest
│   ├── archive.py      # JSONL archive + resume state
│   ├── play_store.py   # google-play-scraper implementation
│   └── commands.py     # pv fetch / export / info / langs
├── lang/
│   ├── detect.py       # py3langid; Play's `lang` is NOT the review's language
│   └── translate.py    # MarianMT fr→en, cached
├── matching/           # method M
│   ├── run.py          # pv match: the window, one run, stored
│   ├── units.py        # reviews -> complaint units
│   ├── embed.py        # MiniLM and Qwen3 embeddings, cached; local or Ollama
│   ├── method.py       # example complaints, classifier, gate, model step
│   ├── store.py        # topics.db: runs, units, matches
│   └── check.py        # pv check-matching, with its fixtures in acceptance/
├── report/             # pv report
│   ├── data.py         # the latest run as counts per topic and period
│   ├── text.py         # dates, quotes, lozenges and sentences
│   ├── parts.py        # pieces every page shares: tables, tiles, method, footer
│   ├── overview.py     # the overview page
│   ├── team.py         # a team page
│   ├── member.py       # a member's report
│   ├── blocks.py, svg.py   # Confluence storage markup; SVG charts
│   └── build.py        # the page tree: build, write, publish
└── publish/            # Confluence REST: client, storage format, pv publish
tests/                  # python -m unittest discover -s tests
```

`ingest.models.Review` is the contract between ingestion and everything downstream.
When reviews arrive from an internal feed instead of the Play Store, only
`ingest/` changes.

JSONL stays the raw landing zone. `data/reviews.db` is rebuilt from it every
run and `data/cache.db` only holds model output, so losing either never loses
data. `data/topics.db` is the one file worth backing up besides the archive.

## Trends: always divide by the corpus

October 2024 alone holds 1,663 negative reviews, 35× the ~48/month baseline,
so on raw counts every topic spikes that month. The report counts each topic
per period against its own usual level and tests the change, rather than
comparing raw counts across months.
