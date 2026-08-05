# Background jobs and queues

**Micro module.** One mechanism, one experiment, three cards. Runs against
[service-lab/](service-lab/).

**Capability:** Background jobs and queues (Layer 1b, Aware -> Independent).
Map evidence: "A durable job with supervision, retry, and idempotent
execution."

---

## The problem

Three adjectives in that evidence line, each of which fails independently, and
none of which the queue library gives you. Durability is decided by the order
of two writes you make before the queue is involved at all. Supervision is
decided by whether a claim can expire. Idempotence is forced on you by the
first two, whether or not the handler is ready for it.

## The mechanism

**Two writes, one intent, and a process that stops between them.** Ingesting a
document means storing it *and* scheduling its extraction. Those are two
systems. The process is killed between them on 5 of 20:

```text
write order                         docs   jobs   docs w/o job   jobs w/o doc
row committed, then enqueued        20     15     5              0
enqueued, then row committed        15     20     0              5
outbox: one transaction + relay     20     20     0              0
```

The first two rows are the same bug wearing different clothes, and they are not
equally bad. A document with no job is **silent**: nothing errors, the
extraction simply never happens, and you find out from a customer. A job with
no document is **loud**: the worker fails immediately, retries, dead-letters,
and puts itself on a dashboard. Given a forced choice, prefer loud.

The choice is not forced. The outbox writes the intent inside the same
transaction as the data, so a crash takes both or neither, and a relay --
allowed to run late, twice, or after a restart -- turns committed intent into a
queued job. What it buys is that the queue is no longer a second system inside
your transaction. What it costs is a relay that must itself be supervised,
because an outbox nobody drains is a document with no job again, just with
better evidence.

**A lease expiring is not the same as a worker dying.** One job, 150 ms lease.
Worker A is slow (400 ms) but alive; worker B claims the expired lease and also
finishes:

```text
fencing token: off    2 writes    A (slow) fence=1, B fence=2
fencing token: on     1 write     B fence=2
```

A visibility timeout does not stop the first worker. It cannot -- the queue has
no way to interrupt a thread on another machine that is merely slow, and "slow"
and "dead" are indistinguishable from here. So **at-least-once is not a
property of an unreliable broker; it is a property of any lease short enough to
be useful.**

The fencing token is what makes the duplicate harmless. Every claim increments
a counter, the worker carries its number, and the write is conditional on still
holding it -- `WHERE job_id=? AND fence=?`. The stale worker's UPDATE matches
zero rows and it discards its own result. This is the only thing in the file
that makes a stolen lease *safe* rather than merely detectable.

**Supervision: what happens to what nobody finished.** 20 jobs, 4 workers, 5
killed mid-job:

```text
claim mechanism         done   stuck   recovered by sweep
state flag, no lease     9     11      impossible
lease + expiry          19      1      4 jobs, attempts>1
```

A state flag records that a job was taken. It cannot record that the taker is
gone, so a killed worker's jobs sit in `leased` forever and restarting the
workers does not help -- those rows no longer match `state='ready'`. Every
queue that has ever needed a manual `UPDATE jobs SET state='ready'` at 3am has
this shape.

A lease with an expiry makes the same row reclaimable with nobody deciding.
What it needs in exchange is the fencing check above and a bounded attempt
count, because a job that killed its worker will now kill the next one --
the poison item measured in
[failure-queues-and-replay.md](failure-queues-and-replay.md).

**What the job carries: an id, or a copy.** A document is corrected between
enqueue and execution -- a re-fetch, an OCR fix, a redaction:

```text
payload                worker sees       correct?   if the doc was deleted
snapshot of the body   ...三月十日在深圳    no         still runs, on stale data
document id only       ...三月十一日在合肥  yes        fails loudly
```

Pass the id and reload inside the worker. A serialized copy is a snapshot of a
decision made at enqueue time, and the gap between enqueue and execution is
exactly where corrections, deletions and permission changes land -- so a
snapshot quietly re-does work someone has already said was wrong. The exception
is real: pass an immutable value when you *want* the snapshot, such as a price
at order time or the text a user actually approved. The rule is that the choice
be deliberate, because both options are silent when wrong.

