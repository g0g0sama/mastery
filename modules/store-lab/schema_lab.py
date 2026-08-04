"""Three shapes for the same twelve records, and the three fields that arrive later.

    python schema_lab.py

The map's evidence line for this row is "a schema for events + sources + claims
that survives three new fields". Survives is doing the work in that sentence, so
this lab defines it as something checkable: after the change, how many DDL
statements were needed, how many rows had to be rewritten, and how many readers
written *before* the change still return the right answer.

The readers are the point. A schema that accepts a new field with one ALTER and
silently changes what an existing query returns has not survived anything.
"""
from __future__ import annotations

import store

conn = store.build()

# --------------------------------------------------------------------------- #
# The three candidates, each holding the same twelve records.
# --------------------------------------------------------------------------- #
conn.executescript("""
-- A: wide. One row per event, repeating groups flattened into a delimiter.
CREATE TABLE wide (
    record_id  TEXT PRIMARY KEY,
    event_type TEXT,
    event_date TEXT,
    location   TEXT,
    actors     TEXT,      -- '宁德时代|宝马集团'
    claims     TEXT,
    url        TEXT,
    fetched_at TEXT,
    confidence REAL
);

-- B: EAV. Nothing is a column, so nothing is ever a migration.
CREATE TABLE eav (
    record_id TEXT,
    attribute TEXT,
    ordinal   INTEGER DEFAULT 0,
    value     TEXT,
    PRIMARY KEY (record_id, attribute, ordinal)
);
""")

rows = conn.execute("""
    SELECT e.record_id, e.event_type, e.event_date, e.location, e.confidence,
           s.url, s.fetched_at, e.event_id
      FROM events e JOIN sources s USING (source_id)
     WHERE e.record_id LIKE 'R%'
""").fetchall()
for rid, etype, date, loc, conf, url, fetched, eid in rows:
    actors = [r[0] for r in conn.execute(
        "SELECT name FROM actors WHERE event_id=? ORDER BY ordinal", (eid,))]
    claims = [r[0] for r in conn.execute(
        "SELECT text FROM claims WHERE event_id=?", (eid,))]
    conn.execute("INSERT INTO wide VALUES (?,?,?,?,?,?,?,?,?)",
                 (rid, etype, date, loc, "|".join(actors), "|".join(claims),
                  url, fetched, conf))
    # amount is the deal size in 亿元 -- a field with values on both sides of a
    # digit-count boundary, which is where text collation stops being harmless.
    amount = {"R01": 5, "R02": 100, "R03": 3, "R04": 40, "R05": 7, "R06": 250,
              "R07": 9, "R08": 60, "R09": 2, "R10": 120, "R11": 30,
              "R12": 8}[rid]
    pairs = [("event_type", 0, etype), ("event_date", 0, date),
             ("location", 0, loc), ("url", 0, url), ("fetched_at", 0, fetched),
             ("confidence", 0, str(conf)), ("amount", 0, str(amount))]
    pairs += [("actor", i, a) for i, a in enumerate(actors)]
    pairs += [("claim", i, c) for i, c in enumerate(claims)]
    conn.executemany("INSERT INTO eav VALUES (?,?,?,?)",
                     [(rid, a, o, v) for a, o, v in pairs])

# One more event, added because a real corpus contains it: a company whose name
# has another company's name as a prefix.
conn.execute("INSERT INTO sources VALUES (99,'https://example.test/a/99',"
             "'2026-06-01T00:00:00Z','中国石化销售公司调整成品油价格','deadbeef')")
conn.execute("INSERT INTO events (event_id, record_id, event_type, event_date,"
             " location, source_id, confidence) VALUES"
             " (99,'R99','price_change','2026-06-01','北京',99,1.0)")
conn.execute("INSERT INTO actors VALUES (99,0,'中国石化销售公司')")
conn.execute("INSERT INTO wide VALUES ('R99','price_change','2026-06-01','北京',"
             "'中国石化销售公司','调整成品油价格','https://example.test/a/99',"
             "'2026-06-01T00:00:00Z',1.0)")
conn.executemany("INSERT INTO eav VALUES (?,?,?,?)", [
    ("R99", "event_type", 0, "price_change"), ("R99", "actor", 0, "中国石化销售公司"),
    ("R99", "confidence", 0, "1.0"), ("R99", "event_date", 0, "2026-06-01"),
])
conn.commit()

