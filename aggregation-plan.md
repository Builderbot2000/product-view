# Aggregation: semantic clustering of reviews into pain points

> **Status: built and verified.** This was the implementation plan for milestone 3
> of [project.md](project.md); the stage now runs end to end on the real corpus.
> All figures are measured, not estimated.
>
> **Five things changed once it met real data.** They are corrected in place below,
> and each is recorded because the reasoning that produced the original is still
> worth reading:
>
> 1. **Near-duplicate collapse (Step 2) was cut.** Justified by "appears verbatim
>    four times"; measured, there are **9 exact duplicates in 13,050** negative
>    reviews. It bought nothing and made `min_cluster_size` ambiguous.
> 2. **Impact scoring was recalibrated** from `tau=180`/90-day momentum to
>    **365/365**. At 180 days only 3.6% of the stream carried any weight, and a
>    90-day window held 231 reviews — about 5 per cluster, noise at a 0.20 weight.
> 3. **Raw monthly series per pain point, plus a run-level corpus denominator**,
>    replaced the single trend ratio. October 2024 runs 35× baseline, so every
>    cluster spikes there on raw counts; only the share is meaningful.
> 4. **Pain point statistics are flat SQL columns**, so any of them can order the
>    table directly — the audience re-ranks by whichever column answers its question.
> 5. **The granularity search needed a bracketing sweep.** Plain bisection assumed
>    the post-filter cluster count is monotonic in the knob. It is not.
>
> **Superseded on 2026-09-24: clustering now runs on complaint units, not whole
> reviews.** Whole-review vectors of long, multi-issue reviews landed near the
> corpus centre and formed generic clusters that topped the ranking. Reviews are
> now split into segments, re-joined into one unit per complaint, and clustered.
> Titles are extractive user sentences. See project.md §0 "Still open" for the
> diagnosis and §2 (C)–(E) for the design. Figures and schema below describe the
> whole-review version unless marked otherwise.

## Context

Ingestion is done — 21,506 RBC Mobile reviews sit in `data/raw/`, one JSONL per locale.
The next stage turns that flat archive into **pain points**: semantic clusters of
related reviews, each one an object carrying a synthesized message, aggregate
statistics (impact, frequency, trend), and the full catalogue of its member reviews.

Two decisions shape this plan:

1. **No LLM.** Synthesis must be algorithmic — the techniques vector databases and
   retrieval systems use (kNN graphs, medoids, MMR, graph centrality), not a
   generated paraphrase. Every word in a pain point's message must be traceable to
   a real review.
2. **Positive and negative clustered separately**, so praise and complaints never
   contaminate each other's clusters.

### Finding: the rating discrepancy is explained, and the scrape is clean

The corpus skews far more negative than the Play listing's 3.8 stars. Verified against
the store's own numbers:

| | Count | Mean |
|---|---|---|
| Play **ratings** (the "48.9k") | 48,934 | 3.78 |
| Play **reviews with text** | ~20,206 | — |
| **Our archive** | 21,506 (at or above complete) | 2.63 |

Play's histogram is 57.6% five-star. Our corpus is 25.2% five-star. That gap is *not*
a scraping defect — it is the silent-majority effect: **people who are happy tap five
stars without typing anything; people who are angry write.** Roughly 85% of one-star
raters write text against ~19% of five-star raters.

Confirmed empirically rather than assumed: per-score filtered walks exhaust at exactly
the counts we hold, and the corpus now exceeds Play's own text-review figure.

Corroborating signal: 66% of positive reviews are under 20 characters ("Good", "great app"),
versus 6% of negative ones. Unhappy users write paragraphs; happy users write two words.

**Consequence for the dashboard, and it matters for PM trust:** we must never present
the corpus distribution as the app's rating distribution. The dashboard shows the true
histogram from the store *alongside* the text-review corpus, labelled distinctly, and
states that pain points are mined from text reviews which skew negative by nature.
So `fetch` will also snapshot app metadata (`score`, `ratings`, `reviews`, `histogram`,
`installs`, `version`) on every run — cheap, and it gives every later percentage an
honest denominator.

*(Minor caveat to record: Play's own histogram reports 1,913 two-star ratings globally
while our `en`/`ca` slice holds 2,226 two-star text reviews — impossible if the histogram
were exact. It is approximate or time-lagged, so treat it as a display figure, not a
denominator for arithmetic.)*

### Corpus (revised after the multi-locale backfill)

The first backfill fetched only `lang=en`. **Play partitions reviews by locale**, and
those partitions hold different reviews — 2,486 were missing (13%), 1,729 of them
French. Fixed via `pv fetch --all-langs`; corpus is now **21,506**.

