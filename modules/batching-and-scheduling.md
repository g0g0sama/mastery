# Batching and request scheduling

**Micro module.** One mechanism, one experiment, three cards. Runs against
[serving-lab/](serving-lab/).

**Capability:** Batching and request scheduling (Layer 8, - -> Working). Map
evidence: "Throughput vs latency curve for your local setup."

---

## The problem

`batching_lab.py` is a discrete-event simulation, and it says so at the top. It
cannot surprise anyone about hardware. What it can do -- and what the map row
asks for -- is produce the *shape* of the curve from a step-time model that came
out of [memory-bandwidth-roofline.md](memory-bandwidth-roofline.md) rather than
out of a guess: every decode step costs `max(bytes/bandwidth, FLOP/compute)` at
the current batch size, on Llama-3-8B at 70% of a 4090's peak bandwidth.

## The mechanism

**Four schedulers, one arrival trace** (300 requests, Poisson at 4/s, lognormal
lengths, median 67 output tokens with a max of 960):

```text
policy                  req/s  tok/s  TTFT p50  TTFT p95  ITL p50  ITL p99  e2e p95  util
no batching              0.42     42    315467    590178     22.9     23.2   592.16  100%
static, batch 32         1.94    193     37275     67319     27.2     31.2    77.21   89%
continuous, batch 32     3.53    352        91       285     24.4    191.9     9.19   36%
continuous + chunked     3.53    352       139       417     24.4    132.0     9.20   37%
```

(TTFT and ITL in ms, e2e in seconds.)

Static to continuous is **1.8x throughput and a 400x improvement in TTFT p50**,
and the utilization column is the tell: static batching shows *higher*
utilization while doing less work, because a slot occupied by a sequence that
finished 200 steps ago still counts as occupied.

**Where the static batch goes.** The waste is `1 - mean/max` within a batch, and
it is a property of the length distribution alone:

```text
batch composition   mean len   max len   padding waste
sorted by length        65.5        73          10.2%
as they arrive          91.4       243          62.4%
```

Length-sorted batching is the classic fix and it needs the output length in
advance, which nobody has. Continuous batching does not need it. That -- not the
batching -- is the actual innovation.

**The curve has a knee, and past it a bigger cap is a pure loss.**

```text
max batch  req/s  TTFT p50  ITL p99  e2e p95   util
1           0.42    315467     23.2   592.16   100%
4           1.51     44486     99.5    85.57    99%
8           2.56      2544    148.9    11.62    93%
16          3.51        84    177.3     8.97    50%
32          3.53        84    191.9     9.19    25%
128         3.53        84    191.9     9.19     6%
```

Past 16 the cap stops binding -- concurrency is set by the arrival rate and the
engine's own speed -- so throughput is flat. But ITL p99 keeps rising (177 ->
192 ms), because on the steps where the queue happens to be deep, more sequences
share the step. The peak-throughput setting is not the answer; two defensible
rules are *the smallest cap that reaches peak throughput* and *the largest cap
that still meets the SLO*, and they move with the arrival rate:

```text
arrivals 8/s:  max batch 8 -> 2.64 req/s, TTFT p50 34.2 s
               max batch 32 -> 5.43 req/s, TTFT p50 1.5 s
               max batch 128 -> 5.57 req/s, TTFT p50 0.15 s, ITL p99 350 ms
```

Under overload the same three settings that were indistinguishable at 4/s
separate by 2x in throughput and 200x in TTFT. A batch cap tuned at low load is
untuned.

**Prefill priority vs chunked prefill.** A prefill is compute-bound and long; a
decode step is bandwidth-bound and short. Running prefills at highest priority
stalls every sequence that is already generating:

```text
policy                 TTFT p50   ITL p99
prefill-priority             91     191.9
chunked, 512 tokens         139     132.0
```

Chunking does not make prefill cheaper -- the prefill share of engine time is
essentially unchanged. It makes the stall shorter and more frequent, moving cost
from the sequences that are already streaming to the one that just arrived. Both
of those are called "latency", and an SLO that does not name which one cannot
adjudicate this trade.

## The experiment

```powershell
cd modules\serving-lab
python batching_lab.py     # under 2 seconds; it is a simulation
```

## Boundary

- **Simulation.** The arrival process and length distribution are authored; the
  step-time model is derived from the roofline arithmetic and an assumed 70% of
  peak bandwidth. Directions transfer, magnitudes do not.
- **No memory limit is modelled.** A real engine's max batch is bounded by KV
  cache, not by a config value -- see [kv-cache-sizing.md](kv-cache-sizing.md) --
  and admitting past that point causes preemption, which this lab does not
  simulate.
- **No scheduling policy beyond FIFO.** Priority classes, fair queueing between
  tenants, and shortest-job-first (which needs a length prediction) all change
  the picture and none are here.
- **Speculative decoding, prefix caching and disaggregated prefill/decode**
  serving are the three things a 2026 engine does that this model has no term
  for. Each of them attacks exactly the bottleneck the roofline module names.

## Cards

### 1. [misconception] Continuous batching is a modest optimization over static batching -- maybe 20-30%.

**Answer:** In the lab it was 1.8x throughput and 400x better TTFT p50 on the
same trace. Static batching holds a slot for a sequence that has already
finished until the *longest* sequence in the batch is done; with arrival-order
batches the waste was 62% of slot-steps.

**Why:** Waste is `1 - mean/max` over the batch's output lengths, and output
lengths are long-tailed. The one fix that does not require knowing the length in
advance is refilling slots per step.

**Boundary:** Utilization can look better under static batching -- a padded slot
counts as busy. Measure completed work, not occupancy.

**Tags:** `serving` `misconception` `general-principle`

---

### 2. [decision] Your engine's max batch size is a config value. How do you choose it?

**Answer:** Not by maximizing throughput. Sweep it, and pick either the smallest
cap that reaches peak throughput or the largest that meets the latency SLO --
then re-check at the arrival rate you actually expect at peak, because the
answer moves. In the lab, caps of 8, 32 and 128 were indistinguishable at 4
req/s and differed by 2x throughput and 200x TTFT at 8 req/s.

**Why:** Past the knee the cap stops binding at low load, so it looks free while
still raising ITL p99. Under overload it is the whole difference between a queue
and a collapse.

**Boundary:** In a real engine the cap that matters is KV cache capacity, and
setting the batch cap above what memory supports means preemption instead of
queueing.

**Tags:** `serving` `decision` `general-principle`

---

### 3. [failure] After enabling chunked prefill, time-to-first-token got worse and the team wants to revert.

**Answer:** Expected, and the question is which metric the SLO names. In the lab
chunked prefill moved TTFT p50 from 91 to 139 ms while improving inter-token
latency p99 from 192 to 132 ms. It does not make prefill cheaper; it splits the
stall so streaming sequences are not frozen for the length of someone else's
prompt.

**Why:** Prefill is compute-bound and long, decode steps are bandwidth-bound and
short. Interleaving them trades the arriving request's first token against
everyone else's smoothness.

**Boundary:** With long prompts and few concurrent streams, prefill-priority is
the better default. With many streams and a human watching each one, chunking
is. Neither is a global answer, and both are "latency".

**Tags:** `serving` `failure` `general-principle`
