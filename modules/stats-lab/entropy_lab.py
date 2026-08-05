"""Entropy, cross-entropy, KL and perplexity: what each one can and cannot see.

    python entropy_lab.py

Map row (Layer 2): "Explain what perplexity does and does not tell you about
quality."

That row carries no project pull on the map, and it acquired one from the far
end of the stack. `drift-and-degradation.md` found that no gold-free signal saw
a 12-point collapse in record accuracy, and the signals people reach for next
are exactly these four. So the question here is not what perplexity is; it is
which of the four measures something a production panel could act on.

Four sections:

  1. Perplexity of a real character-level model over the Chinese corpus in
     `../zh-retrieval-lab/`, and what happens to the number when the unit
     changes. Real text, real counts, real arithmetic.
  2. What perplexity is actually dominated by, and why an unsmoothed model has
     no perplexity at all.
  3. Predictive entropy as an error detector, against the confidence token the
     extractor emits. This is the one with a decision attached.
  4. KL divergence as a gold-free drift alarm: what it catches, and the
     question it cannot answer.

Seventeen documents is a language-model fixture in the same sense that twelve
records is an eval set: enough to compute the quantity and see its shape, not
enough to be a measurement of Chinese.
"""
from __future__ import annotations

import math
import os
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "zh-retrieval-lab"))

from analyzers import bigram, dictmatch, unigram  # noqa: E402
from corpus import DOCS                           # noqa: E402

from models import fit_naive_bayes                # noqa: E402
from population import EVENT_TYPES, MIX_SHIFT_DAY, RECORDS  # noqa: E402

PREDICTIONS = {
    "A": "Perplexity is a property of the model and the text, so two models "
         "evaluated on the same documents can be compared by it.",
    "B": "Smoothing is an implementation detail: it shifts perplexity a "
         "little, and does not change what the number means.",
    "C": "A model's own confidence and the entropy of its predictive "
         "distribution carry about the same information about correctness.",
    "D": "A KL divergence alarm on the input distribution is a quality alarm.",
}

doc_ids = sorted(DOCS)
HELD_OUT = doc_ids[-4:]
TRAIN_DOCS = doc_ids[:-4]

print("=" * 76)
print("1. The same model, the same text, three units")
print("=" * 76)
print(f"train on {len(TRAIN_DOCS)} documents, held out {len(HELD_OUT)}: "
      f"{', '.join(HELD_OUT)}")
print()


def unigram_lm(tokens_by_doc, alpha=1.0):
    counts = Counter(t for ts in tokens_by_doc for t in ts)
    total = sum(counts.values())
    vocab = len(counts)

    def logp(t):
        return math.log((counts[t] + alpha) / (total + alpha * (vocab + 1)))
    return logp, vocab, total


def cross_entropy(logp, tokens):
    """Mean negative log2 probability per token."""
    return -sum(logp(t) for t in tokens) / len(tokens) / math.log(2)


print(f"{'analyzer':<12}{'train tokens':>14}{'vocab':>8}"
      f"{'held-out tokens':>17}{'bits/token':>12}{'perplexity':>12}"
      f"{'ppl per char':>14}")
n_chars = sum(len([c for c in DOCS[d] if c.strip()]) for d in HELD_OUT)
for name, analyze in (("unigram", unigram), ("bigram", bigram),
                      ("dictmatch", dictmatch)):
    logp, vocab, total = unigram_lm([analyze(DOCS[d]) for d in TRAIN_DOCS])
    held = [t for d in HELD_OUT for t in analyze(DOCS[d])]
    bits = cross_entropy(logp, held)
    ppl = 2 ** bits
    # Renormalise to a per-character basis: total bits over the same text,
    # divided by the number of characters in it.
    ppl_char = 2 ** (bits * len(held) / n_chars)
    print(f"{name:<12}{total:>14}{vocab:>8}{len(held):>17}"
          f"{bits:>12.4f}{ppl:>12.2f}{ppl_char:>14.2f}")
print()
print(f"The held-out text is {n_chars} characters in every row. The perplexity")
print("column moves by a large factor and none of that movement is about how")
print("well the text was predicted -- it is about how many pieces the text was")
print("cut into. Only the last column compares.")

