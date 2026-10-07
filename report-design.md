# Report design: decisions and plan

Design decisions for stage (F) `pv report`, made 2026-10-03. Read with
[Project.md](Project.md): §0 "Still open" has the Confluence probe results, and
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
  - LLM: only a company-approved internal model.
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
| D5 | **Shared sections:** sections are built once, wrapped in named `excerpt`, and reused on role pages with `excerpt-include` | One source for every view, and analysts can reuse the same sections in their own pages. `excerpt` is confirmed; `excerpt-include` across pages is **not yet tested** |
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

## 3. Confluence building blocks (all confirmed by probe 2)

Probe 2 source: [spike/build_confluence_probe_native.py](spike/build_confluence_probe_native.py).
Live page: MFS / "PV probe 2: native macros" (page 294964).

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
- **Heatmap (hub):** issues by the last 12 periods on one sequential blue
  scale, this period's column outlined.
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
- "TITLE-TAG probe title" (98532): probe 1 (HTML route).
- "PV probe 2: native macros" (294964): probe 2 (storage route).
- "Product View @ RBC Mobile" (294942): **the hub page**, built by
  `pv report --publish --space MFS`. Its attachments list still holds charts
  from earlier versions (priority map, monthly sparklines); they are
  unreferenced and harmless.
- Under it, the role pages, titled by role name alone: "UI & design"
  (295149), "Sign-in & security" (295174), "Payments" (131429),
  "Engineering / QA" (65919), "Support / CX" (65956).
  Pages are matched by title, so renaming one means renaming the live page
  first, or the next publish creates a new page beside it.

Per-row SVG sparklines in table cells render well, given an explicit
`ac:width` (without one Confluence stretches them to the cell).

Still open:
- Which internal model and how to call it (API, or chat only).
- Who maintains `curation.yaml` (labels, areas, roles) as new clusters appear.
- Whether the developer account can write to the team's space.
