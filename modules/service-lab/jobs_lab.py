"""A durable job, and the four places durability is quietly not there.

    python jobs_lab.py        # ~20 s, real threads against a real SQLite file

Map evidence line: "a durable job with supervision, retry, and idempotent
execution". Each of those three words fails independently and this file breaks
them one at a time.

No HTTP here. A queue is internal machinery, and every effect below is a real
thread racing a real lease against a real clock.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

import service as s

RUNS = 20               # units of work per experiment


class Crash(Exception):
    """A process that stopped between two writes. Nothing catches this."""


# --------------------------------------------------------------------------- #
# The queue. Claim by lease, not by flag -- a flag cannot expire.
# --------------------------------------------------------------------------- #

def enqueue(conn, doc_id, payload=None):
    conn.execute("INSERT INTO jobs (doc_id, payload, state, enqueued_at)"
                 " VALUES (?,?, 'ready', ?)",
                 (doc_id, json.dumps(payload) if payload else None, time.time()))
    conn.commit()


def claim(conn, lease: float = 0.2):
    """Take one job whose lease has expired or was never taken.

    The UPDATE ... WHERE state/lease is the whole concurrency argument: two
    workers issuing it race inside the database, and exactly one changes a row.
    `fence` increments on every claim, so a lease handed out later always
    carries a strictly larger number than one handed out earlier.
    """
    now = time.time()
    cur = conn.execute(
        "UPDATE jobs SET state='leased', lease_until=?, attempts=attempts+1,"
        " fence=fence+1"
        " WHERE job_id = (SELECT job_id FROM jobs"
        "   WHERE state='ready' OR (state='leased' AND lease_until < ?)"
        "   ORDER BY job_id LIMIT 1)"
        " RETURNING job_id, doc_id, payload, fence, attempts",
        (now + lease, now))
    row = cur.fetchone()
    conn.commit()
    return row


def complete(conn, job_id, fence) -> bool:
    """Finish, but only if this worker still holds the lease it was given."""
    cur = conn.execute("UPDATE jobs SET state='done' WHERE job_id=? AND fence=?",
                       (job_id, fence))
    conn.commit()
    return cur.rowcount == 1


def counts(conn):
    docs = conn.execute("SELECT count(*) FROM documents").fetchone()[0]
    jobs = conn.execute("SELECT count(*) FROM jobs").fetchone()[0]
    orphan_docs = conn.execute(
        "SELECT count(*) FROM documents d WHERE NOT EXISTS"
        " (SELECT 1 FROM jobs j WHERE j.doc_id = d.doc_id)").fetchone()[0]
    phantom_jobs = conn.execute(
        "SELECT count(*) FROM jobs j WHERE NOT EXISTS"
        " (SELECT 1 FROM documents d WHERE d.doc_id = j.doc_id)").fetchone()[0]
    return docs, jobs, orphan_docs, phantom_jobs


print(f"{RUNS} units of work per experiment. Real threads, real leases, a real\n"
      f"SQLite file on disk.\n")

# --------------------------------------------------------------------------- #
s.rule("1. Two writes, one intent, and a process that stops in between")
# --------------------------------------------------------------------------- #
print("Ingesting a document means storing it AND scheduling its extraction.\n"
      "Those are two systems. The process is killed between them on 5 of 20.\n")


def ingest(conn, i, order, crash_at):
    doc_id = f"D{i:02d}"
    body = s.DOCUMENTS[s.DOC_IDS[i % len(s.DOC_IDS)]][0]
    if order == "row_first":
        conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                     (doc_id, "acme", f"u/{doc_id}", body, s.sha(body), time.time()))
        conn.commit()
        if i in crash_at:
            raise Crash
        enqueue(conn, doc_id)
    elif order == "job_first":
        enqueue(conn, doc_id)
        if i in crash_at:
            raise Crash
        conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                     (doc_id, "acme", f"u/{doc_id}", body, s.sha(body), time.time()))
        conn.commit()
    else:   # outbox: one transaction, no second system inside it
        conn.execute("BEGIN IMMEDIATE")
        conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                     (doc_id, "acme", f"u/{doc_id}", body, s.sha(body), time.time()))
        conn.execute("INSERT INTO outbox (doc_id) VALUES (?)", (doc_id,))
        conn.commit()
        if i in crash_at:
            raise Crash
        relay(conn)


def relay(conn):
    """The separate step that turns committed intent into a queued job.

    It is allowed to run late, twice, or after a restart -- which is the point.
    Its only requirement is that it never runs *never*.
    """
    for (out_id, doc_id) in conn.execute(
            "SELECT out_id, doc_id FROM outbox WHERE sent=0").fetchall():
        enqueue(conn, doc_id)
        conn.execute("UPDATE outbox SET sent=1 WHERE out_id=?", (out_id,))
    conn.commit()


s.row("write order", "docs", "jobs", "docs w/o job", "jobs w/o doc",
      widths=[36, 8, 8, 15, 14])
CRASH_AT = {3, 7, 11, 15, 19}
for label, order in (("row committed, then enqueued", "row_first"),
                     ("enqueued, then row committed", "job_first"),
                     ("outbox: one transaction + relay", "outbox")):
    with s.workdir() as d:
        conn = s.store(str(d / "q.db"))
        for i in range(RUNS):
            try:
                ingest(conn, i, order, CRASH_AT)
            except Crash:
                conn.rollback()
        if order == "outbox":
            relay(conn)                 # the relay runs again after the restart
        c = counts(conn)
        conn.close()
    s.row(label, *c, widths=[36, 8, 8, 15, 14])
print("""
  The first two rows are the same bug wearing different clothes, and they are
  not equally bad. A document with no job is silent: nothing is broken, nothing
  errors, the extraction simply never happens and you find out from a customer.
  A job with no document is loud: the worker fails immediately, retries, dead
  letters, and puts itself on a dashboard.

  Given a forced choice, prefer the loud one. But the choice is not forced. The
  outbox row writes the intent inside the same transaction as the data, so the
  crash takes both or neither, and a relay -- allowed to run late, twice, or
  after a restart -- turns committed intent into a queued job. What it buys is
  that the queue is no longer a second system inside your transaction; what it
  costs is a relay that must be supervised, because an outbox nobody drains is
  a document with no job again, just with better evidence.
