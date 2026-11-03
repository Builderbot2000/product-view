# Production plan: from trials to a portable, scheduled service

Written 2026-11-02, after topic matching passed its held-out test
(trials/topic-trials.md, round 6 and T2). This is the work between the trial code
and a service that a team can deploy and leave running. Decisions D18–D22 are in
report-design.md §9. This plan says how to build them.

**Status, 2026-11-03.** Steps 1, 2, 3, 5 and 7 are built: `pv matrix`,
`pv match`, `pv report` (team pages and member reports; `--hub` for the
earlier pages) and `pv cycle`. Step 4 (acceptance check) waits until a host is
chosen, step 6 (email) is deferred, step 8 has only the existing compose
file, and step 9 is not started. Choices made while building, beyond what the
plan says:
- **Period and cadence.** A cycle is meant to run weekly, but the reporting
  period stays 28 days with 3 baseline periods (`report:` in config.yaml).
  Weekly counts per topic would be mostly 0–2 and nothing could ever read as
  a change. A weekly cycle re-reports the latest 28 days.
- **Window.** Each run matches every period the reports show (12 periods of
  28 days, about 11 months), not the 4-month windows the trials used. Self-
  training sees more units as a result. Step 4 should confirm the method
  holds at that size.
- **Store.** One `units` table (every unit, with its route: sure, model or
  misc) stands in for the planned `misc` table, and runs, units and matches
  live in `data/topics.db`, kept across rebuilds. Model answers and
  embeddings are cached in `cache.db`.
- **"No topic".** Counted as complaint reviews with no topic at all, from
  units routed to misc and units the model gave no topic, so both kinds of
  gap show.
- **Overview (2026-11-03, Kevin).** One page, also the analysts' view: app
  totals and trend, what changed, every team's topics with 2 quotes each,
  and "did not fit a topic" with 10 examples. It replaces the hub in place.
  The role pages become the team pages (`report.replaces`), the hub and role
  page code and `--hub` are gone, and `curation.yaml` keeps only the areas
  `pv issues` uses.
