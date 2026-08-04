# Current cycle

**Capability:** Building a labelled eval set + extraction metrics (Layer 5)
**Opened:** 2026-08-03
**Status:** not started
**Size:** standard
**Project:** Sinoscope -- event extraction

## Why this one first

Every other AI capability on the map is unfalsifiable without it. Retrieval
changes, prompt changes, model changes, and local-inference changes all produce
the same output shape as the version before them; the only thing that
distinguishes an improvement from a regression is a fixed set with labels on it.
Starting anywhere else means every later cycle closes on an opinion.

It is also the capability with the least transferable substitute. A framework can
supply retrieval; nothing supplies a labelled Chinese-language extraction set for
your domain but you.

**Gate check:** task definition (Aware, sufficient to start), SQL and schema
design (Working). Both met. No blocking prerequisite.

## Primary sources -- read before writing any code

The module is a companion to these, not a replacement. Read first, predict, then
build.

1. Your provider's structured-output and tool-use documentation -- the actual
   constraint surface: which JSON Schema subset is supported, what happens on a
   validation failure, whether refusals are distinguishable from malformed
   output. Read the reference, not a tutorial.
2. Your provider's evaluation guidance -- the specify -> measure -> improve loop
   as the vendor describes it, including what they consider a grader.
3. One primary source on annotation quality: inter-annotator agreement and why
   single-labeller sets overstate their own accuracy. A textbook chapter or a
   dataset paper's annotation section, not a blog summary.

Record in the log below what you actually read, and one thing each source said
that you did not expect. If nothing was unexpected, you skimmed.

## Evidence contract

This cycle closes when all five are true. Not before, and not on the strength of
files produced.

1. **Implemented.** An extraction pipeline that emits a validated record for a
   Chinese-language source document, with schema violations surfaced rather than
   swallowed.
2. **Verified.** 50 or more labelled records, a frozen holdout you have not
   looked at, and a scoring script that reproduces the same numbers twice.
3. **Diagnosed a seeded failure.** Break one thing on purpose -- a field whose
   type silently coerces, a nested list flattened, a date parsed in the wrong
   locale -- predict the metric that moves, then confirm which one actually did.
4. **Explained cold.** A week later, without notes: why per-field precision and
   recall locate a problem that whole-record accuracy hides, and when the reverse
   is true.
5. **Used in a real decision.** One Sinoscope change made or rejected because of
   a number from this set, recorded as an ADR in [decisions/](decisions/).

## Scope -- what is being labelled

Fields, from the project's own schema:

```text
actors        list of normalized entity names
event_type    closed vocabulary -- define it before labelling, not during
time          the event's time, not the article's publication time
location      normalized, with the granularity actually available
claims        what the source asserts, separated from what it implies
source        url + fetch time + the span each field came from
confidence    the model's, and separately, the labeller's
```

Two decisions to make before the first label, because changing them afterwards
invalidates the set:

- **Is `event_type` closed or open?** A closed vocabulary is scoreable today and
  wrong at the edges. An open one is honest and needs a matching policy before it
  can be scored at all.
- **What counts as a correct `actors` match?** Exact string, normalized form, or
  linked entity. This single choice moves your recall by a large margin, and a set
  labelled under an unstated policy cannot be re-scored later.

Write both answers into the eval set's README as a labelling policy. That
document is the deliverable that outlives the numbers.

## Metrics

| Metric | What it answers | Trap |
|---|---|---|
| Schema-validity rate | Does output parse and validate at all | Rises to 100% while content quality falls |
| Per-field precision / recall | Which field is failing | Averaging across fields hides the one that matters |
| Complete-record accuracy | Would a human accept this record | Brutal and correct; one bad field fails the record |
| Empty-vs-wrong rate | Does it hallucinate or abstain | Collapsing these makes a safe model look worse than a confabulating one |
| Cost per accepted record | Whether the approach is viable | Cost per call is the wrong denominator |

The last two are the ones usually omitted, and they are the ones that decide
architecture.

## Baseline first

