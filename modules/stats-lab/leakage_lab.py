"""Leakage, distribution shift, and imbalance: four ways a holdout lies.

    python leakage_lab.py

Map row (Layer 2): "Find the leak in a naively split dataset."

The holdout in the cycle's evidence contract exists to answer one question --
would this change help on documents nobody has seen? Four things break that
answer, and only the first is usually called leakage:

  1. the split cuts through groups of near-duplicate documents;
  2. the labels were produced by correcting the system's own output, so they
     inherit its blind spots;
  3. the rare class has too few holdout examples to have a score at all;
  4. the holdout was drawn from a period the traffic has since left.

Section 2 answers open question 1 in `current-cycle.md` with a number, so read
that section against the sentence "how many of the 50 records can come from
existing Sinoscope output that you correct".

Magnitudes are properties of `population.py`'s declared parameters. The
directions are not: a group-correlated split cannot deflate a holdout, and a
label set produced by correction cannot be unbiased with respect to the system
that produced it.

Commit to the predictions before running.
"""
from __future__ import annotations

import random
import statistics
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import population
from models import evaluate, fit_naive_bayes
from population import EVENT_TYPES, MIX_SHIFT_DAY, RECORDS

PREDICTIONS = {
    "A": "Near-duplicate documents in a corpus of 600 are a minor effect; a "
         "random split is within a point or two of a grouped one.",
    "B": "Correcting model output is a reasonable way to build labels -- it "
         "biases the set toward what the model finds, but not the score.",
    "C": "Six hundred documents give a rare class enough holdout examples for "
         "a per-class F1 worth quoting.",
    "D": "If the aggregate accuracy falls, quality fell. If the worry is that "
         "the traffic mix moved instead, decomposing the change into a mix "
         "term and a quality term settles it.",
}


def split_random(records, seed=101):
    rows = list(records)
    random.Random(seed).shuffle(rows)
    half = len(rows) // 2
    return rows[:half], rows[half:]


def split_by_story(records, seed=101):
    stories = sorted({r["story"] for r in records})
    random.Random(seed).shuffle(stories)
    train_ids, train = set(), []
    for s in stories:
        if len(train) >= len(records) // 2:
            break
        train_ids.add(s)
        train += [r for r in records if r["story"] == s]
    return train, [r for r in records if r["story"] not in train_ids]


def split_temporal(records, day=MIX_SHIFT_DAY):
    return ([r for r in records if r["day"] < day],
            [r for r in records if r["day"] >= day])


def shared_stories(train, test):
    return len({r["story"] for r in train} & {r["story"] for r in test})


print("=" * 76)
print("1. The same classifier, the same corpus, three splits")
print("=" * 76)
print(f"{'split':<22}{'train':>7}{'test':>6}{'shared stories':>16}"
      f"{'accuracy':>10}{'macro F1':>10}")
splits = {
    "random over records": split_random(RECORDS),
    "grouped by story": split_by_story(RECORDS),
    f"temporal, day<{MIX_SHIFT_DAY}": split_temporal(RECORDS),
}
scores = {}
for label, (train, test) in splits.items():
    model = fit_naive_bayes(train)
    res = evaluate([(r["event_type"], model(r)) for r in test])
    scores[label] = res
    print(f"{label:<22}{len(train):>7}{len(test):>6}"
          f"{shared_stories(train, test):>16}"
          f"{res['accuracy']:>10.4f}{res['macro_f1']:>10.4f}")

base = scores["grouped by story"]["accuracy"]
infl = scores["random over records"]["accuracy"] - base
print()
print(f"On this one split the random arm reports {infl:+.4f} against the grouped")
print("arm -- the wrong sign. One split cannot establish the effect, which is")
print("the same lesson eval-set-sample-size.md reached from the other side.")
print()
print("Over 30 seeds:")
gaps, gaps_macro = [], []
for seed in range(200, 230):
    tr_r, te_r = split_random(RECORDS, seed)
    tr_g, te_g = split_by_story(RECORDS, seed)
    a = evaluate([(r["event_type"], fit_naive_bayes(tr_r)(r)) for r in te_r])
    b = evaluate([(r["event_type"], fit_naive_bayes(tr_g)(r)) for r in te_g])
    gaps.append(a["accuracy"] - b["accuracy"])
    gaps_macro.append(a["macro_f1"] - b["macro_f1"])
print(f"  accuracy inflation  mean {statistics.mean(gaps):+.4f}  "
      f"sd {statistics.stdev(gaps):.4f}  "
      f"min {min(gaps):+.4f}  max {max(gaps):+.4f}  "
      f"negative in {sum(1 for g in gaps if g < 0)}/30 seeds")
