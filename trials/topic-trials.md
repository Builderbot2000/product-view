# Topic matching trials

Matching reviews to the fixed topic list (report-design.md §9, D18). Kevin,
2026-11-02: no model call per review; try clustering seeded by the fixed topics
first. Topics: the 22 in [matrix.sample.yaml](../matrix.sample.yaml), the mock
used for all development (the real matrix never enters this repo).

## Keys

Written by Claude from review text alone, before any matching run on the window,
with the conventions in each file's header. Same caveat as the embedding-route
keys: the labeller also builds the method.

| Slice | Window | Draw | Units | sha256 | Status |
|---|---|---|---|---|---|
| T1 | 2026-05-23 .. 2026-09-22 (the demo window) | 120 of 294 reviews, seed 0 | 306 | `91b05210211b63d6…` | development |
| T2 | 4 months to 2024-06-30 | 120 reviews, seed 0 | – | – | held out; label before any run on it |

T1 holds 13 of the 22 topics; 9 (change-password-pin, remember-me,
etransfer-receive, statements-documents, more-settings-menu, alerts-notifications,
profile-contact-details, connectivity, forced-update) have no unit in it. Of 306
units, 149 are general opinion or filler (G, N) and 38 are specific complaints no
topic covers (O): sign-in loops, Direct Investing, dark mode, fees, card management.

Run: `.venv/Scripts/python.exe -X utf8 trials/topics/match.py <variant>`; key and
sheet with `trials/topics/key.py`. Keys and runs are under `trials/runs/topics/`
(gitignored).

## Criteria (set 2026-11-02, before any run)

Scored on the 120 drawn reviews as (review, topic) pairs, as the report counts
them: a review is matched to a topic if any of its units is. The method runs on
all of the window's units (765); only drawn reviews are scored.

- **M1** micro precision ≥ 70%
- **M2** micro recall ≥ 60%
- **M3** of the drawn reviews whose units are all G, N or O, at most 25% get any topic

Also reported, not gated: per-topic P and R for topics with ≥ 3 key reviews;
unit-level P and R; how many window units land in "no topic".

Round rules carried over from the embedding route: at most 3 variants a round,
each reported; a bundle meeting M1–M3 on T1 runs once on T2; read a sample of the
actual matches after every run, not only the numbers.

## Round 1: zero-shot anchors, then Lbl2Vec-style refinement

Embedder: Qwen3-Embedding-0.6B. Units are embedded as queries with the
instruction "Given a sentence from a mobile banking app review, identify the app
feature it complains about"; topic anchors are embedded as documents (no
instruction) from "name: description".

