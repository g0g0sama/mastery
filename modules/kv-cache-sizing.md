# Weights, runtime memory and KV cache sizing

**Micro module.** One mechanism, one experiment, three cards. Runs against
[serving-lab/](serving-lab/).

**Capability:** Weights, runtime memory, KV cache sizing (Layer 8, Aware ->
Working). Map evidence: "Predict RAM for a context length before loading."

---

## The problem

This is the one part of serving that can be computed instead of benchmarked,
and it is routinely discovered by an out-of-memory error at 03:00 instead. Four
predictions were written into `memory_lab.py` before it ran. Two were wrong,
and both in the direction that loses a production incident.

## The mechanism

**The capacity of a service is a division.**

```text
device memory         24.00 GB
weights fp16          13.48 GB
runtime overhead       1.50 GB   (CUDA context, allocator pools, workspaces)
left for KV            9.02 GB
KV per token           0.52 MB
=> tokens that fit    17,204
=> at 4096 context, 4.2 concurrent sequences
```

Four. Not four hundred. The formula for the middle line is worth memorizing
because every term in it is a config value you already have:

```text
KV bytes per token = 2 (K and V) x layers x kv_heads x head_dim x dtype_bytes
```

Note what is *absent*: batch and sequence length are multipliers applied later,
and `hidden_size` does not appear -- `kv_heads x head_dim` is what matters, and
in a GQA model that is much smaller than the hidden size.

**The KV cache overtakes the weights inside a single busy batch.**

```text
model         scheme    weights    KV/token  crossover tokens  = seqs @4k
Llama-2-7B    MHA       13.48 GB   0.52 MB          25,711          6.3
Llama-2-13B   MHA       26.00 GB   0.82 MB          31,738          7.7
Llama-3-8B    GQA 4:1   16.06 GB   0.13 MB         122,528         29.9
Llama-2-70B   GQA 8:1  138.00 GB   0.33 MB         421,143        102.8
7B            MQA       0.02 MB/t                  822,754        200.9
```

Six concurrent 4k sequences and the cache is larger than the model. This is the
whole argument for grouped-query attention, stated in bytes rather than in
quality: one line of the config buys 4-8x the concurrency at the same context
length. It is also why context-length announcements are capacity announcements
-- 128k context on an MHA model is 64 GB of cache for *one* user.

**Reserve-max allocation is not a 20% problem.**

Traffic with an advertised `max_len` of 4096 and a real mean length of 713
tokens, 6.44 GB of KV budget:

```text
allocator       reserved/req  concurrent  useful tokens   waste
reserve-max     4,096         11          6,430           85.7%
paged, 16-token grows         155         47,516           2.4%
```

**14x the concurrency**, on identical hardware and identical traffic. The
prediction said 20-30% waste, "annoying, not decisive". The gap is not an
implementation quality difference: reserving the maximum is the only way to
guarantee a sequence is never preempted mid-generation, and paging is what you
buy when you give that guarantee up. Internal fragmentation of the paged scheme
-- the thing that sounds expensive -- is 2.4%, at most 15 tokens per sequence.

Two operational consequences that follow directly:

- **Paged allocation requires a preemption policy**, because it admits requests
  it cannot finish. Recompute (throw away the cache, prefill again) costs ~167
  ms of compute for a 2048-token sequence on a 4090; swapping it to host memory
  costs ~11 ms of PCIe time but competes with everything else on the bus. A
  config that never preempts is one that admitted too few.
- **A KV cache is quantized activations, not weights.** Halving the KV dtype
  doubles capacity exactly -- and lands precisely where the outlier problem
  measured in [quantization.md](quantization.md) lives.

## The experiment

```powershell
cd modules\serving-lab
python memory_lab.py
```

All arithmetic, no timing; it returns instantly. Section 4's length
distribution is authored and seeded, so the 85.7% is fixture-specific and the
*direction* is not: any long-tailed length distribution produces a large number
there, and every real traffic log is long-tailed.

## Boundary

- **Activation memory is ignored.** At large batch the transient activations of
  a forward pass are not nothing, and a framework's allocator pools hold onto
  freed blocks. The 1.5 GB overhead line is a plausible constant, not a
  measurement.
- **The model shapes are real; the device memory figures are declared.**
- **Fragmentation here is internal only.** External fragmentation -- free blocks
  that exist but are not contiguous -- is a real failure mode of naive
  allocators and is exactly what fixed-size paging eliminates.
- **Prefix sharing changes the arithmetic.** Multiple sequences with a common
  system prompt can share those blocks; the lab does not model it, and it is the
  single largest saving available for a chat workload with a long system prompt.

## Cards

### 1. [decision] You are asked to raise the advertised context window from 8k to 32k on the same hardware. What happens to capacity?

**Answer:** Concurrency falls by 4x if the allocator reserves the maximum, and
by however much traffic actually uses if it pages. Compute the KV bytes per
token (`2 x layers x kv_heads x head_dim x dtype`) and divide the free memory by
it -- the answer is a division, available before any change is deployed.

**Why:** For a 7B MHA model, KV is 0.52 MB per token. A 24 GB card has ~9 GB
free after weights: 17,204 tokens total, which is four 4k sequences or one 16k
sequence.

**Boundary:** With GQA the same change is far cheaper (0.13 MB/token for
Llama-3-8B). The question "can we support 32k" has a different answer per model
family, and the config file answers it.

**Tags:** `serving` `decision` `general-principle`

---

### 2. [misconception] Paged attention's win is that it avoids memory fragmentation.

**Answer:** Its win is that it stops reserving the *advertised maximum length*
for every request. In the lab, reserve-max wasted 85.7% of the cache and
supported 11 concurrent sequences; 16-token paging wasted 2.4% and supported
155. Internal fragmentation -- the thing named "fragmentation" -- was the small
term all along.

**Why:** Requests are long-tailed. Reserving the max for a mean of 713 tokens
means paying 4096 for every one of them.

**Boundary:** The saving is bought with a guarantee: a paged engine admits
sequences it may have to preempt, so it needs a recompute-or-swap policy and a
scheduler that can make that decision. Prefix sharing across sequences is a
second, separate win that the same block structure enables.

**Tags:** `serving` `misconception` `general-principle`

---

### 3. [failure] The service ran fine for weeks, then started OOM-ing during a normal-looking afternoon.

**Answer:** Look for the KV cache crossing the weights. The weights are a fixed
cost; the cache grows with concurrent tokens in flight, and for a 7B MHA model
it exceeds the 13.5 GB of weights at about 25,700 tokens -- six concurrent 4k
sequences. Nothing announces that boundary, and average load charts do not show
it because it is about simultaneity, not volume.

**Why:** KV bytes = per-token constant x seq x batch. The only variable in
production is the product on the right.

**Boundary:** A paged allocator turns this from an OOM into a queue -- requests
wait or get preempted instead of the process dying -- which is better and also
hides the same signal. Alert on cache occupancy and preemption count, not on
process memory.

**Tags:** `serving` `failure` `general-principle`
