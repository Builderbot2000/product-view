"""Vague units: complaints that say how the reviewer feels, not what went wrong.

"It is frustrating", "worst app ever", "please fix" carry no feature, failure
or device, yet embed close to one another and to anything said angrily. Left in
the clustering they become the hubs the specific complaints get pulled toward
(a unit like "can't log in, this app is garbage" averages toward "garbage").
So they are set aside before clustering and reported as one bucket.

Two signals, because neither is enough alone. A closed word list (stopwords,
sentiment, words every banking-app review uses) is app-independent but cannot
cover the long tail of ways to say "awful". Similarity to anchor sentiment
phrases covers the tail but also scores "every time I open the app it crashes"
high. A unit is vague when it has no content word at all, or when it is close
to an anchor *and* has at most `MAX_CONTENT_WORDS` of them.
"""

from __future__ import annotations

import re

import numpy as np
from sklearn.feature_extraction.text import ENGLISH_STOP_WORDS

BUCKET_TITLES = {
    "negative": "General dissatisfaction (no specific complaint)",
    "positive": "General praise (nothing specific)",
}
BUCKET_TITLE = BUCKET_TITLES["negative"]

_TOKEN = re.compile(r"[a-z]+(?:'[a-z]+)?")

# Sentiment, intensity and request filler.
_SENTIMENT = """
terrible horrible awful bad worst worse worse poor pathetic useless garbage trash
rubbish crap sucks suck sucked stupid ridiculous annoying annoyed frustrating
frustrated frustration disappointing disappointed disappointment unacceptable
disgusting joke waste hate hated horrendous lousy dreadful atrocious lame
rating star stars review reviews rate rated zero give gave
great good nice love loved amazing excellent fine okay ok alright decent
please fix fixed fixing need needs needed want wanted should must
really very extremely quite pretty absolutely totally completely seriously
literally honestly actually basically definitely unfortunately sadly
again still always never ever anymore lately recently finally already
bit lot little much many ton tons more most less least
thing things stuff something anything nothing everything someone anyone
people guys folks everyone everybody
"""

# Words that name the product or relationship without naming a problem.
_DOMAIN_GENERIC = """
app apps application bank banks banking mobile phone version
rbc royal canada canadian customer customers client clients service
company experience user users use using used
switch switching switched change changing changed leave leaving left
close closing closed move moving moved
work works working worked wrong problem problems issue issues
try tried trying say says said tell tells told think thought know knew
get gets got getting make makes made go goes going went come comes came
look looks looked like feel feels felt seem seems seemed
time times day days week weeks month months year years
one two three
"""

GENERIC_WORDS: frozenset[str] = frozenset(
    set(ENGLISH_STOP_WORDS) | set(_SENTIMENT.split()) | set(_DOMAIN_GENERIC.split())
)


def _content_words(text: str) -> list[str]:
    words = []
    for tok in _TOKEN.findall(text.lower()):
        # "don't" / "isn't": the negation is a stopword, the stem is not
        # content either way.
        if tok in GENERIC_WORDS or tok.split("'")[0] in GENERIC_WORDS:
            continue
        words.append(tok)
    return words


ANCHORS = [
    "This app is terrible", "It is frustrating", "Worst app ever",
    "Please fix this", "It needs to be fixed", "I am switching banks over this",
    "This app sucks", "It does not work", "The app has problems",
    "What the hell", "This is a nightmare", "I hate this app",
    "Very disappointed", "Useless app", "Garbage", "I would give zero stars",
    "Customer service is no help", "Not happy with this", "Terrible experience",
    "Fix your app", "Doesn't work properly", "Absolutely ridiculous",
]
ANCHOR_SIMILARITY = 0.7
MAX_CONTENT_WORDS = 2


def vague_mask(texts: list[str], vectors: np.ndarray, encode_fn) -> np.ndarray:
    """Boolean mask over units: True where the unit names nothing specific.

    `encode_fn(list[str]) -> L2-normalized vectors` is the encoder, passed in so
    this module stays importable without loading the model.
    """
    if not len(texts):
        return np.zeros(0, dtype=bool)
    anchors = np.asarray(encode_fn(ANCHORS), dtype=np.float32)
    near = (vectors @ anchors.T).max(axis=1) >= ANCHOR_SIMILARITY
    n_content = np.array([len(_content_words(t)) for t in texts])
    return (n_content == 0) | (near & (n_content <= MAX_CONTENT_WORDS))