""")

# --------------------------------------------------------------------------- #
s.rule("2. A lease expiring is not the same as a worker dying")
# --------------------------------------------------------------------------- #
print("One job, lease 150 ms. Worker A is slow (400 ms) but alive. Worker B\n"
      "claims the expired lease and also finishes. Both then try to write.\n")

for fencing in (False, True):
    with s.workdir() as d:
        db = str(d / "q.db")
        conn0 = s.store(db)
        enqueue(conn0, "N01")
        conn0.close()
        written, lock = [], threading.Lock()

        def worker(name, duration):
            conn = s.connect(db)
            row = claim(conn, lease=0.15)
            if not row:
                return
            job_id, doc_id, _, fence, _ = row
            time.sleep(duration)                      # the work
            ok = complete(conn, job_id, fence) if fencing else True
            if not fencing:
                conn.execute("UPDATE jobs SET state='done' WHERE job_id=?",
                             (job_id,))
                conn.commit()
            if ok:
                with lock:
                    written.append((name, fence))
            conn.close()

        a = threading.Thread(target=worker, args=("A (slow)", 0.40))
        b = threading.Thread(target=worker, args=("B", 0.05))
        a.start()
        time.sleep(0.20)                              # A's lease has now expired
        b.start()
        a.join(); b.join()
    s.row("fencing token: " + ("on" if fencing else "off"),
          f"{len(written)} write(s)",
          ", ".join(f"{n} fence={f}" for n, f in sorted(written)),
          widths=[24, 14, 44])
print("""
  A visibility timeout does not stop the first worker. It cannot -- the queue
  has no way to interrupt a thread on another machine that is merely slow, and
  "slow" and "dead" look identical from here. So at-least-once delivery is not
  a property of the broker being unreliable; it is a property of any lease
  short enough to be useful.

  The fencing token is what makes the duplicate harmless. Every claim
  increments a counter, the worker carries its number, and the write is
  conditional on still holding it: `WHERE job_id=? AND fence=?`. The stale
  worker's UPDATE matches zero rows and it discards its own result. This is
  cheap and it is the only thing in this file that makes a stolen lease safe
  rather than merely detectable.
