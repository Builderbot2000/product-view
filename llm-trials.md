# LLM grouping trials

Started 2026-10-08. The clustering stage (D) groups reviews by how they
*sound*, not what they are about. This document records the trials of a
local LLM as the grouping step: what was tried, what each run showed, the
design they point to, and what is still open. It is a spike: nothing here is
wired into `pv run` yet.

## Why

The current negative run (`pv painpoints --polarity negative`) shows three
faults that tuning cannot fix, because they come from the embedding itself:

- **Tone clusters.** "Way to go RBC", "Absolute waste of time", "RBC you are
  not doing the app thing well", "Largest bank in Canada and their app sucks"
  are each a pain point. `all-MiniLM-L6-v2` places sarcasm and venting
  together because they read alike.
- **One issue, several clusters.** Device compatibility ×2, the forced-update
  loop ×2, cheque deposit ×2, sign-in failure ×4–5.
- **Titles that name nothing.** The two largest clusters are titled "I even
  called customer service about this" and "App for banking is usable".

## Decisions taken

1. **The "no LLM" rule is dropped** (Project.md §0 decision 1, superseded).
   Compliance is met by running the model **locally**: no review text leaves
   the machine.
2. **Model: Qwen3.5 9B** (Alibaba, March 2026, Apache 2.0), through
   **Ollama 0.40.1** on the dev laptop (RTX 4060 Laptop, 8 GB). 6.6 GB at
   Q4_K_M. Chosen on published scores over Gemma 4 12B (Google, April 2026,
   Apache 2.0), the size-matched rival:

   | Benchmark | Qwen3.5 9B | Gemma 4 12B | Qwen3.5 4B | Gemma 4 E4B |
   |---|---|---|---|---|
   | MMLU-Pro | **82.5** | 77.2 | 79.1 | 69.4 |
   | GPQA Diamond | **81.7** | 78.8 (75.3 elsewhere) | 76.2 | 58.6 |
   | MMMLU (multilingual) | 81.2 | **83.4** | 76.1 | 76.6 |
   | TAU2 (agentic) | **79.1** | 69.0 | 79.9 | 42.2 |
   | LiveCodeBench v6 | 65.6 | **72.0** | 55.8 | 52.0 |
   | Artificial Analysis Intelligence Index | **32** | — | 27 | — |

   Mostly vendor model-card numbers (gathered on gemma4all.com), likely in
   thinking mode; we run with thinking off. Gemma 4 12B is the fallback if
   compliance rules out a Chinese-origin model.
3. **Every call:** temperature 0, seed 0, `think: false`, and a JSON schema
   in Ollama's `format` field, so the output always parses.

## Scripts

All in [spike/](spike/), run with `.venv/Scripts/python.exe -X utf8`. Output
goes to `out/llm-spike/` (gitignored, local only).

| Script | Does |
|---|---|
| [llm_extract.py](spike/llm_extract.py) | Call 1, cut only. Per review: the list of `{problem, area}` it contains, or none, with no filtering. Cached as JSONL by review id and `PROMPT_VERSION`. `--n`, `--recent` (newest N instead of a random sample weighted to Oct 2024) |
| [llm_refine.py](spike/llm_refine.py) | Call 2, rules only. One call per statement returns its `feature` and `failure`; code drops the statement if either is empty. Writes `-refined-v<RULES_VERSION>.jsonl` with `issues` (kept) and `dropped` |
| [llm_cluster.py](spike/llm_cluster.py) | Embeds the kept statements and runs the production kNN graph and Leiden code on them, with a range cap (`--reach`, `--pull`) that sends outliers to Miscellaneous. Prints groups at several resolutions |

Trials 3–8 used `llm_catalog.py`, `llm_features.py` and an agglomerative
`llm_compare.py`. All three were removed on 2026-10-09 once trials 9–11
superseded them; the trial log below is the record of what they showed.

## Trial log

Samples: **A** = 300 negative reviews, random, one third from October 2024.
**B** = the newest 200 negative reviews (2026-07-10 → 2026-09-22).

### 1. Extraction, prompt v1 (sample A)