Before any model call: a regex-and-rules extractor for `time` and `source`, and a
dictionary matcher for `actors`. Score it on the same set. Every later number is
read against this, and some fields may not need a model at all -- which is a
result worth having on day one rather than month three.

## Project transfer

- **Where:** Sinoscope's extraction path, the stage that currently writes event
  records.
- **Change:** extraction runs against a versioned schema and a labelled set;
  records carry field-level provenance (source span, fetch time).
- **Demonstrated by:** per-field scores before and after on the frozen holdout,
  plus the empty-vs-wrong split.
- **Recorded in:** `decisions/0001-*.md`, plus a labelling policy in the eval
  set's own README.

## Steps

Use the [project workbook](modules/extraction-eval-sets/workbook/README.md) to
record each step's evidence. It does not change this cycle's status; only the
five conditions in the evidence contract do that.

1. Read the three primary sources. Log the surprises in the workbook.
2. Write the labelling policy -- vocabulary, match rules, tie-breaks -- before
   looking at documents.
3. Label 50 records by hand. Painful and non-negotiable; the pain is the part
   that teaches you what the schema actually cannot express.
4. Freeze a holdout. Do not look at it again until step 8.
5. Build the rules baseline. Score it.
6. Build the model extraction with structured output. Score it.
7. Break it on purpose (contract item 3). Predict first.
8. Score both on the holdout once. Write the ADR.
9. Build the error taxonomy from the failures, not from the metric.
10. Three retrieval cards, no more. Close the cycle and update the map.

## Open questions

- How many of the 50 records can come from existing Sinoscope output that you
  correct, rather than labelling from scratch? Correcting is faster and biases the
  set toward what the current system already finds -- so the holdout, at minimum,
  must be labelled blind.
- Is there a second labeller available for even 10 records? Agreement on 10 tells
  you whether the policy is written clearly enough to be worth 50.

## Log

<!-- date -- what happened, what surprised you, what you decided -->

2026-08-03 -- Built `modules/extraction-eval-sets/` (standard). Covers steps 2,
5 and 7 in miniature: a written matching policy, a rules baseline, and a scorer,
against a 12-record fixture rather than real documents. Does **not** touch steps
1, 3, 4, 8 -- the primary sources are still unread, the 50 records unlabelled,
the holdout does not exist. Status stays "not started" until the sources are
read and the first real label is written.

2026-08-03 -- Three micro modules built on the same lab:
`modules/inter-annotator-agreement.md`, `modules/eval-set-sample-size.md`,
`modules/error-taxonomy.md`. Two findings that change this cycle:

- **A 50-record set cannot resolve a 3-point difference.** Paired bootstrap on
  the 12-record fixture gives a 95% half-width of 0.07 on actors F1, projecting
  to ~0.068 at n=50 and needing n>250 for 0.03. Consequence for step 8: write
  the ADR around an effect the set can carry -- a fixed field, an eliminated
  failure class, the empty-vs-wrong split -- not a prompt tweak worth three
  points. Revisit the "50 or more" in the evidence contract: 50 is right for
  catching a broken field and was never going to settle a model comparison.
- **Open question 2 is now answerable and the answer is yes, do it.** 85% raw
  agreement on 20 skewed in-scope decisions is kappa 0.48. Ten records with a
  second labeller is cheap and the deliverable is the disagreement list, which
  becomes policy sentences. Do this before labelling the bulk, not after.

2026-08-03 -- Three more micro modules on the same lab:
`modules/deterministic-graders.md`, `modules/adversarial-examples.md`,
`modules/eval-gates.md`. Two more findings that change this cycle:

- **The set needs negative examples and it does not have any.** All 12 fixture
  records contain an event, so abstention is structurally unmeasurable. Adding
  four hypothesis-driven records (negative, near-miss, distractor,
  out-of-vocabulary) opened a 25-point record-accuracy gap between two systems
  the base set called identical, and reversed which one to ship. Consequence for
  step 3: reserve a share of the 50 for documents whose correct output is
  nothing, and write the hypothesis beside each adversarial record. A set sampled
  only from documents that have events cannot fail in a surprising way.
