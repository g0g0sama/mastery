"""The client whose request timed out, and the five ways a server answers it twice.

    python idempotency_lab.py     # ~25 s, real threads against a real SQLite file

Map evidence line: "an idempotent write endpoint with a durable key and
fingerprint". Both adjectives in that line are load-bearing and each is worth a
section.

The scenario, held fixed throughout: 24 extraction requests are sent, 8 of them
time out at the client while succeeding at the server, and the client -- doing
exactly the right thing -- sends those 8 again. Nothing fails. The only
question is how many rows exist afterwards.
"""
from __future__ import annotations

import json
import sqlite3
import threading
import time

import service as s

N_REQUESTS = 24
RETRIED = 8                       # of those, this many time out and are resent
WORK = 0.05                       # seconds of provider time inside the window


# --------------------------------------------------------------------------- #
class API(s.Handler):
    """POST /extractions, Idempotency-Key header. Policy set per experiment."""

    db = None
    mode = "none"          # none | check_insert | unique
    inflight = "again"     # again | conflict | wait
    store_response = True
    fingerprint = True
    natural_key = False    # UNIQUE(doc_id, content_sha) as a second line

    def work(self, conn, doc_id, key):
        record, status = s.extract(doc_id, latency=WORK)
        if status != "ok":
            return 502, {"error": status}
        csha = s.content_sha(record)
        try:
            cur = conn.execute(
                "INSERT INTO events (doc_id, tenant, event_type, event_date,"
                " actors, content_sha, request_id, created_at)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (doc_id, "acme", record["event_type"], record.get("date"),
                 json.dumps(record["actors"], ensure_ascii=False), csha, key,
                 time.time()))
            conn.commit()
            return 201, {"event_id": cur.lastrowid, "doc_id": doc_id,
                         "content_sha": csha}
        except sqlite3.IntegrityError:
            # only reachable with natural_key on: the row is already there and
            # says the same thing, so this request has nothing to add
            conn.rollback()
            row = conn.execute(
                "SELECT event_id FROM events WHERE doc_id=? AND content_sha=?",
                (doc_id, csha)).fetchone()
            return 200, {"event_id": row[0], "doc_id": doc_id,
                         "content_sha": csha, "suppressed": True}

    def do_POST(self):                                  # noqa: N802
        body = self.read_json()
        key = self.headers.get("Idempotency-Key")
        doc_id = body["doc_id"]
        fp = s.sha(json.dumps(body, sort_keys=True))[:16]
        conn = s.connect(self.db)
        try:
            if self.mode == "none" or not key:
                return self.send_json(*self.work(conn, doc_id, key))

            if self.mode == "check_insert":
                # Look, then leap. The gap between the two is the work itself,
                # which is exactly why this is not a narrow window.
                row = conn.execute("SELECT state, response, fingerprint FROM idem"
                                   " WHERE key=?", (key,)).fetchone()
                if row and row[0] == "done":
                    return self.replay(row, fp)
                status, resp = self.work(conn, doc_id, key)
                conn.execute("INSERT OR REPLACE INTO idem VALUES (?,?,?,?,?,?)",
                             (key, "acme", fp, "done",
                              json.dumps(resp) if self.store_response else None,
                              time.time()))
                conn.commit()
                return self.send_json(status, resp)

            # mode == "unique": claim the key first, and let the database
            # decide who won. The INSERT is the lock.
            try:
                conn.execute("INSERT INTO idem VALUES (?,?,?,?,?,?)",
                             (key, "acme", fp, "in_progress", None, time.time()))
                conn.commit()
            except sqlite3.IntegrityError:
                # A failed statement does NOT end the transaction. Leaving it
                # open holds a write lock and blocks every other writer while
                # this request sits in a polling loop -- which is how the wait
                # policy turned into a deadlock the first time this file ran.
                conn.rollback()
                return self.existing(conn, key, fp)
            status, resp = self.work(conn, doc_id, key)
            conn.execute("UPDATE idem SET state='done', response=? WHERE key=?",
                         (json.dumps(resp) if self.store_response else None, key))
            conn.commit()
            return self.send_json(status, resp)
        finally:
            conn.close()

    def existing(self, conn, key, fp):
        deadline = time.time() + 5.0
        while True:
            row = conn.execute("SELECT state, response, fingerprint FROM idem"
                               " WHERE key=?", (key,)).fetchone()
            if row[0] == "done":
                return self.replay(row, fp)
            if self.inflight == "conflict":
                return self.send_json(409, {"error": "in progress", "key": key})
            if self.inflight == "again":
                return self.send_json(*self.work(conn, "N01", key))
            if time.time() > deadline:
                return self.send_json(504, {"error": "timed out waiting"})
            time.sleep(0.01)

    def replay(self, row, fp):
        state, response, stored_fp = row
        if self.fingerprint and stored_fp != fp:
            # Same key, different request. Returning the old answer here is the
            # quietest bug in this file.
            return self.send_json(422, {"error": "key reused with a different body"})
        if response is None:
            return self.send_json(200, {"replayed": True, "body": None})
        return self.send_json(200, json.loads(response) | {"replayed": True})