| Stream | Reviews | ≥20 chars | clustered (actual) |
|---|---|---|---|
| Negative (score ≤ 3) | 13,930 | **13,050** | **13,030** — 47 pain points, 9 unclustered |
| Positive (score ≥ 4) | 7,576 | **4,898** | **4,876** — 51 pain points, 0 unclustered |

The clustered figures are the ≥20-char counts minus the non-Latin drops (20 and
22 respectively), not an estimate. Unclustered is far lower than anticipated:
Leiden assigns every node, and at `min_cluster_size=25` with a 0.35 cohesion
floor almost nothing is discarded.

### Language: measured, not assumed

**Play's `lang` partition does not indicate a review's language.** The `zh` partition is
222/276 plain ASCII English; the `fr` partition mixes French and English freely. Locale
selects a *listing*, not a language, so nothing can be routed by partition.

Script detection over the corpus gave the first estimate; running `py3langid` over the
text itself during `pv translate` gave the real figure. Over the 17,948 reviews long
enough to cluster:

| | Reviews | Share | Source |
|---|---|---|---|
| English | 16,491 | 91.9% | detected |
| **French** | **1,335** | **7.4%** | detected — **not** the 1,024 the accent heuristic found |
| Other Latin (es 34, pcm 12, it 3, la 3, …) | ~80 | 0.4% | detected, passed through |
| Non-Latin script (Arabic 15, Cyrillic 14, CJK 11, Devanagari 1, Hebrew 1) | **42** | **0.2%** | script, dropped |

The accent-based heuristic undercounted French by ~30%: it cannot see French written
without accents, which is common in short mobile reviews. Detecting on text rather than
on script or locale partition is what closes that gap.

This is effectively a **French/English** problem with 42 stragglers — not the
17-language problem it looked like. That makes translation the better approach
(see Step 0).

---

## Clustering strategy

This is the heart of the stage, so the reasoning is spelled out rather than asserted.

### Step 0 — Detect language, translate French to English

`pv translate`, run once between `db build` and `embed`, cached in SQLite forever.

- **Detect** with `py3langid` (pure-Python wheel, ~2 MB). Partition is useless as a
  signal, so every review is detected on its text.
- **Translate French → English** with `Helsinki-NLP/opus-mt-fr-en` (MarianMT, **301 MB**).
  A dedicated bilingual model, materially better at fr→en than any many-to-many model.
  **1,335 reviews detected as French**, then cached — subsequent runs translate only
  newly-arrived French.

  **Not "a few minutes on CPU", as first estimated.** MarianMT defaults to 4-way
  beam search, and a batch pads every sequence to its longest member, so a
  two-word review costs as much as the longest review beside it. Unsorted, this
  ran **past 65 minutes without finishing**; length-bucketing the batches brought
  it to **~20 minutes**. Batches are persisted as they complete, so an
  interrupted run keeps what it produced.
- **Drop the 42 non-Latin-script reviews** (0.2%) and report the count. A second
  310 MB `mul-en` model to rescue forty reviews is not a trade worth making; silently
  dropping them without saying so would be.
- Store `content_en` beside `content`, never overwriting the original.

**Why this beats a multilingual embedding model.** `paraphrase-multilingual-MiniLM-L12-v2`
(471 MB) was the earlier choice, made on the assumption that 11.6% of the corpus spanned
17 languages. Measured, the figure is 5.9% and nearly all French — at which point
translation wins on three counts:

1. **The dashboard becomes readable.** This is the decisive one. Synthesis is
   extractive, so a French cluster's medoid quote and LexRank sentences would render
   *in French* to an English-speaking PM — evidence they cannot read. Translating first
   means every quote on the dashboard is legible.
2. **Better embeddings on the 94% majority.** `all-MiniLM-L6-v2` is the stronger English
   model; multilingual models pay a capacity tax across 50 languages.
3. **Slightly less weight, not more** — 90 MB embed + 301 MB MT = 391 MB against 471 MB,
   and the MT model is only loaded when new French arrives.

**The honest cost, now demonstrated rather than predicted.** Hand-checking translated
reviews found MT errors landing exactly where the design warned they would:

- *"Empreinte digitale non fonctionnelle"* → *"Non-functional digital print"*
  (should be **fingerprint** — and the same term translates correctly elsewhere).
- *"Plus capable de recevoir un interac"* → *"More able to receive an interac"*.
  Colloquial Québec French elides the *ne* in *ne…plus*, so the meaning is
  **inverted**: a complaint reads as praise.

