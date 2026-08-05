# Transactions and consistency

**Micro module.** One mechanism, one experiment, three cards. Runs against
[service-lab/](service-lab/).

**Capability:** Transactions and consistency (Layer 1b, Working ->
Independent). Map evidence: "Correct boundary across two repositories under a
seeded failure."

---

## The problem

"The boundary" sounds like one question and is three: does it cover both
writes, what is inside it that should not be, and does it survive two callers
arriving at once. The first is the one people mean, the second is the one that
takes the service down, and the third is the one that corrupts data silently.

## The mechanism

**One intent, two repositories, a failure between them.** 20 documents; the
extraction fails on 5, after the document row is written:

```text
boundary                          documents   events   orphans
each repository commits its own   20          15       5
one transaction around both       15          15       0
```

The repository pattern's own advice -- each repository owns its persistence --
produces the first row, because **a repository that commits has decided the
boundary, and that is not the repository's decision to make.** The boundary
belongs to the use case: the caller opens it, both repositories join it, the
caller commits or rolls back.

Whether 5 orphaned documents are a bug depends on the domain, and that is the
real point. Here they are recoverable work -- a job can extract them later,
which is what [background-jobs-queues.md](background-jobs-queues.md) is for. If
the second write had been "deduct the payment" they would be an incident.
Decide which you have rather than inheriting it from whichever ORM idiom was
nearest.

**What is inside the boundary.** Same work, 8 concurrent ingests, a 30 ms
provider call per document; the only difference is whether that call is inside
the transaction:

```text
provider call            wall time   throughput   lock errors
inside the transaction   0.96 s      26 docs/s    7
outside, before BEGIN    0.47 s      69 docs/s    0
```

Nothing about the work changed. A transaction containing a network call holds
the write lock for the duration of somebody else's latency, so the database's
concurrency is capped by the provider's p99 rather than by its own throughput
-- and callers that cannot get the lock in time do not queue politely, they
fail.

The rule is narrow and worth stating exactly: **do the slow, fallible, external
thing first; open the transaction only around the writes.** A transaction is a
lock on shared state and its cost is measured in the time it is held, not the
number of statements in it. What it costs is that the external call now happens
before the transaction that records it, so it can succeed and go unrecorded --
the same absence-of-evidence problem as
[idempotency-keys.md](idempotency-keys.md), and the reason the extraction must
be replayable rather than exactly-once.

**Read, modify, write, with company.** 8 threads increment one counter 25 times
each; correct answer 200:

```text
strategy                          final value   missing   errors   retries
read; update; commit               50           150         4       0
BEGIN (deferred); read; update     25           175       175       0
BEGIN IMMEDIATE; read; update     198             2         2       0
optimistic: WHERE version=?       200             0         0      11
UPDATE ... SET value=value+1      198             2         2       0
```

Read `missing` and `errors` together; that pairing is the section. This code
does not retry a lock timeout -- it drops the request, which a real service
would not -- so a few increments go missing under every strategy. The
interesting quantity is how many were *reported*: the naive row lost 150 and
reported 4, so **146 vanished in silence**.

That is the lost update. Two callers read 7, both write 8, one increment is
gone, with no error, no warning and no failed statement. It is detectable only
against a total known in advance, which is exactly the number production does
not have. Correctness here is not "nothing was lost", it is "nothing was lost
quietly".

The deferred row is the one worth learning. `BEGIN` in SQLite is *deferred*:
the SELECT takes a read lock and the UPDATE must then upgrade, which fails if
anyone committed in between. Two rules follow and both generalize past SQLite:

- if a transaction will write, **say so when it starts** (`BEGIN IMMEDIATE`,
  `SELECT ... FOR UPDATE`) rather than discovering it at the UPDATE
- when a transaction fails on a conflict, retry the **transaction**, not the
  statement. The values it read are stale by definition -- that is what the
  conflict means -- so re-issuing the UPDATE alone writes a number computed
  from a world that no longer exists

The row also shows what "correct but unusable" looks like: it never writes a
wrong number and it barely writes any. Declaring intent up front collapses 175
conflicts into 2 lock waits, because callers queue for the lock instead of
racing for it and losing.

The last two rows are both correct and are different tools. The optimistic
version check works across a read-think-write gap spanning a user, a request or
a queue; it needs a retry loop and a caller that can handle losing. The atomic
`SET value=value+1` is unbeatable when the new value is a pure function of the
old one, and unavailable the moment it depends on something the database cannot
see.

