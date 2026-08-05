"""The classifiers and the metrics, shared by the labs that need them.

Four systems that need no model call, and a scorer. Everything is stdlib and
everything is deterministic given a seed -- `fit_logreg` shuffles, so it takes
one.

The point of keeping these in one file is that `classical_lab.py` and
`leakage_lab.py` have to be scoring the *same* classifier for their numbers to
be comparable. Two implementations of naive Bayes that differ in their
smoothing constant are two different baselines.
"""
from __future__ import annotations

import math
import random
from collections import Counter

from population import BASE_RATES, EVENT_TYPES, KEYWORDS


def fit_majority(train):
    top = Counter(r["event_type"] for r in train).most_common(1)[0][0]
    return lambda r: top


def fit_keyword(train):
    """No training at all. The rule a person writes in ten minutes, given the
    same keyword lists the documents were generated from -- the most favourable
    possible case for a hand-written rule, and a fair upper bound on one."""
    def predict(r):
        scores = {t: sum(1 for tok in r["tokens"] if tok in KEYWORDS[t])
                  for t in EVENT_TYPES}
        best = max(scores.values())
        if best == 0:
            return max(BASE_RATES, key=BASE_RATES.get)
        # Ties broken by base rate: the honest version of "pick one".
        return max((t for t in EVENT_TYPES if scores[t] == best),
                   key=lambda t: BASE_RATES[t])
    return predict


def fit_naive_bayes(train, alpha=1.0):
    counts = {t: Counter() for t in EVENT_TYPES}
    prior = Counter()
    vocab = set()
    for r in train:
        prior[r["event_type"]] += 1
        counts[r["event_type"]].update(r["tokens"])
        vocab.update(r["tokens"])
    v = len(vocab) or 1
    totals = {t: sum(counts[t].values()) for t in EVENT_TYPES}
    logprior = {t: math.log((prior[t] + alpha)
                            / (len(train) + alpha * len(EVENT_TYPES)))
                for t in EVENT_TYPES}

    def predict(r):
        best, best_score = None, -float("inf")
        for t in EVENT_TYPES:
            s = logprior[t]
            for tok in r["tokens"]:
                s += math.log((counts[t][tok] + alpha) / (totals[t] + alpha * v))
            if s > best_score:
                best, best_score = t, s
        return best
    return predict


def fit_logreg(train, epochs=30, lr=0.20, l2=1e-4, seed=3):
    """One-vs-rest logistic regression on binary token features. Plain SGD, no
    library, because the point of the map row is that this is not a big
    commitment -- it is forty lines and an afternoon."""
    vocab = sorted({tok for r in train for tok in r["tokens"]})
    index = {tok: i for i, tok in enumerate(vocab)}
    w = {t: [0.0] * len(vocab) for t in EVENT_TYPES}
    b = {t: 0.0 for t in EVENT_TYPES}
    rng = random.Random(seed)
    order = list(train)
    for _ in range(epochs):
        rng.shuffle(order)
        for r in order:
            feats = {index[tok] for tok in r["tokens"] if tok in index}
            for t in EVENT_TYPES:
                z = b[t] + sum(w[t][i] for i in feats)
                p = 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))
                g = p - (1.0 if r["event_type"] == t else 0.0)
                b[t] -= lr * g
                for i in feats:
                    w[t][i] -= lr * (g + l2 * w[t][i])

    def predict(r):
        feats = {index[tok] for tok in r["tokens"] if tok in index}
        return max(EVENT_TYPES, key=lambda t: b[t] + sum(w[t][i] for i in feats))
    return predict


TRAINERS = {
    "majority": fit_majority,
    "keyword": fit_keyword,
    "naive_bayes": fit_naive_bayes,
    "logreg": fit_logreg,
}


def evaluate(pairs):
    """pairs: (truth, prediction). Accuracy, macro F1, and per-class P/R/F1.

    Macro averages over the six classes in EVENT_TYPES whether or not they
    appear -- a class absent from the holdout contributes 0.0, which is the
    conservative convention and the one that makes a missing class visible
    instead of silently shrinking the denominator.
    """
    tp, fp, fn = Counter(), Counter(), Counter()
    for truth, pred in pairs:
        if truth == pred:
            tp[truth] += 1
        else:
            fp[pred] += 1
            fn[truth] += 1
    per_class = {}
    for t in EVENT_TYPES:
        p = tp[t] / (tp[t] + fp[t]) if (tp[t] + fp[t]) else 0.0
        r = tp[t] / (tp[t] + fn[t]) if (tp[t] + fn[t]) else 0.0
        per_class[t] = (p, r, 2 * p * r / (p + r) if (p + r) else 0.0)
    return {
        "accuracy": sum(tp.values()) / len(pairs),
        "macro_f1": sum(v[2] for v in per_class.values()) / len(EVENT_TYPES),
        "per_class": per_class,
    }
