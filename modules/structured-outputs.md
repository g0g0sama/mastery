# Structured outputs and JSON schema

**Micro module.** One mechanism, one experiment, three cards. Runs against
[model-interface-lab/](model-interface-lab/).

**Capability:** structured outputs and JSON schema (Layer 4, Aware -> **Deep**).
Map evidence to graduate: "Schema-validity rate measured, failure modes
taxonomized." Both are below. What is *not* below is the graduate evidence
itself, which needs the provider's real constraint surface -- read the vendor's
structured-output reference before trusting any number here, because the JSON
Schema subset they support is smaller than the spec and that subset is the
mechanism.

**Gate:** typing. Met by `../patterns/06-types-and-interfaces`.

---

## The problem

The model returns text. Your database takes rows. Between them sits a parse that
fails a few percent of the time, and each failure costs the full price of the
call plus a retry.

So you turn on schema-constrained decoding, watch schema-validity go to 100%, and
put that number on a dashboard. This module is about what that number stopped
measuring.

## The wrong model

**"Valid means correct."**

The reason it is tempting is that in every other part of the stack it very nearly
is. A row that satisfies its column types is usually a row you can use. A request
that satisfies its schema is usually a request you can serve. Validation has been
a proxy for correctness for so long that the substitution is invisible.

With a generative model the substitution breaks, because the schema is enforced
by the **decoder**, not by the model's understanding. A constrained decoder will
happily produce a perfectly-typed record about a document it misread.

## The mechanism

Three layers of failure, and they need three different instruments:

| Layer | Example | Detected by |
|---|---|---|
| **Syntax** | markdown fence, trailing comma, prose preamble | the parser |
| **Shape** | missing required field, `confidence` as a string, enum drift | the validator |
| **Semantics** | plausible wrong `event_type`, fetch date as event date | a grader with gold |

Constrained decoding eliminates the first two **by construction**. It cannot
touch the third. And because the decoder must emit a value for every required
field, it converts a fourth thing you were relying on -- **abstention** -- into
confabulation.

## The experiment

```powershell
cd modules\model-interface-lab
python schema_lab.py
```

200 draws per cell, deterministic.

**Predict before running.** Constrained decoding takes schema-validity from
0.880 to 1.000 on the mid tier. By how much does record accuracy move?

```text
system                               parses   valid  correct  $/accepted
tiny-1 free-form                      0.935   0.895    0.540    0.000184
tiny-1 constrained                    1.000   1.000    0.590    0.000168
mid-1 free-form                       0.885   0.880    0.735    0.001603
mid-1 constrained                     1.000   1.000    0.780    0.001509
large-1 free-form                     0.955   0.950    0.900    0.006490
large-1 constrained                   1.000   1.000    0.930    0.006259
```

Validity `+0.120`, accuracy `+0.045`. The headline moves about three times as far
as the thing the headline stands for.

**Where the failures went.** The mid-tier failure census, free-form against
constrained:

```text
free-form                       constrained
clean                  0.715    clean                  0.750
location_filled        0.045    hallucinated_actor     0.095
plausible_wrong_enum   0.045    date_is_fetch_date     0.055
fenced                 0.045    location_filled        0.055
date_is_fetch_date     0.040    plausible_wrong_enum   0.045
trailing_comma         0.040
hallucinated_actor     0.035
prose                  0.030
wrong_type             0.005
```

Every mode that disappeared was **detectable without gold labels**. Every mode
that remains is valid, well-formed and wrong. That is usually the right trade and
it is never a free one.

**Abstention becomes confabulation.** 800 draws, because this effect is smaller
than the last one:

```text
system                       omitted a field   filled it wrongly
mid-1 T=0.0 free-form                  0.006               0.120
mid-1 T=0.0 constrained                0.000               0.180
mid-1 T=0.6 free-form                  0.030               0.152
mid-1 T=0.6 constrained                0.000               0.158
```

Omission goes to exactly zero -- it has to, a required field cannot be absent --
and wrong-fill rises. For a pipeline that writes to a database this is the most
expensive line in the lab: **a missing date is a row you can queue for review,
and a wrong date is a row nobody will ever look at again.**

**And most of the validity gap did not need a schema at all:**

