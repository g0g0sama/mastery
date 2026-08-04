# Batch and incremental pipelines

**Micro module.** One mechanism, one experiment, three cards. Runs against
[store-lab/](store-lab/).

**Capability:** Batch and incremental pipelines (Layer 1c, Aware ->
Independent). Map evidence: "Incremental ingestion with watermarks and
reprocessing."

---

## The problem

An incremental pipeline is a loop with one piece of state: where it got to. The
capability is choosing that state well. The failure mode is that a badly chosen
watermark loses records **silently and permanently** -- the job succeeds, the
row count rises, and a document is never processed by anything, ever.

Five hundred documents with two timestamps, which is the whole subject:
`fetched_at`, when the crawler collected it, and `ingest_seq`, when this
database learned about it. They are not the same order.

## The wrong model

**"Track the newest timestamp you have processed."**

```text
strategy                    processed  MISSED  writes  reprocessed
A  fetched_at >                   192     308     192            0
B  fetched_at >=                  200     300     208            4
C  (fetched_at, doc_id) >         200     300     200            0
D  ingest_seq >                   500       0     500            0
```

Every run of every strategy reported success. Three of the four lost more than
half the corpus.

## The mechanism

Every lost document, attributed:

```text
strategy A lost 308 of 500:
  tie at the boundary                     8    D0102, D0103, D0104
  late arrival (old doc)                 10    D0037, D0088, D0141
  collateral of a skewed timestamp      290    D0204, D0205, D0206

cursor at the start of each run:
  [0, 1770006000, 1770634200, 1770634200, 1770634200]
```

Three mechanisms, and only the first is the one that gets discussed.

**Ties.** The cursor is `max(fetched_at)` of the batch and the next run asks for
strictly greater, so a document carrying that exact timestamp but arriving in
the next batch is skipped forever. A crawler stamps a whole batch with one time,
so ties are normal, not a corner case -- ten documents share every timestamp
here. Strategy C fixes exactly this by making the cursor a *pair*,
`(timestamp, id)`, which is a total order and therefore has no ties.

**Late arrivals.** A document fetched at 09:00 and inserted after the cursor
passed 11:00 is below the watermark the moment it lands. No comparison on
`fetched_at` can find it, because the field being selected on describes the
past. C does not fix this; nothing of that shape can.

**One bad timestamp took the rest.** This is the dominant cause and the one
worth carrying away. Two documents with a clock a week fast arrived in run 2.
The cursor is a *maximum*, so it jumped a week ahead and froze there -- every
genuine document arriving afterwards had a `fetched_at` below it and was never
selected again. Two bad rows disabled the pipeline for the remaining 290, and
the job kept reporting success with a shrinking batch size.

That last one is why `max()` over an externally supplied timestamp is the wrong
cursor even after ties and lateness are handled: **the watermark inherits the
worst clock of every system upstream of it.**

**`>=` is not the safe choice it looks like.** It processed 200 distinct
documents with 208 writes -- 8 redundant -- and still missed 300. It trades one
bug for a cost and does not close the other, and `>` versus `>=` is where this
discussion usually ends.

**The sink decides whether a re-run is safe.** With no unique constraint on the
sink, B's re-writes became duplicate rows rather than overwrites, and every
aggregate downstream is inflated by exactly the amount the pipeline was "safely"
redundant. With a unique index and an upsert, the same re-run is free.
Reprocessing is a property of the sink, not of the pipeline -- decide idempotency
at the write, once, and an over-inclusive cursor becomes merely wasteful instead
of corrupting. That is the argument from
[provider-errors-retries.md](provider-errors-retries.md), arriving from the data
side.

## The experiment

```powershell
cd modules\store-lab
python pipeline_lab.py
```

## Boundary

- **None of this is visible from inside the pipeline.** Every run succeeded. The
  instrument is a query comparing the two tables:

  ```sql
  SELECT count(*) FROM raw
   WHERE doc_id NOT IN (SELECT doc_id FROM processed)
     AND ingest_seq <= (SELECT seq FROM cursor_);
  ```

  Run it on a schedule and alert on non-zero. Without it the only evidence is an
  absence, and nobody files a bug about a document they never saw -- the same
  blind spot [retrieval-freshness-deletion.md](retrieval-freshness-deletion.md)
  found from the retrieval side.
- **Design rules this produces:** drive the cursor from arrival order (a
  monotonic sequence, a commit LSN, an `ingested_at` your own writer sets), never
  from a timestamp belonging to the outside world; if it must be a timestamp,
  make it a tuple with a tie-breaking id; make the sink idempotent before tuning
  the cursor; ship the completeness query in the same commit as the pipeline.
- **`ingest_seq` is not free of problems either.** A monotonic sequence assigned
  before commit can be committed out of order, so a reader at the high-water mark
  can skip a row that was still uncommitted -- the reason Postgres logical
  replication tracks LSN plus in-progress transaction ids rather than a bare
  sequence. This fixture has one writer and cannot show it.
- **Event-time is still needed** -- for windowed aggregates, for "what happened
  on Tuesday", for anything a human asks. The claim is narrower: event-time is
  the wrong thing to make the *cursor*, even when it is the right thing to
  report.
- **Deletions and updates are not covered.** A watermark finds new rows. Finding
  rows that changed or vanished upstream is a different mechanism (change
  capture, tombstones, or periodic full reconciliation).

## Cards

### 1. [failure] An incremental job keyed on `WHERE fetched_at > :watermark` has been reporting success for weeks, with batch sizes quietly shrinking to zero. What is the most likely cause?

**Answer:** A record with a wrong, future-dated timestamp advanced the cursor
past everything real. Because the cursor is a maximum, one bad clock upstream
freezes the pipeline permanently.

**Why:** In the lab, two documents stamped a week ahead cost 290 of 500
documents -- far more than ties (8) and genuine late arrivals (10) combined. The
job never errored; its batch simply got smaller.

**Boundary:** Clamping the watermark to `now()` limits the damage but does not
fix the class. The cursor should be arrival order, which no upstream clock can
influence.

**Tags:** `pipelines` `failure` `general-principle`

---

### 2. [misconception] Is choosing `>=` over `>` for the watermark the safe option?

**Answer:** It closes the tie bug at the cost of reprocessing the whole trailing
tie group every run, and it does nothing about late arrivals or a poisoned
watermark. It is the smaller half of the problem.

**Why:** Measured: `>=` processed 8 documents more than `>` and still missed
300. The tie-safe cursor is a `(timestamp, id)` pair, which is a total order and
needs no redundant reprocessing.

**Boundary:** Whether the redundant reprocessing is even a cost depends entirely
on the sink. Against an idempotent upsert it is wasted compute; against an
append-only table it is duplicate rows and inflated aggregates.

**Tags:** `pipelines` `misconception` `general-principle`

---

### 3. [decision] What should an incremental pipeline's cursor be based on?

**Answer:** Arrival order that you control -- a monotonic ingest sequence, a
commit LSN, or an `ingested_at` set by your own writer. Not an event or fetch
timestamp supplied by an upstream system.

**Why:** Event-time cursors fail three ways at once: ties at batch boundaries,
late arrivals that land below the mark, and a single skewed timestamp that
advances the mark past everything real. The arrival-ordered cursor processed 500
of 500 with no duplicates.

**Boundary:** Arrival order still needs care under concurrent writers -- a
sequence assigned before commit can commit out of order, so a naive high-water
mark skips rows. Single-writer fixtures like this one cannot show that, and it
is the reason real change-capture tracks in-progress transactions too.

**Tags:** `pipelines` `decision` `general-principle`