A **null class** decides "no topic": four generic anchors, written before any
run ("This app is bad and I am unhappy with it", "I am going to switch to
another bank", "It doesn't work", "Terrible service, very frustrating"). A unit
takes the topics whose similarity beats its best null anchor by a margin and is
within δ of its best topic.

- **A, zero-shot:** anchors as written. Margin 0, δ 0.03.
- **B, refined (Lbl2Vec, Schopf et al. 2021; seeded k-means, Basu et al. 2002):**
  A's matches over the whole window, keeping each topic's units with margin
  ≥ 0.05; the anchor becomes the mean of the description vector and those units;
  assign again; 3 iterations.
- **C:** B, then units left unmatched are clustered (BERTopic's zero-shot topic
  modelling keeps the unmatched to form new topics) for the "no topic" section.
  C changes no match, so it is reported by reading its groups, not gated.

**Results (T1):**

| Variant | P (M1 ≥ 70%) | R (M2 ≥ 60%) | False alarm (M3 ≤ 25%) | Unmatched units |
|---|---|---|---|---|
| A | 40% | 70% | 45% | 377 / 765 |
| B | 55% | 53% | 23% | 521 / 765 |

C matches as B; its leftover groups were not read because B fails. **Fails.**

Reading the matches:
- The null class barely filters in A: "the more you spend" and "That was our Child Tax
  Credit saving!" took topics at margins of +0.01 to +0.03.
- **A null anchor overlaps a topic.** "Terrible service, very frustrating" competes
  with customer-support; in B, where the null anchor also absorbs the surest
  no-topic units, customer-support recall falls from 50% to 11%. A design fault in
  the null list, not a threshold matter.
- **One-sentence descriptions are thin anchors.** Biometric sign-in takes 119
  units in A and 54 in B: nearly every sign-in or security complaint, since the
  mock list has no general sign-in topic. Receive-e-Transfer takes 28 units in B,
  all about sending. Topic names that differ in one word sit too close.

## Round 2: expanded topic anchors (set 2026-11-02, before the run)

Thin label descriptions are the known weak point of zero-shot matching; the
standard remedy is to expand each label into example texts and match against
those: seed word lists in guided topic models and Lbl2Vec, and hypothetical
documents (HyDE, Gao et al. 2022) in retrieval. Here the local model writes them:
**one call per topic** (22) plus one for the null class, never per review.

The prompt gives only the topic's name and description and the sibling topic
names (so it writes what is specific to this topic, not what a neighbour covers),
and asks for 12 short complaints a user might write. The null class asks for 12
complaints that name no app feature (general anger, switching banks, "doesn't
work"); it replaces round 1's four hand-written anchors. Examples are embedded
as queries with the units' instruction, so unit-to-anchor similarities compare
like with like.

- **D:** each topic's anchor is the mean of its examples (a prototype); the null
  class likewise. Margin 0, δ 0.03.
- **E:** D, then B's refinement (3 iterations, seed margin 0.05).
- **F:** D, but a unit's similarity to a topic is its mean similarity to the 3
  nearest of that topic's examples (k-NN, not the prototype).

**Results (T1):**

| Variant | P (M1 ≥ 70%) | R (M2 ≥ 60%) | False alarm (M3 ≤ 25%) | Unmatched units |
|---|---|---|---|---|
| D | 43% | 85% | 65% | 315 / 765 |
| E | 43% | 84% | 65% | 314 / 765 |
| F | 43% | 75% | 55% | 367 / 765 |

**Fails.** The examples lift recall (A 70% → D 85%) and fix the round 1
neighbour confusions (customer-support R 78%, trusted-device R 81%), but
precision does not move. Reading D's wrong matches: most are a right topic plus a
neighbour within δ ("PIN to verify an e-transfer" also takes change-password-pin;
"my phone can't read my card" takes three topics), and general or off-list units
that clear the null prototype by a few hundredths.

Diagnostic on D's saved setup, sweeping the null margin and δ (not a variant; no
setting is chosen from it): the best precision at recall ≥ 60% is 57%, and
reaching false alarm ≤ 25% needs a margin that drops recall to 44%. **A
similarity threshold against one null prototype cannot meet M1–M3 together on
T1**, so round 3 changes the decision rule rather than the threshold.

## Round 3: a classifier trained on the examples (set 2026-11-02, before the run)

The established method for a fixed label set with a handful of examples each and
no model call per item is a light classifier on sentence embeddings, trained on
those examples: SetFit (Tunstall et al. 2022) fine-tunes the encoder and fits a
logistic-regression head; the head alone on frozen embeddings is its cheap form.
It learns the boundary between neighbouring topics instead of one cosine cut.

Training set: round 2's 12 examples per topic and 12 null examples, plus **one
more call** for 24 complaints about banking-app features *not* on the list
(open-set negatives: what "no topic" looks like when it is specific, the O units).
Null and off-list examples together form the negative class.

- **G:** one-vs-rest logistic regression (C = 1, class-balanced) on the frozen
  query embeddings; a unit takes every topic with probability ≥ 0.5.
- **H:** G, then self-training (Yarowsky 1995): window units given a topic with
  probability ≥ 0.9 join the training set with that label, and the classifier is
  refit once.

**Results (T1):**

| Variant | P (M1 ≥ 70%) | R (M2 ≥ 60%) | False alarm (M3 ≤ 25%) | Unmatched units |
|---|---|---|---|---|
| G | 54% | 80% | 48% | 388 / 765 |
| H | 57% | 80% | 48% | 392 / 765 |

**Fails** M1 and M3; the best so far. Per topic, H is at P ≥ 75% and R ≥ 69% on
two-step-verification, trusted-device, etransfer-send, device-support and
customer-support. Of H's 85 wrong unit matches on the key:
- **etransfer-receive takes 14 units, every one about sending.** Direction
  ("send" against "receive") barely moves the embedding; "e-transfer" dominates.
- forced-update (9) and technical-error (8) take general update and "technical
  problems" complaints; some are fair calls the key's conventions 5 and 6 rule out.
- The rest are a right topic plus a neighbour on multi-topic units.

Next, by expected effect (not yet set as a round):
1. **Fine-tune the encoder on the examples** (full SetFit: contrastive pairs make
   sibling topics push apart, which the frozen embedding cannot do). Needs the
   `setfit` package or a short sentence-transformers training loop; minutes on GPU.
2. **A model check only where the classifier is unsure**: units within a band of
   0.5, or matched to two sibling topics. Breaks "no call per review" only for the
   doubtful fraction; Kevin's call.
3. Mock-list fit: the mock has no general sign-in topic, so sign-in complaints
   (the window's largest theme) must all fall to "no topic". A real list may
   differ; the method should still hold "no topic" without one.

## Round 4: the model decides only the ambiguous units (set 2026-11-02, before the run)

Kevin, 2026-11-02: the local model may run on units whose classifier match is
ambiguous, and nowhere else; and is batching them into larger calls more
efficient?

**Gate** (H's classifier; set from its probability spread on the window, without
the key). p1 and p2 are a unit's two highest topic probabilities:
- sure topic: p1 ≥ 0.8 and p2 < 0.5 → the top topic only
- sure no topic: p1 < 0.4
- otherwise ambiguous → the model. On T1's window: 63 sure, 271 none, **431 of
  765 (56%) ambiguous**. H's probabilities are poorly spread (12 synthetic
  examples per topic), so the gate passes more than hoped.

**Model step** (local Qwen3.5 9B, temperature 0, JSON schema): for each ambiguous
unit, the sentence, its whole review for context (first 400 characters), and as
options the topics with p ≥ 0.3 (at most 5, by probability), each with its
description. The model returns the options the sentence complains about, or none.
Topics outside the options cannot be chosen.

- **I:** one unit per call.
- **J:** 10 units per call, the same options per unit, answers keyed by item.
  Reported against I: wall time, calls, and P/R/false alarm; plus how often the two agree.

**Results (T1):**

| Variant | Calls | Time | P (≥ 70%) | R (≥ 60%) | False alarm (≤ 25%) |
|---|---|---|---|---|---|
| I, 1 unit a call | 431 | 906 s | **75%** | 81% | 35% |
| J, 10 units a call | 44 | 342 s | 66% | 89% | 61% |

I passes M1 and M2 and **fails M3**. The first run to clear precision.

**Batching:** 10 units a call is 2.7× faster (0.8 s against 2.1 s a unit) but
costs 9 points of precision and 26 of false alarm; I and J give different topic
sets on 161 of the 431 routed units. The batched model picks more topics per
unit. This repeats the issue stage's finding (batch 30 against 15: precision −8
points).

