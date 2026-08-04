# Provenance, lineage and data quality

**Micro module.** One mechanism, one experiment, three cards. Runs against
[store-lab/](store-lab/).

**Capability:** Provenance, lineage, data quality (Layer 1c, Aware ->
Independent). Map evidence: "Every extracted claim traceable to source span and
fetch time." This is also the line the current cycle's project transfer depends
on.

---

## The problem

The evidence line reads as a switch to turn on. Build it against the twelve gold
records and measure how much of it can exist:

```text
field         values  with a span  coverage
actor             23           17      74%
location          12            3      25%
event_type        12            0       0%
event_date        12            0       0%
claim             12            6      50%
TOTAL             71           26      37%
```

Just over a third -- and this is the *optimistic* number, measured against
hand-labelled records on documents that genuinely contain them.

## The wrong model

**"Every extracted value points at the text it came from."**

Four different reasons it cannot, and they are not interchangeable:

- **`event_type` is inferred.** `investment` is a label from a closed
  vocabulary, nowhere in the text and never will be. A span for it would be a
  *rationale span* -- the phrase that justified the label -- which is a different
  artifact needing its own policy.
- **`event_date` is computed.** The source says 一月十二日 or nothing; the record
  says `2026-01-12`. The honest provenance is a pointer to the normalizer plus
  the raw string it consumed.
- **`location` is normalized.** 深圳市 in the record, 深圳 in the text. The span
  exists and exact-match lookup cannot find it. The only one of the four fixable
  by writing better code.
- **`claims` are paraphrases, and six actors are absent from their sources.**
  The claims were summarized rather than quoted. The absent actors are the
  interesting case: a name in the record that appears nowhere in its source
  document is either a normalization artifact or a value the extractor invented.
  **An untraceable actor is a hallucination candidate** -- a cheap detector
  needing no labels, which puts it in the gold-free grader family of
  [deterministic-graders.md](deterministic-graders.md).

Note which field is worst. `event_date` is the field this entire cycle is
organized around -- the model substituting the fetch date, measured in
[structured-outputs.md](structured-outputs.md) and reproduced by a poisoned
passage in [prompt-injection.md](prompt-injection.md) -- and it has the least
provenance of any field. **The fields that most need auditing are the hardest to
attribute**, because both properties come from the same cause: the value was
produced rather than copied.

## The mechanism

Then the document changes. Source 10 is re-fetched; the article has been
rewritten and shortened:

```text
field    stored span   stored value   text at that span now   verdict
actor    [5:9]         通威股份        (out of bounds)         out of bounds
actor    [0:4]         隆基绿能        通威股份                SILENT DRIFT
```

The out-of-bounds span is harmless: it raises, someone notices, the citation is
visibly broken. The drifted span still resolves, still returns Chinese text of
the right length, and still renders in a UI as "here is where we got this" --
while pointing at a different company. **A citation that cannot fail loudly is
not a citation.**

The check is one join, and it is exact:

```sql
SELECT count(*) FROM provenance p JOIN sources s USING (source_id)
 WHERE p.body_sha <> s.body_sha;          -- 6
```

It works because the hash was written *beside the span*, at extraction time, by
the same code that wrote the span. Storing the hash only on `sources` would not
work -- it moves with the document, leaving nothing to compare against. The
mechanism *is* the redundancy, and the instinct to normalize it away is exactly
wrong: provenance is a snapshot of a belief, one of the few places where
duplicating a value is the correct design.

**Lineage runs backwards, and that is the direction that matters.** Forwards --
where did this value come from -- is the easy direction and the one provenance
is sold on. Backwards is the query written during an incident:

```sql
SELECT DISTINCT event_id FROM provenance
 WHERE extractor = 'extract-v3' AND field = 'event_date';   -- 5 records
```

That needs the extractor version stored *per value*, not per run. Without it the
answer is "everything since the deploy": reprocess the corpus, re-review records
that were fine. The column costs one TEXT per row; not having it is paid once
per incident, in review time, forever.

## The experiment

```powershell
cd modules\store-lab
python provenance_lab.py
```

## Boundary

- **Four invariants worth asserting in CI**, of which two currently fail and
  should: every event has a source; every source has a fetch time; no span
  points outside its document; no span whose document has changed. A provenance
  schema with no failing check is a schema nobody has tested against a changed
  source.
- **This changes the cycle's error taxonomy.** "Wrong date" is not one failure
  class -- it is at least four: the model invented it, the normalizer mis-parsed
  it, the source said something different when it was read, or the source was
  poisoned. Only these columns tell them apart, which is why step 9's taxonomy
  needs a **provenance axis** and not only a failure-class axis.
- **Character offsets are the fragile representation.** They break on any edit,
  on re-tokenization, and on a normalization pass over the stored body. Anchoring
  to a quoted snippet plus a fuzzy locate degrades more gracefully, at the cost
  of being approximate -- and approximate provenance needs its own accuracy
  measurement, which is a further eval.
- **Provenance is a retention and access-control question the moment it exists.**
  It stores document text alongside extracted values, so PII, licensing and
  deletion propagate into it. Deleting a source must delete its spans, or
  [retrieval-freshness-deletion.md](retrieval-freshness-deletion.md)'s sweep
  finds them.
- **Not covered:** provenance through aggregation (which rows produced this
  count), and provenance across a model call chain, where the "source" of a
  value is a prompt, a set of retrieved passages, and a decoding seed rather
  than a span.

## Cards

### 1. [misconception] "Every extracted claim traceable to a source span" -- is that a property you implement, or a property you measure?

**Answer:** Measure. On hand-labelled records over documents that genuinely
contain them, only 37% of extracted values could be located in their source, and
two fields scored 0%.

**Why:** Inferred fields (a closed-vocabulary label), computed fields (a
normalized date), normalized fields (深圳市 vs 深圳) and paraphrased fields
(summarized claims) each fail for a different reason, and only one of the four
is a tooling gap.

**Boundary:** The corollary is worth more than the number: the fields with the
worst provenance are the ones that most need auditing, because both come from
the value being produced rather than copied.

**Tags:** `provenance` `misconception` `project-specific`

---

### 2. [failure] A record's citation renders correctly, shows plausible source text, and names the wrong company. The span offsets were never edited. What happened?

**Answer:** The source document was re-fetched and changed. The stored offsets
still resolve, into different text.

**Why:** In the lab, one edit produced one out-of-bounds span (harmless -- it
raises) and one silent drift, where `[0:4]` returned a different company name of
the same length. Nothing distinguishes a drifted span from a correct one without
comparing the document to what it said at extraction time.

**Boundary:** The detector is a content hash stored *on the provenance row*, not
on the source row. A hash that lives only with the document moves when the
document does, leaving nothing to compare against.

**Tags:** `provenance` `failure` `project-specific`

---

### 3. [decision] You store the extractor version once per pipeline run. An extractor bug is found. What can you not answer?

**Answer:** Which specific records to re-extract. A per-run stamp gives
"everything since the deploy"; a per-value stamp gives the exact list -- 5
records in the lab rather than all 12.

**Why:** Lineage is used backwards during incidents, and the backwards query is
the expensive one to get wrong: reprocessing a corpus and re-reviewing records
that were never affected costs review time, which is the scarce resource.

**Boundary:** Per-value stamping is only useful if the version identifies
behaviour rather than a deploy -- the same problem as the behavioural policy hash
in [eval-set-versioning.md](eval-set-versioning.md), where a byte-identical
source file still produced different results after a runtime swap.

**Tags:** `provenance` `decision` `general-principle`