Stream membership comes from the star rating, not the text, so an inverted
translation cannot move a review between the positive and negative streams — but
it can land it in the wrong cluster. `pv painpoints --detail` tags translated
quotes `[translated]`; a dashboard must do the same and keep the French original
reachable, or "every word traces to a real review" quietly stops being true.

**A detection trap worth recording.** Short reviews defeat language ID, so
detections under 25 characters are overridden to English below a confidence
floor. Setting that floor at 0.95 was badly wrong: py3langid calls *"Très bonne
application"* (22 chars) French at 0.83, so real French was forced to English,
left untranslated, and formed its own French-titled cluster on the positive
stream. Genuine ambiguity sits below 0.45 ("Good" is Oromo at 0.06); correct
short detections sit above 0.70. The floor is **0.60**.

### Step 1 — Embed

`sentence-transformers` / **`all-MiniLM-L6-v2`** (~90 MB, 6 layers), 384-dim,
**L2-normalized** so cosine similarity is a plain dot product. Runs over `content_en`,
which is the original text for English reviews and the translation for French ones.
Native `max_seq_length` is 256; only 7 reviews of 17,948 exceed it, so no chunking.
Vectors cache to SQLite keyed by `(review_id, model)`.

### Step 2 — Collapse near-duplicates — **cut, not built**

The plan was to merge reviews at cosine ≥ 0.97 into weighted nodes, on the
grounds that "not compatible with my phone" appears verbatim four times.

Measured before building it: the negative stream holds **9 exact duplicate
texts in 13,050**, the positive stream 11 in 4,898. The most repeated string
occurs four times — nowhere near the 25-member floor a cluster needs. The pass
would have bought nothing while making `min_cluster_size` ambiguous (nodes or
reviews?) and forcing every downstream statistic to be weight-aware.

`min_cluster_size` therefore counts reviews, unambiguously. If a junk cluster of
restatements ever appears, the collapse belongs here.

### Step 3 — Build the kNN graph

Each review connects to its `k=15` nearest neighbours by cosine, edges weighted by
similarity. This graph *is* the data structure a vector database maintains.

**A deliberate simplification worth stating:** at ~13,000 vectors, exact kNN via a chunked
numpy matmul takes a couple of seconds. HNSW (`hnswlib`, what Qdrant and pgvector use
underneath) is an *approximation* that only starts paying for itself around 10⁶ vectors.
Adding it here would be cargo-culting the vector-database aesthetic while making results
approximate and the dependency list longer. Exact kNN now; the interface leaves room to
swap in ANN when the corpus justifies it.

### Step 4 — Community detection: a pluggable strategy set

Cluster quality on real review text is genuinely hard to predict from theory, so rather
than betting on one algorithm, **all candidates implement one interface and emit the
identical output format**. Switching is a flag, never a code change.

```python
class ClusterStrategy(Protocol):
    name: str
    def fit(self, vectors: np.ndarray, knn: KnnGraph, granularity: float) -> np.ndarray:
        """Return an integer label per row; -1 means noise."""
```

Everything downstream — synthesis, scoring, the `PainPoint` object, storage — consumes
only that label array. A new strategy is one file and one registry entry.

| Strategy | Character | Trade-off |
|---|---|---|
| `leiden` *(default)* | Community detection on the cosine kNN graph — the vector-database-native approach. Uses only *relative* neighbour ranks, sidestepping the distance-concentration that degrades density methods in 384 dimensions. Deterministic with a fixed seed; handles very uneven cluster sizes, which ours will be. | Needs `igraph` + `leidenalg`. No explicit noise class — handled by post-filtering (Step 5). |
| `agglomerative` | scikit-learn only, zero extra dependencies. Fully deterministic. Produces a dendrogram, so pain-point → sub-issue drill-down comes free. | Relies on absolute distances, less trustworthy than neighbour ranks at this dimensionality. |
| `hdbscan` | Built into scikit-learn 1.3+, so still no extra dependency. Explicit noise class. On L2-normalized vectors euclidean is monotonic with cosine, so it runs on the right geometry directly. | Density estimation degrades in 384 dimensions without reduction. |
| `hdbscan+umap` *(optional extra)* | The BERTopic standard; reduction to ~10 dims makes density estimation behave. | Pulls `umap-learn` → `numba` → `llvmlite`, the most install-fragile chain in this space, and is stochastic. Gated behind `pip install -e ".[umap]"` so the core install stays light and the cross-platform promise is unaffected. |

Default `leiden`; the others exist to be compared on real output. `pv cluster --compare`
runs every available strategy at the same granularity and prints cluster count, noise
share, mean cohesion, and silhouette side by side — so the choice is settled by looking
at actual RBC clusters rather than by argument.

**It was, and the result is decisive.** On the 13,030-review negative stream, target
band 40–60:

