# service-lab

A shared fixture for eight micro modules covering Layer 1b (backend systems).
Not a module itself.

```powershell
cd modules\service-lab
python http_lab.py         # ../http-semantics-streaming.md    (~12 s, binds a port)
python auth_lab.py         # ../authn-and-authz.md             (~3 s)
python idempotency_lab.py  # ../idempotency-keys.md            (~25 s, threads)
python resilience_lab.py   # ../backoff-circuit-breaking.md    (~35 s, threads)
python jobs_lab.py         # ../background-jobs-queues.md      (~20 s, threads)
python tx_lab.py           # ../transactions-and-consistency.md (~25 s, threads)
python cache_lab.py        # ../caching.md                     (~20 s)
python storage_lab.py      # ../object-storage-and-files.md    (~5 s, writes files)
```

CPython 3.14, stdlib only. `service.py` reuses the fake provider and the
extraction task from [../model-interface-lab/](../model-interface-lab/) via a
`sys.path` insert, so a record produced here is the same record the Layer 4,
7 and 9 modules produce, with the same token counts and prices.

| File | Role |
|---|---|
| `service.py` | the listener, the store, the work, and the two tenants |
| `http_lab.py` | a mid-stream failure, a vanished client, and what cancellation costs |
| `auth_lab.py` | six endpoints, one rule, and the five that get it wrong |
| `idempotency_lab.py` | one client timeout, five server answers |
| `resilience_lab.py` | retry, jitter, breaker and rate limiter against a real outage |
| `jobs_lab.py` | two writes, one lease, one killed worker, one stale payload |
| `tx_lab.py` | where the boundary starts, what is inside it, and who else is writing |
| `cache_lab.py` | a hit rate that is not the saving, and three incomplete keys |
| `storage_lab.py` | what a hash means, and what a filename does |

## What is real here

Like [../store-lab/](../store-lab/), and unlike the other five fixtures, **the
machinery is real**:

- **real** -- a TCP listener on 127.0.0.1, HTTP/1.1 framing and chunked
  transfer, kernel socket buffers, connection resets, accept-queue overflow,
  SQLite transactions and lock contention, OS thread interleaving, file writes,
  renames, hashing, and the filesystem's own opinions about filenames. Every
  race below is a race the interpreter and the kernel actually ran; nothing
  schedules a duplicate on purpose.
- **real, with a declared failure distribution** -- the extraction records,
  from `../model-interface-lab/provider.py`, whose failure weights are asserted
  rather than discovered.
- **declared** -- request and arrival volumes, the two-tenant layout, provider
  latency (a `sleep`), outage windows, the cache workload's Zipf shape and its
  cost skew, and the 8-document corpus.
- **derived** -- hit rates, amplification factors, duplicate counts as
  fractions, and every delta the labs print.

Two consequences worth stating before reading any table:

**Loopback flatters everything.** No RTT, no packet loss, no proxy, no load
balancer, no TLS record layer, no second machine. Where a number depends on the
network -- the 149,504 bytes written after a client left, the backoff constants,
the throughput figures -- the *direction* transfers and the magnitude does not.

**These numbers move between runs.** They are real thread races against real
locks and a real accept queue. The orderings are stable; the values are this
machine on this run. Anything quoted outside the repository should be re-run
first.

## The centre of gravity

One event, and it is not a failure: **a client whose request timed out, and who
therefore sends it again.** The server did not fail. `http_lab.py` section 5
shows why no status code can resolve it -- a timeout is an absence of evidence,
not a result -- and the rest of the fixture is what each layer does with the
second delivery:

```text
idempotency   a key claimed before the work, or 8 duplicate rows
jobs          a lease that expired on a worker that is merely slow
transactions  two callers reading the same row and both writing
caching       40 callers missing the same key at the same instant
storage       the same bytes arriving twice under a different name
```

Two of the eight are about the layer that cannot see it happened: `auth_lab.py`,
where the cache and the batch endpoint answer before the check, and
`http_lab.py`, where the server cannot distinguish a cancelled request from a
crashed client.

## Read in this order

1. `http-semantics-streaming` -- the wire, and the two beliefs about it that
   are false
2. `authn-and-authz` -- who is asking, and whether they may have this object
3. `idempotency-keys` -- the same request twice, which is the fixture's subject
4. `backoff-circuit-breaking` -- the same request many times, on purpose
5. `background-jobs-queues` -- the request that outlives its connection
6. `transactions-and-consistency` -- what the writes underneath all of it
   guarantee
7. `caching` -- the answer you did not compute, and what it is keyed on
8. `object-storage-and-files` -- the bytes, and why their name is a hash

The order is a dependency chain rather than a preference: 3 before 4 because a
retry policy without idempotency is a duplicate generator; 5 after 3 because a
queue is at-least-once and needs the same key; 6 after 5 because the outbox in
5 is a claim about transactions; 7 late because a cache key needs the tenant
from 2 and the config id from `../model-prompt-registry.md`.

## What this fixture cannot show

- **Scale.** One process, one SQLite file, one machine, no proxy. SQLite has a
  single writer, so contention in `tx_lab.py` arrives sooner and harder than
  Postgres would; the failures are the same failures and the thresholds are not.
- **A real broker, a real cache server, a real object store.** Each is
  simulated to the depth of one measurement. Redis being down, S3 having no
  rename, and Kafka rebalancing a consumer group are all absent.
- **Server-side load shedding**, admission control and concurrency limits --
  the other half of not falling over, and the half a client cannot do for you.
- **Ownership.** Who is paged when the outbox stops draining, who reviews a
  bulk replay, what queue age alerts at. Half of Layer 1b in practice, none of
  it here.

A module here is evidence of exposure, not of level. Levels move in
[../../capability-map.md](../../capability-map.md), and only on the five
conditions in the cycle's evidence contract.
