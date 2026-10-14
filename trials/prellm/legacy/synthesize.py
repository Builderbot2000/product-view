"""Pain point synthesis -- fully algorithmic, no LLM.

Every word shown traces back to a real review, which also means no API key, no
cost, no review text leaving the machine, and deterministic output that does
not drift between runs.

- **Title** -- a real user's sentence: the most central *short* complaint unit
  that contains one of the cluster's distinctive keywords ("The remember me
  option does not work"), lightly tidied. Keyphrase titles ("login") told a
  PM the topic but not the complaint.
- **Keywords** -- c-TF-IDF: each cluster is one document, 1-3 grams scored
  against the other clusters, so they surface what makes *this* cluster
  distinctive rather than merely what is frequent. They anchor the title.
- **Canonical quote** -- the medoid: the complaint unit closest to the centroid.
- **Message** -- LexRank over member sentences, then MMR, so the selected
  sentences are central *and* mutually non-redundant.
- **Supporting quotes** -- MMR against the centroid. Without MMR you get five
  near-identical sentences; with it you get the range of phrasing.
"""

from __future__ import annotations

import re
from typing import Callable, Sequence

import numpy as np

SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")
MIN_SENTENCE_CHARS = 15

# LexRank needs sentence vectors, and the negative stream holds 32,785
# sentences -- 2.5x the review count. Bounding it to the most typical members
# per cluster keeps that pass cheap and improves quality, since outlying
# members contribute little to a representative summary.
LEXRANK_MAX_MEMBERS = 150

# A title is a sentence a PM reads at a glance; longer units are left to the
# message and quotes.
TITLE_MIN_WORDS = 3
TITLE_MAX_WORDS = 10

# How many of the cluster's top keywords a title may be anchored on.
TITLE_ANCHOR_KEYWORDS = 3

DAMPING = 0.85
SIM_THRESHOLD = 0.10


def split_sentences(text: str) -> list[str]:
    parts = SENTENCE_SPLIT.split(text or "")
    return [s.strip() for s in parts if len(s.strip()) >= MIN_SENTENCE_CHARS]


# --- keywords --------------------------------------------------------------

def ctfidf(
    cluster_texts: dict[int, list[str]],
    top_k: int = 8,
) -> dict[int, list[str]]:
    """Class-based TF-IDF: the n-grams most distinctive to each cluster.

    BERTopic's labelling method. `tf` is within-cluster frequency; the idf term
    `log(1 + A / f_t)` divides by the term's total frequency across all
    clusters, so words common everywhere ("app", "bank") sink.

    Keywords only. It used to supply the title as well, and a keyphrase title
    had two failures on the real corpus: it named a topic, not a complaint
    ("login"), and because titles had to be distinct, a duplicate cluster fell
    through to whatever phrase was left -- one device-compatibility cluster was
    titled "royal bank".
    """
    from sklearn.feature_extraction.text import CountVectorizer

    labels = sorted(cluster_texts)
    if not labels:
        return {}
    documents = [" ".join(cluster_texts[label]) for label in labels]

    vectorizer = CountVectorizer(
        ngram_range=(1, 3),
        stop_words="english",
        # min_df counts *documents*, and here each document is a whole cluster.
        # Anything above 1 would drop terms unique to a single cluster --
        # exactly the distinctive terms c-TF-IDF exists to surface.
        min_df=1,
        max_features=100_000,
        lowercase=True,
    )
    try:
        counts = vectorizer.fit_transform(documents).toarray().astype(np.float64)
    except ValueError:
        # Every document was stop words or empty -- no keywords are derivable,
        # but the clusters themselves are still valid output.
        return {label: [] for label in labels}
    vocab = np.array(vectorizer.get_feature_names_out())

    words_per_cluster = counts.sum(axis=1, keepdims=True)
    words_per_cluster[words_per_cluster == 0] = 1.0
    tf = counts / words_per_cluster

    freq_across = counts.sum(axis=0)
    freq_across[freq_across == 0] = 1.0
    avg_words = counts.sum() / max(len(labels), 1)
    idf = np.log1p(avg_words / freq_across)

    scores = tf * idf
    out: dict[int, list[str]] = {}
    for i, label in enumerate(labels):
        order = np.argsort(-scores[i])
        out[label] = _dedupe_ngrams(vocab[order[: top_k * 4]], top_k)
    return out


