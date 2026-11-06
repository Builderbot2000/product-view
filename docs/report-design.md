# Report design: decisions and plan

Design decisions for stage (F) `pv report`, made 2026-10-03. Read with
[Project.md](legacy/Project.md): §0 "Still open" has the Confluence probe results, and
§2 (F) and (G) have the render and publish summaries. This file has the detail
and the next steps, written so a fresh session can start building.

## 0. How these decisions were reached (2026-10-03 session)

- **Starting point.** The demo moved to a new Confluence site
  (kevintangcyberium.atlassian.net). `pv publish` worked there first time. A
  quick plain-HTML page of the real pain points (built by a throwaway script)
  rendered, but looked crude: plain tables, cramped columns, unreadable
  text-glyph sparklines.
- **Kevin's direction:** don't base the design on that preview. The UX comes
  first, and **the aggregated data may change to serve what the UX wants to
  offer.** Clustering output is an input to the design, not a constraint on
  it.
- **Usage scenario (from Kevin):**
  - The Mobile product team already gets raw reviews from a Slack bot.
  - The team has asked for richer delivery: role-customised Confluence pages
    sent to team members.
  - Pages would be published through **a real employee's developer account
    acting as a service account.**
  - Analysts should be upgraded, not replaced.
  - A competing internal effort uses weaker models and publishes by hand.
- **Concerns raised, not yet acted on** (delivery was deferred until after the
  demo):
  - An employee's account as the publisher means every page is authored as
    them, and publishing breaks if they leave or the token rotates.
    Atlassian service accounts or an OAuth app are the proper fix, and IT
    should be asked.
  - Confluence has no inbox. "Sent to inboxes" in practice means @mentions or
    watchers (Confluence then emails people) or a Slack link.
  - Another account usually can't write into people's personal spaces.
- **Kevin's answers to the open questions:**
  - Role views: all four (analysts, PMs, Engineering/QA, Support/CX).
  - Delivery: both @mentions and Slack.
  - Cadence: weekly plus each release.
  - LLM: only a company-approved internal model. *Revised 2026-10-08: a
    small model run locally (Qwen3.5 9B through Ollama) for compliance,
    pending approval. It groups issues as well as naming them
    ([llm-trials.md](../trials/llm-trials.md)).*
  - Then: **demo first, delivery infrastructure later.**
- **Design canvas tried, then set aside.** A claude.ai Design canvas
  (link in §4) was mocked up with real data. It was first built as a manager
  briefing, then judged wrong for analysts once the scenario was known.
  Because it relies on CSS, which Confluence strips, the decision was to
  design directly in real Confluence pages once the probes showed what
  renders. The canvas stays only as a visual reference.
- **Probes.** Probe 1 (HTML through `pv publish`) confirmed the HTML route
  caps the page at plain tables. Probe 2 (raw storage format) confirmed the
  native vocabulary in §3. That made D1 and D2.

## 1. Who it's for

- **Users:** the Mobile division product team. They already get raw Play
  Store reviews in Slack from a bot. Product View adds the aggregated view.
- **Primary users are the analysts who interpret reviews.** The report gives
  them evidence to build their own reports from. It does not replace them, and
  it is not a manager summary.
- **Role views:**

  | Role | What the view emphasises |
  |---|---|
  | Review analysts (primary) | Every theme, evidence behind every number, quotes ready to cite, change since the last run |
  | PMs / feature owners | Issues in their feature area |
  | Engineering / QA | Release regressions, version breakdowns, login / compatibility issues |
  | Support / CX | Issues users raise with support, developer-reply coverage |

- **Competition:** an internal effort on weaker models (Haiku, Cohere), with
  little automation and pages published by hand. It will likely produce text
  summaries and plain tables. We win on depth, charts, traceable evidence and
  change over time, not on prose.
- **Demo first.** Delivery infrastructure (mentions, Slack, schedules,
  service accounts) waits until after the demo.

## 2. Decisions