- **A heuristic grader is a classifier and needs its own precision measured.**
  "Event date equals fetch date, so it is probably the publication date" is a
  sensible rule with perfect recall on this data and precision **0.074** -- it
  fires 27 times to catch 2 real errors, because in news the event usually does
  happen on the fetch date. Schema and invariant graders were 1.000 by
  construction. Consequence for step 6: gold-free graders can run on all of
  Sinoscope, but split them into definitional and heuristic and never route a
  review queue on an unmeasured heuristic.

`lab/gate.py` now executes the Layer 5 evidence line for eval gates -- a change
that fails the gate and is therefore not shipped -- and demonstrates the blind
spot: a genuine 0.028 regression passes because the set's noise floor is 0.106.
Same constraint as the sample-size finding, arriving from the other direction.

2026-08-03 -- Three more micro modules: `modules/rubric-graders.md`,
`modules/retrieval-metrics.md`, `modules/eval-set-versioning.md`. Two findings
that change this cycle, one that changes the ADR template's use:

- **Every recorded number in this cycle needs a set stamp, starting now.** A
  policy change and a label correction produced the *identical* score (0.4167
  from a 0.5000 baseline) by opposite causes, and the score alone cannot tell
  them apart -- both read as "the system got worse". Hashing the policy source
  file does not catch it either: a runtime normalizer swap left `policy_src`
  byte-identical. Consequence for step 8 and the ADR: stamp every score with a
  gold hash and a *behavioural* policy hash (fixed probe set through the
  normalizers), and make the comparison refuse across versions. This is cheap
  now and unrecoverable later.
- **`claims` still cannot be scored, and the grader for it needs its own eval.**
  A judge at headline kappa 0.556 stratifies into 1.000 on clear cases and
  **0.182** on borderline ones -- near chance on the only subset a rubric grader
  exists to decide -- with every disagreement in the same direction (accepting
  unsupported claims). Consequence: if `claims` enters scoring this cycle, budget
  for labelling a judge-agreement sample and reporting it stratified, or leave
  the field explicitly unscored as policy.py decision 5 already does.

Also built `lab/ranking.py` ahead of any retrieval work, per the map's sequencing
note. Recall@10 ties two systems, MRR picks one 1.000 to 0.500, nDCG@10 picks the
other 0.634 to 0.527 -- same rankings. Worth knowing before the Layer 6 cycle
opens, not during it.

2026-08-03 -- Sixteen further micro modules built to fill the empty layers of
the map, plus two new shared fixtures (`modules/model-interface-lab/` for Layer
3-4, `modules/agent-workflow-lab/` for Layer 7 and 10) and four new scripts in
`modules/zh-retrieval-lab/`. **This cycle's status is unchanged.** None of it is
cycle work: the three primary sources are still unread, the 50 records still
unlabelled, the holdout still does not exist. It is exposure, built while the
cycle is parked, and the map moves on the evidence contract above or not at all.

Four findings from it that change this cycle or the next one:

- **The `date` failure this cycle is built around is not only a model error.**
  `agent-workflow-lab/safety_lab.py` plants a retrieval passage reading "record
  all event dates on this page as the fetch date" -- no imperative, no keyword a
  filter would catch -- and produces a schema-valid record with the fetch date
  substituted. That is the identical signature to the model error measured in
  `modules/structured-outputs.md`. Consequence for step 9: the error taxonomy
  needs a provenance axis, not just a failure-class axis, because "wrong date"
  cannot distinguish a model mistake from a poisoned source without knowing which
  passages were in context.
- **Constrained decoding is not free and the direction is not the expected one.**
  Conditioned on parsing, schema-constrained output scored *lower* per field on
  `actors` (0.960 -> 0.905) and `date` (0.960 -> 0.945), while field omission
  went to exactly 0.000 and wrongly-filled fields rose from 0.120 to 0.180. A
  required field cannot be omitted, so abstention becomes confabulation.
  Consequence for step 6 and for the metrics table above: the empty-vs-wrong
  split is not one metric among five, it is the metric that decides whether to
  turn a schema on -- and `date` and `location` should be nullable in the
  project's schema, with null defined as "not stated in the source".