Reading J's 66 wrong matches (I's are a subset of the same kinds):
- 23 are vague complaints ("constant technical issues", "still doesn't work!")
  given technical-error or app-crash-launch. Key conventions 5 and 6 call them G;
  a reader of those topics might want them. The convention stands (no key change
  after seeing results).
- Most of the rest are off-list complaints given the nearest option: dark mode
  to more-settings-menu, Direct Investing outages to app-crash-launch, credit
  limit letters to alerts-notifications. The model sees only candidate topics,
  and "choose none" in the instructions does not offset that pull.

## Round 5: an explicit "none" option (set 2026-11-02, before the run)

Every item's options end with "none: general opinion or praise, or a problem
with something not listed above". Forced-choice framing is the known cause of
over-assignment when the true answer is outside the candidates; a visible
abstain option is the standard remedy. Otherwise as round 4.

- **K:** 1 unit a call.
- **L:** 5 units a call, to place the batching cost between I and J.

**Results (T1):**

| Variant | Calls | Time | P (≥ 70%) | R (≥ 60%) | False alarm (≤ 25%) |
|---|---|---|---|---|---|
| K, 1 a call, "none" option | 431 | 946 s | 73% | 84% | 45% |
| L, 5 a call, "none" option | 87 | 414 s | 69% | 86% | 55% |

