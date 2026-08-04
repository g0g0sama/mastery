"""Four watermark strategies over five incremental runs, scored on completeness.

    python pipeline_lab.py

An incremental pipeline is a loop with one piece of state: where it got to. The
capability is choosing that state well, and the failure mode is that a badly
chosen watermark loses records **silently and permanently** -- the job succeeds,
the row count goes up, and a document is never processed by anything, ever.

The corpus here is 500 fetched documents with two timestamps, which is the whole
subject: `fetched_at`, when the document was collected, and `ingest_seq`, when
this database learned about it. They are not the same order, and every result
below follows from that.
"""
from __future__ import annotations

import random

import store

RUNS = 5
conn = store.build()
conn.executescript("""
    CREATE TABLE raw (
        doc_id     TEXT PRIMARY KEY,
        fetched_at INTEGER NOT NULL,   -- event time: when the crawler got it
        ingest_seq INTEGER NOT NULL,   -- arrival time: when this table got it
        body       TEXT
    );
    CREATE TABLE processed (
        doc_id  TEXT,                  -- deliberately NOT unique. See section 4.
        run     INTEGER
    );
    CREATE TABLE cursor_ (name TEXT PRIMARY KEY, ts INTEGER, doc_id TEXT,
                          seq INTEGER);
""")

