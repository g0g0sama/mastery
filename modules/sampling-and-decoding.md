# Sampling and decoding

**Micro module.** One mechanism, one experiment, three cards. Runs against
[model-interface-lab/](model-interface-lab/).

**Capability:** sampling and decoding (Layer 3, Aware -> Independent). Map
evidence to graduate: "Show how decoding params change schema-validity rate."

**Gate:** probability. Learned here rather than before, per the map's note on
Layer 2.

---

## The problem

`temperature` has a default and nobody remembers choosing it. Then an extraction
pipeline starts returning malformed JSON a few percent of the time and the
debugging goes to the prompt, because the prompt is the thing that looks like it
is about content.

## The wrong model

**"Temperature controls creativity."**

It controls the sharpness of the distribution the sampler draws from -- nothing
else. The word *creativity* smuggles in a value judgment and hides the mechanism,
which is that raising temperature raises the probability of every token the model
thought was second-best, including the ones that break a JSON structure it was
otherwise about to close.

## The mechanism

The model emits a distribution over the vocabulary at every position. Decoding is
how you pick from it:

- **greedy / temperature 0** -- take the argmax. No sampling noise.
- **temperature `t`** -- divide the logits by `t` before the softmax. `t < 1`
  sharpens, `t > 1` flattens.
- **top-p (nucleus)** -- keep the smallest set of tokens whose mass sums to `p`,
  renormalize, sample. Bounds the tail without bounding the head.
- **top-k** -- keep the k most likely. Cruder, since the right k depends on how
  peaked the distribution already is.

Structural tokens -- `{`, `"`, `,`, `}` -- usually have very high probability at
the positions where they belong. Raising temperature is precisely the operation
that gives their competitors a chance.

## The experiment

```powershell
cd modules\model-interface-lab
python decoding_lab.py
```

```text
     T   valid (free-form)   correct   valid (constrained)   correct
   0.0               0.900     0.757                 1.000     0.772
   0.2               0.765     0.625                 1.000     0.830
   0.5               0.552     0.420                 1.000     0.820
   0.8               0.417     0.275                 1.000     0.807
   1.0               0.268     0.100                 1.000     0.762
```

Free-form validity collapses from 0.900 to 0.268 and correctness from 0.757 to
0.100. Constrained validity does not move and cannot -- the decoder forbids the
failure.

**The lab is explicit that its constrained-correctness column is
temperature-independent by construction**, so the wiggle there is noise rather
than a finding. In reality temperature does move content under a schema, because
the constraint applies to the token grammar and not to the distribution over
values. This lab can show that the free-form collapse is mostly packaging; it
cannot size the content effect, and neither can any lab that is not your corpus.

**Where sampling pays for itself.** Self-consistency -- three samples at `T=0.7`,
majority vote per field -- against one greedy sample:

```text
strategy                       correct       $/doc   $/accepted
greedy, 1 sample                 0.750    0.001160     0.001546
majority of 3 @ T=0.7            0.875    0.003493     0.003992
```

Eight documents, so that gap is one record: a direction, not a result. What the
table does establish without statistics is the denominator. Three calls cost 3x,
so voting must be compared against spending the same money on one call to a
better model -- and on this fixture the better model wins that comparison.

**The recipe that looks right and is not.** Sample greedily; on a validation
failure, resample with temperature to shake it loose:

```text
40 invalid first attempts, 33 recovered by resampling (0.825)
For comparison, repair() alone recovers 36 of those 40 at zero additional calls.
```

Resampling works, and it is the expensive way to fix a formatting problem.
Escalate on the failure **class**: packaging goes to `repair()`, shape goes to
constrained decoding, semantics goes to a better model or a different prompt, and
only genuine nondeterminism goes to a resample.

## Boundary

- **Temperature 0 is not determinism.** Floating-point non-associativity under
  batching, expert routing that depends on who else is in the batch, and silent
  model updates all move the output. Greedy decoding removes the sampling noise
  and nothing else. Never build a cache key, an idempotency key, or a test
  assertion on "the same prompt returns the same string".
- **Set temperature and top-p together or set one.** Both narrow the candidate
  set, and tuning them independently produces a search over a space where the
  two axes interact, on an eval set that usually cannot resolve either.
- **Per-task, not per-application.** Extraction wants `T=0`; a paraphrase
  generator for adversarial eval examples ([adversarial-examples.md](adversarial-examples.md))
  wants the opposite. One global setting is a decision not to have made a
  decision.
- **When an eval score moves and nothing changed**, the null hypothesis is
  provider drift. The instrument is a pinned model version plus a stored prompt
  hash ([prompt-versioning.md](prompt-versioning.md)).

## Cards

### 1. [mechanism] Your extraction pipeline returns malformed JSON a few percent of the time. Before touching the prompt, which decoding parameter do you check and why?

**Answer:** Temperature. Structural tokens like `{`, `,` and `}` are
high-probability at the positions where they belong, and temperature is exactly
the parameter that gives their competitors a chance.

**Why:** In the lab, free-form schema-validity fell from 0.900 at `T=0` to 0.268
at `T=1.0` with no change to the prompt. Most of that loss is packaging, not
comprehension.

**Boundary:** Constrained decoding makes validity temperature-proof by
construction, which removes the symptom rather than the cause -- content quality
still moves with temperature, where you can no longer see it.

**Tags:** `decoding` `mechanism` `general-principle`

---

### 2. [misconception] Why is `temperature=0` not the same as a deterministic API?

**Answer:** Greedy decoding removes sampling noise only. Floating-point
non-associativity under batching, expert routing that depends on batch
composition, and unannounced model updates all still change the output.

**Why:** Anything built on byte-identical responses -- cache keys, idempotency
keys, exact-match test assertions -- is therefore unsound, and fails
intermittently in a way that looks like a different bug.

**Boundary:** It does make outputs *stable enough* for evaluation, which is why
`T=0` is still the right default for extraction. Stability is a statistical
claim; determinism is not available.

**Tags:** `decoding` `misconception` `general-principle`

---

### 3. [decision] An extraction returns invalid JSON. Your options are: resample at higher temperature, repair the text, switch to constrained decoding, or use a bigger model. How do you choose?

**Answer:** By failure class. Packaging (fences, prose, trailing commas) goes to
repair; shape (missing field, wrong type) goes to constrained decoding;
semantics (plausible wrong value) goes to a better model or a different prompt.
Resampling is only for genuine nondeterminism.

**Why:** In the lab, resampling recovered 33 of 40 invalid outputs at one extra
call each, and a 30-line repair pass recovered 36 of the same 40 for free --
because most of them were packaging.

**Boundary:** This requires classifying the failure before reacting to it, which
means a validator that reports codes rather than a boolean
([deterministic-graders.md](deterministic-graders.md)).

**Tags:** `decoding` `decision` `general-principle`
