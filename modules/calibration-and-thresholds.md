# Calibration and thresholds

**Micro module.** One mechanism, one experiment, three cards. Runs against
[stats-lab/](stats-lab/).

**Capability:** Calibration and thresholds (Layer 2, Aware -> Independent). Map
evidence: "Pick a confidence threshold from a precision/recall curve."

---

## The problem

The extractor states a confidence on every record. Somebody is going to use it
to decide what a human looks at, and there are two separate questions hiding
inside that sentence: is the number a probability, and where does the cut-off
come from. They have different answers and the second one does not depend on
the first in the way everybody assumes.

600 records, 234 stories, six event types, extractor accuracy 0.8100. The
confidence is generated from a declared per-type bias, so the *magnitudes*
below are fixture properties. The two results that decide how to think about
this are theorems and would reproduce on any data.

## The mechanism

**The number is not a probability, and the gap is not uniform.** Mean stated
confidence 0.8918 against accuracy 0.8400, so +0.0518 overall. Per type:

```text
event_type            n   ECE raw   ECE cal  conf-acc raw  conf-acc cal
investment          146    0.0273    0.0298       +0.0273       -0.0164
trade_dispute       179    0.0854    0.0701       +0.0756       +0.0229
plant_opening       108    0.0691    0.0568       -0.0071       -0.0553
leadership_change    40    0.0683    0.1294       -0.0154       -0.0628
sanction             22    0.3125    0.2547       +0.3125       +0.2547
production_halt     105    0.0770    0.0395       +0.0770       +0.0269
```

The aggregate +0.05 is an average over a class that is well calibrated and a
class that is 31 points overconfident. `sanction` is the class the extractor is
worst at (accuracy 0.4773) and the one it is most confident about, which is the
usual direction and the expensive one.

**Fitting a temperature fixes the aggregate and cannot fix that.** T = 1.37,
fitted on a story-grouped half:

```text
metric                     raw conf   calibrated     change
ECE (equal-width 10)       0.061938     0.029136   -0.031531
Brier                      0.132162     0.128415   -0.003747
negative log likelihood    0.433040     0.408934   -0.024105
AUC                        0.736042     0.736042   +0.000000
```

**The AUC row is exact and it is the point of the module.** Temperature scaling
is strictly monotone, so it cannot reorder two records, so every metric that
depends only on the ordering is unchanged to the last decimal. The lab asserts
the holdout ordering is identical afterwards and it is. Calibration does not
make a model better at telling right from wrong. Whatever ability to separate
correct from incorrect the confidence had, it still has, exactly.

What it changes is that the number becomes one you may do arithmetic with. And
the per-type table shows the cost of the global version: `investment` went from
0.0273 to 0.0298 and `leadership_change` from 0.0683 to **0.1294** -- one
temperature dragged two already-calibrated classes into underconfidence to
compensate for one broken class it still did not fix.

**Where the threshold comes from, with review costing 1 and a wrong shipped
record costing 8:**

```text
rule                                     threshold  coverage  precision  cost/rec
analytic threshold on RAW confidence        0.8750    0.6133     0.9076    0.8400
analytic threshold on CALIBRATED prob       0.8750    0.4433     0.9398    0.7700
swept on the fit split, raw                 0.9500    0.4100     0.9431    0.7767
swept on the fit split, calibrated          0.8900    0.4267     0.9375    0.7867
accept everything                           0.0000    1.0000     0.8267    1.3867
review everything                           1.0000    0.0000        n/a    1.0000
```

The threshold is arithmetic, not a search. Auto-accept when the probability of
being correct exceeds `1 - review/wrong` = 0.875, because that is where the
expected cost of shipping crosses the cost of looking. **The analytic rule on
calibrated probabilities is the cheapest of the six, and both swept thresholds
lose to it** -- a sweep fits the noise in the split it was swept on, and there
is no reason for the empirical optimum to generalise when the cost structure
already determines the answer.

This is where calibration pays. The same rule, `p > 0.875`, costs 0.8400 per
record on the raw number and 0.7700 on the calibrated one, because on the raw
number 0.875 does not mean what the arithmetic assumed. Calibration buys the
right to use the cost ratio.

**A swept threshold is unstable at every sample size worth having:**

```text
 n records  median threshold   10th-90th   holdout cost/rec
        50              0.830   0.68-0.96             0.8906
       100              0.880   0.70-0.96             0.8408
       200              0.880   0.72-0.96             0.8235
       300              0.880   0.77-0.96             0.8133
```

