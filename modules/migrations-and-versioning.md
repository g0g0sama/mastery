# Migrations and schema versioning

**Micro module.** One mechanism, one experiment, three cards. Runs against
[store-lab/](store-lab/).

**Capability:** Migrations and schema versioning (Layer 1c, Aware -> Working).
Map evidence: "A backward-compatible migration run against real data."

---

## The problem

`location` becomes `location_name` plus `admin_level`, because 深圳市 and 深圳
are the same place at different granularities and nothing in the schema says so.
Twenty thousand rows, and the application is serving traffic.

## The wrong model

**"A migration is a change to a schema."**

It is a *sequence of states*, and during a rolling deploy -- and for as long as
a rollback is possible -- two versions of the code are live against every one of
them. The one-step version:

```text
ALTER TABLE events RENAME COLUMN location TO location_name;

v1_read   -> FAIL  no such column: location
v2_read   -> ok
v1_write  -> FAIL  table events has no column named location
```

v1 is not degraded, it is down, on every request, from the instant the migration
commits until the last old process drains. Rolling back the *code* does not
help, because the schema does not roll back with it. This migration is fine in
review and fine in staging, where only one version runs.

## The mechanism

Expand and contract, probed at every phase with both versions of the code:

```text
phase                                  v1_read   v1_write  v2_read   v2_write
0. before anything                     ok        ok        FAIL      FAIL
1. expand (add nullable columns)       ok        ok        ok        ok
2. backfill (20,164 rows, 5 batches)   ok        ok        ok        ok
3. dual-write trigger installed        ok        ok        ok        ok
```

Four green columns in every row after phase 1. That is what backward compatible
means operationally: no deploy or rollback of either version ever meets a schema
it cannot serve. It works because `ADD COLUMN` with a null default is invisible
to a `SELECT` written before it -- the null result from
[sql-schema-design.md](sql-schema-design.md), used deliberately.

**And it still lost three quarters of the old code's writes.**

```text
rows the new code cannot see:                    451
total rows v1 wrote during the migration:        604
share of v1's writes invisible to the new code:  75%
```

The backfill was bounded to the rows that existed when it started -- which is
how every real backfill is written, because a job chasing live inserts does not
terminate. It was correct when it ran and stale one millisecond later, because
v1 was still serving. Nothing failed. **The bug is the belief that a backfill is
a step rather than a race.**

The order that works is not the intuitive one:

```text
expand -> dual-write -> backfill -> verify -> switch reads -> contract
```

Dual-write comes **before** backfill. Then the backfill only has to catch rows
that existed when it started, a set that has stopped growing. Install the
trigger afterwards, as the lab deliberately does, and the window between them is
a permanent hole.

The verify step is a query, and it is the one to write first:

```sql
SELECT count(*) FROM events
 WHERE location IS NOT NULL AND location_name IS NULL;
```

Zero, twice, five minutes apart. Not zero once.

**What each statement costs**, on 20,000 rows:

```text
ADD COLUMN (nullable)              0.17 ms
ADD COLUMN NOT NULL DEFAULT 'x'    0.13 ms
UPDATE every row                   9.01 ms
DROP COLUMN                        9.09 ms
```

`ADD COLUMN` is a catalogue edit -- existing rows are untouched and the missing
value is materialized on read -- so it is O(1) in table size and safe at any
hour. `DROP COLUMN` and the full `UPDATE` are O(rows) and hold a write lock
throughout. They belong in the contract phase, scheduled and batched, behind the
verify query, and never in the same deploy as the expand.

## The experiment

```powershell
cd modules\store-lab
python migrate_lab.py
```

## Boundary

- **The version number is a range.** Both v1 and v2 run correctly against schema
  version 2, so the startup assertion is `MIN_SCHEMA <= current <= MAX_SCHEMA`,
  not equality. A build demanding equality cannot be deployed without downtime,
  by construction; a build declaring a window states in code exactly how far
  back you may roll. As in [eval-set-versioning.md](eval-set-versioning.md), the
  stamp is worthless unless something refuses to run when it disagrees.
- **Engine differences change the numbers, not the shape.** Postgres has had
  metadata-only `ADD COLUMN` with a constant default since 11, `DROP COLUMN`
  there is metadata-only with space reclaimed by `VACUUM`, and it is `ALTER TYPE`
  that rewrites. Additive is cheap and destructive is not, so separate the
  deploys -- that part carries.
- **Not covered:** lock queueing (in Postgres, a blocked `ALTER` blocks every
  reader behind it, which is how a "metadata-only" change takes an application
  down), `NOT VALID` constraints, concurrent index builds, and multi-node
  replication lag. This is a single-writer fixture and cannot pose those
  honestly.
- **Triggers are one way to dual-write and not the best one.** Writing both
  columns in the application is more visible and easier to remove; a trigger is
  the tool when you cannot deploy to every writer, which is exactly the case
  during a rolling deploy of the writer itself.
- **The contract phase is the one that gets forgotten.** A schema left in the
  expanded state forever accumulates columns nothing reads, and the next
  engineer cannot tell which of the pair is authoritative.

## Cards

### 1. [misconception] A migration renames a column and the new code is deployed in the same release. What breaks?

**Answer:** Every instance of the old code, on every request, from the moment
the migration commits until the last one drains -- and rolling back the code
does not fix it, because the schema does not roll back with it.

**Why:** During any rolling deploy two versions are live against one database.
In the lab, `v1_read` and `v1_write` both raised `no such column` immediately
after the rename while v2 was fine.

**Boundary:** This is invisible in staging, where only one version usually runs,
and invisible in review, where the diff shows one correct-looking statement.

**Tags:** `migrations` `misconception` `general-principle`

---

### 2. [failure] You ran expand, then a batched backfill, then verified zero rows unmigrated, then installed dual-write. Later, 75% of one version's writes are missing from the new columns. Where did they go?

**Answer:** Into the window between the backfill and the dual-write. The
backfill was bounded to rows existing at its start; the old code kept writing
old-shaped rows the whole time, and nothing was populating the new columns for
them.

**Why:** Measured in the lab: 451 of 604 rows written by v1 during the migration
were invisible to v2. Every job reported success and no constraint fired.

**Boundary:** The fix is ordering, not effort -- dual-write *before* backfill, so
the backfill's working set stops growing. The verify query must also be run
twice, minutes apart: a single zero cannot distinguish "complete" from "the race
has not produced a row yet".

**Tags:** `migrations` `failure` `general-principle`

---

### 3. [decision] Which schema changes may ship in the same deploy as the code that needs them?

**Answer:** Only additive ones -- new nullable columns, new tables, new indexes.
Anything destructive (drop, rename, type change, adding NOT NULL) goes in a
separate, later deploy after every reader of the old shape is gone.

**Why:** `ADD COLUMN` is a catalogue edit, O(1) in table size and invisible to
queries written before it. `DROP COLUMN` and a full `UPDATE` are O(rows) and
hold a write lock -- measured at ~50x the additive statements on 20,000 rows,
and the ratio grows with the table.

**Boundary:** "Additive is safe" is about the *statement*, not the deploy. In
Postgres even a metadata-only `ALTER` must first acquire a lock, and a long
transaction ahead of it in the queue will block every reader behind it.

**Tags:** `migrations` `decision` `general-principle`
