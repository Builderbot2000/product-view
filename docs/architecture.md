# Product View architecture

Two diagrams: the whole system, and one review's journey from Google Play to a report.

## The whole system

Each box is a component and the steps inside it, in order. Solid arrows carry data,
labelled with the store between the two; dotted arrows are calls.

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 18, "rankSpacing": 30, "padding": 8, "wrappingWidth": 250}} }%%
flowchart TB
    SCHED([Scheduler]) -.-> CYCLE
    PLAY([Google Play]) --> INGEST
    MX[/Ownership Matrix/] --> MATCH
    MX --> REPORT

    subgraph CYCLE["pv cycle"]
        direction LR
        C1["`**Take lock**
Only one cycle runs per data volume.`"] --> C2["`**Validate matrix**
A broken matrix stops the cycle before fetching.`"] --> C3["`**Run stages**
Fetch, build, translate, match and report, in order.`"] --> C4["`**Publish if all OK**
A failed step never leaves half a report.`"] --> C5["`**Exit 0 / 1 / 3**
Done, a step failed, or another cycle holds the lock.`"]
    end

    subgraph INGEST["fetch"]
        direction LR
        I1["`**Each locale**
Play splits reviews by locale, so every one is read.`"] --> I2["`**Page newest first**
200 reviews a page, a second apart.`"] --> I3["`**Stop at known IDs**
A weekly top-up ends where the archive begins.`"] --> I4["`**Append JSONL**
The raw archive, never deleted.`"]
    end

    subgraph PREP["db build"]
        direction LR
        P1["`**Rebuild reviews.db**
A fresh database from the archive on every run.`"] --> P2["`**Dedupe by review_id**
Locales overlap, so each review is kept once.`"]
    end

    subgraph LANG["translate"]
        direction LR
        L1["`**Detect language**
The review's own language, not the locale it came from.`"] --> L2["`**French → English**
A local MarianMT model; translations are cached.`"]
    end

    subgraph MATCH["match"]
        direction LR
        M1["`**1–3★ in window**
Complaints from the reporting period and the periods before it.`"] --> M2["`**Split into units**
One unit per complaint, by sentence and clause.`"] --> M3["`**Example complaints per topic**
The model writes about 12 for each topic in the matrix.`"] --> M4["`**Train classifiers**
One per topic, on embeddings of the examples.`"] --> G{p1, p2}
        G --> S["`**sure**
A clear best topic is taken as it is.`"] & D["`**model picks**
Unclear units go to the model with up to 5 candidates.`"] & X["`**misc**
A unit that fits no topic well gets none.`"]
        S & D & X --> M5["`**Store run**
Units and their topics, kept for every run.`"]
    end

    subgraph REPORT["report"]
        direction LR
        R1["`**Counts per period**
Distinct reviews per topic in each 28-day period.`"] --> R2["`**Change vs usual**
Up, down or new against the 3 periods before.`"] --> R3["`**Rank quotes**
Sure matches first, short pieces last.`"] --> R4["`**Overview, team, member pages**
One template for each level of the tree.`"]
    end

    subgraph PUB["publish"]
        direction LR
        U1["`**To storage format**
HTML and SVG charts converted for Confluence.`"] --> U2["`**Parents, then children**
Stable titles, so each run is a new page version.`"]
    end

    subgraph MODEL["llm.py · embed.py"]
        direction LR
        Q1["`**Cache lookup**
Every answer and embedding is cached by model.`"] --> Q2["`**Call model**
The chat model or the embedding model.`"] --> Q3["`**Cache answer**
A weekly run pays only for new reviews.`"]
    end

    subgraph CHECK["check-matching"]
        direction LR
        K1["`**Fixed windows t1, t2**
Two shipped samples with answer keys.`"] --> K2["`**Score vs keys**
Precision, recall and false alarms.`"] --> K3["`**Pass / fail**
Run before go-live and after any model change.`"]
    end

    CYCLE -.-> INGEST
    INGEST -->|JSONL archive| PREP -->|reviews.db| LANG -->|reviews.db| MATCH -->|topics.db| REPORT -->|out/report| PUB --> CONF([Confluence])
    MATCH -.-> MODEL
    MODEL <-.-> CDB[(cache.db)]
    MODEL -.-> LLM([Ollama / OpenAI])
    CHECK -.-> MATCH

    classDef ext fill:#e8f1fb,stroke:#3b78c4
    classDef store fill:#e9f6ee,stroke:#2f8a55
    class SCHED,PLAY,MX,LLM,CONF ext
    class CDB store
```

## One review, from Play Store to the report

Read left to right. It follows one real review, posted on Sep 17, 2026, from Google Play to the report page of the person who owns the feature it complains about. Each yellow box is one stage of the process. The boxes inside it say what that stage does and what happened to this review. Green marks the part of the review that was matched to a topic, and grey marks the part that wasn't. Each step, with its code, is in [the Q&A sheet](qa.md#one-review-from-play-store-to-the-report).

```mermaid
%%{init: {"flowchart": {"nodeSpacing": 18, "rankSpacing": 30, "padding": 8, "wrappingWidth": 250}} }%%
flowchart LR
    REV["`**A customer reviews the app**
On Sep 17, 2026, someone gives the RBC Mobile app 1 star on Google Play:
“Keeps asking to send in photos of IDs and selfies after submitting and accepting. Figure your stuff out, please.”`"]

    subgraph S1["1 · Collect the reviews"]
        direction TB
        C1["`**Download new reviews**
Once a week, the tool reads the newest reviews from Google Play: the text, star rating, date and app version.`"] --> C2["`**Keep a permanent copy**
Every review is saved exactly as it arrived and is never changed or deleted. The reviewer's name and photo are not kept.`"]
    end

    subgraph S2["2 · Prepare the text"]
        direction TB
        P1["`**Remove duplicates**
Google Play can list the same review more than once, so each review is kept once.`"] --> P2["`**Put everything in English**
French reviews are translated so all reviews can be read the same way. This one is already in English.`"] --> P3["`**Keep the complaints**
Reviews with 1 to 3 stars from the last 12 four-week periods. This review is one of 747.`"]
    end

    subgraph S3["3 · Sort into topics"]
        direction TB
        T0["`**What is a topic?**
A feature of the app that someone on the product team owns, such as “Trusted device and ID check”. The product team sets the list of topics and their owners.`"] --> T1["`**Split into separate complaints**
One review can complain about several things, so it is cut into pieces. This one becomes two.`"]
        T1 --> A0 & B0
        A0["`**Complaint 1**
“Keeps asking to send in photos of IDs and selfies after submitting and accepting”`"] --> A1["`**Scored against every topic**
A model that learned from example complaints for each topic gives every topic a score from 0 to 1 for how well it fits. “Trusted device and ID check” scores 0.83, and no other topic comes close.`"] --> A2["`**Clear fit: topic assigned**
A high score with no close second is accepted as it is.`"]
        B0["`**Complaint 2**
“Figure your stuff out, please”`"] --> B1["`**Scored against every topic**
No topic scores above 0.45.`"] --> B2["`**No fit: no topic**
It names no part of the app, so it is set aside. Borderline cases, unlike these two, are decided by an AI model.`"]
        A2 & B2 --> T2["`**Result**
The review is filed under “Trusted device and ID check”.`"]
    end

    subgraph S4["4 · Count and compare"]
        direction TB
        K1["`**Count each topic's reviews per period**
A period is 4 weeks. The latest is Aug 26 – Sep 22, and this review falls in it. A review counts once per topic.`"] --> K2["`**12 this period**
12 reviews complained about trusted devices and ID checks.`"] --> K3["`**Compare with usual**
The 3 periods before had 9, 4 and 1. Their average, 4.7, is called “usual”.`"] --> K4["`**Is the rise real?**
When 4.7 is normal, 12 or more happens by chance only about 3 times in 1,000. So the topic is marked as rising.`"] --> K5["`**Choose quotes**
Complaints with a clear fit are quoted first, so this one is among the 5 quotes shown.`"]
    end

    subgraph S5["5 · Publish"]
        direction TB
        R1["`**Priya Shah's report**
Priya owns this topic. Her page in Confluence opens with: “The one to look at first is Trusted device and ID check: 12 reviews, well above the usual 4.7.”`"] --> R2["`**Counted elsewhere too**
In the 75 complaints across the whole app this period, on the Sign-in & security team page, and in the report of Sam Gagnon, who also owns this topic.`"]
    end

    REV --> S1 --> S2 --> S3 --> S4 --> S5

    classDef ext fill:#e8f1fb,stroke:#3b78c4
    classDef fit fill:#e9f6ee,stroke:#2f8a55
    classDef none fill:#f3f3f3,stroke:#999
    classDef note fill:#fff,stroke:#bbb,stroke-dasharray:4 3
    class REV ext
    class A0,A1,A2,T2 fit
    class B0,B1,B2 none
    class T0 note
```