print(f"  macro F1 inflation  mean {statistics.mean(gaps_macro):+.4f}  "
      f"sd {statistics.stdev(gaps_macro):.4f}")
print()
print("Duplicate structure that produces it:")
sizes = Counter(Counter(r["story"] for r in RECORDS).values())
print(f"  {len({r['story'] for r in RECORDS})} stories over {len(RECORDS)} documents")
for size in sorted(sizes):
    n_docs = size * sizes[size]
    print(f"    stories of size {size}: {sizes[size]:>4}  "
          f"({n_docs:>3} documents, {n_docs / len(RECORDS):.1%} of the corpus)")
singles = sizes.get(1, 0)
print(f"  documents with at least one near-duplicate elsewhere in the corpus: "
      f"{(len(RECORDS) - singles) / len(RECORDS):.1%}")

print()
print("=" * 76)
print("2. Labels produced by correcting the extractor's own output")
print("=" * 76)
print("A labeller reviewing extractor output notices "
      f"{population.NOTICE_RATE:.0%} of its errors, and only "
      f"{population.NOTICE_RATE_CONFUSABLE:.0%} when the error is onto the")
print("confusable neighbour -- the error that reads as plausible. Both rates")
print("are declared; the consequence is not.")
print()
_, test = split_by_story(RECORDS)
train, _ = split_by_story(RECORDS)
nb = fit_naive_bayes(train)
print(f"{'system':<14}{'vs blind labels':>17}{'vs corrected labels':>21}{'gap':>9}")
for name, predict in (("extractor", lambda r: r["pred"]),
                      ("naive_bayes", nb)):
    true_acc = evaluate([(r["event_type"], predict(r)) for r in test])["accuracy"]
    corr_acc = evaluate([(r["corrected"], predict(r)) for r in test])["accuracy"]
    print(f"{name:<14}{true_acc:>17.4f}{corr_acc:>21.4f}{corr_acc - true_acc:>+9.4f}")
agree = sum(1 for r in test if r["corrected"] == r["event_type"]) / len(test)
print()
print(f"the corrected label set agrees with the truth on {agree:.4f} of records")
print(f"-- it is {1 - agree:.1%} wrong, and every one of those errors is a")
print("record where the extractor was wrong and the labeller did not notice.")
print()
print("Per-type, on the whole population:")
print(f"{'event_type':<20}{'n':>5}{'true acc':>10}{'corrected acc':>15}{'inflation':>11}")
for t in EVENT_TYPES:
    rows = [r for r in RECORDS if r["event_type"] == t]
    a = sum(r["pred"] == r["event_type"] for r in rows) / len(rows)
    b = sum(r["pred"] == r["corrected"] for r in rows) / len(rows)
    print(f"{t:<20}{len(rows):>5}{a:>10.4f}{b:>15.4f}{b - a:>+11.4f}")

print()
print("=" * 76)
print("3. Imbalance: what a rare class actually gives you")
print("=" * 76)
declared = population.BASE_RATES["sanction"]
print(f"`sanction` is declared at {declared:.0%} early and "
      f"{population.BASE_RATES_LATE['sanction']:.0%} late.")
print()
print("Realized share over 40 seeds of the same generator "
      f"({population.N_DOCS} documents each):")
shares, holdout_counts = [], []
for seed in range(300, 340):
    recs = population.build(seed)
    shares.append(sum(1 for r in recs if r["event_type"] == "sanction") / len(recs))
    _, te = split_by_story(recs, seed)
    holdout_counts.append(sum(1 for r in te if r["event_type"] == "sanction"))
shares.sort()
print(f"  share  mean {statistics.mean(shares):.4f}  "
      f"10th-90th {shares[3]:.4f}-{shares[35]:.4f}  "
      f"min {shares[0]:.4f}  max {shares[-1]:.4f}")
print(f"  holdout examples  median {statistics.median(holdout_counts):.0f}  "
      f"min {min(holdout_counts)}  max {max(holdout_counts)}  "
      f"fewer than 10 in {sum(1 for c in holdout_counts if c < 10)}/40 seeds")
print()
print("The draw is per STORY, not per document, so 600 documents are")
print(f"{statistics.mean([len({r['story'] for r in population.build(s)}) for s in range(300, 310)]):.0f}"
      " independent draws, not 600.")