| # | Decision | Why |
|---|---|---|
| D1 | `pv report` emits **Confluence storage format**, not HTML | HTML conversion drops layout and styling and leaves plain tables. Native layouts and macros render well (probe 2) |
| D2 | **Charts are SVGs we design**, uploaded as page attachments. The `chart` macro is not used | Styled SVG renders intact. The `chart` macro works but looks dated |
| D3 | **Full-width pages**, set through the `content-appearance-published` / `-draft` content properties | Confirmed over REST. The default page width squeezes wide tables |
| D4 | **Page tree per run:** a hub page (analyst view), one child page per top issue, role pages | Nothing is interactive, so different views have to be different pages |
| D5 | **Shared sections:** sections are built once, wrapped in named `excerpt`, and reused on role pages with `excerpt-include` | One source for every view, and analysts can reuse the same sections in their own pages. `excerpt` and `excerpt-include` across pages are both confirmed, including tables, status lozenges and SVG images (probe 3, 2026-11-02) |
| D6 | **Issue names:** a label written by the **company-approved internal model** (assume it is weak), with the medoid quote shown under it as "in users' words". The current extractive title is the fallback | Today's titles are raw review sentences ("It is frustrating"). The model's job is narrow and checkable. All numbers stay deterministic, and the report must work without the model |
| D7 | **General sentiment is kept apart from actionable issues.** Clusters with no specific cause ("This app is terrible") get their own section, not the ranked list | In the current run, 4 of the top 8 negative clusters are mood, not a cause |
| D8 | **Near-duplicate clusters are shown merged.** Example: two update-prompt clusters (930 + 972 reviews) | Duplicates split the volume and crowd the list |
| D9 | **Cadence: weekly, plus each app release** (later). Delivery: page @mentions and Slack links (later). A weekly run still reports a 28-day period (D15), so each week is a rolling update | Settled with the team's needs in mind. Not needed for the demo |
| D10 | **Raw data stays in the store; views derive their numbers.** No pre-computed classifications baked into the data | Fits the role-view model: each page computes its own cut of the same data |
| D11 | *Superseded by D15.* Recent activity leads; all-time is context (90-day / 365-day pace) | Replaced when the report became periodic |
| D12 | **Several orderings of the same rows, not one ranked list.** The hub orders by change ("What changed"), by area, and by volume within an area. Impact (an all-time score) no longer ranks anything | Impact alone ranked 6 mood or outcome clusters in the top 14. Fits D10: readers pick the cut |
| D13 | **Outcomes are their own kind,** apart from issues and mood: "switching banks", "other banks are better". They feed the KPI tiles, not the issue tables | They are consequences of issues, not causes, and are the strongest single number for a manager reading over an analyst's shoulder |
| D14 | **Hand curation lives in `curation.yaml`,** keyed by **label**: kind (issue / mood / outcome / hide), areas, and **anchor reviews**. On every run a cluster takes the label whose anchors it holds (an anchor goes to the cluster it is the medoid of, else where its unit is most central); several clusters under one label merge, counted as distinct reviews | Demo stand-in for D6–D8. Cluster ids change whenever a scheduled run re-clusters; anchors survive that. An uncurated cluster keeps its extractive title, marked "auto-labelled", and is filed by area keywords |
| D15 | **The report is a periodic overview** (decided 2026-10-03). It covers one period (default 28 days, ending on the newest review's day) against "usual": the mean of the 6 equal periods before it. Change is a Poisson test against that rate (p < 0.05, at least 3 reviews), not a ratio. Quotes come from the period. Clustering still spans all history | Negative reviews run at ~55–80 a month (15–20 a week), so a week leaves most issues at 0–3 reviews, and ratios on small counts mislead ("1 → 3 = ×3"). 28 days matches the release rhythm (4.64 Jun 9, 4.65 Jul 7, 4.66 Aug 11, 4.67 Sep 9). Clustering only the period's ~70 reviews would give a few unstable clusters; full history keeps definitions stable and the report counts the period's share |
| D16 | **Issues are filed by product area; roles read areas.** Areas and roles live in `curation.yaml`. The hub shows every area; each role gets a child page with only its areas (e.g. the UI & design team never sees sign-in connectivity). An issue can sit in several areas; the first is where the hub files it | A team member should see only what their team can act on. The mapping is a view-level lookup, not stored in the data (D10), and editable without touching code |
| D17 | **Demo standard (decided 2026-10-14): 4 months of issues, complaints only.** `pv issues` runs on the local Qwen3.5 9B over a 4-month window (about 390 reviews, ~6,600 calls, ~19 h at the 10 s a call measured in the port check); "usual" is the mean of 3 periods, not 6; the per-issue heatmap shows only the periods the issue window covers; praise issues are left out. The review-count trend keeps all 12 periods, since it reads reviews directly | Scoring cost grows with the square of the window: the full 12-month layout is ~53,000 calls (~110 h). Three baseline periods keep the change flags working on small counts. Praise prompts are not validated. A full window and 6 baseline periods return when runs are cheaper or scheduled (llm-trials.md, "Cost controls") |

## 3. Confluence building blocks (all confirmed by probe 2)

Probe 2 source: [trials/confluence/build_confluence_probe_native.py](../trials/confluence/build_confluence_probe_native.py).
The live probe page was deleted on 2026-11-04; the builder above recreates it.

| Use | Storage element |
|---|---|
| Dashboard grid | `<ac:layout>` with `<ac:layout-section ac:type="three_equal" \| "two_right_sidebar" \| "single" …>`. Once used, the whole body must sit inside the layout |
| KPI tile | `panel` macro with `bgColor` and `borderColor`, holding an `<h1>` number and a coloured caption |
| Trend / state tags | `status` macro: `colour` = Red / Blue / Grey / Green / Yellow / Purple. Works inside table cells |
| Heat-map cells | `<td data-highlight-colour="#ffebe6">`; column widths with `<colgroup><col style="width: …px"/>` |
| Callouts | `info` / `note` / `warning` / `tip` |
| Evidence on demand | `expand` (can hold tables) |
| Navigation | `toc`, `anchor` macro + `<ac:link ac:anchor>`, `<ac:link><ri:page ri:content-title>` |
| Reusable section | `excerpt` with a `name` parameter |
| Metadata | `details` (page properties), `<time datetime>`, `code` |
| Text colour | `<span style="color: …">`, `<span style="background-color: …">` |
| Charts | `<ac:image><ri:attachment ri:filename="x.svg"/></ac:image>` plus the file uploaded with `Client.sync_attachments` |

**Doesn't work:** CSS classes, `<style>`, flexbox and grid, scripts, `<div>`
bars, `href="#id"` links. Note that `toc` also lists headings inside panels,
so KPI tiles shouldn't use `<h1>` on a page that has a table of contents (or
the `toc` should be given `minLevel` / `maxLevel`).