def _token_overlap(a: str, b: str) -> float:
    """Fraction of the shorter term's tokens shared with the longer one."""
    ta, tb = set(a.split()), set(b.split())
    return len(ta & tb) / min(len(ta), len(tb))


def _dedupe_ngrams(terms: Sequence[str], top_k: int, overlap: float = 0.5) -> list[str]:
    """Collapse n-grams that name the same idea, keeping the best-scoring form.

    Substring matching alone is not enough: "send transfer interac",
    "transfer interac fails" and "fails send transfer" are rotations of one
    phrase and contain none of each other, so a substring rule keeps all three
    and the keyword list becomes five spellings of a single idea. Comparing
    token overlap catches rotations and near-repeats alike.

    Terms arrive in score order, so the first spelling of an idea is the
    best-scoring one and later overlapping variants are dropped.
    """
    kept: list[str] = []
    for term in terms:
        if any(_token_overlap(term, k) >= overlap for k in kept):
            continue
        kept.append(term)
        if len(kept) >= top_k:
            break
    return kept


# --- titles ----------------------------------------------------------------

# Openers that only make sense after the sentence the split cut away:
# "However the deposit cheque feature never worked" -> "The deposit ...".
_LEADING = re.compile(
    r"^(?:(?:however|but|and|also|so|plus|now|then|well|ok|okay)\b[\s,]*"
    # Label prefixes only with their colon: "update your app" is a sentence,
    # "Update: still broken" is a label.
    r"|(?:edit|update|ps)\s*:\s*)+",
    re.I,
)
_STUTTER = re.compile(r"\b(\w+)(\s+\1\b)+", re.I)      # "this app app is"
_REPEAT_PUNCT = re.compile(r"([!?.])\1+")
_WORD = re.compile(r"[a-z0-9']+", re.I)


def tidy_title(text: str) -> str:
    """Make a unit presentable as a title without changing what it says:
    drop a dangling opener, a keyboard stutter, repeated punctuation and
    shouting. Every remaining word is still the user's."""
    t = " ".join(text.split())
    t = _LEADING.sub("", t)
    t = _STUTTER.sub(r"\1", t)
    t = _REPEAT_PUNCT.sub(r"\1", t).strip(" ,;:-")
    letters = [c for c in t if c.isalpha()]
    if letters and sum(c.isupper() for c in letters) / len(letters) > 0.7:
        t = t.lower()
    return t[:1].upper() + t[1:]


def _starts_sentence(text: str) -> bool:
    """Whether a unit begins where its writer began a sentence: a capital, or
    an opener `tidy_title` strips. A clause the split cut out of the middle of
    a sentence -- "not use a banking app" -- reads as a fragment."""
    t = text.lstrip()
    return t[:1].isupper() or bool(_LEADING.match(t))


def sentence_title(
    texts: Sequence[str],
    similarities: np.ndarray,
    keywords: Sequence[str],
    taken: set[str],
) -> str:
    """The most central short member that names one of the cluster's
    distinctive keywords.

    Centrality alone picks the vaguest member: in a cluster about the
    remember-me box, "need to be fixed" sits close to the centroid too. Anchoring
    on a top c-TF-IDF term keeps the title about what sets the cluster apart.
    Members that start a sentence are preferred over mid-sentence fragments.
    Falls back through looser pools, then to the medoid cut short, so every
    cluster gets a title; `taken` keeps two clusters from sharing one.
    """
    anchors = {
        tok for kw in keywords[:TITLE_ANCHOR_KEYWORDS] for tok in kw.lower().split()
    }
    # Pools from strictest to loosest: (anchored, starts a sentence).
    pools: dict[tuple[bool, bool], list[tuple[float, str]]] = {
        key: [] for key in ((True, True), (True, False), (False, True), (False, False))
    }
    for text, sim in zip(texts, similarities):
        title = tidy_title(text)
        words = _WORD.findall(title.lower())
        if not TITLE_MIN_WORDS <= len(words) <= TITLE_MAX_WORDS:
            continue
        if title.lower() in taken:
            continue
        anchored = bool(anchors & set(words))
        starts = _starts_sentence(text)
        for a, s in pools:
            if (anchored or not a) and (starts or not s):
                pools[(a, s)].append((float(sim), title))

    for pool in pools.values():
        if pool:
            return max(pool)[1]
    medoid_words = tidy_title(texts[int(np.argmax(similarities))]).split()
    return " ".join(medoid_words[:TITLE_MAX_WORDS]) + (
        "…" if len(medoid_words) > TITLE_MAX_WORDS else "")


