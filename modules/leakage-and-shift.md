# Leakage, shift, and imbalance

**Micro module.** One mechanism, one experiment, three cards. Runs against
[stats-lab/](stats-lab/).

**Capability:** Leakage, distribution shift, imbalance (Layer 2, Aware ->
Independent). Map evidence: "Find the leak in a naively split dataset."

---

## The problem

The frozen holdout in the cycle's evidence contract exists to answer one
question: would this change help on documents nobody has seen? Four things
break that answer, and only the first is normally called leakage. The second
one is a live decision in [../current-cycle.md](../current-cycle.md).

## The mechanism

**1. The split cuts through near-duplicates.** One news story is covered by
several outlets, so documents arrive in groups. In this fixture 234 stories
produce 600 documents and **86.7% of documents have at least one near-duplicate
elsewhere in the corpus**.

```text
split                   train  test  shared stories  accuracy  macro F1
random over records       300   300             115    0.7500    0.6604
grouped by story          300   300               0    0.7733    0.6883
temporal, day<60          302   298               0    0.7886    0.6861
```

A random split shares 115 stories across the boundary. On this particular seed
it reports **less** than the grouped split, which is the wrong sign -- and that
is the first result worth keeping. Over 30 seeds:

```text
accuracy inflation  mean +0.0426  sd 0.0341  min -0.0298  max +0.1033
                    negative in 3/30 seeds
macro F1 inflation  mean +0.0619  sd 0.0422
```

The leak is real, it averages four points of accuracy and six of macro F1, and
**one split cannot establish it** -- 3 seeds in 30 point the other way. If you
compare a random against a grouped split once on your own data and see nothing,
you have learned nothing. This is the same arithmetic
[eval-set-sample-size.md](eval-set-sample-size.md) found for a 3-point F1
difference, arriving from the split side.

**2. The labels were produced by correcting the system's output.** A labeller
reviewing extractor output notices 75% of its errors, and only 45% when the
error lands on the confusable neighbour -- the error that reads as plausible.
Both rates are declared. The consequence is not:

```text
system          vs blind labels  vs corrected labels      gap
extractor                0.8300               0.8900  +0.0600
naive_bayes              0.7733               0.7467  -0.0267
```

The corrected set agrees with the truth on 94% of records, which sounds
tolerable. But the 6% is not random: every one of those records is a case where
the extractor was wrong and the labeller did not notice, so the bias points in
one direction. **The extractor gains 6.0 points and its competitor loses 2.7 --
an 8.7-point swing in the measured gap between two systems**, produced entirely
by who wrote the labels.

Per type, the inflation is largest exactly where the extractor is worst:

```text
event_type            n  true acc  corrected acc  inflation
investment          115    0.8957         0.9130    +0.0174
trade_dispute       181    0.7514         0.8895    +0.1381
plant_opening        95    0.8842         0.9158    +0.0316
leadership_change    45    0.8889         0.9111    +0.0222
sanction             44    0.4773         0.7500    +0.2727
production_halt     120    0.8500         0.8833    +0.0333
```

`sanction` reads 0.7500 instead of 0.4773. A set built this way is least
trustworthy about the class you most need it to be trustworthy about, because
the errors a labeller fails to notice and the errors a model makes confidently
are the same errors.

**3. The rare class does not have a score, it has a range.** `sanction` is
declared at 6% early and 18% late. Over 40 fresh populations the realised share
runs 0.0617 to 0.1800 -- a factor of three -- because the class is drawn per
*story*, so 600 documents are about 232 independent draws, not 600. On one
grouped holdout with 12 sanction records:

```text
             point         95% interval      half-width
extractor    0.2857   [0.0800, 0.4828]          0.2014
naive_bayes  0.1739   [0.0000, 0.3846]          0.1923
```

An F1 of 0.2857 with a half-width of 0.20 cannot distinguish "broken" from
"mediocre", and it is the number a macro average weights equally with a class
that has 108 records.

**4. The traffic moved, and the decomposition that is supposed to catch it
produces a fiction.** The mix shifts on day 60; there is **no quality change in
the generator at all**.

```text
slice                   early acc  late acc   change  early share  late share
ALL (extractor)            0.8576    0.7617  -0.0959        1.000       1.000
  investment               0.9344    0.8519  -0.0826        0.202       0.181
  trade_dispute            0.8161    0.6915  -0.1246        0.288       0.315
  plant_opening            0.9194    0.8182  -0.1012        0.205       0.111
  leadership_change        0.9565    0.8182  -0.1383        0.076       0.074
  sanction                 0.5882    0.4074  -0.1808        0.056       0.091
  production_halt          0.8077    0.8824  +0.0747        0.172       0.228

  observed late accuracy       0.7617
  late accuracy at early mix   0.7764
  attributed to the mix        -0.0147
  attributed to 'quality'      -0.0812   of a total -0.0959
```