## 4. Visual language

From the design canvas (reference only; it uses CSS that Confluence strips):
https://claude.ai/artifact/2pguJCqs8HS6TfqhkW9azc (private). It has three
artboards: Briefing, Issue deep dive, Priority map.

- **Colours:** ink `#16191D`, muted `#596069`, grid lines `#E3E4E1`, neutral bars
  `#A3A8AE`. A change is coloured by what it means for the app (`blocks.tone`),
  so the same direction differs by stream: complaints up / new are *worse*
  (orange `#B43C0A`), complaints down and praise up are *better* (green
  `#1F7A3A`), praise down is *fading* (blue `#2B5FB8`). Green against orange
  is hard for red-green colour-blind readers, so every change also carries an
  arrow and a word (`↑ UP`, `↓ DOWN`), never colour alone.
- **Sparklines:** one bar per period (12 periods), each on its own scale, this
  period on the right in ink, or in its tone's colour when it changed.
- **Change lozenges:** red, green or blue by tone with a matching cell tint;
  `steady` / `quiet` grey.
- **Area chart:** a bar per area for this period with a black tick at usual.
- **Trend (hub):** negative and positive reviews per period as two small
  multiples on their own scales, dashed usual, this period's dot in its tone.
- **Heatmap (hub):** issues by the last 12 periods on one scale from green
  (1 review) through pale yellow to orange-red, topping out at the 95th
  percentile of the grid's counts so one spike doesn't wash the rest green;
  grey for none, counts printed in every cell; this period's column outlined.
