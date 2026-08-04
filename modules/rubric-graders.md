# Model-based and rubric graders

**Micro module.** One mechanism, one experiment, three cards. Closes the gap
`extraction-eval-sets/lab/policy.py` decision 5 deliberately left open: `claims`
is in the schema and absent from the score because it needs a rubric grader.

**Capability:** model-based and rubric graders (Layer 5, - -> Independent). Map
evidence to graduate: "Grader agreement measured against your own labels."

---

## The problem

`claims` is free text. "公司宣布在当地新建研发中心" against a predicted
"该公司计划在深圳投资建设研发中心" -- is that right? There is no set
intersection to compute. Exact match says no; a human says mostly, with a
qualifier the source did not contain.

So you use a model as the judge, with a rubric. That is the correct move, and it
introduces a component nobody evaluates.

## The wrong model

**"The judge is the measurement, so it does not itself need measuring."**

A rubric grader is a classifier you deployed without a test set. It has a
precision, a recall, and a bias, and you are about to make shipping decisions
out of its output. Every objection you would raise about trusting the extractor
applies to the thing grading the extractor -- with the twist that its errors are
harder to see, because its output *is* the ground truth in every downstream
report.

The second wrong model is subtler and it is the one this experiment kills:
**"agreement with the human is a single number."** It is not. It is an average
over cases where the grader is trivially right and cases where it is nearly
useless, and the mix is set by your data, not by the grader.

## The mechanism

1. Write the rubric as a **decision procedure**, not a vibe: what counts as
   supported, what counts as a paraphrase, what to do with an added qualifier,
   how to break ties. If two humans cannot follow it, a model cannot either --
   which is why [inter-annotator-agreement.md](inter-annotator-agreement.md)
   comes first.
2. Label a sample **yourself**, blind to the judge's output.
3. Run the judge. Cache its verdicts to a file, so the harness is deterministic
   and re-scorable without re-spending.
4. Measure agreement -- kappa, not raw -- **and the marginals**, which reveal
   directional bias.
5. **Stratify.** Report agreement separately on clear and borderline cases. This
   is the step that is always skipped and it is where the answer lives.
6. Only then decide whether to route decisions on it, and at what confidence.

## The experiment

`extraction-eval-sets/lab/rubric.py`. The judge's verdicts are a recorded
transcript checked into the lab, so the run is offline and deterministic; in your
project that file is written by a real call and everything downstream is
identical. Constructed fixture -- the arithmetic is real, the 16 rows are
authored.

Sixteen claim judgments, human against judge, each pre-tagged clear or borderline
by the human *before* seeing the judge's answer.

**Predict before running: raw agreement is 13/16. Predict kappa, and predict
whether the disagreements are spread evenly across clear and borderline cases.**

```powershell
cd modules\extraction-eval-sets\lab
python rubric.py
```

Actual:

```text
human called it supported 10/16, judge called it supported 13/16

raw agreement   po = 0.8125
Cohen's kappa      = 0.5556

subset           n   agreement    kappa
clear           10      1.0000   1.0000
borderline       6      0.5000   0.1818
```

The headline kappa of 0.556 reads as "moderate, usable". It is an average of
**1.0000 on the cases that did not need a grader** and **0.1818 on the cases that
did** -- barely above chance, on the only subset the grader exists to adjudicate.

Then the marginals: the judge calls a claim supported 13 times out of 16 to the
human's 10, and every single disagreement runs the same direction -- the judge
accepting an unsupported claim. That is not noise, it is a bias, and it means the
grader will systematically overstate your groundedness in exactly the way a
groundedness metric is supposed to prevent.

Notice what would have happened with a different data mix. Fill the sample with
clear cases and the headline kappa approaches 1.0 with the grader unchanged. **The
number describes your sample as much as your grader**, which is why the
stratified table is the report and the single number is not.

## Boundary

- Kappa here compares the judge to *you*, so it measures agreement, not
  correctness -- see [inter-annotator-agreement.md](inter-annotator-agreement.md).
  A judge that has learned your idiosyncratic reading scores well and is still
  wrong.
- Sixteen rows cannot resolve a small difference between two judges. Sizing
  applies to grader evaluation exactly as it does to system evaluation --
  [eval-set-sample-size.md](eval-set-sample-size.md).
- Cache and version the judge's verdicts alongside the model id and the rubric
  text. A judge silently upgraded underneath you re-scores history, and the
  fingerprint that catches it is in
  [eval-set-versioning.md](eval-set-versioning.md).
- Exhaust deterministic graders first. A rubric grader that has not been compared
  against schema and field-match assertions on the cases those *can* decide is
  spending money and variance on solved problems --
  [deterministic-graders.md](deterministic-graders.md).
- Position bias, verbosity bias, and self-preference are documented failure modes
  of model judges. Check the vendor's current evaluation guidance rather than
  this file for what is known about the model you actually use.

## Cards

### 1. [misconception] You measure your rubric grader's agreement with your own labels at kappa 0.56 and call it usable. What has that number hidden?

**Answer:** That agreement is not uniform. Stratified, it can be 1.0 on clear
cases and near chance on borderline ones -- and borderline is the only subset the
grader exists to adjudicate.

**Why:** The headline is an average weighted by your sample's mix of easy and
hard cases, so it describes the sample as much as the grader. Load the sample
with easy cases and the same grader scores near 1.0.

**Boundary:** Stratify by a difficulty tag assigned before the judge runs, or the
strata are contaminated by the thing you are measuring.

**Tags:** `evaluation` `misconception` `general-principle`

---

### 2. [mechanism] Beyond an agreement statistic, what must you read from a rubric grader's confusion table, and what does it reveal?

**Answer:** The marginals -- how often each side assigned each label. Unequal
marginals reveal directional bias.

**Why:** A judge calling claims supported 13 times to a human's 10, with every
disagreement in that direction, is not noisy: it systematically overstates
groundedness, which is precisely what a groundedness metric exists to prevent.

**Boundary:** Bias and agreement are independent. A grader can be well-calibrated
in aggregate and still disagree case by case, which is why both are reported.

**Tags:** `evaluation` `mechanism` `general-principle`

---

### 3. [best-practice] Why cache a model judge's verdicts to a versioned file rather than calling it fresh each evaluation run?

**Answer:** So the evaluation is deterministic and re-scorable without re-paying,
and so the judge's identity is pinned alongside its output.

**Why:** An un-pinned judge silently upgraded by the provider re-scores your
history, and every stored number becomes incomparable with no diff to show for
it. The cached file with a model id and rubric text is what makes an old number
still mean something.

**Boundary:** Re-run the judge deliberately when the rubric changes, and treat
that as a new set version rather than an update to the old one.

**Tags:** `evaluation` `best-practice` `general-principle`
