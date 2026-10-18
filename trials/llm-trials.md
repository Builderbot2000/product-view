# LLM grouping trials

Started 2026-10-08. The clustering stage (D) groups reviews by how they
*sound*, not what they are about. This document records the trials of an
LLM as the grouping step: what was tried, what each run showed, the design
they point to, and what is still open. It is a spike: nothing here is wired
into `pv run` yet.

**State on 2026-10-09.** Trials 1–11 ran on a local Qwen3.5 9B. A review of
the production report the same day ([below](#production-report-review-2026-10-09))
found its hand curation unsound, and a literature check found an established
method, LLooM, close to our design. The next design is LLooM's, run on
OpenAI's small models ([Design as it stands](#design-as-it-stands-aligned-with-lloom-not-built)).
It was built as a spike ([lloom.py](lloom/lloom.py), trials 12–13). On
2026-10-13 it first **failed the [viability test](#viability-test-criteria-set-2026-10-13-before-any-run)**
(39% precision; merges and the loop made catch-alls), then **passed its
structural gates** once merging was replaced by a breadth check, a frozen
codebook and selection, with two marginal results. The same day it replaced
embedding clustering in the pipeline as `pv issues`
([issues/](../src/product_view/issues/)), with the model as a setting.

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

Decided 2026-10-09:

4. **No app-specific curation.** Hand labels may only be categories that
   apply to any app (general sentiment, stability, sign-in, ...). The
   `issues:` labels and anchor reviews in `curation.yaml` go, and so do the
   app-specific areas (Payments, Investing, Budgeting) and keywords
   (`interac`, `nomi`, `grapheneos`). Issue names come from the data.
5. **This is a proof of concept for the method, not an operation.** Stale
   data (last fetch 2026-09-23), the missing Spanish translation and the
   lack of tests are accepted. Work goes to structural faults in the design;
   operational and validation work comes after.
6. **Align the design with the published method** (LLooM, with TopicGPT and
   BERTopic for the category list and persistence) rather than invent one.
7. **Model: OpenAI's small models through the API**, not the local model and
   not top-tier models. Planned split, as in LLooM: GPT-5.4 nano for the
   high-volume extract and score calls, GPT-5.4 mini for writing concepts.
   This supersedes 1–2 above. **Open:** sending review text to OpenAI
   conflicts with the local-only rule (1) and with report-design's
   "company-approved internal model only"; needs sign-off before a full run.
   Every step calls the model through one function, so the provider is a
   setting.
   **Reversed 2026-10-14: the local Qwen3.5 9B stays the model.** nano
   failed the gates and tuning did not help; mini only nears Qwen at about
   3.8 times nano's price ([tuning result](#result-of-the-tuning-no-variant-kept-2026-10-14)).
   The openai provider stays in the code as a setting.

## Scripts

In this folder, grouped by trial: [extract/](extract/) (trials 1–11),
[lloom/](lloom/) (trials 12–13, the viability test, cost controls and the
OpenAI checks) and [prellm/](prellm/) (the embedding-route upgrade trials).
Run from the repo root with `.venv/Scripts/python.exe -X utf8`. Output goes
to `trials/runs/` (gitignored, local only). Criteria and results are also
tabulated in [requirements.xlsx](../docs/requirements.xlsx).

| Script | Does |
|---|---|
| [llm_extract.py](extract/llm_extract.py) | Call 1, cut only. Per review: the list of `{problem, area}` it contains, or none, with no filtering. Cached as JSONL by review id and `PROMPT_VERSION`. `--n`, `--recent` (newest N instead of a random sample weighted to Oct 2024) |
| [llm_refine.py](extract/llm_refine.py) | Call 2, rules only. One call per statement returns its `feature` and `failure`; code drops the statement if either is empty. Writes `-refined-v<RULES_VERSION>.jsonl` with `issues` (kept) and `dropped` |
| [lloom.py](lloom/lloom.py) | The LLooM design end to end (trial 12): distill, cluster (UMAP + HDBSCAN, needs the `[umap]` extra), synthesize, review, score, loop. Every model call cached by request in `lloom-calls-<model>.jsonl`. `--n`, `--negative-only`, `--min-size`, `--threshold`, `--nearest`, `--loops`. Writes concepts, scores and a report to `trials/runs/lloom-<settings>/` |
| [ablate.py](lloom/ablate.py) | Cost controls: scores `sel-v1`'s round-0 candidates under one scoring variant (`--compact`, `--batch`, `--nearest`) and reports precision and recall against the gold labels |
| [relabel.py](lloom/relabel.py), [mergelabels.py](lloom/mergelabels.py) | Carry a validated run's gold labels to a re-run of the same slice (concepts matched by name and criterion), then merge in blind labels for its new concepts |
| [llm_cluster.py](extract/llm_cluster.py) | Embeds the kept statements and runs the production kNN graph and Leiden code on them, with a range cap (`--reach`, `--pull`) that sends outliers to Miscellaneous. Prints groups at several resolutions |

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

### 12. LLooM steps end to end (newest 100 reviews, all stars)

First run of the aligned design ([lloom.py](lloom/lloom.py)), still on the
local Qwen3.5 9B: quotes → bullets → UMAP + HDBSCAN → name and criterion →
tidy (merge, mark general) → score every bullet against every concept → one
loop over the leftovers. 100 reviews gave 268 complaint and 43 praise
bullets; all 311 quotes were exact. Only 2 complaints came from 4–5★
reviews.

**Speed rules out full scoring locally.** Scoring calls took 6–9 s on the
laptop GPU, which ran at 87 °C. A 200-review run made 76 concepts at
`min_cluster_size` 3, which is about 3,000 scoring calls (4–5 hours), and was
stopped. At 100 reviews and size 4 the run took about 45 minutes.

**Settings tried:**

- **Threshold has no effect.** The model answers A 528 times, B 31, C 1,672,
  D 1,587 and E 1,006, so "A or B" is in practice "A only". In 30 A matches
  read by hand, about 23 fit the criterion. In 30 C matches, 3–5 fit at
  best, so counting C as a match would add about 500 matches at around 15%
  precision. The threshold stays at 0.75.
- **Cluster size.** At 200 reviews, sizes 3 / 5 / 8 / 10 gave 76 / 32 / 22 / 16
  clusters. At 100 reviews, size 4 gave 19, near trial 9's 21.
- **Loop on or off.** With the loop, 41% of bullets match an issue concept,
  but the loop turned 199 leftovers into catch-alls: "App crashes, errors, or
  fails to function" was built from 165 bullets with 22% self-fit, and a
  general concept took 146. Without the loop, 26% match an issue concept and
  114 of 268 match nothing.

**The concepts:**

- **Real issues:** trusted device (8 reviews, clean), ID-photo capture
  (7), sign-in loops, e-transfer limits.
- **Lost:** device compatibility (older phones, tablets, foldables,
  GrapheneOS, "unavailable for this device", about 12 bullets), the
  "technical difficulties" message (about 6), connectivity
  (Wi-Fi, data, DNS), SMS as the only 2FA, and readability. All of these end
  up unmatched.

**Faults, none of them fixable by settings:**

1. **The tidy step merges too much.** "App fails on specific devices"
   (20 bullets) was merged into a crash concept, and the merged concept's
   criterion no longer matches compatibility complaints. Of 22 concepts, 14
   were merged away, including round-0 concepts merged into round-1
   catch-alls.
2. **Broad criteria.** Names written from large or mixed clusters describe
   the whole app ("fails to function"), so scoring has nothing to separate.
3. **Scoring is loose across neighbours.** 49 bullets match two or more issue
   concepts. Sign-in loops match both the crash and the login concepts.
4. **Seven of 14 concepts are general opinion** (support, regret, "worthless
   or scam"). Marking them works; together they take 85 bullets.

Self-fit (the share of a concept's own cluster that scores as a match)
exposes grab-bags directly: the merged concepts sit at 22–44%.

### 13. LLooM steps, revised prompts (same 100 reviews)

Prompt changes in [lloom.py](lloom/lloom.py), checked with `--dry` (stop
before scoring):

- **Synthesize** returns one concept per specific problem in a cluster, with
  the point numbers it covers, at the level one product team would own. Its
  examples split a mixed group and join device variants. Concepts with fewer
  than 2 points are dropped. Asking for "the most common problem" had failed:
  the model does not count, and named a device cluster after its 3
  card-reader points.
- **Review** merges only true duplicates: the same feature and the same
  failure, which it has to name. A shared symptom does not count, and a
  specific concept is never merged into a broad one.
- **A new confirm call** checks each proposed merge with one yes/no. On its
  own, Review still merged e-transfer into trusted device despite a rule
  against it. With the confirm call, all merges are rejected, real
  duplicates included. That is the chosen failure, because under-merging can
  be repaired and over-merging lost device compatibility.
- **Score** answers are defined by meaning: A same feature and failure, B a
  clear case of it, C a near miss (same symptom, other feature), D
  unrelated, E general opinion.

| | Trial 12 prompts | Revised |
|---|---|---|
| Issue coverage, no loop / loop | 26% / 41% | **47% / 60%** |
| Self-fit, round 0 | 22–44% | **67–100%** |
| Bullets on 2+ issues, no loop / loop | 26 / 49 | 72 / 112 |
| Hand audit, 30 random matches | ~23 fit | ~20 fit |
| Device compatibility | lost | **"App not supported on some devices", 16 reviews** |
| Run time | ~45 min | ~100 min (longer scoring prompt, 2 more concepts) |

Specific concepts now exist for e-transfer, card reader, Wi-Fi/data,
balance access, trusted device, ID photos and web sign-in.

**Still wrong:**

1. **Duplicates.** 2+-issue matches nearly all fall inside two families that
   are not merged: sign-in (C013–C018, top pair shares 24 bullets) and
   install/device (C016/C019, 13). Score overlap identifies them directly,
   so the next fix is to merge concepts whose matches mostly coincide,
   using the scores rather than another model call.
2. **Some criteria are too broad.** "Web browser login fails" takes app
   sign-in failures (32 matches); "App cannot be downloaded or installed"
   takes "removed the app" and "reinstall didn't help".
3. **Feeling concepts are marked as issues.** "Login process causes
   frustration or embarrassment" is an issue concept and pulls in real
   sign-in faults.
4. **The loop still makes catch-alls.** Round 1 named "App performance is
   poor and buggy" (84 matches) and "App does not function or lacks
   buttons" (53) from 143 leftovers. Without the loop, 122 of 268 bullets
   stay unmatched, mostly one-offs and vague complaints.

Precision did not improve on the hand audit (one reader, 30 matches, within
noise). The gain is in what is matched: specific concepts instead of broad
ones that anything fits.

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

## Viability test (criteria set 2026-10-13, before any run)

Can the LLooM design, at 100 reviews a slice on the local model, produce
issues a product team could trust, and keep them across months? Three
slices, run in a chain so concepts persist:

| Slice | Reviews | Role |
|---|---|---|
| **V1** | Newest 100 (2026-08-20 → 09-22), all stars | Builds the concepts. The trial 13 prompts were tuned on it, so it is in-sample and does not gate |
| **V2** | 100 random from February 2026, all stars | Held out. Scored against V1's concepts first; only leftovers loop and mint |
| **V3** | 100 random from October 2024, all stars | Held out, the 35× incident month. Scored against V1 + V2's concepts |

Method as run: trial 13 prompts, `min_size` 4, threshold 0.75, one loop,
plus the fix trial 13 named: after scoring, two issue concepts whose
matches mostly coincide (overlap ≥ 50% of the smaller) are re-named
together and re-scored. Concepts from earlier slices keep their ids;
Review may merge a new concept into an old one, never the reverse.

**Gold labels.** Every complaint point in every slice is labelled with the
concept(s) its criterion truly covers, or *general* (opinion, no feature)
or *uncovered* (specific, but no concept fits). The labels are written
**before** looking at the model's matches. The labeller is Claude (a larger
model than the one under test), not a person: a stand-in until the team
labels a set.

Each issue concept is also judged **specific** (names one feature and one
failure a team could own; "the app won't open or run at all" counts) or
**broad** ("app is buggy", "app does not function"). A broad concept's
matches count as misses in G2 and G7, since a vague point fits a vague
criterion and would otherwise score as precise.

**Pass: every gate on both V2 and V3.**

| # | Gate | Bar | Why this bar |
|---|---|---|---|
| G1 | Quotes exact | ≥ 98% | The link back to the review is the traceability promise |
| G2 | Precision: of points the model files under an issue, share the label agrees with | ≥ 75% | A reader sees at most one off-topic quote in four. Production runs about 68–73% (27–32% of units below 0.5 cosine) |
| G3 | Recall: of points the label files under an issue, share the model files under one of the same | ≥ 60% | Most of an issue's evidence reaches its page |
| G4 | Grab-bags: issue concepts with ≥ 5 matches and precision < 50% | ≤ 1 | Trial 12–13's catch-alls are the fault this design exists to fix |
| G5 | Duplicates: issue concepts that repeat another live one | ≤ 10% | One issue, one page |
| G6 | Persistence: new concepts that duplicate one carried from an earlier slice | ≤ 1 | Stable issue ids |
| G7 | Better than production on V1: share of a page's quotes that sit under a specific named issue and fit it | ≥ 15 points above production | Worth replacing what is live |

G7 is the only gate on V1, because production has no V2/V3 run to
compare. Uncovered points are reported, not gated: they measure what the
loop failed to name, which at 100 reviews includes real one-offs.

### Result: failed (2026-10-13). V3 not run

V2 failed G2 and G4 outright, and passing needed every gate on both
held-out slices, so V3 was stopped before it ran. Scripts:
[lloom.py](lloom/lloom.py) (`--month`, `--prior`, `--overlap`) and
[viability.py](lloom/viability.py) (label sheets, gate scoring, the
production baseline).

| Gate | V1 (in-sample) | V2 (held out) | Bar |
|---|---|---|---|
| G1 quotes exact | 100% | 97.8% (first reported as 100%, unchecked) | ≥ 98% |
| G2 precision | 55% blind, 63% after correction | **39%** (34 of 88) | ≥ 75% |
| G3 recall | 75–76% | not labelled | ≥ 60% |
| G4 grab-bags | **4** | **2** | ≤ 1 |
| G5 duplicates | 0 | 0 | ≤ 10% |
| G6 new duplicates of old | — | 0, but see below | ≤ 1 |
| G7 vs production | 55 vs 43 (+12) blind, 63 vs 43 (+20) after correction | — | +15 |
| Issue coverage (points matching an issue) | 42% | 35% | reported |

How the labels were made. V1's 268 points were labelled blind. 11 labels
were then corrected in the model's favour after reading its matches, where
the blind label had been stricter than the literal criterion; both figures
are shown. V2's precision comes from judging each of the 88 matches
directly, counting a match as correct wherever the criterion plausibly
covered the point. Production's 43% is from 116 quotes the live report
shows for the same reviews, with outcome and support headings left out on
both sides.

**What failed:**

1. **The overlap merge widens concepts by chaining.** In V1, eight merges
   joined sign-in, web sign-in, setup errors and trusted device into
   "Login crashes or fails" (C038): 33 matches, 11 correct. Each merge
   is reasonable on its own; together they move the name away from what
   the concept holds. Coverage fell from trial 13's 60% to 42%.
2. **Carried concepts absorb what they should not.** V2's loop minted "App
   stops working or crashes" (36 matches) and "Charts unavailable in
   direct investing". The merge folded both into the carried C038, which
   kept its id and name and took 46 of V2's 88 matches, 7 correct: charts,
   cheque deposit, payees, CRA, settings resets, all under "Login crashes
   or fails". A stable id is worse than none when its meaning drifts
   silently. G6 counts new duplicates and did not catch this.
3. **The loop still makes catch-alls** (trial 12–13 fault 4), on held-out
   data as well.
4. **Specific concepts carry over well.** Device support was 12 of 13 on
   V2, 2FA 5 of 6, e-transfer 6 of 9. Narrow criteria transfer to a new
   month; the broad ones and the merge step fail.

At 100 reviews a slice on the local 9B model, the design as built is not
viable. What fails is the merge and loop machinery around Score, not
Distill or Score: the specific concepts were precise and carried over.
Before any 1,000-review or OpenAI trial, these would need changing: no
chained merges (merge only round-0 siblings, once); a carried concept never
absorbs a new one, so a near-match becomes a new concept instead; and a
breadth check that rejects any concept whose criterion joins features with
"or". The stronger model (decision 7) may also write narrower criteria;
that is untested.

### Re-run with selection instead of merging (set 2026-10-13, before running)

The same slices, gates and labelling rules. What changes is `lloom.py
--select`, which replaces Review, the confirm call and the overlap merge
with three steps from the literature:

1. **Breadth check** (LLooM Review's "too general"): one call per new
   concept, answering specific, broad or general. Broad ones are dropped
   before scoring; general ones go to general sentiment.
2. **Frozen codebook** (BERTopic `merge_models`; deductive coding): earlier
   concepts never change. A new one joins an earlier one only when their
   definitions are close (embedding cosine ≥ 0.7) and the same/different
   call agrees. Shared points never merge anything.
3. **Selection** (GoalEx, Wang et al. 2023): an integer program chooses
   which new concepts to keep. It maximises covered points minus 1 per
   repeated match minus 2 per concept, with earlier concepts fixed in. A
   concept that mostly repeats another loses to it.

Parent links are recorded where one concept's matches contain ≥ 80% of
another's (Sanderson & Croft 1999); they are reported, never merged. The
URR area seed is not part of this run. The settings above were fixed
before any run.

The breadth prompt was then tuned on V1 (in-sample, allowed): its first
version called every concept with "or" broad, e-transfer included. After
two example changes it agreed with a hand judgment on 37 of 38 V1
concepts.

**Gates revised 2026-10-13, after V1 and before V2 was labelled.** The
focus is structural soundness; the local 9B scorer's precision is a model
limit (on V1 its matches to specific concepts were right 68% of the time,
whatever the selection did). So:

- **G2 precision: ≥ 60%** (was 75%). Production's 43% plus about the G7
  margin, so the bar stays anchored to what is live, not to the model's
  own numbers.
- **G4: ≤ 1 live issue concept judged broad** (was: precision below 50%).
  Specific concepts with low precision are scorer errors; they are
  reported, not gated.
- **G6 also requires** that no carried concept's name or criterion
  changes on a later slice.
- G1, G3, G5 and G7 are unchanged.

### Result of the re-run: structurally sound; two marginal gates (2026-10-13)

| Gate | V1 (in-sample) | V2 Feb 2026 | V3 Oct 2024 | Bar |
|---|---|---|---|---|
| G1 quotes exact | 100% | 97.8% (5 of 231) | 99.3% (2 of 281) | ≥ 98% |
| G2 precision | 63% | 69% (50 of 72) | 79% (114 of 144) | ≥ 60% |
| G3 recall | 77% | 75% | not labelled | ≥ 60% |
| G4 live issues judged broad | 1 | 1, or 2 if "User cannot locate requested items" counts | same as V2 (both carried) | ≤ 1 |
| G5 duplicate issues | 0 | 0 | 0 | ≤ 10% |
| G6 new duplicates of carried / carried changed | — | 0 / none | 0 / none | ≤ 1 / none |
| G7 vs production | 63 vs 43 (+20) | — | — | +15 |

V1 was labelled by mapping the blind V1 labels onto the new concept ids,
plus labels for the concepts new to this run. V2 was labelled in full
before its matches were read. V3's precision comes from judging each of
its 144 matches, as the failed run's V2 was; its recall was not measured.

**What held, on both held-out months:**

- **Persistence.** Every carried concept kept its id, name and criterion.
  New months were counted against them first: in V2, 29 correct matches
  landed on V1 concepts (device support 12 of 14, two-factor 5 of 6,
  e-transfer 6 of 9). In V3, the 2024 device-support wave landed on V1's
  "App not supported on some devices" (50 of 58).
- **New issues only for what is new.** V2 minted investing charts (9 of 11)
  and ID checks on every transfer (7 of 7); V3 minted the forced-update
  loop, "No updates available or false prompts" (40 of 42).
- **No catch-alls.** The breadth check rejected "App stops working or
  crashes" in V2 (the concept that broke the first run) and two more in V3.
  No duplicates on either month.

**What is marginal or wrong:**

1. **G1 on V2, 97.8%.** None of the 5 misses changes meaning: quote marks
   swapped (`"` → `'`) and `...` joining two parts of a sentence. Every
   quote keeps its review id. The first run's V2 table above claimed 100%
   here; that was not checked, and the same distill output measures 97.8%.
2. **"User cannot locate requested items"** (minted in V2, carried): a real
   findability issue (statements, documents, reservations) under a name
   that says nothing. Judged specific, G4 passes; judged broad, it fails.
3. **Scorer errors, not structure:** "Savings funds inaccessible" took
   generic "can't access my account" points (0 of 8 in V3); "Web browser
   login fails" is named for the browser but its criterion covers any
   sign-in.
4. **The selection drops some real issues.** In V3 it kept "No updates
   available or false prompts" and dropped "App fails to launch" (35) and
   "App unusable after update" (62), because the scorer matched most of
   their points to the kept one as well.

**Verdict.** The structural design works on held-out data: concepts persist
unchanged, new months mint only what is new, and catch-alls and duplicates
are kept out. What remains is model quality: scoring precision, quote
fidelity and naming. On 2026-10-13 the method replaced embedding clustering
in the pipeline (`pv issues`), with the model as a setting so that the
OpenAI models can be tried next.

## Cost controls (2026-10-13)

The whole archive (17,948 reviews) through `pv issues` on GPT-5.4 nano + mini
was estimated at about $3,500, nearly all of it scoring. Minting makes it
grow with the square of the corpus: every candidate is scored against every
point, and the candidates grow with the points. Seven controls were built
into `pv issues` and the spike; the ones that change what the model is asked
were re-validated on the local model.

| Control | What it does | Status |
|---|---|---|
| `issues.mint_sample: 3000` | Form and select new issues on a random sample of the points; score only the kept ones on the rest (TopicGPT, TnT-LLM) | **On.** Inactive at slice size, so not exercised by the gates; it rests on the V1 → V2/V3 chain above, which validated assigning new points to a codebook built elsewhere |
| `llm.batch` | Uncached requests of each step go through the OpenAI Batch API | **On for openai.** Same requests, half price. Checked live with a synthetic job (9 min) |
| `llm.prices`, `llm.budget_usd` | Spend counted from each reply's token usage; a run stops before passing the budget | On. Checked live and with a mocked API |
| `pv issues --estimate` | Calls, tokens and cost of a run, from the codebook's state and the trial rates | On |
| `issues.min_cluster_share` | HDBSCAN minimum size grows with the points clustered | Off: with `mint_sample` the pool no longer grows |
| `issues.compact_scores` | Scores as a bare list of letters instead of `{n, answer}` objects | **Failed** |
| `issues.batch: 30` | 30 points per scoring call instead of 15 | **Failed** |
| `issues.nearest: 10` | Score each point only against its 10 nearest concepts by embedding (production version fixed to compare candidates with each other, as the spike did) | **Not validated** |

**Result.** With all three scoring controls on (`lloom.py --compact --batch
30 --nearest 10`, run `cc-v1`), V1 precision fell from 63% to 35% (39 of 110
matches; six concepts new to the run were labelled blind, one judged broad)
and recall from 77% to 60%. The chain was stopped before V2 and V3. To
separate the controls, [ablate.py](lloom/ablate.py) scored the 20 round-0
candidates of `sel-v1` under each one alone, against the same gold labels
(13 labelled concepts, 268 points), with no selection afterwards:

| Scorer | Precision | Recall |
|---|---|---|
| Validated: 15 per call, `{n, answer}` | 60% (111/185) | 78% |
| Compact letters | 50% (106/210) | 75% |
| 30 per call | 52% (111/214) | 78% |
| 10 nearest | 58% (103/177) | 73% |
| All three | 48% (87/180) | 61% |

Compact letters and longer lists both add false matches: the 9B model keeps
its place in a list better when it writes each point's number. The nearest
filter cannot add a false match by itself, so its 2-point precision change
is the scorer answering differently in different company (each call's other
points change), which puts run-to-run noise at a couple of points. Its
recall loss (5 points; two-factor, sign-in loops, browser sign-in) is real:
a point's right concept is not always among its 10 nearest by embedding.
On a whole-archive codebook of hundreds of concepts, 10 nearest is a far
tighter filter than at the 20 concepts tested here, so this test is a best
case.

The cheaper scoring settings were tested on Qwen3.5 9B only; GPT-5.4 nano
may hold a longer or unnumbered list better. That is untested.

**Cost with what passed** (estimate, ±2x, reasoning tokens not counted): 12
months about $8 (was $15.50), whole archive about $80 (was $3,500). With
all controls on it would be about $0.50 and $5.

## OpenAI models, first check (2026-10-13): fails

The first run with review text sent to OpenAI, on the user's go-ahead: the
V1 points and some public reviews, about $2 in all.

**Scorer.** [ablate.py](lloom/ablate.py) `--model`: `sel-v1`'s round-0
candidates (written by the local model) scored by OpenAI models against the
same gold labels, 15 points per call:

| Scorer | Precision | Recall | Cost of 234 calls |
|---|---|---|---|
| Qwen3.5 9B, local (validated) | 60% | 78% | — |
| GPT-5.4 nano, reasoning none | 32–36% | 80–84% | $0.06 |
| nano, low | 38% | 89% | $0.13 |
| nano, medium | 44% | 87% | $0.17 |
| GPT-5.4 mini, none | 50% | 73% | $0.21 |
| mini, low | 53% | 73% | $0.44 |

The OpenAI models match too much. Most extra matches are real errors
(camera crashes in ID checks under "Login requires repeated verification
loops", sign-in failures under "App cannot be downloaded or installed",
device trust under device support); a few follow loose criteria literally
("fails suddenly", "unable to … access"). Answers vary between identical
runs (nano at none: 36%, then 32%): no temperature or seed is sent, since
these models take neither. Counting only A answers as matches does not
close the gap.

**End to end.** `pv issues` on the newest month (92 reviews, 307 complaint
points), nano for the fast tier and mini for naming, reasoning low: runs in
2.5 minutes for $0.47, three times the estimate, because reasoning tokens
were most of the output. The codebook it built fails G4 outright: "Bank
connection is difficult" (criterion: "the bank connection is difficult or
the app asks for unnecessary bank access") passed nano's breadth check,
took 104 points (two-factor, trusted devices, ID photos, missing savings),
and selection then dropped the specific issues it overlapped (trusted
device, sign-in, e-transfer). "App not compatible on devices" also joins
"does not work" to compatibility. Five issues kept, two of them broad.

Stopped there: G2 and G4 fail clearly. The local model stays the default.
A lenient scorer breaks selection, since a vague concept that matches
everything covers most points. What might change this, untested: mini (or a
larger model) for scoring and the breadth check, prompts tuned for these
models, and a coverage cap in selection.

Also fixed: the model cache ignored request options, so changing
`reasoning_effort` returned answers cached under the old setting. Options
are now part of the key (left out when empty, so existing keys still match).

### Tuning for both models (set 2026-10-14, before running)

Reading nano's false matches on V1: most follow a loose criterion literally.
"Cannot view account balance or access funds" took 37 sign-in, e-transfer
and device-trust points because its criterion ends "or finds their funds
missing/inaccessible"; "App cannot be downloaded or installed" took "cannot
access" points. Qwen anchors on the concept's name and ignores the loose
clause. Two scorer changes, each a general rule rather than a fix for these
concepts:

- **S1 anchor:** the SCORE prompt adds that the name sets the feature, and
  that words in the criterion that fit any feature ("cannot access",
  "fails") never make a point about another feature a match. The example
  stays in food delivery.
- **S2 feature first:** each answer carries a yes/no "is the point about the
  concept's feature" written before the letter; a match needs yes and A or
  B. A decomposed judgment, as in checklist evaluation.

Rules against fitting either model:

1. Tune on V1 only (`ablate.py`, 13 labelled concepts, 268 points). At most
   these two variants and their combination; no rewording after seeing
   per-concept results.
2. The same prompt for both models. A variant is kept only if it raises
   GPT precision and does not cost Qwen more than 3 points of precision or
   recall on V1 (run-to-run noise is about 2).
3. The kept variant is then run once on held-out V2 (`sel-v2`'s concepts and
   labels) for both models. Gates unchanged: precision ≥ 60%, recall ≥ 60%.
4. Then one end-to-end `pv issues` run on GPT if the scorer passes on V2,
   judged for G4 as before.
5. OpenAI spend capped at $3 for the whole round; nano first, mini only for
   the final variant.

### Result of the tuning: no variant kept (2026-10-14)

V1, reasoning low, 234 calls each:

| Scorer | Precision | Recall | Cost |
|---|---|---|---|
| nano, no change (earlier run) | 38% | 89% | $0.13 |
| nano, S1 anchor | 43% | 88% | $0.13 |
| nano, S2 feature first | 37% | 90% | $0.18 |
| nano, S1 + S2 | 40% | 87% | $0.18 |
| mini, no change (earlier run) | 53% | 73% | $0.44 |
| mini, S1 anchor | 53% | 74% | $0.49 |

Neither variant moves GPT beyond run-to-run noise, so by rule 2 neither is
kept, the held-out and end-to-end steps were not run, and the Qwen runs of
the variants were stopped unfinished (they could no longer change the
decision). Spent: $0.98.

**Where the gap is (read after the results, so a lead, not a finding).**
Most of mini's extra matches fall on two of the three overlapping sign-in
concepts, C013 "Two-factor authentication is broken or excessive" (38–41
matched, 15–18 right) and C014 "Login requires repeated verification loops"
(36–39 matched, 8 right). The labels give a sign-in point to one of them;
mini gives it to several. Leaving those two out, on the other 11 concepts:

| Scorer | Precision | Recall |
|---|---|---|
| Qwen3.5 9B | 63% (89/142) | 81% |
| mini, low | 65% (81/124) | 74% |
| mini, low, S1 | 68% (79/117) | 72% |
| nano, low, S1 | 49% (99/201) | 90% |

So mini is about Qwen's level on concepts that do not overlap, and nano is
well below it everywhere. The ablation scores every candidate with no
selection, which is where overlapping concepts cost a lenient scorer most;
in the pipeline, selection keeps one of an overlapping set. Untested next
steps, in order: mini for scoring and the breadth check end to end (about
3.8 times nano's price: $0.49 against $0.13 for these 234 calls); then, if
overlapping concepts still pass, a stricter join between candidates of the
same round.

## Port check: `pv issues` on V1 (2026-10-14): fails, and shows the pass was one draw

Before the demo run (report-design D17), `pv issues` ran on Qwen over V1's
100 reviews, complaints only, in a scratch data folder: 81 minutes in the
model, 661 calls, scoring at 10.2 s a call (not the 7.6 s assumed in the
demo estimate).

Distill matched the spike exactly: the same 268 complaint points, all 268
quotes exact. From clustering on, the result differs:

| | Spike `sel-v1` (validated) | `pv issues` |
|---|---|---|
| Live issues | 11 | 7 |
| Coverage | 44% | 42% |
| Precision (live issues, V1 labels) | 63% | **45%** (63 of 140); 59% without C011 |
| Sign-in issues kept | "Web browser login fails", two-factor | two-factor only |

The fault is one catch-all. "App displays technical difficulties or lost
connection" (criterion: "a technical difficulties message, an error message,
or a lost connection message") passed the breadth check, took 43 points of
which about 6 are that message (the rest are sign-in failures, crashes,
downloads), and selection then dropped "Login access fails" (32), "Web
login fails" (25) and "Sign in fails with repeated verification loops"
(22). G2 and G4 fail; G7 (+2 on production's 43%) fails.

**Why it differs from the spike.** Prompts are identical, requests carry the
same options (temperature 0, seed 0, no thinking). The input order is not:
the spike clusters points newest review first, the pipeline by review id.
UMAP with a fixed seed still depends on input order. Clustering the same 268
points in five random orders gave 20–24 clusters against the spike's 19,
with adjusted Rand index 0.42–0.56 against the spike's clusters. So each
validated slice (V1, V2, V3) was one draw from that spread, and this is a
different draw that fails. The gates measured one outcome per slice, not
how often the method passes.

**What this means.** Not a port bug: a structural fault the gates could not
see. The method is not stable under an arbitrary choice (input order), and
the catch-all failure seen with GPT also happens with Qwen when the clusters
fall differently. The 4-month demo run is not started. Fixes to consider
before any more runs, structural first:

1. Measure the spread: the same slice under several orders, gates reported
   as a pass rate, not one number.
2. Make the breadth check catch criteria that end in a generic clause ("an
   error message", "does not work"), or check breadth by behaviour: a
   candidate whose matches mostly lie outside its own cluster is broad.
3. Make selection robust to one lenient concept, so a catch-all cannot
   displace several specific issues it overlaps.

**Literature check (2026-10-14, LLooM read in full this time).** The table
under "Prior methods" was built from abstracts. The full LLooM paper
foresees this failure and protects against it in ways we left out:

- It states that "there is variability in the results upon re-run", that
  its defaults "have not been robustly tested", and that nothing checks the
  scores. Its technical evaluation ran **10 trials per method, each on
  shuffled documents**; we ran one per slice.
- It is **mixed-initiative**: analysts add, edit, merge and split concepts in
  a workbench. Our pipeline has no person reviewing concepts.
- It used GPT-4 to write concepts and GPT-3.5 to score; we use a 9B model
  for both.
- UMAP is our addition (from BERTopic), and BERTopic's FAQ warns that UMAP
  makes results differ between runs. Agrawal, Fu & Menzies (2018) showed the
  same "order effects" in LDA topic models (shuffling the input changes the
  topics) and asked that studies test and mitigate topic instability.

Sources: [LLooM, full text](https://arxiv.org/html/2404.12259v1);
[BERTopic FAQ (mirror)](https://huggingface.co/kisejin/TopicModelingRepo/blob/main/BERTopic/docs/faq.md);
[Agrawal et al., What is wrong with topic modeling?](https://arxiv.org/abs/1608.08176v2).

## Embedding route: upgrade trials (set 2026-10-14, before running)

An alternative to `pv issues`: the production embedding pipeline as it was
before commit 25d794f (sentences, MiniLM, kNN graph, Leiden, c-TF-IDF
titles), with each known fault fixed in code, and the model used only for
calls over the whole issue list, **at most 20 per run**. It runs in minutes
rather than hours. The code fixes are tried together as one stack against
the same baseline, with drop-one ablations to show what each contributes;
the model calls and persistence are then tried on the stack's output, and
the result is run once on held-out data.

**Data.** The demo window (report-design D17): the negative stream (★ ≤ 3,
20+ characters) over 4 months. Dev: the window ending 2026-09-22, which
holds V1. Held out: the window ending 2026-02-28, which holds V2. Segment
vectors come from the cache (`segments` in `data/cache.db`).

**Gold labels.** The V1 and V2 labels from the selection run
(`sel-v1/labels.txt`, `sel-v2/labels.txt`) give each complaint point its
issue, or G (general), U (specific, no issue) or N (not a complaint). A
sentence takes the labels of every point whose quote it overlaps; a
sentence that overlaps no point is X (not a complaint point). Each cluster
is credited with the issue most of its labelled sentences carry, which is
the best name it could have; naming is tested on its own (L1).

**Measures** (V1 sentences only; each run in 5 shuffled input orders,
reported as median and range):

| Measure | Definition |
|---|---|
| P, precision | Of labelled sentences in issue clusters (not the general bucket or Miscellaneous), the share whose labels include the cluster's issue. G and X count as misses |
| R, recall | Of points with an issue label, the share with a sentence in a cluster credited with that issue. Points in 4–5★ reviews count as missed |
| Tone | Clusters with ≥ 3 labelled sentences, most of them G or X |
| Grab-bags | Clusters with ≥ 5 labelled sentences and P below 50% |
| Split | Issues credited to two or more clusters |
| Stability | Adjusted Rand index between the 5 orders' clusterings of the whole window |

Clusters whose labelled sentences are mostly U may be real issues the
labels lack. They are listed and judged by hand, not scored.

**Baseline (B0).** The old code (`cluster/`, `embed/segment.py`) restored
in a spike, with the settings scaled to a window of about a thousand
sentences: Leiden on a kNN graph (k 10), a target of 20–30 clusters,
minimum size 5, cohesion floor 0.35, the general bucket (`vague.py`) on.
The 2026-10-08 production run was the same code at corpus scale (G7: 43%).

**The fixes**, in three groups. **S** (the code stack): U1–U4 and U6 all on
at once, plus five drop-one runs (S without each fix), all on the dev
window. **P**: U5 on the stack's clustering. **M**: L1 and L2 on the stack's
clusters.

| # | Fix | Main measure |
|---|---|---|
| U1 | Specificity score (word rarity, or Speciteller-style features): low scorers go to the general bucket before clustering | Tone, P |
| U2 | Range cap (reach before clustering, pull after) and holding back clusters below the cohesion floor; quotes ranked by closeness to the centre instead of thumbs-up | P, grab-bags; precision of the top 5 quotes |
| U3 | Duplicate clusters joined when their centres are close; parent links reported, never chained | Split, without P falling |
| U4 | Sentiment per sentence over all stars, instead of the star stream | R, without P falling |
| U5 | Persistence: issues frozen and matched by centre from month to month, Feb → Sep 2026; only unmatched clusters become new issues | V1 points of issues carried from V2 that land on the issue id born in Feb; no carried issue drifts |
| U6 | Consensus clustering: co-association over many orders, then one clustering | Stability, without P or R falling |
| L1 | Model names clusters in batches (≤ 12 calls) | Names judged to fit, against c-TF-IDF titles |
| L2 | One call reviews the full issue list (duplicates, too broad); one call files issues into areas | Agreement of its flags with the measured duplicates and grab-bags; areas judged correct |

**Rules, against fitting:**

1. Tune on V1 only, at most 3 variants of the stack, every variant
   reported.
2. The stack is kept if it beats B0 by more than B0's spread across orders
   on P or tone, without R falling more than 3 points (medians). A fix
   stays in the stack only if dropping it worsens its main measure by more
   than that spread, or costs P or R more than 3 points; otherwise it is
   removed as dead weight. U5, L1 and L2 are judged on their own main
   measures.
3. The final stack, with whatever of U5, L1 and L2 passed, is run once on
   the held-out window (V2).
   Pass: P ≥ 60% and R ≥ 60% (the `pv issues` bars), at most one tone
   cluster and one grab-bag, stability reported.
4. A trial stops once its main measure clearly fails.
5. Hand judgments (U clusters, L1 names, L2 areas) are made by Claude, a
   larger model than the one under test, as in the viability test.

### Result: the stack fails (2026-10-14). P and M not run

Scripts in [trials/prellm/](prellm/) (`harness.py`, `stack.py`,
`run_s.py`); write-up in `trials/runs/prellm/result-S.md`. Dev window:
765 sentences from 294 reviews; 259 of V1's 268 points mapped exactly, 2
fall in 4★ reviews, 7 are 2-word quotes the sentence splitter drops.

| Run | P | R | Tone | Grab-bags | Split | Stability (ARI) |
|---|---|---|---|---|---|---|
| B0 | 31% (30–32) | 68% (66–71) | 8 | 15 | 5 | 0.84 |
| Stack, all five | 42% | 59% | 5 | 6 | 5 | 0.94 |
| **Final: U2 + U4 + U6** | **41% (39–41)** | **59% (57–60)** | **4** | 6 | 5 | 0.93 |

Medians over 5 orders, ranges in brackets. Drop-one verdicts: U2 (range
cap) stays, 7 points of P; quotes by closeness beat thumbs-up in every run,
by 3–10 points. U4 (sentiment per sentence) stays on P (+4) but adds no
recall, its main measure: neutral facts ("double authentication
mandatory") are filtered out. U6 (consensus) stays on stability (0.86 →
0.94). U1 (word rarity) is dropped: noisy, and tone was better without it.
U3 (joining duplicates) is dropped: it made about one join per run and
split did not move. Two of the three variants were used; the first broke
because the range cap thinned the graph and the old resolution search then
picked a setting that left most sentences in fragments.

The stack beats B0 on P and tone, but loses 9 points of recall (rule 2
allows 3), and P is 20 points below the 60% bar. Counting only sentences
that are complaint points (X and N left out, closer to how `pv issues`
precision was counted), P is 40% for B0 and 46% for the final stack. That
is the port check's 45% for `pv issues`, at seconds instead of 81 minutes,
but nowhere near the spike's 63% or the bar. Persistence (U5) and the model
calls (L1, L2) cannot close that gap: neither changes which sentences sit
in which cluster. So both were stopped (rule 4).

**Why it fails.** A sentence of a raw review carries its topic words but
not its problem, so the embedding still groups by topic: six of the final
20 clusters are mostly general opinion ("RBC seems to be incompetent in
every way"), and a "money" cluster mixes e-transfers, deposits and fees.
This is the job distill did in trials 9–11 and `pv issues`, and no fix in
code replaced it.

Caveats: about 5 labelled sentences per cluster, so tone and grab-bag flags
can turn on one sentence; one issue point is about 1 point of recall; all
in-sample on V1.

## Embedding route, round 2: steer the embedding (set 2026-10-14, before running)

Round 1 failed because a raw sentence's embedding carries its topic and tone,
not its problem. Distill fixed that with a model call per review, which this
route rules out (minutes, not hours; the model only in calls over the whole
cluster list). The literature has an established way to steer an embedding
toward one facet of the text without generating anything: **instruction-tuned
embedders** (INSTRUCTOR, Su et al. 2023; used by ClusterLLM, Zhang et al.
2023, to set a clustering's "perspective"). A comparison of LLM uses in
clustering (Viswanathan et al. 2023) found that improving each document's
representation helped on every metric, while LLM post-correction of clusters
helped little. So the representation is the main fix here, and the model's
cluster-level calls come second.

**Fixes**, as one bundle on top of the round-1 final stack (U2 + U4 + U6), with
drop-one runs:

| # | Fix | Main measure |
|---|---|---|
| W1 | Units embedded by **Qwen3-Embedding-0.6B** with a task instruction ("the app feature and the problem with it"), replacing MiniLM for clustering, the range cap and quote ranking. The vague set-aside keeps MiniLM (its anchors are MiniLM vectors). The range cap's reach and pull are re-set from the new space's similarity distribution, label-free, at the percentiles MiniLM's 0.40 and 0.50 sat at | P, tone |
| W2 | **Cluster review by the model**: one call per issue cluster (≤ 20 a run), showing its 12 members closest to the centre: specific problem, or general opinion. General clusters go to the general bucket | Tone, P |

**Gates** unchanged from round 1: on the held-out window (V2), medians over 5
input orders, P ≥ 60%, R ≥ 60%, at most one tone cluster and one grab-bag;
stability reported. Following T07, also reported as a pass rate: the number of
the 5 orders that meet all four bars (pass needs at least 4).

**Rules**, as round 1: tune on V1 only, at most 3 variants of the bundle,
every variant reported; a fix stays only if dropping it worsens its main
measure beyond B0's order spread, or costs P or R more than 3 points; the final
bundle runs once on V2; stop once the main measure clearly fails. Each trial
is kept under 45 minutes.

### Result: no variant passes on V1 (2026-10-14)

Script [round2.py](prellm/round2.py); results in `trials/runs/prellm/R2/`. V1,
medians over 5 orders, with the number of orders meeting all four bars:

| Variant | P | R | Tone | Grab-bags | ARI | Pass | Minutes |
|---|---|---|---|---|---|---|---|
| Round 1 final (U2 + U4 + U6) | 41% | 59% | 4 | 6 | 0.93 | 0/5 | <1 |
| v1: W1 + W2 two-way | 48% (46–51) | 52% (49–53) | 2 | 5 | 0.89 | 0/5 | 9 (7 embedding, once) |
| v2: W2 breadth (specific / broad / general) + W3 segments, not re-joined units | **67% (62–67)** | 42% | **0** | **1** | 0.94 | 0/5 | 2 |
| v3: v2 + 35–50 clusters before review + W4 outliers back at the pull bar | 49% (47–51) | 53% (51–56) | 1 | 5 | 0.80 | 0/5 | 3 |

What each step showed:

- **W1 works on what it is for.** With the instructed embedder, the specific
  clusters are clean (e-transfer 71%, two-factor 83%, sign-in 71%; round 1:
  57%, 40–100%, 53%). Tone and opinion still cluster, but as their own
  clusters ("avoid it", "doesn't work, reinstalled", "updates made it worse",
  "technical difficulties") instead of inside issue ones.
- **W2 needs the breadth definition.** Two-way (specific / general) let
  "doesn't work" and "confusing UI" clusters pass as specific; the validated
  breadth definition (broad = names no single feature) removes them, and
  every cluster it removed was below 30% precision. That gives v2's
  precision and tone.
- **Recall is the gap.** In v2, before the review, R is 55%: 10 issue points
  have no unit (the sentiment filter or the 3-word floor drops them), 16 sit
  only in Miscellaneous, and the rest sit in clusters credited with another
  issue: at 20–30 clusters before a review that removes about half, trusted
  device shares a cluster with ID verification and never gets credit.
- **v3's finer band fixed that** (trusted device became its own cluster, 6 of
  6), **but W4 broke precision:** about 90 Miscellaneous units came back, most
  of them from the clusters the review had just removed as broad, and formed
  new G-majority grab-bags. A unit closest to a rejected cluster should stay
  out.
- W2 made 20 calls a run in v1–v2 and 34–36 in v3 (one per cluster, about 1 s
  each), over the 20 set: a deviation, recorded here.

Three variants used, so round 2 stops (rule 1). Its findings set round 3.

## Embedding route, round 3 (set 2026-10-14, before running)

The bundle is v2 plus the two parts of v3 that the result supports, with W4
corrected:

- **Band 35–50** clusters before the review (it removes about half).
- **W4, corrected:** a Miscellaneous unit joins an issue cluster only when the
  closest centre of *all* reviewed clusters (kept, broad and general) is that
  issue cluster's, and its similarity reaches the pull bar. Units closest to a
  removed cluster stay out (BERTopic `reduce_outliers` over the full topic
  set, the removed topics acting as outlier topics).

Drop-one runs for W1–W4, the band, U2, U4 and U6, with the same keep rule.
W2 is allowed one call per cluster (up to 50 a run). Gates, held-out rule and
pass rate as round 2. At most 3 variants.

### Result: closest yet, still no pass (2026-10-14)

V1, medians over 5 orders:

| Variant | P | R | Tone | Grab-bags | ARI | Pass |
|---|---|---|---|---|---|---|
| v1: W1 + W2 breadth + W3 + W4 corrected + band 35–50, on U2 + U4 + U6 | 63% | 50% | 0 | 3 | 0.80 | 0/5 |
| **v2: v1 less the dead weight (below)** | **61% (59–65)** | **59% (56–60)** | **0** | 2 | 0.71 | 0/5 |
| v3: v2 with band 45–60 | 63% | 54% | 0 | 2 | 0.82 | 0/5 |

Drop-one on v1 (P / R): without W1 61 / 41 (stays); W2 40 / 64, tone 4,
grab-bags 10 (stays); band 67 / 42 (stays); U6 65 / 50.5, ARI 0.80 → 0.66
(stays). Dead weight: W3 (re-joined units beat segments, 71 / 49.5), W4 (moves
4–7 units), U2 (no gain in P or grab-bags; U6 holds stability) and **U4**
(the sentence-sentiment filter: 67 / 52 without it; the review now does its
job, and it dropped neutral-sounding complaints). The first drop-one batch
reused one window's band and U2/U6 settings for every run (a cache bug); band,
U2 and U6 were re-run after the fix.

v3's search reached 42–45 clusters, and the review then removed about 29, so
recall fell. The review judges a cluster whole: a verdict right for most
members is wrong for some. In v2, 12 issue points sit in clusters judged
general (long units mixing opinion with a complaint: "RBC you are bad people,
you no longer support … Android tablets"), and kept clusters still hold
opinion units.

Content check of v2 (members read across each cluster, not only the labelled
ones): 10 of 14 clusters are one specific problem (sign-in, e-transfer,
repeated two-factor, device support, trusted device, verification on
e-transfers, transactions not shown, too many security checks, cheque
deposit, crash on open). The two grab-bags are ID checks by driver's licence
(coherent; the labels split it over photo capture, trusted device and
sign-in) and the "technical difficulties" message (coherent; labelled general
or uncovered). Two weak ones pass the review: "please try again later / has not
worked for months" and "cannot turn features off / privacy".

## Embedding route, round 4: unit-level verdicts (set 2026-10-14, before running)

The base is round 3 v2. One fix:

- **W5, verdicts per unit.** As TnT-LLM (Wan et al. 2024) does, the model's
  labels train a lightweight classifier on the embeddings, which then labels
  every item. Here the labels are free: each unit takes its cluster's review
  verdict (specific, broad or general). A logistic regression on the W1
  vectors, cross-fitted (5 folds, so no unit is judged by a model trained on
  its own label), gives each unit a verdict. A unit in a kept cluster whose
  verdict is general goes to the general bucket, broad to Miscellaneous. A unit
  outside the issue clusters (Miscellaneous, or a removed cluster) whose
  verdict is specific joins the nearest kept cluster when it reaches the pull
  bar. The vague set-aside is untouched. No extra model calls.

Gates, rules, held-out run and pass rate as rounds 2–3; drop-one is W5 on and
off (off is round 3 v2). At most 3 variants.

### Result: passes on V1, fails on held-out V2 (2026-10-14)

| Variant | Slice | P | R | Tone | Grab-bags | ARI | Pass |
|---|---|---|---|---|---|---|---|
| v1: round 3 v2 + W5 | V1 | 65% (58–68) | 62% (59–63) | 0 | 2 (1–3) | 0.65 | 0/5 |
| v2: + W6 second look | V1 | 71% | 49.5% | 0 | 1 | 0.70 | 0/5 |
| **v3: W6 with the review pitched at what one team owns** | V1 | **66% (59–69)** | **63% (59–65)** | 0 | **1** (1–4) | 0.75 | **3/5** |
| v3, drop W5 | V1 | 61% | 61% | 2 | 2 | 0.77 | 0/5 |
| v3, drop W6 | V1 | 56% | 67% | 0 | 4 | 0.78 | 0/5 |
| **v3, held out** | **V2** | **56% (41–59)** | **61.5% (45–63)** | 1 | **3 (1–5)** | **0.56** | **0/5** |

W6 at first removed real issues: read across the whole cluster, e-transfer
shows several failures of one action (crash, fee, limit, double send), and
the concept-level wording "one feature and one kind of failure" called that
broad. v3 pitches the review at the level the synthesize prompt uses ("what
one product team would own"; the details may differ). W5 and W6 both stay.

Content check, V1 v3 order 0: 14 of 15 clusters are one ownable problem
(sign-in, e-transfer, two-factor, ID checks by licence, device support, card
tap to send e-transfers, trusted device, verification on e-transfers, too
many security checks, GrapheneOS, cheque deposit, transactions not shown,
dark mode, credit-card balance delay); one is mixed ("settings I had to turn
off"). The broad clusters are gone.

**V2 fails.** Two causes, read from the clusters with their labels:

1. **The labels miss sentences the distiller never extracted.** V2 has 44 X
   sentences of 174 labelled (V1: 19 of 184), and P counts every X as a miss.
   The V2 grab-bags are coherent: "app not compatible / phone too old" and "no
   tablet support" score 33–38% because half their labelled sentences are X
   ("not available on my tablet so I change bank", "Add my name to the no
   tablet version available"); "can't sign in" is split by the labels between
   web sign-in and two-factor. With X sentences left out (a diagnostic, not the
   gate), P is 54–69% and grab-bags 0–1.
2. **The method is unstable on new data (a real fault).** Even with X left
   out, only orders 1–3 would pass. Orders 0 and 4 lose a third of recall (45%
   and 48%); in order 0 the e-transfer cluster is gone. ARI 0.56 (V1: 0.75).

Round 4 stops here: V2 has been seen, so it can no longer serve as held-out
data for this route. Open: whether the precision rule should count X
sentences (a gate revision, the team's call), and a fresh held-out slice
(V3, October 2024, has no recall labels) labelled blind before any further
run.

**Decided 2026-10-14 (Kevin):** label every sentence blind. The next held-out
slice is V3 (the 100 October 2024 reviews of `sel-v3`). Before any run touches
its window, each unit of those reviews (the units the method clusters: the
1–3★ stream, segments re-joined at 0.45) is labelled from the review text
alone against the concept list (`sel-v3/concepts.json`, live issues), or G /
U / N. There are no X units: every sentence has a label. P is unchanged in
form. R is counted over units with an issue label instead of points.

Done the same day, before any run on the V3 window ([v3_gold.py](prellm/v3_gold.py);
`trials/runs/prellm/v3/labels.txt`, sha256 `32c4b28400e5fb85…`): 215 units
from 91 reviews (9 are 4–5★). App not supported on the device 66, update
prompt with no update to install 48, sign-in 6, general 63, not a complaint
30, other specific 5. October 2024 is the incident month, so V3 is mostly two
intertwined issues, a hard test of keeping them apart.

## Embedding route, round 5: stability (set 2026-10-14, before running)

Diagnosis on V2 (now spent, so usable for development): the instability
starts in the clustering, not in the model calls. In order 0 the e-transfer
and sign-in clusters never form; in orders 2 and 4 they do, from the same
data. Each order's consensus averages only 20 clustering runs. And the review
called "technical difficulties" specific in every order: the validated
breadth definition's example "app shows errors and crashes, with no screen or
action named → broad" was left out of the cluster prompt.

- **S1:** consensus over 100 clustering runs instead of 20 (the co-association
  matrix converges as runs grow; Monti et al. 2003).
- **S2:** the review prompt gets back the validated example: an error message
  with no screen or action named is broad.

Development data: V1 and V2, both to be passed. Held out: V3, once, against
its blind labels. Gates and pass rate as before (≥ 4 of 5 orders). At most 3
variants; drop-one for S1 and S2.

### Result on the development slices (2026-10-14)

| Variant | Slice | P | R | Tone | Grab-bags | ARI | Pass |
|---|---|---|---|---|---|---|---|
| Round 4 v3 | V1 | 66% (59–69) | 63% (59–65) | 0 | 1 (1–4) | 0.75 | 3/5 |
| Round 4 v3 | V2 | 56% (41–59) | 61.5% (45–63) | 1 | 3 (1–5) | 0.56 | 0/5 |
| v1: S1 + S2 | V1 | 67% (64–69) | 59% (58–61) | 0 | 1 (1–1) | **0.87** | 1/5 |
| v1 | V2 | 51% (51–53) | 61.5% (55–62) | 1 | 3 (3–3) | **0.78** | 0/5 |
| **v2: + W5 rescue against each cluster's own spread** | V1 | **68% (65–71)** | 59% (58–61) | 0 | 1 (1–1) | 0.87 | 1/5 |
| v2 | V2 | 52% (52–54) | 61.5% (55–62) | 1 | 3 (3–3) | 0.78 | 0/5 |
| v3: + S3 contextual unit embeddings | V1 | 45% | 25% | 0 | 3 | 0.72 | 0/5 (V2 not run) |

- **S1 fixed the instability.** Order-to-order ranges shrank from 18 points of
  P and recall to 2–7; on V2 no order loses e-transfer or sign-in any more, and
  the same clusters come out every time.
- On V2 the three grab-bags are the same in every order, and all three are
  coherent: sign-in (split by the labels between web sign-in and two-factor),
  phone compatibility and tablet support (half their labelled sentences X).
  With X left out (diagnostic only): P 63–65%, grab-bags 0–1, tone 0 in every
  order; recall 55–62%.
- **Recall now binds.** W5's rescue was blocked by the old pull bar (units
  judged specific sat 0.73–0.78 from a kept centre against a 0.79 bar). v2
  measures each unit against the cluster's own 10th-percentile member
  (HDBSCAN `approximate_predict`, BERTopic topic distributions): +1–2 P, no
  recall. The V1 misses left are context-labelled sentences ("always shows an
  error" is a trusted-device point only because of the sentence before it),
  issues too small to form a cluster in the window (savings, ATM, Wi-Fi: 12
  points), and long units that mix opinion with a complaint.
- **S3 failed clearly.** Embedding each unit with its neighbours made units of
  one review stick together; 54% went to Miscellaneous. Stopped before V2.

v2 is the round's bundle, run once on V3 below.

### Result on held-out V3: P and R pass, grab-bags fail (2026-10-14)

| Gate | V3, median (range over 5 orders) | Bar |
|---|---|---|
| P | **70% (69–71)** | ≥ 60% |
| R | **67% (65–68)** | ≥ 60% |
| Tone clusters | **0 (0–0)** | ≤ 1 |
| Grab-bags | 2 (1–3) | ≤ 1 |
| ARI | 0.87 | reported |
| Orders meeting all four | **2/5** | ≥ 4/5: **fail** |

The window is the incident month: 4,362 units from 1,849 reviews, about 6
times V1. Embedding took 36 minutes on CPU (once; cached) and each order
4.5–5 minutes, against the ~12 estimated from V1's size. On a window this size
the run is over the 45-minute trial budget; embedding on the GPU would remove
most of it.

Content check (members read across each cluster, unlabelled ones included):
the large clusters are clean: "no longer compatible with my device" (283
units, 92%), "asks me to update but there is no update" (181, 100%), plus
device-model, tablet and Android-version splits of the compatibility issue.
The grab-bags:

- **"Can't log in"** (flagged in all 5 orders): every member is a sign-in
  failure, but the V3 labels file sign-in failures by cause (in a review about
  the update prompt, "I can't log in" is the update issue). The cluster groups
  by symptom; one sentence does not say the cause.
- **"Can't open the app / can't get into my account"** (2–3 orders): the same
  symptom with causes spread over the update loop, incompatibility and
  sign-in; closer to genuinely broad.

So the method fails the pass rule on its own merits, with one nameable
limitation left: a sentence carries a symptom, and in an incident month one
symptom has several causes. P and R pass in every order on a complete, blind
key, and the result is stable. V3 is now spent as held-out data.

Caveats on the whole of rounds 2–5: the variants and thresholds were chosen
by reading V1 (and in round 5, V2) gold results, so those slices are
optimistic (round 4: P 66% on V1, 56% on V2); the cluster-review prompts name
banks ("worst bank", "switching banks") and S2's example phrases ("technical
difficulties", "something went wrong") were taken from this app's reviews; the
V3 labels were written by the same agent that built the method. A key written
by a team member would be the independent check.

## Embedding route, round 6: symptom and cause (set 2026-10-14, before running)

Kevin chose option 2 of the handoff (docs/handoff-2026-10-14.md). Diagnosis on V3
(now development data): in the "can't log in" grab-bag, the sentences the key
files under another cause share a review with a sentence in that cause's
cluster ("I can't log in" beside "it keeps saying to update when there is no
update"); the sentences with no such neighbour are sign-in failures. In order 0,
moving the co-occurring ones takes the cluster from 33% to 80%.

Established method: implicit-aspect identification by co-occurrence association
rules (Hai, Chang & Kim 2011; the "context-sensitive" variant picks the related
explicit aspect from the same review). A unit that only gives a symptom takes
its aspect from the cause it co-occurs with. Adapted here from words to clusters:

- **C (cause attribution):** over the window's reviews, a rule S → C between two
  kept issue clusters holds when at least 3 reviews contain both, conf(S → C) =
  n(S, C) / n(S) ≥ 0.15 and lift ≥ 2. A unit of S whose own review has a unit in
  C moves to C (the highest-confidence rule when several hold). S stays as an
  issue with the rest of its units; the report shows S → C as a parent link.
  Which side is the symptom:
  - **Ca (code only):** S is the side with the lower conf in the reverse direction
    (conf(S → C) > conf(C → S)), and at least 25% of S's reviews contain another
    kept cluster.
  - **Cb (model check):** one call per candidate pair, on 6 reviews containing
    both: is one a consequence of the other, or are they independent?
- **N (neutral wording):** the review prompts lose "worst bank" and "switching
  banks", S2's example phrases are replaced by wording not taken from this app,
  and the old set-aside's word list loses "rbc", "royal", "canada", "canadian".
- **GPU embedding:** Ollama `qwen3-embedding:0.6b` for texts not already cached.
  Checked against the CPU vectors on 200 V1 units: same-text cosine 0.9997
  (min 0.997), top-10 neighbour overlap 96%.

Screening (diagnostic): C applied to the saved round 5 labels on V1, V2, V3.
Variants (full runs on V1, V2): v1 = round 5 v2 + N + Ca; v2 = + N + Cb; drop-one N.
Development criteria: on V3, grab-bags ≤ 1 with P and R ≥ 60% in ≥ 4 of 5
orders; on V1 and V2, median P and R no more than 3 points below round 5 v2,
grab-bags and tone no higher.

Held out: **V4**, 100 reviews drawn (seed 0) from September–October 2025, window
July–October 2025: the newest window overlapping no earlier slice's (October
alone has 61 reviews, so the draw takes the window's last two months, as V1
spans two). 229 units of 86 reviews labelled blind before any run, every unit
(`trials/runs/prellm/v4/labels.txt`, sha256 `b9122b3dbff480c8…`, labeller
Claude, by cause as V3). The bundle runs once; pass bar as before (all four
gates, ≥ 4 of 5 orders).

### Result: passes on development, fails on held-out V4 (2026-10-14)

Changes made on development data after the criteria were set (all method
settings, no gate or rule changed):

- C's candidate test: lift ≥ 2 never fired on V3's sign-in cluster. In an
  incident month each cause is common and split over several clusters (the
  update loop sat in three), so lift stays at 1.7–1.9 on real links. Replaced by
  a one-sided Fisher exact test, p ≤ 0.05 (significant association rules, Webb
  2007), and conf ≥ 0.10.
- N's first wording dropped "technical issues" from the error-message example;
  on V2 a "technical issues / glitches" cluster was then kept (P 48.5%, grab-bags
  4: fails the development criteria). Reworded as the generic category
  ("a generic error, glitch or outage message (technical issues, an error
  occurred, try again later)"). Variant r6v2 is r6v1 with that wording.
- Screen on saved round 5 labels: Cb (model check per pair) gave no gain on V3
  (2/5), so it got no full run.

| Run | Slice | P | R | Tone | Grab-bags | ARI | Pass |
|---|---|---|---|---|---|---|---|
| Round 5 v2 | V1 | 68% | 59% | 0 | 1 | 0.87 | 1/5 |
| **r6v2** | V1 | 69% (67–70) | 62% (60–64) | 0 | 1 (1–2) | 0.88 | 3/5 |
| r6v2 − N | V1 | 67% | 58% | 0 | 1 | 0.87 | 1/5 |
| Round 5 v2 | V2 | 52% | 61.5% | 1 | 3 | 0.78 | 0/5 |
| **r6v2** | V2 | 52% (46–53) | 61.5% (46–65) | 1 (1–3) | 3 (2–4) | 0.65 | 0/5 |
| Round 5 v2 | V3 | 70% | 67% | 0 | 2 | 0.87 | 2/5 |
| **r6v2** | V3 | 72% (71–76) | 70% (61–78) | 0 | 1 (0–1) | 0.87 | **5/5** |
| **r6v2, held out** | **V4** | **53% (50–57)** | **54% (49–61)** | 0 (0–1) | 3 (2–5) | 0.81 | **0/5: fail** |

Development criteria met (V3 ≥ 4/5; V1 and V2 no worse), with V2 less stable
than before (ARI 0.65 against 0.78). V4: 841 units, embedded on the GPU in
100 s, 6 minutes for 5 orders.

Content check, V3: the sign-in cluster loses its update-loop and device
sentences to their causes ("It wont let me log in" beside "still says I need to
update") and keeps the sign-in failures; the remaining grab-bag is a coherent
"forced update" cluster the key partly files under device support. V1's cost:
"cannot complete verification when I e-transfer" moved from verification to
e-transfer; C moves a sentence that names its own cause too.

Content check, V4 (a calm window with many small issues; C made 2–4 rules and
moved 12–23 units, so it is not the fault):

- Real grab-bags: balance display + cheque hold + exchange-rate converter;
  adding recipients + "Android 16" + unsubscribing; assorted credit-card
  complaints. The band (35–50 clusters before the review) forces small issues
  together in a window this size.
- Fragmentation: verification and trusted devices split over four clusters;
  device support over four.
- Recall binds: missed issue sentences went to the general bucket (5 device
  support), Miscellaneous (update loop, adding a payee, crashes) or the wrong
  fragment.
- Key artifact: "identity verification fails" and "can't activate the virtual
  Visa" form coherent clusters, but each is in one sampled review, so the U rule
  scores them wrong (the X problem of V1/V2 in another form). Diagnostic only,
  U left out: P 62–71%, grab-bags 1–2, R still 49–61%: fails on recall alone.

Checks requested after the run (scratch scripts, no GPU):

- **Bootstrap over reviews** (1,000 resamples, 90% intervals of the medians):
  V3 P 69–81%, R 66–79%, grab-bags 0–3, pass rule met in 46% of resamples; V1
  P 60–78%, R 53–70%, 31%; V4 P 46–65%, R 49–66%, grab-bags 1–4, 0%. On ~220
  labelled units a 5/5 pass is itself a coin toss; the grab-bag gate is the
  noisiest.
- **Size test of C** (round 5's V3 labels, before any move; reviews subsampled,
  clustering fixed): rules 3.6 at 25% of reviews, 8.6 at 50%, 12 at 100%; units
  moved 3.7%, 5.5%, 6.4%. The rule count grows with volume and does not level
  off: the significance test needs an effect-size floor before larger windows.

V4 is spent. Round 6 ends without a pass; the faults left, most severe first:
granularity fixed regardless of window size (grab-bags and fragments in calm
windows), recall lost to the general bucket and Miscellaneous, the cause step's
volume dependence, and the key's U rule for issues rare in the sample (a rule
question for Kevin).

## Production report review (2026-10-09)

The latest production runs (2026-10-08) and the report built from them
(period Aug 26 – Sep 22) were checked by loading the issues the way
`pv report` does and tracing every curated anchor review to its cluster.

- **Curated labels sit on the wrong clusters.** The anchors were picked
  against an earlier run and have moved. "App won't open; reinstalling
  doesn't help" held "Old app was perfect. This new app is horrid" (1,496
  reviews, a grab-bag); "Credit card payment-due info missing" held the
  sarcasm cluster "Way to go RBC"; "'Technical difficulties' error" took the
  fingerprint cluster on a tie. Ten labels matched no cluster. Nothing warns.
- **Praise was hidden.** The `hide` label's 14 anchors caught 8 positive
  clusters, about 860 reviews (18% of the stream), among them "Great app,
  easy to use" (406). An uncurated cluster titled "Easy to use" merged into
  the curated label of the same name and took the keyword-guessed area.
- **Quotes off topic.** Leiden places every unit, and 27–32% of units sit
  below 0.5 cosine to their cluster's centre. Quotes are picked by
  thumbs-up with no relevance check: "The restaurant works" under "It
  doesn't work half the time".
- **Rising flags inflated** by those weak members: three of the six reviews
  behind "It doesn't work half the time" (6, usually 2.0) match weakly.
- **Confirmed from the trials:** tone clusters, and the identity-verification
  story filed under cheque deposit.

Decision 4 removes the curation layer rather than fixing it. The production
clustering (D, E) is not being repaired; the design below replaces it.

## Prior methods (literature, 2026-10-09)

Read from abstracts and summaries, not the full papers.

| Method | What it does | What we take |
|---|---|---|
| **LLooM** (Lam et al., CHI 2024) | **Distill**: an LLM extracts quotes, then 2–4 bullets of 5–8 words. **Cluster**: embed the bullets, HDBSCAN, outliers stay unassigned. **Synthesize**: GPT-4 with step-by-step reasoning writes each concept as a 2–4 word name, a one-sentence inclusion criterion and example ids. **Review**: merge redundant concepts, drop ones too general or too specific. **Score**: each item against each concept on a 5-point agree scale (0–1), with a threshold; an item can match several. **Loop**: unmatched items, and items matching only concepts that cover ≥50% of the data, go round again. 93% coverage against BERTopic's 77.7% | The whole pipeline; Score as the grab-bag fix |
| **TopicGPT** (Pham et al., NAACL 2024) | An LLM generates topics from a sample, refines them (merge duplicates, drop rare ones), then assigns each document with a supporting quotation; two levels | Minting by batch, then refine; areas over concepts |
| **TnT-LLM** (Microsoft) | Builds the category list over successive batches of a sample, then classifies everything against it | Categories from batches, never one item at a time |
| **Clio** (Anthropic) | Extract one attribute per conversation, embed, k-means, LLM names each cluster, then a hierarchy | Extract → embed → name |
| **FeClustRE** (Tiessler & Motger, 2025) | App reviews: hybrid feature extraction, hierarchical clustering with automatic tuning, LLM labels | The same pattern on app reviews |
| **IDEA / MERIT** (Gao et al., ICSE 2018 on) | A topic model per app version that carries the previous version's topics forward and flags emerging ones | Persistent issues, an emerging flag |
| **BERTopic** online mode, `merge_models` | Updates topics as data arrives; a new run's topics join the old ones when similar, otherwise are added | Persistent issues |
| **AR-Miner** (Chen et al., ICSE 2014) | Filter non-informative reviews, group, rank, visualise | Ancestor of our filter step |
| **Speciteller** (Li & Nenkova) | Sentence specificity from 0 (general) to 1 (specific) from light features | A specificity signal |
| **Aspect-based sentiment**; Chhetri et al. 2025 | Sentiment per feature, not per review. 894k reviews of 292 AI apps: 15 negative and 18 positive themes recurring across apps | Praise/complaint per statement; universal areas exist |

Trial 7 minted categories one statement at a time and got 8 catch-alls;
these methods avoid that by minting from a batch.

## Design as it stands (aligned with LLooM, not built)

Replaces the trials 9–11 design (cut, rules, embed + Leiden + range cap).
Carried over from the trials: cutting each review into separate points, one
job per call, prompt examples from an unrelated domain, picking from a short
closed list, naming a group the model can see whole (trials 3–8), and
caching per review.

| Step | LLooM | Ours |
|---|---|---|
| Seed | An optional term steers Distill and Synthesize | "Problems or praise about the app", with the universal area list as context |
| Distill: filter | Exact quotes | Call 1, per review: the exact quote of each complaint or praise point, tagged `complaint` or `praise`. Every review regardless of stars, so a complaint in a 4★ review reaches the complaint side. The quote is the link back to the review |
| Distill: summarize | 2–4 bullets of 5–8 words | Call 2: one short bullet per quote. The rules call (feature + failure) goes |
| Cluster | Embed, HDBSCAN, outliers unassigned | The same, with UMAP reduction first as BERTopic does. HDBSCAN on raw 384-d review vectors called 98% noise; the paper doesn't say whether LLooM reduces |
| Synthesize | Name, criterion, examples | The same, on the stronger model |
| Review | Merge; drop too general or too specific | One call over all concepts (replaces trial 5's pairwise tidy) |
| Score | Every item against every concept | Every bullet against every concept, or against its 10 nearest by embedding (cheaper; open) |
| Loop | Unmatched and generic-only items go again | The same; this is where new concepts and areas are minted |
| Persist | Concepts score new data | Concepts (id, name, criterion, area, members) are stored permanently. Each new period is scored against them and its leftovers loop. Merges and renames are logged. This is the stable issue id |
| Hierarchy | Loop again for broader concepts | Areas are the upper level: seeded with the universal list, extended by Loop |

**Universal area seed** (proposed, not approved): Sign-in & account access,
Stability & performance, Install & updates, Devices & compatibility, UI &
usability, Privacy & security, Customer support, Features (anything
app-specific), General sentiment. Team pages map to areas as before.

**Unchanged:** fetch; translate (French only); the 20-character floor; a
review counts once per issue it reaches; concepts span the whole corpus and
a report counts its period as a slice; every statement keeps its review id
and its closeness to the concept, and pages list members closest first (no
separate quote-selection step).

### Model, speed and cost

Locally (Qwen3.5 9B) calls run one at a time at 1–2 s each: about 3–4 hours
for a 1,000-review trial and about 30 hours to score the full corpus.
Through an API, tens of calls run in parallel: about 10 minutes and about an
hour.

Estimated for the full corpus: 17,948 reviews of 20+ characters, about 1.5
bullets per review, about 100 concepts. Token counts are from character
lengths (±30%); prices are from third-party trackers and need confirming on
openai.com.

| Setup | Score against every concept | Score against the 10 nearest |
|---|---|---|
| **GPT-5.4 nano (distill, score) + GPT-5.4 mini (synthesize, review)** | ~$80 | ~$31 |
| All GPT-5.4 nano | ~$71 | ~$21 |
| All GPT-5 nano | ~$20 | ~$6 |

The Batch API halves each figure. Scoring is most of the cost, as in LLooM
(80% there). On the nano + mini mix, the 1,000-review trial is about $3–4
and each month of new reviews afterwards under $1.

## Open problems

### Design faults, most severe first (2026-10-09)

1. **Grab-bag groups.** Embedding similarity groups by shared topic words,
   so generic statements ("account info", "web browser") have neighbours and
   join the nearest group. *Plan:* LLooM's Score step decides membership
   against each concept's criterion. A specificity signal (word rarity or
   Speciteller, the per-group `focus()` check in `cluster/vague.py`, Loop's
   generic-only rule) keeps generic statements from seeding groups.
2. **The area list.** Areas are the top level of the output. Gaps: identity
   verification (this period's main theme), notifications, accounts &
   statements. Payments, Investing and Budgeting are app-specific. *Plan:*
   the universal seed list; new areas minted by Loop from leftovers, batch
   and refine as in TopicGPT and TnT-LLM.
3. **Period size vs. minimum group size.** A month is about 80 negative
   reviews. *Plan:* concepts form over the whole corpus and persist; a
   period is scored against them, so it never has to form groups alone.
4. **No stable issue identity.** Every run grouped from scratch and nothing
   was kept (`pv run` rebuilds `reviews.db`; `llm_cluster.py` only prints).
   *Plan:* persistent concepts (Design, Persist).
5. **One yes/no call decided what is vague.** Rules v2 dropped "app crashes
   after recent update" and "technical difficulties ... 10% of the time"
   and kept "I need a new phone or a new bank". *Plan:* the rules call goes;
   Review and Loop handle generic statements. If a filter stays, its prompt
   needs fixing (e.g. "the app as a whole" counts as a feature for crashes
   and errors).
6. **No group names.** *Plan:* Synthesize.
7. **The range cap is weak.** Raising `--pull` from 0.4 to 0.55 moved only
   6–11 statements. Superseded by Score.
8. **Complaints in 4–5★ reviews.** *Plan:* cut every review and tag each
   statement complaint or praise.

### Decisions still needed before the trial

1. **Specificity:** which signal or signals; low scorers to Miscellaneous or
   dropped.
2. **Areas:** approve the seed list; minting automatic or proposed and
   approved; where a new area shows until it has a team page.
3. **Generic failures:** "app crashes", "won't open", "technical
   difficulties error" as Stability issues, or as vague.
4. **Persistent concepts:** the score threshold for joining; renames allowed
   and logged; merges and splits automatic or approved.
5. **Praise:** grouped and shown, or used only to rescue complaints from
   4–5★ reviews.
6. **Scoring:** against every concept (as LLooM) or the 10 nearest.
7. **Trial slice:** 1,000 reviews over 12 months (exercises persistence and
   Loop) or the 200-review samples.
8. **Provider sign-off** for OpenAI (decision 7).

### Set aside (validation and operations)

- Nothing is scored against a hand-labelled set; one 200-review sample has
  been judged by eye.
- Group count only tried at 200 reviews.
- Backfill time, no model in the Docker image, repeatability, compliance of
  the local model (moot if decision 7 holds).

Next: settle the decisions above, build the aligned steps as spike scripts
with the model as a setting, and run the 1,000-review slice.

## Sources (methods and pricing)

- [LLooM: Concept Induction (arXiv 2404.12259)](https://arxiv.org/abs/2404.12259v1), [code](https://github.com/michelle123lam/lloom)
- [TopicGPT (arXiv 2311.01449)](https://arxiv.org/html/2311.01449v2)
- [TnT-LLM (summary)](https://hackernoon.com/tnt-llm-automating-text-taxonomy-generation-and-classification-with-large-language-models)
- [Clio (arXiv 2412.13678)](https://arxiv.org/pdf/2412.13678)
- [FeClustRE (arXiv 2510.18799)](https://arxiv.org/abs/2510.18799v1)
- [What Users Value and Critique: AI-powered mobile apps (arXiv 2506.10785)](https://arxiv.org/abs/2506.10785)
- [MERIT: emerging app issues via online sentiment-topic tracing](https://deepai.org/publication/emerging-app-issue-identification-via-online-joint-sentiment-topic-tracing); [IDEA, ICSE 2018](https://www.springerprofessional.de/doi/10.1145/3180155.3180218)
- [BERTopic online topic modeling](https://huggingface.co/kisejin/TopicModelingRepo/blob/main/BERTopic/docs/getting_started/online/online.md)
- [AR-Miner, ICSE 2014](https://ink.library.smu.edu.sg/sis_research/2323)
- [Speciteller](https://www.cis.upenn.edu/~nlp/software/speciteller.html)
- [Analysing app reviews for software engineering: a systematic literature review](https://link.springer.com/article/10.1007/s10664-021-10065-7)
- [Aspect extraction and sentiment classification of app reviews (arXiv 1712.03430)](https://arxiv.org/pdf/1712.03430)
- Pricing: [Morph](https://morphllm.com/openai-api-pricing), [Price Per Token: GPT-5.4 nano](https://pricepertoken.com/pricing-page/model/openai-gpt-5.4-nano), [Puter](https://developer.puter.com/tutorials/openai-api-pricing/)

## Sources (model choice)

- [Qwen (Wikipedia)](https://en.wikipedia.org/wiki/Qwen)
- [Artificial Analysis: Qwen3.5 small models](https://artificialanalysis.ai/articles/qwen3-5-small-models)
- [Gemma 4 vs Qwen 3.5 benchmark matchups](https://gemma4all.com/blog/gemma-4-vs-qwen-3-5-benchmarks)
- [BenchLM: Gemma 4 12B](https://benchlm.ai/md/models/gemma-4-12b.md)
- [Gemma 4 vs Qwen 3.5 — MindStudio](https://www.mindstudio.ai/blog/gemma-4-vs-qwen-3-5-open-weight-comparison)

## Embedding route, round 7: granularity from the data (set 2026-10-14, before running)

Fault (round 6, V4): one granularity for every window. Each of the 100 consensus
runs searches for 35–50 clusters itself, so the consensus can only repeat that
granularity: in a calm window small issues are forced together (grab-bags) and
large ones split (fragments).

Established method: **evidence accumulation clustering** (Fred & Jain 2005):
base clusterings at varied granularity, then the co-association matrix cut by
stability rather than a target count. The cut used here is HDBSCAN's
excess-of-mass selection on the co-association distance, with the minimum
cluster size a share of the window (BERTopic's guidance that min_topic_size
scales with corpus size); units in no stable cluster are noise (Miscellaneous)
instead of a forced cluster.

- **E:** per order, one band search finds the resolution r* for 35–50 clusters;
  the 100 base runs then use Leiden at r* × e^u, u uniform on [ln ¼, ln 2]
  (coarser to finer), each filtered as before; HDBSCAN (precomputed 1 − co,
  min_samples 5, EOM) with min cluster size max(5, f × units).
- **F (floor):** C's rules also need lift ≥ 1.5 (round 6's size test: the rule
  count grows with volume under the significance test alone; V3's real links
  had lift 1.66–1.87).

Variants: v1 = round 6 v2 + E (f = 0.5%) + F; v2 = + E (f = 1%) + F;
drop-one E and F. Development: V1–V4 (V4 spent in round 6). Criteria: V3 and V4
≥ 4 of 5 orders meeting all four gates; V1 and V2 median P and R no more than 3
points below round 6 v2, grab-bags and tone no higher.

Held out: **V5**, 100 reviews drawn (seed 0) from May–June 2025, window
March–June 2025 (overlaps no earlier slice's), V4's draw rule. 227 units of 84
reviews labelled blind before any run (`trials/runs/prellm/v5/labels.txt`,
sha256 `6551c0959274d4af…`, labeller Claude, conventions as V4; the U rule is
kept). The bundle runs once.

Added within the round after v1 and v2 failed the development criteria (V1
recall 50.5% and 53% against 62%; noise units left in Miscellaneous), set
before running: **v3** = v1 + noise units join the cluster they co-occur with
most when the mean co-association is ≥ 0.2 (outlier reduction: BERTopic
`reduce_outliers`, HDBSCAN soft clustering).

### Result: no variant passes development (2026-10-14). V5 not run

| Variant | V4: P | R | Grab-bags | Pass | V1: P | R | Pass |
|---|---|---|---|---|---|---|---|
| Round 6 v2 | 53% | 54% | 3 | 0/5 | 69% | 62% | 3/5 |
| v1: E, f = 0.5% | **60.5% (55–67)** | **62%** | 2 (1–2) | 0/5 | 70% | **50.5%** | 0/5 |
| v2: E, f = 1% | 51% | 57% | 3 | 0/5 | 70% | 53% | 0/5 |
| v3: v1 + outlier join | 55% | 61% | 3 | 0/5 | 68% | 57% | 0/5 |

- E does what it was meant to on V4: finer clusters where the window has many
  small issues (30 kept against 17), P and R both up about 8 points. But on V1
  it leaves ~100 units as noise and recall falls 11 points; ARI drops from 0.88
  to about 0.69 (base runs at random resolutions agree less).
- The outlier join recovers part of V1's recall (57%) and V4's stability (ARI
  0.84) but gives back V4's precision.
- No variant meets the criteria on V4 or V1, so the drop-ones, V2, V3 and the
  held-out run were not made. V5 stays unspent; its key is frozen.

Round 7 ends without a pass. Two rounds since the handoff have each fixed the
fault they targeted on the window that showed it (V3's symptoms, V4's
granularity) and lost elsewhere, while round 6's bootstrap puts a 5/5 on ~220
labelled units at 31–46% odds. Further tuning against these keys risks fitting
their noise; see the handoff for the options put to Kevin.

## Embedding route, round 8: where V4's losses happen (2026-10-17, screens only)

Diagnosis first: r6v2's saved V4 labels, order 0, traced stage by stage (set-aside,
consensus, cluster review, W5, C). Of the issue units that end outside every issue
cluster, 18 of 21 leave with a whole cluster at the review (9 to the general bucket,
9 to Miscellaneous), 2 at W5, 1 at the set-aside. Of the 33 missed issue points: about
12 are sentences that name no feature ("doesnt work at all", "Technical difficulties,
every time", "RBC fix this asap") and carry their issue only through the review; about
11 sit in a neighbouring issue's cluster (biometrics in two-step verification, blocked
account in device access, GrapheneOS in phone compatibility); about 6 belong to issues
too small for a cluster in this window (adding a bill or payee, late Visa alerts,
crashes); about 4 are specific sentences grouped with general ones on the bank's name
("No RBC Mobile app is available for my Samsung tablet" with "I love rbc"). Both
grab-bags are mostly U units.

Three fixes screened on saved labels, no new model calls; none got a full run:

- **D, split broad clusters** (LLM-confirmed splitting of low-cohesion clusters,
  arXiv 2603.08159; recursive re-clustering, arXiv 2510.16152): each broad cluster
  re-clustered into 2–4 children. Children stay vague ("technical difficulties",
  "no idea why"); about 3 of 18 look specific, carrying 1–3 issue points, mostly U.
  Not worth the calls.
- **Rm, similarity rescue from removed clusters** (BERTopic reduce_outliers,
  embeddings, at each kept cluster's 10th-percentile member): 113 units join, of the
  labelled ones 4 right and 33 wrong. Fail.
- **Ci, context attribution for units outside the issue list** (round 6's C,
  Hai et al. 2011, extended to Miscellaneous and general-bucket units in a review
  with a kept issue unit), all slices, 5 orders:

| Slice | r6v2: P | R | Grab | Pass | Misc, one cluster: P | R | Grab | Pass |
|---|---|---|---|---|---|---|---|---|
| V1 | 69% | 62% | 1 | 3/5 | 55% | 64.5% | 2 | 0/5 |
| V2 | 52% | 61.5% | 3 | 0/5 | 40% | 61.5% | 4 | 0/5 |
| V3 | 72% | 70% | 1 | 5/5 | 73% | 71% | 1 | 5/5 |
| V4 | 53% | 54% | 3 | 0/5 | 45% | 57% | 5 | 0/5 |

  Recall rises 1–3 points (up to 8 with the general bucket included) and precision
  falls 7–20: the keys mark most such sentences G, X or U. Fail.

Round 8 ends without a full run; V5 stays unspent. What V4 still lacks is mostly the
key's conventions rather than a fault a single method change reaches: sentences filed
by their review's cause, issues finer than one team's area, and the U rule. Each
remaining reachable loss is worth 3–4 recall points on V4, against 6 needed in
precision and recall at once.

### Round 8 continued: finer clusters before the review (set 2026-10-17, before running)

Fault (V4 trace above): about 11 missed points sit in a neighbouring issue's cluster
and about 6 belong to issues with no cluster of their own, so the clusters are coarser
than the issues before the review sees them. Neither P nor R penalises a finer split
(each cluster is credited with its own majority issue); only grab-bags, tone and the
minimum cluster size push back.

Established method: over-cluster, then reduce (BERTopic's guidance to fit many topics
and reduce after; Janssens et al. 2025, arXiv 2509.19365, LLM-assisted reduction of an
over-clustered BERTopic model). The reduce step only fixes fragments, which no gate
counts; it is left out unless the content check shows fragments a reader would mind.

- v1 = r6v2 with the band at 50–70 clusters before the review (was 35–50)
- v2 = r6v2 with the band at 60–85
- v3 = v1 with a minimum cluster size of 3 (was 5)

Development: V4 first (the window that shows the fault), then V1, V3, V2. Criteria:
V3 and V4 ≥ 4 of 5 orders meeting all four gates; V1 and V2 median P and R no more
than 3 points below r6v2, grab-bags and tone no higher. A variant that clearly fails
V4 stops there. The bundle that meets them runs once on V5.

### Result: v2 best; meets V1 and V3, fails V2 and V4 on X and U clusters (2026-10-18)

| Run | Slice | P | R | Tone | Grab-bags | ARI | Pass |
|---|---|---|---|---|---|---|---|
| r6v2 | V4 | 53% | 54% | 0 | 3 | 0.81 | 0/5 |
| v1 (50–70) | V4 | 50% (48–53) | 61% (54–65) | 0 | 4 (2–5) | 0.77 | 0/5 |
| **v2 (60–85)** | V4 | 55% (53–55) | **71% (68–71)** | 0 | 5 (4–5) | 0.88 | 0/5 |
| v3 (v1, min 3) | V4 | 50.5% (49.5–56) | 63% (62–65) | 0 | 5 (1–5) | 0.78 | 0/5 |
| **v2** | V1 | 70% (69–71) | 62% (60–62) | 0 | 1 (0–1) | 0.89 | 3/5 |
| **v2** | V2 | 47% (44–48) | 69% (65–74) | 1 (1–2) | 3 (2–3) | 0.89 | 0/5 |
| **v2** | V3 | 77% (73–77) | 69.5% (69–72) | 0 | 1 (1–1) | 0.86 | 5/5 |

About 12 minutes per variant on V4, V1 and V2; V3 took 57 minutes (ETA 45: the
finer band search on 4,362 units). Criteria: V3 met, V1 met (no worse), V2 fails
(P 5 points below r6v2, limit 3), V4 fails (0/5). V5 not run.

Content check: every grab-bag read on V4 and V2, order 0, is a coherent cluster but one:
V4 "two-step verification, biometrics, trusted devices" (one area, three key issues),
"only on the website" (U), "balance shows the previous day" (U), and one real mix
(credit-card sign-up, credit score, a loan, a locked account); V2 "no tablet app"
(X), "e-transfer daily limits" (N, U), "forced to install the app" (X, U). The recall
gain is real: dark mode, adding a payee and GrapheneOS get clusters of their own.

Diagnostic, scored with U (and on V1/V2 X) units left out of the key, saved labels:
V4 v2 P 71%, R 71%, grab-bags 1, **5/5** (r6v2 0/5); V2 v2 P 78%, R 69%, **5/5**
(r6v2 3/5); V1 v2 P 82%, R 59%, 0/5 (recall binds). Not a pass: the gates are
unchanged.

Next fault, V1 recall (trace of order 0): 10 of 20 lost issue units are left
unclustered by the consensus, mostly long sentences naming two or three faults.

Screened after the result, on saved r8v2 labels (no model calls), for V1's recall:
**A, clause assignment** (BERTopic `approximate_distribution`: a Miscellaneous unit is
split into clauses and joins the kept cluster its best clause reaches at that
cluster's 10th- or 25th-percentile member). V1 R unchanged (61.7%), P 58–65% (from
70%); V2 and V4 P down 2–4, R up 1–2. Fail. V1's missed points are mostly the
incident's one flow filed under three key issues: 4 of 9 missed "photo capture"
points sit in the trusted-device cluster ("adding a trusted device does not work,
there is no capture image button when scanning back of license").

## Embedding route, round 9: the reduce step (set 2026-10-18, before running)

Fault (r8v2, every slice): fragments. One issue spread over several kept clusters
(V1: two-factor in 5, sign-in in 4; split 3–5 per slice). No gate counts them, but a
reader sees one problem listed several times. Established method: the second half
of over-cluster-then-reduce (Janssens et al. 2025, LLM-assisted merging of an
over-clustered topic model): **M**, each kept cluster's 2 nearest kept clusters by
centre are candidate pairs; one model call per pair on the 6 members closest to each
centre ("same problem, fixed together by one team" or "different", examples from
another domain); pairs judged the same merge (union-find). Before C.

Variant: r9v1 = r8v2 + M. Criteria, on V4, V1, V2 then V3: split lower than r8v2;
median P and R no more than 2 points below r8v2; grab-bags and tone no higher; the
pass gates as before. A merge that joins two key issues raises grab-bags, which the
criteria catch. Content check: read every merged pair of order 0.

### Result: M fails (2026-10-18)

| Run | Slice | P | R | Grab-bags | Split | Clusters | Pass |
|---|---|---|---|---|---|---|---|
| r8v2 | V4 | 55% | 71% | 5 | 5 | 31 | 0/5 |
| r9v1 | V4 | 50.5% | 65% | 6 (6–8) | 4 | 22 | 0/5 |
| r8v2 | V1 | 70% | 62% | 1 | 5 | 24 | 3/5 |
| r9v1 | V1 | 57% | **49%** | 1 | 2 | 11 | 0/5 |
| r8v2 | V2 | 47% | 69% | 3 | 2 | 33 | 0/5 |
| r9v1 | V2 | 47% | 69% | 2 | 2 | 25 | 0/5 |

26 minutes for the three slices. Content, V1 order 0: 14 of 36 pairs judged the same,
24 clusters became 13; merged were e-transfer with cheque deposit, e-transfer with
"turn off USB debugging", repeated verification prompts with crashing, verification
with "security setup is garbage". The local model says "same" far too readily and
union-find chains the pairs. V3 not run; M dropped. Best bundle stays **r8v2**.
