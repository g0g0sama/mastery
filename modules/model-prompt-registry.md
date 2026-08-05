# Model and prompt registry

**Micro module.** One mechanism, one experiment, three cards. Runs against
[ops-lab/](ops-lab/).

**Capability:** Model and prompt registry (Layer 9, - -> Working). Map evidence:
"Which prompt and model produced a given stored record."

---

## The problem

The map row is a query, so this module runs it. Sixty days of records, a release
timeline with a canary rollout, and one provider-side change that no deploy
accompanied — then five levels of stamping, measured on whether each one can
actually answer the question.

## The mechanism

**What each level of stamping buys.** 6,000 records, five distinct behaviours
actually in play:

```text
stamped with              distinct stamps   records uniquely attributable   share
nothing                   1                 0                               0.0%
model name                1                 0                               0.0%
model + prompt name       2                 1552                            25.9%
+ prompt and param sha    3                 1552                            25.9%
full declared stamp       4                 3800                            63.3%
```

A prompt *name* is worth 25.9% because `v2` covered three releases differing in
decoding parameters, schema version and code. Adding the two hashes buys nothing
on this timeline — worth knowing, because it is the fix that feels like the
answer — since the releases they separate were already separated by name.

The remaining 37% is the module:

```text
release     days live         spans the reskill?    attributable?
r1          0-15              no                    yes
r2          12-29             no                    yes
r3          30-51             YES                   NO
r4          52-59             no                    yes
```

Exactly the release that was live on both sides of day 45, when the provider
changed what `mid-1` resolves to. The full declared stamp names every field the
service controls, and this change was made on the other side of the boundary,
with no deploy, no config change, and no field to record it in. **Identity by
declaration cannot detect a change nobody on your side declared.**

**The fingerprint that is taken rather than declared.** Push a fixed 24-item
probe set through the configuration and hash the outputs:

```text
change                              model name  prompt name  prompt sha  params sha  behaviour
prompt file edited, still called v2 -           -            CAUGHT      -           CAUGHT
prompt version changed (v2 -> v1)   -           CAUGHT       CAUGHT      -           CAUGHT
temperature 0.0 -> 0.7              -           -            -           CAUGHT      CAUGHT
constrained decoding turned on      -           -            -           CAUGHT      CAUGHT
provider reskills the alias         -           -            -           -           CAUGHT
```

Read the columns. The prompt hash catches prompt changes, including the in-place
edit that the name misses — the most ordinary change on the list. The params
hash catches decoding changes and is the field nobody stores, which is why a
temperature change gets diagnosed as a model regression. Only the behavioural
hash catches all five, because it is the only detector that runs the system
instead of describing it.

This is the third time this repository has landed on that shape.
[eval-set-versioning.md](eval-set-versioning.md) found that hashing the policy
source file missed a runtime normalizer swap and needed a probe set pushed
through the normalizers; [reproducible-builds.md](reproducible-builds.md) found
a byte-identical artifact behaving differently. **Hash what the system does on a
fixed input, not what its configuration says.**

**The incident query.** "The v2 prompt had a bug between day 12 and day 30 —
which stored records are affected?"

```text
method                    selected    true positives  precision   recall
date range                1800        1448            0.804       1.000
stamp query               1448        1448            1.000       1.000

records written during the 4-day canary: 400, of which 352 were served
by the previous release
date-range false positives: 352
```

A date range is a proxy for a deploy, and a deploy is not an instant: canary,
blue-green, a stalled rollout, a worker pool draining slowly, a queue holding
requests built against the old config. The cost of being wrong is not the query
— it is that the remediation (reprocess, refund, notify, retract) runs against
the selected set. False positives reprocess records that were fine; false
negatives leave bad ones in the table.

**What a registry does not give you.**

```text
re-execution                                        identical records
same config, same day, same inputs                  1.000
same config, replayed after the alias moved         0.810
same config at temperature 0.7, two draws           0.730
```

