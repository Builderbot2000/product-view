# Pitch deck brief: Product View for RBC managers

Instructions for a Claude session asked to build the Product View pitch deck.
Written 2026-10-22. Read all of it before writing a slide.

## Workflow: build here, polish in PowerPoint

1. **Build (Claude Code, this repo):** the full deck, from the sources below,
   with every number checked and every slide rendered and inspected.
2. **Polish (Kevin, PowerPoint with the Claude add-in):** brand fit against the
   real template and fonts, spacing, small wording edits. The add-in can't see
   the repo, so the build has to leave everything it needs inside the deck.
3. **Commit the polished file** over the built one at the same path (LFS).

So that the polish step has something to work with:

- Build on the template's slide layouts and placeholders, not free-floating
  text boxes, so the add-in and PowerPoint's own tools can restyle them.
- Keep all text as live text. Never put text inside a picture.
- Use native PowerPoint charts for the simple data charts (the monthly trend,
  bar charts), so they can be restyled in PowerPoint. Pictures are fine for the
  report's own rendered charts and screenshots.
- Put each slide's sources in its speaker notes, so wording edits in
  PowerPoint can still be checked against them.
- End with a **polish list** in your reply: a short, paste-ready prompt for the
  add-in that lists what to check (the logo placeholder, fallback colours to
  swap for the template's, slides that came out dense, any wording you weren't
  sure of).

## The job

Make a PowerPoint deck (`.pptx`) that pitches Product View **internally, to
managers at RBC**. Use RBC branding and colours. Kevin presents it. The aim is
to get managers to back the next stage (see "The ask"), not to train them on
the tool.

- **Tool:** load the `anthropic-skills:pptx` skill and follow it. The output is
  a real `.pptx` file, because it will go through RBC's own channels.
- **Output:** `docs/deck/product-view-pitch.pptx`, committed to the repo. `*.pptx`
  is tracked by Git LFS (`.gitattributes`), so check `git lfs ls-files` lists the
  deck before pushing. Put working chart images in `out/deck/assets/`, which is
  gitignored. The deck itself carries them.
- **Length:** 10–12 main slides plus a short appendix. Plan for a 10–15 minute
  slot. Put the talk track in each slide's speaker notes.

## Read these first

Every claim on a slide must come from these files. Don't estimate or round
beyond what they say.

| File | What to take from it |
|---|---|
| [Project.md](Project.md), §0 | What's built, corpus facts, the Oct 2024 incident, settled decisions |
| [report-design.md](report-design.md) §1, §2, §5 | Who the report serves, the role pages, what the hub page shows |
| [handoff-2026-10-18.md](handoff-2026-10-18.md) | Where issue grouping stands: the pass bar, held-out results, what's left |
| [llm-trials.md](../trials/llm-trials.md), "Why" | The three faults that motivated using a language model |
| [README.md](../README.md), "Demo" | The live Confluence hub page |
| `out/report/` and `out/report-proofread/` | Rendered report pages and their SVG charts |

## Audience

The audience is **RBC managers** (Mobile division product leadership and the
managers around it). They know the RBC Mobile app and the business. They don't
know this project, and they won't read code.

- **Write slide text in their language.** Follow the project's rule for
  reader-facing copy: no tool or file names (`pv`, `curation.yaml`), no pipeline
  terms (embedding, Leiden, clustering, medoid, ILP), and no statistics terms
  (Poisson, precision/recall, held-out). Say "groups reviews by the problem they
  describe", not "clusters". Technical detail can go in the appendix, labelled
  as such.
- **Managers sponsor it; analysts use it.** The project's primary users are the
  analysts who read reviews. Product View gives them evidence to build their own
  reports. It does not replace them, and it is not a manager summary. The pitch
  has to say this plainly. Managers are being asked to back a tool for their
  teams, and "it replaces the analysts" is both untrue and the wrong message.
- **Don't name or criticise the other internal effort.** Another team is working
  on review summaries with different models. Keep the deck about what Product
  View does: depth, charts, quotes traceable to the review, change over time,
  views per role, automated publishing. Managers can draw the comparison
  themselves. If Kevin wants a direct comparison, he'll ask for it.

## Story arc (slide outline)

Treat this as the default. Merge or split slides where it reads better, but
keep the order of the argument.

1. **Title.** "Product View: what RBC Mobile users are telling us, grouped by
   issue." Subtitle: internal proposal, date, Kevin Tang.
2. **The problem.** Reviews arrive one at a time (a Slack bot posts them raw).
   Nobody can see from that feed which problems are growing, which are new, or
   how big each one is. Ground it with real scale: 21,506 Canadian text reviews
   of RBC Mobile, 2011–2026; 13,930 at 1–3 stars; 7.4% in French.
3. **Why it matters: the October 2024 incident.** 1,661 negative reviews in
   October 2024, 35 times the usual ~48 a month. This is the strongest single
   chart in the deck: monthly negative reviews with that spike. Build it from
   `data/reviews.db` (see "Charts").
4. **What Product View does.** One flow, four steps, in plain words: collect
   every public Play Store review → translate French to English → group reviews
   by the problem they describe, with the same issue keeping the same name from
   one run to the next → publish Confluence pages for each team.
5. **What the team sees.** The hub page: what changed this period, issues by
   product area, a 12-period trend for each issue, and real quotes with stars,
   date and app version. Use the rendered charts (heatmap, area chart, trend)
   and/or a screenshot of the live hub page.
6. **A view for each role.** UI & design, Sign-in & security, Payments,
   Engineering / QA, Support / CX. Each team sees only the areas it can act on.
   One example issue traced from a chart to the quotes behind it.
