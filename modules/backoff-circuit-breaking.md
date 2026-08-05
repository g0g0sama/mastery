# Backoff, circuit breaking and rate limits

**Micro module.** One mechanism, one experiment, three cards. Runs against
[service-lab/](service-lab/).

**Capability:** Backoff, circuit breaking, rate limits (Layer 1b, Aware ->
Independent). Map evidence: "A provider client that degrades instead of
amplifying an outage."

---

## The problem

Every one of these mechanisms is a client-side policy about a server-side
problem, and each one is individually defensible. The failure they share is
that none of them can see the others: three reasonable retry policies compose
into a 27x amplification, and a reasonable backoff without jitter turns 60
clients into a wall.

The setup: 60 logical requests over 1.2 s at a real listener that counts what
arrives. The upstream returns 503 for the first 600 ms, so roughly half of them
meet a failing server. A short provider incident.

## The mechanism

**What each policy sends at a server that is already failing:**

```text
client policy                   requests sent   amplification   succeeded
no retry                        60              1.00x           30/60
retry 3x, fixed backoff        116              1.93x           39/60
retry 3x, full jitter          118              1.97x           34/60
retry 3x + retry budget 10%     63              1.05x           31/60
retry 3x + circuit breaker      32              0.53x           25/60
```

Read the first two rows together. Retrying bought real successes -- that is
what it is for -- and it bought them by sending roughly twice the traffic at a
server whose problem may well have been traffic. The client cannot distinguish
"this instance is unlucky" from "this service is saturated", and the same
policy is correct for the first and harmful for the second.

The budget row is the one to copy. A per-request retry count scales *with*
traffic, so it is largest exactly when the provider can least absorb it; a
budget expressed as a fraction of calls has a ceiling that does not move during
an incident. Nothing else in this file has that property. Same argument as
[failure-queues-and-replay.md](failure-queues-and-replay.md) reached from the
queue side.

**Retries multiply through layers, they do not add.** Real servers chained,
each middle layer retrying 3x, upstream down throughout, 10 logical requests
entering at the top:

```text
layers retrying   upstream hits   amplification   predicted
0                  10             1.0x            3^0 = 1x
1                  30             3.0x            3^1 = 3x
2                  90             9.0x            3^2 = 9x
3                 270            27.0x            3^3 = 27x
```

Each layer's policy is defensible on its own and nobody owns the product. The
layers are usually written by different teams reading different runbooks, so
the 27x is not visible in any one code review. Two rules follow: retry at
exactly one layer -- normally the one closest to the failure, which is the only
one that knows whether the error is transient -- and make the **deadline travel
with the request**, so a layer with 200 ms of budget left cannot start a retry
that takes 300 ms. A timeout per call cannot express that; a deadline in the
request can.

**Jitter is not a rounding detail.** 60 clients fail at the same instant and
retry after the same 200 ms ceiling:

```text
backoff                peak / 50 ms   connections lost   drain time
fixed 200 ms           25             23 of 60           1016 ms
full jitter 0-200 ms   20              0 of 60            197 ms
```

The middle column was not part of the plan. The synchronised burst overflowed
the listener's accept backlog and **the OS reset 23 connections the application
never saw**. Those clients get a transport error, which every retry policy
reads as transient, so they retry -- in unison, because they failed in unison.

The drain column is the rest of it. A burst does not arrive faster for having
been sent together; it arrives together and then waits behind itself, and every
client pays that queueing delay on top of the 200 ms it already slept. Put that
spike on a server that has just come back -- cold caches, empty pools, cold JIT
-- and it fails again, everyone backs off in unison again, and the
synchronisation gets *tighter* each round. That is the mechanism behind a
service that will not come up until traffic is shed by hand.

`sleep(random(0, ceiling))` instead of `sleep(ceiling)` is one function call.

**What the breaker is for, and its two failure modes:**

```text
breaker                        upstream hits   short-circuited   succeeded
none                           119             0                 33/60
threshold 5, cooldown 300ms     34             31                28/60
threshold 5, cooldown 3s         6             60                 0/60
```

The breaker's job is not to make the client succeed. It makes the client fail
*faster and cheaper*, which is a different and less popular product. What it
buys is the upstream's chance to recover, and a caller that gets an instant
error rather than holding a connection through three timeouts.

Both failure modes are in the table. A cooldown longer than the outage converts
a 600 ms incident into a self-inflicted one -- and it is the setting raised
after every incident review. At the other end, a breaker that closes fully on
the first success sends the entire held-back load at a server that has proven
exactly one request, which is why half-open admits a *bounded number of probes*
rather than opening the gate.