Three rows, three different reasons: nothing changed (the easy case, and the
only one most teams test); the alias moved, so the stamped configuration no
longer resolves to what it resolved to, permanently once a model is retired; and
sampling above temperature 0 makes two draws of the *same* configuration
disagree by design.

So if a record has to be defensible later, store the **output and its
provenance**, not a recipe for regenerating it. And the stamp belongs in a
config table with an integer key on the record — 149 bytes inline against 8 for
a foreign key, with four distinct configurations across sixty days. The
cardinality is per release, not per record.

## The experiment

```powershell
cd modules\ops-lab
python registry_lab.py    # ~2 s
```

## Boundary

- **The provider reskill is declared by the fixture.** What is real is the
  measurement that no declared field detects it and a probe set does. Whether
  your provider does this, how often, and whether it announces it is a question
  about your provider.
- **The behavioural hash costs a probe run per deploy per day** and is only as
  good as the probe set: probes that do not exercise the changed slice will not
  move. It detects *that* behaviour changed, never *how much it matters* — that
  is the eval set's job, and the two are complementary instruments.
- **Attribution here is per record.** Attributing an *aggregate* (a dashboard
  number, a weekly quality figure) to a configuration additionally needs the
  traffic mix, because a shifting mix moves an average with every configuration
  held constant — see [metrics-and-cost-monitoring.md](metrics-and-cost-monitoring.md).
- **Nothing here addresses prompt *management***: review, approval, staged
  rollout of a prompt change. This module is about identity after the fact.

## Cards

### 1. [misconception] Every record stores the model and the prompt name, so we know what produced it.

**Answer:** A name is not a version. In the lab, model plus prompt name uniquely
attributed 25.9% of records, and the full declared stamp — model, prompt name,
prompt hash, params hash, code, schema, index — only reached 63.3%. `v2` covered
three releases differing in decoding parameters, schema and code, and survived an
in-place edit of its own file without changing.

**Why:** Attribution needs the tuple of everything that can change output
independently, and each element has to be a content hash rather than a label.

**Boundary:** Even the full stamp misses a change made on the provider's side of
the boundary. The residual 37% was exactly the one release that was live on both
sides of the day the alias moved.

**Tags:** `registry` `misconception` `ai-specific`

---

### 2. [decision] How do you version a prompt: a file name, a git sha, or something else?

**Answer:** A content hash of the prompt text *and* a hash of the decoding
parameters, plus a behavioural fingerprint — a fixed probe set run through the
configuration, hashed. In the lab the prompt hash caught both prompt changes and
neither decoding change; the params hash caught both decoding changes and no
prompt change; only the behavioural hash caught all five, including the
provider-side one.

**Why:** A prompt is not the unit of behaviour. The unit is prompt text ×
decoding parameters × the model actually serving the alias.

**Boundary:** The behavioural hash only detects that behaviour moved, not
whether it moved for the better, and it is blind to changes the probe set does
not exercise. It costs one probe run per deploy per day, which is why it is
usually skipped and why it is the only thing that caught the silent change.

**Tags:** `registry` `decision` `ai-specific`

---

### 3. [failure] A bad prompt shipped on Tuesday and was fixed on Friday. Which stored records need reprocessing?

**Answer:** Not "the ones written between Tuesday and Friday". In the lab a date
range selected 1,800 records for 1,448 truly affected — 352 false positives,
precision 0.804 — because the release went out as a four-day canary and the
previous release kept serving most traffic. The stamp query selected exactly the
affected set.

**Why:** A date is a proxy for a deploy, and a deploy is a gradual, partial,
sometimes-reverted event.

**Boundary:** Precision matters here because the selected set is what the
remediation runs against. And the registry answers *which* records, not *what
they would say now*: replaying them reproduced 81% after the model alias moved
and 73% at temperature 0.7. Attribution is not reproduction.

**Tags:** `registry` `failure` `ai-specific`
