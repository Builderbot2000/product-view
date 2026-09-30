"""French to English translation, MarianMT, cached in SQLite forever.

A dedicated bilingual model rather than a many-to-many one: at fr->en it is
materially better, and the corpus is 94% English with nearly all the remainder
French, so a multilingual embedder would pay a capacity tax across 50
languages to serve ~1,000 reviews.

**The honest cost:** French reviews pass through two lossy steps instead of
one, and MT errors land on exactly the domain vocabulary that defines a pain
point ("virement Interac"). Callers keep the original `content` beside
`content_en` so a translated quote can always be shown as such.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from typing import Callable, Iterator, Sequence

MODEL_NAME = "Helsinki-NLP/opus-mt-fr-en"
BATCH_SIZE = 32
# Longest review in the corpus is 1,198 chars (~350 tokens) and p99 is 507.
# Capping generation bounds the worst case; beam search runs every hypothesis
# to this limit when a sequence never emits EOS.
MAX_TOKENS = 256

log = logging.getLogger(__name__)


def cache_dir() -> str:
    """Model cache under the platform's own location, not a hardcoded ~/.cache."""
    from platformdirs import user_cache_dir

    return user_cache_dir("product-view", "product-view")


@lru_cache(maxsize=1)
def _model():
    """Load tokenizer + model once. ~301 MB on first call, then cached on disk."""
    from transformers import MarianMTModel, MarianTokenizer

    log.info("loading %s (first run downloads ~301 MB)", MODEL_NAME)
    tok = MarianTokenizer.from_pretrained(MODEL_NAME, cache_dir=cache_dir())
    model = MarianMTModel.from_pretrained(MODEL_NAME, cache_dir=cache_dir())
    model.eval()
    # The shipped config sets max_length=512. Leaving it while also passing
    # max_new_tokens makes transformers warn once per batch about the conflict;
    # setting the budget here states it once instead.
    model.generation_config.max_length = None
    model.generation_config.max_new_tokens = MAX_TOKENS
    return tok, model


def translate_batches(
    texts: Sequence[str],
    batch_size: int = BATCH_SIZE,
) -> Iterator[tuple[list[int], list[str]]]:
    """Yield `(original_indices, translations)` as each batch completes.

    A generator rather than one list so the caller can persist progress as it
    arrives. The model default is 4-way beam search, which on CPU runs to tens
    of minutes at corpus scale; buffering all of it would mean an interrupted
    run saves nothing -- the same reason the ingest stage flushes per record.

    **Batches are length-bucketed.** Every sequence in a batch is padded to the
    longest one and beam search then runs all of them for that many steps, so a
    random batch makes a two-word review cost as much as the longest review it
    happens to sit beside. Sorting by length first means short reviews finish
    in a few steps. Indices are yielded back because that sort reorders the
    input.
    """
    if not texts:
        return
    import torch

    tok, model = _model()
    order = sorted(range(len(texts)), key=lambda i: len(texts[i]))
    for i in range(0, len(order), batch_size):
        indices = order[i : i + batch_size]
        batch = [texts[j] for j in indices]
        encoded = tok(
            batch, return_tensors="pt", padding=True,
            truncation=True, max_length=MAX_TOKENS,
        )
        with torch.no_grad():
            generated = model.generate(**encoded)
        yield indices, tok.batch_decode(generated, skip_special_tokens=True)


def translate(
    texts: Sequence[str],
    on_progress: Callable[[int, int], None] | None = None,
) -> list[str]:
    """Translate French texts to English, in order."""
    out: list[str] = [""] * len(texts)
    done = 0
    for indices, batch in translate_batches(texts):
        for idx, english in zip(indices, batch):
            out[idx] = english
        done += len(batch)
        if on_progress:
            on_progress(done, len(texts))
    return out