The model listed 1.15 problems per review, all short and neutral ("cheque
deposit camera fails to capture", "verification code not received on
secondary device"). Speed: **1.2 s/review**. Grouping the phrases at cosine
distance 0.45 merged device compatibility into one group of 69 (the current
run splits it across two clusters plus two vague ones) and kept "crashes after
update", "can't sign in after update" and "update loop" apart.

**Catch:** 33 of the 44 compatibility reviews used the prompt's example
phrase word for word. The examples were banking examples.

### 2. Extraction, prompt v2: examples from another domain (sample A)

With food-delivery examples, the model writes its own wording, and
compatibility split into four groups (38, part of 29, 9, 5). **Part of v1's
clean grouping was the copied example, not understanding.** Embedding
similarity of phrases is not enough to group them. Examples in every prompt
since are from an unrelated domain.

### 3. Scan-and-mint, catalog v1 (sample A)

Oldest first, each problem goes to the model with the 10 closest issues so
far; it picks one or mints. 43 issues. **Lumped:** "Login processing
errors" took 71 reviews including Facebook redirects; an issue named "App
requires root privileges" held compatibility complaints, because names never
changed. The prompt also said "a different trigger still counts as the same
issue".

### 4. Scan-and-mint, catalog v2: stricter match, renaming (sample A)

91 issues. The large ones were coherent ("App falsely claims update required
despite being current" 22, "App crashes when depositing a cheque" 9,
fingerprint 8). Still wrong: one wrong merge sticks (login + cheque errors,
14), the update loop split in two (22 + 19), and singletons that had an
obvious home. Errors depend on review order.

### 5. Scan-and-mint plus tidy, catalog v3 (sample B)

Added a tidy pass: the model sees each issue's members together and sends out
the ones that do not belong (placed again elsewhere), then judges pairs of
similar issues for merging. 79 issues, 9% of reviews with no specific
problem. **This period's real story came out:** identity verification (too
many checks at sign-in 30, e-transfer verification 22, ID photo capture,
trusted devices). For the same 200 reviews, the current pipeline's top
groups were "Says it sends verification" (48), "General dissatisfaction"
(42), "Don't even tried Banking with them" (33).

Still wrong: only 5 merges (e-transfer split three ways, ID verification
three ways); vague buckets ("App functionality is unreliable"); a member
renamed its issue ("App falsely claims no hold time" holding "app is slow").

### 6. Extraction v3 + catalog v4 (sample B)