# --------------------------------------------------------------------------- #
def run(base, *, concurrent: bool, keys: bool = True, mutate_body=None):
    """Send N_REQUESTS, retry RETRIED of them, collect the statuses."""
    results, lock = [], threading.Lock()

    def send(i, attempt):
        doc = s.DOC_IDS[i % len(s.DOC_IDS)]
        body = {"doc_id": doc, "n": i}
        if mutate_body and attempt == 1:
            body = mutate_body(body)
        hdr = {"Idempotency-Key": f"req-{i}"} if keys else {}
        st, resp = s.post(base, "/extractions", body, headers=hdr)
        with lock:
            results.append((i, attempt, st, resp))

    threads = []
    for i in range(N_REQUESTS):
        attempts = [0, 1] if i < RETRIED else [0]
        for a in attempts:
            t = threading.Thread(target=send, args=(i, a))
            threads.append(t)
            if concurrent:
                t.start()
            else:
                t.start(); t.join()
    if concurrent:
        for t in threads:
            t.join()
    return results


def fresh(d, *, natural_key: bool = False) -> str:
    """A new database file with the schema already in place."""
    db = str(d / "svc.db")
    conn = s.store(db)
    if natural_key:
        conn.execute("CREATE UNIQUE INDEX ux_nat ON events(doc_id, content_sha)")
    conn.commit()
    conn.close()
    return db


def rows(db):
    conn = s.connect(db)
    n = conn.execute("SELECT count(*) FROM events").fetchone()[0]
    dupes = conn.execute(
        "SELECT count(*) FROM (SELECT doc_id, content_sha, count(*) c"
        " FROM events GROUP BY 1,2 HAVING c>1)").fetchone()[0]
    conn.close()
    return n, dupes


print(f"{N_REQUESTS} extraction requests. {RETRIED} of them time out at the client\n"
      f"and are sent again. Nothing fails. Correct outcome: {N_REQUESTS} rows.\n")

# --------------------------------------------------------------------------- #
s.rule("1. The retry arrives after the first one finished")
# --------------------------------------------------------------------------- #
s.row("server policy", "rows written", "duplicates", "verdict",
      widths=[40, 15, 13, 12])
for label, attrs in [
    ("no idempotency key", dict(mode="none")),
    ("key: check, then insert", dict(mode="check_insert")),
    ("key: insert, let the DB decide", dict(mode="unique")),
]:
    with s.workdir() as d:
        db = fresh(d)
        with s.serve(API, db=db, **attrs) as base:
            run(base, concurrent=False)
        n, dupes = rows(db)
    s.row(label, n, n - N_REQUESTS, "ok" if n == N_REQUESTS else "WRONG",
          widths=[40, 15, 13, 12])
