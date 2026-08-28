"""Headline sentiment via FinBERT.

Model choice was measured, not assumed. On 84 real GDELT semiconductor headlines
(2026-08-26):

  ProsusAI/finbert            43% pos / 35% neutral / 23% neg, mean conf 0.824
  cardiffnlp twitter-roberta  32% pos / 52% neutral / 16% neg, mean conf 0.701
  yiyanghkust/finbert-tone    fails to load - no model_type in config.json

The two working models disagree on 40% of headlines, and FinBERT is right where
it matters: "CXMT Could Threaten Samsung and SK Hynix" reads negative to it and
neutral to twitter-roberta; "AMD Stock Jumps as Earnings Reignite AI Chip Trade"
reads positive vs neutral. Twitter-roberta defaults to neutral on financial verbs
it carries no weight for, and its 52% neutral share is a direct loss of signal
variance.

FinBERT is used zero-shot. It was further-pretrained on Reuters TRC2 and
fine-tuned on Financial PhraseBank - financial news sentences, the same register
as a headline - so there is nothing obvious for a fine-tune to add. See
methodology.md.
"""

import hashlib
import re

import pandas as pd

from quant.cache import CACHE_DIR

MODEL = "ProsusAI/finbert"
MAX_LENGTH = 128
CACHE = CACHE_DIR / "sentiment_finbert.parquet"

# GDELT pre-tokenises titles, inserting spaces before punctuation:
# "Micron , SK hynix , Oracle" and "12 . 8 Gbps". FinBERT was not trained on
# that spacing, so it is undone before scoring.
_SPACED_PUNCT = re.compile(r"\s+([,.:;!?%)\]])")
_SPACED_OPEN = re.compile(r"([(\[])\s+")
_DECIMAL = re.compile(r"(\d)\s*\.\s*(\d)")


def clean_headline(text):
    """Undo GDELT's punctuation spacing."""
    t = _DECIMAL.sub(r"\1.\2", str(text))
    t = _SPACED_PUNCT.sub(r"\1", t)
    t = _SPACED_OPEN.sub(r"\1", t)
    return re.sub(r"\s+", " ", t).strip()


def _key(text):
    return hashlib.sha1(text.encode("utf-8")).hexdigest()[:16]


def _read_cache():
    """Cached scores, or an empty Series if the file is absent or unusable.

    A cache is a speed optimisation, so an unreadable one should cost time, not
    break the caller. An earlier version wrote the value column as `0` instead
    of `score`, and every read then raised KeyError deep inside the signal -
    surfacing as a dashboard crash with no hint that deleting one file fixed it.
    Rebuilding silently is the right failure mode.
    """
    empty = pd.Series(dtype="float64", name="score")
    if not CACHE.exists():
        return empty
    try:
        df = pd.read_parquet(CACHE)
        if not {"key", "score"} <= set(df.columns):
            raise ValueError(f"columns {list(df.columns)}, expected key/score")
        return df.set_index("key")["score"]
    except Exception as exc:
        print(f"sentiment cache at {CACHE} unusable ({exc}); rebuilding")
        return empty


def _pipeline():
    """The FinBERT classifier. Separate so tests can stub it.

    Import is deferred: transformers and torch are ~2.5GB and are only needed
    when a headline is not already cached.
    """
    from transformers import pipeline

    return pipeline("text-classification", model=MODEL, top_k=None,
                    truncation=True, max_length=MAX_LENGTH)


def score_headlines(titles, batch_size=32):
    """P(positive) - P(negative) per headline, in [-1, +1].

    Signed probability rather than the argmax label: a headline the model calls
    positive at 0.51 should not count the same as one it calls positive at 0.99,
    and a neutral headline lands near 0 rather than being discarded.

    Results are cached by headline hash. Scoring is the slow step, headlines
    repeat across outlets and re-runs, and the model is deterministic.
    """
    clean = [clean_headline(t) for t in titles]
    keys = [_key(c) for c in clean]

    cached = _read_cache()

    todo = sorted({k: c for k, c in zip(keys, clean) if k not in cached.index}.items())
    if todo:
        clf = _pipeline()
        texts = [c for _, c in todo]
        fresh = {}
        for i in range(0, len(texts), batch_size):
            chunk = texts[i:i + batch_size]
            for (k, _), preds in zip(todo[i:i + batch_size], clf(chunk)):
                p = {d["label"].lower(): d["score"] for d in preds}
                fresh[k] = p.get("positive", 0.0) - p.get("negative", 0.0)
        cached = pd.concat([cached, pd.Series(fresh, dtype="float64")])
        # Set the name AFTER concat, not before: concatenating a named Series
        # with an unnamed one drops the name, and reset_index() then writes the
        # value column as `0`. The write succeeds and the read-back raises
        # KeyError('score') on the next call - a bug only a second invocation
        # reveals, which is why test_score_cache_round_trips exists.
        cached.name = "score"
        cached.index.name = "key"
        CACHE_DIR.mkdir(exist_ok=True)
        cached.reset_index().to_parquet(CACHE, index=False)

    return pd.Series([cached[k] for k in keys], index=getattr(titles, "index", None),
                     dtype="float64", name="sentiment")
