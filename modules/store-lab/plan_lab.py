"""Predict the plan, then read it. Six cases, on 40,000 real rows.

    python plan_lab.py

The map's evidence line is "read an EXPLAIN ANALYZE and predict the effect of an
index *first*". The prediction is the whole exercise, so the predictions are
written into this file as data and the script scores them. A prediction made
after seeing the plan is a description.

Read PREDICTIONS below, decide whether you agree with each, and only then run
the script.
"""
from __future__ import annotations

import store

N = 40_000
conn = store.build()
store.seed_bulk(conn, N)
conn.commit()

# Every prediction is the textbook answer, written before running anything.
# `uses_index` is about the plan; `speedup` is the order of magnitude expected.
PREDICTIONS = {
    "A high-cardinality equality": dict(uses_index=True, speedup="large"),
    "B skewed equality, common value": dict(uses_index=False, speedup="none"),
    "C skewed equality, rare value": dict(uses_index=True, speedup="large"),
    "D prefix LIKE": dict(uses_index=True, speedup="large"),
    "E infix LIKE": dict(uses_index=False, speedup="none"),
    "F function on the column": dict(uses_index=False, speedup="none"),
}

QUERIES = {
    "A high-cardinality equality":
        "SELECT count(*) FROM events WHERE record_id = 'B20000'",
    "B skewed equality, common value":
        "SELECT count(*) FROM events WHERE event_type = 'investment'",
    "C skewed equality, rare value":
        "SELECT count(*) FROM events WHERE event_type = 'sanction'",
    "D prefix LIKE":
        "SELECT count(*) FROM events WHERE location LIKE '深圳%'",
    "E infix LIKE":
        "SELECT count(*) FROM events WHERE location LIKE '%圳市%'",
    "F function on the column":
        "SELECT count(*) FROM events WHERE substr(event_date, 1, 4) = '2026'",
}

print(f"{N:,} synthetic events. event_type is skewed: investment ~40%, "
      f"sanction ~10%.\n")

# --------------------------------------------------------------------------- #
store.rule("1. Baseline: no index anywhere")
# --------------------------------------------------------------------------- #
base = {}
for name, sql in QUERIES.items():
    base[name] = store.timed(conn, sql)
    rows = conn.execute(sql).fetchone()[0]
    print(f"  {name:<32} {base[name]:6.2f} ms  {rows:>6,} rows  "
          f"{store.plan(conn, sql)[0]}")
print()

# --------------------------------------------------------------------------- #
store.rule("2. Indexes on, statistics off")
# --------------------------------------------------------------------------- #
conn.executescript("""
    CREATE INDEX ix_rec  ON events(record_id);
    CREATE INDEX ix_type ON events(event_type);
    CREATE INDEX ix_loc  ON events(location);
    CREATE INDEX ix_date ON events(event_date);
""")
print("  (no ANALYZE yet -- the planner has the indexes but no idea what is in")
print("  them, which is the state of every database nobody has run ANALYZE on)")
print()
noanalyze = {}
for name, sql in QUERIES.items():
    noanalyze[name] = (store.timed(conn, sql), store.plan(conn, sql)[0])
    print(f"  {name:<32} {noanalyze[name][0]:6.2f} ms  {noanalyze[name][1]}")
print()

# --------------------------------------------------------------------------- #
store.rule("3. ANALYZE, then score the predictions")
# --------------------------------------------------------------------------- #
conn.execute("ANALYZE")
print(f"  {'case':<32} {'predicted':<10} {'plan':<10} {'ms':>7} {'vs base':>9}  "
      f"verdict")
for name, sql in QUERIES.items():
    ms = store.timed(conn, sql)
    p = store.plan(conn, sql)[0]
    used = "SEARCH" in p
    pred = PREDICTIONS[name]["uses_index"]
    ratio = base[name] / ms if ms else float("inf")
    verdict = "ok" if used == pred else "PREDICTION WRONG"
    print(f"  {name:<32} {str(pred):<10} {str(used):<10} {ms:7.2f} "
          f"{ratio:8.1f}x  {verdict}")
print()
for name in QUERIES:
    print(f"  {name}\n      {store.plan(conn, QUERIES[name])[0]}")
print()

# --------------------------------------------------------------------------- #
store.rule("4a. Case A was never a fair test")
# --------------------------------------------------------------------------- #
print("  Case A was already a SEARCH in section 1, before a single CREATE INDEX")
print("  ran. `record_id TEXT UNIQUE` built `sqlite_autoindex_events_1`, and the")
print("  same is true of every PRIMARY KEY and UNIQUE constraint in the schema:")
for tbl, idx, stat in conn.execute(
        "SELECT tbl, idx, stat FROM sqlite_stat1 WHERE idx LIKE 'sqlite_auto%'"
        " ORDER BY tbl"):
    print(f"    {tbl:<10} {idx:<34} {stat}")
