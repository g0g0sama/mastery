# Deterministic graders

**Micro module.** One mechanism, one experiment, three cards. Serves steps 5-6
of [../current-cycle.md](../current-cycle.md).

**Capability:** deterministic graders (Layer 5, Aware -> Independent). Map
evidence to graduate: "Schema, field-match, and no-side-effect assertions."

---

## The problem

Your labelled set has 50 records. Production has 50,000. Every quality number
you have describes 0.1% of what you ship, and the other 99.9% is unobserved --
not because you lack a metric, but because you lack labels, and labels are the
expensive part.

## The wrong model

**"Grading is computing the metric."**

They are different jobs and conflating them is why people cannot swap a match
rule without rewriting their reporting. A **grader** is a function from one
prediction to a judgment. A **metric** aggregates judgments into a number. Keep
them separate and you can change the match rule without touching the aggregation,
add a grader without inventing a metric, and -- the point of this module -- run
graders where no gold exists at all.

The second wrong model follows from the first: **"a grader needs a gold label."**
Only one of the three kinds does.

## The mechanism

Three kinds, in the order you should exhaust them:

| Kind | Needs gold? | Judgment | Example |
|---|---|---|---|
| **Schema** | no | definitional | `event_type` outside the closed vocabulary |
| **Invariant** | no | definitional | an event with no actor; a date after the fetch time |
| **Field-match** | **yes** | policy-defined | normalized `actors` sets differ |

Schema and invariant graders encode facts, so a firing is an error by definition
-- precision 1.0 by construction. They run on unlabelled production traffic.
That is their whole value.

There is a fourth thing people write and call a grader: a **heuristic** -- a
shape correlated with error rather than definitionally wrong. "The extracted
event date equals the article's fetch date, so it is probably the publication
date." Heuristics are not free. A heuristic is a classifier, it has its own
precision, and you must measure it before routing anything on it.

## The experiment

`extraction-eval-sets/lab/graders.py`. Requires lab tasks 1 and 2.

Five checks over 36 predictions (3 systems x 12 records). No gold is consulted to
*fire* a check; the labels are used only at the end, to score the graders
themselves.

**Predict before running: the publication-date heuristic is a real, sensible
rule, and it does catch both of the genuine publication-date errors in this data.
What is its precision?** Write a number.

```powershell
cd modules\extraction-eval-sets\lab
python graders.py
```

Actual:

```text
check                                                 fired  real  precision
----------------------------------------------------------------------------
schema: event_type outside the closed vocabulary          2     2      1.000
invariant: event with no actor                            3     3      1.000
suspicion: event date equals fetch date                  27     2      0.074
```

Seven percent. The heuristic finds both real errors -- perfect recall -- and
buries them under 25 false alarms, because in news data the event usually *does*
happen on the day the article was fetched. The rule is not stupid; it is simply a
classifier nobody evaluated.

Route on that at production volume and you have built a review queue that is 93%
noise, which a human will learn to dismiss within a week -- at which point it
catches nothing and still costs money.

The contrast is the lesson. Two checks at precision 1.000 and one at 0.074, all
three written with equal confidence, and only measurement separates them.

## Boundary

- Invariant graders are only as good as the invariants, and a wrong invariant
  fails *silently in the other direction* -- it never fires and you conclude the
  property holds. Assert one deliberately-broken record against each invariant,
  the same way `verify.py` checks specifications against mutants.
- Precision 1.0 says nothing about recall. Schema and invariant graders catch a
  narrow, definitional slice; they cannot see a fluent, well-formed, entirely
  wrong record.
- "No-side-effect" assertions -- the third item in the map's evidence line --
  matter once extraction can write. Assert that a scoring or dry run performed no
  insert, no outbound call, no file write. That grader has no metric attached and
  is still the one that saves you.
- Exhaust deterministic graders before reaching for a model-based one. They are
  free, reproducible, and instant, and a rubric grader you have not compared
  against them is a rubric grader you cannot trust.

## Cards

### 1. [comparison] What distinguishes a grader from a metric in an evaluation pipeline, and why keep them separate?

**Answer:** A grader judges one prediction; a metric aggregates judgments into a
number.

**Why:** Separated, you can change the match rule without touching reporting,
add a grader without inventing a metric, and run graders where no gold exists.
Fused, every change to either requires rewriting both.

**Boundary:** The split only pays off if the grader returns a structured judgment
-- counts or a labelled outcome -- rather than a float it has already collapsed.

**Tags:** `evaluation` `comparison` `general-principle`

---

### 2. [mechanism] Which kinds of grader can run on unlabelled production traffic, and why does that matter more than their accuracy?

**Answer:** Schema and invariant graders, because they encode facts about a
storable record rather than comparing against a gold answer.

**Why:** The labelled set is a few hundred records and production is a few
hundred thousand. A grader that needs no gold is the only quality signal that
covers the traffic you actually ship.

**Boundary:** They are definitionally precise and narrow. Neither can see a
well-formed, fluent, entirely wrong record, so they supplement a labelled set
rather than replacing it.

**Tags:** `evaluation` `mechanism` `general-principle`

---

### 3. [failure] You add a heuristic check -- "flag records whose event date equals the article's fetch date" -- and route every hit to a review queue. What must you measure first, and what happens if you do not?

**Answer:** The heuristic's own precision on your labelled set. In this module's
data it is 0.074: it catches both real errors and raises 25 false alarms.

**Why:** A heuristic is a classifier, not a fact. Unmeasured, it produces a queue
that is mostly noise, reviewers learn to dismiss it within a week, and it then
costs money while catching nothing.

**Boundary:** Low precision is not a reason to delete it -- recall was perfect
here. It is a reason to make it a ranking signal or pair it with a second check,
rather than a page.

**Tags:** `evaluation` `failure` `general-principle`
