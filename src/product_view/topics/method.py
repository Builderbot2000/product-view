"""Matching units to the fixed topics: method M (trials/topic-trials.md, round 6).

1. The model writes about 12 example complaints per topic from its name and
   description, plus complaints that name no feature (null) and complaints
   about features not on the list (off-list). Answers are cached, so they are
   written again only when the matrix's topics change.
2. One-vs-rest logistic regression per topic on the examples' embeddings,
   negatives being null, off-list and the other topics' examples. Units the
   first fit puts at 0.9 or above join the training set (self-training), and
   the classifiers are fitted again.
3. A gate on each unit's best and second-best topic probability, p1 and p2:
   - p1 >= 0.8 and p2 < 0.5: the best topic, no model call ("sure");
   - p1 < 0.6: no topic, no model call ("misc");
   - otherwise the model picks among up to 5 candidate topics, one unit per
     call, reading the whole review for context ("model").
4. A review has a topic if any of its units has it.

Validated: development sample precision 84%, recall 67%, false alarm 13%;
held-out sample 78%, 65%, 12%. Every constant below belongs to that result:
change one and the method has to pass the check again.
"""

from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from ..llm import LLM, arr, obj
from ..matrix import Topic

INSTRUCTION = ("Given a sentence from a mobile banking app review, identify the app feature "
               "it complains about")
N_EXAMPLES = 12
SELF_TRAIN = 0.9
SURE, SECOND = 0.8, 0.5
MISC_BELOW = 0.6
OPTION_P, MAX_OPTIONS, CONTEXT = 0.3, 5, 400
NULL, OFFLIST = "_null", "_offlist"

EXPAND = """You help a product team sort reviews of their mobile banking app by app feature.

Feature: {name}
What it covers: {description}

Other features on the list, which are NOT this one: {siblings}

Write {n} short complaints, one per line, that a user might post in an app store review about this feature and no other on the list. Vary the wording, length and tone the way real reviews do (some angry, some plain, some with typos); describe problems, missing options and annoyances. Write only the complaints, no numbering."""

EXPAND_NULL = """You help a product team sort reviews of their mobile banking app by app feature.

Write {n} short complaints, one per line, that a user might post in an app store review WITHOUT naming any feature of the app: general anger, the app or bank being bad, leaving for another bank, "it doesn't work", sarcasm, demands to fix it. Vary the wording, length and tone the way real reviews do. Write only the complaints, no numbering."""

EXPAND_OFFLIST = """You help a product team sort reviews of their mobile banking app by app feature.

The team's feature list is: {names}

Write {n} short complaints, one per line, that a user might post in an app store review about a feature or part of a banking app or bank that is NOT on this list. Cover many different features. Vary the wording, length and tone the way real reviews do. Write only the complaints, no numbering."""

PROMPT = """You sort complaints from app store reviews of a mobile banking app by app feature.

For each item below you get one sentence from a review (SENTENCE), the whole review for \
context (REVIEW), and a short list of candidate features (OPTIONS). Say which of the options \
the SENTENCE itself complains about. Choose several only if the sentence clearly complains \
about each; choose none if it is general opinion, praise, or about something not in its \
options. Use the review only to understand what the sentence refers to.

{items}

Answer with one entry per item, using the item numbers and the option ids."""

ITEM = """ITEM {n}
SENTENCE: {sentence}
REVIEW: {review}
OPTIONS:
{options}"""

SCHEMA = obj({"answers": arr(obj({"item": {"type": "integer"},
                                  "topics": arr({"type": "string"})}))})


def _lines(text: str) -> list[str]:
    out = []
    for line in text.splitlines():
        line = line.strip().lstrip("-*•0123456789.) ").strip().strip('"')
        if len(line) >= 8:
            out.append(line)
    return out