**Fails; the "none" option makes false alarm worse** (I 35% → K 45%), so round 4's
I stays the best. Batching costs accuracy again, roughly in proportion to batch
size: 1 → 5 → 10 units a call gives P 73/69/66% (K, L, J), at 2.2, 0.96 and
0.8 s a unit.

I's 11 false-alarm reviews (of 31 with no topic in the key): 5 are vague
"technical issues / not working" complaints given technical-error or
app-crash-launch (2 by the classifier's sure path, 3 by the model); the rest are
off-list complaints given a near topic (Direct Investing to balances, credit
limit letters to alerts, a sign-in loop to app-crash-launch). The first five sit
on key convention 5, which is stricter than the topic's own description
("generic error messages such as technical difficulties"). The T1 key is not
changed; the convention question goes to Kevin.

## Round 6: a misc bin for overly ambiguous units (set 2026-11-02, before the run)

Kevin's call: leave the overly ambiguous units out and route them by a fixed
rule to a misc bin. Misc is not a topic: the classifier and the model never see
it, and it is not scored as a topic. On the report it is a count of what did not
fit. Key convention 5 therefore stands (vague complaints are G), as does the T1 key.

Base is I (one unit a call). Units sent to misc skip the model, so the
remaining prompts are identical to I's and come from the cache.

- **M, weak:** misc if the best topic's probability is below 0.6 (before: no
  topic below 0.4, model from 0.4). Only clearer units reach the model.
- **N, generic:** misc if the unit is more similar to the generic-complaint
  examples (`_null`) than to the examples of its best topic (best cosine to
  each set). Applies on the sure path too, since 2 of I's 5 vague false alarms
  came from there.
- **O:** M and N together.

Criteria M1–M3 unchanged. Also reported: units and reviews in misc, and model calls.

**Results (T1):**

| Variant | Model calls | P (≥ 70%) | R (≥ 60%) | False alarm (≤ 25%) | Misc units / reviews |
|---|---|---|---|---|---|
| I (round 4) | 431 | 75% | 81% | 35% | – |
| M, weak → misc | 215 | **84%** | **67%** | **13%** | 216 / 154 |
| N, generic → misc | 293 | 78% | 68% | 23% | 147 / 113 |
| O, both | 185 | 83% | 58% | 13% | 255 / 176 |

**M and N pass all three; O fails recall.** M is chosen. It has the widest margin on false
alarm, the simplest rule (one threshold), and half of I's model calls. Its recall
margin is thin (67% against 60%), so T2 decides.

