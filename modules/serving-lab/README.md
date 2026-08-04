# serving-lab

A shared fixture for six micro modules covering Layer 8 (inference and
serving). Not a module itself.

```powershell
cd modules\serving-lab
python roofline_lab.py    # ../memory-bandwidth-roofline.md
python memory_lab.py      # ../kv-cache-sizing.md
python quant_lab.py       # ../quantization.md
python latency_lab.py     # ../latency-percentiles.md   (~60 s, sleeps)
python batching_lab.py    # ../batching-and-scheduling.md
python bench_lab.py       # ../benchmark-methodology.md (~10 s, spawns load)
```

CPython 3.14, stdlib only. `quant_lab.py` and `bench_lab.py` reuse the Chinese
corpus, judgments and metrics from [../zh-retrieval-lab/](../zh-retrieval-lab/)
via a `sys.path` insert, so retrieval quality here is scored with the same
instrument as every Layer 6 module.

| File | Role |
|---|---|
| `hardware.py` | device specs, model shapes, the byte/FLOP arithmetic, measurement helpers |
| `roofline_lab.py` | measured copy bandwidth, then where every workload sits against the ridge |
| `memory_lab.py` | weights, KV cache and two allocators against a fixed budget |
| `quant_lab.py` | seven quantization schemes, scored on the Chinese retrieval set |
| `latency_lab.py` | real threads, real clock: TTFT, ITL, percentiles, coordinated omission |
| `batching_lab.py` | discrete-event scheduler comparison, throughput-latency curve |
| `bench_lab.py` | the harness itself: warmup, order, repetitions, and the joint metric |

## Three kinds of number, and only one of them is a measurement

This is the fixture with the widest gap between what it computes and what it
can prove, so each lab prints the kind alongside the value:

- **measured** -- came out of `perf_counter()` on the machine that ran it.
  Memory-copy bandwidth and its cache curve, sleep resolution, thread and
  process contention, quantization error, retrieval quality under quantization,
  every latency percentile in `latency_lab.py`.
- **declared** -- copied from a vendor specification sheet. Every GPU row in
  `hardware.DEVICES`. **No GPU was involved in producing this repository.**
- **derived** -- exact arithmetic over the first two. KV cache sizes, ridge
  points, decode ceilings, the step-time model underneath `batching_lab.py`.

The derived numbers are the ones worth carrying, because the arithmetic does
not care whose hardware it runs on. The danger is reading them as measurements:
a derived ceiling of 69 tok/s assumes perfect bandwidth utilization, and real
engines reach 60-80% of it.

`batching_lab.py` is a simulation. It cannot surprise you about hardware; what
it can do -- and what the map row asks for -- is produce the shape of the
throughput-latency curve from a step-time model that came out of
`roofline_lab.py` rather than out of a guess.

## Read in this order

Each module uses the previous one's result:

1. `memory-bandwidth-roofline` -- which resource you are actually spending
2. `kv-cache-sizing` -- what fits, and what the second-largest tensor costs
3. `quantization` -- the lever that moves bytes, and what it costs in quality
4. `latency-percentiles` -- how to measure any of it without lying
5. `batching-and-scheduling` -- the knob that trades the two metrics
6. `benchmark-methodology` -- reporting it so a second person can act on it

Reversing 4 and 5 is the standard mistake: a scheduler tuned against a
closed-loop harness is tuned against a client that refuses to queue.

## What this fixture cannot show

- Anything about a specific GPU kernel, a real engine's scheduler, or an actual
  model's quality under weight quantization.
- Numerical behaviour of fp16/bf16/fp8 arithmetic. The quantization lab
  round-trips through an integer grid in fp64 and measures the grid error, not
  the accumulation error.
- Contention effects on a GPU: SM occupancy, memory-controller queueing, NCCL.
  The bandwidth contention it does measure is a CPU's, and it transfers as an
  analogy, not as a number.

A module here is evidence of exposure, not of level. Levels move in
[../../capability-map.md](../../capability-map.md), and only on the five
conditions in the cycle's evidence contract.