The decomposition hands back a 0.0812 quality regression that does not exist.
Over 40 fresh populations:

```text
aggregate accuracy, late - early   mean -0.0455  sd 0.0337  negative in 37/40
per-class accuracy, late - early   mean +0.0016  sd 0.0824  (n=234)
```

**The aggregate falls reliably and nothing underneath it moves.** The per-class
standard deviation of 0.0824 on ~50-record slices is the noise the
decomposition divides among six classes and reports as a finding. This extends
[metrics-and-cost-monitoring.md](metrics-and-cost-monitoring.md)'s result --
aggregate unit cost moved 54.7% with no slice moving -- with the part that
hurts: the standard remedy is underpowered at the sample size that produced the
alarm, so it converts a mix change into a confident, specific, wrong
attribution.

## The experiment

```powershell
cd modules\stats-lab
python leakage_lab.py     # ~50 s, 30 seeds plus two bootstraps
```

## Boundary

- **Every magnitude here is a property of `population.py`'s declared
  parameters** -- `STORY_SIZES`, `NOTICE_RATE`, `BASE_RATES_LATE`. The
  directions are not: a group-correlated split cannot deflate a holdout in
  expectation, and labels produced by correction cannot be unbiased with
  respect to the system that produced them.
- **Story membership is known here.** In a real corpus it is not, and finding
  the groups is the work: near-duplicate detection, canonical URL, wire-service
  id, or a shingle hash. A group split you cannot compute is not a plan.
- **The labeller model is one-directional.** A real reviewer also introduces
  errors on records the system got right, which this does not model and which
  makes the corrected set worse, not better.
- **The temporal split here is also a group split** (stories do not span the
  boundary), so it isolates the mix effect. A real temporal split usually has
  both.
- **Nothing here covers feature leakage** -- a field computed after the label
  exists, which is the other common leak and needs schema review rather than a
  split strategy.

## Cards

### 1. [failure] Your holdout says the new extractor is 4 points better. What is the first thing to check about how the split was made?

**Answer:** Whether near-duplicate documents span it. In the lab 86.7% of
documents had a near-duplicate elsewhere in the corpus, and a random split
inflated accuracy by a mean of +0.0426 and macro F1 by +0.0619 against a
story-grouped split over 30 seeds.

**Why:** A random split puts one outlet's version of a story in train and
another outlet's version in test, so the holdout measures recall of things
already seen.

**Boundary:** One comparison does not establish it -- 3 of 30 seeds showed the
opposite sign, sd 0.0341 against a mean of 0.0426. Run several seeds, or
inspect the group structure directly. And the group key is the real work: if
you cannot compute "same story", you cannot make the split.

**Tags:** `leakage` `eval-sets` `splits` `failure` `general-principle`

---

### 2. [misconception] Labelling by correcting the model's output is just a faster way to get the same labels.

**Answer:** It is a different label set with a directional bias. In the lab it
agreed with blind labels on 94% of records, and the 6% disagreement raised the
extractor's measured accuracy by 6.0 points while lowering its competitor's by
2.7 -- an 8.7-point swing in the gap between them. Per type the inflation was
worst where the extractor was worst: `sanction` read 0.7500 against a true
0.4773.

**Why:** A reviewer accepts what looks plausible. The errors a model makes
confidently and the errors a reviewer fails to notice are the same errors, so
the correction pass is systematically blind in the model's blind spot.

**Boundary:** Correction is still the right way to build the *bulk* of a set --
it is several times faster. The holdout has to be labelled blind, and the two
must never be pooled. This is the answer to open question 1 in
[../current-cycle.md](../current-cycle.md).

**Tags:** `labelling` `leakage` `eval-sets` `misconception`

---

### 3. [mechanism] Aggregate accuracy fell 10 points. You decompose it into a mix term and a quality term. What can go wrong?

**Answer:** The quality term can be entirely noise. In the lab the generator
contains no quality change at all -- per-class accuracy is stationary by
construction -- and the decomposition still attributed -0.0812 of a -0.0959
drop to "quality". Over 40 populations the aggregate fell in 37 and the mean
per-class change was +0.0016 with sd 0.0824.

**Why:** The per-class accuracies are estimated on slices of a few dozen
records each. Their noise does not cancel in the reweighting; it lands in the
residual, which is the term labelled "quality".

**Boundary:** The decomposition is still the right first move -- it is the only
thing that separates the two causes at all. Put an interval on the quality term
before acting on it, and report volume-by-slice next to it. When the slices are
too small to carry an interval, the honest output is "the mix moved and the
data cannot say whether quality did", which is what routes the alarm to a
labelled eval run instead of to an engineer.

**Tags:** `distribution-shift` `metrics` `slices` `mechanism` `general-principle`