- **Page titles.** A team page is titled with the team's name. A member
  report is titled "Name · Team", since titles must be unique in a space and
  one person can sit in two teams. Team pages go under the overview page
  (`report.overview`, default: the hub's title).
- **Descriptions.** The sample's descriptions are left as validated. The
  guidance for writing them is in the sample's header, for Kevin's review.

## 0. Target: portable across corporate clouds

Kevin, 2026-11-02: Product View ships as **a portable, containerized solution**
that can be deployed on corporate cloud environments with **in-house model servers
and in-house run environments**. So the service makes as few assumptions about its
host as possible:

| Concern | We assume | We do not assume |
|---|---|---|
| Runtime | An OCI container runtime (Docker, Podman, Kubernetes, a cloud container job service) | A particular cloud, an orchestrator, a GPU |
| Model serving | An HTTP endpoint for chat completions, which can be in-house | Ollama, a specific vendor, internet access to a model hub |
| Scheduling | Something outside the container that starts a run (cron, a Kubernetes CronJob, a cloud scheduler, Airflow, a CI runner) | That we own the scheduler |
| State | One persistent volume (or mounted directory) | A managed database |
| Secrets | Environment variables, filled from the platform's secret store | `.env` files on disk (supported for local use only) |
| Network | Outbound HTTPS to Google Play, Confluence, the SMTP relay and the model endpoint, possibly through a proxy that inspects TLS | Direct internet |

The unit of deployment is **one image that runs one cycle and exits**:
`pv cycle` fetches the newest reviews, matches them, builds the reports,
publishes and emails, then exits with a status code. The host's own scheduler
decides when it runs. The local `compose.yaml` is one such host, not the only one.

## 1. The method being productionized

Method M from round 6, unchanged (trials/topics/route.py, variant M):

1. Units: reviews split into sentence segments (MiniLM), re-joined at cosine 0.45.
2. Embed units with Qwen3-Embedding-0.6B, using the query instruction.
3. Per topic, about 12 example complaints are written once by the model from the
   topic's name and description. Null and off-list examples are written the same
   way. They are cached and regenerated only when the matrix changes.
4. One-vs-rest logistic regression on the examples, with self-training at 0.9.
5. Gate on each unit's best-topic probability p1 and second p2:
   - p1 ≥ 0.8 and p2 < 0.5: take the best topic (no model call).
   - p1 < 0.6: misc (no topic, no model call).
   - otherwise: the model picks from up to 5 candidate topics, one unit per call.
6. A review has a topic if any of its units has it. Misc is not a topic: the
   classifier and the model never see it, and reports show it only as a count.

Validated: dev sample P 84%, R 67%, false alarm 13%; held-out sample P 78%,
R 65%, false alarm 12%. About a third of units reach the model, so at about 45
units a week, a weekly run makes about 15 calls.

Known weak spot: short, plain sign-in security mentions, and complaints whose form
the topic description leaves out (app approvals read as alerts). **Topic
descriptions are part of the method.** The guidance for writing them belongs in the
matrix format notes (§2, step 1).

## 2. Work ahead, in build order

### 1. Matrix loader and format notes
- `src/product_view/matrix.py`: read `matrix.yaml` if present, else
  `matrix.sample.yaml`. The path can be overridden by `PV_MATRIX` (a mounted
  secret or config map in the cloud). Validate per D19: every member topic exists,
  every topic has an owner, ids are unique, and emails are well formed.
- A matrix hash is stored with each run. A changed hash regenerates the topic
  examples (step 3 above).
- Format notes at the top of `matrix.sample.yaml`: how to write a description
  (name the feature's common forms, such as "a code by text or call, or approving
  on another device"; one feature per topic; no overlaps with neighbours).
- The real matrix never enters the repo (D19, .gitignore).

### 2. Model access that works with any in-house server
`config.py` already has `llm.provider` and `llm.base_url`. Extend it so that one
setting points at the in-house endpoint:
- **Chat:** `provider: openai` with `base_url` covers vLLM, TGI, LiteLLM, Azure
  OpenAI and most in-house gateways, through the OpenAI-compatible
  `/v1/chat/completions`. Keep `provider: ollama` for local use. The key comes
  from `PV_LLM_API_KEY` (or `OPENAI_API_KEY`).
- **Structured answers:** ask for `response_format: json_schema` where the server
  supports it. Otherwise fall back to JSON mode plus validation and one retry.
  The trials relied on Ollama's `format` and `think: false`. Those are
  provider-specific and go behind the adapter.
- **Embeddings run in the container, not on the server.** Gate thresholds (0.45,
  0.6, 0.8) are calibrated to Qwen3-Embedding-0.6B with a fixed instruction. A
  different embedding model would silently move them. The 0.6B model runs on CPU
  (sentence-transformers). MiniLM segmentation already runs in-process the same
  way. A served embedding endpoint can be an option, but only for the same model.
- Concurrency setting (`max_workers`), timeouts and retries with backoff. A
  run fails cleanly if the endpoint stays down; it does not publish half a report.

### 3. Matching in the pipeline
- `src/product_view/topics/`: port route.py variant M (classifier, gate, model
  step, misc). No trial-only variants.
- Store: a `matches` table (review id, unit seq, topic id, how: `sure` | `model`,
  run id) and a `misc` table (review id, unit seq, run id). Raw matches are stored,
  and reports derive counts from them (store raw, let the consumer derive).
- The model-answer cache moves into `cache.db`, keyed by prompt and model name.
- `pv match` runs this step on its own, for testing.

### 4. Acceptance check for a new deployment
A new host means a new chat model, and possibly a different quantization of the
embedding model. Before go-live, and after any model change:
- Move the two answer keys (`trials/runs/topics/t1|t2/labels.txt`, now
  gitignored) into tracked fixtures. They hold review ids and labels only.
- `pv check-matching`: run the configured models on both windows, score them
  against the keys and print P / R / false alarm. Pass is the same bar: 70 / 60 / 25.
- It needs the archive for those windows. Ship a fixture extract of the 240
  drawn reviews (public app-store text) with the keys, so the check runs without
  the full archive.

### 5. Reports: team pages, member reports, misc
- Team page and member report template, per D20, starting from the role page
  layout (report-design.md §5).
- Each report shows its topics' counts against usual, trends and quotes. Misc
  appears only on the team and overview pages, as "Did not fit a topic: N
  reviews", with a few examples. This keeps gaps in the topic list visible.
- Copy follows the reader rules: no tool, pipeline or statistics terms.

### 6. Email
- After publishing, each member gets a link to their report and each team list
  gets the team page link (D21).
- SMTP relay host, port, TLS mode, sender and credentials from the environment
  (`PV_SMTP_*`). A `--dry-run` writes the emails to `out/` instead of sending.
- Open: who may receive review quotes by email (the email holds only a link and
  a one-line summary, so quotes stay on Confluence).

### 7. One cycle command
- `pv cycle`: fetch → build → match → report → publish → email, once. Email
  is deferred (§3); until it lands the cycle ends at publish.
  - Exit 0 on success, non-zero on any failure.
  - Writes a one-line summary to stdout and a run record to the store.
- **Idempotent per period:** re-running the same period republishes pages
  without sending duplicate emails (a sent-mail record per period and recipient).
- **One run at a time:** a lock file on the data volume. A second run exits
  with a clear message.
- Logs: plain lines to stdout (JSON with `PV_LOG_JSON=1`) so any platform's log
  collector picks them up.

### 8. Image and deployment
- Rebuild the image (the 2026-09-29 image predates matching):
  - Non-root user, and works with a read-only root filesystem (writes only to
    `/app/data`, `/cache`, `/tmp`).
  - Pinned dependencies.
  - CPU-only torch, as now.
- **Model weights for air-gapped hosts:** the image can be built with the
  embedding and segmentation models baked in (`--build-arg BAKE_MODELS=1`), or
  pull them at first run from a mirror (`HF_ENDPOINT` pointing at an in-house
  artifact store). The weights total about 1.3 GB (MiniLM about 90 MB, Qwen3
  embedding 0.6B about 1.2 GB). Translation (opus-mt) is not needed while
  reports are English-only (PoC scope) and leaves the image.
- **Corporate network:** honour `HTTPS_PROXY` / `NO_PROXY`, and a custom CA bundle
  (`SSL_CERT_FILE`, `REQUESTS_CA_BUNDLE`) for TLS-inspecting proxies.
- **Configuration only by environment and mounts:**
  - `config.yaml` as a mount.
  - `matrix.yaml` as a secret mount.
  - Every secret as an environment variable from the platform's store.
  - No credentials in the image.
- Deployment examples, all running the same image:
  - `compose.yaml`: local and demo. `pv` plus an optional `ollama` profile
    (model in a volume, port configurable) plus an optional scheduler profile
    (a cron container calling `pv cycle`), for hosts with no scheduler of their own.
  - `deploy/kubernetes/`: a CronJob, a PersistentVolumeClaim, a Secret and a
    ConfigMap.
  - A short note for container job services (Azure Container Apps jobs, AWS ECS
    scheduled tasks, Cloud Run jobs): the same image, the same env vars, a
    mounted volume.

### 9. Operations
- On failure, the scheduler sees a non-zero exit. Optionally, `pv cycle` emails
  an operator address (`PV_ALERT_TO`) with the error summary.
- Data retention: the review archive is kept (never deleted). Run records and
  the model cache are pruned after N periods.
- After the first month of real matches, review a sample with the topic owners
  and adjust descriptions, not thresholds.

## 3. Decisions and open questions

Decided 2026-11-02 (Kevin):
- **Chat model:** the same in-house model the method was validated on
  (qwen3.5:9b). Any later change still has to pass `pv check-matching`.
- **Run environment:** no production host is targeted or tested yet. The goal
  is an image that stays containerized and environment agnostic. In step 8,
  only `compose.yaml` is built and run. The Kubernetes and job-service examples
  wait until a host is chosen.
- **Real matrix:** Kevin adds it at deployment. Until then everything runs on
  `matrix.sample.yaml`.
- **Order of work:** get the pipeline working end to end (steps 1–7) first.
  Revising the overview page for the new requirements comes later.

- **Email (step 6):** deferred. How the integration will work is still being
  researched, so `pv cycle` ends at publishing for now. The SMTP relay, sender,
  mailing lists and whether quotes appear in email are settled with it.
- **Topic descriptions:** Kevin reviews them.
- **Member report:** as defined in D20. One Confluence page per member, under
  their team page, covering only their topics, all from one template.