print(__doc__.split("\n\n")[0])
print()

# --------------------------------------------------------------------------- #
store.rule("1. The question every reader asks, in three schemas")
# --------------------------------------------------------------------------- #
Q_NORM = ("SELECT DISTINCT e.record_id FROM events e JOIN actors a USING (event_id)"
          " WHERE a.name = ? ORDER BY 1")
Q_WIDE = "SELECT record_id FROM wide WHERE actors LIKE '%' || ? || '%' ORDER BY 1"
Q_EAV = ("SELECT record_id FROM eav WHERE attribute='actor' AND value = ?"
         " ORDER BY 1")

needle = "中国石化"
for label, sql in (("normalized", Q_NORM), ("wide", Q_WIDE), ("eav", Q_EAV)):
    got = [r[0] for r in conn.execute(sql, (needle,))]
    print(f"  {label:<11} actor = {needle!r} -> {got}")
print()
print("  The wide schema returns an extra record, and it is not a near miss: R99")
print("  is 中国石化销售公司, a different legal entity. Flattening a repeating")
print("  group into a delimited string turns equality into substring matching,")
print("  and substring matching is wrong in exactly the cases a Chinese corpus")
print("  produces constantly -- company names that are prefixes of other company")
print("  names. This is not a style problem. It is a wrong answer that no test")
print("  written against the first twelve records would ever catch.")
print()

# --------------------------------------------------------------------------- #
store.rule("2. EAV loses the type, and the type was load-bearing")
# --------------------------------------------------------------------------- #
AMOUNTS = {"R01": 5, "R02": 100, "R03": 3, "R04": 40, "R05": 7, "R06": 250,
           "R07": 9, "R08": 60, "R09": 2, "R10": 120, "R11": 30, "R12": 8}
truth = sorted(r for r, v in AMOUNTS.items() if v > 20)
eav_amt = [r[0] for r in conn.execute(
    "SELECT record_id FROM eav WHERE attribute='amount' AND value > '20'"
    " ORDER BY 1")]
eav_cast = [r[0] for r in conn.execute(
    "SELECT record_id FROM eav WHERE attribute='amount'"
    " AND CAST(value AS REAL) > 20 ORDER BY 1")]
print("  'deals over 20亿元', against the same twelve records:")
print(f"    truth (in Python)          {truth}")
print(f"    eav, value > '20'          {eav_amt}")
print(f"    eav, CAST(value AS REAL)   {eav_cast}")
wrong_in = sorted(set(eav_amt) - set(truth))
wrong_out = sorted(set(truth) - set(eav_amt))
print(f"    wrongly included {wrong_in} (values "
      f"{[AMOUNTS[r] for r in wrong_in]}), "
      f"wrongly excluded {wrong_out} (values {[AMOUNTS[r] for r in wrong_out]})")
print()
print("  Under text collation '5' > '20' and '100' < '20', so a filter for large")
print("  deals admits a 3亿 one and drops a 250亿 one. The result is non-empty,")
print("  plausibly sized, and inverted at both ends -- the shape of bug that")
print("  survives review because the query is obviously correct and the output")
print("  is obviously a list of records.")
print()
print("  CAST fixes this query. It does not fix the column, because the column")
print("  has no type to fix: every reader must remember, forever, and the one")
print("  that forgets produces a number rather than an error. That is the trade")
print("  EAV makes -- schema flexibility bought with an unenforceable contract.")
print()

# --------------------------------------------------------------------------- #
store.rule("3. Three fields arrive")
# --------------------------------------------------------------------------- #
# Readers written before any of the changes. These run again after each one.
READERS = {
    "count by type": "SELECT event_type, count(*) FROM {t} GROUP BY 1 ORDER BY 1",
    "actor lookup": None,      # schema-specific, defined above
    "date range": "SELECT count(*) FROM {t} WHERE event_date >= '2026-03-01'",
}


