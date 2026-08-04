"""A schema change with two versions of the code running at once.

    python migrate_lab.py

The map's evidence line is "a backward-compatible migration run against real
data". The word doing the work is *backward*: during any rolling deploy, and for
as long as a rollback is possible, the old code and the new code are both live
against one database. A migration is not a change to a schema. It is a sequence
of states, every one of which two versions of the code must survive.

The change: `location` becomes `location_name` plus `admin_level`, because
'深圳市' and '深圳' are the same place at different granularities and nothing in
the current schema says so.
"""
from __future__ import annotations

import sqlite3

import store

N = 20_000
conn = store.build()
store.seed_bulk(conn, N)
conn.execute("CREATE TABLE schema_version (version INTEGER NOT NULL)")
conn.execute("INSERT INTO schema_version VALUES (1)")
conn.commit()


# --------------------------------------------------------------------------- #
# The two versions of the application. Neither one knows the other exists.
# --------------------------------------------------------------------------- #
def v1_read(c):
    return c.execute("SELECT location FROM events WHERE event_id=1").fetchone()


def v1_write(c, eid):
    c.execute("INSERT INTO events (event_id, record_id, event_type, location,"
              " source_id) VALUES (?,?,?,?,1)", (eid, f"V1-{eid}", "investment",
                                                 "深圳市"))


def v2_read(c):
    return c.execute("SELECT location_name, admin_level FROM events"
                     " WHERE event_id=1").fetchone()


def v2_write(c, eid):
    c.execute("INSERT INTO events (event_id, record_id, event_type,"
              " location_name, admin_level, source_id) VALUES (?,?,?,?,?,1)",
              (eid, f"V2-{eid}", "investment", "深圳", "city"))


LAST_ERROR = {}


def survives(fn, *args) -> str:
    try:
        fn(conn, *args)
        return "ok"
    except sqlite3.OperationalError as exc:
        LAST_ERROR[fn.__name__] = str(exc)
        return "FAIL"


print(f"{N:,} rows, schema version 1, v1 code in production.\n")

# --------------------------------------------------------------------------- #
store.rule("1. The one-step migration")
# --------------------------------------------------------------------------- #
conn.execute("SAVEPOINT naive")
conn.execute("ALTER TABLE events RENAME COLUMN location TO location_name")
conn.execute("ALTER TABLE events ADD COLUMN admin_level TEXT")
for fn, args in ((v1_read, ()), (v2_read, ()), (v1_write, (900001,))):
    status = survives(fn, *args)
    err = LAST_ERROR.get(fn.__name__, "")
    print(f"  after RENAME + ADD:  {fn.__name__:<9} -> {status:<5} {err}")
print()
print("  v1 is down. Not degraded -- down, on every request, from the instant the")
print("  migration commits until the last v1 pod is drained. And a rollback of")
print("  the *code* does not help, because the schema does not roll back with it.")
print("  This is the migration that is fine in review, fine in staging where only")
print("  one version runs, and an outage on deploy.")
conn.execute("ROLLBACK TO naive")
conn.execute("RELEASE naive")
print()

# --------------------------------------------------------------------------- #
store.rule("2. Expand and contract, one phase at a time")
# --------------------------------------------------------------------------- #
print(f"  {'phase':<38} {'v1_read':<9} {'v1_write':<9} {'v2_read':<9} v2_write")


def probe(label, eid):
    r = (survives(v1_read), survives(v1_write, eid), survives(v2_read),
         survives(v2_write, eid + 1))
    print(f"  {label:<38} {r[0]:<9} {r[1]:<9} {r[2]:<9} {r[3]}")


def v1_traffic(base, count=150):
    """v1 keeps serving. It does not know a migration is running."""
    for i in range(count):
        try:
            v1_write(conn, base + i)
        except sqlite3.OperationalError:
            return
    conn.commit()


probe("0. before anything", 910000)

# Phase 1: expand. Additive only -- new columns, nullable, no default.
conn.execute("ALTER TABLE events ADD COLUMN location_name TEXT")
conn.execute("ALTER TABLE events ADD COLUMN admin_level TEXT")
conn.execute("UPDATE schema_version SET version=2")
conn.commit()
probe("1. expand (add nullable columns)", 920000)
v1_traffic(921000)      # 150 v1 inserts land while the expand is settling

# Phase 2: backfill. Batched, because one UPDATE over the whole table holds a
# write lock for as long as it takes -- and bounded to the rows that existed
# when the job started, which is how every real backfill is written. It has to
# terminate, and a job chasing live inserts does not.
high_water = conn.execute("SELECT max(event_id) FROM events").fetchone()[0]
batch, done, batches = 5_000, 0, 0
while True:
    cur = conn.execute(
        "UPDATE events SET location_name = rtrim(location, '市省区'),"
        " admin_level = CASE WHEN location LIKE '%市' THEN 'city'"
        "                    WHEN location LIKE '%省' THEN 'province'"
        "                    ELSE 'unknown' END"
        " WHERE event_id IN (SELECT event_id FROM events"
        "                     WHERE event_id <= ? AND location IS NOT NULL"
        "                       AND location_name IS NULL LIMIT ?)",
        (high_water, batch))
    conn.commit()
    if not cur.rowcount:
        break
    done += cur.rowcount
    batches += 1
    v1_traffic(940000 + 1000 * batches, count=50)   # v1 writes throughout
probe(f"2. backfill ({done:,} rows, {batches} batches)", 930000)

# The deploy takes time. v1 pods drain over the next twenty minutes, and every
# one of them is still writing v1-shaped rows.
v1_traffic(960000, count=200)