- **Dots (role pages):** one dot per reviewer this period under each issue,
  coloured by stars, orange (1★) through grey (3★) to green (5★).
- **Versions (roles with `charts: [versions]`):** each issue's reviews this
  period stacked by app version; the three busiest known versions get blue,
  aqua and violet (checked with the dataviz palette validator), the rest grey.
- **SVG text** uses system fonts (`Segoe UI, Helvetica, Arial`), because web
  fonts don't load inside an attachment. Right-align end labels with
  `text-anchor="end"` (the probe clipped one).

## 5. Pages for the demo

Revised 2026-10-03 (second pass) to make the report periodic (D15) and split
by role (D16). Live: hub 294942 and five role pages under it (§8).

**Hub page (analyst view):**

```
┌ two_equal ───────────────────────────────────────────────────────┐
│ period, links to the role pages │ Area chart SVG: reviews per     │
│ details: period · usual window ·│ area this period, tick = usual  │
│ reviews (usual) · versions ·    │                                 │
│ store rating · app              │                                 │
├ three_equal ─────────────────────────────────────────────────────┤
│ [75 negative, usual 58 ↑]  [12 ↑ UP: Can't log in]  [11 switching]│
├ single ──────────────────────────────────────────────────────────┤
│ What changed this period: new / up / down issues and outcomes ·   │
│   area · this period · usual · change · 12-period sparkline       │
│ By area: one table per area (busiest first), with links to the    │
│   team pages that read it; quiet issues counted, not listed       │
│ ▸ expand: General sentiment and outcomes this period              │
│ ▸ expand: What users liked this period (positive run)             │
│ ▸ expand: Method (periods, change test, clustering, curation)     │
└──────────────────────────────────────────────────────────────────┘
```

Each issue row shows its label and the period's top quote (most thumbs-up,
with stars, date and app version).

**Role page** (one per role in `curation.yaml`, a child of the hub): the
period and areas; three tiles (reviews in these areas vs usual, the top
change, the busiest other issue); a summary table of the role's issues;
then "What users said": per issue a change lozenge, counts, the app
versions this period, a sparkline and up to 3 quotes from the period; and
the positive themes in the same areas. Roles today: UI & design, Sign-in &
security, Payments, Engineering / QA (stability & devices), Support / CX.

**Issue page** (not built): one per issue, with the longer trend, version
history across releases, and quotes over time. Deferred: the role pages
already carry the period's quotes.

## 6. Data work the design needs

Done for the demo: issue kinds (D7, D13), merges (D8), per-issue period
counts and versions, hand labels (D14), period and baseline (D15), areas and
roles (D16). All derived at report time from the existing tables.

Still to do:
1. **Labels** from the internal model (D6), replacing the hand labels.
2. **Quote quality.** A period quote is the review's most central unit in the
   cluster, which is sometimes off-topic (a translated cheque-photo review
   under "App won't open"). Prefer units above a similarity floor.
3. **Release periods** as an alternative to fixed 28 days ("since 4.67"),
   using the first-seen date of each `app_version`.
4. **Developer-reply rate** per issue (from `reviews.reply_content`) for the
   Support / CX page.
5. **Curating new clusters.** An uncurated cluster appears "auto-labelled";
   someone should add it to `curation.yaml` (label, kind, areas, anchor =
   its `canonical_review_id`). A helper command could print the stub.
6. **Validate areas and roles with the team;** the current set is a guess.
7. **Stale attachments:** republishing leaves unreferenced charts on a page.

The project-wide list (tests, scheduling, delivery, clustering, commit) is
Project.md §0 "Remaining work".

Watch out: `pain_points.pct_of_stream` and `pct_one_star` are **already
percentages** (14.1 means 14.1%). Don't multiply by 100.

## 7. Build steps

1. Done: `pv publish` passes storage files (`.xhtml`) through with their
   SVG attachments at full width, retries transient 5xx attachment
   writes, and publishes page trees (`publish_tree`, parent first).