print()
print("  So `CREATE INDEX ix_rec` was redundant the moment it was written -- a")
print("  second copy of an index that already existed, paid for on every insert.")
print("  Your index inventory is not your CREATE INDEX statements; it is those")
print("  plus every uniqueness constraint you declared. Read it from the")
print("  catalogue, not from the migration files.")
print()

# --------------------------------------------------------------------------- #
store.rule("4b. Case B: covering beat selectivity")
# --------------------------------------------------------------------------- #
b_ms = store.timed(conn, QUERIES["B skewed equality, common value"])
b_plan = store.plan(conn, QUERIES["B skewed equality, common value"])[0]
print(f"  the 40% value: {b_plan!r}")
print(f"  {b_ms:.2f} ms against {base['B skewed equality, common value']:.2f} "
      f"ms unindexed.")
print()
print("  The textbook prediction -- 'an index on a low-selectivity column will")
print("  not be used, the planner will scan' -- is wrong here, and why is the")
print("  case. `count(*)` needs no column the index does not carry, so the whole")
print("  query runs inside the index, which is narrower than the table. Reading")
print("  40% of a narrow structure beats reading 100% of a wide one. **Covering,")
print("  not selectivity, decided it** -- note the word COVERING in the plan.")
print()
print("  Ask for a column the index does not carry and the seek stops being free:")
WIDE = "SELECT sum(confidence) FROM events WHERE event_type = ?"
for value, share in (("investment", "~40%"), ("sanction", "~10%")):
    print(f"    {value:<12} ({share:<5}) {store.timed(conn, WIDE, (value,)):6.2f}"
          f" ms  {store.plan(conn, WIDE, (value,))[0]}")
print()
print("  Same plan for both values, and a several-fold runtime difference between")
print("  them. That is not the planner adapting -- it is the planner *not*")
print("  adapting. Here is everything ANALYZE recorded about that index:")
for tbl, idx, stat in conn.execute(
        "SELECT tbl, idx, stat FROM sqlite_stat1 WHERE idx='ix_type'"):
    print(f"    {idx} -> {stat!r}  (rows, average rows per distinct value)")
print()
print("  One average, 6,669, for a column whose true per-value counts run from")
print("  ~2,000 to ~16,000. `sqlite_stat1` has no histogram, so a skewed column")
print("  gets one plan for every value and the common value is planned as if it")
print("  were the average. Postgres does keep per-value statistics (`most_common_")
print("  vals` in `pg_stats`), and SQLite can too if compiled with STAT4 -- which")
print("  is the actual reason 'it is fast in staging' survives to production.")
print()

# --------------------------------------------------------------------------- #
store.rule("5. Case D: why the prefix LIKE did not seek")
# --------------------------------------------------------------------------- #
LK = "SELECT count(*) FROM events WHERE location LIKE '深圳%'"
GL = "SELECT count(*) FROM events WHERE location GLOB '深圳*'"
RG = ("SELECT count(*) FROM events WHERE location >= '深圳'"
      " AND location < '深圳' || char(0x10FFFF)")
print(f"  LIKE '深圳%'   {store.plan(conn, LK)[0]}")
print(f"  GLOB '深圳*'   {store.plan(conn, GL)[0]}")
print(f"  explicit range {store.plan(conn, RG)[0]}")
conn.execute("PRAGMA case_sensitive_like=ON")
print(f"  LIKE, case_sensitive_like=ON")
print(f"                 {store.plan(conn, LK)[0]}")
conn.execute("PRAGMA case_sensitive_like=OFF")
print()
print("  The blocker is not the wildcard and not the Chinese text. It is that")
print("  **LIKE is case-insensitive by default**, so 'A%' must also match 'a%',")
print("  and one contiguous index range cannot express that. Turn case-")
print("  sensitivity on and the same query seeks. GLOB, which is case-sensitive,")
print("  seeks without being asked.")
print()
print("  This is a collation problem wearing a syntax costume, and it transfers")
print("  exactly: in Postgres, `LIKE 'x%'` uses a b-tree index only under the C")
print("  collation or an index built with `text_pattern_ops`. Same cause, same")
print("  fix, different spelling. The portable version is the explicit range")
print("  above -- ugly, and it seeks everywhere.")
print()

# --------------------------------------------------------------------------- #
store.rule("6. Composite order, and the optimization that hides the mistake")
# --------------------------------------------------------------------------- #
Q = ("SELECT record_id FROM events WHERE event_type = 'sanction'"
     " ORDER BY event_date DESC LIMIT 10")
