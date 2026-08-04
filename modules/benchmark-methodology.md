# Benchmark methodology

**Micro module.** One mechanism, one experiment, three cards. Runs against
[serving-lab/](serving-lab/).

**Capability:** Benchmark methodology (Layer 8, Aware -> Independent). Map
evidence: "A benchmark that reports task accuracy alongside tokens/sec."

---

## The problem

Every other module in this fixture produces numbers. This one is about whether
a number means anything: warmup, measurement order, repetitions, and the joint
metric that the systems report and the quality report never contain together.

## The mechanism

**Warmup is a hypothesis, not a ritual.**

```text
workload              iter 1    iter 2    iter 3    med 4-10   med 11-30  1 / steady
pure compute loop       6.06      5.90      6.19        5.80        5.91       1.02x
fresh 64 MB buffer     21.08     26.44     26.08       22.87       22.41       0.94x
    steady-state spread for the compute loop: min 5.76, max 7.03 ms (22% of median)
```

Neither workload shows a first-iteration penalty here. On CPython with no JIT,
and with an allocator handing back pages the process already faulted in,
"discard the first" removes nothing. The number that *does* matter is the
steady-state spread: 22% of the median, which is the smallest effect this
harness can resolve at all.

Warmup is real and large where there is state to warm -- a JIT, a GPU whose
clocks ramp, a kernel autotuner choosing an algorithm on first call, a cold page
cache, an empty KV cache, a connection pool. Every one of those applies to an
inference server and none applies here, which is exactly why the rule has to be
tested rather than recited.

**A blocked A/B measures the machine, not the code.**

A and B are the same 32 MB memcpy. Four competing processes start partway
through:

```text
layout                  A median    B median    B/A     verdict
A-block then B-block        3.99       12.85    3.22x   "B is slower"
interleaved A,B,A,B         9.22        8.52    0.92x   no difference
```

A 222% machine change, attributed entirely to the code. Interleaving does not
remove the noise -- both arms still slow down -- it removes the **confound**. It
costs nothing and it is the default nowhere.

Two side results from the same section, both worth more than the demonstration:

- The same load costs a bandwidth-bound workload 3.2x and a compute-bound one
  1.9x. Memory bandwidth is shared and cannot be scheduled away from; cores can.
  "It was fine on my machine" is usually true and rarely relevant.
- An earlier version of this section used four *threads* as the noise generator
  and measured no interference at all -- under the GIL they mostly wait, while
  completing 519 units of work. **A noise generator that does not compete for
  the resource under test proves nothing.**

**Repetitions decide whether a claim exists.** Arm B does 5% less work, by
construction:

```text
n per arm   A mean   B mean   diff    95% CI of diff       resolvable?
3             5.91     6.05   -0.14   [ -1.14,   0.55]     NO
5             6.05     5.94    0.12   [ -0.54,   0.70]     NO
10            6.21     5.99    0.23   [ -0.34,   0.86]     NO
25            6.10     5.87    0.23   [ -0.11,   0.55]     NO
50            6.09     5.78    0.30   [  0.11,   0.50]     yes
```

Bootstrap the *difference*, not each arm -- the question is about one quantity,
and two overlapping intervals do not answer it. The threshold moves with the
machine: on a quieter run the same effect resolved at n=5. Which is the point.
Report the interval; never the verdict alone. Same arithmetic as
[eval-set-sample-size.md](eval-set-sample-size.md), different units.

**The metric that decides has a task metric in the numerator.**

Quality measured on the Chinese retrieval set in
[quantization.md](quantization.md); scan throughput derived from this machine's
measured memory bandwidth, since an exhaustive index scan is bandwidth-bound.
10M vectors, one GPU-hour priced at $1.20:

```text
scheme              bytes/vec  index GB  queries/s  recall@5  successful q/s  $/1M ok
fp32 (baseline)         1028     10.28       1.16     0.500            0.58   575.77
int8 per-tensor          260      2.60       4.58     0.500            2.29   145.62
int4 per-vector          132      1.32       9.02     0.333            3.01   110.90
int4 per-channel         132      1.32       9.02     0.500            4.51    73.93
int4 group-32            160      1.60       7.44     0.500            3.72    89.61

best recall@5:                          fp32 (baseline)
best queries/s:                         int4 per-vector
lowest cost per 1M successful queries:  int4 per-channel
```