2. Done: `render/` has the storage blocks (`blocks.py`), SVG charts
   (`svg.py`), period and issue derivation (`issues.py`) and the pages
   (`pages.py`). `pv report` builds them from the latest runs; settings are
   in `config.yaml` under `report:`.
3. Done: the hub and the role pages, checked in the browser.
4. Next: test `excerpt-include` (D5) if role pages should reuse hub
   sections verbatim; today each page is generated, so it isn't needed.

## 8. State of the demo site

kevintangcyberium.atlassian.net, space `MFS` (no dedicated space yet;
`pv publish` can't create one):
- Wiped 2026-11-04 (Kevin): every earlier Product View page (the overview,
  team pages, member reports, the retired role pages) and the probe pages
  went to the space trash, and the pages were rebuilt from scratch. The
  probes' findings are recorded here and in §3; their builders stay in
  trials/confluence/.
- "Product View @ RBC Mobile": **the overview page**, under the space home,
  built by `pv cycle --space MFS --parent-id 98427`.
- Under it, one page per team in the sample matrix, and under each team page
  its members' reports, "Name · Team". Publishing moves a page back under its
  intended parent if it was moved. Until email lands (D21), a member's report
  page is what they would be sent.

Per-row SVG sparklines in table cells render well, given an explicit
`ac:width` (without one Confluence stretches them to the cell).

Still open:
- Which internal model and how to call it (API, or chat only).
- Who maintains `curation.yaml` (labels, areas, roles) as new clusters appear.
- Whether the developer account can write to the team's space.

## 9. Requirements change (2026-10-22): a fixed team, member and topic matrix

The requirements changed on 2026-10-22. Reports are now tailored to a fixed
matrix of **team → team member → topic**. Topics are specific app features
("change password or PIN", "more / settings menu"), and they are predefined:
Product View no longer forms its own issues. Each team has several members,
and each member owns several topics. Three operational needs come with it:
the whole application runs in containers, reports reach people by email, and
collection runs on a schedule.

D18–D20 are built, D22 as far as one cycle command (`pv cycle`); D21 (email)
is deferred. Decided 2026-11-03 (Kevin): the overview is one page that is
also the analysts' all-topics view. Team pages are not paired with the old
role pages: every team page comes from one template, since the number of
teams in the real matrix is unknown, and the role pages are retired by hand. Status and build choices: docs/production-plan.md, top. The
Project.md §0 "Requirements change" block
lists what each one supersedes.

| # | Decision | Why |
|---|---|---|
| D18 | **Topics are fixed and given; reviews are matched to them.** Product View never creates, renames or merges a topic. A review can match several topics or none; reviews with no topic are counted and reported as "no topic", so gaps in the list stay visible. Supersedes issue forming (R03's open-ended grouping), D6 (names written by a model), D8 (merging near-duplicate issues) and the issue part of D14 | Teams already know which features they own, and want reports keyed to those features, not to groups the tool invents. A fixed list also keeps every trend's meaning stable: "change password or PIN" means the same thing every period |
| D19 | **One matrix file, in a standard format.** `matrix.sample.yaml` (committed) defines the format with invented content: `topics` (id, name, description) and `teams` (name, mailing list, members with name, email and topics). The real `matrix.yaml` is gitignored and never committed. Every member topic must exist, and every topic needs at least one owner. The matrix replaces `roles` in `curation.yaml`; the `areas` there are kept only while the earlier report still renders | The real matrix is a confidential internal document holding staff names and addresses. Kevin populates the real file from it with an AI assistant, keeping the format, so the format has to be fixed and documented first |
| D20 | **Confluence: one page per team, and one report per member from a standard template.** The team page is the high-level view of every topic its members own. Each member's report covers only their topics, built from one template: the period and their topics; tiles (reviews on their topics against usual, the top change); a table of their topics (this period, usual, change, 12-period trend); then per topic the change, counts, app versions and up to 3 quotes; a link to the team page. The overview page (today's hub) stays as the parent. Supersedes D16's role pages; the role page layout (§5) is the starting point for the template | Managers and leads read at team level; each member wants only what they own. One template keeps every member's report the same shape, so it can be read cold |
| D20a | **Team page and member report split (2026-11-04, Kevin).** The two had one skeleton and read as twins. The **team page** is a lead's overview: a row per member (reviews on their topics against usual, change, what to look at, link), a 12-period trend of the team's topics beside the whole app's, tiles (team total, top change, busiest member), and the topic table with an Owner column and one quote per topic; no app-wide "did not fit" section (that is the overview's). The **member report** is a working page: no tiles; the period and their topics; a topic table; then per topic the description, change, counts this period, the period before and usual, app versions, trend, up to 5 quotes (clearest first), and every review of the period in full behind an expand. Amends D20 | A lead reads across people; a member reads their reviews. Pages that look alike teach readers to skip one of them |
| D21 | **Email delivery.** After publishing, each member gets an email with a link to their own report, and each team's mailing list gets a link to its team page. Mail goes through an SMTP relay; its address and credentials come from the environment or `.env`, like the Confluence token (R22). Supersedes D9's delivery by @mentions and Slack | People act on what reaches them; a page nobody is told about is not read. A link keeps the email short and keeps one copy of the report |
| D22 | **Containerized and scheduled.** The whole application runs in containers: the app, the local model server (Ollama, with the model in a volume), and a scheduler that triggers a run periodically (fetch the newest reviews, match, report, publish, email). Default cadence weekly (D9). Supersedes the "no scheduler daemon" non-goal (N01) and Project.md §7's documented-recipes-only approach | Collection must run without anyone starting it. The image built 2026-09-29 predates the issue stage and holds no model, so it cannot run the current pipeline locally |