**Two invariants that no isolation level restores:**

```text
read-modify-write   a value derived from a stale read (above)
write skew          two transactions each read a set, each check an invariant
                    over it, each write a DIFFERENT row, and both commit
```

Write skew is why "we use transactions" is not an answer to "is this invariant
safe". A transaction guarantees your writes land together, not that the world
you read them against still holds. "At most one active extraction per document"
fails exactly this way: both readers see zero, both insert, nobody wrote the
same row so no conflict is detected. An invariant spanning rows that no single
transaction writes needs a constraint (a unique index over the thing being
counted), a lock taken deliberately on a row representing the set, or
serializable isolation plus a retry loop -- and the first is nearly always
cheapest.

Which is where [authn-and-authz.md](authn-and-authz.md) also landed: a rule the
database enforces cannot be forgotten by a code path, and a rule enforced in
application code is enforced once per code path that remembers it.

## The experiment

```powershell
cd modules\service-lab
python tx_lab.py     # ~25 s, real SQLite locks and real threads
```

## Boundary

- **SQLite has one writer, so contention arrives sooner and harder than in
  Postgres.** The failures are the same failures and the thresholds are not.
  Postgres surfaces the deferred-upgrade case as a serialization failure under
  `REPEATABLE READ`/`SERIALIZABLE` rather than a busy timeout, and MVCC means
  readers never block writers -- so the throughput numbers in section 2 would
  be less brutal and the argument identical.
- **The numbers move between runs.** They are real thread races on a real lock;
  150-missing was this run. The ordering of the five strategies is stable, the
  values are not.
- **Section 2's 30 ms "provider call" is a sleep.** A real one is 900 ms
  ([serving-lab](serving-lab/)'s mid-1 latency), which makes the effect roughly
  thirty times worse, not milder.
- **Nothing here covers distributed transactions**, two-phase commit, or
  sagas. The honest summary is that the outbox in
  [background-jobs-queues.md](background-jobs-queues.md) is what you reach for
  instead, and it buys eventual consistency rather than atomicity.

## Cards

### 1. [failure] A use case writes to two repositories. A failure between them leaves half the work committed. Where is the bug?

**Answer:** In the repositories committing at all. Each one owning its own
`commit()` means each has decided the transaction boundary, which belongs to
the use case: the caller opens the transaction, both repositories join it, the
caller commits or rolls back.

**Why:** A boundary is a property of the intent, not of any single table's
access object, so it cannot be composed from pieces that each end their own.

**Boundary:** Whether the half-write is a bug is a domain question. Orphaned
documents that a job can extract later are recoverable; a committed shipment
with no committed payment is an incident. Decide before choosing, and if the
two writes cannot share a transaction at all, use an outbox.

**Tags:** `transactions` `failure` `general-principle`

---

### 2. [decision] Should a provider call sit inside the transaction that records its result?

**Answer:** No. Do the slow, fallible, external work first and open the
transaction only around the writes. In the lab, moving a 30 ms provider call
inside the transaction halved throughput (69 -> 26 docs/s) and produced 7 lock
timeouts where there had been none.

**Why:** A transaction is a lock held on shared state; its cost is the time it
is held. Holding it across a network call caps the database's concurrency at
the provider's latency.

**Boundary:** The cost is that the external call can now succeed and go
unrecorded if the process dies before the commit. That is unavoidable without
distributed transactions -- which is why the operation must be replayable and
keyed, rather than assumed exactly-once.

**Tags:** `transactions` `decision` `general-principle`

---

### 3. [mechanism] A read-modify-write transaction intermittently fails to commit under load. Retry the statement or the transaction?

**Answer:** The transaction, from the read. The conflict means something
committed after your SELECT, so the value you read is stale by definition;
re-issuing only the UPDATE writes a number computed from a world that no longer
exists.

**Why:** A deferred transaction takes a read lock first and must upgrade to
write. The upgrade is what fails, and it fails precisely because the read is no
longer valid.

**Boundary:** Better still, do not get there: declare the write intent when the
transaction starts (`BEGIN IMMEDIATE`, `SELECT ... FOR UPDATE`) so callers
queue for the lock instead of racing and losing -- in the lab that turned 175
conflicts into 2. If the new value is a pure function of the old, skip all of
it with `SET value = value + 1`.

**Tags:** `transactions` `concurrency` `mechanism` `general-principle`