print("""
  Sequentially, both key designs work and the difference between them looks
  like taste. It is not.
""")

# --------------------------------------------------------------------------- #
s.rule("2. The retry arrives while the first one is still running")
# --------------------------------------------------------------------------- #
print(f"Same 8 retries, sent concurrently with the original -- which is what a\n"
      f"{WORK * 1000:.0f} ms client timeout against {WORK * 1000:.0f} ms of work "
      f"actually produces.\n")
s.row("server policy", "rows written", "duplicates", "provider calls",
      widths=[40, 15, 13, 15])
for label, attrs in [
    ("no idempotency key", dict(mode="none")),
    ("key: check, then insert", dict(mode="check_insert")),
    ("key: insert first, second req 409s", dict(mode="unique", inflight="conflict")),
    ("key: insert first, second req waits", dict(mode="unique", inflight="wait")),
]:
    with s.workdir() as d:
        db = fresh(d)
        with s.serve(API, db=db, **attrs) as base:
            res = run(base, concurrent=True)
        n, dupes = rows(db)
    calls = sum(1 for _, _, st, _ in res if st in (201, 502))
    s.row(label, n, n - N_REQUESTS, calls, widths=[40, 15, 13, 15])
print("""
  Check-then-insert is not a narrow race. The gap between the SELECT and the
  INSERT is the work itself -- a provider call, hundreds of milliseconds --
  and a client timeout is precisely a signal that the work is taking longer
  than expected, so the retry is aimed at the middle of the window.

  Making the INSERT of the key the first thing that happens moves the decision
  into the database, where uniqueness is a constraint rather than an intention.
  What is left is a genuine product choice about the second caller:

    409 in progress   honest, cheap, and pushes the problem to a client that
                      now has to distinguish "retry later" from "you failed"
    wait and replay   the client gets the answer it wanted, at the cost of
                      holding a connection and a worker for the duration
""")

# --------------------------------------------------------------------------- #
s.rule("3. What the key record has to contain")
# --------------------------------------------------------------------------- #
print("Retry after completion, under three storage choices:\n")
s.row("stored under the key", "retry gets", "client can proceed?",
      widths=[34, 34, 22])
for label, attrs, probe in [
    ("key only", dict(mode="unique", store_response=False),
     "200 with an empty body"),
    ("key + response body", dict(mode="unique", store_response=True), None),
]:
    with s.workdir() as d:
        db = fresh(d)
        with s.serve(API, db=db, **attrs) as base:
            st1, r1 = s.post(base, "/extractions", {"doc_id": "N01"},
                             headers={"Idempotency-Key": "k1"})
            st2, r2 = s.post(base, "/extractions", {"doc_id": "N01"},
                             headers={"Idempotency-Key": "k1"})
    got = f"{st2} {json.dumps(r2, ensure_ascii=False)[:26]}"
    s.row(label, got, "yes" if r2.get("event_id") else "NO -- no event_id",
          widths=[34, 34, 22])
print("""
  A key that records only "seen" makes the retry safe and useless: the write
  did not duplicate, and the client still does not have the event id it needed.
  It will now either give up or ask a different endpoint for it, and the second
  is a new race. Store the response, not just the key.
""")

# --------------------------------------------------------------------------- #
s.rule("4. Same key, different body")
# --------------------------------------------------------------------------- #
print("A client bug (or a reused key from a retry library) sends key k1 twice\n"
      "with two different documents:\n")
s.row("fingerprint stored?", "second request gets", "what the client believes",
      widths=[24, 30, 36])
for fp_on in (False, True):
    with s.workdir() as d:
        db = fresh(d)
        with s.serve(API, db=db, mode="unique", fingerprint=fp_on) as base:
            s.post(base, "/extractions", {"doc_id": "N01"},
                   headers={"Idempotency-Key": "k1"})
            st, r = s.post(base, "/extractions", {"doc_id": "N05"},
                           headers={"Idempotency-Key": "k1"})
    belief = ("N05 was extracted" if st == 200 and r.get("doc_id") == "N01"
              else "the key was reused")
    s.row("yes" if fp_on else "no", f"{st} {json.dumps(r)[:22]}",
          belief, widths=[24, 30, 36])