The last column is the other half. A worker that reloads and finds nothing
fails loudly, which is correct for a deleted document; a worker holding a copy
processes it happily and writes an event about a document that no longer exists
-- the reachability problem
[retrieval-freshness-deletion.md](retrieval-freshness-deletion.md) found from
the retrieval side, arriving through the queue.

**The three words, separately:**

```text
durable      the job survives the process that created it -- a property of
             write ordering, not of the broker
supervised   something reclaims what nobody finished -- a lease expiry plus a
             bounded attempt count, not a person
idempotent   running twice equals running once -- forced on you by any useful
             lease, so the handler must tolerate it
```

All three are needed and none implies another. A durable, supervised queue of
non-idempotent handlers is a machine for producing duplicates reliably.

## The experiment

```powershell
cd modules\service-lab
python jobs_lab.py     # ~20 s, real threads against a real SQLite file
```

## Boundary

- **SQLite's `UPDATE ... RETURNING` gives an atomic claim for free** because
  there is one writer. Postgres needs `FOR UPDATE SKIP LOCKED`; a broker gives
  you a visibility timeout instead. The lease *argument* transfers exactly; the
  claim statement does not.
- **A real broker adds problems this lab has none of**: partition ordering,
  consumer rebalancing, redelivery on rebalance, and a dead-letter policy you
  do not control. Some of them make at-least-once worse, none makes it better.
- **The crash here is an exception between two commits.** A real kill -9 can
  also land inside a commit, mid-fsync, or after the commit but before the
  acknowledgement -- which is the same absence-of-evidence problem as
  [idempotency-keys.md](idempotency-keys.md), one layer down.
- **Nothing here covers ownership.** Who is paged when the outbox stops
  draining, who reviews a bulk replay, and what queue *age* alerts at are the
  operational half, and the queue that nobody drains remains the commonest
  failure of all.

## Cards

### 1. [decision] An endpoint saves a document and enqueues its extraction. Which write goes first, and why is the question wrong?

**Answer:** The question is wrong because either order loses on a crash between
them: row-first leaves 5 documents with no job (silent -- the work simply never
happens), job-first leaves 5 jobs with no document (loud -- the worker fails and
dead-letters). Write the intent to an outbox table inside the same transaction
as the row, and let a relay turn it into a queued job.

**Why:** Two systems and one atomic intent with no shared transaction. Only
moving the intent into the transaction removes the gap; the relay may then run
late, twice, or after a restart without harm.

**Boundary:** If you must pick an order, pick the loud one. And the relay is
now the thing that needs supervising -- an outbox nobody drains is the silent
failure again with better evidence.

**Tags:** `queues` `outbox` `decision` `general-principle`

---

### 2. [misconception] Duplicate job execution means the broker delivered twice.

**Answer:** It usually means a lease expired on a worker that was slow, not
dead. In the lab worker A held a 150 ms lease, took 400 ms, and both A and B
completed the same job -- with no broker involved and nothing malfunctioning.

**Why:** A visibility timeout cannot interrupt a worker; from the queue's side
"slow" and "dead" are the same observation. So at-least-once is a consequence
of any lease short enough to be useful.

**Boundary:** The fix is a fencing token -- increment a counter on each claim,
carry it into the worker, and make the write conditional (`WHERE job_id=? AND
fence=?`) so the stale worker's update matches zero rows and it discards its
result. Raising the lease timeout only widens the window in which a genuinely
dead worker's job is stuck.

**Tags:** `queues` `leases` `misconception` `general-principle`

---

### 3. [why] Why should a background job receive a document id rather than the document body?

**Answer:** So the worker reads the current state. In the lab a job carrying a
snapshot extracted from text that had already been corrected, and reported
success; the job carrying only the id extracted from the corrected text.

**Why:** The gap between enqueue and execution is exactly where corrections,
deletions and permission changes land. A serialized payload freezes a decision
made before them.

**Boundary:** Pass an immutable value when the snapshot is the point -- a price
at order time, text a user approved. And note the deletion case: reloading
fails loudly for a document that is gone, whereas a snapshot processes happily
and writes an event about something that no longer exists.

**Tags:** `queues` `why` `general-principle`
