# JSONB vs relational modelling

**Micro module.** One mechanism, one experiment, three cards. Runs against
[store-lab/](store-lab/).

**Capability:** JSONB vs relational modelling (Layer 1c, Aware -> Independent).
Map evidence: "A defended choice per field, with the query that decided it."

---

## The problem

A field arrives whose shape is still changing. It goes into the `extra` JSON
column, because that is what the JSON column is for. Six months later, something
filters on it.

## The wrong model

**"JSON is flexible but slow, so trade flexibility against performance."**

This is the axis everybody measures and it is close to a non-issue. On 40,000
rows, the same lookup as a column and as a JSON path:

```text
unindexed                column   3.46 ms   json  23.42 ms   (6.8x)
index on the column      column   0.30 ms   json  24.10 ms   (80x)
+ index on the JSON path column   0.29 ms   json   0.49 ms   (1.7x)
```

The expression index closes the gap to a small constant. Anyone who says JSON
paths cannot be indexed has not tried it. Performance is not what decides this.

## The mechanism

Read the DDL that closed the gap:

```sql
CREATE INDEX ix_json_loc ON events(json_extract(extra, '$.location'));
```

The path is now written into the schema. You have named the field, committed to
its type by usage, and made the relational decision -- in a place where nothing
validates the spelling and no catalogue query will list it as a column. **JSON
does not save you from schema design; it defers it to a point where it is
unenforced.**

Three consequences, in order of how much damage they do.

**A typo changes category.**

```text
column typo -> OperationalError: no such column: locaton
json   typo -> 0 rows, silently        (correct answer: 7,899)
```

A misspelled column is a startup error caught by the first test run. A
misspelled JSON path is a valid query returning zero rows, which reads as a
business fact -- no events in 深圳市 this week. The same shape appears in a
filter that silently no-ops, a join key that silently matches nothing, and a
dashboard that silently goes to zero.

**Three different nulls collapse into one.**

```text
record       stored extra               json_extract  IS NULL  json_type
X-absent     {"sentiment":"neutral"}    None          1        None
X-jsonnull   {"location":null}          None          1        null
X-empty      {"location":""}            ''            0        text
```

"The extractor never wrote this field" and "the source did not state a location"
become the same SQL `NULL`. Those are the two halves of the empty-vs-wrong split
that [structured-outputs.md](structured-outputs.md) found to be the metric
deciding whether to turn a schema on -- and this storage choice destroys the
distinction *after* the extractor correctly made it. `json_type` recovers it and
nobody writes `json_type` in a report query.

**The keys are stored per row.** Three quarters of the `extra` column here is
the same three key names repeated 40,000 times, and the payload is 24x the
column holding one of the same values. Postgres `jsonb` does not fix this; it
stores keys per row too. Rarely decisive on its own, quoted so the decision gets
made on the reasons that are.

## The experiment

```powershell
cd modules\store-lab
python json_lab.py
```

Sections 3 and 4 are the module. Section 2 is the argument everyone expects,
included so it can be set aside.

## Boundary

- **SQLite is not Postgres here, and the difference is real.** SQLite has no
  `jsonb` type: `extra` is `TEXT` and every read reparses it, which is why the
  unindexed JSON scan is ~7x slower rather than ~2x. Postgres stores a parsed
  binary form and genuinely fixes that constant. The structural results -- the
  silent typo, the collapsed nulls, the index expression naming the path -- are
  properties of schemaless access and hold identically in both.
- **The rule this produces:** JSON when *all three* hold -- nothing filters,
  joins or sorts on it; its shape is still changing; and a wrong value is seen
  by a human before it is used by code. Otherwise a column.
- **A grader over a JSON path needs a presence assertion.** A rule cannot
  distinguish "field absent" from "path wrong", so assert the path resolves on a
  known row before trusting any aggregate computed from it. This is a real gap
  in the gold-free graders of [deterministic-graders.md](deterministic-graders.md).
- **Not covered:** GIN indexes over whole documents, containment operators
  (`@>`), and schema validation extensions. Postgres can index every key at once
  with GIN, which weakens the "you must name the path" argument for existence
  queries -- though not for the typo or the null-collapse.
- **The legitimate JSON case survives all of this:** a per-event-type payload,
  where the fields a `sanction` record has are not the fields a `plant_opening`
  record has. Modelling that relationally means either a sparse table or a table
  per type.

## Cards

### 1. [misconception] Is the argument against storing a queried field in JSON a performance argument?

**Answer:** No. An expression index on a JSON path is a real index -- in the lab
it closed an 80x gap to 1.7x. The argument is that writing that index means
naming the path in DDL, where nothing validates it.

**Why:** Indexing the path *is* the schema decision, made in the one place with
no spelling check, no type, and no catalogue entry. You have paid the cost of
schema design and received none of its guarantees.

**Boundary:** Postgres `jsonb` narrows the unindexed gap further by storing a
pre-parsed form; SQLite reparses text on every row, so the raw numbers here
overstate the runtime cost and understate nothing else.

**Tags:** `data-modelling` `misconception` `general-principle`

---

### 2. [failure] A dashboard tile that counted events in 深圳市 has read zero for three weeks. The query is `WHERE json_extract(extra, '$.locaton') = '深圳市'`. Why did nothing alert?

**Answer:** A misspelled JSON path is a valid expression that evaluates to NULL
for every row, so the query is well-formed and returns an empty result. A
misspelled column name would have raised `no such column` at the first execution.

**Why:** The failure mode of schemaless access is a plausible answer rather than
an error. Zero events in a city for three weeks is indistinguishable from a slow
news month unless something asserts the path resolves.

**Boundary:** The same shape hits filters (silently no-op), join keys (silently
match nothing), and any aggregate downstream. The check is a presence assertion
on a known row, not a review of the query text.

**Tags:** `data-modelling` `failure` `general-principle`

---

### 3. [decision] Your extractor correctly distinguishes "the source stated no location" from "extraction did not run for this field". Where can that distinction survive, and where does it die?

**Answer:** It dies in a JSON path: `json_extract` returns SQL NULL for both an
absent key and an explicit JSON null. It survives as a nullable column beside a
`NOT NULL` status column.

**Why:** That distinction is the empty-vs-wrong split, which
[structured-outputs.md](structured-outputs.md) measured as the metric deciding
whether to enable a constrained schema at all. Destroying it in storage discards
the one signal separating a safe abstention from a confabulation.

**Boundary:** `json_type()` does recover it -- 'null' for an explicit null, NULL
for an absent key -- so the distinction is recoverable but not *unmissable*, and
no report query will ever be written that way.

**Tags:** `data-modelling` `decision` `project-specific`
