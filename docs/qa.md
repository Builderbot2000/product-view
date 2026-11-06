# Product View Q&A

## The central algorithm: how reviews are sorted into topics

| Question | Answer | Show |
|---|---|---|
| How does it work, in short? | Each review is cut into its separate complaints. For every topic in the Ownership Matrix, the AI writes a dozen example complaints. A small classifier learns from those examples and scores every complaint against every topic. When it's clearly one topic, that's the answer. When nothing fits, it's left as "no topic". Only the unclear ones go to the AI, which picks from the top few topics while reading the whole review | [method.py:1](../src/product_view/matching/method.py#L1), [match_reviews](../src/product_view/matching/run.py#L49) |

| Step | What happens | Where |
|---|---|---|
| 0. Which reviews | 1–3 star reviews from the reporting period and the periods before it, so trends have history | [run.py:29](../src/product_view/matching/run.py#L29), [run.py:89](../src/product_view/matching/run.py#L89) |
| 1. Cut into complaints | Split at sentence ends and words like "but", "also", "however". Then join neighbouring pieces back together when they're about the same thing (a small embedding model judges this). One piece = one complaint | [units.py:38](../src/product_view/matching/units.py#L38) split, [units.py:80](../src/product_view/matching/units.py#L80) join |
| 2. Examples per topic | The AI writes 12 example complaints for each topic from its name and description. It also writes complaints that name no feature, and complaints about features not on the list, so the classifier learns what "none of these" looks like | [method.py:91](../src/product_view/matching/method.py#L91), prompts at [method.py:41](../src/product_view/matching/method.py#L41) |
| 3. Turn text into numbers | Every complaint and example becomes a vector (Qwen3 embedding model), so similar meaning = nearby numbers | [embed.py:76](../src/product_view/matching/embed.py#L76) |
| 4. Score every topic | One small classifier per topic (logistic regression), trained on the examples. Complaints it's ≥ 90% sure of are added to the training set, and it trains once more | [method.py:106](../src/product_view/matching/method.py#L106) |
| 5. Decide the route | Best score ≥ 0.8 and runner-up < 0.5 → take the best topic ("sure"). Best < 0.6 → no topic ("misc"). Anything else → ask the AI | [method.py:139](../src/product_view/matching/method.py#L139), thresholds at [method.py:34-38](../src/product_view/matching/method.py#L34-L38) |
| 6. AI decides the unclear ones | One call per complaint: the sentence, the whole review for context, and up to 5 candidate topics. It may pick one, several or none, but only from those candidates | [method.py:154](../src/product_view/matching/method.py#L154), prompt at [method.py:60](../src/product_view/matching/method.py#L60) |
| 7. Review gets its topics | A review counts under a topic if any of its complaints matched it | [run.py:106](../src/product_view/matching/run.py#L106) |
| 8. Saved | Every run is kept, with each complaint, its route, its score and its topics | [matching/store.py:27](../src/product_view/matching/store.py#L27) |

## Follow-up questions about the algorithm

| Question | Answer | Show |
|---|---|---|
| Why not have the AI read every review and summarize? | A single summary can't be split by feature owner or counted over time. Sending every review to the AI is also slow and expensive. Here the AI handles only the unclear complaints | [method.py:139](../src/product_view/matching/method.py#L139) (the gate) |
| Why cut reviews into pieces? | One review often complains about two features, e.g. login and then e-Transfers. Cutting it up lets each complaint go to its own topic | [units.py:1](../src/product_view/matching/units.py#L1) |
| How much does the AI actually do? | It writes the examples (once, then cached) and decides the unclear complaints. The clear cases and "no topic" need no AI call | [run.py:67-72](../src/product_view/matching/run.py#L67-L72) |
| Can the AI invent topics or go off-list? | No. Topics come only from the Ownership Matrix, and any answer outside the candidates offered is thrown away | [method.py:170-176](../src/product_view/matching/method.py#L170-L176) |
| What happens to a review that fits no topic? | It's counted as "did not fit a topic" and shown with examples, so gaps in the topic list are visible | [method.py:142](../src/product_view/matching/method.py#L142), [report/data.py:1](../src/product_view/report/data.py#L1) |
| How do you know it's accurate? | It's checked against two samples labelled by hand. Of the topics it assigns, about 8 in 10 are right, and it finds about two-thirds of what a person would. One sample was kept aside and never used while building, and it scored about the same | [check.py:1](../src/product_view/matching/check.py#L1), pass bar at [check.py:55](../src/product_view/matching/check.py#L55) |
| How do you re-run the accuracy check? | `pv check-matching` runs the same code as the pipeline on both samples and prints pass or fail | [check.py:129](../src/product_view/matching/check.py#L129) |
| What did you try before this? | Six rounds, each written down before it ran, plus a final test on the sample kept aside | [trials/topic-trials.md](../trials/topic-trials.md) |
| How do topics get changed? | Edit the topic's description in the Ownership Matrix. The next run re-matches everything | [matrix.sample.yaml](../matrix.sample.yaml) (the guidance on writing descriptions is at the top) |

## One review, from Play Store to the report

A real 1★ review from Sep 17, 2026, followed to the number at the top of Priya Shah's report: **"Trusted device and ID check: 12 reviews, well above the usual 4.7."** The run uses the sample Ownership Matrix and the reporting period Aug 26 – Sep 22, 2026. The same journey as a diagram: [architecture.md](architecture.md#one-review-from-play-store-to-the-report).

> *"Keeps asking to send in photos of IDs and selfies after submitting and accepting. Figure your stuff out, please."*

| Stage | What this review looks like there | Code |
|---|---|---|
| 1. Fetched | Google Play returns it with its star rating, date, app version and thumbs-up. The reviewer's name and photo are dropped on arrival | [play_store.py:172](../src/product_view/ingest/play_store.py#L172), [models.py:57](../src/product_view/ingest/models.py#L57) |
| 2. Raw archive | One line added to `data/raw/com.rbc.mobile.android_en_ca.jsonl`: `review_id 6d9545b4…`, `score 1`, `created_at 2026-09-17T20:57:22Z`, `app_version 4.67`, `thumbs_up 1` | [archive.py:91](../src/product_view/ingest/archive.py#L91) |
| 3. Review database | All language files merged, each review kept once, into the `reviews` table of `reviews.db` | [prepare.py:30](../src/product_view/prepare.py#L30), [store.py:148](../src/product_view/store.py#L148) |
| 4. Language | Detected as English (99.9% sure), so the text goes through unchanged. A French review would be translated here, with the original kept | [prepare.py:60](../src/product_view/prepare.py#L60), [detect.py:71](../src/product_view/lang/detect.py#L71) |
| 5. Picked for matching | 1–3 stars and inside the 12 periods the report shows, so it's one of 747 complaint reviews in the run | [store.py:192](../src/product_view/store.py#L192), [run.py:86-90](../src/product_view/matching/run.py#L86-L90) |
| 6. Cut into complaints | Two pieces: **(0)** "Keeps asking to send in photos of IDs and selfies after submitting and accepting" and **(1)** "Figure your stuff out, please" | [units.py:80](../src/product_view/matching/units.py#L80) |
| 7. Scored against every topic | Piece 0 scores 0.83 for "Trusted device and ID check", with no other topic close. Piece 1 tops out at 0.45 | [method.py:106](../src/product_view/matching/method.py#L106) |
| 8. Routed | Piece 0 is "sure" (≥ 0.8, runner-up < 0.5): matched with no AI call. Piece 1 is "misc" (< 0.6): no topic | [method.py:139](../src/product_view/matching/method.py#L139), thresholds at [method.py:36-37](../src/product_view/matching/method.py#L36-L37) |
| 9. Stored | `topics.db`, run `20261104T234449Z`: both pieces in `units` with route and score; one row in `matches`: piece 0 → `trusted-device`, `how = sure` | [run.py:103-108](../src/product_view/matching/run.py#L103-L108), [matching/store.py:47-65](../src/product_view/matching/store.py#L47-L65) |
| 10. Counted | Sep 17 falls in this period, so the review is added to the topic's set for period 0. It's a set of review ids, so a review counts once however many pieces match | [report/data.py:142-148](../src/product_view/report/data.py#L142-L148), [periods.py:51](../src/product_view/periods.py#L51), [periods.py:83](../src/product_view/periods.py#L83) |
| 11. This period and usual | 12 distinct reviews this period. The 3 periods before held 9, 4 and 1, so usual = 14 ÷ 3 = 4.7 | [periods.py:97-103](../src/product_view/periods.py#L97-L103) |
| 12. Up or down | With a usual of 4.7, a count of 12 or more happens by chance about 3 times in 1,000. That's under the 5% bar, so the topic is **up** | [periods.py:106-123](../src/product_view/periods.py#L106-L123), bar at [periods.py:16-17](../src/product_view/periods.py#L16-L17) |
| 13. Its quote | Its matched piece becomes its quote. "Sure" matches are listed before the AI's, so it's among the 5 quotes shown under the topic | [report/data.py:150-160](../src/product_view/report/data.py#L150-L160), ranking at [report/data.py:31-36](../src/product_view/report/data.py#L31-L36) |
| 14. On the page | The topic moved most among Priya's topics, so it leads her report: "The one to look at first is 'Trusted device and ID check': 12 reviews, well above the usual 4.7." It's also a row in the topic table, with its 12-period trend | [parts.py:168](../src/product_view/report/parts.py#L168), [text.py:69](../src/product_view/report/text.py#L69), [parts.py:128](../src/product_view/report/parts.py#L128), [member.py:53](../src/product_view/report/member.py#L53) |
| 15. Also counted | The same review counts toward 75 complaints across the whole app this period, and toward the Sign-in & security team page and Sam Gagnon's report, which share this topic | [report/data.py:163-170](../src/product_view/report/data.py#L163-L170), [team.py:43](../src/product_view/report/team.py#L43) |

The same trail in the data files:

```sql
-- data/reviews.db
SELECT review_id, score, created_at, app_version, content
  FROM reviews WHERE review_id = '6d9545b4-88cf-4834-b4a6-23950985be4a';

-- data/topics.db
SELECT seq, route, best_topic, p1, text FROM units
 WHERE run_id = '20261104T234449Z' AND review_id = '6d9545b4-88cf-4834-b4a6-23950985be4a';
SELECT seq, topic_id, how FROM matches
 WHERE run_id = '20261104T234449Z' AND review_id = '6d9545b4-88cf-4834-b4a6-23950985be4a';
```

## Where is it in the code?

| Question | Answer | Show |
|---|---|---|
| Where is the diagram of the whole system? | The architecture page | [architecture.md](architecture.md) |
| Where is the diagram of one review's journey? | Below the system diagram, on the same page | [architecture.md](architecture.md#one-review-from-play-store-to-the-report) |
| Where does a run start? | `pv cycle` runs every step once, in order | [cycle.py:117](../src/product_view/cycle.py#L117) |
| Where are all the commands listed? | The command-line entry point; each command lives with the code it runs | [cli.py:1](../src/product_view/cli.py#L1) |
| Where are the settings? | One settings file. Built-in defaults fill in anything it leaves out | [config.yaml](../config.yaml), defaults at [config.py:27](../src/product_view/config.py#L27) |
| Where are reviews fetched from Google Play? | The Play Store reader, the only file tied to Google Play | [play_store.py:143](../src/product_view/ingest/play_store.py#L143), command at [commands.py:36](../src/product_view/ingest/commands.py#L36) |
| Where is the raw data kept? | `data/raw/`, one file per language listing, only ever added to | [archive.py:91](../src/product_view/ingest/archive.py#L91) |
| Where is the review database built? | Rebuilt from the raw data on every run, each review kept once | [prepare.py:30](../src/product_view/prepare.py#L30), tables at [store.py:26](../src/product_view/store.py#L26) |
| Where is language detection? | Detected from each review's own text | [detect.py:57](../src/product_view/lang/detect.py#L57) |
| Where is translation? | French to English, cached | [translate.py:90](../src/product_view/lang/translate.py#L90) |
| Where is the Ownership Matrix? | `matrix.yaml`, which stays out of the code repository. The repository has a sample with the same format | [matrix.sample.yaml](../matrix.sample.yaml), loader at [matrix.py:88](../src/product_view/matrix.py#L88) |
| Where are the topics defined? | Under `topics:` in the Ownership Matrix | [matrix.sample.yaml](../matrix.sample.yaml) |
| Where is a review cut into complaints? | Split, then joined back where pieces agree | [units.py:38](../src/product_view/matching/units.py#L38), [units.py:80](../src/product_view/matching/units.py#L80) |
| Where is the matching algorithm? | Whole method in one file, run by one function | [method.py](../src/product_view/matching/method.py), [run.py:49](../src/product_view/matching/run.py#L49) |
| Where are the AI prompts? | The example-writing prompts and the topic-picking prompt | [method.py:41-76](../src/product_view/matching/method.py#L41-L76) |
| Where are the thresholds? | Fixed with the method, not settings | [method.py:34-38](../src/product_view/matching/method.py#L34-L38) |
| Where is the AI model called? | One gateway for every provider | [llm.py:226](../src/product_view/llm.py#L226) |
| Where is the AI model chosen? | The `llm:` section of the settings | [config.yaml](../config.yaml) |
| Where are the embedding models? | Qwen3 for matching, MiniLM for cutting reviews into complaints | [embed.py:32-34](../src/product_view/matching/embed.py#L32-L34) |
| Where is the cache? | `cache.db`. AI answers and embeddings are looked up there before any call | [llm.py:207-224](../src/product_view/llm.py#L207-L224), [embed.py:111](../src/product_view/matching/embed.py#L111) |
| Where are matching results stored? | `topics.db`, every run kept | [matching/store.py:27](../src/product_view/matching/store.py#L27) |
| Where is the accuracy check? | The check command, plus the hand-labelled samples and answer keys | [check.py:129](../src/product_view/matching/check.py#L129), [acceptance/](../src/product_view/matching/acceptance/) |
| Where are the counts per topic worked out? | Read from the latest matching run and split into periods | [report/data.py:119](../src/product_view/report/data.py#L119) |
| Where is the up/down test? | The period comparison | [periods.py:106](../src/product_view/periods.py#L106) |
| Where are quotes ranked? | The report's data layer | [report/data.py:31-37](../src/product_view/report/data.py#L31-L37) |
| Where is each page built? | One file per page type | [overview.py:81](../src/product_view/report/overview.py#L81), [team.py:43](../src/product_view/report/team.py#L43), [member.py:53](../src/product_view/report/member.py#L53) |
| Where are the charts drawn? | Sparklines, bars, trend panels and the heatmap | [report/svg.py](../src/product_view/report/svg.py) |
| Where is the page converted for Confluence? | HTML to Confluence's page format | [storage.py:50](../src/product_view/publish/storage.py#L50) |
| Where is publishing to Confluence? | Pages pushed parents first, updated in place | [report/build.py:90](../src/product_view/report/build.py#L90), [confluence.py:152](../src/product_view/publish/confluence.py#L152) |
| Where is the container defined? | The image build, and a local run setup | [Dockerfile](../Dockerfile), [compose.yaml](../compose.yaml) |
| Where are the tests? | Core logic and report pages | [tests/](../tests/) |
| Where is the record of what was tried? | The matching trials, round by round | [trials/topic-trials.md](../trials/topic-trials.md) |

## The whole pipeline

| Question | Answer | Show |
|---|---|---|
| What happens, start to finish? | Fetch reviews → build the database → translate French → match to topics → build reports → publish to Confluence | [architecture.md](architecture.md), [cycle.py:117](../src/product_view/cycle.py#L117) |
| How is it started? | One command, `pv cycle`, runs everything once and exits. A scheduler decides when it runs | [cycle.py:1](../src/product_view/cycle.py#L1) |
| Where do reviews come from? | Google Play, read page by page in every language listing. A weekly run stops when it reaches reviews it already has | [play_store.py:143](../src/product_view/ingest/play_store.py#L143) |
| Where is the raw data kept? | A raw archive that's only added to, never deleted. Everything else is rebuilt from it | [archive.py:1](../src/product_view/ingest/archive.py#L1), [store.py:1](../src/product_view/store.py#L1) |
| What about French reviews? | Each review's language is detected from its text, and French is translated to English by a local model. The original is kept next to the translation | [detect.py:1](../src/product_view/lang/detect.py#L1), [translate.py:1](../src/product_view/lang/translate.py#L1) |
| Where are teams, members and topics defined? | The Ownership Matrix, one file. It's checked before each run, and a broken file stops the run before anything is fetched | [matrix.sample.yaml](../matrix.sample.yaml), checks at [matrix.py:95](../src/product_view/matrix.py#L95) |
| What if a step fails? | Nothing is published unless every step before it succeeded, so there's never half a report | [cycle.py:117-190](../src/product_view/cycle.py#L117-L190) |
| Can two runs collide? | No. A lock file lets only one run at a time | [cycle.py:63](../src/product_view/cycle.py#L63) |

## The report

| Question | Answer | Show |
|---|---|---|
| What's a "period"? | 28 days, ending on the day of the newest review | [config.yaml](../config.yaml) (`report:`), [periods.py:33](../src/product_view/periods.py#L33) |
| What does "usual" mean? | The average count over the 3 periods before this one | [periods.py:101](../src/product_view/periods.py#L101) |
| How is "up" or "down" decided? | A statistical test asks whether this period's count is surprising given the usual rate, so 1 → 3 reviews isn't flagged as "tripled". Anything under 3 reviews never counts as a change | [periods.py:106](../src/product_view/periods.py#L106) |
| What exactly is counted? | Distinct reviews, not sentences. A review that mentions login twice counts once | [periods.py:83](../src/product_view/periods.py#L83) |
| How are the quotes chosen? | Matches the classifier was sure of come first, and very short pieces come last. This changes which quotes show, never the counts | [report/data.py:25-37](../src/product_view/report/data.py#L25-L37) |
| What pages are there? | An overview of the whole app (for analysts), one page per team, and one report per member covering only their topics | [report/build.py:1](../src/product_view/report/build.py#L1), [overview.py](../src/product_view/report/overview.py), [team.py](../src/product_view/report/team.py), [member.py](../src/product_view/report/member.py) |
| How are the charts made? | Drawn as SVG images in code and attached to the page | [report/svg.py](../src/product_view/report/svg.py) |
| How does it get to Confluence? | Through Confluence's API. A page with the same title is updated in place, so each run becomes a new version and the page history is the archive | [confluence.py:152](../src/product_view/publish/confluence.py#L152) |
| What about email? | Planned, not built yet. A run currently ends at publishing | [cycle.py:3](../src/product_view/cycle.py#L3) |

## Running it at RBC

| Question | Answer | Show |
|---|---|---|
| Which AI model does it use? | A local model today (Qwen 3.5 9B through Ollama). Switching to RBC's approved model is a setting, not a code change | [config.yaml](../config.yaml) (`llm:`), [llm.py:1](../src/product_view/llm.py#L1) |
| Does review text leave the machine? | Not with the local model. On RBC's cloud it would go only to the approved in-house model. The reviews are public Play Store text anyway | [llm.py:1](../src/product_view/llm.py#L1) |
| What does it cost to run weekly? | Every AI answer and embedding is cached, so a weekly run pays only for new reviews. With a paid API model there's also a spending cap | [llm.py:207-248](../src/product_view/llm.py#L207-L248), [embed.py:111](../src/product_view/matching/embed.py#L111) |
| If RBC's model is different, does accuracy still hold? | Re-run the accuracy check on the new model before go-live. It has a fixed pass bar | [check.py:1](../src/product_view/matching/check.py#L1) |
| How would it be deployed? | One container image that runs one cycle and exits. It has no credentials inside, works with a read-only file system and a corporate proxy, and can bundle the models for hosts without internet | [Dockerfile](../Dockerfile) |
| Where do passwords and keys go? | Environment variables only, never the config file or the image | [confluence.py:1](../src/product_view/publish/confluence.py#L1), [Dockerfile](../Dockerfile) |
| Is it tested? | Automated tests cover the core logic and the report pages | [tests/test_core.py](../tests/test_core.py), [tests/test_report.py](../tests/test_report.py) |
