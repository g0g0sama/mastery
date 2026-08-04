# TTFT, throughput and latency percentiles

**Micro module.** One mechanism, one experiment, three cards. Runs against
[serving-lab/](serving-lab/).

**Capability:** TTFT, throughput, latency percentiles (Layer 8, Aware ->
Independent). Map evidence: "p50/p95 measured under concurrency, not single
requests."

---

## The problem

The map row puts the weight on *under concurrency*. The engine in
`latency_lab.py` is a sleep-based stand-in -- no weights, no GPU -- and
everything the row is actually about is real: the threads, the queue, the
clock, the arrival process, and the arithmetic that turns 200 samples into a
p99. Those are the parts that get measurement wrong in production too.

## The mechanism

**Start by measuring the instrument.**

```text
time.sleep(1 ms) actually takes: median 1.525 ms, p95 1.572, p99 1.625, max 1.989
perf_counter() call overhead: 87 ns
```

A 3% improvement is not measurable on a harness whose own p99 is 60% above its
target. This is the first question to ask of any benchmark, and it is asked
almost never.

**Throughput saturates long before latency stops rising.**

```text
clients  req/s    TTFT p50   TTFT p95   e2e p50   e2e p95   e2e p99   e2e mean
1           6.3       26.0       34.0     114.7     341.9     661.9     159.7
2          11.6       26.1       33.8     122.8     366.3     716.9     172.3
4          19.1       26.1       33.8     143.3     420.5     857.6     199.1
8          19.1       26.3     2563.2     146.9    2817.6    3141.2     379.2
16         19.5       27.3     2465.8     177.3    2821.0    3075.2     676.7
```

Past the slot count, every additional client buys queueing and nothing else.
Single-request latency multiplied by client count is not an estimate of anything.

**Coordinated omission: the same server, timed from two instants.**

```text
harness / metric                  offered  p50       p90       p95       p99
closed loop, 8 clients              18.9    157.2     419.9     628.5    5081.2
open loop, thread per arrival       18.8    735.0    1060.1    1134.2    1300.2
open loop, 8 senders, from send     18.8    178.2     423.1     569.4    6357.1
  ... same run, from arrival        18.8    590.9     943.7    1063.3    6357.5

understatement:                             3.3x      2.2x      1.9x      1.0x
```

The last two rows are the **same requests on the same run**, timed from when the
sender got around to issuing them versus when they were scheduled to arrive.
When every sender thread is blocked on a slow response, the arrivals that should
have happened do not -- the harness stops sampling exactly when the server is
worst.

Two things about this table are worth more than the effect itself:

- A **closed-loop** harness (N clients, each sending when the last returns)
  reports a p50 of 157 ms for a server that an open-loop measurement at the same
  throughput puts at 735 ms. The closed-loop client is a self-throttling client,
  and real traffic does not wait to be asked.
- The understatement is largest **in the body of the distribution**, not at the
  extreme tail: the single slowest request is slow from either reference point,
  while the requests that were never issued would have populated p50 through
  p95. A report that quotes only p99 can miss the whole effect.

**The mean is not a summary of a latency distribution.**

```text
n=120, mean 580.0 ms, p50 156.8 ms, p99 6134.2 ms
fraction of requests worse than the mean: 8%
p99/p50 ratio: 39.11x
```

And the p99 is not the number it appears to be either:

```text
p99 = 6134.2 ms, bootstrap 95% CI [5911.2, 6271.2]  -- from 2 samples
p50 =  156.8 ms, bootstrap 95% CI [ 140.1,  185.5]
```

At n=120 the p99 *is* the two slowest samples. The same arithmetic as
[eval-set-sample-size.md](eval-set-sample-size.md), arriving from the other
direction: a tail percentile from a few hundred requests is a wide interval
reported as a single number.

**One "latency" is at least three metrics.**

```text
config       req/s   TTFT p50   TTFT p95   e2e p50   tok/s
A: 4 slots    19.9       26.3     3589.9     156.1     609
B: 8 slots    31.4       26.2     2165.2     190.1     960
```

More slots means more sequences sharing each step: the engine finishes more of
them while each individual one decodes more slowly. Which number is
"performance" depends on whether a human is watching the tokens appear.

## The experiment

```powershell
cd modules\serving-lab
python latency_lab.py     # ~60 seconds; it is mostly sleeping on purpose
```

## Boundary

- **The engine is sleeps.** No model, no memory pressure, no GPU scheduling. The
  contention model (`CONTENTION = 0.10`, each in-flight sequence slows the step)
  is authored; the queueing that follows from it is not.
- **Sleep resolution is the floor**, ~1.5 ms for a 1 ms request. Effects smaller
  than that are invisible here and the section-0 table says so.
- **Percentiles are nearest-rank**, not interpolated. At n=200 the difference
  between p99 definitions is larger than most optimizations, which is a reason to
  state the definition rather than a reason to prefer one.
- **What this cannot show:** GPU-side queueing, batch formation delay in a real
  engine, network and TLS costs, or the effect of a garbage collector. All of
  those land in the same percentiles and none of them are modelled.

## Cards

### 1. [failure] Your load test says p99 is 600 ms. Users report multi-second waits at the same hour.

**Answer:** Check whether the harness is closed-loop -- a fixed number of
clients, each sending when the last response returns. Such a client cannot
produce a queue, so it measures a server that is never behind. In the lab, the
same server at the same throughput read 157 ms at p50 closed-loop and 735 ms
open-loop.

**Why:** Coordinated omission. Latency must be measured from the *intended*
arrival time. When the load generator is itself blocked, the requests that would
have been slowest are never issued.

**Boundary:** The understatement was largest at p50-p95 (3.3x, 2.2x, 1.9x) and
vanished at p99, because the single slowest request is slow from any reference
point. Comparing only p99 across harnesses can hide the problem entirely.

**Tags:** `serving` `failure` `general-principle`

---

### 2. [decision] The engine change raises throughput 58% and TTFT p50 is unchanged. Ship it?

**Answer:** Ask which latency. In the lab, doubling the decode slots raised
req/s from 19.9 to 31.4 and tok/s from 609 to 960, while e2e p50 got worse (156
-> 190 ms) and inter-token latency degraded further. For a streaming UI the
metric a human feels is TTFT and then the inter-token gap; for a batch pipeline
it is tokens/s.

**Why:** More sequences share each decode step, so per-sequence speed falls
while aggregate speed rises. The two metrics are traded, not aligned.

**Boundary:** Report TTFT, inter-token latency and end-to-end separately, as
percentiles. A single "latency" number in a serving report is a decision someone
made without telling you.

**Tags:** `serving` `decision` `general-principle`

---

### 3. [misconception] p99 from a few hundred requests is a reliable number to alert on.

**Answer:** At n=120 the p99 is the two slowest samples. Its bootstrap 95%
interval in the lab was [5911, 6271] ms against a point estimate of 6134 -- and
that is the interval when the underlying distribution is stable, which it rarely
is.

**Why:** A tail percentile is an estimate from the few samples in the tail.
Sample count enters through the tail, not through the total.

**Boundary:** The fix is not "use the mean" -- the mean was worse than 92% of
requests in the same run. Report p50 with p95/p99, state n, and treat a tail
percentile from a short window as a trend, not a threshold.

**Tags:** `serving` `misconception` `general-principle`