Three different winners on one table. The first two are the numbers each team
reports; the third is the only one that answers "which should we serve", and it
is 7.8x cheaper than the quality winner at identical measured recall.

The denominator is what people get wrong. Cost per *query* makes the fastest
wrong answer look best -- `int4 per-vector` is the throughput champion and gets
a third of the queries wrong. Cost per *successful* query is the Layer 5 row
"cost per successful task", arriving from Layer 8.

## What a serving benchmark has to state to be readable

```text
- the model, the exact weights, and the quantization
- the hardware and the achieved bandwidth, not the sticker bandwidth
- prompt and output length distributions -- means are not enough
- arrival process: closed loop with N clients, or open loop at R req/s
- warmup discarded, repetitions kept, and the order they ran in
- TTFT, ITL and end-to-end separately, as percentiles
- the task metric, on a named eval set with a version
- cost per successful task, with the denominator defined
```

A report missing the fourth line cannot be compared with any other report, and
it is the line missing most often. See
[latency-percentiles.md](latency-percentiles.md) for what it costs.

## The experiment

```powershell
cd modules\serving-lab
python bench_lab.py      # ~10 s; spawns 4 CPU/memory load processes and kills them
```

## Boundary

- **The A/B demonstration uses an artificial neighbour.** The size of the error
  depends on what the machine was doing, which is the point -- a blocked A/B has
  an error term set by something nobody is recording.
- **The joint metric's throughput model is a brute-force scan**, not an ANN
  index. An HNSW graph is latency-bound by random access rather than by
  sequential bandwidth, so the *ranking* of schemes by cost survives and the
  absolute queries/s does not.
- **A failed query is priced at zero here.** If a miss costs a retry, a human, or
  a wrong answer downstream, the denominator changes and so can the winner. That
  is a decision to state, not a default to inherit.
- **This module cannot make a bad eval set good.** Every number in the numerator
  comes from 6 queries and 17 documents. The methodology is the transferable
  part; the measurements are a fixture.

## Cards

### 1. [failure] Your benchmark says the new implementation is 20% faster. The change was a comment.

**Answer:** Check the measurement layout. A blocked A/B -- all of A, then all of
B -- varies time and configuration together, so any change in the machine lands
on the code. In the lab, the same 32 MB memcpy measured 3.99 ms then 12.85 ms
because four processes started competing for memory bandwidth in between.

**Why:** Confounding. Interleaving A,B,A,B gives both arms the same distribution
of machine states; it does not remove noise, it removes the confound.

**Boundary:** Interleaving cannot fix a monotone drift within a single
measurement (thermal throttling), and it cannot fix a harness whose noise
generator does not contend for the resource under test -- four Python threads
perturbed a compute benchmark by 1%, four processes by 86%.

**Tags:** `benchmarking` `failure` `general-principle`

---

### 2. [decision] Config A does 960 tok/s at 91% task accuracy. Config B does 1,600 tok/s at 84%. Which ships?

**Answer:** Compute cost per *successful* task -- the throughput divided by the
quality, priced. Neither the speed table nor the accuracy table answers it, and
they are usually produced by different people in different documents. In the
lab's version of this table the quality winner, the throughput winner and the
cost winner were three different configurations.

**Why:** Serving cost is per unit of work delivered, and a wrong answer is not
work delivered.

**Boundary:** The denominator has to be stated. If a failure costs a retry, the
cheap-and-wrong config gets worse; if failures are free and rare, it gets
better. Cost per successful task is the Layer 5 row, and it is the row that
decides model choice.

**Tags:** `benchmarking` `decision` `general-principle`

---

### 3. [misconception] Discard the first iteration, then report the mean of the rest.

**Answer:** Both halves are assumptions. On this machine neither a compute loop
nor a fresh 64 MB buffer showed a first-iteration penalty -- while the
steady-state spread was 22% of the median, which is the real limit on what can
be claimed. Warmup matters where there is state to warm: JIT, GPU clocks,
autotuners, page cache, KV cache, connection pools.

**Why:** "Warm up" is shorthand for "reach the steady state of a specific
system". Which state, and whether it exists, is a property of that system.

**Boundary:** Discard until the median stops moving, then report the residual
spread and an interval on the difference you care about. A 3% improvement
claimed on a harness with a 22% spread is not a small result -- it is an
unmeasured one.

**Tags:** `benchmarking` `misconception` `general-principle`