| Strategy | Knob found | Clusters | Noise | Cohesion | Silhouette |
|---|---|---|---|---|---|
| **`leiden`** | `resolution=3.519` | **47** | **0.1%** | 0.689 | 0.045 |
| `agglomerative` | `distance_threshold=0.6125` | 43 | 15.7% | 0.706 | 0.089 |
| `hdbscan` | `min_cluster_size=55` | **2** | **98.1%** | 0.827 | 0.499 |

**HDBSCAN fails completely at this dimensionality**, which is precisely the failure the
table above predicted: density estimation degrades in 384 dimensions without reduction.
It never found more than 2 clusters at any setting and discarded 98% of the stream as
noise. Its flattering cohesion (0.827) and silhouette (0.499) are artifacts of exactly
that — keep only two tiny dense blobs and any compactness metric looks excellent. This
is the case for reporting noise share beside every quality metric: on the metrics alone,
the worst strategy here looks like the best.

`agglomerative` is a genuine alternative — marginally better cohesion and silhouette —
but it discards **15.7%** of the stream against leiden's 0.1%. For a dashboard whose
job is to account for what users are saying, covering 99.9% of the feedback outweighs a
0.04 silhouette gain. Leiden stays the default, now on evidence rather than on theory.

*(All silhouette values are low in absolute terms. That is normal for high-dimensional
text embeddings, where clusters overlap heavily; the figures are useful for comparing
strategies against each other, not as an absolute quality score.)*

Dependency risk checked, not assumed: `leidenalg` and `igraph` ship **abi3** wheels
(`cp38-abi3` / `cp39-abi3`) covering Windows x64, macOS x86_64 **and** arm64, and
manylinux/musllinux. Prebuilt on all three target platforms, no compiler.

### Granularity: one knob across every strategy

Each algorithm exposes granularity through a different native parameter, which would
normally make them incomparable. Instead there is a **single `--granularity` control**,
translated per strategy:

| Strategy | Native knob | Direction |
|---|---|---|
| `leiden` | `resolution` | higher → more clusters |
| `agglomerative` | `distance_threshold` | lower → more clusters |
| `hdbscan` | `min_cluster_size` | lower → more clusters |

Granularity is expressed as a **target cluster count** (default band **40–60** on the
negative stream — roughly 275 reviews each, specific enough to act on and short enough
to read in one sitting). The runner searches the native knob until the count lands in
the band. Measured: `broad` → 18, `balanced` → 47, `fine` → 80, all inside their bands.

**The search targets the post-filter count**, so the band means what a reader assumes.
Each probe therefore applies `min_cluster_size` and `cohesion_floor` before counting.

**Plain bisection is not sufficient, and this took two attempts to get right.**

*First*, the knobs are not linear: cluster count responds roughly exponentially to
`resolution` and to `min_cluster_size`, so a linear search spends every iteration in
the top of the range. Interpolation is geometric for those two, linear only for
`distance_threshold` over its narrow band.

*Second*, the post-filter count is **not monotonic** in the knob. It rises as
communities split, then collapses back toward zero once they split so finely that every
one falls below `min_cluster_size` and is discarded. A bisection's first probe can
already sit on the descending flank, and it will then exclude the half containing the
peak before any evidence exists that it was the right half. The search therefore does a
coarse 5-point sweep first and bisects inside the bracket that sweep identifies —
preferring the interval where the band is actually crossed, and falling back to the
neighbourhood of the highest sample otherwise. The sweep's height is never used to
declare a band unreachable, because a coarse sweep can badly under-sample a sharp peak.

On the real negative stream the curve simply rises across the whole range
(1 → 9 → 27 → 83 → 225 clusters), which is exactly the case the naive "bracket the
peak" rule got wrong: it bracketed the top of the range while the band sat well below.

Two benefits beyond convenience: strategies become directly comparable because they are
held at the *same* cluster count, and a PM can say "show me fewer, broader themes"
without knowing what a resolution parameter is.

```yaml
cluster:
  algorithm: leiden
  granularity: {target_min: 40, target_max: 60}   # or: preset broad | balanced | fine
  min_cluster_size: {negative: 25, positive: 15}
  cohesion_floor: 0.35
  native_override: null       # set resolution/threshold directly, skipping the search
```

Presets `broad` (15–25), `balanced` (40–60), `fine` (80–120) map onto the same mechanism,
and `native_override` is the escape hatch for tuning a single strategy directly.

### Step 5 — Quality filtering

Leiden labels every node, so noise is removed afterwards rather than by the algorithm:

- Drop communities below `min_cluster_size` (25 negative / 15 positive — the positive
  corpus is a third the size).
