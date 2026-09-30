"""Language and script detection.

**Play's `lang` partition does not indicate a review's language.** It selects a
store listing, not a language: the `zh` partition is 222/276 plain ASCII
English, and `fr` mixes French and English freely. So nothing can be routed by
partition — every review is detected on its own text.
"""

from __future__ import annotations

import unicodedata
from functools import lru_cache

# Scripts we cannot translate without a second ~310 MB model. Measured at 20
# reviews in the negative stream and 22 in the positive one — dropping them is
# the right trade; dropping them *silently* would not be.
NON_LATIN = (
    "ARABIC", "CYRILLIC", "CJK", "HANGUL", "DEVANAGARI", "HEBREW",
    "HIRAGANA", "KATAKANA", "THAI", "GREEK", "ARMENIAN", "GEORGIAN",
)

# Below this length langid is guessing *when it is also unsure*. "Good" comes
# back as Oromo at 0.06 and "Fix it" at 0.20; trusting those would push English
# reviews through a French model.
#
# The confidence floor has to stay low, though. At 0.95 this rule misfired
# badly: "Très bonne application" (22 chars) is detected as French at 0.83 and
# was being overridden to English, so short French reviews reached the
# dashboard untranslated -- they formed their own French-titled cluster on the
# positive stream. Measured, genuine ambiguity sits below 0.45 and correct
# short-text detections above 0.70, so 0.60 separates them cleanly.
SHORT_TEXT_CHARS = 25
SHORT_TEXT_CONFIDENCE = 0.60


@lru_cache(maxsize=1)
def _identifier():
    from py3langid.langid import MODEL_FILE, LanguageIdentifier

    # norm_probs gives a real 0-1 confidence instead of a raw log-probability,
    # which is what the short-text rule below needs to be meaningful.
    return LanguageIdentifier.from_model_file(MODEL_FILE, norm_probs=True)


def script_of(text: str) -> str:
    """The first non-Latin script found in `text`, else 'LATIN'."""
    for ch in text:
        if not ch.isalpha():
            continue
        name = unicodedata.name(ch, "")
        for script in NON_LATIN:
            if script in name:
                return script
    return "LATIN"


def detect(text: str) -> tuple[str, float]:
    """Return `(lang_code, confidence)` for one review's text."""
    text = (text or "").strip()
    if not text:
        return "und", 0.0
    lang, confidence = _identifier().classify(text)

    # Short texts are unreliable regardless of what the model reports; default
    # them to English rather than routing them into translation.
    if len(text) < SHORT_TEXT_CHARS and confidence < SHORT_TEXT_CONFIDENCE:
        return "en", float(confidence)
    return str(lang), float(confidence)


def route(text: str) -> tuple[str, float, str]:
    """Classify one review into a translation action.

    Returns `(lang, confidence, action)` where action is one of
    `passthrough` (already English), `translate` (French), or `drop`
    (non-Latin script we have no model for).
    """
    script = script_of(text or "")
    if script != "LATIN":
        return script.lower(), 1.0, "drop"
    lang, confidence = detect(text)
    if lang == "fr":
        return lang, confidence, "translate"
    return lang, confidence, "passthrough"