def examples(topics: dict[str, Topic], llm: LLM) -> dict[str, list[str]]:
    """Example complaints per topic id, plus NULL and OFFLIST: one call each."""
    names = {t: topics[t].name for t in topics}
    prompts = {t: EXPAND.format(name=names[t], description=topics[t].description, n=N_EXAMPLES,
                                siblings="; ".join(n for x, n in names.items() if x != t))
               for t in topics}
    prompts[NULL] = EXPAND_NULL.format(n=N_EXAMPLES)
    prompts[OFFLIST] = EXPAND_OFFLIST.format(n=2 * N_EXAMPLES, names="; ".join(names.values()))
    out = {t: _lines(llm.complete(p)) for t, p in prompts.items()}
    empty = [t for t, ex in out.items() if not ex]
    if empty:
        raise ValueError(f"the model wrote no usable examples for: {', '.join(empty)}")
    return out


def probabilities(U: np.ndarray, sets: list[np.ndarray], negatives: np.ndarray) -> np.ndarray:
    """(units, topics) probability of each topic, one-vs-rest, with self-training."""
    from sklearn.linear_model import LogisticRegression

    X = np.vstack([*sets, negatives])
    y = np.concatenate([np.full(len(E), t) for t, E in enumerate(sets)]
                       + [np.full(len(negatives), -1)])
    Y = np.stack([y == t for t in range(len(sets))], axis=1)

    def fit_predict(X, Y):
        P = np.zeros((len(U), Y.shape[1]))
        for t in range(Y.shape[1]):
            clf = LogisticRegression(C=1.0, class_weight="balanced", max_iter=2000).fit(X, Y[:, t])
            P[:, t] = clf.predict_proba(U)[:, 1]
        return P

    P = fit_predict(X, Y)
    sure = P >= SELF_TRAIN
    keep = sure.any(axis=1)
    return fit_predict(np.vstack([X, U[keep]]), np.vstack([Y, sure[keep]]))


@dataclass
class Routed:
    """Per unit: route (sure | model | misc), p1 and best topic index; the
    matches as (unit index, topic index, how)."""
    route: list[str]
    p1: np.ndarray
    best: np.ndarray
    matches: list[tuple[int, int, str]] = field(default_factory=list)
    off_option: int = 0           # model answers outside the unit's options, ignored


def gate(P: np.ndarray) -> Routed:
    s = np.sort(P, axis=1)
    p1, p2 = s[:, -1], s[:, -2] if P.shape[1] > 1 else np.zeros(len(P))
    route = np.where(p1 < MISC_BELOW, "misc",
                     np.where((p1 >= SURE) & (p2 < SECOND), "sure", "model")).tolist()
    r = Routed(route, p1, P.argmax(axis=1))
    r.matches = [(i, int(r.best[i]), "sure") for i, x in enumerate(route) if x == "sure"]
    return r


def options(P: np.ndarray, i: int) -> list[int]:
    order = [int(t) for t in np.argsort(-P[i]) if P[i, t] >= OPTION_P][:MAX_OPTIONS]
    return order or [int(P[i].argmax())]


def ask(llm: LLM, P: np.ndarray, r: Routed, topics: list[Topic], texts: list[str],
        reviews: list[str], label: str = "") -> None:
    """The model decides every unit routed to it; adds its matches to `r`."""
    todo = [i for i, x in enumerate(r.route) if x == "model"]
    opts = {i: options(P, i) for i in todo}

    def prompt(i: int) -> str:
        lines = "\n".join(f"- {topics[t].id}: {topics[t].name} ({topics[t].description})"
                          for t in opts[i])
        review = " ".join(reviews[i].split())
        item = ITEM.format(n=1, sentence=" ".join(texts[i].split()), options=lines,
                           review=review[:CONTEXT] + ("…" if len(review) > CONTEXT else ""))
        return PROMPT.format(items=item)

    answers = llm.map(lambda i: llm.chat("", prompt(i), SCHEMA), todo, label=label, every=50)
    for i, out in zip(todo, answers):
        allowed = {topics[t].id: t for t in opts[i]}
        got = next((a["topics"] for a in out["answers"] if a["item"] == 1), [])
        for tid in dict.fromkeys(got):
            if tid in allowed:
                r.matches.append((i, allowed[tid], "model"))
            elif tid != "none":
                r.off_option += 1