print("""
  Without the fingerprint the server confidently returns N01's event id in
  response to a request about N05, with status 200 and no error anywhere. The
  client stores it. Nothing in any log distinguishes this from correct
  behaviour, because from the key's point of view it *was* correct behaviour.

  The fingerprint is a hash of the request that the key claims to be about. Its
  job is not deduplication -- the key does that -- it is to detect that the two
  requests sharing a key are not the same request, and 422 is the only honest
  answer.
""")

# --------------------------------------------------------------------------- #
s.rule("5. Durable, and for how long")
# --------------------------------------------------------------------------- #
with s.workdir() as d:
    db = fresh(d)
    with s.serve(API, db=db, mode="unique") as base:
        s.post(base, "/extractions", {"doc_id": "N01"},
               headers={"Idempotency-Key": "k9"})
    # a "restart": in-memory keys would be gone here; the table is not
    with s.serve(API, db=db, mode="unique") as base:
        st, r = s.post(base, "/extractions", {"doc_id": "N01"},
                       headers={"Idempotency-Key": "k9"})
    n, _ = rows(db)
print(f"""  after a process restart, the same key returns {st} replayed={r.get('replayed')}
  and the table holds {n} row, because the key lives in the database rather
  than in a dict.

  An in-memory key store is correct until the first deploy, and a deploy is
  when clients retry most. The same argument bounds the *retention*: a key
  expired at 24 h against a client whose queue retries for 72 h is a hole that
  opens only during the incident that filled the queue. Expiry has to be longer
  than the longest retry window any caller has, and that is a number you have
  to ask for rather than pick.
""")

# --------------------------------------------------------------------------- #
s.rule("6. The backstop that needs no client cooperation")
# --------------------------------------------------------------------------- #
print("UNIQUE(doc_id, content_sha) on the events table, with NO idempotency key.\n"
      "The 24 requests cover 8 documents, so 3 requests genuinely ask about each.\n")
s.row("natural key", "rows written", "vs 24 intended", "note", widths=[16, 15, 16, 38])
for nat in (False, True):
    with s.workdir() as d:
        db = fresh(d, natural_key=nat)
        with s.serve(API, db=db, mode="none", natural_key=nat) as base:
            run(base, concurrent=True, keys=False)
        n, dupes = rows(db)
    s.row("on" if nat else "off", n, f"{n - N_REQUESTS:+d}",
          "one row per distinct observation" if nat else "every retry is a row",
          widths=[16, 15, 16, 38])
print("""
  Read the second row carefully before adopting it. It did not remove the 8
  duplicates and leave 24 -- it left 8, because it also collapsed the 16
  requests that were distinct requests about the same document producing the
  same answer. That is not a bug in the constraint, it is the constraint
  answering the question it was asked.

    idempotency key   "is this the same REQUEST?"      -- the client's intent
    natural key       "is this the same OBSERVATION?"  -- the data's identity

  Which one is correct depends on whether re-extracting a document is supposed
  to produce a second row. For an append-only event log it is; for a current
  view of what a document says it is not, and one of the two needs an UPSERT
  rather than a constraint.

  Two further limits on the natural key. It only suppresses because this
  provider is at temperature 0 and the two extractions agree byte for byte;
  change the model, the prompt or the sampling parameters between the original
  and the retry -- which is exactly what a fallback route or a mid-incident
  deploy does -- and the hashes differ, so a genuine duplicate is admitted.
  ../model-prompt-registry.md is why those diverge with nothing being wrong.
  And it cannot help a write whose content is not deterministic at all.

  So: both, and for different reasons. The key protects the client's intent;
  the constraint protects the table from every path that forgot the key.
""")
