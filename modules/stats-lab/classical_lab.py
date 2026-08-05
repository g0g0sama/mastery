"""The baseline classifier the model has to beat, and the metric that says so.

    python classical_lab.py

Map row (Layer 2): "A baseline classifier that your LLM approach must beat."

One task -- assign `event_type` from the document's tokens -- and five systems:
a majority-class constant, a keyword rule, multinomial naive Bayes, one-vs-rest
logistic regression, and the extractor from `population.py` standing in for the
model. All five are scored on the same story-grouped holdout.

Three things this measures that a single accuracy number cannot:

  1. accuracy against macro-F1 under a 6% class, where they disagree about
     which system is better;
  2. the learning curve -- how many labels the cheap classifier needs before it
     is competitive, which is the only honest way to price "just label some
     data" against "just call the model";
  3. where each system fails, because two systems at the same accuracy that
     fail on different classes are not the same system.

An honesty note that matters more here than in the other labs: the separability
of the task is a **declared parameter**. `population.CONTAMINATION` decides how
many of the confusable type's keywords a document also carries; set it to zero
and every classifier below scores 0.99, which is a fact about the generator and
about nothing else. So do not read "naive Bayes is within N points of the model"
off this fixture. Read the shape: it takes forty lines to find out, the answer
is not knowable in advance, and the map row exists because people skip it.

Commit to the predictions before running.
"""
from __future__ import annotations

import random
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from models import TRAINERS, evaluate
from population import EVENT_TYPES, RECORDS

PREDICTIONS = {
    "A": "A bag-of-words classifier on a few hundred labels lands far below a "
         "language model on a six-way typing task.",
    "B": "Accuracy and macro-F1 rank the five systems the same way; macro-F1 "
         "is just the stricter number.",
    "C": "The learning curve is smooth, so the value of the next fifty labels "
         "is about the same as the value of the last fifty.",
    "D": "Two systems with the same accuracy are interchangeable.",
}

COST_PER_RECORD = {"majority": 0.0, "keyword": 0.0, "naive_bayes": 0.0,
                   "logreg": 0.0, "extractor": 0.0042}