- Compute **cohesion** = mean cosine of members to centroid; drop communities below
  ~0.35 as incoherent grab-bags.
- Survivors become pain points. Everything dropped lands in an `unclustered` count that
  is *reported*, so a PM can see what fraction of feedback the analysis actually covers.
  Hiding that number would be the easiest way to make this tool quietly untrustworthy.

---

## Pain point synthesis — algorithmic, no LLM

Every element traces to real user text.

1. **Centroid** — mean of member vectors, renormalized.
2. **Canonical quote** — the **medoid**, the actual review with highest cosine to the
   centroid. The single most typical statement of this pain point, in a user's own words.
3. **Title** — **c-TF-IDF**: treat each cluster as one document, score 1–3 grams against
   all other clusters, take the top distinctive phrase. This is BERTopic's labelling
   method, and it surfaces what makes *this* cluster different rather than what is merely
   frequent.

   **Two corrections that the real corpus forced, both about selection rather than
   scoring.** Every scoring variant tried (the `log(1 + A/f)` above, document-frequency
   idf, and lift) ranked the *right* phrase somewhere in each cluster's list — the
   failures were in which entry got picked.

   - **A unigram almost always out-scores the phrase containing it**, because its term
     frequency subsumes every phrase it appears in. Taking the single top term gave
     titles like "rbc", "phone" and "bank" — and "rbc" named three different clusters.
     The title is therefore drawn from the best-scoring **multi-word** n-gram, while the
     keyword list stays as scored.
   - **Titles must also be distinct from each other.** Even restricted to phrases, three
     clusters led with "new phone" and two with "credit card". Clusters now bid for
     titles strongest-claim-first, and a cluster whose phrase is taken falls through to
     its next one. Collision is judged on token overlap rather than equality, at a
     deliberately high threshold: at 0.5 any two two-word phrases sharing a word
     collided, so "compatible device" blocked "longer compatible" and pushed a genuine
     device-compatibility cluster onto the meaningless "phone just". Two similar titles
     beat one wrong one.

   Titles name specific themes well — *trusted device*, *interac transfer*, *compatible
   device*, *samsung tablet*, *graphene os*, *direct investing*, *reset password*.
   Broad clusters get correspondingly broad phrases ("rbc app", "use app"), which is an
   honest reflection of what distinguishes them.
4. **Message (the synthesized summary)** — **graph-centrality extractive summarization**
   (LexRank): split members into sentences, embed them, build a sentence-similarity
   graph, rank by PageRank eigenvector centrality, then select the top 2–3 sentences
   under **MMR** (λ≈0.7) so they are central *and* mutually non-redundant. The result is
   a short readable paragraph assembled from the most representative real sentences.

   **A cost the original plan did not budget:** the negative stream holds **32,785
   sentences**, 2.5× the review count, so a naive pass embeds more text than the corpus
   itself. LexRank runs over the **top 150 members by centroid similarity** per cluster,
   which bounds the work and improves the result — outlying members contribute little to
   a representative summary. Those sentence vectors are **transient and never written to
   `embeddings`**, which is keyed by `review_id`.
5. **Supporting quotes** — 5 reviews chosen by **MMR** against the centroid. Without MMR
   you get five near-identical sentences; with it you get the span of how the issue is
   expressed.

---

## Impact scoring

Four components, each converted to a **percentile rank** across clusters (robust to the
outliers min-max normalization would let dominate), then weighted into 0–100:

| Component | Weight | Definition |
|---|---|---|
| Recency-weighted volume | 0.40 | `Σ exp(-age_days / tau)`, **tau = 365 days**, configurable |
| Severity | 0.25 | share of 1-star members + `(3 − mean_score)`; mirrored for the positive stream |
| Momentum | 0.20 | share of the cluster inside a **365-day** window |
| Endorsement | 0.15 | `log1p(Σ thumbs_up)` |

**Recalibrated from the original 180/90, and the reason is in the data.** This corpus
is overwhelmingly historical: only 1.8% of the negative stream falls in the last 90
days and 6.2% in the last year. At `tau=180` just **3.6%** of the stream carried any
weight at all, so the ranking was decided by ~800 of 13,030 reviews while clustering
all of them. A 90-day momentum window held **231 reviews — about 5 per cluster**, which
is noise at a 0.20 weight. At 365/365 the effective mass is 8.8% and the window holds
809 reviews (~16 per cluster). Both remain configurable via `--tau-days` and
`--momentum-window`.

The momentum definition simplifies to the fraction of a cluster inside the window: the
design's "window share ÷ all-time share" differs from that only by a factor of N/W,
which is identical for every cluster in a run and therefore vanishes under percentile
ranking.