def reader_results(schema: str) -> dict:
    out = {}
    if schema == "wide":
        out["count by type"] = conn.execute(
            "SELECT event_type, count(*) FROM wide GROUP BY 1 ORDER BY 1").fetchall()
        out["actor lookup"] = conn.execute(Q_WIDE, (needle,)).fetchall()
        out["date range"] = conn.execute(
            "SELECT count(*) FROM wide WHERE event_date >= '2026-03-01'").fetchall()
    elif schema == "eav":
        out["count by type"] = conn.execute(
            "SELECT value, count(*) FROM eav WHERE attribute='event_type'"
            " GROUP BY 1 ORDER BY 1").fetchall()
        out["actor lookup"] = conn.execute(Q_EAV, (needle,)).fetchall()
        out["date range"] = conn.execute(
            "SELECT count(*) FROM eav WHERE attribute='event_date'"
            " AND value >= '2026-03-01'").fetchall()
    else:
        out["count by type"] = conn.execute(
            "SELECT event_type, count(*) FROM events GROUP BY 1 ORDER BY 1").fetchall()
        out["actor lookup"] = conn.execute(Q_NORM, (needle,)).fetchall()
        out["date range"] = conn.execute(
            "SELECT count(*) FROM events WHERE event_date >= '2026-03-01'").fetchall()
    return out


before = {s: reader_results(s) for s in ("normalized", "wide", "eav")}

CHANGES = {
    # 1. A scalar. One value per event, no cardinality change.
    "sentiment (scalar)": {
        "normalized": ["ALTER TABLE events ADD COLUMN sentiment TEXT"],
        "wide": ["ALTER TABLE wide ADD COLUMN sentiment TEXT"],
        "eav": [],
    },
    # 2. A qualifier on an existing repeating group: each actor gains the id of
    #    the entity it was linked to. Distinct per actor, which is what makes a
    #    misalignment visible instead of merely possible.
    "actor_eid (per actor)": {
        "normalized": ["ALTER TABLE actors ADD COLUMN entity_id TEXT"],
        "wide": ["ALTER TABLE wide ADD COLUMN actor_eids TEXT",
                 "-- and every reader of `actors` must now zip two "
                 "delimited strings positionally"],
        "eav": ["-- ordinal already keys the actor; entity_id is a second "
                "attribute whose ordinal must agree with the first"],
    },
    # 3. Offsets into the source text, per claim. Cardinality again, plus a
    #    dependency on a column in another table.
    "claim spans (per claim)": {
        "normalized": ["-- already present: claims.span_start, claims.span_end"],
        "wide": ["ALTER TABLE wide ADD COLUMN claim_spans TEXT",
                 "-- positional zip again, now three-way"],
        "eav": ["-- two more attributes, and no constraint can express that a "
                "span belongs to the claim at the same ordinal"],
    },
}

print(f"  {'change':<24} {'schema':<11} {'DDL':<5} {'reader-visible':<14} "
      f"positional zips introduced")
for change, per_schema in CHANGES.items():
    for schema, statements in per_schema.items():
        ddl = [s for s in statements if not s.startswith("--")]
        zips = sum(1 for s in statements if "zip" in s)
        for sql in ddl:
            conn.execute(sql)
        conn.commit()
        after = reader_results(schema)
        broken = [k for k in before[schema] if before[schema][k] != after[k]]
        print(f"  {change:<24} {schema:<11} {len(ddl):<5} {len(broken):<14} "
              f"{zips}")
print()
print("  Every reader still works in all nine cells, and that is the first real")
print("  finding rather than a null result: **an additive change breaks nothing**.")
print("  ADD COLUMN with a null default is invisible to a SELECT written before")
print("  it. This is the property the expand/contract migration in")
print("  ../migrations-and-versioning.md is built on, and it is why the DDL")
print("  column cannot distinguish these schemas -- all three accept the field.")
print()
print("  The difference is in the last column, and it costs nothing until data")
print("  changes underneath it. Section 3b makes it cost something.")
print()

# --------------------------------------------------------------------------- #
store.rule("3b. The correction that misaligns the zip")
# --------------------------------------------------------------------------- #
EIDS = {  # backfilled after change 2, correct in both schemas at this point
    "R03": ["E-MIIT", "E-CREG", "E-NRE", "E-SHR", "E-GDR", "E-MMR", "E-XTC"],
}
conn.execute("UPDATE wide SET actor_eids=? WHERE record_id='R03'",
             ("|".join(EIDS["R03"]),))
