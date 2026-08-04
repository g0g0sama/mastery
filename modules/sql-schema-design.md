# SQL and schema design

**Micro module.** One mechanism, one experiment, three cards. Runs against
[store-lab/](store-lab/).

**Capability:** SQL and schema design (Layer 1c, Working -> Independent). Map
evidence: "A schema for events + sources + claims that survives three new
fields."

---

## The problem

Three fields arrive after the schema is in production: a per-event sentiment, an
entity id for each actor, and character offsets for each claim. The question is
not whether the schema can accept them -- almost any schema can -- but what each
one costs, and who pays.

## The wrong model

**"Survives means the migration is easy."**

It is the DDL statement count that gets argued about in review, and it is the
column that carries no information. In the lab, all three candidate schemas
absorbed all three fields: one `ALTER TABLE ... ADD COLUMN` each, or none at all
for the EAV design, and **not a single reader written before the change returned
a different answer afterwards**.

That null result is worth keeping. An additive change breaks nothing, in any
shape, which is why the DDL count cannot distinguish a good schema from a bad
one -- and why the expand phase of a migration is the safe phase
([migrations-and-versioning.md](migrations-and-versioning.md)).

The cost shows up later, when the *data* changes.

## The mechanism

Three shapes for the same twelve records:

```text
normalized   events / actors(event_id, ordinal, name) / claims / sources
wide         one row per event, actors = '宁德时代|宝马集团'
eav          (record_id, attribute, ordinal, value)
```

Two things go wrong before any new field arrives at all.

**The wide schema answers a question wrongly.** "Which events involve 中国石化"
becomes `actors LIKE '%中国石化%'`, and 中国石化销售公司 is a different legal
entity whose name contains it:

```text
normalized   actor = '中国石化' -> ['R01']
wide         actor = '中国石化' -> ['R01', 'R99']
eav          actor = '中国石化' -> ['R01']
```

Flattening a repeating group into a delimited string converts equality into
substring matching. In a Chinese corpus that is not an edge case -- company
names contain company names constantly.

**The EAV schema loses the type, and the type was doing work.** Asking for deals
over 20亿元 against a `TEXT` value column:

```text
truth                      R02 R04 R06 R08 R10 R11
value > '20'               R01 R03 R04 R05 R06 R07 R08 R11 R12
wrongly included  5, 3, 7, 9, 8亿   wrongly excluded  100, 120亿
```

Under text collation `'5' > '20'` and `'100' < '20'`. The answer is non-empty,
plausibly sized, and wrong at both ends. `CAST(value AS REAL)` fixes that query
and not the column, because the column has no type to fix.

**Then the correction arrives.** After each actor gains an `entity_id`, a
labeller removes one actor from R03 -- 广晟有色 was never in that document. In
the wide schema the name list is edited and the id list is not:

```text
2 of 6 entity ids are now attached to the wrong actor
wide says 五矿稀土 -> E-GDR;  normalized says 五矿稀土 -> E-MMR
```

No error, no constraint violation, no reader failure. Both strings are still
well-formed and plausibly sized. Every downstream join now attributes those
events to the wrong company.

In the normalized schema the same correction was a `DELETE`, and the id went
with the row because it was *on* the row. The misalignment is not unlikely
there; it is unrepresentable.

## The experiment

```powershell
cd modules\store-lab
python schema_lab.py     # sections 1, 2 and 3b are the argument
```

Section 3 is the null result -- nine cells, zero readers broken -- and section
3b is what it was hiding.

## Boundary

- **This is an argument about grain, not about normal forms.** What made the
  normalized schema survive was one decision made on day one: every repeating
  group got its own table with an explicit `ordinal`. Fields arrive weekly and
  cost an `ALTER`. A grain that was wrong on day one costs a rewrite of every
  reader that ever touched it.
- **EAV's zero-DDL property is real.** It genuinely absorbed all three changes
  with no schema change at all. The invoice is section 2: no types, no
  constraints, and no way to state that the id at ordinal 3 belongs to the actor
  at ordinal 3. It relocates the schema from the database to the readers, where
  it is unenforced and duplicated per reader.
- **A denormalized read model is a different thing** and is not what this
  measures. Derived, rebuildable, and never the source of truth is a legitimate
  design; the wide table above is the source of truth, which is the failure.
- **Nullable is a feature.** `event_date` is nullable because R09's source
  states a month and no day. A schema that cannot represent "not stated" forces
  the extractor to invent -- measured directly in
  [structured-outputs.md](structured-outputs.md), where a required field turned
  abstention into confabulation.
- **What this does not cover:** partitioning, foreign-key enforcement under
  concurrency, and multi-tenant isolation. All three are Postgres-shaped
  questions that a single-writer SQLite fixture cannot pose honestly.

## Cards

### 1. [misconception] Two schemas each accept a new field with one `ALTER TABLE ... ADD COLUMN`, and no existing query changes its answer. What has this told you about which schema is better?

**Answer:** Nothing. An additive change breaks nothing in any shape, so DDL
count and reader breakage cannot distinguish the designs.

**Why:** In the lab, three schemas absorbed three new fields across nine cells
with zero readers broken. The difference only appeared when data changed
underneath: a labeller removing one actor misaligned 2 of 6 entity ids in the
delimited-string schema, silently.

**Boundary:** The corollary is operationally useful -- because additive changes
are invisible to old readers, the expand phase of a migration is safe to run at
any time, which is what makes expand/contract possible at all.

**Tags:** `data-modelling` `misconception` `general-principle`

---

### 2. [failure] A `WHERE actors LIKE '%中国石化%'` filter returns a record for 中国石化销售公司. Where is the bug, and what class of bug is it?

**Answer:** The bug is the schema, not the query. Storing a repeating group as a
delimited string forces every lookup to be a substring match, and substring
matching is not equality.

**Why:** Company names contain company names -- especially in Chinese, where
subsidiaries are formed by suffixing the parent's name. The query is exactly as
correct as it can be given the storage; only a row-per-actor table makes
equality expressible.

**Boundary:** No test written against the original twelve records catches this.
It requires a record whose name is a prefix of another, which is a property of
the corpus rather than of the code, so it arrives with real data and not with
the fixture.

**Tags:** `data-modelling` `failure` `project-specific`

---

### 3. [decision] A new field arrives and its shape is still changing weekly. Column, JSON blob, or EAV row?

**Answer:** JSON blob, and promote it to a column the moment the first `WHERE`
clause touches it. EAV essentially never, unless the attribute set is genuinely
open and user-defined.

**Why:** EAV buys zero-DDL flexibility with an unenforceable contract -- no
types, no constraints, no way to tie two attributes at the same ordinal
together. The lab's numeric filter returned an inverted answer at both ends
under text collation, and every reader must independently remember to `CAST`.

**Boundary:** The first `WHERE` clause is the trigger because that clause *is*
the schema decision -- you are only choosing between making it in DDL, where a
typo is an error, and making it in an index expression, where a typo is a zero.
See [jsonb-vs-relational.md](jsonb-vs-relational.md).

**Tags:** `data-modelling` `decision` `general-principle`