7. **Built for the bank's constraints.** The language model runs locally, so
   review text never leaves the machine. The input is public store data. Every
   number is a count of real reviews and every quote links back to its review;
   the model only groups and names. Publishing to Confluence is automatic.
8. **Where it stands (be honest).** It's a working proof of concept: collection,
   translation, the report and publishing are built, and the pages are live on a
   demo Confluence site. Grouping is the hard part and is still being validated.
   On fresh months it finds most issues correctly (roughly 6–7 in 10, both ways),
   but it still lumps unrelated complaints together about twice a month, and the
   bar is at most once. See "Honesty rules".
9. **Why it's worth backing.** Analysts get a richer starting point. PMs see
   their area at a glance. Engineering sees regressions by app version. Support
   sees what users are raising. Issues have stable names, so trends hold up from
   one release to the next.
10. **The ask.** See below. One slide, concrete, with owners where known.
11. **Next steps and timeline.** Only what the handoff lists. No invented dates.
12. **Appendix.** How grouping is checked (the pass bar in plain words, the
    table of held-out results), the data facts table, architecture, and the
    open questions from report-design.md §8.

## The ask

Draft it from the project's open items. **Mark the slide "DRAFT, confirm with
Kevin"** in its speaker notes, because the asks are his to set:

- **An independent check:** a team analyst labels one month of reviews, so the
  grouping is judged by someone other than its builder. This is the handoff's
  top-priority next step.
- **Approval to run an RBC-approved model** (compliance sign-off on the local
  model, or access to an internal one).
- **A pilot with the Mobile product team:** a Confluence space the tool can
  publish to, and a few analysts to use the pages for a few release cycles.
- **Later:** internal review data in place of the store scrape (collection is
  built to be swapped out).

## Honesty rules

The validation numbers are the easiest part to oversell. Don't.

- Don't say "validated", "accurate" or "production-ready". Grouping has **not
  passed** its bar on fresh data (handoff, "Where it stands").
- Report held-out results only, never development results, and say they come
  from monthly samples the builder labelled. The handoff's caveats apply: the
  answer keys were written by the agent that built the method, which is why an
  independent check is the first ask.
- The rendered report in `out/report/` (2026-10-08) comes from **the earlier
  grouping method** with hand curation. Use it to show the *page layout and
  charts*, captioned as "Report layout from the demo". Don't present its issue
  counts as results of the current method.
- Leave out 3.78 vs 2.63 (the listing's rating vs the mean of text reviews) unless
  you explain why they differ. The listing counts every rating; the corpus holds
  only reviews with text.
- If a number isn't in the files above, leave it out.

## RBC branding

- **Use the official template if there is one.** Ask Kevin whether he has the
  RBC PowerPoint template (`.potx`) or a brand guide before you start. If he
  does, build on its masters, fonts and colours, and the rest of this section
  is only a fallback.
- **Logo:** use only an official RBC logo file that Kevin supplies. Never
  redraw, trace or approximate the RBC shield or wordmark. If no file is
  supplied, leave a clearly marked logo placeholder on the master slide and say
  so when you hand the deck over.
- **Fallback palette** (check it against the brand guide when one is available):

  | Role | Colour |
  |---|---|
  | Primary (title bars, headings, key shapes) | RBC Blue `#005DAA` |
  | Accent (highlights, one emphasis per slide) | RBC Yellow `#FFD200` |
  | Deep blue (dark backgrounds, footers) | `#002D72` |
  | Body text | `#16191D` |
  | Muted text, gridlines | `#596069`, `#E3E4E1` |
  | Background | white |

  Use yellow sparingly and never as text on white, where it's illegible. Put it
  on blue or use it as a rule or marker.
- **Fonts:** the template's fonts if there is a template. Otherwise Arial, which
  is safe on every RBC machine. Don't embed web fonts.
- **Footer:** slide numbers only. No classification marking is needed.
- **Look:** clean corporate style. Plenty of white space, one idea per slide,
  a headline that states the takeaway ("October 2024: 35× the usual complaints"),
  not a topic label ("Data").

## Charts

- Load the `dataviz` skill before making any chart.
- Pull chart data from `data/reviews.db` (SQLite) with a script in the
  scratchpad. Run Python with `.venv/Scripts/python.exe -X utf8`, because the
  Windows console otherwise fails on emoji and accents. Make simple charts
  native PowerPoint charts (see "Workflow"). Fall back to a PNG at 2× only for a
  chart PowerPoint can't draw.
- For the October 2024 chart, count 1–3★ reviews of at least 20 characters per
  month, the same stream Project.md uses. The current database gives **1,663**
  for October 2024 (Project.md says 1,661 from an earlier build). Use the database
  figure on both the chart and the headline so they agree.
- Recolour charts to the brand palette. When colour carries meaning (worse /
  better), add an arrow or a word too, as the report does for colour-blind
  readers.
- The report's SVGs in `out/report/hub/` (heatmap, areas, trend, sparklines) can
  be rasterised for the "What the team sees" slides. Keep them in their own
  colours, since they show the real report.
- Live screenshots: the hub page is in README.md, "Demo". If you can't reach it,
  ask Kevin for a screenshot rather than mocking one up.

## Before handing over

- Render every slide to an image (the pptx skill has a step for this) and look
  at each one: overflowing text, clipped labels, yellow-on-white, missing
  sources.
- Check every number on every slide against the source files, and list the
  source of each in the speaker notes.
- In your reply, tell Kevin what's a placeholder (logo, the ask, any
  screenshots) and which brand values are fallbacks, not taken from a guide.