print(f"  query: WHERE event_type = ? ORDER BY event_date DESC LIMIT 10")
print(f"  single-column indexes only: {store.timed(conn, Q):6.2f} ms  "
      f"{store.plan(conn, Q)}")
distinct = conn.execute(
    "SELECT count(DISTINCT event_date), count(DISTINCT source_id) FROM events"
).fetchone()
print(f"  (event_date has {distinct[0]:,} distinct values, source_id "
      f"{distinct[1]:,})")
print()
for cols in ("event_type, event_date", "event_date, event_type",
             "source_id, event_type"):
    conn.execute(f"CREATE INDEX ix_pair ON events({cols})")
    conn.execute("ANALYZE")
    print(f"  ({cols:<22}) {store.timed(conn, Q):6.2f} ms  {store.plan(conn, Q)}")
    conn.execute("DROP INDEX ix_pair")
    conn.execute("ANALYZE")
print()
print("  `(event_type, event_date)` is the textbook answer and it wins: seek to")
print("  the event_type prefix, then walk a date order that already exists")
print("  inside it, no sort node at all.")
print()
print("  `(event_date, event_type)` is the textbook mistake -- the constrained")
print("  column is not on the left edge -- and it is *just as fast here*. Read")
print("  its plan: `ANY(event_date) AND event_type=?` is a **skip-scan**. With")
print("  1,344 distinct dates over 40,000 rows, roughly 30 rows repeat per date,")
print("  and SQLite decides it is cheaper to seek once per distinct leading value")
print("  than to scan. Postgres has no skip-scan; the same index there would be")
print("  the mistake the textbook says it is.")
print()
print("  Make the leading column unique -- `(source_id, event_type)`, 40,000")
print("  distinct values, nothing to skip -- and the rescue disappears. The")
print("  planner abandons the pair index entirely, falls back to the single-")
print("  column `ix_type` and sorts in a temp b-tree: ~100x the two working")
print("  plans, and exactly the number it had before any pair index existed.")
print("  An index the planner declines to use is pure write-time cost.")
print()
print("  So the rule survives, with its mechanism attached: **equality columns")
print("  first, then the range or sort column** -- and the reason a wrong order")
print("  sometimes goes unnoticed is that a low-cardinality leading column can be")
print("  skipped over. That is a property of your data distribution, not of your")
print("  schema, and it changes as the data does.")
print()

# --------------------------------------------------------------------------- #
store.rule("7. The join everyone writes")
# --------------------------------------------------------------------------- #
J = ("SELECT count(*) FROM events e JOIN actors a USING (event_id)"
     " WHERE a.name = '稀土永磁研究院'")
print(f"  needle appears in ~0.02% of actor rows.")
print(f"  no index on actors(name): {store.timed(conn, J):7.2f} ms  "
      f"{store.plan(conn, J)}")
conn.execute("CREATE INDEX ix_actor_name ON actors(name)")
conn.execute("ANALYZE")
print(f"  with index:               {store.timed(conn, J):7.2f} ms  "
      f"{store.plan(conn, J)}")
print()
print("  Read the plan order, not just the timing. Before the index the planner")
print("  scans `actors` and probes `events` by primary key; after it, it seeks")
print("  `actors` by name and probes `events`. The join order flipped to put the")
print("  most selective table first, and that -- not the index itself -- is where")
print("  the time went. **An index changes which table is driven, and the driving")
print("  table decides the cost.**")
print()

# --------------------------------------------------------------------------- #
store.rule("8. What to carry into the project")
# --------------------------------------------------------------------------- #
print("  - Predict the *plan*, not the runtime. The plan is deterministic given")
print("    the statistics; the runtime is contaminated by cache state. Four of")
print("    the six predictions above were right about the plan and two were")
print("    wrong, and both misses were about *why* an index is usable at all --")
print("    covering, and collation -- not about selectivity.")
print("  - Run ANALYZE. Postgres autovacuum does it for you; SQLite does not,")
print("    and a stale stat is how a plan changes overnight without a deploy.")
print("  - Selectivity is a property of the value, not of the column, and your")
print("    planner may not know that. One plan serves every value of a skewed")
print("    column, so the common value is planned as the average and only the")
print("    tail of the latency distribution shows it -- see the percentile")
print("    argument in ../budgets-and-timeouts.md.")
print("  - Any function around the column disables the index. Rewrite to a range")
print("    (case F) or index the expression (../jsonb-vs-relational.md section 2).")
print("  - An optimization can hide a design mistake for as long as the data")
print("    distribution holds. Skip-scan rescued a badly ordered index at 30 rows")
print("    per distinct value; nothing announces the day that ratio changes.")
