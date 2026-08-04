# CPU vs GPU and memory bandwidth

**Micro module.** One mechanism, one experiment, three cards. Runs against
[serving-lab/](serving-lab/).

**Capability:** CPU vs GPU, memory bandwidth (Layer 8, Aware -> Working). Map
evidence: "Predict which of your workloads is bandwidth-bound."

---

## The problem

The map row asks for a prediction, so `roofline_lab.py` holds four predictions
as data and scores them. Three were wrong and the fourth was half right. They
were not careless guesses; they are the standard mental model, which is the
useful thing about them.

## The mechanism

**One number describes an accelerator: FLOP per byte.**

```text
device                          GB/s      TFLOP/s     FLOP/byte
CPU, DDR5-5600 dual channel       90          2           17
RTX 4090                        1008        165          164
A100 80GB SXM                   2039        312          153
H100 SXM5                       3350        990          296
M3 Max, 128GB unified            400         28           70
```

That last column is the *ridge point*: the arithmetic intensity below which the
device cannot use its own FLOPs. Read it as "how many tokens must be in flight
together before the accelerator is computing rather than waiting".

The H100's ridge is *higher* than the 4090's. Its compute grew faster than its
bandwidth, so the newer, more expensive device needs a **larger** batch to be
efficient. Buying a faster accelerator for a low-batch workload buys idle
silicon.

**Decode at batch 1 is not close.**

```text
batch   weights GB  KV GB    FLOP/step   intensity   bound by
1          13.48     1.07       13 GF        0.9      memory
16         13.48    17.18      216 GF        7.0      memory
512        13.48   549.76    6,902 GF       12.3      memory
```

Intensity 0.9 against a ridge of 164: the 4090 spends 99.5% of a single-stream
decode step waiting for weights. This is why a 7B model runs at a similar speed
on cards with wildly different FLOPs, and why the ceiling is a division:

```text
tokens/s <= bandwidth / bytes per step
7B fp16 on a 4090:  1008e9 / 14.55e9 = 69 tok/s
```

Measured 7B fp16 numbers on that card land in the 60s. The arithmetic is not an
approximation of the benchmark; it is what the benchmark is measuring.

**The result that changed the module: intensity converges, it does not grow.**

Batching amortizes the weights over more tokens, so intensity should rise with
batch until it crosses the ridge. It does not, because each sequence reads its
own KV cache, and that traffic scales with the batch that was supposed to
amortize:

```text
intensity -> 2 x params / KV-bytes-per-sequence
```

```text
model         scheme    KV/token   seq    plateau  ridge 4090  reachable?
Llama-2-7B    MHA       0.52 MB     512      50.2      164     NO -- never
Llama-2-7B    MHA       0.52 MB    2048      12.6      164     NO -- never
Llama-3-8B    GQA 4:1   0.13 MB     512     239.3      164     yes
Llama-3-8B    GQA 4:1   0.13 MB    2048      59.8      164     NO -- never
7B            MQA       0.02 MB    2048     401.7      164     yes
```

At 2048 tokens of context with multi-head attention, **no batch size on a 4090
makes decode compute-bound**. The FLOPs are unreachable and the only remaining
lever is moving fewer bytes. That single table explains GQA, MQA, KV-cache
quantization, and FlashAttention's obsession with not materializing anything --
they are all the same move.

**Prefill and decode are two different machines.**

```text
phase                   bytes     FLOP      mem ms   compute ms   bound by
decode, 1 token        14.55 GB   0.01 TF    14.44       0.08     memory
prefill, 128 tokens    14.55 GB   1.73 TF    14.44      10.46     memory
prefill, 2048 tokens   14.55 GB  27.61 TF    14.44     167.32     compute
```

Same weights, same device, opposite bottleneck, crossover around 130 tokens.
So:

```text
dtype     decode tok/s    prefill 2048 ms
fp16            69             167.3
int8           129             167.3
int4           227             167.3
```

Quantizing weights to int4 is worth 3.3x on decode and **exactly nothing** on
prefill. Half the disagreements about whether quantization "helps" are two
people measuring different phases.

## The measured part

The lab measures memcpy bandwidth on the machine it runs on, at seven
working-set sizes:

```text
working set     GB/s median   GB/s min-max
4 KB                  41.3      41.3 -  41.7
64 KB                 72.5      70.9 -  73.3
512 KB                60.7      58.7 -  61.9
4 MB                  46.8      41.4 -  51.5
16 MB                 25.1      23.8 -  26.0
256 MB                18.2      16.4 -  20.9
```

Two things worth having. The cache hierarchy is visible as a 4x fall from L2 to
DRAM. And a single thread achieves **20% of the theoretical 89.6 GB/s** -- which
is why "memory-bandwidth-bound" is a statement about a device, not a core: one
stream cannot keep enough requests in flight to saturate the controller. The
same fact on a GPU is spelled "one warp cannot saturate HBM"; it is why kernels
are written to have thousands of threads in flight rather than the fastest
possible single thread.

## The experiment

```powershell
cd modules\serving-lab
python roofline_lab.py
```

Read `PREDICTIONS` at the top and commit to each before running.

## Boundary

- **The GPU numbers are declared, not measured.** No GPU was involved. The
  arithmetic transfers; the constants come from specification sheets and real
  achieved bandwidth is 60-80% of them.
- **Attention FLOPs are ignored** in the intensity calculation -- only the
  2 FLOP/parameter term is counted. At long context the attention term grows and
  the picture shifts further toward memory, so the conclusion is conservative.
- **This says nothing about quality.** int4 moves 4x fewer bytes; whether the
  model is still worth serving is [quantization.md](quantization.md).
- **The ridge point assumes the kernel can reach peak.** A kernel with poor
  occupancy is below both roofs and neither number explains it. The roofline
  bounds what is possible; a profiler explains what happened.

## Cards

### 1. [decision] Your 7B model decodes at 60 tok/s on a 4090. Would an H100 -- 6x the FLOPs -- make it 6x faster?

**Answer:** No. Decode at low batch is bandwidth-bound, so the speedup is the
bandwidth ratio (3350/1008 = 3.3x), not the FLOP ratio. And the H100's ridge
point is *higher* (296 vs 164 FLOP/byte), so it needs a larger batch than the
4090 before any of that compute is reachable.

**Why:** tokens/s <= bandwidth / bytes-per-step. At batch 1 with a 7B fp16
model the step moves ~14.5 GB and does ~13 GFLOP: intensity 0.9 against a ridge
of 164.

**Boundary:** Prefill is the opposite -- compute-bound past ~130 tokens -- so a
prompt-heavy workload does benefit from the FLOPs. Name the phase before
answering.

**Tags:** `serving` `decision` `general-principle`

---

### 2. [misconception] Batching amortizes the weight load, so a large enough batch always makes decode compute-bound.

**Answer:** No. Arithmetic intensity converges to `2 x params / KV-bytes-per-
sequence`, because each sequence reads its own KV cache. For a 7B MHA model at
2048 tokens of context that limit is 12.6 FLOP/byte, against a 4090 ridge of
164 -- unreachable at any batch size.

**Why:** Weights are read once per step for the whole batch; the KV cache is
read once per sequence. The term that grows with batch is the one that does not
amortize.

**Boundary:** The plateau is a function of the attention scheme and the context
length. Llama-3-8B (GQA 4:1) crosses the ridge at 512 tokens of context and not
at 2048. MQA crosses at both. That is the design pressure that produced GQA.

**Tags:** `serving` `misconception` `general-principle`

---

### 3. [failure] Quantizing a model to int4 made generation 3x faster but the batch job that summarizes long documents did not speed up at all.

**Answer:** Expected. Quantization moves fewer bytes; it does not do fewer
FLOPs. Decode is bandwidth-bound and gets the full 3-4x. Prefill past ~130
tokens is compute-bound and gets nothing -- in the lab, 167 ms for a 2048-token
prefill at fp16, int8 and int4 alike.

**Why:** Prefill does 2 x params x tokens FLOP against one weight read, so its
intensity is the token count. A long-prompt job is a prefill job wearing a
generation costume.

**Boundary:** int4 kernels that dequantize to fp16 before the matmul can be
*slower* on prefill than fp16 was. And the reverse trap: measuring a
quantization win on a decode benchmark and promising it to a summarization
workload.

**Tags:** `serving` `failure` `general-principle`
