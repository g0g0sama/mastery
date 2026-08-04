# Cards -- labelled eval sets and extraction metrics

14 cards, derived from the concept map in [README.md](README.md). Numbers cited
are reproducible from `lab/` and are there to make a card gradable, not to be
memorized.

---

### 1. [mechanism] In an extraction eval set, why is gold stored in its raw surface form and normalized only at scoring time?

**Answer:** So the set can be re-scored when the matching policy changes.
Normalization is applied to both sides at scoring time instead.

**Why:** Normalization is a policy decision that will be revised -- a new
suffix rule, a different location granularity. Gold that was normalized on
ingest has already had the old policy baked into it irreversibly, so every
historical number becomes incomparable and the labels have to be redone.

**Boundary:** Whitespace and encoding repairs to genuinely corrupt input are
fine to apply on ingest; the rule is about semantic folding, not cleanup.

**Tags:** `eval-sets` `mechanism` `general-principle`

---

### 2. [failure] An eval metric moves several points between two runs and no extractor code changed in between. What do you inspect first?

**Answer:** The matching policy -- normalizers, the closed vocabulary, the
field match rules -- before the model or the extractor.

**Why:** The policy is a measuring instrument that lives in the repository and
is edited like code. Replacing the normalizers with `str.strip()` in this
module's lab moves one system's location F1 from 1.0000 to 0.5000 with no
prediction and no label changed.

**Boundary:** Also check whether the gold set itself was re-labelled or extended
-- a changed denominator produces the same symptom.

**Tags:** `eval-sets` `failure` `general-principle`

---

### 3. [misconception] Your extraction output is 100% schema-valid. What does that tell you about its quality?

**Answer:** Nothing. Validity says the record can be stored, not that it is
right.

**Why:** The schema is usually looser than the labelling policy and can only
enforce what the storage type permits. A schema that accepts an ISO datetime
cannot see a producer that switched from dates to datetimes; that field scores
0.0 with validity still at 1.0.

**Boundary:** Validity is still worth reporting -- as a gate, and because
invalid records are excluded from per-field scoring and therefore change the
denominator of every other number.

**Tags:** `extraction` `misconception` `general-principle`

---

### 4. [mechanism] How do you define precision and recall for a field that is sometimes a list and sometimes a single value?

**Answer:** Treat a scalar as a set of size 0 or 1, then
`tp = |gold & pred|`, `fp = |pred - gold|`, `fn = |gold - pred|` for every
field.

**Why:** One code path, no special case for missing values, and no division by
zero when nothing was predicted. A substitution falls out correctly as
`fp=1, fn=1`.

**Boundary:** Both sides empty gives `0/0/0` -- correctly declining to answer
earns nothing under any of these metrics, which is why a system optimized on
recall alone learns to guess.

**Tags:** `extraction` `mechanism` `general-principle`

---

### 5. [implementation] Write the counts for these three cases, given gold and predicted actor sets: ({A,B} vs {A,C}), ({A} vs {}), ({} vs {A}).

**Answer:** `(tp=1, fp=1, fn=1)`, `(0, 0, 1)`, `(0, 1, 0)`.

**Why:** The three shapes are substitution, omission, and invention. They are
the entire vocabulary of extraction error, and F1 collapses all three into one
number.

**Boundary:** Normalization must be applied to both sides before the set
operations, or the counts measure formatting rather than content.

**Tags:** `extraction` `implementation` `general-principle`

---

### 6. [comparison] Micro versus macro averaging of per-field precision and recall across records: what does each weigh, and when do they diverge?

**Answer:** Micro pools `tp/fp/fn` across all records and computes once, so
every extracted **item** weighs the same. Macro computes per record and
averages, so every **document** weighs the same.

**Choose micro when:** the cost is per wrong item -- a database filling with
bad entities.

**Choose macro when:** the cost is per bad document -- a human reviewing each
record.

**Boundary:** They diverge exactly where the data has a long tail. One document
with seven actors drives a 15-point gap between micro and macro recall in this
module's lab.

**Tags:** `metrics` `comparison` `general-principle`

---

### 7. [misconception] A system that never predicts a given field at all posts a macro precision of 1.0000 for it. Is the scorer broken?

**Answer:** No. Precision with no predictions is 0/0, and macro averaging
conventionally scores that record 1.0, so abstention inflates macro precision.

**Why:** Micro averaging uses the opposite convention (0.0) because it pools
counts before dividing, so the two averages disagree on exactly the systems
that can decline to answer.

**Boundary:** Never report macro precision alone for an abstaining system.
Recall is unaffected by the convention and exposes the same system immediately.

**Tags:** `metrics` `misconception` `general-principle`

---

### 8. [decision] Two extraction systems have actors F1 within 0.01 of each other and identical record accuracy. Their counts are `tp=20, fp=3, fn=3` and `tp=18, fp=0, fn=5`. Which do you ship into a database analysts query, and on what basis?

**Answer:** The second (`fp=0`). It omits five actors; the first fabricates
three.