**What this does to validation.** Matching reviews to a fixed list is a
different task from forming issues, and the embedding-route pass bar
(handoff-2026-10-18.md: precision and recall per formed cluster, tone clusters,
grab-bags) was written for forming them. Its results do not measure matching.
A matching check needs reviews labelled against the topic list, ideally by a
team analyst (the independent check the handoff has asked for since round 5),
scored per topic.

**Open (2026-10-22):**
- **The matching method.** Decided 2026-11-02 (Kevin): no model call per
  review if it can be avoided. Settled the same day by trials
  (trials/topic-trials.md, rounds 1–6 and T2):
  - A classifier trained on model-written example complaints per topic takes
    the clear units.
  - Units with weak correlation (best topic below 0.6) go to a misc bin by a
    fixed rule. Misc is not a topic, and reports show it only as a count.
  - The local model decides the rest, one unit per call. About a third of
    units reach it.
  - Results: held-out precision 78%, recall 65%, false alarm 12%.
  - Build plan: docs/production-plan.md.
- **Development matrix.** Decided 2026-11-02: the real `matrix.yaml` never
  enters this repo or its sessions. Development and demos use
  `matrix.sample.yaml`, which is a complete mock in the real format.
- **Where the member report lives.** Confirmed 2026-11-02 (Kevin): a
  Confluence page under its team page, in the D20 template.
- The overview page and the analyst's all-topics view. Decided 2026-11-02
  (Kevin): both are revised to fit D18–D20, but only after the pipeline works
  end to end. Until then they stay as they are.
- Email delivery (D21). Deferred 2026-11-02 (Kevin): how the integration will
  work is still being researched. The relay, sender, mailing lists and quotes
  in email are settled then.
- Topic descriptions are reviewed by Kevin (2026-11-02).
- Where the containers run. Decided 2026-11-02 (Kevin): a portable container
  solution, deployable on corporate clouds with in-house model servers and
  in-house run environments. One image runs one cycle (`pv cycle`) and exits.
  The host's scheduler starts it, and compose with a cron container is only the
  local default. This amends D22's "a scheduler container". The plan is in
  docs/production-plan.md §0. Decided 2026-11-02 (Kevin): no production host
  is targeted or tested yet. The image stays containerized and environment
  agnostic.
- Who maintains the real matrix as teams and features change. Decided
  2026-11-02 (Kevin): Kevin adds the real matrix at deployment. Development
  stays on `matrix.sample.yaml`.