Two things a breaker must not do. It must not count 4xx errors: a schema
violation is a fact about the request, and breaking on it takes the service down
for one bad caller. And it must not be global across tenants or routes when the
failure is not. Both depend entirely on the transient/terminal split measured in
[provider-errors-retries.md](provider-errors-retries.md).

**Rate limits: the same limit, three meanings.** Limit 10/second; a client sends
10 at t=0.9 s and 10 at t=1.0 s, polite by its own reading of the rule:

```text
limiter          admitted of 20   worst 1s window   burst vs limit
fixed window     20               20                2.0x
sliding log      10               10                1.0x
token bucket     10               10                1.0x
```

The fixed window admits twice its own limit across the boundary and is still
the most commonly implemented, because it is a counter and a modulo. If your
provider enforces a sliding window and you model it as a fixed one, you are
429ing on their side while your dashboard says you are under the limit; the
reverse pairing hands you an outage you cannot see coming.

Token bucket is the one to reach for when the limit protects a resource:
capacity is the burst you will absorb and rate is the refill, which are the two
numbers you actually have opinions about. Sliding log is exact and stores every
timestamp, so it costs memory per key. Whichever you pick, the 429 must carry
`Retry-After` and the client must read it -- a limit response indistinguishable
from a 503 turns every well-behaved client into the first table's second row.

## The experiment

```powershell
cd modules\service-lab
python resilience_lab.py     # ~35 s, real servers and real clocks
```

## Boundary

- **These are real measurements of a real listener and they move between runs.**
  The connections-lost count in particular depends on the backlog the OS gave
  the socket and on what else the machine is doing; 23 of 60 is this machine on
  this run. The direction is stable, the number is not. Re-run it before quoting
  it.
- **Loopback has no RTT**, so backoff constants that look reasonable here are
  not tuned for anything. What transfers is the *shape*: budget beats count,
  jitter beats none, cooldown must be compared against the outage length.
- **The amplification chain uses uniform 3x at every layer.** Real stacks have
  a load balancer, a sidecar, an SDK and a framework, several of which retry by
  default without saying so in your code. The exponent is usually larger than
  the one you can see.
- **Nothing here covers server-side load shedding**, concurrency limits, or
  queue admission control -- which is the other half of not falling over, and
  the half the client cannot do for you.

## Cards

### 1. [decision] A provider client retries 3 times per request. During an incident, what should it retry against instead?

**Answer:** A retry *budget* -- retries capped as a fraction of total calls
(say 10%) -- rather than a count per request. In the lab, 3x-per-request sent
1.93x traffic during an outage; the same policy under a 10% budget sent 1.05x
and lost almost no successes.

**Why:** A per-request count scales with traffic, so total retry load is
largest exactly when the provider can least absorb it. A budget's ceiling does
not move during the incident.

**Boundary:** The budget is a client-side ceiling and does nothing about
multiple layers each retrying: three chained layers at 3x sent 27 upstream
requests per user action. Retry at one layer, and carry a deadline in the
request so a layer with 200 ms left cannot start a 300 ms retry.

**Tags:** `retries` `decision` `general-principle`

---

### 2. [failure] A service will not recover after a brief outage. Load stays synchronised in waves and each wave fails. First suspect?

**Answer:** Backoff without jitter. In the lab 60 clients on a fixed 200 ms
backoff overflowed the accept backlog -- 23 of 60 connections reset by the OS
before the application saw them -- and took 1016 ms to drain, against 0 and
197 ms with full jitter.

**Why:** Clients that failed together retry together. The reset connections are
read as transient errors, so they retry too, and the synchronisation gets
tighter each round rather than looser.

**Boundary:** Fix it with `sleep(random(0, ceiling))`, not by raising the
ceiling -- a longer synchronised wait is still a wave. The second suspect is a
circuit breaker whose cooldown is longer than the outage, which converts a
600 ms incident into a self-inflicted one.

**Tags:** `backoff` `jitter` `failure` `general-principle`

---

### 3. [misconception] A circuit breaker makes the client more likely to succeed during an outage.

**Answer:** It makes the client fail faster and cheaper. In the lab the breaker
cut upstream traffic from 119 requests to 34 and *reduced* successes from 33 to
28.

**Why:** What it buys is the upstream's chance to recover, plus callers that
get an instant error instead of holding connections through three timeouts. It
protects the system, not the request.

**Boundary:** It must not trip on 4xx -- a schema violation is a fact about the
request, so breaking on it takes the service down for one bad caller -- and it
must not be global if the failure is per tenant or per route. Half-open must
admit a bounded number of probes; closing fully on one success sends the whole
held-back load at a server that has proven exactly one request.

**Tags:** `circuit-breaker` `misconception` `general-principle`
