# Error taxonomy

**Micro module.** One mechanism, one experiment, three cards. Serves step 9 of
[../current-cycle.md](../current-cycle.md).

**Capability:** error taxonomy (Layer 5, **Deep** target). This module is the
Aware-to-Working step only -- the Deep evidence is named failure classes with
counts driving the next fix on the real Sinoscope set, which is cycle work.

---

## The problem

Your extraction scores 0.87 F1. You want it at 0.92. What do you build?

The metric cannot tell you. It is a scalar, and "0.87" has no gradient pointing
at a next action. So the usual move is to guess -- rewrite the prompt, try a
bigger model, add few-shot examples -- and measure again. Each guess costs a
day and the measurement, as the sample-size module shows, cannot resolve the
size of improvement a guess typically produces. That loop can run for months.

## The wrong model

**"The taxonomy comes from breaking down the metric: precision errors, recall
errors, per-field."**

This feels like analysis and produces nothing, because it is a restatement. "23
recall errors on `actors`" is the same fact as the recall score, reorganised.
Every class it yields is a *symptom*, and symptoms do not name fixes.

A class must name a **cause** that implies an action. The test: can you write the
fix in the same sentence? "Actors missed" fails. "Gold holds the short form and
the model emits the registered legal name" passes -- the fix is entity linking,
and it is now competing for your time against the other classes on evidence
rather than on intuition.

## The mechanism

1. Dump every individual error as one line: record id, field, invented or
   missed, and the value. Not aggregates -- individual errors, readable.
2. Read them. Assign a class by hand, coining new classes as you go. This is
   manual on purpose; the classes are not in the data, they are in the
   explanation of the data.
3. Count per class, and sort.
4. Attach a fix to each class and its rough cost.
5. Build the top class. Re-run. The class should shrink; if the metric moves and
   the class does not, the taxonomy is wrong.

Step 5 is what makes this an instrument rather than an essay: a taxonomy makes
falsifiable predictions about which errors a change will remove.

## The experiment

`extraction-eval-sets/lab/errors.py`. Requires task 1 of the lab (the
normalizers). Unlike the rest of that lab it prints raw field values, because you
cannot classify an error you cannot read.

**Predict before running: model_a has 11 errors and model_b has 8. Predict how
many distinct causal classes each has, and whether the system with fewer errors
has fewer classes.**

```powershell
cd modules\extraction-eval-sets\lab
python errors.py model_a
python errors.py model_b
python errors.py rules
```

`model_a`, 11 errors (regrouped here by class -- the script prints in record
order):

```text
R01  actors      INVENTED  中国石油化工集团有限公司
R01  actors      MISSED    中国石化
R05  actors      INVENTED  华为
R05  actors      MISSED    华为技术有限公司
R03  actors      INVENTED  中国铝业
R03  actors      MISSED    厦门钨业
R09  time        INVENTED  2026-04-05
R10  time        INVENTED  2026-04-16
R10  time        MISSED    2026-04-17
R12  event_type  INVENTED  sanction
R12  event_type  MISSED    trade_dispute
```

Four classes, and they are wildly unequal:

| Class | Errors | Fix |
|---|---|---|
| Legal-form mismatch: gold short form, model registered name (or the reverse) | 4 | Entity linking, or a policy change -- both, measured |
| Publication date read as event date | 1 | A prompt constraint, cheap |
| Date substitution, off by one day | 2 | Source-span provenance, so the date is traceable |
| Closed-vocabulary confusion between adjacent types | 2 | Vocabulary definitions in the prompt, cheap |

**Thirty-six percent of model_a's errors are one class, and it is the only class
whose fix is a system rather than a sentence.** No F1 delta could have told you
that. Note also that the legal-form class produces an INVENTED and a MISSED line
for the same underlying error -- error counts double-count substitutions, which
is why the class table, not the line count, is what you act on.

`model_b`, 8 errors, and the shape is the finding (the three R03 lines are
printed separately):

```text
R03  actors      MISSED    厦门钨业 / 广晟有色 / 盛和资源
R05  actors      MISSED    华为技术有限公司
R06  location    MISSED    华盛顿
R08  actors      MISSED    合肥市政府
R10  time        MISSED    2026-04-17
R12  event_type  MISSED    trade_dispute
```

Every line says MISSED. Not one INVENTED. Model_b has fewer errors *and* fewer
classes -- essentially one, "abstains under uncertainty" -- with one fix
(a lower abstention threshold, paid for in precision) and a decision to make
about whether you want it. The taxonomy makes visible in six seconds of reading
what the F1 scores of 0.8696 and 0.8780 actively concealed.

And `rules`, 23 errors, 12 of which are `event_type MISSED`: one class, one fix,
and it is not a modelling problem -- the baseline has no `event_type` rule at
all. A taxonomy over a baseline tells you which fields need a model, which is the
result worth having on day one.

## Boundary

- The taxonomy is built on **your** labels, so a labelling error becomes a
  spurious class. A class you cannot explain is a prompt to re-check the gold,
  not to build something.
- Classes are not stable across systems. Model_a's and model_b's taxonomies share
  almost nothing, so a taxonomy is an artifact of a system-and-set pair and gets
  redone when either changes materially.
- Long-tail classes with one member each are not evidence. Keep them in a
  bucket, but do not act on a class of size one from a 12-record set -- see
  [eval-set-sample-size.md](eval-set-sample-size.md).
- Beware classing by field. Field is a location, not a cause; the legal-form
  class and the long-tail class both live in `actors` and have nothing in common.

## Cards

### 1. [misconception] Why is "23 recall errors on the actors field" not a class in an error taxonomy?

**Answer:** It is a restatement of the metric, not a cause. It names where the
errors are, not why they happened, so it implies no fix.

**Why:** The test for a class is whether the fix fits in the same sentence.
"Gold holds the short form and the model emits the registered legal name" passes
-- the fix is entity linking. "Actors missed" does not.

**Boundary:** Field is a useful *index* for grouping errors while you read them;
it is just not the classification.

**Tags:** `evaluation` `misconception` `general-principle`

---

### 2. [scenario] Two extractors score 0.870 and 0.878 F1 on the same field. What does dumping and classifying their individual errors reveal that the scores do not?

**Answer:** That the failures have different shapes and different fixes -- in
this module's data, one system's errors are all omissions with a single cause,
the other's split across four classes including fabrication.

**Why:** F1 pools false positives and false negatives, so systems with opposite
failure modes land on the same score. The class counts are what tell you which
fix to build first.

**Boundary:** Substitutions appear as an INVENTED line and a MISSED line for the
same error, so act on class counts rather than raw error counts.

**Tags:** `evaluation` `scenario` `general-principle`

---

### 3. [best-practice] What makes an error taxonomy an instrument rather than a piece of writing?

**Answer:** That it predicts which specific errors a proposed change will
remove, and that you check the class shrank -- not just that the metric moved.

**Why:** A metric improvement with no corresponding drop in the targeted class
means the change worked for a reason you have not identified, and the taxonomy
is wrong. That is a finding, and it is invisible if you only watch F1.

**Boundary:** Re-derive the taxonomy after any material change to the system or
the set; classes are an artifact of a system-and-set pair, not a property of the
task.

**Tags:** `evaluation` `best-practice` `general-principle`