**All four component values are stored on the object, not just the total.** A PM who
asks "why is this ranked #1" gets an answer instead of a black box — and that
answerability is what decides whether the dashboard gets trusted or ignored.

Recency weighting is what makes "cluster all 15 years, rank by recency" work: a 2016
issue still forms its cluster (and its history stays available for trend lines), but
it sinks in the ranking unless it is still live.

---

## The PainPoint object

Every statistic a reader might sort by is a **flat column**, not a field nested inside
`stats`. That is the whole point: the audience re-ranks this table by whichever column
answers its question — impact, frequency, severity, criticality — so `ORDER BY` has to
reach all of them, and the terminal view and a future dashboard sort identical data.

```jsonc
{
  "pain_point_id": "pp_a3f21c",      // derived from the medoid review
  "run_id": "2026-09-23T17:50:06Z_negative",
  "polarity": "negative",
  "title": "interac transfer",
  "message": "…2-3 centrality-ranked real sentences…",
  "keywords": ["transfer", "transfers", "send", "interac", "money", "etransfer"],
  "canonical_review_id": "…",        // the medoid, a real review

  // sortable columns
  "size": 628, "pct_of_stream": 4.8,
  "mean_score": 1.64, "pct_one_star": 57.0,
  "thumbs_up_total": 2456, "cohesion": 0.65,
  "first_seen": "2013-07-21", "last_seen": "2026-09-22",
  "peak_month": "2017-03", "peak_count": 145,
  "count_90d": 12, "count_365d": 75,
  "impact": 81.9,
  "c_recency": 1.00, "c_severity": 0.36,
  "c_momentum": 0.89, "c_endorsement": 1.00,

  // raw counts; divide by the run's corpus_monthly_json for share-of-month
  "monthly_counts": {"2017-03": 145, "2024-10": 104, "…": 0},
  "representative_review_ids": ["…"],   // MMR-selected, not the most central
  "centroid": "<384 float32 BLOB>"
}
```

Members live in `pain_point_members` with a per-review similarity, so the full catalogue
is a join rather than an array inside the object.

**On cross-run stability — built differently from the design, deliberately.** The plan
called for Hungarian centroid matching against the previous run to inherit
`pain_point_id`. That is **not built**. `pain_point_id` is instead derived from the
medoid review, which keeps it stable for as long as the cluster's most typical review
does, at no cost.

The reason the full mechanism can wait is that **trend lines never depended on it.**
Because all fifteen years are clustered in one pass, each pain point's entire history
comes from its own members' dates — the series is complete on the first run. Cross-run
matching is only needed to compare *this week's clustering to last week's*, which is a
weaker and later need than the design assumed.

---

## Storage: SQLite

Clustering is the point where SQLite earned its place — embeddings as BLOBs, run
history, and per-cluster membership are all awkward in flat files.

The schema diverges from the original design in one respect, and deliberately:
`pain_points` has **real columns instead of a `stats_json` blob**, because every one of
them is something the audience may want to order the table by. A blob would make
`ORDER BY impact` possible and `ORDER BY pct_one_star` not.

```
-- data/cache.db (ATTACHed as `cache`; survives every rebuild)
translations(review_id PK, detected_lang, confidence, content_en, model, translated_at)
embeddings(review_id, model, dim, vector BLOB, PRIMARY KEY(review_id, model))

-- data/reviews.db (deleted and rebuilt on every `pv db build` / `pv run`)
reviews(review_id PK, app_id, source, lang, country, content, score,
        thumbs_up, created_at, app_version, …, content_hash)
app_metadata(fetched_at PK, app_id, score, ratings, reviews, histogram_json,
             installs, version)

runs(run_id PK, started_at, finished_at, app_id, polarity, algorithm,
     granularity, seed, params_json, stream_size, unclustered,
     corpus_monthly_json)          -- the shared denominator for every series

pain_points(run_id, pain_point_id, polarity, title, message, keywords_json,
            canonical_review_id,
            size, pct_of_stream, mean_score, pct_one_star, thumbs_up_total,
            cohesion, first_seen, last_seen, peak_month, peak_count,
            count_90d, count_365d,
            impact, c_recency, c_severity, c_momentum, c_endorsement,
            monthly_counts_json, representative_json, centroid BLOB,
            PRIMARY KEY(run_id, pain_point_id))

pain_point_members(run_id, pain_point_id, review_id, similarity)
```

`runs.corpus_monthly_json` is the piece that makes the trend data honest. Each pain
point stores raw monthly counts; dividing by the run's corpus totals for the same month
is what separates a pain point that *drove* a spike from one merely carried along by it.
Storing it costs one array per run.