```text
free-form, raw          validity 0.880
free-form, + repair()   validity 0.995
constrained             validity 1.000
```

Thirty lines of fence-stripping and trailing-comma removal recover almost all of
it, because most free-form invalidity is *packaging*, not confusion. Measure that
before adopting constrained decoding -- if repair closes the gap, what the schema
is actually buying you is the semantic change above, and you should decide
whether you want it.

**Per field, conditioned on parsing** -- the record-level number averaged this
away:

```text
field            free-form   constrained
event_type           0.949         0.955
actors               0.960         0.905
date                 0.960         0.945
location             0.966         0.975
```

Two fields go **down** under the schema. `actors` loses most: forced to emit a
non-empty array, the model appends a plausible extra organization.

## Boundary

- **Nullable fields give abstention back.** `date` and `location` typed as
  `["string", "null"]`, with a policy that null means *not stated in the source*,
  restores the distinction the schema removed. This is a schema **design**
  decision, not a decoding one, and it is the cheapest fix in this module.
- **A schema cannot express provenance.** "This date must be the one in the
  sentence, not the one in the metadata" is not a type constraint. It is a
  grader ([deterministic-graders.md](deterministic-graders.md)) or a field-level
  span requirement that makes the model quote its source -- which costs output
  tokens, at 5x input price ([tokenization.md](tokenization.md)).
- **The provider's subset is the real constraint surface.** `pattern`,
  `additionalProperties`, `minItems`, nested `oneOf` -- support varies, and an
  unsupported keyword is usually ignored silently rather than rejected. The
  validator in `task.py` is deliberately hand-written so this is visible; in
  production, validate again on your side, always.
- **Violation codes, not messages.** Section 6 counts codes because a code is
  countable and a message is only readable. That census is the input to
  [error-taxonomy.md](error-taxonomy.md), which is the method for turning it into
  a taxonomy.
- **This provider is a fake** whose failure distribution is declared in
  `provider.py`. The *consequences* measured here are real arithmetic over that
  distribution; the distribution itself is a stand-in, and the module's claims
  should be re-measured against a real provider before they decide anything.

## Cards

### 1. [misconception] After enabling schema-constrained decoding, schema-validity rate goes from 88% to 100%. What has that number stopped measuring?

**Answer:** Content. The schema is enforced by the decoder, so validity becomes a
property of the decoder rather than evidence about the model's output.

**Why:** In the lab, validity rose 0.120 while record accuracy rose 0.045, and
per-field accuracy *fell* on two of four fields. A validity dashboard at 100% is
compatible with extraction quality degrading.

**Boundary:** The right pairing is schema-validity next to record accuracy and
the empty-versus-wrong split. Validity alone can only ever go up.

**Tags:** `model-interface` `structured-output` `misconception` `general-principle`

---

### 2. [failure] Under a required-field JSON schema, your extractor stops returning empty fields entirely. Why is that bad news rather than good?

**Answer:** Abstention has become confabulation. A required field cannot be
omitted, so the model fills it with something plausible instead of leaving it
out.

**Why:** In the lab, field omission went to exactly 0.000 under the schema while
wrongly-filled fields rose from 0.120 to 0.180. A missing value is a row you can
queue for review; a wrong value is a row nobody looks at again.

**Boundary:** The fix is schema design, not decoding: type the field as nullable
and define null as "not stated in the source". Then measure the empty-vs-wrong
split, which collapsing them makes a safe model look worse than a confabulating
one.

**Tags:** `model-interface` `structured-output` `failure` `general-principle`

---

### 3. [decision] Free-form JSON parses 88% of the time. Before adopting constrained decoding, what should you measure, and why?

**Answer:** The validity rate after a cheap repair pass -- strip markdown fences,
take the outermost braces, remove trailing commas.

**Why:** Most free-form invalidity is packaging rather than confusion. In the lab
repair took validity from 0.880 to 0.995 against constrained decoding's 1.000, so
the schema's real purchase was the semantic change it also causes.

**Boundary:** Repair cannot fix shape errors -- a missing required field or a
wrong type survives it -- and it must never silently "fix" a value. Repair
packaging, validate content, and keep the two steps distinguishable in the logs.

**Tags:** `model-interface` `structured-output` `decision` `general-principle`