At n=300 the 10th-90th range is still 0.19 wide. That is the same arithmetic
[eval-set-sample-size.md](eval-set-sample-size.md) found for a 3-point F1
difference, arriving at a different decision.

**One worry that turns out to be the wrong worry.** Four defensible ECE
estimators on the same 600 records give 0.0518, 0.0568, 0.0544 and 0.0518 --
a spread of 0.005. The bootstrap 95% interval on one of them is
[0.0315, 0.0816], a half-width of 0.0250, five times the spread. On the 22
`sanction` records the point estimate is 0.3125 with a half-width of **0.1985**.
Binning is not the problem; n is. Quote the Brier score if you want a
binning-free number, and quote an interval either way.

## The experiment

```powershell
cd modules\stats-lab
python calibration_lab.py
```

## Boundary

- **The confidence is generated**, from `population.CONFIDENCE_BIAS`. That the
  extractor is most overconfident on its worst class is declared, not
  discovered. Measure the direction on your own records before assuming it.
- **Temperature scaling is the weakest recalibrator** and was chosen because it
  has one parameter and the monotonicity argument is visible. Isotonic
  regression fits more and needs more data; it is also monotone, so the AUC
  result holds for it too.
- **Per-type calibration is the obvious fix and it is not free**: it needs
  enough records per type to fit, and `sanction` has 22.
- **Nothing here covers calibration under distribution shift.** A temperature
  fitted in one period is a parameter fitted on a distribution; see
  [leakage-and-shift.md](leakage-and-shift.md) section 4.
- **The cost ratio is declared.** 1 and 8 are made up. The arithmetic is not,
  and the ratio is the only input it needs.

## Cards

### 1. [mechanism] Recalibrating a model's confidence improved ECE by half. What happened to its ability to rank correct answers above incorrect ones?

**Answer:** Nothing, exactly. In the lab, temperature scaling moved ECE from
0.0620 to 0.0291 and AUC from 0.736042 to 0.736042. Any monotone recalibration
-- temperature, Platt, isotonic -- preserves the ordering of every pair of
records, so every ranking metric is unchanged to the last decimal.

**Why:** Calibration is a relabelling of the confidence axis, not a change to
which record sits where on it.

**Boundary:** So calibration is worth doing for a different reason: it makes the
number admissible in expected-cost arithmetic and comparable across slices. If
the decision is "review the worst 20%", recalibration changes nothing at all --
you are using a rank, and the rank is what did not move.

**Tags:** `calibration` `metrics` `mechanism` `general-principle`

---

### 2. [failure] You need an auto-accept threshold. Reviewing a record costs 1, shipping a wrong one costs 8. What threshold, and what is the tempting mistake?

**Answer:** Accept when P(correct) > 1 - 1/8 = 0.875. It comes from the cost
ratio, not from the data. The tempting mistake is to sweep thresholds and take
the best on the split you have: in the lab both swept thresholds lost to the
analytic one on the holdout (0.7767 and 0.7867 against 0.7700 per record), and
the swept value had a 10th-90th range of 0.77-0.96 even at n=300.

**Why:** The sweep is fitting noise in a quantity the cost structure already
determines. It also silently assumes the split's error rate is the deployment
error rate.

**Boundary:** The arithmetic only works on a *calibrated* probability. In the
lab the identical rule cost 0.8400 per record applied to the raw confidence and
0.7700 applied to the calibrated one -- same threshold, same records, 8% of the
budget. Recalibrate first, or derive the threshold empirically and accept it
will not survive the next model.

**Tags:** `calibration` `thresholds` `cost` `failure` `general-principle`

---

### 3. [misconception] Aggregate ECE fell after recalibration, so the confidences are now trustworthy.

**Answer:** Not per slice. One global temperature moved `leadership_change`
from ECE 0.0683 to 0.1294 and `investment` from 0.0273 to 0.0298 -- both were
already calibrated and were dragged into underconfidence -- while `sanction`,
the class that was 31 points overconfident, stayed at 0.2547.

**Why:** A single scalar can only rotate the whole reliability curve. If the
miscalibration differs by slice, fixing the average necessarily moves the
well-behaved slices in the wrong direction.

**Boundary:** Per-slice calibration needs records per slice, and the slice that
needs it most is usually the rarest -- 22 records here, on which the ECE
estimate itself has a 95% half-width of 0.1985. The honest move is often to
report the slice as uncalibrated rather than to fit a parameter to 22 points.

**Tags:** `calibration` `slices` `misconception` `general-principle`
