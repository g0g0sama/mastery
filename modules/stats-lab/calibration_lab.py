"""Calibration and thresholds: what a confidence score is allowed to decide.

    python calibration_lab.py

Map row (Layer 2): "Pick a confidence threshold from a precision/recall curve."

The extractor states a confidence on every record. Four questions, in the order
they actually arise:

  1. Is the number a probability -- does 0.90 mean nine times in ten?
  2. How much does the answer depend on how the question was asked (bin count,
     bin scheme, sample size)?
  3. If it is not calibrated, what does fixing it change and what does it not?
  4. What threshold should the review queue use, and where does the number for
     it come from?

Section 3 contains the result that decides how to think about all of this, and
it is a theorem rather than a measurement: temperature scaling is monotone, so
it cannot reorder anything, so every ranking metric is unchanged to the last
decimal. Calibration does not make the model better at telling right from
wrong. It makes the number one you are allowed to do arithmetic with.

The split is grouped by story -- see leakage_lab.py for what a random split
would do to these numbers.

Commit to the predictions before running.
"""
from __future__ import annotations

import math
import random
import statistics
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import population
from population import EVENT_TYPES, RECORDS

PREDICTIONS = {
    "A": "ECE depends heavily on the binning choice, so the main thing to be "
         "careful about when quoting one is which estimator produced it.",
    "B": "Fitting a temperature to the confidences improves both calibration "
         "and the model's ability to separate correct from incorrect answers.",
    "C": "The confidence is overconfident by roughly the same amount "
         "everywhere, so one global correction fixes it.",
    "D": "The right threshold for an auto-accept queue is found by sweeping "
         "thresholds and taking the best one on the data you have.",
}

COST_REVIEW = 1.0     # declared: analyst time to check one record
COST_WRONG = 8.0      # declared: one wrong record shipped unreviewed

