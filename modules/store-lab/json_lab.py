"""The same field as a column and as a JSON path, on 40,000 rows.

    python json_lab.py

The choice is usually argued as flexibility against performance, which is the
least interesting axis and the only one people measure. This lab measures it
anyway -- section 2 -- and then measures the three things that actually decide
it: what a typo does, what a null means, and what indexing a path costs you in
the freedom you chose JSON for.

SQLite, not Postgres. SQLite has no `JSONB` type: `extra` is TEXT and every
read reparses it, so the constant factor here is *worse* than Postgres jsonb,
which stores a parsed binary form. The structural results -- the full scan, the
silent typo, the collapsed nulls -- are properties of schemaless access and hold
in both.
"""
from __future__ import annotations

import sqlite3

import store

N = 40_000
conn = store.build()
store.seed_bulk(conn, N)

# Write the same three facts into JSON as well as into columns. `sentiment` and
# `source_kind` exist ONLY in JSON: they are the new fields, the ones that have
# not earned a column yet.
conn.execute("""
    UPDATE events SET extra = json_object(
        'location',    location,
        'sentiment',   CASE abs(random()) % 3 WHEN 0 THEN 'negative'
                                              WHEN 1 THEN 'neutral'
                                              ELSE 'positive' END,
        'source_kind', CASE abs(random()) % 4 WHEN 0 THEN 'regulator'
                                              ELSE 'news' END)
""")
conn.commit()
conn.execute("ANALYZE")

rows = conn.execute("SELECT count(*) FROM events").fetchone()[0]
print(f"{rows:,} events. `location` exists as a column AND at $.location in "
      f"`extra`.\n")

# --------------------------------------------------------------------------- #
store.rule("1. The plans, before any index")
# --------------------------------------------------------------------------- #
COL = "SELECT count(*) FROM events WHERE location = '深圳市'"
JSON = "SELECT count(*) FROM events WHERE json_extract(extra, '$.location') = '深圳市'"
for label, sql in (("column", COL), ("json path", JSON)):
    print(f"  {label:<10} {store.plan(conn, sql)}")
print("  Identical: both are full scans, because neither is indexed. The JSON")
print("  path is not disadvantaged *yet*, and this is the state every schema is")
print("  in on the day the field is added.")
print()

# --------------------------------------------------------------------------- #
store.rule("2. Then the obvious index goes on, and only one query moves")
# --------------------------------------------------------------------------- #
base_col, base_json = store.timed(conn, COL), store.timed(conn, JSON)
print(f"  unindexed   column {base_col:7.2f} ms   json {base_json:7.2f} ms   "
      f"({base_json / base_col:.2f}x)")

conn.execute("CREATE INDEX ix_loc ON events(location)")
conn.execute("ANALYZE")
i_col, i_json = store.timed(conn, COL), store.timed(conn, JSON)
print(f"  ix on col   column {i_col:7.2f} ms   json {i_json:7.2f} ms   "
      f"({i_json / i_col:.2f}x)")
print(f"              column plan {store.plan(conn, COL)}")
print(f"              json   plan {store.plan(conn, JSON)}")

# SQLite indexes expressions. So does Postgres. This is the fix everyone reaches
# for, and it works.
conn.execute("CREATE INDEX ix_json_loc ON events(json_extract(extra, '$.location'))")
conn.execute("ANALYZE")
x_col, x_json = store.timed(conn, COL), store.timed(conn, JSON)
print(f"  + expr ix   column {x_col:7.2f} ms   json {x_json:7.2f} ms   "
      f"({x_json / x_col:.2f}x)")
print(f"              json   plan {store.plan(conn, JSON)}")
print()
print()
print("  Two things happened. Unindexed, the JSON scan is already several times")
print("  slower than the column scan -- that is 40,000 reparses of a text blob,")
print("  and it is the part Postgres jsonb genuinely fixes by storing a parsed")
print("  form. Then the column index makes the gap enormous, and the expression")
print("  index closes it again to a small constant.")
print()
print("  The gap closes. An expression index on a JSON path is a real index with")
print("  real seek behaviour, and anyone who tells you JSON columns cannot be")
print("  indexed has not tried. The performance argument is, on this evidence,")
print("  close to a non-argument.")
print()
print("  Now read the DDL that closed it:")
print("      CREATE INDEX ix_json_loc ON events(json_extract(extra, '$.location'))")
print("  The path is written into the schema. A field you index is a field you")
print("  have named, typed by usage, and committed to -- you have made the")
print("  relational decision, in a place where nothing validates the spelling and")
print("  no `information_schema` query will list it as a column. **JSON does not")
print("  save you from schema design. It defers it to the point where it is")
print("  unenforced.**")
print()

# --------------------------------------------------------------------------- #
store.rule("3. The typo")
# --------------------------------------------------------------------------- #
try:
    conn.execute("SELECT count(*) FROM events WHERE locaton = '深圳市'").fetchone()
    print("  column typo: no error (unexpected)")
