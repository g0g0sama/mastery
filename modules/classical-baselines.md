# Classical baselines

**Micro module.** One mechanism, one experiment, three cards. Runs against
[stats-lab/](stats-lab/).

**Capability:** Classical ML: regression, trees, clustering (Layer 2, Aware ->
Working). Map evidence: "A baseline classifier that your LLM approach must
beat."

---

## The problem

The map's sequencing note says baseline before technique: BM25 before dense,
regex before LLM. The eval-set cycle already has a rules baseline for the
fields with a grammar. `event_type` has no grammar, so it looks like the field
that needs a model -- and that is exactly the shape of claim the map row exists
to make you check.

Five systems on one task, all scored on the same story-grouped holdout of 300
records: a majority-class constant, a hand-written keyword rule, multinomial
naive Bayes, one-vs-rest logistic regression, and the extractor standing in for
the model.

## The mechanism

**The headline table, and the two orderings it produces:**

```text
system          accuracy  macro F1      gap  $/record  $/correct
majority          0.2467    0.0660  +0.1807    0.0000     0.0000
keyword           0.7867    0.7209  +0.0657    0.0000     0.0000
naive_bayes       0.8033    0.6828  +0.1206    0.0000     0.0000
logreg            0.7600    0.6555  +0.1045    0.0000     0.0000
extractor         0.8267    0.7731  +0.0536    0.0042     0.0051

Ranked by accuracy:  extractor > naive_bayes > keyword > logreg > majority
Ranked by macro F1:  extractor > keyword > naive_bayes > logreg > majority
```

**The two rankings disagree, and they disagree about the two cheapest
systems.** Naive Bayes beats the keyword rule by 1.7 points of accuracy and
loses to it by 3.8 points of macro F1. Only one of those orderings can be used
to pick a system, and which one depends on whether the rare classes matter.

Per class, which is where the disagreement lives:

```text
event_type            n   majority   keyword  naive_bayes   logreg  extractor
investment           74     0.3957    0.8125       0.7162   0.6573     0.9041
trade_dispute       108     0.0000    0.9109       0.9412   0.9083     0.8557
plant_opening        47     0.0000    0.6415       0.5510   0.5149     0.8077
leadership_change    21     0.0000    0.8333       1.0000   1.0000     0.9333
sanction              8     0.0000    0.4000       0.0000   0.0000     0.3158
production_halt      30     0.0000    0.7273       0.9383   0.9024     0.8219
```

**Both learned classifiers score exactly 0.0000 on `sanction`.** Eight holdout
records, and neither ever emits the class. That is not a bug: with a 3% prior
and features shared with `trade_dispute`, predicting the majority neighbour is
the accuracy-maximising move, so accuracy rewards them for abstaining from the
class that matters most to the project. The keyword rule, which cannot learn a
prior and therefore cannot exploit one, is the only cheap system that gets
anything (0.4000). A metric that averages over records rather than classes
cannot see this, and 8 of 300 records is 2.7% of the aggregate.

**What labels are worth, measured:**

```text
  n train  naive_bayes acc  macro F1   logreg acc  macro F1
       10           0.4394    0.2990       0.4064    0.2468
       25           0.4931    0.3602       0.4494    0.2927
       50           0.6414    0.4964       0.6181    0.4385
      100           0.7261    0.5809       0.6822    0.5253
      200           0.7894    0.6643       0.7200    0.6225
      300           0.8033    0.6828       0.7461    0.6463

extractor, for reference: accuracy 0.8267  macro F1 0.7731  (needs no labels)
```

The curve is steeply concave. Labels 10 to 50 buy 0.20 of accuracy; labels 200
to 300 buy 0.014. **At n=50 -- the cycle's evidence contract number -- the
classifier is at 0.6414 and 19 points behind the extractor.** Fifty labels do
not buy a competitive classifier on this task. They buy an *instrument*, which
is what the cycle wants them for, and that is a different purchase; the
learning curve is the argument for not confusing the two.

**Two systems 2.3 points apart are not the same system:**

```text
naive_bayes and extractor on the same 300 records:
  both correct           200   (0.667)
  only naive_bayes        41   (0.137)
  only extractor          48   (0.160)
  neither                 11   (0.037)
  agreement between the two systems: 0.6833

  ceiling if a router always picked the right one: 0.9633
  agree -> accept, disagree -> review:
    coverage 0.6833, precision on the agreed set 0.9756
```