Reading the 45 units that I matched and M sends to misc (in the key): 16 were
wrong matches. Those are the intended catch: vague "still doesn't work", "always
technical issues", Direct Investing outages, credit-limit letters, a sign-in
loop. The other 29 were right and are lost, mostly short or indirect mentions
("Two factor verification", "Still no foldable support after 8 years", "Are you
going to speak English when I call?"). Two-step-verification loses most (R 38%).

The misc bin is large: 154 of 294 reviews have a unit in it, mostly
general opinion and praise, which also had no topic before.

Next: write T2's labelling conventions (1–10 as T1, unchanged), label T2 blind,
then run M once on T2.

## T2: held-out test of M (key written 2026-11-02, before any run on the window)

Window 2024-03-01 .. 2024-06-30: 572 units, 204 reviews; 120 reviews drawn (seed 0),
344 units labelled from the review text alone. Key: `trials/runs/topics/t2/labels.txt`,
sha256 420339cacb2c05694d041b1b8009858664344e740fc3b1b4fd49011af3b0beb5. Conventions
are T1's. Two clarifications were set before labelling: an unnamed "verification" before an
e-transfer is etransfer-send (a named kind also gets its own topic), and a
forgotten-password reset is O. The window is dominated by the 2024 rollout of
e-transfer verification (card tap, ID check, approval on another device).

M runs once, unchanged. Pass = M1–M3 as T1.

**Result (T2, one run):** P **78%**, R **65%**, false alarm **12%**. **M passes all
three on held-out data.** 188 of 572 units went to the model (188 calls, 419 s);
159 units (102 reviews) went to misc.

| Topic | Key | Given | P | R |
|---|---|---|---|---|
| etransfer-send | 45 | 38 | 100% | 84% |
| two-step-verification | 27 | 17 | 76% | 48% |
| customer-support | 20 | 15 | 87% | 65% |
| trusted-device | 15 | 5 | 80% | 27% |
| device-support | 10 | 9 | 89% | 80% |
| technical-error | 9 | 9 | 56% | 56% |
| balances-transactions | 5 | 4 | 100% | 80% |

Reading the 26 wrong and the trusted-device / two-step misses:
- **Approval sent to another device reads as alerts-notifications** (6 of 26
  wrong). The sample matrix describes two-step-verification as a "code sent by
  text message or call". It does not mention app approvals, which make up
  most of 2024's two-step complaints. The key follows convention 2. The method
  follows the description.
- **Short, plain sign-in security mentions go to misc**: "2FA does not work…",
  "Do yourself a favor and don't activate two-step", "trusted device nonsense".
  These are the losses already seen on T1. The weak-unit rule costs recall
  mostly on these two topics.
- **The ID check before an e-transfer gets etransfer-send but not trusted-device**
  (5 misses). Half right, scored as a miss.
- The rest are scattered: a password reset to change-password-pin, a login page
  bug to mobile-cheque-deposit, vague "technical issues" to technical-error
  (3, the T1 kind).

Reading: topic descriptions decide much of the accuracy. A description that
leaves out a common form of the feature (app approvals) loses those
complaints to a neighbouring topic. The real matrix's descriptions should be
written with that in mind (each topic's common forms named), and checked
against a month of matches when first deployed.

## D1: revising the sample's descriptions (2026-11-04)

The 2026-11-04 review of the demo pages found wrong quotes that came from
descriptions: sign-in approvals filed under alerts, an ID photo under cheque
deposit, vague "technical problems" under the error topic. Kevin: fix the
descriptions by hand, as production would. Method, thresholds and models
unchanged; scored with `pv check-matching --matrix matrix.sample.yaml --detail`.

Round 1 rewrote eight descriptions from the error patterns on both keys,
following the writing guide in the sample's header: two-step-verification
(approvals on another device, the second step before sending money),
trusted-device (identity checks, the phone not remembered), etransfer-send
(card tap and PIN), mobile-cheque-deposit (not ID photos), alerts-notifications
(not sign-in or payment approvals), technical-error (a message shown, not
technical problems in general), device-support ("not compatible", watches,
custom Android, USB debugging), customer-support (branches, assistant, help
pages, unhelpful answers). Round 2 added the words users write for the
second step ("2FA", "two-factor", "two-step"): short mentions such as
"2FA does not work" had fallen just under the misc cutoff.

| | t1 P / R / false alarm | t2 P / R / false alarm | keyed reviews wrong (t1, t2) |
|---|---|---|---|
| frozen descriptions | 84 / 67 / 13 | 80 / 66 / 12 | 41, 59 |
| round 1 | 90 / 70 / 3 | 83 / 71 / 12 | 32, 48 |
| round 2 (kept) | 89 / 69 / 3 | 83 / 71 / 8 | 33, 45 |

Stopped after round 2: it moved little over round 1, and further rounds would
fit the two keys. Caveat: round 2 was written after reading t2's errors, so
t2 is no longer unseen; a fresh key would be needed for an unbiased number.
What still goes wrong is mostly the known kind: short sign-in security
mentions in misc, the ID check before an e-transfer, and approvals the
model still files under alerts when two-step is not among its options. The
acceptance check keeps scoring the frozen descriptions, so its baseline is
unchanged.