# --- selection -------------------------------------------------------------

def medoid(vectors: np.ndarray, center: np.ndarray) -> int:
    """Row index of the member closest to the centroid."""
    return int(np.argmax(vectors @ center))


def mmr_select(
    vectors: np.ndarray,
    center: np.ndarray,
    k: int = 5,
    lam: float = 0.7,
) -> list[int]:
    """Maximal Marginal Relevance: central *and* mutually non-redundant."""
    n = vectors.shape[0]
    k = min(k, n)
    if k <= 0:
        return []
    relevance = vectors @ center
    selected: list[int] = [int(np.argmax(relevance))]
    while len(selected) < k:
        chosen = np.array(selected)
        # Redundancy = similarity to the nearest already-selected item.
        redundancy = np.max(vectors @ vectors[chosen].T, axis=1)
        score = lam * relevance - (1 - lam) * redundancy
        score[chosen] = -np.inf
        nxt = int(np.argmax(score))
        if not np.isfinite(score[nxt]):
            break
        selected.append(nxt)
    return selected


# --- message ---------------------------------------------------------------

def lexrank(sentence_vectors: np.ndarray) -> np.ndarray:
    """PageRank eigenvector centrality over the sentence-similarity graph."""
    n = sentence_vectors.shape[0]
    if n == 1:
        return np.ones(1)
    sim = sentence_vectors @ sentence_vectors.T
    np.fill_diagonal(sim, 0.0)
    sim[sim < SIM_THRESHOLD] = 0.0

    row_sums = sim.sum(axis=1, keepdims=True)
    # Isolated sentences would divide by zero; give them a uniform row so the
    # chain stays stochastic.
    isolated = (row_sums.ravel() == 0)
    sim[isolated] = 1.0 / n
    row_sums = sim.sum(axis=1, keepdims=True)
    transition = sim / row_sums

    scores = np.full(n, 1.0 / n)
    for _ in range(100):
        updated = (1 - DAMPING) / n + DAMPING * (transition.T @ scores)
        if np.abs(updated - scores).sum() < 1e-8:
            scores = updated
            break
        scores = updated
    return scores


def build_message(
    texts: Sequence[str],
    encode_fn: Callable[[Sequence[str]], np.ndarray],
    max_sentences: int = 3,
    lam: float = 0.7,
) -> str:
    """Assemble 2-3 central, non-redundant real sentences into a paragraph.

    Sentence vectors are transient by design -- they are never written to the
    `segments` cache, which holds the stream's own segmentation.
    """
    sentences: list[str] = []
    for text in texts:
        sentences.extend(split_sentences(text))
    if not sentences:
        return (texts[0].strip() if texts else "")
    if len(sentences) == 1:
        return sentences[0]

    vectors = encode_fn(sentences)
    centrality = lexrank(vectors)

    # Rank by centrality, then diversify with MMR over the strongest candidates.
    ranked = np.argsort(-centrality)[: max(20, max_sentences * 5)]
    candidates = vectors[ranked]
    pseudo_center = candidates.mean(axis=0)
    norm = np.linalg.norm(pseudo_center)
    if norm:
        pseudo_center = pseudo_center / norm
    picked = mmr_select(candidates, pseudo_center, k=max_sentences, lam=lam)

    # Restore the centrality order so the strongest sentence leads.
    chosen = sorted((int(ranked[p]) for p in picked), key=lambda i: -centrality[i])
    return " ".join(sentences[i] for i in chosen)