They agree on 68% of records and only 3.7% are wrong for both. The last two
lines are the usable result: routing the 68% they agree on straight through
gives **0.9756 precision against the extractor's 0.8267 alone**, and sends
under a third of the volume to review. The free classifier's value here was
never that it might replace the model -- it is that it disagrees in different
places, which is a signal the model cannot produce about itself.

## The experiment

```powershell
cd modules\stats-lab
python classical_lab.py     # ~30 s, trains over 100 models for the curve
```

## Boundary

- **The separability of the task is a declared parameter.**
  `population.CONTAMINATION` decides how many of the confusable type's keywords
  a document also carries; set it to zero and every classifier scores 0.99.
  The first version of this fixture did exactly that. Nothing in the accuracy
  *levels* transfers; the metric disagreement, the rare-class zero and the
  disjoint-failures result do.
- **The keyword rule is given the generator's own keyword lists**, so it is a
  fair upper bound on a hand-written rule and an unfair one on a rule you would
  actually write on day one.
- **Features are a bag of tokens.** No ordering, no negation, no distance --
  which is why `plant_opening` and `investment` confuse: they share vocabulary
  and differ in what the sentence asserts.
- **Nothing here covers regression, trees, or clustering**, the other three
  words in the map row. The row is satisfied by having a scored baseline that
  the model must beat, not by touring the algorithm list.
- **$0.0042 per record is illustrative**, carried over from
  `extraction-eval-sets/lab/predictions.py`.

## Cards

### 1. [failure] Your six-way classifier reports 0.80 accuracy and 0.68 macro F1. What is the most likely cause, and why does it matter?

**Answer:** A rare class it never predicts. In the lab both learned classifiers
scored exactly 0.0000 F1 on the 3% `sanction` class while leading on accuracy,
because with a small prior and shared features, predicting the majority
neighbour is the accuracy-maximising move. Eight records out of 300 cannot move
an accuracy figure.

**Why:** Accuracy averages over records; macro F1 averages over classes. The
gap between them is a direct read on how much of the score is being carried by
the common classes.

**Boundary:** Macro F1 is not simply the better metric -- it weights an 8-record
class equally with a 108-record one, so it is noisy exactly where it is
strictest (see [leakage-and-shift.md](leakage-and-shift.md) section 3, where
the bootstrap half-width on that class's F1 is 0.19). Report both, and report
the per-class table, which is the only thing that actually locates the problem.

**Tags:** `classical-ml` `metrics` `imbalance` `failure` `general-principle`

---

### 2. [mechanism] A bag-of-words classifier reaches 0.80 against the model's 0.83 on the same task. What is the useful thing to do with it?

**Answer:** Not replace the model. Route on agreement. In the lab the two
systems agreed on 68.3% of records, and on that subset precision was 0.9756
against the extractor's 0.8267 overall -- with only 3.7% of records wrong for
both, and an oracle router ceiling of 0.9633.

**Why:** Two systems built from different evidence fail on different records.
That is what makes the disagreement informative, and a model cannot generate
that signal about itself -- its own confidence is one view, not two.

**Boundary:** The coverage is the cost: a third of the volume goes to review.
And the agreed set's high precision is not free of correlation -- if both
systems share an upstream bug (the same segmenter, the same truncation), they
agree confidently and are both wrong.

**Tags:** `classical-ml` `routing` `mechanism` `general-principle`

---

### 3. [misconception] Fifty labelled records is enough to train a baseline classifier that tells you whether the model is worth its cost.

**Answer:** Not on this task. The measured learning curve puts naive Bayes at
0.6414 accuracy and 0.4964 macro F1 at n=50, against the extractor's 0.8267 and
0.7731. It reaches 0.79 at n=200 and 0.80 at n=300 -- steeply concave, with
labels 10-50 buying 0.20 of accuracy and labels 200-300 buying 0.014.

**Why:** A classifier has to learn the feature-class association from the
labels alone. Fifty examples over six classes is eight per class, and the rare
one gets two.

**Boundary:** This is not an argument against labelling fifty records. Fifty
records is enough to *measure* a system to within a large effect, which is what
the cycle wants them for; it is not enough to *train* a competitor. Confusing
those two purchases is what produces the demand for 500 labels before anything
can be measured at all.

**Tags:** `classical-ml` `learning-curve` `eval-sets` `misconception`
