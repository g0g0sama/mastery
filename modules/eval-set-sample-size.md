# Eval set sample size and the bootstrap interval

**Micro module.** One mechanism, one experiment, three cards. Serves step 8 of
[../current-cycle.md](../current-cycle.md) and stretch task 3 of
[extraction-eval-sets/lab/](extraction-eval-sets/lab/).

**Capability:** confidence intervals and significance (Layer 2), learned inside
the module that needs it rather than as a cycle of its own -- per the map's own
sequencing note.

---

## The problem

You score two extractors on your 50-record set. One gets 0.87 F1, the other 0.90.
Three points. You ship the second one and write the ADR.

You have no idea whether those three points exist.

## The wrong model

**"A bigger number on the eval set means a better system; the set is the ground
truth, so the comparison is exact."**

The arithmetic *is* exact -- 0.90 really is larger than 0.87 on those 50
records. The error is treating the 50 records as the population rather than as a
sample drawn from it. What you want to know is which system is better on the
documents you have not scored, and for that the question is whether a different
50 records would have ranked them the same way.

The tempting corollary is worse: "50 is a decent sample size." Fifty is a decent
size for *catching a broken field*, where the effect is 40 points. It is nowhere
near enough to adjudicate three.

## The mechanism

Resample the eval set from itself, with replacement, a few thousand times. Score
every resample. The spread of those scores estimates how much your metric would
move if you had drawn a different set of documents of the same size.

Two details do the real work:

**Resample records, not extracted items.** The document is the sampling unit --
you drew documents, and errors cluster inside them. A document with seven actors
contributes seven correlated outcomes, and treating them as seven independent
draws produces an interval that is too narrow, which is the direction that gets
things shipped.

**Pair the comparison.** Use the *same* resampled indices for both systems and
take the difference inside each resample. Both systems then see the same
documents in every draw, so the shared difficulty of those documents cancels and
the interval is on the thing you actually care about -- the difference. Building
two independent intervals and checking whether they overlap tests a different
and weaker question.

## The experiment

`extraction-eval-sets/lab/interval.py`. Requires the lab's stubs to be
implemented (`python verify.py` at 10/10).

On the 12-record set, `model_b` leads `model_a` on actors F1 by 0.0084.

**Predict before running: the 95% interval on that difference, and the fraction
of resamples in which model_a wins.** Write both down.

```powershell
cd modules\extraction-eval-sets\lab
python interval.py
```

Actual:

```text
model_a actors F1 = 0.8696
model_b actors F1 = 0.8780
observed difference (B - A) = +0.0084

paired bootstrap, 10000 resamples of n=12 records, seed 20260803
  95% interval on the difference: [-0.0909, +0.1875]
  fraction of resamples where A >= B: 0.483

  bootstrap standard error at n=12: 0.0706
  projected SE at n=50    -> 95% half-width ~0.0678
  projected SE at n=200   -> 95% half-width ~0.0339
  projected SE at n=1000  -> 95% half-width ~0.0152
```

The interval spans zero by a wide margin, and `model_a` wins 48.3% of the
resamples. The observed lead is a coin flip.

The projection is the part with teeth. Standard error falls with `1/sqrt(n)`, so:

- at **n = 50** the 95% half-width on this metric is still about **0.068**. A
  three-point difference is not resolvable. A twenty-point one is.
- resolving three points needs a half-width under 0.03, which lands somewhere
  past **n = 250**, and comfortably at n = 1000.

This is a direct constraint on the open cycle, and it is better to know it now
than after the ADR: **the 50-record set can prove a field is broken and cannot
adjudicate a small model-versus-model difference.** That is not a reason to
label 1000 records. It is a reason to write the ADR in terms the set can
support, and to reach for a bigger effect -- a fixed field, a removed failure
class -- rather than a tuned prompt.

## Boundary

- The projection assumes the same error structure at larger `n`. New documents
  usually bring new failure modes, so treat it as a lower bound on the records
  needed.
- The bootstrap estimates **sampling** variability only. It says nothing about
  label error, policy drift, or a holdout you have already looked at -- all of
  which bias the estimate rather than widen it.
- Percentile intervals on a 12-record set are themselves noisy. The honest
  reading here is "spans zero decisively", not "[-0.0909, +0.1875]" to four
  places.
- Seed the RNG and record the seed. An interval you cannot reproduce is not
  evidence, and the seed belongs in the ADR with the numbers.

## Cards

### 1. [decision] Your two extractors differ by 3 F1 points on a 50-record eval set. Can you conclude the higher one is better?

**Answer:** No. At n=50 the 95% half-width on a metric like this is roughly
0.07 -- more than twice the effect -- so a different 50 records could easily
reverse the ranking.

**Why:** Standard error falls with `1/sqrt(n)`, so resolving a 3-point
difference needs a few hundred records, not fifty.

**Boundary:** Fifty records is entirely sufficient for large effects -- a field
that dropped 40 points, a validity failure, a broken match rule. Size the set to
the effect you intend to detect, and state that effect before labelling.

**Tags:** `evaluation` `decision` `general-principle`

---

### 2. [mechanism] When bootstrapping a confidence interval for an extraction metric, what is the unit you resample, and why does it matter?

**Answer:** Records, not extracted items -- the document is the sampling unit
you actually drew from.

**Why:** Errors cluster within a document, so items from the same record are
correlated. Resampling items treats them as independent draws and produces an
interval that is too narrow, which is the direction that gets a change shipped.

**Boundary:** If your true unit of interest is per-item -- a per-entity SLA, for
instance -- the metric itself should be defined per item, and the clustering
handled explicitly rather than by choosing a convenient resampling unit.

**Tags:** `evaluation` `mechanism` `general-principle`

---

### 3. [implementation] You are bootstrapping the difference between two systems on the same eval set. What must be true of the indices you draw in each resample?

**Answer:** Both systems must be scored on the **same** resampled indices, and
the difference taken inside each resample.

**Why:** Pairing cancels the shared difficulty of the drawn documents, so the
interval is on the difference rather than on the sum of two independent noises.
It is substantially tighter and it answers the question you asked.

**Boundary:** Checking whether two separately-computed intervals overlap is a
different, weaker test -- non-overlapping intervals imply a difference, but
overlapping ones do not imply its absence.

**Tags:** `evaluation` `implementation` `general-principle`