print()
n_sanction = sum(1 for r in test if r["event_type"] == "sanction")
print(f"On this run's grouped holdout there are {n_sanction} sanction records.")
print("Bootstrap on that class's F1 for the extractor, 2000 resamples:")
rng = random.Random(13)
for name, predict in (("extractor", lambda r: r["pred"]), ("naive_bayes", nb)):
    draws = []
    for _ in range(2000):
        sample = [test[rng.randrange(len(test))] for _ in test]
        res = evaluate([(r["event_type"], predict(r)) for r in sample])
        draws.append(res["per_class"]["sanction"][2])
    draws.sort()
    print(f"  {name:<12} point "
          f"{evaluate([(r['event_type'], predict(r)) for r in test])['per_class']['sanction'][2]:.4f}"
          f"   95% [{draws[50]:.4f}, {draws[1949]:.4f}]"
          f"   half-width {(draws[1949] - draws[50]) / 2:.4f}")

print()
print("=" * 76)
print("4. Distribution shift: the aggregate that does not move")
print("=" * 76)
early, late = split_temporal(RECORDS)
print(f"early: {len(early)} records (day 0-{MIX_SHIFT_DAY - 1}), "
      f"late: {len(late)} records")
print()
print(f"{'slice':<22}{'early acc':>11}{'late acc':>10}{'change':>9}"
      f"{'early share':>13}{'late share':>12}")
ea = sum(r["correct"] for r in early) / len(early)
la = sum(r["correct"] for r in late) / len(late)
print(f"{'ALL (extractor)':<22}{ea:>11.4f}{la:>10.4f}{la - ea:>+9.4f}"
      f"{1.0:>13.3f}{1.0:>12.3f}")
for t in EVENT_TYPES:
    e = [r for r in early if r["event_type"] == t]
    l = [r for r in late if r["event_type"] == t]
    if not e or not l:
        continue
    a = sum(r["correct"] for r in e) / len(e)
    b = sum(r["correct"] for r in l) / len(l)
    print(f"  {t:<20}{a:>11.4f}{b:>10.4f}{b - a:>+9.4f}"
          f"{len(e) / len(early):>13.3f}{len(l) / len(late):>12.3f}")
print()
print("Recompute the late-period accuracy holding the early mix fixed --")
print("the counterfactual 'what would the number be if only quality changed':")
reweighted = sum(
    (len([r for r in early if r["event_type"] == t]) / len(early))
    * (sum(r["correct"] for r in late if r["event_type"] == t)
       / max(1, len([r for r in late if r["event_type"] == t])))
    for t in EVENT_TYPES)
print(f"  observed late accuracy       {la:.4f}")
print(f"  late accuracy at early mix   {reweighted:.4f}")
print(f"  attributed to the mix        {la - reweighted:+.4f}")
print(f"  attributed to 'quality'      {reweighted - ea:+.4f}   "
      f"of a total {la - ea:+.4f}")
print()
print("The generator contains NO quality change over time. Per-class accuracy")
print("is stationary by construction and only the mix moves. So the quality")
print("term above is entirely spurious, and the decomposition that was")
print("supposed to protect the reader produced it. Over 40 fresh populations:")
agg, per_class_deltas = [], []
for seed in range(400, 440):
    recs = population.build(seed)
    e = [r for r in recs if r["day"] < MIX_SHIFT_DAY]
    l = [r for r in recs if r["day"] >= MIX_SHIFT_DAY]
    agg.append(sum(r["correct"] for r in l) / len(l)
               - sum(r["correct"] for r in e) / len(e))
    for t in EVENT_TYPES:
        et = [r for r in e if r["event_type"] == t]
        lt = [r for r in l if r["event_type"] == t]
        if len(et) > 5 and len(lt) > 5:
            per_class_deltas.append(sum(r["correct"] for r in lt) / len(lt)
                                    - sum(r["correct"] for r in et) / len(et))
print(f"  aggregate accuracy, late - early   mean {statistics.mean(agg):+.4f}  "
      f"sd {statistics.stdev(agg):.4f}  "
      f"negative in {sum(1 for d in agg if d < 0)}/40")
print(f"  per-class accuracy, late - early   mean "
      f"{statistics.mean(per_class_deltas):+.4f}  "
      f"sd {statistics.stdev(per_class_deltas):.4f}  "
      f"(n={len(per_class_deltas)} class-populations)")
print()
print("The aggregate falls reliably. Nothing underneath it does. The per-class")
print(f"standard deviation of {statistics.stdev(per_class_deltas):.4f} is the noise the")
print("decomposition divides by six and reports as a finding.")

print()
print("=" * 76)
print("Predictions")
print("=" * 76)
for k, v in PREDICTIONS.items():
    print(f"  {k}: {v}")