# ---------------------------------------------------------------------------
# Split by story, so no near-duplicate spans the boundary.
# ---------------------------------------------------------------------------
stories = sorted({r["story"] for r in RECORDS})
random.Random(11).shuffle(stories)
fit_stories = set(stories[: len(stories) // 2])
FIT = [r for r in RECORDS if r["story"] in fit_stories]
HOLD = [r for r in RECORDS if r["story"] not in fit_stories]


def ece_equal_width(records, bins=10, key="conf"):
    """The textbook estimator: split [0,1] into equal-width bins."""
    total, n = 0.0, len(records)
    for b in range(bins):
        lo, hi = b / bins, (b + 1) / bins
        rows = [r for r in records
                if (lo <= r[key] < hi) or (b == bins - 1 and r[key] == 1.0)]
        if not rows:
            continue
        conf = sum(r[key] for r in rows) / len(rows)
        acc = sum(r["correct"] for r in rows) / len(rows)
        total += len(rows) / n * abs(conf - acc)
    return total


def ece_equal_count(records, bins=10, key="conf"):
    """The other textbook estimator: equal numbers of samples per bin."""
    rows = sorted(records, key=lambda r: r[key])
    n, total = len(rows), 0.0
    for b in range(bins):
        chunk = rows[b * n // bins: (b + 1) * n // bins]
        if not chunk:
            continue
        conf = sum(r[key] for r in chunk) / len(chunk)
        acc = sum(r["correct"] for r in chunk) / len(chunk)
        total += len(chunk) / n * abs(conf - acc)
    return total


def auc(records, key="conf"):
    """Probability a correct record outranks an incorrect one. Ties count half."""
    pos = [r[key] for r in records if r["correct"]]
    neg = [r[key] for r in records if not r["correct"]]
    if not pos or not neg:
        return None
    wins = sum((p > q) + 0.5 * (p == q) for p in pos for q in neg)
    return wins / (len(pos) * len(neg))


def brier(records, key="conf"):
    return sum((r[key] - r["correct"]) ** 2 for r in records) / len(records)


def logit(p, eps=1e-6):
    p = min(1 - eps, max(eps, p))
    return math.log(p / (1 - p))


def apply_temperature(records, t):
    for r in records:
        r["cal"] = 1 / (1 + math.exp(-logit(r["conf"]) / t))
    return records


def nll(records, key):
    return -sum(math.log(max(1e-9, r[key] if r["correct"] else 1 - r[key]))
                for r in records) / len(records)


print("=" * 72)
print("1. Is the stated confidence a probability?")
print("=" * 72)
print(population.summary())
print()
overall_conf = sum(r["conf"] for r in RECORDS) / len(RECORDS)
overall_acc = sum(r["correct"] for r in RECORDS) / len(RECORDS)
print(f"mean stated confidence {overall_conf:.4f} against accuracy "
      f"{overall_acc:.4f}   gap {overall_conf - overall_acc:+.4f}")
print()
print("Reliability, equal-count deciles over all 600 records:")
print(f"{'bin':>4}{'n':>6}{'mean conf':>12}{'accuracy':>11}{'gap':>9}")
rows = sorted(RECORDS, key=lambda r: r["conf"])
for b in range(10):
    chunk = rows[b * len(rows) // 10: (b + 1) * len(rows) // 10]
    c = sum(r["conf"] for r in chunk) / len(chunk)
    a = sum(r["correct"] for r in chunk) / len(chunk)
    print(f"{b + 1:>4}{len(chunk):>6}{c:>12.4f}{a:>11.4f}{c - a:>+9.4f}")

print()
print("=" * 72)
print("2. The same data, four defensible estimators of the same quantity")
print("=" * 72)
print(f"{'estimator':<34}{'ECE':>10}")
for label, value in (
    ("equal-width, 10 bins", ece_equal_width(RECORDS, 10)),
    ("equal-width, 15 bins", ece_equal_width(RECORDS, 15)),
    ("equal-count, 10 bins", ece_equal_count(RECORDS, 10)),
    ("equal-count, 5 bins", ece_equal_count(RECORDS, 5)),
):
    print(f"{label:<34}{value:>10.4f}")
print(f"{'Brier score (binning-free)':<34}{brier(RECORDS):>10.4f}")

print()
print("Bootstrap on the ECE estimate, 2000 resamples, equal-width 10 bins:")
rng = random.Random(5)
sanctions = [r for r in RECORDS if r["event_type"] == "sanction"]
for label, subset in (("all records", RECORDS),
                      ("the sanction records only", sanctions)):
    draws = []
    for _ in range(2000):
        sample = [subset[rng.randrange(len(subset))] for _ in subset]
        draws.append(ece_equal_width(sample, 10))
    draws.sort()
    lo, hi = draws[50], draws[1949]
    print(f"  {label:<26}n={len(subset):>4}  point {ece_equal_width(subset, 10):.4f}"
          f"   95% [{lo:.4f}, {hi:.4f}]  half-width {(hi - lo) / 2:.4f}")

print()
print("=" * 72)
print("3. Temperature scaling: what it fixes and what it cannot touch")
print("=" * 72)
best_t, best_nll = None, float("inf")
t = 0.20
while t <= 5.0:
    apply_temperature(FIT, t)
    v = nll(FIT, "cal")
    if v < best_nll:
        best_t, best_nll = t, v
    t = round(t + 0.01, 2)
apply_temperature(RECORDS, best_t)
print(f"temperature fitted on {len(FIT)} records (grouped split): T = {best_t}")
print()
print(f"{'metric':<28}{'raw conf':>12}{'calibrated':>12}{'change':>10}")
for label, fn in (("ECE (equal-width 10)", lambda k: ece_equal_width(HOLD, 10, k)),
                  ("Brier", lambda k: brier(HOLD, k)),
                  ("negative log likelihood", lambda k: nll(HOLD, k)),
                  ("AUC", lambda k: auc(HOLD, k))):
    a, b = fn("conf"), fn("cal")
    print(f"{label:<28}{a:>12.6f}{b:>12.6f}{b - a:>+10.6f}")
print()
print("The AUC row is not a rounding coincidence. Temperature scaling is")
print("strictly monotone, so it cannot reorder two records, so every metric")
print("that depends only on the ordering is unchanged exactly.")
order_raw = [r["id"] for r in sorted(HOLD, key=lambda r: (r["conf"], r["id"]))]
order_cal = [r["id"] for r in sorted(HOLD, key=lambda r: (r["cal"], r["id"]))]
print(f"  holdout ordering identical after recalibration: {order_raw == order_cal}")

print()
print("Per-type calibration, before and after one global temperature:")
print(f"{'event_type':<20}{'n':>5}{'ECE raw':>10}{'ECE cal':>10}"
      f"{'conf-acc raw':>14}{'conf-acc cal':>14}")
for et in EVENT_TYPES:
    rows_t = [r for r in RECORDS if r["event_type"] == et]
    acc = sum(r["correct"] for r in rows_t) / len(rows_t)
    graw = sum(r["conf"] for r in rows_t) / len(rows_t) - acc
    gcal = sum(r["cal"] for r in rows_t) / len(rows_t) - acc
    print(f"{et:<20}{len(rows_t):>5}{ece_equal_width(rows_t, 10, 'conf'):>10.4f}"
          f"{ece_equal_width(rows_t, 10, 'cal'):>10.4f}{graw:>+14.4f}{gcal:>+14.4f}")

print()
print("=" * 72)
print("4. Where the threshold comes from")
print("=" * 72)
print(f"declared costs: review = {COST_REVIEW:.1f} per record, "
      f"wrong record shipped = {COST_WRONG:.1f}")
analytic = 1 - COST_REVIEW / COST_WRONG
print(f"cost-optimal rule: auto-accept when P(correct) > 1 - review/wrong "
      f"= {analytic:.4f}")
print()


def evaluate(records, key, threshold):
    """Auto-accept above the threshold; everything else goes to a human."""
    accepted = [r for r in records if r[key] > threshold]
    reviewed = len(records) - len(accepted)
    wrong = sum(1 for r in accepted if not r["correct"])
    cost = reviewed * COST_REVIEW + wrong * COST_WRONG
    precision = (len(accepted) - wrong) / len(accepted) if accepted else None
    return {
        "coverage": len(accepted) / len(records),
        "precision": precision,
        "wrong": wrong,
        "cost": cost,
        "cost_per_record": cost / len(records),
    }


def sweep(records, key):
    best, best_cost = None, float("inf")
    for i in range(5, 100):
        c = evaluate(records, key, i / 100)["cost"]
        if c < best_cost:
            best, best_cost = i / 100, c
    return best


sweep_raw = sweep(FIT, "conf")
sweep_cal = sweep(FIT, "cal")
print(f"{'rule':<44}{'threshold':>10}{'coverage':>10}{'precision':>11}"
      f"{'cost/rec':>10}")
plans = [
    ("analytic threshold on RAW confidence", "conf", analytic),
    ("analytic threshold on CALIBRATED prob", "cal", analytic),
    (f"swept on the fit split, raw", "conf", sweep_raw),
    (f"swept on the fit split, calibrated", "cal", sweep_cal),
    ("accept everything", "conf", 0.0),
    ("review everything", "conf", 1.0),
]
for label, key, th in plans:
    m = evaluate(HOLD, key, th)
    p = f"{m['precision']:.4f}" if m["precision"] is not None else "n/a"
    print(f"{label:<44}{th:>10.4f}{m['coverage']:>10.4f}{p:>11}"
          f"{m['cost_per_record']:>10.4f}")

print()
print("Threshold stability: swept on subsamples of the fit split, calibrated.")
print(f"{'n records':>10}{'median threshold':>18}{'10th-90th':>18}"
      f"{'holdout cost/rec':>18}")
rng = random.Random(7)
for n in (50, 100, 200, len(FIT)):
    picks, costs = [], []
    for _ in range(200):
        sample = [FIT[rng.randrange(len(FIT))] for _ in range(n)]
        th = sweep(sample, "cal")
        picks.append(th)
        costs.append(evaluate(HOLD, "cal", th)["cost_per_record"])
    picks.sort()
    print(f"{n:>10}{statistics.median(picks):>18.3f}"
          f"{f'{picks[19]:.2f}-{picks[179]:.2f}':>18}"
          f"{statistics.mean(costs):>18.4f}")

print()
print("=" * 72)
print("Predictions")
print("=" * 72)
for k, v in PREDICTIONS.items():
    print(f"  {k}: {v}")