rng = random.Random(11)
T0 = 1_770_000_000
# 50 distinct fetch timestamps for 500 documents: a crawler stamps a whole batch
# with one time, so ties are the normal case rather than a corner case.
stamps = sorted(T0 + 600 * i for i in range(50))
docs = {f"D{i:04d}": stamps[i // 10] for i in range(500)}

# Three populations, because they fail for three different reasons and a lab
# that mixes them can only report a total.
#
# 1. IN ORDER -- arrival order matches fetch order. 467 documents.
# 2. LATE     -- old documents that arrive after much newer ones: a retried
#                fetch, a slow shard, a second source backfilled later.
# 3. SKEWED   -- documents whose `fetched_at` is wrong and far in the future,
#                arriving at their normal time. One bad clock on one crawler,
#                or a source that reports its own timestamp and lies.
LATE = [f"D{i:04d}" for i in (37, 88, 141, 196, 233, 268, 299, 314, 355, 401)]
SKEWED = ["D0121", "D0122"]
for d in SKEWED:
    docs[d] = stamps[-1] + 7 * 86_400          # a week ahead of the newest real one

arrival = [d for d in docs if d not in LATE]   # natural order, minus the late ones
for i, d in enumerate(LATE):                   # they show up near the very end
    arrival.insert(470 + i, d)
for seq, doc_id in enumerate(arrival, start=1):
    conn.execute("INSERT INTO raw VALUES (?,?,?,?)",
                 (doc_id, docs[doc_id], seq, "..."))
conn.commit()

total = conn.execute("SELECT count(*) FROM raw").fetchone()[0]
print(f"{total} documents, {len(stamps)} distinct fetch timestamps "
      f"({total // len(stamps)} documents per timestamp -- ties everywhere).")
print(f"{len(LATE)} arrive late with old timestamps. {len(SKEWED)} arrive on "
      f"time with timestamps a week in the future.\n")

VISIBLE = [100, 200, 300, 420, 500]      # ingest_seq visible at each of 5 runs

STRATEGIES = {
    "A  fetched_at >":
        "SELECT doc_id, fetched_at, ingest_seq FROM raw"
        " WHERE ingest_seq <= :vis AND fetched_at > :ts ORDER BY fetched_at",
    "B  fetched_at >=":
        "SELECT doc_id, fetched_at, ingest_seq FROM raw"
        " WHERE ingest_seq <= :vis AND fetched_at >= :ts ORDER BY fetched_at",
    "C  (fetched_at, doc_id) >":
        "SELECT doc_id, fetched_at, ingest_seq FROM raw"
        " WHERE ingest_seq <= :vis AND (fetched_at > :ts OR"
        "       (fetched_at = :ts AND doc_id > :doc)) ORDER BY fetched_at, doc_id",
    "D  ingest_seq >":
        "SELECT doc_id, fetched_at, ingest_seq FROM raw"
        " WHERE ingest_seq <= :vis AND ingest_seq > :seq ORDER BY ingest_seq",
}


CURSOR_TRACE: dict[str, list[int]] = {}


def run_pipeline(name: str, sql: str) -> dict:
    CURSOR_TRACE[name] = []
    conn.execute("DELETE FROM processed")
    conn.execute("INSERT OR REPLACE INTO cursor_ VALUES (?,?,?,?)",
                 (name, 0, "", 0))
    for run, vis in enumerate(VISIBLE, start=1):
        ts, doc, seq = conn.execute(
            "SELECT ts, doc_id, seq FROM cursor_ WHERE name=?", (name,)).fetchone()
        CURSOR_TRACE[name].append(ts)
        rows = conn.execute(sql, {"vis": vis, "ts": ts, "doc": doc,
                                  "seq": seq}).fetchall()
        conn.executemany("INSERT INTO processed VALUES (?,?)",
                         [(r[0], run) for r in rows])
        if rows:
            conn.execute(
                "UPDATE cursor_ SET ts=?, doc_id=?, seq=? WHERE name=?",
                (max(r[1] for r in rows), max(r[0] for r in rows),
                 max(r[2] for r in rows), name))
        conn.commit()
    seen = conn.execute("SELECT count(DISTINCT doc_id) FROM processed").fetchone()[0]
    writes = conn.execute("SELECT count(*) FROM processed").fetchone()[0]
    dupes = conn.execute(
        "SELECT count(*) FROM (SELECT doc_id FROM processed GROUP BY 1"
        " HAVING count(*) > 1)").fetchone()[0]
    return {"processed": seen, "missed": total - seen, "writes": writes,
            "reprocessed": dupes}


# --------------------------------------------------------------------------- #
store.rule("1. Five runs, four watermarks")
# --------------------------------------------------------------------------- #
print(f"  {'strategy':<26} {'processed':>10} {'MISSED':>7} {'writes':>7} "
      f"{'reprocessed':>12}")
results = {}
for name, sql in STRATEGIES.items():
    results[name] = run_pipeline(name, sql)
    r = results[name]
    print(f"  {name:<26} {r['processed']:>10} {r['missed']:>7} {r['writes']:>7} "
          f"{r['reprocessed']:>12}")
print()
print("  Every one of these runs reported success. Three of the four lost")
print("  documents; the one that did not is the one whose cursor is on arrival")
print("  order rather than on a timestamp that means something to a human.")
print()

# --------------------------------------------------------------------------- #
store.rule("2. Attributing every lost document to a cause")
# --------------------------------------------------------------------------- #
run_pipeline("A  fetched_at >", STRATEGIES["A  fetched_at >"])
trace = CURSOR_TRACE["A  fetched_at >"]
missing = conn.execute(
    "SELECT doc_id, fetched_at, ingest_seq FROM raw"
    " WHERE doc_id NOT IN (SELECT doc_id FROM processed)"
    " ORDER BY ingest_seq").fetchall()


def arrival_run(seq: int) -> int:
    return next(i for i, v in enumerate(VISIBLE) if seq <= v)


causes = {"tie at the boundary": [], "late arrival (old doc)": [],
          "collateral of a skewed timestamp": []}
for doc_id, ts, seq in missing:
    cursor_when_it_arrived = trace[arrival_run(seq)]
    if doc_id in LATE:
        causes["late arrival (old doc)"].append(doc_id)
    elif ts == cursor_when_it_arrived:
        causes["tie at the boundary"].append(doc_id)
    else:
        causes["collateral of a skewed timestamp"].append(doc_id)

print(f"  strategy A lost {len(missing)} of {total} documents:")
for cause, ids in causes.items():
    print(f"    {cause:<36} {len(ids):>4}   e.g. {', '.join(ids[:3])}")
print()
print(f"  cursor value at the start of each run: {trace}")
skew_ts = conn.execute("SELECT fetched_at FROM raw WHERE doc_id=?",
                       (SKEWED[0],)).fetchone()[0]
print(f"  the two skewed documents carry fetched_at {skew_ts}, which is "
      f"{(skew_ts - stamps[-1]) // 3600} hours")
print(f"  beyond the newest genuine document.")
print()
print("  Three mechanisms, and only the first is the one people discuss.")
print()
print("  **Ties.** The cursor is `max(fetched_at)` of the batch and the next run")
print("  asks for strictly greater, so any document carrying that exact timestamp")
print("  but arriving in the next batch is skipped forever. Ten documents share")
print("  every timestamp here, so a batch boundary lands mid-tie routinely.")
print("  Strategy C fixes exactly this by making the cursor a *pair* --")
print("  (timestamp, id) -- which is a total order and therefore has no ties.")
print()
print("  **Late arrivals.** A document fetched at 09:00 and inserted after the")
print("  cursor passed 11:00 is below the watermark the moment it lands. No")
print("  comparison on `fetched_at` can find it, because the field being")
print("  selected on describes the past. C does not fix this; nothing of that")
print("  shape can.")
print()
print("  **One bad timestamp took the rest.** This is the dominant cause here and")
print("  it is the one worth carrying away. Two documents with a clock a week")
print("  fast arrived in run 2. The cursor is a maximum, so it jumped a week")
print("  ahead -- and every genuine document that arrived afterwards had a")
print("  `fetched_at` below it and was never selected again. Two bad rows")
print("  silently disabled the pipeline for the rest of the corpus, and the job")
print("  kept reporting success with a shrinking batch size.")
print()
print("  That last one is why `max()` over an externally-supplied timestamp is")
print("  the wrong cursor even after ties and lateness are handled. The watermark")
print("  inherits the worst clock of every system upstream of it.")
print()

store.rule("3. Why B is not the safe choice it looks like")
# --------------------------------------------------------------------------- #
b = results["B  fetched_at >="]
print(f"  B processed {b['processed']} distinct documents with {b['writes']} "
      f"writes: {b['writes'] - b['processed']} redundant.")
print(f"  and it still missed {b['missed']}.")
print()
print("  `>=` trades one bug for a cost and does not close the other. It")
print("  reprocesses the whole trailing tie group on every run -- which is fine")
print("  if and only if the sink is idempotent -- and the late arrivals stay")
print("  invisible, because they were never a boundary problem to begin with.")
print()
print("  This is worth being precise about, because `>` versus `>=` is where")
print("  this discussion usually ends. It is the smaller half of the problem.")
print()

# --------------------------------------------------------------------------- #
store.rule("4. The sink decides whether a re-run is safe")
# --------------------------------------------------------------------------- #
dupe_rows = conn.execute(
    "SELECT count(*) FROM (SELECT doc_id FROM processed GROUP BY 1"
    " HAVING count(*) > 1)").fetchone()[0]
print(f"  `processed` has no unique constraint, so B's re-writes became "
      f"duplicate rows,")
print(f"  not overwrites. Downstream, every aggregate over that table is now")
print(f"  inflated by exactly the amount the pipeline was 'safely' redundant.")
print()
conn.execute("CREATE UNIQUE INDEX ix_proc ON processed(doc_id)")
print("  With `CREATE UNIQUE INDEX ix_proc ON processed(doc_id)` and an upsert,")
print("  the same re-run is free:")
print("      INSERT INTO processed (doc_id, run) VALUES (?, ?)")
print("        ON CONFLICT (doc_id) DO UPDATE SET run = excluded.run")
print()
print("  **Reprocessing is not a property of the pipeline; it is a property of")
print("  the sink.** Decide idempotency at the write, once, and the watermark")
print("  choice stops being load-bearing -- an over-inclusive cursor becomes")
print("  merely wasteful instead of corrupting. That is the same argument as")
print("  ../provider-errors-retries.md makes for a retried API call, arriving")
print("  from the data side.")
print()

# --------------------------------------------------------------------------- #
store.rule("5. The completeness assertion")
# --------------------------------------------------------------------------- #
print("  None of the above is detectable from inside the pipeline. Every run")
print("  succeeded. The instrument is a query that compares the two tables:")
print()
print("      SELECT count(*) FROM raw")
print("       WHERE doc_id NOT IN (SELECT doc_id FROM processed)")
print("         AND ingest_seq <= (SELECT seq FROM cursor_)")
print()
gap = conn.execute(
    "SELECT count(*) FROM raw WHERE doc_id NOT IN"
    " (SELECT doc_id FROM processed)").fetchone()[0]
print(f"  Against strategy A's state, right now, that returns {gap}.")
print()
print("  Run it on a schedule, alert on non-zero, and a lost document becomes a")
print("  page instead of a discovery. Without it the only evidence is an absence,")
print("  and nobody files a bug about a document they never saw -- the same blind")
print("  spot ../retrieval-freshness-deletion.md found from the retrieval side.")
print()
print("  Design rules this lab produces:")
print("    - Drive the cursor from **arrival order** (a monotonic sequence,")
print("      commit LSN, or an `ingested_at` your own writer sets), never from a")
print("      timestamp that belongs to the outside world.")
print("    - If the cursor must be a timestamp, make it a **tuple** with a")
print("      tie-breaking id, and make the comparison total.")
print("    - Make the sink idempotent before tuning the cursor.")
print("    - Ship the completeness query with the pipeline, in the same commit.")
