# Product View

Product View reads what customers say about the RBC Mobile app in their Google
Play reviews, and tells each person on the product team what customers are
complaining about in the features they own.

Each run, it:

1. Collects the newest reviews from Google Play.
2. Translates French reviews into English.
3. Sorts every complaint (a 1, 2 or 3 star review) into the app features listed
   in the **Ownership Matrix**: the list of teams, their members, and the
   features each member owns.
4. Counts the complaints about each feature over the last four weeks, and
   compares that with the usual number to show what has risen or fallen.
5. Publishes the results as pages in Confluence.

It runs on a schedule, weekly by default, with no one needing to start it.

## What you get

Three kinds of Confluence pages:

- **The overview**: every team and feature on one page, for analysts and
  anyone who wants the whole picture.
- **A page per team**: the team's features, who owns each, and what changed.
- **A report per team member**: only the features that person owns, with what
  customers said in their own words.

For each feature, a page shows the number of complaints in the last four
weeks, the usual number, whether it went up or down, a trend over the last 12
four-week periods, and quotes from the reviews.

## See it

These demo pages use a sample Ownership Matrix, so the teams and people are
invented. The reviews are real. Viewing the pages needs access to the demo
Confluence site.

[Product View @ RBC Mobile](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144019) is the overview. Each team page sits
under it, and each member's report under their team page:

| Team page | Member reports |
|---|---|
| [Sign-in & security](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7013146) | [Alex Martin](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144136), [Priya Shah](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144163) |
| [Payments & transfers](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144200) | [Jordan Lee](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7111296), [Sophie Tremblay](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7078879) |
| [Accounts & settings](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7372840) | [Daniel Okafor](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7078920), [Maria Lopez](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144245) |
| [App platform (Engineering / QA)](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7078945) | [Chris Wong](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7013257), [Nadia Haddad](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7078994) |
| [Support / CX](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7013286) | [Sam Gagnon](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7079031) |

## How complaints are sorted into features

- A review often complains about more than one thing, so each review is first
  cut into separate complaints.
- For each feature in the Ownership Matrix, an AI model writes a dozen example
  complaints. A small model learns from those examples and scores how well each
  complaint fits each feature.
- A complaint that clearly fits one feature is filed under it. A complaint that
  fits none, such as "Figure your stuff out, please", is filed under no
  feature.
- Only the borderline complaints go to the AI model, which reads the whole
  review and picks from the closest few features. It can't invent features.

Checked against reviews sorted by hand: about 8 in 10 of the features it
assigns are right, and it finds about two-thirds of what a person would.

[The journey diagram](docs/architecture.md#one-review-from-play-store-to-the-report)
follows one real review through every step, to the number at the top of
[Priya Shah's report](https://kevintangcyberium.atlassian.net/wiki/spaces/MFS/pages/7144163).

## Learn more

| Document | What it covers |
|---|---|
| [Architecture](docs/architecture.md) | Two diagrams: the whole system, and one review's journey from Google Play to a report. Images: [system](docs/diagrams/system.png), [journey](docs/diagrams/journey.png) |
| [Q&A sheet](docs/qa.md) | Answers to common questions about the method, the reports and running it at RBC, each linked to the code |
| [Report design](docs/report-design.md) | Why the pages look and count the way they do |
| [Production plan](docs/production-plan.md) | What it takes to run Product View as a service |
| [Matching trials](trials/topic-trials.md) | How the sorting method was chosen and tested |
| [Sample Ownership Matrix](matrix.sample.yaml) | The format of the Ownership Matrix, and how to describe a feature well |
| [Older documents](docs/legacy/) | Earlier plans, kept for history |

## Running it

### Set up

Needs Python 3.10 or newer, on Windows, macOS or Linux.

```bash
python -m venv .venv
.venv\Scripts\activate         # Windows
source .venv/bin/activate       # macOS and Linux
pip install -e .
```

On Linux, run `pip install torch --index-url https://download.pytorch.org/whl/cpu`
first. Without it, pip installs a 2.5 GB GPU version you don't need.

The first run downloads about 1.6 GB of language models. Later runs reuse them.

### Run

```bash
pv cycle                            # the whole run: collect, translate, sort, count, publish
pv cycle --no-fetch --no-publish    # the same on the reviews already collected, pages saved to out/report
pv matrix                           # check the Ownership Matrix and list who owns what
pv check-matching                   # check sorting accuracy against the hand-sorted reviews
```

`pv cycle` runs once and exits, so a scheduler decides when it runs. If any
step fails, nothing is published. Pages are published only when a Confluence
space is set in the settings, and are otherwise saved to `out/report`. `pv --help` lists the commands for running
one step at a time.

### Settings

- **[config.yaml](config.yaml)**: the app, the AI model, the reporting period
  and the Confluence space. Each setting is explained in the file.
- **The Ownership Matrix**: `matrix.yaml`, which stays private and is never
  committed. Without it, the sample matrix is used.
- **Passwords and keys** go in environment variables or a local `.env` file,
  never in the settings file: `CONFLUENCE_BASE_URL`, `CONFLUENCE_USER` and
  `ATLASSIAN_TOKEN` for Confluence, and `PV_LLM_API_KEY` for a hosted AI model.

### The AI model

By default it uses Qwen 3.5 9B, running on the same machine through
[Ollama](https://ollama.com), so review text never leaves the machine. It can
also use RBC's in-house model server or OpenAI by changing the `llm:` setting.
Run `pv check-matching` after any model change: it passes or fails against a
fixed bar.

Every AI answer is saved, so a weekly run only pays for new reviews.

### In a container

```bash
docker compose build
docker compose run --rm pv                  # one full run
docker compose run --rm pv check-matching   # the accuracy check
```

The container runs one cycle and exits, and keeps its data in one volume. It
expects Ollama on this machine at port 11600. The [Dockerfile](Dockerfile) lists
every setting the container reads.

### Tests

```bash
python -m unittest discover -s tests
```
