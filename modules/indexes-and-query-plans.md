# Indexes and query plans

**Micro module.** One mechanism, one experiment, three cards. Runs against
[store-lab/](store-lab/).

**Capability:** Indexes and query plans (Layer 1c, Aware -> Independent). Map
evidence: "Read an `EXPLAIN ANALYZE` and predict the effect of an index first."

---

## The problem

The evidence line puts the weight on *first*. A prediction made after seeing the
plan is a description, so the six predictions in `plan_lab.py` are written into
the file as data and the script scores them. Four were right. The two that were
wrong are this module.

## The wrong model

Not one model -- two, and both are the standard advice:

**"An index on a low-selectivity column will not be used."** `event_type` is 40%
`investment`. The planner used the index anyway and the query got 3.8x faster.

**"A prefix `LIKE 'x%'` can use an index; only a leading wildcard cannot."** It
did not. The plan was a full scan of the index, not a seek.

## The mechanism

**Case B: covering beat selectivity.**

```text
SEARCH events USING COVERING INDEX ix_type (event_type=?)     0.62 ms
(unindexed scan)                                              2.37 ms
```

The word is `COVERING`. `count(*)` needs no column the index does not carry, so
the entire query runs inside the index, which is narrower than the table.
Reading 40% of a narrow structure beats reading 100% of a wide one. Ask for a
column the index does not carry and the advice comes back -- but not as a plan
change:

```text
sum(confidence) WHERE event_type='investment'  (~40%)   3.21 ms   SEARCH ix_type
sum(confidence) WHERE event_type='sanction'    (~10%)   0.98 ms   SEARCH ix_type
```

Same plan, several-fold runtime difference. That is not the planner adapting to
the value -- it is the planner *not* adapting. Here is everything `ANALYZE`
recorded about that index:

```text
ix_type -> '40012 6669'      rows, average rows per distinct value
```

One average, for a column whose true per-value counts run from ~2,000 to
~16,000. `sqlite_stat1` holds no histogram, so a skewed column gets one plan for
every value and the common value is planned as though it were the average.
Postgres does keep per-value statistics (`most_common_vals`), and SQLite can
with STAT4 compiled in. This is the actual mechanism behind "it was fast in
staging".

**Case D: the prefix `LIKE` was a collation problem.**

```text
LIKE '深圳%'                    SCAN events USING COVERING INDEX ix_loc
GLOB '深圳*'                    SEARCH ... (location>? AND location<?)
location >= '深圳' AND < ...    SEARCH ... (location>? AND location<?)
LIKE, case_sensitive_like=ON    SEARCH ... (location>? AND location<?)
```

The blocker is neither the wildcard nor the Chinese text. `LIKE` is
case-insensitive by default, so `'A%'` must also match `'a%'`, and one
contiguous index range cannot express that. Turn case sensitivity on and the
identical query seeks. `GLOB`, which is case-sensitive, seeks unasked.

This transfers exactly: in Postgres `LIKE 'x%'` uses a b-tree only under the C
collation or an index built with `text_pattern_ops`. Same cause, same fix,
different spelling.

**Two more results worth carrying.**

*Your index inventory is not your `CREATE INDEX` statements.* Case A was already
a `SEARCH` before any index was created -- `record_id TEXT UNIQUE` had built
`sqlite_autoindex_events_1`, making the later `CREATE INDEX ix_rec` a redundant
second copy paid for on every insert. Read the inventory from the catalogue, not
from the migration files.

*An optimization can hide a design mistake.* For `WHERE event_type = ? ORDER BY
event_date DESC LIMIT 10`:

```text
(event_type, event_date)   0.01 ms   SEARCH ix_pair (event_type=?)
(event_date, event_type)   0.01 ms   SEARCH ix_pair (ANY(event_date) AND event_type=?)
(source_id, event_type)    1.12 ms   SEARCH ix_type ... + USE TEMP B-TREE FOR ORDER BY
```

The second is the textbook mistake -- the constrained column is not on the left
edge -- and it is just as fast, because `ANY(event_date)` is a **skip-scan**:
1,344 distinct dates over 40,000 rows is ~30 repeats per value, and SQLite
decides seeking once per distinct leading value beats scanning. Make the leading
column unique and the rescue vanishes; the planner abandons the pair index
entirely. Postgres has no skip-scan, so the same index there is the mistake the
textbook says it is.

## The experiment

```powershell
cd modules\store-lab
python plan_lab.py
```

Read `PREDICTIONS` at the top and commit to each before running.

## Boundary

- **Predict the plan, not the runtime.** The plan is deterministic given the
  statistics; the runtime is contaminated by cache state. Both misses above were
  about *why an index is usable at all* -- covering, and collation -- rather than
  about selectivity.
- **Run `ANALYZE`.** Postgres autovacuum does it; SQLite does not. A stale
  statistic is how a plan changes overnight with no deploy.
- **Selectivity is a property of the value, not of the column** -- and your
  planner may not know that. One plan serves every value, so only the tail of
  the latency distribution shows it. A p50 dashboard cannot see this class of
  problem at all.
- **Any function around the column disables the index.** Rewrite to a range, or
  index the expression ([jsonb-vs-relational.md](jsonb-vs-relational.md)).
- **What this fixture cannot show:** bitmap index scans, parallel plans, join
  algorithm selection beyond nested loops, and partial or covering indexes with
  `INCLUDE`. SQLite has one join strategy; Postgres plan-reading is a larger
  skill than this module teaches.

## Cards

### 1. [misconception] An index on a column where the queried value matches 40% of rows -- will the planner use it?

**Answer:** It depends on whether the index *covers* the query, not on the
selectivity. In the lab a `count(*)` filtered on a 40%-selective value used the
index and ran 3.8x faster, because the index carried every column the query
needed.

**Why:** A full scan of a narrow index beats a full scan of a wide table.
Selectivity governs the cost of *returning to the table*; when there is no
return trip, it barely matters.

**Boundary:** Change the query to need one column the index does not carry and
selectivity dominates again -- and the plan may not change at all, only the
runtime, because the planner has one estimate for the whole column.

**Tags:** `databases` `misconception` `general-principle`

---

### 2. [failure] `WHERE location LIKE '深圳%'` will not use the index on `location`. The wildcard is not leading. Why?

**Answer:** `LIKE` is case-insensitive by default, so `'a%'` and `'A%'` must both
match and a single contiguous index range cannot express that. `GLOB`, an
explicit range, or `case_sensitive_like=ON` all seek.

**Why:** Index range scans require the comparison to agree with the index's
collation. Case-insensitive matching over a case-sensitively ordered index is
not a range.

**Boundary:** Same cause in Postgres, different spelling: `LIKE 'x%'` needs the
C collation or `text_pattern_ops`. The portable fix is the explicit range
`>= 'x' AND < 'x' || <high char>`, which seeks everywhere and reads badly.

**Tags:** `databases` `failure` `general-principle`

---

### 3. [decision] A composite index with the columns in the wrong order benchmarks just as fast as the right order. Do you leave it?

**Answer:** No. Check whether a skip-scan is rescuing it -- `ANY(col) AND ...`
in the plan -- because that depends on the leading column having few distinct
values, which is a property of today's data.

**Why:** In the lab, `(event_date, event_type)` matched the correct order at
~30 rows per distinct date. Nothing announces the day that ratio changes, and
Postgres has no skip-scan at all, so the same index does not survive a port.

**Boundary:** The rule still holds with its mechanism attached: equality columns
first, then the range or sort column, because an index is only usable from its
left edge inward. What the skip-scan changes is how long a violation stays
invisible.

**Tags:** `databases` `decision` `general-principle`
