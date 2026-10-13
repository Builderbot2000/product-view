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
It was built as a spike ([lloom.py](spike/lloom.py), trials 12–13). On
2026-10-13 it first **failed the [viability test](#viability-test-criteria-set-2026-10-13-before-any-run)**
(39% precision; merges and the loop made catch-alls), then **passed its
structural gates** once merging was replaced by a breadth check, a frozen
codebook and selection, with two marginal results. The same day it replaced
embedding clustering in the pipeline as `pv issues`
([issues/](src/product_view/issues/)), with the model as a setting.

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

## Scripts

All in [spike/](spike/), run with `.venv/Scripts/python.exe -X utf8`. Output
goes to `out/llm-spike/` (gitignored, local only).

| Script | Does |
|---|---|
| [llm_extract.py](spike/llm_extract.py) | Call 1, cut only. Per review: the list of `{problem, area}` it contains, or none, with no filtering. Cached as JSONL by review id and `PROMPT_VERSION`. `--n`, `--recent` (newest N instead of a random sample weighted to Oct 2024) |
| [llm_refine.py](spike/llm_refine.py) | Call 2, rules only. One call per statement returns its `feature` and `failure`; code drops the statement if either is empty. Writes `-refined-v<RULES_VERSION>.jsonl` with `issues` (kept) and `dropped` |
| [lloom.py](spike/lloom.py) | The LLooM design end to end (trial 12): distill, cluster (UMAP + HDBSCAN, needs the `[umap]` extra), synthesize, review, score, loop. Every model call cached by request in `lloom-calls-<model>.jsonl`. `--n`, `--negative-only`, `--min-size`, `--threshold`, `--nearest`, `--loops`. Writes concepts, scores and a report to `out/llm-spike/lloom-<settings>/` |
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

### 12. LLooM steps end to end (newest 100 reviews, all stars)

First run of the aligned design ([lloom.py](spike/lloom.py)), still on the
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

Prompt changes in [lloom.py](spike/lloom.py), checked with `--dry` (stop
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
[lloom.py](spike/lloom.py) (`--month`, `--prior`, `--overlap`) and
[viability.py](spike/viability.py) (label sheets, gate scoring, the
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