print()
print("=" * 76)
print("2. What the number is made of")
print("=" * 76)
logp, vocab, total = unigram_lm([unigram(DOCS[d]) for d in TRAIN_DOCS])
held = [t for d in HELD_OUT for t in unigram(DOCS[d])]
train_counts = Counter(x for d in TRAIN_DOCS for x in unigram(DOCS[d]))
bits = {t: -logp(t) / math.log(2) for t in set(held)}
total_bits = sum(bits[t] for t in held)
unseen = [t for t in held if train_counts[t] == 0]
unseen_bits = sum(bits[t] for t in unseen)
print(f"held-out tokens: {len(held)}   total surprisal: {total_bits:.1f} bits")
print(f"tokens never seen in training: {len(unseen)} "
      f"({len(unseen) / len(held):.1%} of the held-out text), carrying "
      f"{unseen_bits / total_bits:.1%} of the bits")
print()
print("So the headline number is mostly a report on vocabulary coverage. The")
print("model is not being scored on how well it predicts Chinese; it is being")
print("scored on how often it had never seen the character before, and that")
print("is a property of the training corpus size.")
print()
print("Unsmoothed, the same model on the same text:")
counts = Counter(x for d in TRAIN_DOCS for x in unigram(DOCS[d]))
zero = [t for t in held if counts[t] == 0]
if zero:
    print(f"  {len(zero)} held-out tokens have probability 0 -> "
          f"cross-entropy is infinite -> perplexity is infinite")
    print("  A number that is either infinite or a function of your smoothing")
    print("  constant is not a property of the model alone.")
print()
print(f"{'alpha':>8}{'bits/token':>13}{'perplexity':>13}")
for alpha in (0.01, 0.1, 1.0, 10.0):
    lp, _, _ = unigram_lm([unigram(DOCS[d]) for d in TRAIN_DOCS], alpha=alpha)
    b = cross_entropy(lp, held)
    print(f"{alpha:>8}{b:>13.4f}{2 ** b:>13.2f}")

print()
print("=" * 76)
print("3. Predictive entropy against a stated confidence")
print("=" * 76)
print("The extractor states a confidence. Naive Bayes has a real posterior")
print("over the six event types, so its entropy is a measurement rather than")
print("a token. Which one predicts its own errors?")
print()

import random  # noqa: E402