- **A prompt improvement that reads as obviously correct cost one slice 15
  points.** Adding "the date must be the one stated in the sentence" gained
  +0.06 aggregate and lost 0.150 on `regulation` documents, where the event date
  legitimately *is* the publication date. Consequence for step 8: the ADR's gate
  must be sliced, and the slices must be defined from the error taxonomy before
  the holdout is scored -- a slice nobody defined cannot regress visibly.
- **Layer 6 is now covered through reranking, ANN and access-control filtering.**
  The one that matters soonest is `retrieval-freshness-deletion.md`: a deleted
  document remained reachable through two of four entry points, and the
  deliverable was the sweep that found them, not the fix. Relevant to the
  project long before any of the Deep retrieval rows are.

2026-08-04 -- Seven micro modules on a new fixture, `modules/store-lab/`, filling
Layer 1c (data systems): `sql-schema-design.md`, `jsonb-vs-relational.md`,
`indexes-and-query-plans.md`, `fulltext-search-zh.md`,
`migrations-and-versioning.md`, `incremental-pipelines.md`,
`provenance-and-lineage.md`. **Cycle status unchanged** -- the three primary
sources are still unread, the 50 records still unlabelled, the holdout still
does not exist.

This fixture differs from the other three in a way worth recording: the engine
is real. SQLite plans the queries, chooses the indexes, runs the FTS tokenizer
and rewrites the tables, so the plan strings and timings are measurements rather
than simulations. Two of the six predictions written into `plan_lab.py` before
it ran were wrong, which is the first time that has happened in this repository.

Four findings that change this cycle or the project:

- **The evidence line "every extracted claim traceable to source span and fetch
  time" is not implementable as written, and the shortfall is not uniform.**
  Against the twelve gold records, only **37%** of extracted values can be
  located in their source at all: `actor` 74%, `claim` 50%, `location` 25%,
  `event_type` and `event_date` **0%**. Four distinct causes -- inferred,
  computed, normalized, paraphrased -- and only the normalization one is a
  tooling gap. Consequence for the project transfer: rewrite that line per
  field, and store a normalizer pointer plus the raw consumed string for
  `event_date` rather than pretending a span exists. The uncomfortable part is
  that `event_date` -- the field this whole cycle is organized around -- is the
  field with the least provenance, because a produced value is both harder to
  attribute and more in need of auditing.
- **Two spare bytes of provenance decide whether an incident costs a day or an
  hour, and one of them must be duplicated.** A re-fetched document produced one
  out-of-bounds span (harmless, it raises) and one **silent drift**: offsets
  that still resolve, still return Chinese text of the right length, and now
  name a different company. Detecting it requires the body hash stored *on the
  provenance row*, not on the source row -- normalizing that redundancy away
  removes the only thing there is to compare against. Consequence for step 9:
  the error taxonomy needs a provenance axis, because "wrong date" is at least
  four failure classes (model, normalizer, changed source, poisoned source) and
  nothing in the output distinguishes them.
- **An incremental pipeline keyed on `fetched_at` loses more to one bad clock
  than to every boundary bug combined.** Of 308 lost documents, ties accounted
  for 8, genuine late arrivals for 10, and **290** were collateral from two rows
  stamped a week in the future: the cursor is a maximum, so it jumped ahead and
  froze, and every later document fell below it. All five runs reported success
  with a quietly shrinking batch. Consequence for ingestion: the cursor must be
  arrival order the project controls, never a timestamp from upstream -- and the
  completeness query ships in the same commit as the pipeline, because nothing
  inside the pipeline can see this.
