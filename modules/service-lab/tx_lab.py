"""Where the transaction starts, where it ends, and what is inside it.

    python tx_lab.py          # ~25 s, real SQLite locks and real threads

Map evidence line: "correct boundary across two repositories under a seeded
failure". The boundary turns out to have three separate questions in it and
only the first is the one people mean:

  1. does the boundary cover both writes?          section 1
  2. what is inside it that should not be?         section 2
  3. does it survive two callers arriving at once? sections 3 and 4

SQLite has one writer, so the contention here is more brutal than Postgres and
arrives sooner. The failures are the same failures; the thresholds are not.
"""
from __future__ import annotations

import sqlite3
import threading
import time

import service as s

WORKERS = 8
INCREMENTS = 25
PROVIDER_MS = 0.03


class Boom(Exception):
    """The seeded failure. Raised between two repository calls."""


COUNTER = """
CREATE TABLE IF NOT EXISTS counters (
    name    TEXT PRIMARY KEY,
    value   INTEGER NOT NULL,
    version INTEGER NOT NULL DEFAULT 0
);
"""


def setup(d, counter=False):
    db = str(d / "tx.db")
    conn = s.store(db)
    if counter:
        conn.executescript(COUNTER)
        conn.execute("INSERT OR REPLACE INTO counters VALUES ('extractions', 0, 0)")
    conn.commit()
    conn.close()
    return db


# --------------------------------------------------------------------------- #
# Two repositories. Each one is written the way a repository is written: it
# owns its table, it knows nothing about the other, and it commits its own work.
# --------------------------------------------------------------------------- #

class DocumentRepo:
    def __init__(self, conn, autocommit=True):
        self.conn, self.autocommit = conn, autocommit

    def add(self, doc_id, body):
        self.conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                          (doc_id, "acme", f"u/{doc_id}", body, s.sha(body),
                           time.time()))
        if self.autocommit:
            self.conn.commit()


class EventRepo:
    def __init__(self, conn, autocommit=True):
        self.conn, self.autocommit = conn, autocommit

    def add(self, doc_id, record):
        self.conn.execute(
            "INSERT INTO events (doc_id, tenant, event_type, event_date, actors,"
            " content_sha, created_at) VALUES (?,?,?,?,?,?,?)",
            (doc_id, "acme", record["event_type"], record.get("date"),
             str(record["actors"]), s.content_sha(record), time.time()))
        if self.autocommit:
            self.conn.commit()


print(f"{WORKERS} threads, one SQLite file, real locks.\n")

# --------------------------------------------------------------------------- #
s.rule("1. One intent, two repositories, a failure between them")
# --------------------------------------------------------------------------- #
print("20 documents ingested. The extraction fails on 5 of them, after the\n"
      "document row has been written.\n")
s.row("boundary", "documents", "events", "orphans", "verdict",
      widths=[38, 12, 10, 10, 20])
for label, shared in (("each repository commits its own", False),
                      ("one transaction around both", True)):
    with s.workdir() as d:
        conn = s.connect(setup(d))
        docs = DocumentRepo(conn, autocommit=not shared)
        events = EventRepo(conn, autocommit=not shared)
        for i in range(20):
            doc_id = f"D{i:02d}"
            body = s.DOCUMENTS[s.DOC_IDS[i % 8]][0]
            try:
                if shared:
                    conn.execute("BEGIN IMMEDIATE")
                docs.add(doc_id, body)
                if i % 4 == 3:
                    raise Boom                        # the extraction failed
                events.add(doc_id, s.GOLD[s.DOC_IDS[i % 8]])
                if shared:
                    conn.commit()
            except Boom:
                if shared:
                    conn.rollback()
        nd = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        ne = conn.execute("SELECT count(*) FROM events").fetchone()[0]
        orphan = conn.execute(
            "SELECT count(*) FROM documents d WHERE NOT EXISTS"
            " (SELECT 1 FROM events e WHERE e.doc_id=d.doc_id)").fetchone()[0]
        conn.close()
    s.row(label, nd, ne, orphan,
          "5 half-ingested" if orphan else "all or nothing",
          widths=[38, 12, 10, 10, 20])
print("""
  The repository pattern's own advice -- each repository owns its persistence
  -- produces the first row, because a repository that commits has decided the
  boundary, and it is not the repository's decision to make. The boundary
  belongs to the use case: the caller opens it, both repositories join it, and
  the caller commits or rolls back.

  Whether 5 orphaned documents are a bug depends on the domain, and that is the
  real point. Here they are recoverable work -- a job can extract them later,
  which is what ../background-jobs-queues.md is for. If the second write had
  been "deduct the payment", they would be an incident. Decide which one you
  have before choosing the boundary, rather than inheriting it from whichever
  ORM idiom was nearest.
""")