stories = sorted({r["story"] for r in RECORDS})
random.Random(11).shuffle(stories)
train_stories = set(stories[: len(stories) // 2])
TRAIN = [r for r in RECORDS if r["story"] in train_stories]
TEST = [r for r in RECORDS if r["story"] not in train_stories]


def nb_posterior(train, alpha=1.0):
    counts = {t: Counter() for t in EVENT_TYPES}
    prior = Counter()
    vocab_set = set()
    for r in train:
        prior[r["event_type"]] += 1
        counts[r["event_type"]].update(r["tokens"])
        vocab_set.update(r["tokens"])
    v = len(vocab_set) or 1
    totals = {t: sum(counts[t].values()) for t in EVENT_TYPES}

    def posterior(r):
        logs = {}
        for t in EVENT_TYPES:
            s = math.log((prior[t] + alpha) / (len(train) + alpha * len(EVENT_TYPES)))
            for tok in r["tokens"]:
                s += math.log((counts[t][tok] + alpha) / (totals[t] + alpha * v))
            logs[t] = s
        hi = max(logs.values())
        ex = {t: math.exp(s - hi) for t, s in logs.items()}
        z = sum(ex.values())
        return {t: e / z for t, e in ex.items()}
    return posterior


posterior = nb_posterior(TRAIN)
nb_predict = fit_naive_bayes(TRAIN)


def entropy(dist):
    return -sum(p * math.log(p, 2) for p in dist.values() if p > 0)


def auc(scores, labels):
    pos = [s for s, l in zip(scores, labels) if l]
    neg = [s for s, l in zip(scores, labels) if not l]
    if not pos or not neg:
        return None
    return sum((p > q) + 0.5 * (p == q) for p in pos for q in neg) / (len(pos) * len(neg))


nb_correct = [nb_predict(r) == r["event_type"] for r in TEST]
nb_entropy = [entropy(posterior(r)) for r in TEST]
nb_top = [max(posterior(r).values()) for r in TEST]
ex_correct = [r["correct"] for r in TEST]
ex_conf = [r["conf"] for r in TEST]

print(f"{'signal':<40}{'system':<14}{'AUC':>8}{'accuracy':>10}")
print(f"{'stated confidence':<40}{'extractor':<14}"
      f"{auc(ex_conf, ex_correct):>8.4f}"
      f"{sum(ex_correct) / len(TEST):>10.4f}")
print(f"{'top posterior probability':<40}{'naive_bayes':<14}"
      f"{auc(nb_top, nb_correct):>8.4f}"
      f"{sum(nb_correct) / len(TEST):>10.4f}")
print(f"{'negative posterior entropy':<40}{'naive_bayes':<14}"
      f"{auc([-e for e in nb_entropy], nb_correct):>8.4f}"
      f"{sum(nb_correct) / len(TEST):>10.4f}")
print()
print("Entropy and the top probability are the same ordering only when the")
print("distribution has two outcomes. Over six they differ, and the difference")
print("is whether the remaining mass is on one rival or spread over five:")
disagree = sum(1 for i in range(len(TEST)) for j in range(i + 1, len(TEST))
               if (nb_top[i] > nb_top[j]) != (nb_entropy[i] < nb_entropy[j]))
pairs = len(TEST) * (len(TEST) - 1) // 2
print(f"  the two signals order {disagree / pairs:.1%} of record pairs "
      f"differently")
print()
print("Entropy in bands, against realised accuracy:")
print(f"{'entropy band':<22}{'n':>6}{'accuracy':>10}{'mean top p':>12}")
bands = [(0.0, 0.25), (0.25, 0.75), (0.75, 1.5), (1.5, math.log(6, 2) + 0.01)]
for lo, hi in bands:
    rows = [i for i, e in enumerate(nb_entropy) if lo <= e < hi]
    if not rows:
        continue
    acc = sum(nb_correct[i] for i in rows) / len(rows)
    tp = sum(nb_top[i] for i in rows) / len(rows)
    print(f"{f'[{lo:.2f}, {hi:.2f})':<22}{len(rows):>6}{acc:>10.4f}{tp:>12.4f}")

print()
print("=" * 76)
print("4. KL divergence as a drift alarm")
print("=" * 76)
early = [r for r in RECORDS if r["day"] < MIX_SHIFT_DAY]
late = [r for r in RECORDS if r["day"] >= MIX_SHIFT_DAY]


def token_dist(records, alpha=0.5):
    c = Counter(t for r in records for t in r["tokens"])
    vocab_all = {t for r in RECORDS for t in r["tokens"]}
    total = sum(c.values()) + alpha * len(vocab_all)
    return {t: (c[t] + alpha) / total for t in vocab_all}


def kl(p, q):
    return sum(p[t] * math.log(p[t] / q[t], 2) for t in p if p[t] > 0)


def js(p, q):
    m = {t: 0.5 * (p[t] + q[t]) for t in p}
    return 0.5 * kl(p, m) + 0.5 * kl(q, m)


p_early, p_late = token_dist(early), token_dist(late)
print(f"input token distribution, early vs late:")
print(f"  KL(late || early)          {kl(p_late, p_early):.4f} bits")
print(f"  KL(early || late)          {kl(p_early, p_late):.4f} bits   "
      f"(not symmetric -- it is not a distance)")
print(f"  Jensen-Shannon             {js(p_early, p_late):.4f} bits")
print()
print("A null: split the SAME period in half at random and measure again.")
rng = random.Random(31)
nulls = []
for _ in range(30):
    rows = list(RECORDS)
    rng.shuffle(rows)
    nulls.append(js(token_dist(rows[:300]), token_dist(rows[300:])))
nulls.sort()
print(f"  null JS over 30 random halves: median {nulls[15]:.4f}, "
      f"max {nulls[-1]:.4f}")
print(f"  observed early/late JS: {js(p_early, p_late):.4f}  -> "
      f"{'above' if js(p_early, p_late) > nulls[-1] else 'INSIDE'} the null range")
print()
ea = sum(r["correct"] for r in early) / len(early)
la = sum(r["correct"] for r in late) / len(late)
print(f"So the alarm fires. What it does not say:")
print(f"  accuracy early {ea:.4f}, late {la:.4f}   change {la - ea:+.4f}")
print("  and leakage_lab.py section 4 established that this change is entirely")
print("  the class mix -- per-class accuracy is stationary by construction.")
print()
print("KL measured that the input moved. It cannot say whether quality moved,")
print("in which direction, or whether anything needs doing. It is a change")
print("detector attached to a question about change, which is the one honest")
print("use for it: route the alarm to a labelled eval run, never to a decision.")

print()
print("=" * 76)
print("Predictions")
print("=" * 76)
for k, v in PREDICTIONS.items():
    print(f"  {k}: {v}")