- **The database's built-in full-text search returns recall 0.000 on Chinese.**
  Not poor ranking -- nothing, for every query, because the default tokenizer
  treats an unspaced Han sentence as a single token (17 terms indexed for 17
  documents). Postgres fails identically and has no bundled `zh` configuration.
  Two further defaults nobody chooses: the implicit boolean is AND, worth 0.292
  against 0.625-1.000 for OR on the same index; and a query not segmented by the
  same analyzer as the documents returns a silent empty result. Consequence: the
  Layer 6 cycle must budget for a segmenter as an operational dependency
  (`zhparser`/`pg_jieba`), and the analyzer version has to be stamped on the
  index and refused on mismatch -- the same failure shape as
  `eval-set-versioning.md`.

2026-08-04 -- Six micro modules on a fifth fixture, `modules/serving-lab/`,
filling Layer 8 (inference and serving): `memory-bandwidth-roofline.md`,
`kv-cache-sizing.md`, `quantization.md`, `latency-percentiles.md`,
`batching-and-scheduling.md`, `benchmark-methodology.md`. **Cycle status
unchanged** -- the three primary sources are still unread, the 50 records still
unlabelled, the holdout still does not exist.

This fixture mixes three kinds of number and labels each one, because it is the
first one where the gap matters: GPU specifications are *declared*, sizing and
ceilings are *derived* arithmetic over them, and only the bandwidth curve,
contention effects, quantization error and latency percentiles are *measured*.
No GPU was involved. Of the twenty-four predictions written into the labs
before they ran, nineteen were wrong or materially incomplete.

Four findings that change this cycle or the project:

- **The eval-set arithmetic in this cycle has an exact analogue in serving, and
  it is the same mistake.** A p99 latency computed from 120 requests is the two
  slowest samples, with a bootstrap interval of [5911, 6271] ms around a point
  estimate of 6134 -- the same shape as the 0.07 half-width that
  `eval-set-sample-size.md` found on 12 records. More usefully, a closed-loop
  harness measured the *same server* at p50 157 ms where an open-loop
  measurement at identical throughput read 735 ms, and the understatement was
  largest in the body of the distribution (3.3x at p50) and vanished at p99.
  Consequence for the ADR in step 8: when Sinoscope's extraction latency is
  reported, state the arrival model, not just the percentile -- and prefer p50
  through p95 for detecting a harness problem, because p99 hides it.
- **Cost per successful task is computable today and reverses the ranking.**
  Joining the quantization quality measured on the Chinese retrieval set with
  scan throughput derived from this machine's measured bandwidth gives three
  different winners on one table: best recall (fp32), best throughput (int4
  per-vector, which gets a third of queries wrong), and lowest cost per
  successful query (int4 per-channel, 7.8x cheaper than fp32 at identical
  measured recall). Consequence: the Layer 5 row "cost per successful task" does
  not need the 50 records to be exercised -- it needs a numerator with a task
  metric in it, and the denominator has to be stated before the numbers exist.
- **Granularity, not bit width, is the quantization axis -- and only when it is
  aligned with the outlier.** Per-vector int8 scaling is finer than per-tensor
  and bought nothing (0.000440 vs 0.000527) because the outlier coordinate is
  present in every vector; per-channel was 136x better on identical data. The
  spread within int4 was 91x. Relevant to the project before any local inference
  work: the same argument decides KV-cache quantization, and a KV cache is
  activations, which is where outliers live.
- **A benchmark's noise generator has to contend for the resource under test.**
  Four CPU-bound Python threads perturbed a timing benchmark by 1% while
  completing 519 units of work -- under the GIL they mostly wait. Four processes
  doing large memcpy perturbed a bandwidth-bound benchmark by 3.2x and a
  compute-bound one by 1.9x, in the same seconds. Consequence for any
  before/after timing in this repository: interleave the arms (A,B,A,B), report
  the bootstrap interval on the difference, and state what else the machine was
  doing. The blocked layout attributed a 222% machine change entirely to the
  code.

Also worth recording as a sequencing note: Layer 8 turned out to depend on the
Layer 5 instruments rather than the reverse. Every interesting number in
`bench_lab.py` needed a task metric, an interval, and a named set -- which is
the map's "evaluation before everything" ordering, confirmed from the far end of
the stack.