# --------------------------------------------------------------------------- #
s.rule("2. What is inside the boundary")
# --------------------------------------------------------------------------- #
print(f"Same work, {WORKERS} concurrent ingests, a {PROVIDER_MS * 1000:.0f} ms "
      f"provider call per document.\nThe only difference is whether that call "
      f"happens inside the transaction.\n")
s.row("provider call", "wall time", "throughput", "lock errors",
      widths=[30, 14, 16, 14])
for label, inside in (("inside the transaction", True),
                      ("outside, before BEGIN", False)):
    with s.workdir() as d:
        db = setup(d)
        errors, lock = [], threading.Lock()

        def unit(i):
            conn = s.connect(db, timeout=0.25)   # a short, realistic patience
            try:
                for j in range(4):
                    doc_id = f"D{i}-{j}"
                    body = s.DOCUMENTS[s.DOC_IDS[(i + j) % 8]][0]
                    record = s.GOLD[s.DOC_IDS[(i + j) % 8]]
                    try:
                        if inside:
                            conn.execute("BEGIN IMMEDIATE")
                            DocumentRepo(conn, False).add(doc_id, body)
                            time.sleep(PROVIDER_MS)          # the provider
                            EventRepo(conn, False).add(doc_id, record)
                            conn.commit()
                        else:
                            time.sleep(PROVIDER_MS)          # the provider
                            conn.execute("BEGIN IMMEDIATE")
                            DocumentRepo(conn, False).add(doc_id, body)
                            EventRepo(conn, False).add(doc_id, record)
                            conn.commit()
                    except sqlite3.OperationalError as exc:
                        conn.rollback()
                        with lock:
                            errors.append(str(exc))
            finally:
                conn.close()

        t0 = time.perf_counter()
        ts = [threading.Thread(target=unit, args=(i,)) for i in range(WORKERS)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        elapsed = time.perf_counter() - t0
        conn = s.connect(db)
        done = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
        conn.close()
    s.row(label, f"{elapsed:.2f} s", f"{done / elapsed:.0f} docs/s", len(errors),
          widths=[30, 14, 16, 14])
print("""
  Nothing about the work changed. The transaction that contains a network call
  holds the write lock for the duration of somebody else's latency, so the
  database's concurrency is capped by the provider's p99 rather than by its own
  throughput -- and the callers that cannot get the lock in time do not queue
  politely, they fail.

  The rule is narrow and worth stating exactly: **do the slow, fallible,
  external thing first; open the transaction only around the writes.** A
  transaction is a lock held on shared state, and its cost is measured in the
  time it is held, not in the number of statements inside it.

  What this costs you is that the external call now happens before the
  transaction that records it, so it can succeed and then not be recorded --
  the same absence-of-evidence problem as ../idempotency-keys.md, which is why
  the extraction needs to be replayable rather than exactly-once.
""")

# --------------------------------------------------------------------------- #
s.rule("3. Read, modify, write, with company")
# --------------------------------------------------------------------------- #
print(f"{WORKERS} threads each increment the same counter {INCREMENTS} times.\n"
      f"Correct answer: {WORKERS * INCREMENTS}.\n")
s.row("strategy", "final value", "missing", "errors", "retries",
      widths=[34, 13, 9, 9, 9])


def hammer(db, strategy):
    errors, retries, lock = [], [0], threading.Lock()

    def unit():
        conn = s.connect(db, timeout=0.25)
        for _ in range(INCREMENTS):
            while True:
                try:
                    if strategy == "naive":
                        v = conn.execute("SELECT value FROM counters"
                                         " WHERE name='extractions'").fetchone()[0]
                        conn.execute("UPDATE counters SET value=?"
                                     " WHERE name='extractions'", (v + 1,))
                        conn.commit()
                    elif strategy == "deferred":
                        conn.execute("BEGIN")            # deferred: read lock only
                        v = conn.execute("SELECT value FROM counters"
                                         " WHERE name='extractions'").fetchone()[0]
                        conn.execute("UPDATE counters SET value=?"
                                     " WHERE name='extractions'", (v + 1,))
                        conn.commit()
                    elif strategy == "immediate":
                        conn.execute("BEGIN IMMEDIATE")  # write lock up front
                        v = conn.execute("SELECT value FROM counters"
                                         " WHERE name='extractions'").fetchone()[0]
                        conn.execute("UPDATE counters SET value=?"
                                     " WHERE name='extractions'", (v + 1,))
                        conn.commit()
                    elif strategy == "optimistic":
                        v, ver = conn.execute(
                            "SELECT value, version FROM counters"
                            " WHERE name='extractions'").fetchone()
                        cur = conn.execute(
                            "UPDATE counters SET value=?, version=version+1"
                            " WHERE name='extractions' AND version=?",
                            (v + 1, ver))
                        conn.commit()
                        if cur.rowcount == 0:
                            with lock:
                                retries[0] += 1
                            continue          # somebody else won; re-read
                    elif strategy == "atomic":
                        conn.execute("UPDATE counters SET value=value+1"
                                     " WHERE name='extractions'")
                        conn.commit()
                    break
                except sqlite3.OperationalError as exc:
                    conn.rollback()
                    with lock:
                        errors.append(str(exc).split(":")[0])
                    break                     # the request is lost, not retried
        conn.close()

    ts = [threading.Thread(target=unit) for _ in range(WORKERS)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    conn = s.connect(db)
    value = conn.execute("SELECT value FROM counters"
                         " WHERE name='extractions'").fetchone()[0]
    conn.close()
    return value, errors, retries[0]


measured = {}
for label, strategy in (("read; update; commit", "naive"),
                        ("BEGIN (deferred); read; update", "deferred"),
                        ("BEGIN IMMEDIATE; read; update", "immediate"),
                        ("optimistic: WHERE version=?", "optimistic"),
                        ("UPDATE ... SET value=value+1", "atomic")):
    with s.workdir() as d:
        db = setup(d, counter=True)
        value, errors, retries = hammer(db, strategy)
    missing = WORKERS * INCREMENTS - value
    measured[strategy] = (missing, len(errors))
    s.row(label, value, missing, len(errors), retries, widths=[34, 13, 9, 9, 9])

nm, ne_ = measured["naive"]
dm, de = measured["deferred"]
im, ie = measured["immediate"]
print(f"""
  Read the `missing` and `errors` columns together; that pairing is the whole
  section. Nothing here retries a lock timeout -- this code drops the request,
  which a real service would not -- so a handful of increments go missing under
  every strategy. The interesting quantity is how many of them were *reported*.

    naive       {nm:>3} missing, {ne_:>3} errors   -- {nm - ne_} vanished in silence
    deferred    {dm:>3} missing, {de:>3} errors   -- every loss announced itself
    immediate   {im:>3} missing, {ie:>3} errors   -- and the same for the last two

  Row one is the lost update. No error, no warning, no failed statement: two""")
print("""  callers read 7, both write 8, one increment is gone. It is detectable only
  against a total you knew in advance, which is precisely the number production
  does not have. Correctness here is not "nothing was lost" -- it is "nothing
  was lost quietly".

  Row two is the one worth learning here. `BEGIN` in SQLite is *deferred*: the
  SELECT takes a read lock and the UPDATE then has to upgrade to a write lock,
  which fails if anyone committed in between. Two rules fall out of that and
  both generalize past SQLite:

    - if a transaction will write, say so when it starts (`BEGIN IMMEDIATE`,
      `SELECT ... FOR UPDATE`), rather than discovering it at the UPDATE
    - when a transaction fails on a conflict, retry the *transaction*, not the
      statement. The values it read are stale by definition -- that is what the
      conflict means -- so re-issuing the UPDATE alone writes a number computed
      from a world that no longer exists

  Row two also shows what "correct but unusable" looks like: it never writes a
  wrong number and it barely writes any. Declaring the write intent up front
  collapses those conflicts into a much smaller number of lock waits, because
  the callers queue for the lock instead of racing for it and losing.

  The last two rows are the two correct answers and they are different tools.
  The optimistic version check works across a read-think-write gap that spans a
  user, a request, or a queue; it needs a retry loop and it needs the caller to
  handle losing. The atomic UPDATE is unbeatable when the new value is a pure
  function of the old one -- and it is unavailable the moment the new value
  depends on something the database cannot see.
""")

# --------------------------------------------------------------------------- #
s.rule("4. Two invariants that no isolation level restores")
# --------------------------------------------------------------------------- #
print("""  read-modify-write        a value derived from a stale read. Section 3.
                           Fixed by locking the row you read, by a version
                           check, or by pushing the arithmetic into the UPDATE.

  write skew               two transactions each read a set, each check an
                           invariant over it, each write a *different* row, and
                           both commit. Nobody wrote the same row, so no
                           conflict is detected, and the invariant is now false.
                           "At most one active extraction per document" fails
                           this way: both readers see zero, both insert.

  The second one is why "we use transactions" is not an answer to "is this
  invariant safe". A transaction guarantees that your writes land together, not
  that the world you read them against still holds. If an invariant spans rows
  that no single transaction writes, it needs a constraint (a unique index over
  the thing being counted), a lock taken deliberately on a row that represents
  the set, or serializable isolation and a retry loop -- and the first of those
  is nearly always the cheapest.

  Which is the same conclusion as ../authn-and-authz.md reached: a rule the
  database enforces cannot be forgotten by a code path, and a rule enforced in
  application code is a rule enforced once per code path that remembers it.
""")
