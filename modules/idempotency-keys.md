# Idempotency and retry policy

**Micro module.** One mechanism, one experiment, three cards. Runs against
[service-lab/](service-lab/).

**Capability:** Idempotency and retry policy (Layer 1b, Working ->
Independent). Map evidence: "An idempotent write endpoint with a durable key
and fingerprint." Both adjectives in that line are load-bearing.

---

## The problem

A client timeout is not a server failure. It is an absence of evidence: the
write may have been fully applied, applied with the response lost on the way
back, or never seen. Nothing in HTTP resolves it, as
[http-semantics-streaming.md](http-semantics-streaming.md) section 5 shows, so
the client does the only correct thing available and sends the request again.

The scenario held fixed throughout: **24 extraction requests, 8 of which time
out at the client while succeeding at the server, and are resent.** Nothing
fails. The only question is how many rows exist afterwards.

## The mechanism

**Sequentially, both designs look equivalent:**

```text
server policy                     rows written   duplicates
no idempotency key                32             8
key: check, then insert           24             0
key: insert, let the DB decide    24             0
```

**Concurrently -- which is what a client timeout actually produces -- they are not:**

```text
server policy                         rows written   duplicates   provider calls
no idempotency key                    32             8            32
key: check, then insert               32             8            32
key: insert first, second req 409s    24             0            24
key: insert first, second req waits   24             0            24
```

Check-then-insert is not a narrow race. **The gap between the SELECT and the
INSERT is the work itself** -- a provider call, hundreds of milliseconds -- and
a client timeout is precisely a signal that the work is taking longer than
expected. The retry is therefore aimed at the middle of the window, not at a
random point in it, which is why it caught 8 of 8 here rather than the handful
a "rare race" would suggest.

Making the INSERT of the key the *first* thing that happens moves the decision
into the database, where uniqueness is a constraint rather than an intention.
What remains is a genuine product choice about the second caller: `409 in
progress` is honest and cheap and hands the client a state it now has to
distinguish from failure; wait-and-replay gives the client the answer it wanted
at the cost of holding a connection and a worker for the duration.

**What the key record has to contain:**

```text
stored under the key    retry gets                          client can proceed?
key only                200 {"replayed": true, "body": null}  NO -- no event_id
key + response body     200 {"event_id": 1, "doc_id": ...}    yes
```

A key that records only "seen" makes the retry safe and useless. The write did
not duplicate and the client still lacks the event id it needed, so it will
either give up or ask a different endpoint for it -- and that second lookup is
a new race.

**Same key, different body:**

```text
fingerprint stored?   second request gets   what the client believes
no                    200 {"event_id": 1}   N05 was extracted
yes                   422 key reused        the key was reused
```

Without the fingerprint the server confidently returns N01's event id in
response to a request about N05, status 200, no error anywhere, and the client
stores it. Nothing in any log distinguishes this from correct behaviour,
because from the key's point of view it *was* correct behaviour. The
fingerprint's job is not deduplication -- the key does that -- it is to detect
that two requests sharing a key are not the same request.

**Durable, and for how long.** After a process restart the same key still
replays, because it lives in a table rather than a dict. An in-memory key store
is correct until the first deploy, and a deploy is when clients retry most. The
same argument bounds retention: a key expired at 24 h against a client whose
queue retries for 72 h is a hole that opens only during the incident that
filled the queue.

**The backstop that needs no client cooperation.** `UNIQUE(doc_id,
content_sha)` with no idempotency key at all, on 24 requests covering 8
documents:

```text
natural key   rows written   vs 24 intended
off           32             +8
on             8             -16
```

Read the second row before adopting it. It did not remove the 8 duplicates and
leave 24 -- it left 8, because it also collapsed the 16 requests that were
distinct requests about the same document producing the same answer. That is
the constraint answering the question it was asked:

```text
idempotency key   "is this the same REQUEST?"       -- the client's intent
natural key       "is this the same OBSERVATION?"   -- the data's identity
```