# Phase 3: dual-write, installed after the backfill because that is the order
# the runbook was written in.
conn.executescript("""
    CREATE TRIGGER dual_write_ins AFTER INSERT ON events
    WHEN new.location IS NOT NULL AND new.location_name IS NULL
    BEGIN
        UPDATE events SET location_name = rtrim(new.location, '市省区'),
               admin_level = CASE WHEN new.location LIKE '%市' THEN 'city'
                                  ELSE 'unknown' END
         WHERE event_id = new.event_id;
    END;
""")
conn.commit()
probe("3. dual-write trigger installed", 940000)
print()
print("  Four green columns in every row. That is what backward compatible means")
print("  operationally: at no point does a deploy or a rollback of either version")
print("  meet a schema it cannot serve.")
print()

# --------------------------------------------------------------------------- #
store.rule("3. The phase everyone skips, priced")
# --------------------------------------------------------------------------- #
orphans = conn.execute(
    "SELECT count(*) FROM events WHERE location IS NOT NULL"
    " AND location_name IS NULL").fetchone()[0]
print(f"  rows the new code cannot see:                              {orphans}")
total_v1 = conn.execute(
    "SELECT count(*) FROM events WHERE record_id LIKE 'V1-%'").fetchone()[0]
print(f"  total rows v1 wrote during the migration:                  "
      f"{total_v1}")
print(f"  share of v1's writes that the new code cannot see:         "
      f"{orphans / total_v1:.0%}")
print()
print("  Three quarters of everything the old code wrote during the deploy is")
print("  invisible to the new code, and nothing failed. The backfill was correct")
print("  when it ran and stale one millisecond later, because v1 was still")
print("  serving traffic. The bug is not in the backfill -- it is in the belief")
print("  that a backfill is a step rather than a *race*.")
print()
print("  Order that works, and it is not the intuitive one:")
print("    expand -> dual-write -> backfill -> verify -> switch reads -> contract")
print("  Dual-write comes BEFORE backfill. Then the backfill only has to catch")
print("  the rows that existed when it started, which is a set that stops")
print("  growing. Install the trigger after the backfill, as this lab did, and")
print("  the window between them is a permanent hole in the data.")
print()
print("  The verify step is a query, and it is the one to write first:")
print("    SELECT count(*) FROM events")
print("     WHERE location IS NOT NULL AND location_name IS NULL")
print("  Zero, twice, five minutes apart. Not zero once.")
print()

# Close the hole the same way production would: re-run the backfill now that
# the trigger exists.
conn.execute("UPDATE events SET location_name = rtrim(location, '市省区'),"
             " admin_level = 'unknown'"
             " WHERE location IS NOT NULL AND location_name IS NULL")
conn.commit()
left = conn.execute("SELECT count(*) FROM events WHERE location IS NOT NULL"
                    " AND location_name IS NULL").fetchone()[0]
print(f"  after re-running the backfill with the trigger live: {left} orphans")
print()

# --------------------------------------------------------------------------- #
store.rule("4. What each DDL statement actually costs")
# --------------------------------------------------------------------------- #
rows = conn.execute("SELECT count(*) FROM events").fetchone()[0]
print(f"  on {rows:,} rows:")
ms = store.timed(conn, "SELECT 1")  # warm the connection
t = {}
conn.execute("SAVEPOINT ddl")
import time  # noqa: E402  -- kept local to the section that measures

t0 = time.perf_counter()
conn.execute("ALTER TABLE events ADD COLUMN cheap TEXT")
t["ADD COLUMN (nullable)"] = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
conn.execute("ALTER TABLE events ADD COLUMN defaulted TEXT NOT NULL DEFAULT 'x'")
t["ADD COLUMN NOT NULL DEFAULT"] = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
conn.execute("UPDATE events SET cheap = 'x'")
t["UPDATE every row"] = (time.perf_counter() - t0) * 1000

t0 = time.perf_counter()
conn.execute("ALTER TABLE events DROP COLUMN cheap")
t["DROP COLUMN"] = (time.perf_counter() - t0) * 1000

for k, v in t.items():
    print(f"    {k:<30} {v:8.2f} ms")
conn.execute("ROLLBACK TO ddl")
conn.execute("RELEASE ddl")
print()
print("  ADD COLUMN is a catalogue edit: the existing rows are not touched and")
print("  the missing value is materialized on read. It is O(1) in table size and")
print("  that is what makes the expand phase safe to run at any hour.")
print()
print("  DROP COLUMN and the full UPDATE are O(rows) and hold a write lock for")
print("  the duration. Those belong in the contract phase, scheduled, batched,")
print("  and behind the verify query -- never in the same deploy as the expand.")
print()
print("  Postgres differs in the details and not in the conclusion: ADD COLUMN")
print("  with a constant default has been metadata-only since 11, DROP COLUMN is")
print("  metadata-only there (the space is reclaimed later by VACUUM), and it is")
print("  `ALTER TYPE` that rewrites. Measure your own engine; the *shape* of the")
print("  rule -- additive is cheap, destructive is not, so separate the deploys")
print("  -- is the part that carries.")
print()

# --------------------------------------------------------------------------- #
store.rule("5. The version number is a range")
# --------------------------------------------------------------------------- #
print("  `schema_version` says 2. Both v1 and v2 code run correctly against it,")
print("  so the useful assertion at startup is not equality:")
print()
print("      MIN_SCHEMA, MAX_SCHEMA = 1, 2      # this build's window")
print("      assert MIN_SCHEMA <= current_schema_version() <= MAX_SCHEMA")
print()
print("  A build that demands equality cannot be deployed without downtime, by")
print("  construction. A build that declares a window is telling you, in code,")
print("  exactly how far back you may roll -- and the day the window is empty is")
print("  the day you find out the contract phase ran too early.")
print()
print("  What ../eval-set-versioning.md found for eval sets holds here: the")
print("  stamp is worthless unless something refuses to run when it disagrees.")
