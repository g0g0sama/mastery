# Prompt versioning and regression

**Micro module.** One mechanism, one experiment, three cards. Runs against
[model-interface-lab/](model-interface-lab/).

**Capability:** prompt versioning and regression (Layer 4, `-` -> Independent).
Map evidence to graduate: "A prompt change gated by an eval run, with the diff
recorded."

**Gate:** evaluation. Met by the Layer 5 modules; this is where they get used on
something other than an eval set.

---

## The problem

Someone improves the prompt. The improvement is obvious on reading it. It ships,
because there is no mechanism by which it could not.

## The wrong model

**"Review the diff."**

Here is the diff. One sentence, addressing the single most common extraction bug
in this corpus -- the fetch date substituted for the event date:

```text
v1: "... personnel. Sentence: "
v2: "... personnel. The date must be the one stated in the sentence,
     not today's date. Sentence: "
```

Read it and you would approve it. Run it:

```text
v1  record accuracy 0.7958
v2  record accuracy 0.8562
delta +0.0604
```

Still approve it. Now slice it:

```text
slice                     v1      v2    delta
investment             0.817   0.933   +0.117
personnel              0.867   0.867   +0.000
production_change      0.808   0.858   +0.050
regulation             0.750   0.600   -0.150  <-- regression
sanction               0.633   0.933   +0.300
supply_agreement       0.867   0.867   +0.000
```

The aggregate went up and one slice went down hard. **That is what an added
instruction usually does**: it moves probability mass toward the case it names and
away from the cases it does not. `regulation` events are the ones where the event
date genuinely *is* the publication date -- a ministry announces a rule on the
day the article runs -- so the new sentence tells the model to distrust the right
answer.

## The mechanism

A prompt is a component with a version, a test suite, and a release decision. The
three parts, in the order they are usually skipped:

1. **A gate that can fail.** Two rules over the same numbers give opposite
   answers:

   ```text
   aggregate rule:      PASS
   aggregate + slices:  FAIL  ['slice regulation -0.1500']
   ```

   Which is right depends on a policy you must decide in advance and write down:
   is a large loss on one document class acceptable for a small gain everywhere?
   Sometimes yes -- but that has to be a decision someone made, not the
   accidental output of averaging.

2. **A stamp on every produced record.** `sha256(prompt)[:12]`, beside the pinned
   model version from [routing-and-fallback.md](routing-and-fallback.md) and the
   eval-set version from [eval-set-versioning.md](eval-set-versioning.md). Three
   hashes make a score attributable; two make it an anecdote.

3. **An ADR.** Context, what was measured, the decision, and the condition that
   would reopen it. `decisions/TEMPLATE.md` is the shape.

## The experiment

```powershell
cd modules\model-interface-lab
python prompt_lab.py
```

**Predict before running:** you have read the diff. Write down the aggregate
delta and the sign of the change on `regulation` documents specifically.

The lab states its own size limit plainly: eight documents across six slices
means each slice is one or two documents sampled 60 times. That measures the
model's variance on those documents and says nothing about the slice as a
population. **The mechanism is the lesson; the number is not transferable.** A
real slice gate needs enough documents per slice to survive
[eval-set-sample-size.md](eval-set-sample-size.md) -- which is the expensive part
of doing this properly, and the reason most teams gate on the aggregate.

## Boundary

- **Hashing the template is not hashing the system.** The prompt text can be
  byte-identical while an interpolated variable, a retrieved passage, or a tool
  description has changed. Hash the **rendered** prompt for one fixed probe
  input. This is the same blind spot
  [eval-set-versioning.md](eval-set-versioning.md) found from the data side, and
  it is worth noticing that it recurs -- content hashing catches edits, never
  behaviour.
- **Prompt changes and model changes must not ship together.** Two variables, one
  measurement, no attribution. If the provider repointed an alias in the same
  week, you have three.
- **Slice definitions are part of the gate.** A slice nobody defined cannot
  regress visibly. Define them from the error taxonomy
  ([error-taxonomy.md](error-taxonomy.md)), which is built from failures rather
  than from what is easy to group by.
- **A prompt registry answers "what produced this row".** Which prompt, which
  model, which decoding parameters -- Layer 9's row. It is cheap while there is
  one prompt and unrecoverable once there have been ten.
- **Instructions are not free even when they help.** Every sentence added is
  input tokens on every request forever ([tokenization.md](tokenization.md)), and
  a longer prompt dilutes the instructions already there.

## Cards

### 1. [scenario] A prompt change improves aggregate accuracy by six points on your eval set. What do you check before shipping it?

**Answer:** The per-slice deltas. An added instruction moves probability mass
toward the case it names and away from the cases it does not.

**Why:** In the lab a date instruction gained +0.06 overall and lost 0.15 on
regulation documents -- exactly the class where the event date legitimately *is*
the publication date, so the new sentence taught the model to distrust the right
answer.

**Boundary:** Slices need enough documents each to resolve the effect. With one
or two documents per slice you are measuring model variance on those documents,
not the slice.

**Tags:** `prompt-versioning` `evaluation` `scenario` `general-principle`

---

### 2. [failure] Your prompt file's hash is unchanged and behaviour has changed. Name three causes.

**Answer:** An interpolated variable rendered differently; a retrieved passage
inserted into the template changed; a tool description or system preamble outside
the template was edited.

**Why:** Content hashing catches edits to the artifact you hashed and nothing
else. The prompt the model saw is the rendered string, and that is what has to be
hashed -- for a fixed probe input, so the hash is comparable across runs.

**Boundary:** A fourth cause is not yours at all: the provider repointed a model
alias. That is why the model version is stamped separately, and why prompt and
model changes must not ship in the same release.

**Tags:** `prompt-versioning` `failure` `general-principle`

---

### 3. [decision] Your eval gate says an aggregate rule passes and a per-slice rule fails on the same run. How do you resolve it?

**Answer:** With a policy decided in advance and written down: whether a large
loss on one document class is acceptable in exchange for a small gain everywhere.

**Why:** Both rules are correct arithmetic on the same numbers. The choice
between them is a product decision about who is allowed to be worse off, and
letting it be resolved implicitly by whichever rule the CI job happens to run is
a decision made by accident.

**Boundary:** "Ship with a routing exception" is often the honest third answer --
route the regressing slice to the old prompt, record that in the ADR, and revisit
when the slice has enough labelled data to gate properly.

**Tags:** `prompt-versioning` `evaluation` `decision` `general-principle`