**Two files, split by what they cost to recreate** (added after this stage shipped).
`reviews.db` is deleted and rebuilt from the JSONL archive on every `pv db build` /
`pv run`, and `pv cluster` replaces its stream's previous run, so the database only ever
holds the current result and never piles up stale runs. Translations and embeddings are
model output worth ~25 minutes of CPU, so they live in `cache.db`, which survives the
rebuild. `Store` ATTACHes it as schema `cache`, and SQLite resolves unqualified table
names across attached databases, so no query had to change. A database from before the
split hands its cache tables over the first time it's opened.

`Store` also applies a small **column migration** on open, because `CREATE TABLE IF NOT
EXISTS` silently keeps an older table's shape. Since `reviews.db` is now rebuilt every
run, this matters mainly for `cache.db`.

JSONL stays the raw landing zone, and nothing in the pipeline deletes it. Both
databases are derived from it, so losing either one never loses data.

---

## Files — as built

| Path | Status |
|---|---|
| `src/product_view/store.py` | **New.** SQLite schema + access, plus a small column migration so an existing database survives a schema addition. |
| `src/product_view/commands.py` | **New.** `db build`, `translate`, `embed`, `cluster`, `painpoints`. Kept out of `cli.py`, which stays parsing and the ingest stage. |
| `src/product_view/lang/detect.py` | **New.** py3langid wrapper + script detection; partition is not a language signal. |
| `src/product_view/lang/translate.py` | **New.** MarianMT fr→en, length-bucketed batches, persisted per batch. |
| `src/product_view/embed/encoder.py` | **New.** sentence-transformers wrapper, cached, chunked writes. |
| `src/product_view/cluster/graph.py` | **New.** Exact cosine kNN; vectorized undirected edge list. No dedup collapse — see Step 2. |
| `src/product_view/cluster/strategies.py` | **New.** `ClusterStrategy` protocol + registry: `leiden`, `agglomerative`, `hdbscan`. `hdbscan+umap` deferred behind the optional extra. |
| `src/product_view/cluster/granularity.py` | **New.** Sweep-then-bisect mapping target cluster count onto each strategy's native knob, plus the post-filter quality gate. |
| `src/product_view/cluster/synthesize.py` | **New.** c-TF-IDF titles + keywords, medoid, LexRank, MMR. |
| `src/product_view/cluster/scoring.py` | **New.** Impact components, percentile ranking, monthly series. |
| `src/product_view/cluster/pipeline.py` | **New** (not in the original plan). Orchestration, so `commands.py` stays thin. |
| `src/product_view/models.py` | `PainPoint` added beside `Review`; `Review` untouched. |
| `src/product_view/cli.py` | Registers the new subcommands; reconfigures stdout to UTF-8. |
| `pyproject.toml` | Dependencies + the optional `[umap]` extra. |

`ingest/play_store.py` needed **no change** — `fetch_app_metadata()` already snapshotted
the listing, and `db build` loads those snapshots from `data/meta/`.

Reused as intended: `iter_corpus()` ([archive.py](src/product_view/archive.py)) feeds the
SQLite loader and returned exactly 21,506 rows; `Review` ([models.py](src/product_view/models.py))
remained the schema contract.

**Dependencies:** `numpy`, `scipy`, `scikit-learn`, `sentence-transformers`,
`transformers`, `sentencepiece`, `py3langid`, `python-igraph`, `leidenalg`,
`platformdirs`. Optional extra `[umap]` → `umap-learn`, never required. The abi3 wheel
claim held: `igraph` and `leidenalg` installed without a compiler on Python 3.12/Windows.

**`torch` was missing from the original weight accounting** and dominates the install:
~250 MB CPU wheel on Windows and macOS, but plain `pip install` on **Linux resolves to
the ~2.5 GB CUDA build**, so the README documents the CPU index URL.

**Model downloads:** `all-MiniLM-L6-v2` ~90 MB, `opus-mt-fr-en` ~301 MB, one-off and
cached under `platformdirs.user_cache_dir()`.

## Commands

```bash
pv run                               # all of the below on a clean database, both streams

pv db build                          # JSONL -> fresh reviews.db, snapshot app metadata
pv translate                         # detect language, fr->en, cached (~20 min once)
pv embed                             # encode + cache vectors (~2-5 min CPU, once)

pv cluster --polarity negative       # leiden, balanced granularity — seconds
pv cluster --polarity positive       # "what users value"

pv cluster --algorithm agglomerative --granularity fine
pv cluster --compare                 # every strategy, same target, metrics table
pv painpoints --top 20 --detail      # inspect ranked output in the terminal
pv painpoints --sort size            # re-rank by any stored column
```

