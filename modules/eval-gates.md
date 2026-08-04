# Regression suites and eval gates

**Micro module.** One mechanism, one experiment, three cards. Serves the cycle's
project transfer -- the mechanism that keeps a measured improvement from being
undone silently three weeks later.

**Capability:** regression suites and eval gates (Layer 5, - -> Independent).
Map evidence to graduate: "A change that fails the gate and is therefore not
shipped."

---

## The problem

You measured a change, it helped, you shipped it, you wrote the ADR. Six weeks
later someone edits a prompt for an unrelated reason and quietly gives back
everything you gained. Nobody notices for a month, because nobody re-ran the
evaluation -- and nobody re-ran it because re-running it is a thing a person has
to remember to do.

An evaluation nobody is required to run measures nothing. It documents a moment.

## The wrong model

**"The gate is a threshold on the headline metric: ship if F1 is at least what it
was."**

Two ways it fails, and both are common.

It **passes catastrophes**. A change that destroys one field while improving three
raises the average. The datetime regression in this module's experiment drops one
field to zero and leaves the aggregate looking survivable -- the gate must watch
every field, not their summary.

It **cannot tell a regression from noise**. A threshold of "no drop at all" fires
constantly on resampling noise and gets disabled within a fortnight; a threshold
loose enough to be quiet is loose enough to pass real regressions. The tolerance
has to be chosen against the set's measured noise floor, and if the two are
incompatible the honest conclusion is that the set is too small -- not that the
gate is wrong.

## The mechanism

A gate is four things, and it is not a gate if it is missing the last one:

1. **A recorded baseline** -- scores committed to the repository with a date and
   a git sha. Recorded, not recomputed: a baseline recomputed at gate time from
   the current code cannot detect a regression, because it *is* the regression.
2. **A frozen set and a seed.** Both sides scored on the same records with the
   same instrument. A gate whose set changed between runs measured two things.
3. **Per-field checks plus a validity floor**, with a stated tolerance -- never
   the headline alone.
4. **A non-zero exit code that blocks something.** Advisory gates are dashboards.

Then the part that people skip: measure the **noise floor**. Bootstrap the
per-field metric on your set and compare its half-width to your tolerance.
Anything smaller than the noise floor is structurally invisible to the gate at
that set size, and you should know the size of your blind spot rather than
discover it.

## The experiment

`extraction-eval-sets/lab/gate.py`. Requires all five lab tasks. Exit code 0 on
pass, 1 on fail, so it runs in CI.

**Predict before running all three: which of the three candidates the gate
blocks.**

```powershell
cd modules\extraction-eval-sets\lab
python gate.py                    # unchanged
python gate.py --break datetime   # emits datetimes instead of dates
python gate.py --break subtle     # drops one actor from one record
```

Unchanged passes. The datetime change is blocked:

```text
field F1: time      0.9524     0.0000  -0.9524   0.000  FAIL
record accuracy     0.5000     0.0833  -0.4167      --  FAIL

GATE FAILED -- not shipped:
  - time F1 regressed -0.9524
  - record accuracy regressed -0.4167
```

That is the map's evidence line, executed: a change that fails the gate and is
therefore not shipped.

The third run is the one to sit with:

```text
field F1: actors    0.8780     0.8500  -0.0280   0.106  ok (under noise)

GATE PASSED.
  Note: actors moved -0.0280, inside this set's noise floor of +/-0.106.
  A regression smaller than the noise floor cannot be caught here,
  whatever tolerance you set. That is a set-size problem, not a gate one.
```

A real regression -- an actor genuinely dropped -- passes the gate. Not because
the tolerance was badly chosen but because at n=12 the noise floor is 0.106 and
the regression is 0.028. No tolerance setting catches it: tighten below the noise
floor and the gate fails on unchanged code.

This is the same constraint as [eval-set-sample-size.md](eval-set-sample-size.md)
arriving from the other direction. There, it limited what an ADR could claim.
Here, it sizes the regressions you are able to defend against. Both reduce to:
**decide the smallest regression you must catch, then size the set to it.**

## Boundary

- A gate defends the metrics it watches, and a change can be bad in ways nobody
  wrote a check for -- latency, cost, tone, a new failure class. Pair the gate
  with an error taxonomy re-run on the diff, not just a number comparison.
- **Gates rot.** A baseline recorded a year ago against a set that has since
  gained records is not a comparison. Re-record deliberately, with the
  re-recording as a reviewed commit, and never as an automatic step in the gate.
- Everything here assumes a **deterministic** scorer. Sampling temperature above
  zero, an unseeded bootstrap, or a model-based grader adds run-to-run variance
  that must go into the noise floor, or the gate flakes and gets switched off.
- A gate that fails constantly is worse than none, because the response is
  always to bypass it. If it fires on noise, the fix is a bigger set or a wider
  tolerance -- decided once, in writing -- not a bypass that becomes permanent.

## Cards

### 1. [failure] Your eval gate compares the candidate's headline F1 against the baseline's and blocks on a drop. Which regression class does it pass?

**Answer:** A change that destroys one field while improving others -- the
average survives, so the gate never fires.

**Why:** Aggregation is what hides it. Per-field checks with a validity floor
catch it; a headline threshold structurally cannot, because the information was
averaged away before the comparison.

**Boundary:** Also watch complete-record accuracy over the full denominator. A
change that shifts failures into schema violations improves every per-field score
by shrinking `n_scored`.

**Tags:** `evaluation` `failure` `general-principle`

---

### 2. [mechanism] Why must an eval gate's baseline be a recorded artifact rather than recomputed at gate time?

**Answer:** Because a baseline recomputed from current code *is* the candidate,
so the comparison is against itself and no regression can ever be detected.

**Why:** The gate's whole function is to compare two points in time. That needs
one of them pinned -- scores committed with a date and a git sha, on a frozen set
with a recorded seed.

**Boundary:** Recorded baselines go stale as the set grows. Re-record
deliberately as a reviewed commit, never as an automatic step inside the gate.

**Tags:** `evaluation` `mechanism` `general-principle`

---

### 3. [decision] Your gate's tolerance is 0.10 and your set's bootstrap noise floor for that field is +/-0.106. A candidate regresses the field by 0.028 and passes. Is the tolerance wrong?

**Answer:** No -- the set is too small. No tolerance catches a 0.028 regression
when noise alone moves the metric by 0.106; tightening below the noise floor
makes the gate fail on unchanged code.

**Why:** A gate can only defend against regressions larger than its set's noise
floor. Tolerance choice is downstream of set size, not a substitute for it.

**Boundary:** Decide the smallest regression you must catch, size the set to
that, and record the resulting blind spot explicitly -- an unmeasured blind spot
gets mistaken for a guarantee.

**Tags:** `evaluation` `decision` `general-principle`