Which one is correct depends on whether re-extracting a document is supposed to
produce a second row: for an append-only event log it is, for a current view of
what a document says it is not, and one of the two wants an UPSERT rather than
a constraint. Two further limits: the natural key only suppresses here because
the provider is at temperature 0 and the extractions agree byte for byte --
change the model, prompt or sampling parameters between the original and the
retry, which is what a fallback route or a mid-incident deploy does, and the
hashes differ so a genuine duplicate is admitted
([model-prompt-registry.md](model-prompt-registry.md) is why those diverge with
nothing being wrong). And it cannot help a write whose content is not
deterministic at all.

Both, then, for different reasons: the key protects the client's intent, the
constraint protects the table from every path that forgot the key.

## The experiment

```powershell
cd modules\service-lab
python idempotency_lab.py     # ~25 s, real threads against a real SQLite file
```

## Boundary

- **SQLite is one writer.** The `UNIQUE` claim generalizes -- Postgres, MySQL
  and DynamoDB all give you the same "let the constraint decide" primitive --
  but the *contention* numbers do not, and a busy Postgres will surface this as
  serialization failures rather than lock waits.
- **The lab writes the response body inline.** A large response, or one
  containing data whose retention is governed, argues for storing a pointer
  and a status instead. That is a real trade, not an oversight.
- **The wait policy is unbounded here except by a 5 s deadline.** In production
  it needs a shorter one than the client's own timeout, or you have two waiters
  in series and the client leaves before either resolves.
- **Nothing here covers idempotency across services.** One database made the
  key a constraint. Two services sharing an intent need either a distributed
  transaction (do not) or the outbox in
  [background-jobs-queues.md](background-jobs-queues.md).

## Cards

### 1. [failure] A POST endpoint checks the idempotency key, does the work, then inserts. Under load it still writes duplicates. Why?

**Answer:** The gap between the check and the insert is the work itself --
often a several-hundred-millisecond provider call -- so it is a wide window,
not a narrow race. In the lab it caught 8 of 8 retries and wrote exactly as
many duplicates as having no key at all.

**Why:** A client timeout is a signal that the work is running long, so the
retry is aimed at the middle of that window rather than at a random moment.

**Boundary:** The fix is to make claiming the key the *first* write and let a
unique constraint decide the winner. The loser then needs a policy -- 409 in
progress, or wait and replay -- and that is a product decision, not a technical
one.

**Tags:** `idempotency` `concurrency` `failure` `general-principle`

---

### 2. [mechanism] An idempotency key record stores the key and a "done" flag. What is missing, and what does each omission cost?

**Answer:** The stored response and a request fingerprint. Without the
response, the retry is safe but useless -- 200 with no event id, so the client
must go find it via some other path. Without the fingerprint, a key reused with
a different body returns the *first* request's answer with status 200 and no
error anywhere.

**Why:** The key proves "I have seen this request", which is only half of what
the retrying client needs; it needs the original outcome, and the server needs
proof that the two requests are actually the same one.

**Boundary:** Storing the response body raises a retention question when the
body contains governed data, and key expiry must exceed the longest retry
window any caller has -- an expiry shorter than a queue's retry horizon opens a
hole precisely during the incident that filled the queue.

**Tags:** `idempotency` `mechanism` `general-principle`

---

### 3. [comparison] An idempotency key versus a natural-key unique constraint on the written row.

**Answer:** The key answers "is this the same request?" and protects the
client's intent; the constraint answers "is this the same observation?" and
protects the table from any path that forgot the key. In the lab the constraint
alone collapsed 24 intended writes to 8, because it cannot see intent.

**Choose the key when** a repeated call must return the original outcome.
**Choose the constraint as well**, always, because it is cheap and catches the
handler nobody added the key to.

**Boundary:** The constraint only suppresses when the content is deterministic.
A model, prompt or sampling change between the original and the retry produces
a legitimately different hash, and the duplicate is admitted -- so it is a
backstop, never the mechanism.

**Tags:** `idempotency` `comparison` `general-principle`