for i, eid in enumerate(EIDS["R03"]):
    conn.execute("UPDATE actors SET entity_id=? WHERE event_id=3 AND ordinal=?",
                 (eid, i))
conn.commit()


def wide_pairs(rid: str) -> list[tuple[str, str]]:
    """What every reader of the wide schema has to write. Note what zip() does
    when the lists disagree in length: it stops at the shorter one, silently."""
    a, r = conn.execute(
        "SELECT actors, actor_eids FROM wide WHERE record_id=?", (rid,)).fetchone()
    return list(zip(a.split("|"), (r or "").split("|")))


def norm_pairs(rid: str) -> list[tuple[str, str]]:
    return conn.execute(
        "SELECT a.name, a.entity_id FROM actors a JOIN events e USING (event_id)"
        " WHERE e.record_id=? ORDER BY a.ordinal", (rid,)).fetchall()


print(f"  before the correction: wide and normalized agree = "
      f"{wide_pairs('R03') == norm_pairs('R03')}")

# A labelling correction: 广晟有色 was never in this document. One actor is
# removed. Applied by the person who owns the actor list, in both schemas.
conn.execute("UPDATE wide SET actors=replace(actors, '广晟有色|', '')"
             " WHERE record_id='R03'")
conn.execute("DELETE FROM actors WHERE event_id=3 AND name='广晟有色'")
conn.commit()

w, n = wide_pairs("R03"), norm_pairs("R03")
misaligned = sum(1 for (an, ae), (bn, be) in zip(w, n) if ae != be)
print(f"  after:  wide reports {len(w)} actor/entity pairs, "
      f"normalized reports {len(n)}")
print(f"          {misaligned} of {len(n)} entity ids are now attached to the "
      f"wrong actor in the wide schema")
for i in range(len(n)):
    if w[i][1] != n[i][1]:
        print(f"          e.g. wide says {w[i][0]!r} -> {w[i][1]!r}; "
              f"normalized says {n[i][0]!r} -> {n[i][1]!r}")
        break
print()
print("  No error was raised, no constraint fired, no reader broke. Both strings")
print("  are still well-formed, still parse, still have plausible lengths. The")
print("  wide schema now asserts an entity link for a company the link was never")
print("  written for -- every downstream join, aggregate and knowledge-base write")
print("  attributes those events to the wrong company, and it will keep doing so")
print("  until someone reads a report and recognizes a name in the wrong column.")
print()
print("  In the normalized schema the same correction was a DELETE, and the id")
print("  went with the row because it was *on* the row. The misalignment is not")
print("  merely unlikely there -- it is unrepresentable. That is the difference")
print("  between a schema that survives a change and one that accepts it.")
print()
print("  EAV has the identical defect: the role at ordinal 3 and the actor at")
print("  ordinal 3 are two independent rows, and no constraint expressible in")
print("  that shape says they refer to the same thing. It needed zero DDL for")
print("  all three changes -- its entire pitch -- and section 2 is the invoice.")
print()

# --------------------------------------------------------------------------- #
store.rule("4. What actually made the normalized schema survive")
# --------------------------------------------------------------------------- #
print("  Not normalization as a principle. Two specific decisions:")
print()
print("  a. Every repeating group got its own table with an explicit `ordinal`.")
print("     actors and claims were never scalars, so neither change 2 nor change")
print("     3 was a shape change -- both were a column on a table that already")
print("     had the right grain. The cost was paid on day one, when writing one")
print("     table felt like more work than writing one column.")
print()
print("  b. `event_date` is nullable and `extra` exists. Nullable because the")
print("     source sometimes does not state a date (R09), and a schema that")
print("     cannot represent 'not stated' forces the extractor to invent. `extra`")
print("     because the field that arrives with no warning goes there for one")
print("     release and gets promoted to a column once its shape is known.")
print()
print("  The rule that generalizes: **model the cardinality, not the current")
print("  fields.** Fields arrive weekly and cost an ALTER. A grain that was wrong")
print("  on day one costs a rewrite of every reader that ever touched it.")
print()
print("  Which of `extra`'s fields deserve promotion, and what the JSON path")
print("  costs while they wait, is ../jsonb-vs-relational.md.")
