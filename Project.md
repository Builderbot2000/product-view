# Product View

Periodically aggregate Google Play Store reviews, semantically cluster them into
**pain points**, and publish a browsable dashboard on Confluence so the product
team can see what users are complaining about without reading raw review feeds.

Status: **demo / proof of concept.** Data is scraped semi-manually from the Play
Store so the ingestion layer can later be swapped for proper internal data
plumbing without touching the rest of the pipeline.

**Reference app for the demo: RBC Mobile** —
[`com.rbc.mobile.android`](https://play.google.com/store/apps/details?id=com.rbc.mobile.android&hl=en_CA),
`country=ca`, all locale partitions. 21,506 text reviews spanning 2011–2026. Real
scale, a bilingual market that exercises the translation path, and a domain where
pain points are specific enough ("e-transfer fails", "biometric login broken after
update") to tell good clustering from bad.

---

## 0. Current state — read this first

Written as a session handoff: everything below was established by running things,
not by reasoning about them. A fresh session should not need to re-derive any of it.

### What is built

| Stage | Status |
|---|---|
| (A) Fetch | **Done.** `pv fetch --all-langs`, `pv langs`, `pv export`, `pv info` |
| (B) Store | **Done.** `pv db build` → SQLite, 21,506 rows |
| (B2) Translate | **Done.** `pv translate` — detect + fr→en, cached |
| (C) Embed | **Done.** `pv embed` — splits every review into fine segments, 45,839 cached vectors |
| (D) Cluster | **Done.** `pv cluster` — re-joins segments into complaint units, then leiden / agglomerative / hdbscan, `--compare` |
| (E) Label | **Done.** sentence titles (extractive, keyword-anchored), c-TF-IDF keywords, medoid, LexRank, MMR — no LLM |
| (D/E) LLM grouping | **Spike, 2026-10-08/09.** A local model (Qwen3.5 9B via Ollama) cuts each review into problems and checks them against quality rules; embeddings and Leiden then group the problems, to replace (D) and (E). Cut, rules and Leiden-on-statements work on one 200-review sample (grab-bags remain, nothing scored). Scripts `spike/llm_extract.py`, `llm_refine.py`, `llm_cluster.py`, not wired into `pv run`. Trial log, current design and open problems: [llm-trials.md](llm-trials.md) |
| End to end | **Done.** `pv run [--fetch]` — rebuilds `reviews.db` clean, then translate → embed → cluster every stream in config |
| Config | **Done.** [config.yaml](config.yaml); flag > config > built-in default; unknown keys are an error |
| Container | **Built and verified 2026-09-29** on Docker Desktop 4.30 (Windows). Image 1.46 GB, torch `2.14.0+cpu`. `pv run` in the container took 1m49s on warm caches: 43 negative / 51 positive pain points. The resulting `reviews.db` passes `integrity_check`, and host and container `pv painpoints` output match. [Dockerfile](Dockerfile) + [compose.yaml](compose.yaml) |
| (F) Render | **Demo version built 2026-10-03 (uncommitted).** `pv report [--publish]` builds a **periodic** page tree in Confluence storage format: a hub (every area) and one page per role (only that role's areas), with SVG charts. Live on the demo site. Decisions, page plans and progress: [report-design.md](report-design.md); remaining work: "Remaining work" below |
| (G) Publish | **Built 2026-09-30 (`ff32053`); extended 2026-10-03 (uncommitted).** `pv publish FILE` takes HTML (converted) or a storage-format `.xhtml` (passed through, full width, attachments read from its folder). `publish_tree` publishes a parent page then its children. Transient 5xx on attachment writes are retried. No tests yet. See §2 (G) |

Code lives in [src/product_view/](src/product_view/): [cli.py](src/product_view/cli.py)
(parsing + ingest), [commands.py](src/product_view/commands.py) (clustering stage + `run`),
[config.py](src/product_view/config.py) (YAML loading),
[models.py](src/product_view/models.py), [archive.py](src/product_view/archive.py),
[store.py](src/product_view/store.py), and the
[ingest/](src/product_view/ingest/), [lang/](src/product_view/lang/),
[embed/](src/product_view/embed/), [cluster/](src/product_view/cluster/),
[render/](src/product_view/render/) and [publish/](src/product_view/publish/)
packages. Report curation (labels, areas, roles) is in [curation.yaml](curation.yaml).

### Environment

- Python 3.12.10, venv at `.venv/`, package installed editable (`pip install -e .`).
- Entry point: `.venv/Scripts/pv.exe` on Windows, `.venv/bin/pv` elsewhere.
- Runtime deps: `google-play-scraper` 1.2.7 plus the clustering stack — `numpy`,
  `scipy`, `scikit-learn`, `sentence-transformers`, `transformers`,
  `sentencepiece`, `py3langid`, `python-igraph`, `leidenalg`, `platformdirs`,
  `pyyaml`. Optional extra `[umap]`, not required and not built.
- **Git, branch `main`.** `5bec9b9` (2026-09-30) covers stages A–E; `ff32053`
  adds `pv publish` and the first Confluence probe.
- **`torch` dominates the install and is easy to get wrong.** Windows and macOS
  resolve to the ~250 MB CPU wheel; plain `pip install` on **Linux pulls the
  ~2.5 GB CUDA build** — use `--index-url https://download.pytorch.org/whl/cpu`.
- Models cached under `platformdirs.user_cache_dir()`: `all-MiniLM-L6-v2` (~90 MB),
  `opus-mt-fr-en` (~301 MB). One-off; a cold first run is downloading, not hung.
- **LLM spike only:** Ollama 0.40.1 (installed with winget, serves on
  `127.0.0.1:11434`) with `qwen3.5:9b` pulled (6.6 GB). Dev laptop GPU: RTX 4060
  Laptop, 8 GB. Not in the Docker image.
- Data on disk, all gitignored:
  - **Source, never deleted by the pipeline:** `data/raw/` (18 locale JSONL files
    + per-locale `.state.json`), `data/meta/` (listing snapshots), `data/export/` (CSV).
  - `data/reviews.db`: reviews, runs, pain points. **Deleted and rebuilt on every
    `pv db build` / `pv run`**, so it only ever holds the current result. `pv cluster`
    also replaces the previous run for its stream instead of piling up beside it.
  - `data/cache.db`: translations (by `review_id`) + segment vectors (by
    `review_id`, position). Survives the
    rebuild, because recomputing it costs ~20 min of translation plus a few minutes
    of encoding. Delete it only to force re-translation or re-embedding.

### Verified facts about the data

| | Value |
|---|---|
| Corpus | **21,506** reviews, `country=ca`, 18 locale partitions |
| Date range | 2011-10-02 → 2026-09-22 (fifteen years) |
| Mean score | 2.63 (vs 3.78 displayed on the listing) |
| Score split | 1★ 9,269 · 2★ 2,411 · 3★ 2,250 · 4★ 2,151 · 5★ 5,425 |
| Negative stream (≤3) | 13,930 total, 13,050 at ≥20 chars |
| Positive stream (≥4) | 7,576 total, 4,898 at ≥20 chars |
| Language (detected on text) | 91.9% English · **7.4% French (1,335)** · 0.2% non-Latin (42) |
| Duplicate text | negligible — 6 instances corpus-wide |
| Reviews >256 tokens | 7 of 17,948 (0.04%) |

**Completeness is proven, not assumed.** Per-score filtered walks
(`filter_score_with=N`) exhaust at exactly the counts we hold; a `filter_score_with=5`
walk returned 4,654 and zero were missing. `MOST_RELEVANT` and `RATING` sorts surface
nothing new. The corpus now exceeds Play's own ~20,206 text-review figure for Canada.

### Verified facts about the clustering stage

Measured on the real corpus, not estimated:

| | Value |
|---|---|
| Clustering streams | negative **13,030** · positive **4,876** (after 20/22 non-Latin drops) |
| Detected French | **1,335** reviews translated; 42 non-Latin dropped and reported |
| Cached segment vectors | **45,839** from 17,906 reviews (`all-MiniLM-L6-v2`, 384-dim, L2-normalized) |
| Complaint units | negative **32,723** (2.5 per review) · positive **9,248**, at merge ≥ 0.45 |
| Negative clusters | **43** at `balanced`, **0 reviews uncovered** (current `reviews.db`, run of 2026-09-29) |
| Positive clusters | **51** at `balanced`, **0 reviews uncovered** (same run) |
| Presets land in band | broad **18** · balanced **47** · fine **80** (whole-review run; not re-measured on units) |
| Sentences in negative stream | 32,785 — 2.5× the review count, so LexRank is capped |

The French figure is **1,335, not the 1,024** an accent-based heuristic found in the
earlier session: it cannot see French written without accents, which is common in
short mobile reviews. Detecting on the text itself closes that ~30% gap.

**The corpus is dominated by two incidents.** October 2024 holds **1,661 negative
reviews — 35× the ~48/month baseline**; March–May 2016 holds ~1,473 at ~11×. The
top 3 months are 21% of the negative stream. Every cluster therefore spikes in
Oct 2024 on raw counts, which is why each run stores corpus-wide monthly totals
beside each pain point's series: only the *share* separates the pain points that
drove an event from those carried along by it.

Clustering is **deterministic** — two runs at the same seed produced identical
titles, impacts, and all 13,021 memberships (whole-review run). The unit run
of 2026-09-24 reproduced the same 42 negative / 52 positive clusters
(resolutions 1.732 / 3.519) and impacts on a second pass. The run of
2026-09-29, which is in the current `reviews.db`, gives 43 / 51. The cause of
the shift was not recorded.

**Timings, unit pipeline** (CPU): `pv embed` from cold **4m14s** for 45,839
segments; `pv cluster` negative **1m45s**. **Whole-review timings** (13k stream, CPU): exact kNN 2.4s · leiden 0.5s/fit · hdbscan
13.8s/fit · agglomerative 61s/fit. With vectors cached, `pv cluster` takes ~2–3 min
per stream: the fit is seconds and LexRank synthesis takes the rest. A warm-cache
`pv run` took **3m47s** for both streams. `--compare` runs a full search per
strategy and took **~45 minutes**.

**`pv cluster --compare` settled the strategy choice on evidence** (whole-review run). Leiden 47
clusters at **0.1% noise**; agglomerative 43 at 15.7%; **HDBSCAN collapsed to 2
clusters and 98.1% noise** — the 384-dimension density failure the design
predicted. HDBSCAN posts the *best* cohesion and silhouette precisely because it
kept only two tiny dense blobs, which is why noise share is reported beside every
quality metric.

### Play API behaviour worth knowing

These cost real time to discover:

- **`lang` partitions the review set, and partitions hold different reviews.** Fetching
  only `en` silently lost 2,486 reviews (13%). Always `--all-langs`.
- **`lang` is *not* the review's language.** It selects a listing. The `zh` partition is
  222/276 plain ASCII English; `fr` mixes French and English. Detect language from text.
- **Partitions overlap** — `zh-CN` returns the same reviews as `zh`; several codes
  (e.g. `so`) fall back to the English pool. All reads dedupe by `review_id`.
- **`ratings` is global (48,934); `reviews` is per-country** (Canada 20,206, US 860,
  GB 103). Do not treat them as the same denominator.
- **The histogram is approximate.** It reports 1,913 two-star ratings globally while our
  Canadian slice holds 2,411 two-star text reviews — impossible if exact. Display it;
  never compute with it.
- `reviews_all()` exists but buffers everything with no resume — never use it.
- `_ContinuationToken` has `__slots__` and no `__dict__`. Reconstruct it by passing all
  seven slots positionally in order; a partial reconstruction silently returns nothing.

### Development gotchas

- **Windows console encoding.** Printing review text raises
  `UnicodeEncodeError: 'gbk' codec` — the corpus is full of emoji and accents. Prefix
  ad-hoc scripts with `PYTHONIOENCODING=utf-8`. Library code already opens every file
  with an explicit `encoding="utf-8"`, and `cli.main()` now reconfigures stdout to
  UTF-8 so `pv painpoints --detail` survives a default console.
- **scikit-learn's HDBSCAN picks the wrong algorithm at 384 dimensions.** `"auto"`
  selects a ball-tree, which degenerates: measured **54.2s vs 2.4s** for
  `algorithm="brute"` on 6,000 vectors. Cost is flat in `min_cluster_size` either
  way, because the expense is building the hierarchy, not extracting clusters.
- **MarianMT defaults to 4-way beam search**, and batches pad to their longest
  member. Translating ~1,300 French reviews ran **over 65 minutes** unsorted and
  unfinished; length-bucketing the batches cut it to **~20 minutes**. Not "a few
  minutes on CPU" as originally estimated.
- **`CountVectorizer(min_df=...)` counts documents, and in c-TF-IDF each document
  is a whole cluster.** Anything above 1 silently drops the terms unique to a
  single cluster — precisely what the method exists to surface.
- **Short-text language detection needs a *low* confidence floor.** py3langid
  returns Oromo at 0.06 for "Good", but correctly calls "Très bonne application"
  French at 0.83. An over-tight floor (0.95) forced real French to English and
  produced a French-titled cluster on the positive stream.
- **HuggingFace reports inflated model sizes.** Its blob listing sums duplicate formats
  (safetensors + pytorch bin + OpenVINO). `paraphrase-multilingual-MiniLM-L12-v2` lists
  1,530 MB but downloads 471 MB. Take the max single weight file, not the sum.
- **`Path.read_text()` without an encoding reads GBK on this machine** and fails
  on any UTF-8 file holding `…` or similar. Ad-hoc scripts need
  `encoding="utf-8"` or `python -X utf8`.
- **Prompt examples get copied.** With banking examples in the extraction
  prompt, Qwen3.5 9B reused one example phrase word for word in 33 of 44
  reviews, which faked clean grouping. Prompt examples come from an unrelated
  domain (food delivery). See [llm-trials.md](llm-trials.md) trials 1–2.
- **Qwen3.5 thinks by default.** Send `"think": false` to Ollama, or reasoning
  text costs time and can leak into the output.
- **Check `abi3` when auditing wheels.** `igraph` and `leidenalg` ship `cp38-abi3` /
  `cp39-abi3` wheels covering Windows, macOS x86_64/arm64, and Linux. A naive grep for
  `cp312` reports zero and wrongly suggests a source build.

### Decisions already settled (do not relitigate)

1. ~~**No LLM anywhere.**~~ **Superseded 2026-10-08:** embedding clusters group
   by tone, not topic, so grouping moves to a **local** LLM (Qwen3.5 9B through
   Ollama). It stays fully local and needs no credentials; review text still never
   leaves the machine. Determinism now rests on temperature 0 plus a per-review
   cache. Pending compliance approval of the model. See [llm-trials.md](llm-trials.md).
2. **Positive and negative clustered separately.**
3. **Cluster all history; report one period.** Old issues form clusters, which keeps
   issue definitions stable, but the report counts only the reporting period (default
   28 days) against the periods before it (report-design.md D15). `impact` still
   exists for `pv painpoints` but no longer ranks anything in the report.
4. **Translate French → English, then embed with `all-MiniLM-L6-v2`** rather than using
   a multilingual embedder. Reason: extractive quotes must be readable by an
   English-speaking PM.
5. **Pluggable cluster strategies** (`leiden` default) behind one interface, one shared
   output schema, one granularity knob.
6. **The report is split by product area, and roles read areas** (report-design.md
   D16). Areas and roles are a lookup in `curation.yaml`, not stored data.

### Still open

- ~~**What renders in Confluence.**~~ **Settled 2026-10-03** on
  kevintangcyberium.atlassian.net, space `MFS`, by reading each page in the
  browser and through the REST `view` body. Two probes:
  - **Probe 1, HTML through `pv publish`** (page 98532, from
    [ProbeDashboard.html](spike/confluence-probe/Product%20View%20Probe/ProbeDashboard.html)).
    Survives: headings, bold/italic, inline code, links, lists, blockquote,
    tables, `<pre>`, superscript, `text-align`, emoji/French/CJK, `<hr>`,
    inline SVG and data: URI images (both become attachments), `<details>`
    (becomes an expand). Inline `color` survives (Confluence rewrites it to
    its own colour id). **Lost:** `<style>` and classes, flexbox and grid,
    `<div>`-drawn bars, scripts, inline `background`. **Broken:**
    `href="#id"` anchors (Confluence prefixes heading ids) and relative links
    to other pages. Page title: the HTML `<title>`.
  - **Probe 2, raw storage format**
    ([spike/build_confluence_probe_native.py](spike/build_confluence_probe_native.py),
    page 294964). **All render:** full-width page (content properties
    `content-appearance-published` / `-draft` = `full-width`, set over REST);
    `ac:layout` sections (`three_equal`, `two_right_sidebar`, …);
    `panel` with `bgColor` / `borderColor` (works as a KPI tile); styled SVG
    attachments (fonts, colours and text labels intact); `status` lozenges in
    all six colours, inline in tables too; `info` / `note` / `warning` / `tip`;
    `data-highlight-colour` on `<td>`; `<colgroup>` column widths; text
    `color` and `background-color` on spans; named `excerpt`; `anchor` macro +
    `ac:link ac:anchor`; `ac:link` to a page by title; `expand` holding a
    table; `toc`; `<time>`; emoticons; `code`; `details` (page properties);
    `chart` (renders, but the look is dated). Not yet tested:
    `excerpt-include` across pages, @mentions.
  - **Conclusion:** the renderer writes storage format directly. HTML
    conversion caps the page at plain tables. Charts are our own SVGs, not the
    `chart` macro.
  - The zip import route is retired: REST replaced it on 2026-09-30.
- **Which Confluence space.** `confluence.space` is still `null` in
  config.yaml. The demo site (since 2026-10-03) is
  kevintangcyberium.atlassian.net, which has only `MFS` and a personal space;
  `pv publish` can't create a space. The earlier site,
  skenshin2000.atlassian.net, held the space "product view test".
- Who owns the scheduled run. Delivery to team members (page @mentions plus
  Slack links) is deferred until after the demo.
- **Generic clusters at the top of the ranking — built 2026-09-24.** On the
  whole-review run of 2026-09-23 the top three negative pain points were "bank
  rbc", "mobile banking" and "royal bank". There were three causes:
  1. *Fragmentation, hidden by the titles.* The Oct 2024 device-compat /
     forced-update incident (~825 reviews) was split across 8 clusters. The rule
     that titles must be unique pushed the extras onto phrases like "royal bank".
  2. *Whole-review embeddings.* Long reviews that raise several problems
     (3.9–4.5 sentences) embed near the corpus centre: "RBC is bad".
  3. *The ranking rewards being generic.* Recency-weighted volume (0.40)
     favours clusters that collect a steady slice of all traffic.

  Merging clusters with close centroids was ruled out: the generic, device and
  login clusters are all tightly packed (`new phone` ↔ `garbage app` 0.852).

  **What was built:**
  - `pv embed` splits reviews finely ([segment.py](src/product_view/embed/segment.py)).
  - `pv cluster` re-joins adjacent segments into complaint units
    ([units.py](src/product_view/cluster/units.py)) and clusters those units.
    A review can sit in several pain points, and `size` counts distinct
    reviews.
  - Titles are real user sentences, anchored to the top keyword. For example:
    "The remember me option does not work", "Keeps telling me to update. there
    are no updates available", "Does not support GrapheneOS, so I cannot use
    it".
  - A new `sole_share` column.

  **Still open:**
  - **Impact still ranks generic complaints first, by design.** The weights
    are unchanged; `sole_share` is the column for demoting them (`pv
    painpoints --sort sole_share --asc`). Generic clusters sit at 0.04–0.13:
    "It is frustrating", "It needs to be fixed", "This app is terrible". The
    signal has false positives, though: "Customer service is of no help
    either" scores 0.09, and "When you take the picture manually the app
    crashes" scores 0.08. Whether and how to fold it into `impact` is the next
    decision.
  - **Extractive titles can mislead on tone.** "The app works alright for
    banking" and "The new app looks nice" title negative clusters, because
    the words are central even though the reviews are complaints.
  - **Some titles are fragments,** e.g. "Says it sends verification" for the
    2FA cluster.
  - **Merge threshold not tuned.** The 0.45 is from the prototype.
  - **Leftover cache table.** `cache.db` still holds the old whole-review
    `embeddings` table (~27 MB), which nothing reads now. It is safe to drop.
- Cross-run pain-point matching: **solved for the report by anchors, not
  centroid matching** (2026-10-03). Each curated label in `curation.yaml` lists
  anchor reviews (the medoids of its clusters when curated). On every run a
  cluster takes the label whose anchors it holds, so hand labels survive the
  re-clustering every scheduled run does. Period-over-period comparison needs no
  matching: one run spans all history, and the report slices it by date.

### Remaining work

Recorded 2026-10-03, after the periodic, role-split report went live. Detail
for the report items is in [report-design.md](report-design.md) §6.

**Report (F)**
1. **Quote quality.** A period quote is the review's most central unit in the
   cluster, which is sometimes off-topic (a translated cheque-photo review
   under "App won't open"). Prefer units above a similarity floor.
2. **Validate areas and roles with the team.** The five roles (UI & design,
   Sign-in & security, Payments, Engineering / QA, Support / CX) and eight
   areas in `curation.yaml` are a first guess at the org.
3. **Labels from the company-approved internal model** (D6), replacing hand
   labels. Overtaken by the LLM grouping spike (2026-10-08): a local Qwen3.5 9B
   names issues as part of grouping them ([llm-trials.md](llm-trials.md)).
   Whether compliance approves that model is still open.
4. **Curating new clusters.** Uncurated clusters show "auto-labelled" and are
   filed by keyword. Add a helper that prints a `curation.yaml` stub (label,
   kind, areas, anchor), and decide who maintains the file.
5. **Release periods** ("since 4.67") as an alternative to fixed 28 days.
6. **Developer-reply rate** per issue for the Support / CX page.
7. **Stale attachments.** Republishing leaves unreferenced charts from older
   versions on a page; attachment sync could delete what the page no longer
   references.
8. Deferred: per-issue pages; `excerpt-include` (untested, not needed while
   every page is generated).

**Publish (G) and running**
9. **Tests** for `render/` and `publish/` (none yet).
10. **Wire `pv report --publish` into `pv run`** and the scheduling recipes.
11. Set `confluence.space` in config.yaml (still `null`; the demo uses
    `--space MFS`).

**LLM grouping (spike)**: build tier 2 (issues within an area) and a
hand-labelled set of ~100 reviews to score it; then decide whether it
replaces (D) and (E). Open problems are listed in
[llm-trials.md](llm-trials.md).

**Clustering (D)**, now lower priority because the report no longer ranks
by impact, and possibly replaced by LLM grouping: impact weights and `sole_share`; merge threshold 0.45 untuned;
drop the leftover `embeddings` table in `cache.db` (~27 MB).

**After the demo (delivery)**: a proper service account or OAuth app instead
of an employee's token; @mentions and Slack links; write access to the
team's space.

**Housekeeping**: the report work after `ff32053` is now committed. Milestone 1
checks 1–17 and 20 are still unrecorded.

---

## 1. Goals and non-goals

### Goals (demo)

- One command takes an app ID and produces a Confluence-ready dashboard.
- Runs unmodified on Linux, macOS, and Windows.
- Clusters are *semantic*, not keyword buckets — "app keeps logging me out",
  "session expires constantly", and "have to sign in every time" land together.
- Every pain point is traceable back to the individual reviews behind it.
- Incremental: re-running fetches only new reviews and updates the dashboard.
- Ingestion is one swappable module, so the future internal feed drops in cleanly.

### Non-goals (demo)

- No hosted service, no scheduler daemon, no auth system. Scheduling is a cron
  entry / Task Scheduler job / manual run.
- No multi-app tenancy, no iOS App Store, no per-user accounts.
- No fine-tuned or custom-trained models.
- No write-back to Jira or ticket creation.

### Success criteria

The product team opens a Confluence page and, within about a minute, can say
"these are the top 10 things users are unhappy about this month, and here is how
each one is trending" — with enough example reviews to trust the label.

---

## 2. Pipeline

```
fetch ─▶ store ─▶ translate ─▶ embed ─▶ cluster ─▶ label ─▶ render ─▶ publish
 (A)      (B)        (B2)        (C)       (D)        (E)       (F)       (G)
```

Each stage is a CLI subcommand and reads/writes through the store, so any stage
can be re-run in isolation. That matters for iteration: re-clustering should not
require re-scraping or re-embedding.

### (A) Fetch — `pv fetch`

**Library: [`google-play-scraper`](https://pypi.org/project/google-play-scraper/)**
(JoMingyu) — the maintained standard for this. Pure Python, hits the same
internal endpoints the Play web client uses, so there is no Selenium, no
headless Chrome, no chromedriver version-matching, and no API key. That matters
directly for the cross-platform requirement: a browser-driven scraper is the
single most likely thing to break on a teammate's Windows box.

Rejected alternatives: `play-scraper` (unmaintained, HTML-parse based, breaks on
every Play redesign), and anything Selenium/Playwright-driven (heavyweight
install, brittle, and far more conspicuous as traffic).

Pull mechanics:

- `reviews()` with an explicit `continuation_token` loop, **not `reviews_all()`**.
  `reviews_all()` buffers everything in memory with no checkpointing and no
  resume — at RBC's volume, one network blip loses the entire run.
- 200 reviews per request (the endpoint's ceiling), `sort=Sort.NEWEST`.
- Persist the continuation token to the `runs` table each page, so an
  interrupted fetch resumes instead of restarting.
- Stop on the first review ID already in the store, plus an overlap window of a
  few pages to catch edited reviews.
- Deliberate `sleep` between pages (default ~1s) and a retry with backoff on
  HTTP 429/5xx. Low and slow — there is no deadline on a weekly job.
- Config: app ID, languages, countries, review cap, sleep interval.

**Scale note — measured, 2026-09-23.** Full backfill across all locale partitions
yields **21,506 reviews for `ca`, dated 2011-10-02 through 2026-09-22.** Mean score
2.63; 9,269 one-star; **13,930 at score ≤ 3**, which is the pain point corpus.

**Play partitions reviews by `lang`.** The first backfill fetched only `en` and
silently missed 2,486 reviews (13%) — 1,729 of them French. Partitions also
overlap (`zh-CN` duplicates `zh`; several codes fall back to the English pool), so
reads merge and dedupe by `review_id`. `pv langs` probes for unfetched locales.

Two planning assumptions were wrong and are corrected here:

- *"The endpoint won't serve deep history."* It served fifteen years. The
  archive-accumulation argument for keeping every run still holds for tracking
  trends going forward, but it is not needed to obtain history — that arrives on
  the first pull.
- *"Cap the first run around 10k."* Unnecessary. The whole locale is ~19k, which
  is a single ~20-minute polite run at 0.6s between pages.

**The 48.9k figure is ratings, not reviews.** Only ~20.2k of those raters wrote
text, and we now hold 21,506 — at or above complete. The corpus means 2.63 against
a displayed 3.78 because ~85% of 1-star raters write text versus ~19% of 5-star
raters. The dashboard must show the store histogram beside the corpus distribution
and never conflate them; `fetch` snapshots that histogram to `data/meta/` every run.

Every run after the backfill is a cheap incremental top-up.

- **Swap point**: `ingest/base.py` defines `ReviewSource.fetch() -> Iterable[Review]`.
  The Play scraper is one implementation; the future internal feed is another.
  Nothing downstream imports the scraper.

Semi-manual by design: someone runs the command (or a scheduled job) rather than
a service polling continuously. Keeps us off anything that looks like
high-volume automated scraping and keeps the demo dependency-light.

### (B) Store — SQLite

Stdlib `sqlite3`, no ORM. Cross-platform, zero setup, and trivially replaceable
by a real warehouse later. Two files, split by what they cost to recreate:

```
data/reviews.db   -- rebuilt clean from the JSONL archive on every db build / run
  reviews(review_id PK, app_id, source, lang, country, content, score,
          thumbs_up, created_at, app_version, ..., content_hash)
  app_metadata(fetched_at PK, app_id, score, ratings, reviews, histogram_json,
               installs, version)
  runs(run_id PK, ..., polarity, algorithm, params_json, stream_size,
       unclustered, corpus_monthly_json)
  pain_points(run_id, pain_point_id, title, message, <17 sortable columns>, ...)
  pain_point_members(run_id, pain_point_id, review_id, unit_seq, unit_text, similarity)

data/cache.db     -- model output, survives rebuilds; ATTACHed as `cache`
  translations(review_id PK, detected_lang, confidence, content_en, model,
               translated_at)
  segments(review_id, model, seq, splitter, text, dim, vector BLOB,
           PRIMARY KEY(review_id, model, seq))
```

The full schema and the reasoning for flat columns are in
[aggregation-plan.md](aggregation-plan.md#storage-sqlite).

**The database never accumulates history.** It is derived data, so every
`pv run` starts from an empty `reviews.db`, and `pv cluster` replaces its stream's
previous run. Trend lines don't need old runs: all 15 years are clustered in
one pass, so each pain point's monthly series comes from its own members' dates.
Comparing one week's clustering with the next would need old runs, and cross-run
matching isn't built. Keeping snapshots for it is a decision for later.

Dedupe on `review_id`; `content_hash` catches edited reviews.

### (B2) Translate — `pv translate`

**Play's `lang` partition does not indicate a review's language.** The `zh`
partition is 222/276 plain ASCII English; the `fr` partition mixes French and
English freely. Locale selects a *listing*, not a language — so nothing can be
routed by partition, and every review is language-detected on its own text.

Measured composition, detected on the text of the 17,948 reviews of ≥20 chars:

| | Reviews | Share |
|---|---|---|
| English | 16,491 | 91.9% |
| **French** | **1,335** | **7.4%** |
| Other Latin (es 34, pcm 12, it 3, …), passed through | ~80 | 0.4% |
| Non-Latin (Arabic 15, Cyrillic 14, CJK 11, Devanagari 1, Hebrew 1) | **42** | **0.2%** |

An earlier accent-based estimate put French at 1,024; it misses French written
without accents, which is common in short mobile reviews.

- **Detect** with `py3langid` (pure-Python wheel, ~2 MB).
- **Translate French → English** with `Helsinki-NLP/opus-mt-fr-en` (MarianMT,
  ~301 MB). A dedicated bilingual model beats any many-to-many model at fr→en.
  The 1,335 reviews took **~20 minutes** on CPU even with length-bucketed batches.
  The result is saved in `cache.db`, so later runs translate only new French reviews.
- **Drop the 42 non-Latin-script reviews** and report the count. A second 310 MB
  `mul-en` model to rescue forty reviews is not a trade worth making; dropping
  them *silently* would be the actual mistake.
- Store `content_en` beside `content` — the original is never overwritten.

**Why translate rather than use a multilingual embedding model.** With about 8%
non-English and nearly all of that one language, translating up front wins on three
counts: the English-only `all-MiniLM-L6-v2` is the stronger model for the ~92%
majority; total weight is slightly *lower* (90 MB + 301 MB against 471 MB); and
— decisively — **the dashboard becomes readable.** Synthesis is extractive, so a
French cluster's quotes would otherwise render in French to an English-speaking
PM: evidence they cannot act on.

**The honest cost:** French reviews pass through two lossy steps instead of one,
and MT errors land on exactly the domain vocabulary that defines a pain point
("virement Interac"). The dashboard must label auto-translated quotes as such and
keep the French original available, or the "every word traces to a real review"
guarantee quietly stops being true.

### (C) Embed — `pv embed`

- `sentence-transformers` with **`all-MiniLM-L6-v2`** (~90 MB, 384-dim) — runs
  locally on CPU, no API key, no data leaving the machine.
- Embeds `content_en` from stage (B2): the original text for English reviews, the
  translation for French ones. So the English-only model covers 100% of the corpus.
- Native `max_seq_length` is 256, and only 7 reviews of 17,948 exceed it — no
  chunking needed.
- Optional: a hosted embedding provider behind the same interface for quality
  comparison, enabled by config, off by default.
- **Encodes segments, not reviews.** Each review is split at sentence and clause
  boundaries ("but", "however", "also", ";") into fine segments, and each segment
  is encoded and cached by `(review_id, model, seq)` along with the splitter
  version. Changing the split rules re-encodes only the reviews they affect.

Local-first is the right default here: the demo must run on a laptop with no
company credentials, and review text is user data we would rather not ship to a
third party without a conversation first.

### (D) Cluster — `pv cluster`

- Negative-signal focus: filter to reviews scoring ≤ 3 by default (configurable —
  positive clustering is useful too, just not the point of this tool).
- **The unit clustered is a complaint, not a review.** Each review's cached
  segments are walked in reading order. A segment joins the unit before it when
  its vector is within `merge_threshold` (default 0.45) of that unit's
  centroid. The result is one unit per complaint, however many sentences the
  user took to say it. Because this runs at cluster time, tuning the threshold
  never requires re-embedding. Statistics count distinct reviews, and
  `pain_point_members` keeps the unit text that placed each review.
- **Pluggable strategies behind one interface**, all emitting the identical
  `PainPoint` output so switching is a flag, never a code change: `leiden`
  (default — community detection on the cosine kNN graph, the vector-database-native
  approach), `agglomerative` (scikit-learn only, gives a free hierarchy),
  `hdbscan` (explicit noise class, also stdlib-free), and optional `hdbscan+umap`.
  Cluster quality on real review text is hard to predict from theory, so
  `pv cluster --compare` runs them side by side on the same embeddings.
- **One granularity knob across all of them.** Each algorithm exposes granularity
  through a different native parameter (`resolution`, `distance_threshold`,
  `min_cluster_size`), which would make them incomparable. Instead granularity is a
  target cluster count — default band 40–60 — and the runner binary-searches each
  strategy's native knob to hit it. Presets: `broad` 15–25, `balanced` 40–60,
  `fine` 80–120.
- Noise is removed by post-filtering (minimum size, plus a cohesion floor on mean
  cosine to centroid) rather than by the algorithm, so every strategy handles it
  identically. The unclustered count is always reported — hiding what fraction of
  feedback the analysis misses is the fastest way to make the tool untrustworthy.
- Outputs cluster assignments plus per-review distance to centroid, used to pick
  the most representative example reviews for the dashboard.

### (E) Label — `pv label`

Turn a numbered cluster into something a PM can read.

**Fully algorithmic — no LLM.** Every word shown traces back to a real review,
which also means no API key, no cost, no review text leaving the machine, and
deterministic output that does not drift between runs.

*Since 2026-10-08 a local-LLM replacement for (D) and (E) is being trialled,
because these extractive titles name tone clusters, not issues. See
[llm-trials.md](llm-trials.md). This section describes what `pv run` does today.*

- **Title** — a real user sentence: the most central 3–10-word complaint unit
  containing one of the top 3 c-TF-IDF keywords. Leading connectives and
  keyboard stutter are stripped, and fragments that start mid-sentence are
  avoided.
- **Keywords** — c-TF-IDF: treat each cluster as one document and score 1–3 grams
  against the other clusters, surfacing what makes *this* cluster distinctive
  rather than merely what is frequent.
- **Canonical quote** — the **medoid**, the actual review closest to the centroid.
  The most typical statement of the pain point, in a user's own words.
- **Message** — graph-centrality extractive summarization (LexRank): embed the
  cluster's sentences, rank by PageRank centrality over the similarity graph, then
  select 2–3 under **MMR** so they are central *and* non-redundant.
- **Supporting quotes** — 5 reviews chosen by MMR against the centroid. Without
  MMR you get five near-identical sentences; with it you get the range of phrasing.
- Cached per `(run_id, cluster_id)` so re-rendering costs nothing.

### (F) Render — `pv report`

**Full decisions, page plans and progress: [report-design.md](report-design.md).**

**Built 2026-10-03.** `pv report` writes Confluence storage format plus SVG
charts, one folder per page under `out/report/`; `--publish` pushes the tree
(hub first, role pages under it). HTML is not emitted: the probes showed HTML
conversion drops every layout and styling feature (§0 "Still open").

- **Periodic.** The report covers one period (default 28 days, ending on the
  newest review's day) against "usual", the mean of the 6 periods before it.
  A count is *up* or *down* only if a Poisson test at the usual rate says so
  (p < 0.05, at least 3 reviews); negative reviews run at ~55–80 a month, too
  few for ratios. Quotes come from the period.
- **By area and role.** Issues are filed under product areas; each role reads
  some areas and gets its own page. The hub shows all areas, what changed,
  general sentiment, what users liked, and the method.
- **Curation** ([curation.yaml](curation.yaml)): areas (with keywords for
  filing uncurated clusters), roles, and labels with kind, areas and anchor
  reviews. Clusters under one label merge; counts are distinct reviews.
- **Code** ([render/](src/product_view/render/)): `blocks.py` (storage
  helpers), `svg.py` (sparklines, area chart), `issues.py` (period, change
  test, label matching, areas), `pages.py` (hub and role pages).

**Audience (2026-10-03).** The Mobile division product team. Primarily the
**analysts who interpret reviews**: the hub gives them evidence to compose
their own reports, and doesn't replace them. Each team gets a page with only
what it can act on. A competing internal effort on weaker models is expected
to produce text summaries and plain tables, so the demo leads with change
over time, charts and traceable quotes. **Demo first;** delivery
infrastructure comes later.

### (G) Publish

`pv publish FILE` (built 2026-09-30) pushes the HTML over REST, replacing the
manual zip import. The zip probe landed and rendered; REST is used so a run
needs no one to upload anything.

- **Overwrite in place.** The page with the same title in `confluence.space`
  is updated (a new version in its history); if none exists it is created,
  under `confluence.parent_id` if set. This settles open question 4.
- **Conversion** ([publish/storage.py](src/product_view/publish/storage.py)):
  only `<body>` is kept and re-serialized as well-formed XHTML. `<script>`,
  `<style>`, `<button>` and `on*` attributes are dropped. `<details>` becomes the
  expand macro. Local, data: URI and inline-SVG images become page attachments.
  Input must be well-formed-ish HTML (closed `<p>`/`<li>`); the renderer controls
  that.
- **Attachments are synced.** Unchanged ones are skipped, so republishing
  doesn't pile up attachment versions.
- `--dry-run` writes the storage format to `out/<name>.storage.xhtml` and lists
  the attachments, without contacting Confluence.
- Flags `--space`, `--title`, `--parent-id` override the `confluence:` section
  of config.yaml. The title defaults to the HTML `<title>`, else the filename.

**Storage passthrough and page trees (built 2026-10-03).** A `.xhtml` file
is published as-is with the attachments its `ri:attachment` elements name,
read from the same folder, and set to full width. `publish_tree` publishes a
parent then its children; an existing page keeps its place in the tree.
Attachment writes that fail with HTTP 5xx (Confluence Cloud occasionally
answers "transaction rolled back") are retried twice.

Auth: env vars `CONFLUENCE_BASE_URL`, `CONFLUENCE_USER` (account email) and
`ATLASSIAN_TOKEN`, from the environment or `.env`. Never committed, never in
config files. compose.yaml passes `.env` to the container at run time.

---

## 3. Layout

As built. Entries marked *(planned)* don't exist yet.

```
product-view/
├── project.md              # this plan + the session handoff (§0)
├── aggregation-plan.md     # clustering-stage design and measured results
├── report-design.md        # render-stage decisions: audience, Confluence vocabulary, pages, build steps
├── README.md
├── pyproject.toml
├── config.yaml             # every stage's defaults; flags override
├── curation.yaml           # report taxonomy: areas, roles, issue labels + anchor reviews
├── Dockerfile, compose.yaml, .dockerignore
├── spike/                  # milestone 1: build_confluence_probe.py + confluence-probe/ (HTML probe),
│                           #   build_confluence_probe_native.py (storage-format probe)
├── src/product_view/
│   ├── cli.py              # entry point; fetch / export / info / langs
│   ├── commands.py         # db build / translate / embed / cluster / painpoints / run
│   ├── config.py           # config.yaml loading + validation
│   ├── models.py           # Review, PainPoint — the two schema contracts
│   ├── archive.py          # JSONL archive + resume state
│   ├── store.py            # SQLite: reviews.db + attached cache.db
│   ├── ingest/
│   │   ├── base.py         # ReviewSource protocol  ← the swap point
│   │   ├── play_store.py   # google-play-scraper impl
│   │   └── csv_source.py   # (planned) offline / testing impl
│   ├── lang/               # detect.py, translate.py
│   ├── embed/              # encoder.py, segment.py
│   ├── cluster/            # units, graph, strategies, granularity, synthesize, scoring, pipeline
│   ├── render/             # pv report: blocks.py, svg.py, issues.py (periods, curation), pages.py
│   └── publish/            # pv publish: storage.py (HTML→storage), confluence.py (REST), page trees
├── data/                   # gitignored: raw/, meta/, export/, reviews.db, cache.db
├── out/                    # gitignored: probe zip, --dry-run storage format, report/ (one folder per page)
└── tests/                  # (planned) milestone 6
```

Labelling ended up inside `cluster/synthesize.py`, not in a separate `label/` package.

## 4. Cross-platform requirements

Windows is the one that breaks, so it is the one to be explicit about:

- Pure Python, no shell-outs, no platform-specific binaries.
- `pathlib` everywhere; never string-concatenate paths.
- Explicit `encoding="utf-8"` on every file open — Windows still defaults to
  cp1252 and review text is full of emoji and non-Latin scripts.
- Store timestamps as UTC ISO-8601; convert to local only at render time.
- Model and data caches under `platformdirs.user_cache_dir()`, not `~/.cache`.
- No symlinks, no case-sensitive-path assumptions.
- `pip install -e .` from `pyproject.toml`; `uv` documented as the fast path.
- CI matrix across all three OSes once there is anything to test.

## 5. Configuration

**Built.** [config.yaml](config.yaml) holds settings that are safe to commit. Secrets
go in environment variables only: today that means the Confluence credentials
(`CONFLUENCE_BASE_URL`, `CONFLUENCE_USER`, `ATLASSIAN_TOKEN`), read from the
environment or a gitignored `.env`.

- **Precedence:** command-line flag > `config.yaml` > built-in default in
  [config.py](src/product_view/config.py). Any flag config can supply defaults to
  `None` in argparse, so an unset flag can be told apart from one explicitly set.
- **Location:** `./config.yaml` if present, or `pv --config PATH <command>`. If the
  default file is missing, the built-in defaults apply. If an explicit path is
  missing, that's an error.
- **Unknown keys are an error**, not ignored. A typo like `cohesion_flor` would
  otherwise run silently with the default.
- Sections: `app` (id, country), `data_dir`, `fetch`, `corpus.min_chars` (one value
  shared by translate, embed and cluster, so they can't disagree about which
  reviews count), `cluster`, including the streams `pv run` clusters, and
  `confluence` (space, title, parent_id for `pv publish`).
- `cluster.min_cluster_size` is set per stream (`negative: 25`, `positive: 15`).
  This replaced a hidden rule that silently changed 25 to 15 for the positive
  stream, which also caught an explicit `--min-cluster-size 25`.

`report` (built 2026-10-03): `period_days` (28), `baseline_periods` (6) and
`curation` (path to `curation.yaml`). Flags `--period-days`,
`--baseline-periods` and `--curation` override them.

## 6. Milestones

| # | Milestone | Deliverable |
|---|-----------|-------------|
| 0 | Skeleton ✅ | **Done.** Repo, `pyproject.toml`, CLI, JSONL archive. SQLite deferred to milestone 3, where it earns its place |
| 1 | **Confluence spike** (partly done) | Probe built with [spike/build_confluence_probe.py](spike/build_confluence_probe.py), imported by zip and published over REST (2026-09-30). Only checks 18–19 are recorded. **Remaining:** record checks 1–17 and 20 for the REST page. *Constrains milestone 4.* |
| 2 | Ingest ✅ | **Done.** `pv fetch --all-langs` backfilled 21,506 RBC reviews across 18 locales, resumable and deduped; `pv langs` probes coverage; `pv export` → CSV; `pv info` → summary with store-listing contrast |
| 3 | Cluster ✅ | **Done.** `pv db build`, `pv translate`, `pv embed`, `pv cluster`, `pv painpoints`. Complaint-unit clustering: 43 negative / 51 positive pain points, 0 reviews uncovered, deterministic, three strategies behind one interface. Design in [aggregation-plan.md](aggregation-plan.md) |
| 4 | Render ✅ (demo, uncommitted) | `pv report` emits a periodic hub plus role pages in Confluence storage format with SVG charts (2026-10-03). Remaining: §0 "Remaining work" |
| 5 | Publish ✅ | `pv publish` over REST (2026-09-30, committed); storage passthrough, page trees and retries added 2026-10-03 (uncommitted). Still to do: wire `pv report --publish` into `pv run`, and add tests |
| 6 | Polish (partly done) | ✅ `pv run` end to end, ✅ `config.yaml`, ✅ clean database per run, ✅ container built and verified, ✅ git. Still to do: test suite, scheduling notes, CSV ingest source |

Milestone 1 is ordered ahead of the pipeline work deliberately: discovering the
storage-format restriction after building a CSS-heavy dashboard means rebuilding
the renderer.

## 7. Scheduling (demo)

No daemon. Documented recipes only. The scheduled command is `pv run --fetch`:
fetch the latest reviews, rebuild the database clean, then translate, embed and
cluster only what's new.

- Linux/macOS: `cron` entry calling `pv run --fetch`
- Windows: Task Scheduler task calling `pv run --fetch`
- Container: `docker compose run --rm pv run --fetch`, from either of the above
- Manual: run it before the weekly product sync

Weekly is the right cadence — review volume per app is low enough that daily runs
produce noise, and a week of accumulation gives clusters enough mass. Each weekly
run still *reports* a 28-day period (report-design.md D15), so the pages are a
rolling update; `pv report --publish` is not yet part of `pv run`.

## 8. Risks

| Risk | Impact | Mitigation |
|------|--------|------------|
| Confluence storage format can't carry CSS or scripts | Medium (was High) | Confirmed by the probes. Design with native layouts and macros plus SVG chart attachments instead, all of which render (§0 "Still open"). Nothing on the page can be interactive: use separate pages for views and `expand` for detail |
| `google-play-scraper` breaks on a Play redesign | Medium | Isolated behind `ReviewSource`; the JSONL archive already on disk keeps `pv run` working offline (a CSV source is planned) |
| Play Store exposes only recent reviews | Medium | Accumulate across runs. The **JSONL archive** is the long-term store, not SQLite, which is rebuilt every run |
| Generic clusters dominate the ranking | Medium | Clustering now runs on complaint units, and `sole_share` flags generic pain points. `impact` still ranks them high; see §0 "Still open" |
| Container on Docker Desktop (Windows/macOS) bind-mounts `data/` | Low | SQLite WAL on the bind mount verified on Windows: a full rebuild of `reviews.db` completed and passed `integrity_check`. Not yet exercised: writes to `cache.db` from the container (every lookup was a cache hit), and macOS. If either fails, use a named volume for the databases |
| ~~Deep backfill throttled or interrupted~~ | Retired | Full 19k backfill completed in one run, no throttling seen. Checkpointing and backoff are built and tested regardless |
| Scraping a named bank's app draws attention internally | Low | Public data, read-only, low request rate, manually triggered; worth a heads-up to whoever owns the RBC Play listing before this becomes a recurring job |
| Cluster quality poor at low volume | Medium | Tune `min_cluster_size`; fall back to a flat ranked list below a volume threshold |
| Scraping raises ToS concerns | Medium | Low-volume, manually triggered, public data; the internal-feed swap is the real answer |
| ~~Review text sent to a third-party LLM~~ | Retired | Pipeline is fully local: local embeddings, and the LLM grouping spike runs its model locally through Ollama. No review text leaves the machine at any stage |
| Compliance rejects the local model | Medium | Qwen3.5 9B is Chinese-origin (Alibaba), which some banks restrict even offline. Gemma 4 12B (Google, Apache 2.0) is the fallback, untested here |
| LLM grouping drifts between runs | Medium | Temperature 0 and seed 0, but not bit-exact across GPUs or Ollama versions. Results are cached per review and prompt version, so a review is only judged once |

## 9. Open questions

1. ~~**What renders through `pv publish`?**~~ Settled 2026-10-03 by two
   probes: write storage format directly; see §0 "Still open". Cloud is the
   target (now kevintangcyberium.atlassian.net).
2. ~~**Which app(s)?**~~ Settled: `com.rbc.mobile.android`, all `ca` locales.
   The corpus is 91.9% English, 7.4% French, 0.2% non-Latin scripts — handled by
   translating French to English in stage (B2).
3. **LLM access?** Reopened 2026-10-08. Answered for the spike: a local model
   through Ollama, so still no credentials. Open: whether compliance approves
   Qwen3.5 9B, and where Ollama runs once this leaves the laptop (the Docker
   image has none).
4. ~~**Page ownership?**~~ Settled 2026-09-30: overwrite in place. `pv publish`
   updates the same-titled page, and Confluence's version history does the
   archiving.
5. **Who runs it?** Whether the semi-manual trigger lives with one person or a
   shared scheduled job affects how much the setup docs need to cover.

None of these block starting on milestone 0.
