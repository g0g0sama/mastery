# Extraction eval sets and metrics

**Learning target:** After this module you will be able to write a matching
policy that states its own costs, compute per-field precision and recall over
set-valued and scalar fields, choose between micro and macro averaging with a
reason, separate invention from omission in a system's failures, and say which
number a shipping decision should rest on.

**Assumes:** task definition (Aware), SQL and schema design (Working). Both met
per [../../capability-map.md](../../capability-map.md).
**Versions:** CPython 3.14, stdlib only. No third-party packages, no network, no
model calls.
**Time:** ~40 min explainer, ~90 min lab, cards ongoing.

**Size: standard.** Fixed by [../../current-cycle.md](../../current-cycle.md),
not chosen here, and the cycle is right to fix it: this is the capability every
later cycle's numbers are read against, and a micro module could carry the
mechanism but not the six traps, each of which is a way to close a future cycle
on a wrong number.

## Concepts

Ordered by dependency. Nothing is used before it is introduced.

1. **The policy is the instrument** -- a person decided what counts as a match,
   and that decision moves the score without touching the system.
2. **Schema validity is a gate, not a quality metric** -- and the schema is
   looser than the policy, so it is blind to policy violations.
3. **The match rule for each field** -- exact, normalized, or linked, applied to
   both sides at scoring time.
4. **Set-valued precision and recall** -- scalars as sets of size 0 or 1;
   `tp/fp/fn` as the vocabulary of extraction error.
5. **Micro versus macro averaging** -- items weighed equally, or documents.
6. **Empty versus wrong** -- the split that separates the confabulator from the
   abstainer after F1 has hidden the difference.
7. **Complete-record accuracy** -- acceptance as a conjunction over fields;
   brutal, correct, and useless for diagnosis.
8. **The holdout is spent by looking** -- contamination has no partial credit.
9. **Cost per accepted record** -- the denominator that decides architecture.

Concept 8 appears in the explainer and the cards but not the lab: a holdout
cannot be exercised in a fixture you are free to re-run. It is exercised for real
at step 4 of the cycle.

## Order

For the real Sinoscope transfer, follow the
[project workbook](workbook/README.md) in the same order. It records source
reading, policy, dataset and holdout protocol, results, and decision handoff
without treating the fixture as a real evaluation set.

Read [explainer.md](explainer.md) -> answer `lab/predict.py` in writing -> run
[lab/](lab/) -> run all three breaks, predicting each first -> review
[cards.md](cards.md) -> a week later, re-derive the micro/macro gap and the
`0.9^4` arithmetic from memory before re-reading anything.

**The primary sources come first.** The three named in
[../../current-cycle.md](../../current-cycle.md) are not summarized anywhere in
this module and are not replaced by it. Read them, log the surprises in the
cycle's log, and read this as a companion.

## Evidence contract

This module is not the deliverable. The cycle's contract in
[../../current-cycle.md](../../current-cycle.md) governs, and this module
contributes to conditions 3 and 4 only. Producing these files satisfies nothing.

For the module specifically -- finished when all five hold:

1. **Implemented** -- `lab/verify.py` reports 10/10, and `policy.py`'s header has
   gained at least one decision you wrote yourself with its cost stated.
2. **Verified** -- `python scoring.py` produces byte-identical output on two
   consecutive runs, and you can name the one place where set iteration order
   could have leaked into the report and say why it does not.
3. **Diagnosed** -- all three breaks run, each with a written prediction made
   first, and break 1's ranking inversion either predicted or logged in
   [../../failure-log.md](../../failure-log.md) with the wrong model named.
4. **Explained cold** -- a week later, without notes: why `model_a` and `model_b`
   have the same F1 and the same record accuracy, and which two numbers separate
   them.
5. **Used in a real decision** -- the `actors` match rule for the real Sinoscope
   set is chosen and written into that set's labelling policy, with the recall
   ceiling it imposes stated as the argument for entity linking later.

Condition 5 is the one that can actually fail, and it is the one that carries the
cycle.

## Project transfer

- **Where:** the Sinoscope extraction path -- the stage that writes event
  records. Not inspected here: this repository holds the learning system only, so
  every claim in this module about Sinoscope comes from
  [../../current-cycle.md](../../current-cycle.md), not from reading its code.
  Cite real paths when you write the ADR.
- **Change:** the scorer built in `lab/` moves to the Sinoscope repository
  alongside the 50-record set, with `policy.py`'s header rewritten for the real
  labelling decisions -- vocabulary, `actors` match rule, tie-breaks -- and
  versioned next to the labels rather than inside the scoring script.
- **Demonstrated by:** per-field micro and macro scores plus the empty-vs-wrong
  split for the rules baseline and the model extraction, on the frozen holdout,
  scored once; and the `n_scored` denominator printed beside every field score.
- **Recorded in:** `decisions/0001-*.md` per the cycle, plus the labelling
  policy in the eval set's own README -- which is the artifact that outlives the
  numbers.

## Files

```text
README.md      this file
explainer.md   Layer A -- the mechanism and the production failure modes
lab/           Layer B -- 12-record fixture, 7 stubs, 3 seeded failures
  README.md    setup, five steps, verification, break-it, stretch, cleanup
  gold.py      hand-labelled records
  predictions.py  three systems over the same documents
  policy.py    the matching policy      <- you implement 2 functions
  scoring.py   the scorer               <- you implement 5 functions
  predict.py   five questions, answered in writing before anything runs
  verify.py    10 checks
  break_it.py  3 seeded failures, prediction required first
cards.md       Layer C -- 14 cards
workbook/      Project-transfer templates for real Sinoscope work
  README.md    ordered checklist and evidence map
  source-reading.md  primary-source constraints and design consequences
  labelling-policy.md  field policy, match rules, and change log
  dataset-holdout-register.md  dataset version, split, and reproducibility stamps
  results-and-handoff.md  measurements, failure taxonomy, and ADR handoff
```