Because granularity and strategy are both flags, comparing approaches never requires
re-embedding — the expensive step runs once and is cached. Every stage is a cache-hit
no-op on re-run, so only genuinely new work is redone.

**Measured timings** (13,030-review negative stream, CPU): exact kNN 2.4s · leiden
0.5s per fit · hdbscan 13.8s · agglomerative 61s. `pv cluster` is ~2–3 min per stream (LexRank synthesis dominates; the fit itself is seconds), and a warm-cache `pv run` took 3m47s for both streams;
`--compare` runs a full search per strategy and took **~45 minutes** (agglomerative's
61s per fit dominates).

## Verification — results

Run against the real corpus. Everything below passed unless stated.

| # | Check | Result |
|---|---|---|
| 1 | `pv db build` row count | **21,506 exactly** ✅ |
| 2 | Non-Latin drops reported, not silent | **42 dropped**, reported ✅ |
| 2 | French translated, none left unmodelled | **1,335**, 0 missing ✅ |
| 3 | Vector count matches translated corpus | **17,906 = 17,906** ✅ |
| 3 | Re-running `embed` is a no-op | cache hit ✅ |
| 4 | Stream selection | negative **13,030**, positive **4,876** ✅ |
| 5 | Clusters partition the stream | 13,021 + 9 = 13,030 ✅ |
| 5 | Every member id exists in `reviews` | 0 orphans ✅ |
| 6 | Cluster count inside the target band | negative **47**, positive **51** ✅ |
| 7 | Granularity presets land in band | broad **18** · balanced **47** · fine **80** ✅ |
| 8 | Series reconcile with the corpus denominator | bucket-for-bucket ✅ |
| 8 | Clusters differ in share of the spike month | top **15.8%** vs median 0.5% ✅ |
| 9 | Every sortable column orders correctly | all 17, both directions ✅ |
| 10 | Determinism at a fixed seed | identical titles, impacts, **13,021 memberships** ✅ |

**Hand-checks, which are the checks that actually matter.**

*Read the top pain points (item 4 of the original list).* The themes the plan named as
the real test all appear as distinct clusters: **trusted device** (2FA notifications
never arriving), **interac transfer** (e-transfer send/receive failures), and
device-compatibility breakage after the October 2024 release. That last cluster's
series shows the event plainly — 228 of its 375 members land in 2024, 8% of that year's
entire negative stream. Titles, keywords, medoid quote and MMR supporting quotes cohere
within each cluster.

*Polarity split (item 5).* The positive stream produces recognizably different themes —
"works great", "easy use", "pay bills", "online banking", "best banking" — not a mirror
of the negative one.

*French translations (item 2).* Spot-checking domain vocabulary found the predicted
failure mode: "empreinte digitale" rendered once as "fingerprint" and once as "digital
print", and one *ne…plus* elision inverted a complaint into praise. See Step 0.

**Two items not closed.**

- *Cross-run `pain_point_id` inheritance (item 8).* Not built — see the PainPoint
  section. Determinism is verified instead, and trend lines never depended on it.
- *Cross-platform install (item 9).* The abi3 claim held on Windows/Python 3.12, and
  nothing in the code is platform-specific, but **a clean `pip install -e .` on a
  non-Windows machine is still unconfirmed.**

One correction to the original checklist: it asserted the corpus series would show
**1,663** reviews in 2024-10. The measured value is **1,661** — the series covers the
13,030-review stream, and 2 of the 20 dropped non-Latin negatives fall in that month.
The code was right; the assertion had not accounted for the drop.

## Deferred

Rendering and Confluence publishing stay untouched — `project.md` milestone 1
(the Confluence storage-format spike) still gates the dashboard's design, and it
is now the only thing blocking progress.

Also deferred, in rough order of when they would earn their place:

- **Cross-run pain-point matching** (Hungarian assignment on centroids). Needed only to
  compare one run's clusters against another's; within-run history already carries every
  trend line. Centroids are stored, so nothing has to be recomputed to add it.
- **Near-duplicate collapse.** Cut on measurement, not principle. If a cluster of pure
  restatements ever appears, Step 2 is where it belongs.
- **`hdbscan+umap`.** Behind the `[umap]` extra, never installed. The core three
  strategies cover the comparison.
- **Lifecycle classification and spike attribution.** Deliberately out of scope: the
  stored raw series plus the run-level corpus denominator make both reachable later
  without a schema migration.
- **A test suite.** The stage is verified by the measured checks above and by a
  synthetic end-to-end fixture, not by committed tests. Milestone 6.