except sqlite3.OperationalError as exc:
    print(f"  column typo -> OperationalError: {exc}")

bad = conn.execute(
    "SELECT count(*) FROM events WHERE json_extract(extra, '$.locaton') = '深圳市'"
).fetchone()[0]
good = conn.execute(COL).fetchone()[0]
print(f"  json typo   -> {bad} rows returned, silently (correct answer: {good})")
print()
print("  This is the asymmetry that matters and it is not about speed. A")
print("  misspelled column is a startup error caught by the first test run. A")
print("  misspelled JSON path is a valid query returning zero rows, which reads")
print("  as 'no events in 深圳市 this week' -- a plausible business fact. The")
print("  same shape appears in a filter (silently no-ops), a join key (silently")
print("  matches nothing), and a dashboard (silently goes to zero).")
print()
print("  Grader implication, straight from ../deterministic-graders.md: a rule")
print("  over a JSON path cannot distinguish 'the field is absent' from 'the")
print("  path is wrong'. Assert the *presence* of the path on a known row before")
print("  trusting any aggregate computed from it.")
print()

# --------------------------------------------------------------------------- #
store.rule("4. Three different nulls, one answer")
# --------------------------------------------------------------------------- #
conn.executemany("INSERT INTO events (record_id, event_type, source_id, extra)"
                 " VALUES (?,?,1,?)", [
    ("X-absent", "investment", '{"sentiment":"neutral"}'),          # key missing
    ("X-jsonnull", "investment", '{"location":null}'),              # JSON null
    ("X-empty", "investment", '{"location":""}'),                   # empty string
])
conn.commit()
print(f"  {'record':<12} {'stored extra':<32} {'json_extract':<14} "
      f"{'IS NULL':<8} json_type")
for rid in ("X-absent", "X-jsonnull", "X-empty"):
    raw, val, isnull, typ = conn.execute(
        "SELECT extra, json_extract(extra,'$.location'),"
        " json_extract(extra,'$.location') IS NULL,"
        " json_type(extra,'$.location') FROM events WHERE record_id=?",
        (rid,)).fetchone()
    print(f"  {rid:<12} {raw:<32} {str(val):<14} {isnull:<8} {typ}")
print()
print("  `json_extract` collapses 'the extractor never wrote this field' and 'the")
print("  source did not state a location' into the same SQL NULL. Those are the")
print("  two halves of the empty-vs-wrong split that ../structured-outputs.md")
print("  found to be the metric deciding whether to turn a schema on -- and this")
print("  storage choice destroys the distinction *after*")
print("  the extractor correctly made it.")
print()
print("  `json_type` recovers it: 'null' for an explicit JSON null, NULL for an")
print("  absent key. Nobody writes that in a report query. A nullable column with")
print("  a NOT NULL `extraction_status` beside it makes the distinction")
print("  unmissable instead of merely recoverable.")
print()

# --------------------------------------------------------------------------- #
store.rule("5. What it costs on disk, and what that buys")
# --------------------------------------------------------------------------- #
json_bytes = conn.execute("SELECT sum(length(extra)) FROM events").fetchone()[0]
loc_bytes = conn.execute("SELECT sum(length(location)) FROM events").fetchone()[0]
keys = len('{"location":"","sentiment":"","source_kind":""}')
print(f"  extra column total      {json_bytes:>10,} bytes")
print(f"  location column total   {loc_bytes:>10,} bytes")
print(f"  key names alone         {keys * rows:>10,} bytes "
      f"({keys} bytes x {rows:,} rows, ~{keys * rows / json_bytes:.0%} of the "
      f"JSON)")
print()
print("  Three quarters of the JSON is the same three key names, repeated forty")
print("  thousand times, and the payload is 24x the column that holds one of the")
print("  same values. Postgres jsonb does not fix this either -- it stores keys")
print("  per row too. It is rarely enough to matter on its own; it is quoted here")
print("  so that the decision gets made on the reasons that do.")
print()

# --------------------------------------------------------------------------- #
store.rule("6. The rule this lab produces")
# --------------------------------------------------------------------------- #
print("  Put a field in JSON when all three hold:")
print("    - nothing filters, joins, or sorts on it")
print("    - its shape is still changing week to week")
print("    - a wrong value is visible to a human before it is used by code")
print()
print("  Promote it to a column the moment the first WHERE clause touches it,")
print("  because that WHERE clause is the schema decision. You are choosing")
print("  between making it in DDL, where a typo is an error, and making it in an")
print("  index expression, where a typo is a zero.")
print()
print("  For Sinoscope specifically: `event_type`, `event_date`, `location` and")
print("  every provenance field are columns -- all four are filtered on. A")
print("  per-event-type payload (the fields only a sanction record has) is the")
print("  legitimate JSON case, and it needs `json_type` checks in the graders")
print("  rather than trust.")