""")

# --------------------------------------------------------------------------- #
s.rule("3. Supervision: what happens to what nobody finished")
# --------------------------------------------------------------------------- #
print("20 jobs, 4 workers, 5 of which are killed mid-job (the thread returns\n"
      "without completing, holding whatever the queue gave it).\n")
s.row("claim mechanism", "done", "stuck", "recovered by sweep",
      widths=[30, 10, 10, 22])
for label, use_lease in (("state flag, no lease", False), ("lease + expiry", True)):
    with s.workdir() as d:
        db = str(d / "q.db")
        conn0 = s.store(db)
        for i in range(RUNS):
            enqueue(conn0, s.DOC_IDS[i % len(s.DOC_IDS)])
        conn0.close()
        killed = {2, 5, 9, 13, 17}

        def run_worker(wid):
            conn = s.connect(db)
            while True:
                if use_lease:
                    row = claim(conn, lease=0.15)
                else:
                    cur = conn.execute(
                        "UPDATE jobs SET state='leased', attempts=attempts+1,"
                        " fence=fence+1 WHERE job_id ="
                        " (SELECT job_id FROM jobs WHERE state='ready'"
                        "  ORDER BY job_id LIMIT 1)"
                        " RETURNING job_id, doc_id, payload, fence, attempts")
                    row = cur.fetchone()
                    conn.commit()
                if not row:
                    break
                job_id, doc_id, _, fence, attempts = row
                if job_id in killed and attempts == 1:
                    conn.close()
                    return                    # the process is gone, mid-job
                time.sleep(0.01)
                complete(conn, job_id, fence)
            conn.close()

        ts = [threading.Thread(target=run_worker, args=(i,)) for i in range(4)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        conn = s.connect(db)
        # the sweep: a supervisor restarts workers, and expired leases are
        # reclaimable by definition
        if use_lease:
            time.sleep(0.2)
            recovery = [threading.Thread(target=run_worker, args=(9 + i,))
                        for i in range(2)]
            for t in recovery:
                t.start()
            for t in recovery:
                t.join()
        done = conn.execute("SELECT count(*) FROM jobs WHERE state='done'").fetchone()[0]
        stuck = conn.execute(
            "SELECT count(*) FROM jobs WHERE state!='done'").fetchone()[0]
        retried = conn.execute("SELECT count(*) FROM jobs WHERE state='done'"
                               " AND attempts>1").fetchone()[0]
        conn.close()
    s.row(label, done, stuck,
          "impossible" if not use_lease else f"{retried} jobs, attempts>1",
          widths=[30, 10, 10, 22])
print("""
  A state flag records that a job was taken. It cannot record that the taker is
  gone, so a killed worker's jobs are stuck in `leased` forever and no amount of
  restarting the workers helps -- the rows do not match `state='ready'` any
  more. Every queue that has ever needed a manual `UPDATE jobs SET
  state='ready' WHERE ...` at 3am has this shape.

  A lease with an expiry makes the same row reclaimable without anyone
  deciding. What it needs in exchange is the fencing check from section 2 and a
  bounded attempt count, because a job that kills its worker will now kill the
  next one too -- the poison item measured in ../failure-queues-and-replay.md.
""")

# --------------------------------------------------------------------------- #
s.rule("4. What the job carries: an id, or a copy")
# --------------------------------------------------------------------------- #
print("A document is corrected between enqueue and execution -- a re-fetch, an\n"
      "OCR fix, a redaction. What does the worker extract?\n")
s.row("payload", "worker sees", "correct?", "if the doc was deleted",
      widths=[26, 24, 12, 26])
with s.workdir() as d:
    db = str(d / "q.db")
    conn = s.store(db)
    original = "中国石化宣布将于三月十日在深圳新建研发中心"
    corrected = "中国石化宣布将于三月十一日在合肥新建研发中心"
    conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                 ("D1", "acme", "u/D1", original, s.sha(original), time.time()))
    enqueue(conn, "D1", payload={"body": original})       # snapshot
    enqueue(conn, "D1")                                   # id only
    conn.commit()
    conn.execute("UPDATE documents SET body=?, body_sha=? WHERE doc_id=?",
                 (corrected, s.sha(corrected), "D1"))
    conn.commit()
    for label, use_payload in (("snapshot of the body", True), ("document id only", False)):
        row = claim(conn, lease=5.0)
        job_id, doc_id, payload, fence, _ = row
        seen = (json.loads(payload)["body"] if use_payload and payload
                else conn.execute("SELECT body FROM documents WHERE doc_id=?",
                                  (doc_id,)).fetchone()[0])
        s.row(label, seen[9:15] + "...", "no" if seen == original else "yes",
              "still runs, on stale data" if use_payload else "fails loudly",
              widths=[26, 24, 12, 26])
        complete(conn, job_id, fence)
    conn.close()
print("""
  Pass the id and reload inside the worker. A serialized copy is a snapshot of
  a decision made at enqueue time, and the gap between enqueue and execution is
  exactly where corrections, deletions and permission changes land -- so a
  snapshot quietly re-does work that someone has already told you was wrong.

  The exception is real and worth stating: pass an immutable value when you
  *want* the snapshot -- a price at order time, the text a user actually
  approved. The rule is that the choice must be deliberate, because both
  options are silent when they are wrong.

  The last column is the other half. A worker that reloads and finds nothing
  fails loudly, which is what you want for a deleted document; a worker holding
  a copy processes it happily and writes an event about a document that no
  longer exists -- the reachability problem
  ../retrieval-freshness-deletion.md found from the retrieval side, arriving
  through the queue.
""")

# --------------------------------------------------------------------------- #
s.rule("5. The three words in the evidence line, separately")
# --------------------------------------------------------------------------- #
print("""  durable       the job survives the process that created it. Section 1:
                this is a property of the write ordering, not of the broker.
                An in-memory queue fails here and so does a committed row with
                no committed intent beside it.

  supervised    something reclaims what nobody finished. Section 3: a state
                flag cannot express this and a lease can. The supervisor is
                the lease expiry plus a bounded attempt count, not a person.

  idempotent    running twice is the same as running once. Sections 2 and 4:
                at-least-once is guaranteed by any lease short enough to be
                useful, so the handler must tolerate it. The fencing token
                makes the duplicate discard its own result; the natural key in
                ../idempotency-keys.md catches the case where it does not.

  All three are needed and none implies another. A durable, supervised queue of
  non-idempotent handlers is a machine for producing duplicates reliably.
""")