Three fixes: extraction drops generic bugginess ("full of glitches" is an
opinion, not a problem); names change only in the tidy pass; merging judges
more pairs. Vague buckets went away (14% of reviews now name no specific
problem), names became sensible, small issues stayed clean (GrapheneOS 5,
cheque deposit 3, driver's licence back side 4). **But two blobs formed:**
"Interac e-transfer verification and processing failures" (70, including
sign-in passcodes) and "App crashes or fails to run on specific devices"
(38). Frozen names let the first issue absorb its neighbours, and the tidy
prompt ("a name general enough to cover all of them") widened the name
instead of sending members out.

**Conclusion of trials 3–6:** a 9B model making hundreds of one-at-a-time
same-or-different calls swings between lumping and splitting.

### 7. Two tiers, minted features (sample B)

Tier 1: each problem is filed under a product feature, picked or minted.
Tier 2: one call per feature sees all its problems and groups them.
Within a feature, grouping was the best yet: identity verification 25,
two-factor loop 11, SMS on every login 9, trusted devices 5, GrapheneOS 8,
e-transfers fail to send 9. **But only 8 features were minted,** so they were
catch-alls ("security settings" held dark mode and Avion points). 82
singletons, many because the model left problems out of every group.

### 8. Two tiers, curated areas (sample B, `--by-area`)

Tier 1 is the area from extraction (the eight in `curation.yaml` plus
`other`); a leftover pass offers skipped problems to the issues just formed.
Categories are clean and match the role pages. Payments (e-transfer sending
19, e-transfer verification methods 11, cheque upload 4) and support (7, 4)
are good. **Devices is scrambled:** "App incompatibility with Android
tablets" (17) holds trusted-device and phone problems. In long numbered
lists the model attaches the wrong numbers. Sign-in is too fine ("SMS on every
login" as three issues). 63 singletons.

### 9. Leiden on the extracted statements (sample B, extraction v3)

Trials 3–8 asked the model to do the grouping. This one drops that: embed
the 241 extracted statements and run the production kNN graph and Leiden code
(`k` 10) on them. At resolution 4 there were 21 groups and every statement
fell in a group of 3+ reviews. Agglomerative on the same vectors, at similar
group counts, left most statements in groups of one or two (distance 0.35: 87
of 238 in a group of 3+). Real issues came out as their own groups:
ID/licence verification loop 16, two-step verification loop 16, trusted
device 12, e-transfer 14 and e-transfer verification 11, Android tablets 10,
GrapheneOS 8, biometric login 7. These are the identity-verification themes
the current pipeline buried under "Says it sends verification" and "General
dissatisfaction", and the tone clusters are gone because extraction removes
tone before embedding.

Still wrong:

- **Grab-bags.** The first group held balance viewing, device registration,
  pending transactions and a chip-reader fault; "customer service repeats
  itself" absorbed maintenance failures and appointment issues.
- **Mild splitting.** At resolution 8 e-transfer fell into five groups, at 4
  into two, and device compatibility into two or three. Splitting is set by
  the resolution, which is a configured knob (see Design), so it is not
  counted as a fault.

Cause of the grab-bags (traced to the source reviews): Leiden has no noise
class, so a statement that is a legitimate one-off ("card chip reader fails
to read", "appointment kept after user cancellation", "pending transactions
not displayed") attaches to whichever community it is least far from. The
embedding also groups by topic words, placing "appointment kept after user
cancellation" beside "customer service repeats itself". A few were vague
statements the extraction should have dropped ("unwilling to make the app
transfer money" from a sarcastic review).

### 10. Range cap (sample B, extraction v3)

Added to `llm_cluster.py`. A statement whose third-nearest neighbour is less
similar than `--reach` (0.4) skips clustering and goes to Miscellaneous; after
Leiden a member less similar than `--pull` (0.4) to its cluster's centre goes
there too. At resolution 4, 27 of 241 statements went to Miscellaneous: dark
mode, file size, CVV hidden, display scaling, appointments, Avion points, the
vague "setup process" statement. The first cap catches true one-offs well
(26 statements at 0.4, whereas 0.5 starts to catch tight groups such as
"no capture image button for license scan"). Raising `--pull` to 0.5 or 0.55
moved only 6–11 more statements out, so it is a weak lever. The "account
info" group stayed: its members have neighbours, only weak ones.

### 11. Cut and rules as separate calls (sample B, extraction v4 + rules v1/v2)

The v3 prompt asked for cutting, neutral wording, dropping vague statements
and area at once. Split into two calls so each has one job:

- **Call 1** (`llm_extract.py`, prompt v4) cuts only: keep each complaint
  whole, never merge unrelated ones, no filtering. 200 reviews, 1.9 s/review.
- **Call 2** (`llm_refine.py`) sees the review and one statement and returns
  `feature` and `failure`; code, not the model, drops the statement when
  either is empty. About 1.1 s/statement.

Rules v1 dropped 77 of 307 statements (48 reviews left with nothing),
including legitimate ones: "app not supported on Android tablets" (the model
did not count "not supported" as a failure), "unable to set trusted device",
"no dark mode available", and "app does not work on graphene os" (it did not
count an OS as a feature). The fault was the rubric wording. Rules v2 defines
failure to include missing, unsupported, unavailable and cannot-be-done, and
feature to include a named device or OS, with examples from a food domain:
**278 kept, 29 dropped, 22 reviews with nothing kept.** Every drop is a vague
opinion ("app has continuous problems", "customer service is poor", "app is
slow and buggy"). A few drops are generic but arguably worth keeping ("app
crashes after recent update", "app crashes frequently").

Clustering the 278 statements with the range cap at resolution 4: 21 groups,
31 in Miscellaneous. E-transfer, trusted device, Android tablets, GrapheneOS,
double authentication, ID photo loop, customer-service reach and older
devices are clean. Remaining grab-bags: a group mixing savings view with
login and direct investing; "web browser" mixed with technical-difficulties
and vision-accessibility statements; cheque deposit failures filed under
"mobile data connection fails".

### What the trials showed about the model

| Reliable | Unreliable |
|---|---|
| Rewriting one review as neutral problems | Long runs of one-at-a-time same-or-different calls |
| Picking one item from a short closed list (the area was right in every run) | Bookkeeping item numbers across a long list |
| Judging one statement against one rule (rules v2) | Keeping one level of detail across areas and runs |
| Naming a group it can see whole | Applying several priorities in one prompt (v3 let vague statements through) |

Grouping done by embedding and Leiden on the statements (trial 9) did better
than any grouping done by the model (trials 3–8), so the model's job is now
only to prepare the statements.

## Design as it stands

1. **Fetch, translate**: unchanged.
2. **Cut** (built, `llm_extract.py` prompt v4): per review, `{problem, area}`
   entries; each complaint kept whole, no filtering. Cached per review, so a
   review is cut once and the level of detail cannot drift between runs. A
   prompt change forces a full re-extract.
3. **Rules** (built, `llm_refine.py` v2): one call per statement; dropped
   when it names no feature or no failure. Cached per statement.
4. **Cluster** (built as a spike, `llm_cluster.py`): embed the kept
   statements, kNN graph, Leiden, then the range cap. Statements isolated
   from every neighbour, or far from their cluster's centre, go to
   Miscellaneous. Resolution is set by the production granularity search for
   the corpus size of the report period; it is not a fixed number. The
   period is a choice (a window, not the whole archive), and the
   resolution follows it.
5. **Counting**: a review counts once per pain point it reaches and may reach
   several, as today. Area is carried per statement, so a statement that fits
   two areas can show on two role pages.
6. **Report and publish**: unchanged downstream: counts against the usual
   rate, quotes from real reviews, role pages by area.

Per-area LLM grouping (tier 2 of the earlier design) is parked. Build it only
if trials 9–11 repeated on more samples still show too many mixed groups.

### Set by hand

- **Areas** in `curation.yaml`. They are now tier 1, not a filing aid: adding
  or splitting one changes the area filed on each statement. The area
  `keywords` are no longer needed. Roles map to areas as before.
- **Range cap**: `--reach` and `--pull`, 0.4 each so far.
- **Prompt wording.** The biggest hidden setting: "drop tone", "a problem
  names a feature", "one fix resolves the issue" set the level of detail. A
  prompt change re-extracts (cache key `PROMPT_VERSION`).
- Model, temperature, seed; star split (≤3 negative) and 20-character floor
  as before.

### Cost

Measured: cut 1.9 s/review (prompt v4); rules 1.1 s/statement, about 1.5
statements per review, so ~3.5 s/review for both calls; embedding and
clustering the statements takes seconds. A full backfill (~18k reviews) is
roughly 17 hours on the laptop GPU, once. A month (~80 negative reviews) is
about five minutes. Both calls are cached, so only new reviews cost anything.

## Open problems

**Grouping**
1. **Not scored.** Every judgement so far is a person reading groups on one
   200-review sample. Sample A (older, incident-heavy) has not been run with
   prompt v4 or rules v2.
2. **Grab-bags remain.** Statements with neighbours but generic wording (the
   "account info" group, "web browser" with technical difficulties) pass the
   range cap. Candidate fixes: a stricter feature-and-failure rule, or
   listing the feature in the embedded text.
3. **Rules v2 drops a few keepers.** "App crashes after recent update" has a
   failure but the model gave it no feature.
4. **Resolution has only been tried at 200 reviews.** The granularity search
   targets a cluster-count band, so it should carry over; untested.
5. **The area list has gaps.** Identity verification, this period's main
   theme, has no area of its own; notifications and accounts & statements
   scatter across Other, Support and Payments.
6. **The no-specific-problem flag is now the rules call's drop.** It still
   misses some complaints ("According to the update, I need a new phone or a
   new bank").
7. **Monthly runs are small.** About 80 negative reviews a month may leave
   too few statements per period for the size floor; they may need to wait
   until similar ones accumulate.

**Over time**
7. **Stable issue ids.** Renames and merges must not break trend history. The
   anchor-review matching of curated labels would be replaced, and the
   existing labels do not carry over.
8. **No measure of quality.** A hand-labelled set of ~100 reviews would score
   versions (see Grouping 1).

**Operational**
9. **Backfill takes about a day**, and the Docker image has no Ollama.
10. **Repeatability rests on the cache.** Temperature 0 is not bit-exact
    across GPUs or Ollama versions.
11. **Compliance has not approved the model.** Gemma 4 12B, the fallback, is
    untested here.
12. **The positive stream is untested.**

Next, if picked up: run cut, rules and cluster on sample A, then label ~100
reviews to score both samples, then wire the three steps into `pv run`.

## Sources (model choice)

- [Qwen (Wikipedia)](https://en.wikipedia.org/wiki/Qwen)
- [Artificial Analysis: Qwen3.5 small models](https://artificialanalysis.ai/articles/qwen3-5-small-models)
- [Gemma 4 vs Qwen 3.5 benchmark matchups](https://gemma4all.com/blog/gemma-4-vs-qwen-3-5-benchmarks)
- [BenchLM: Gemma 4 12B](https://benchlm.ai/md/models/gemma-4-12b.md)
- [Gemma 4 vs Qwen 3.5 — MindStudio](https://www.mindstudio.ai/blog/gemma-4-vs-qwen-3-5-open-weight-comparison)