# ---------------------------------------------------------------------------
# Story-grouped split. Same split as calibration_lab.py.
# ---------------------------------------------------------------------------
stories = sorted({r["story"] for r in RECORDS})
random.Random(11).shuffle(stories)
train_stories = set(stories[: len(stories) // 2])
TRAIN = [r for r in RECORDS if r["story"] in train_stories]
TEST = [r for r in RECORDS if r["story"] not in train_stories]


def predictions_for(name, model, records):
    if name == "extractor":
        return [(r["event_type"], r["pred"]) for r in records]
    return [(r["event_type"], model(r)) for r in records]


print("=" * 74)
print("1. Five systems, one story-grouped holdout")
print("=" * 74)
print(f"train {len(TRAIN)} records / {len(train_stories)} stories, "
      f"test {len(TEST)} records / {len({r['story'] for r in TEST})} stories")
print()
models = {name: fn(TRAIN) for name, fn in TRAINERS.items()}
models["extractor"] = None
results = {name: evaluate(predictions_for(name, m, TEST))
           for name, m in models.items()}

print(f"{'system':<14}{'accuracy':>10}{'macro F1':>10}{'gap':>9}"
      f"{'$/record':>10}{'$/correct':>11}")
for name, res in results.items():
    cost = COST_PER_RECORD[name]
    per_correct = cost / res["accuracy"] if res["accuracy"] else None
    print(f"{name:<14}{res['accuracy']:>10.4f}{res['macro_f1']:>10.4f}"
          f"{res['accuracy'] - res['macro_f1']:>+9.4f}{cost:>10.4f}"
          f"{per_correct:>11.4f}")

print()
print("Ranked by accuracy: ",
      " > ".join(sorted(results, key=lambda n: -results[n]["accuracy"])))
print("Ranked by macro F1: ",
      " > ".join(sorted(results, key=lambda n: -results[n]["macro_f1"])))

print()
print("=" * 74)
print("2. Per-class F1 -- where the aggregate was hiding the disagreement")
print("=" * 74)
header = f"{'event_type':<20}{'n':>5}"
for name in results:
    header += f"{name[:10]:>12}"
print(header)
for t in EVENT_TYPES:
    n = sum(1 for r in TEST if r["event_type"] == t)
    line = f"{t:<20}{n:>5}"
    for name in results:
        line += f"{results[name]['per_class'][t][2]:>12.4f}"
    print(line)

print()
print("=" * 74)
print("3. The learning curve: what the next fifty labels are worth")
print("=" * 74)
print("Naive Bayes and logistic regression trained on n story-grouped records,")
print("scored on the same holdout. Mean of 12 draws of the training subset.")
print()
print(f"{'n train':>9}{'naive_bayes acc':>17}{'macro F1':>10}"
      f"{'logreg acc':>13}{'macro F1':>10}")
rng = random.Random(19)
train_story_list = sorted(train_stories)
for n_target in (10, 25, 50, 100, 200, len(TRAIN)):
    agg = defaultdict(list)
    for _ in range(12):
        pool = list(train_story_list)
        rng.shuffle(pool)
        subset, chosen = [], set()
        for s in pool:
            if len(subset) >= n_target:
                break
            chosen.add(s)
            subset += [r for r in TRAIN if r["story"] == s]
        subset = subset[:n_target]
        for name in ("naive_bayes", "logreg"):
            res = evaluate(predictions_for(name, TRAINERS[name](subset), TEST))
            agg[name + "_acc"].append(res["accuracy"])
            agg[name + "_macro"].append(res["macro_f1"])
    print(f"{n_target:>9}{sum(agg['naive_bayes_acc']) / 12:>17.4f}"
          f"{sum(agg['naive_bayes_macro']) / 12:>10.4f}"
          f"{sum(agg['logreg_acc']) / 12:>13.4f}"
          f"{sum(agg['logreg_macro']) / 12:>10.4f}")
print()
print(f"extractor, for reference: accuracy {results['extractor']['accuracy']:.4f}"
      f"  macro F1 {results['extractor']['macro_f1']:.4f}  (needs no labels)")

print()
print("=" * 74)
print("4. Same accuracy, different failures")
print("=" * 74)
a, b = "naive_bayes", "extractor"
pa = dict(zip((r["id"] for r in TEST), (p for _, p in predictions_for(a, models[a], TEST))))
pb = dict(zip((r["id"] for r in TEST), (p for _, p in predictions_for(b, models[b], TEST))))
both = sum(1 for r in TEST if pa[r["id"]] == r["event_type"] == pb[r["id"]])
only_a = sum(1 for r in TEST if pa[r["id"]] == r["event_type"] != pb[r["id"]])
only_b = sum(1 for r in TEST if pb[r["id"]] == r["event_type"] != pa[r["id"]])
neither = len(TEST) - both - only_a - only_b
print(f"{a} and {b} on the same {len(TEST)} records:")
print(f"  both correct          {both:>4}   ({both / len(TEST):.3f})")
print(f"  only {a:<16}{only_a:>4}   ({only_a / len(TEST):.3f})")
print(f"  only {b:<16}{only_b:>4}   ({only_b / len(TEST):.3f})")
print(f"  neither               {neither:>4}   ({neither / len(TEST):.3f})")
print(f"  agreement between the two systems: "
      f"{sum(1 for r in TEST if pa[r['id']] == pb[r['id']]) / len(TEST):.4f}")
print()
oracle = (both + only_a + only_b) / len(TEST)
print(f"  ceiling if a router always picked the right one: {oracle:.4f}")
print(f"  ceiling if they agree -> accept, disagree -> review:")
agree = [r for r in TEST if pa[r["id"]] == pb[r["id"]]]
print(f"    coverage {len(agree) / len(TEST):.4f}, precision on the agreed set "
      f"{sum(1 for r in agree if pa[r['id']] == r['event_type']) / len(agree):.4f}")

print()
print("=" * 74)
print("Predictions")
print("=" * 74)
for k, v in PREDICTIONS.items():
    print(f"  {k}: {v}")