**Why:** An omission is a gap you can measure, backfill, and alert on. A
fabrication is indistinguishable from a real record once stored, propagates into
every downstream query, and has no detection signal.

**Boundary:** Reverse it when omission is the expensive failure -- sanctions
screening, safety recalls, anything where a miss is the liability -- and when a
human reviews every record before it lands.

**Tags:** `extraction` `decision` `general-principle`

---

### 9. [mechanism] Four extracted fields each score about 0.9 F1. What fraction of records will be completely correct, and why?

**Answer:** Roughly `0.9^4 ~ 0.66` if the field errors were independent, and
lower in practice -- 0.5 in this module's lab.

**Why:** Record acceptance is a conjunction over fields, so per-field scores
multiply rather than average. Errors also cluster on hard documents, which
pushes the real number below the independent estimate.

**Boundary:** Complete-record accuracy ranks systems but cannot diagnose one --
it moves for every cause and names none. Per-field scores locate the bug.

**Tags:** `metrics` `mechanism` `general-principle`

---

### 10. [failure] One field in your extraction report reads exactly 0.0000 while schema validity holds at 100%. What is the first suspect?

**Answer:** A representation change on that field -- producer and match rule no
longer agreeing on a format -- not a collapse in model quality.

**Why:** A model that genuinely degraded scores badly, not at exactly zero. Zero
with valid structure means every value is being compared under a form it can
never match: dates gaining a time component, lists arriving comma-joined,
identifiers gaining a prefix.

**Boundary:** Also plausible if the field was renamed in the output schema and
now reads as absent everywhere -- check whether the counts show `fn` only
(absent) or `fp` and `fn` together (present but unmatched).

**Tags:** `extraction` `failure` `general-principle`

---

### 11. [scenario] Your per-field extraction scores improved after a release, and analysts report that quality got worse. Where do you look?

**Answer:** At `n_scored` -- how many records entered the per-field
calculation. Records failing schema validation are excluded, so a release that
made structural failures more common raises the average over an easier
remainder.

**Why:** Validity failures correlate with hard documents. Dropping them removes
the cases the system handles worst, which is precisely the population analysts
are complaining about.

**Boundary:** Report complete-record accuracy over the full denominator
alongside per-field scores; it counts an unstorable record as a failure and does
not move for this reason.

**Tags:** `eval-sets` `scenario` `general-principle`

---

### 12. [best-practice] Why is cost reported per accepted record rather than per model call?

**Answer:** Because the denominator should be units of value delivered, not
work attempted. A call producing an unusable record cost money and returned
nothing.

**Why:** Cost per call ranks the cheapest system first regardless of whether
anything it produces is usable. Cost per accepted record ranks a $0.00 rules
baseline that accepts nothing as undefined -- which is the honest answer.

**Boundary:** Include retries and rejected attempts in the numerator, or the
metric rewards systems that fail fast and are re-run.

**Tags:** `metrics` `best-practice` `general-principle`

---

### 13. [best-practice] You have looked at 10 of the 50 records in your frozen holdout while debugging. What is the state of the holdout?

**Answer:** Spent. It is now a dev set, all 50 records, and an unbiased estimate
requires new blind-labelled data.

**Why:** There is no partial contamination. What you learned from the ten
changes what you build, and what you build is then evaluated on the remaining
forty -- so the whole set has been fit through you.

**Boundary:** This is why a dev set exists: iterate freely there, score the
holdout once per decision, and record the date it was spent.

**Tags:** `eval-sets` `best-practice` `general-principle`

---

### 14. [decision] Before labelling, should `event_type` be a closed vocabulary or an open one?

**Answer:** Closed, unless you already have a scoring policy for open values.
Closed is scoreable on day one; open is honest and cannot be scored at all
without a match rule for unseen labels.

**Why:** The choice must be made before the first label, because changing it
afterwards invalidates the set -- records labelled under one policy cannot be
compared to records labelled under the other.

**Boundary:** The cost of closed is that genuinely novel event types are logged
as schema violations. Read that violation log as the backlog for vocabulary v2,
not as a list of model failures.

**Tags:** `eval-sets` `decision` `project-specific`

---

## Retrieval challenge

1. Explain in five sentences why per-field precision and recall locate a problem
   that whole-record accuracy hides, and name the case where the reverse is true.
2. Given a system that returns an empty `actors` list on 30% of documents,
   describe which of micro precision, macro precision, micro recall, and record
   accuracy move, and in which direction.
3. Name the most expensive failure that follows from not writing the matching
   policy down.

## Highest-priority concepts

- **The policy is the instrument** -- it moves every number without touching the
  system, and it is the only artifact here that outlives the model you are
  currently measuring.
- **`tp/fp/fn`, not F1** -- invention and omission need opposite fixes and F1
  reports them as the same score.
- **The denominator** -- `n_scored`, accepted records, cost per accepted record.
  Every trap in this module is a denominator quietly changing.
