"""Weights, runtime memory, KV cache sizing: predict RAM before loading.

Map row (Layer 8): "Predict RAM for a context length before loading."

All arithmetic, no timing. Exact given the published model shapes in
hardware.py -- which is the point: this is the one thing in serving that can be
computed rather than benchmarked, and it is routinely discovered by an
out-of-memory error at 03:00 instead.

Section 4 is a simulation with a seeded length distribution. The distribution
is authored; the allocator behaviour is not.

Commit to the predictions before running.
"""
from __future__ import annotations

import math
import random

import hardware as hw

PREDICTIONS = {
    "A": "For a 7B fp16 model on a 24 GB card, the KV cache is a minor term: "
         "weights dominate at any context length worth serving.",
    "B": "Halving the KV cache dtype from fp16 to fp8 roughly doubles the "
         "number of tokens that fit.",
    "C": "Reserving each request's maximum length up front wastes maybe 20-30% "
         "of the cache -- annoying, not decisive.",
    "D": "Paged allocation with a 16-token block has negligible internal "
         "fragmentation.",
}

MAX_LEN = 4096          # what the API advertises
BLOCK = 16              # tokens per page, the vLLM default


def section_1_budget():
    hw.rule("1. Where a 24 GB card goes, 7B fp16")
    model, dev = hw.MODELS["7B-mha"], hw.DEVICES["rtx-4090"]
    w = hw.weight_bytes(model)
    # Framework overhead is real and nobody budgets for it: CUDA context,
    # allocator pools, cuBLAS workspaces, the tokenizer, the Python process.
    overhead = 1.5e9
    per_token = hw.kv_bytes_per_token(model)
    free = dev.memory - w - overhead
    print(f"device memory      {hw.gb(dev.memory)}")
    print(f"weights fp16       {hw.gb(w)}")
    print(f"runtime overhead   {hw.gb(overhead)}   (CUDA context, pools, workspaces)")
    print(f"left for KV        {hw.gb(free)}")
    print(f"KV per token       {hw.mb(per_token)}")
    print(f"=> tokens that fit {free / per_token:,.0f}")
    print(f"=> at 4096 context, {free / per_token / 4096:.1f} concurrent sequences")
    print("\nThat last line is the capacity of the service. It is a division, and")
    print("it is knowable before the model is downloaded.")


def section_2_crossover(facts):
    hw.rule("2. When the KV cache overtakes the weights")
    print("tokens in flight (batch x seq) at which KV bytes = weight bytes\n")
    hw.row("model", "scheme", "weights", "KV/token", "crossover tokens",
           "= seqs @4k", widths=[22, 10, 12, 12, 18, 12])
    m0 = hw.MODELS["7B-mha"]
    facts["cross_7b"] = hw.weight_bytes(m0) / hw.kv_bytes_per_token(m0)
    for key in ("7B-mha", "13B-mha", "8B-gqa", "70B-gqa", "7B-mqa"):
        m = hw.MODELS[key]
        w = hw.weight_bytes(m)
        per = hw.kv_bytes_per_token(m)
        cross = w / per
        hw.row(m.name.split(" (")[0], m.attention_scheme, hw.gb(w).strip(),
               hw.mb(per).strip(), f"{cross:,.0f}", f"{cross / 4096:8.1f}",
               widths=[22, 10, 12, 12, 18, 12])
    print("\nThe MHA rows cross inside a single busy batch. This is the whole")
    print("argument for GQA, stated in bytes rather than in quality: one line of")
    print("the config file buys 4-8x the concurrency at the same context.")


def section_3_kv_dtype():
    hw.rule("3. KV cache dtype, and what it actually buys")
    model, dev = hw.MODELS["8B-gqa"], hw.DEVICES["a100-80"]
    w = hw.weight_bytes(model)
    free = dev.memory - w - 2e9
    print(f"{model.name} on {dev.name}, {hw.gb(free)} free for KV\n")
    hw.row("KV dtype", "bytes/token", "tokens", "seqs @8k", "seqs @32k",
           widths=[12, 14, 14, 12, 12])
    for dtype in ("fp16", "fp8", "int4"):
        per = hw.kv_bytes_per_token(model, dtype)
        toks = free / per
        hw.row(dtype, f"{per:,.0f}", f"{toks:,.0f}", f"{toks / 8192:8.1f}",
               f"{toks / 32768:8.1f}", widths=[12, 14, 14, 12, 12])
    print("\nLinear, and that is the trap: capacity is linear in KV precision but")
    print("quality is not. A KV cache is quantized activations, not weights --")
    print("and the outlier structure that makes activation quantization hard")
    print("(../quantization.md, section 3) is exactly what lives here.")


def _lengths(n: int, seed: int = 5) -> list[tuple[int, int]]:
    """(prompt, output) pairs. Authored distribution, seeded.

    Long-tailed on purpose: most requests are short, a few are near the cap.
    That shape is what makes reserve-max allocation expensive, and it is the
    shape every real traffic log has.
    """
    rng = random.Random(seed)
    out = []
    for _ in range(n):
        prompt = min(MAX_LEN - 64, int(rng.lognormvariate(6.0, 0.8)))
        gen = min(MAX_LEN - prompt, max(8, int(rng.lognormvariate(4.4, 1.1))))
        out.append((prompt, gen))
    return out


def section_4_allocator(facts):
    hw.rule("4. Two allocators, same traffic")
    model, dev = hw.MODELS["8B-gqa"], hw.DEVICES["rtx-4090"]
    per = hw.kv_bytes_per_token(model)
    budget = dev.memory - hw.weight_bytes(model) - 1.5e9
    capacity = int(budget / per)
    reqs = _lengths(400)
    used = [p + g for p, g in reqs]
    print(f"{model.name} on {dev.name}: {hw.gb(budget)} of KV = "
          f"{capacity:,} tokens")
    print(f"400 requests, advertised max_len={MAX_LEN}, "
          f"mean actual length {sum(used) / len(used):,.0f}, "
          f"p95 {hw.percentiles(used, (95,))['p95']:,}\n")

    # Reserve-max: the allocator every framework starts with, because it is the
    # only one where a sequence can never fail mid-generation.
    concurrent_reserve = capacity // MAX_LEN
    # Paged: allocate in blocks as the sequence grows.
    blocks = [math.ceil(u / BLOCK) * BLOCK for u in used]
    concurrent_paged = 0
    running = 0
    for b in sorted(blocks):
        if running + b > capacity:
            break
        running += b
        concurrent_paged += 1

    hw.row("allocator", "reserved/req", "concurrent", "useful tokens", "waste",
           widths=[16, 16, 14, 16, 10])
    r_useful = sum(used[:concurrent_reserve])
    r_res = concurrent_reserve * MAX_LEN
    hw.row("reserve-max", f"{MAX_LEN:,}", concurrent_reserve, f"{r_useful:,}",
           f"{1 - r_useful / r_res:6.1%}", widths=[16, 16, 14, 16, 10])
    p_useful = sum(sorted(used)[:concurrent_paged])
    p_res = sum(sorted(blocks)[:concurrent_paged])
    hw.row(f"paged, {BLOCK}-token", "grows", concurrent_paged, f"{p_useful:,}",
           f"{1 - p_useful / p_res:6.1%}", widths=[16, 16, 14, 16, 10])
    facts["waste_reserve"] = 1 - r_useful / r_res
    facts["waste_paged"] = 1 - p_useful / p_res
    facts["ratio"] = concurrent_paged / concurrent_reserve
    print(f"\nconcurrency ratio: {concurrent_paged / concurrent_reserve:.1f}x")
    print("Internal fragmentation of the paged scheme is the last column:")
    print(f"at most {BLOCK - 1} tokens per sequence, "
          f"{(BLOCK - 1) / (sum(used) / len(used)):.1%} of the mean length.")
    print("\nThe reserve-max number is not a bad implementation. It is the cost")
    print("of the guarantee that no sequence is ever preempted -- and the reason")
    print("paged attention needs a preemption policy to exist at all.")


def section_5_preemption():
    hw.rule("5. What paging costs when the guess is wrong")
    print("Paged allocation admits requests it cannot finish. When the cache")
    print("fills, someone is preempted -- and the two policies differ in what")
    print("they throw away.\n")
    model = hw.MODELS["8B-gqa"]
    per = hw.kv_bytes_per_token(model)
    seq = 2048
    per_seq = per * seq
    pcie = 25e9      # declared: PCIe 4.0 x16, ~25 GB/s effective
    print(f"one preempted 2048-token sequence = {hw.mb(per_seq).strip()} of KV")
    hw.row("policy", "cost", "when it wins", widths=[16, 22, 40])
    hw.row("recompute", f"{seq} tokens prefill", "prefill is cheap, PCIe is busy",
           widths=[16, 22, 40])
    hw.row("swap to host", f"{per_seq / pcie * 1000:.0f} ms over PCIe",
           "context is long, GPU is saturated", widths=[16, 22, 40])
    print(f"\nRecompute at 2048 tokens costs ~167 ms of compute on a 4090")
    print(f"(roofline_lab.py section 5); the swap costs {per_seq / pcie * 1000:.0f} ms of bus time")
    print("but competes with nothing else that wants the bus. Neither is free,")
    print("and a config that never preempts is one that admitted too few.")


def score(facts):
    hw.rule("6. The predictions")
    verdicts = {
        "A": ("WRONG", f"KV overtakes the 7B MHA weights at "
              f"{facts['cross_7b']:,.0f} tokens -- six concurrent 4k sequences, "
              f"i.e. a quiet afternoon"),
        "B": ("RIGHT", "exactly 2x, and the caveat is quality: a KV cache is "
              "activations, where the outliers live"),
        "C": ("WRONG", f"{facts['waste_reserve']:.1%} wasted on this length "
              f"distribution, and the concurrency ratio is {facts['ratio']:.1f}x "
              f"-- decisive, not annoying"),
        "D": ("RIGHT", f"{facts['waste_paged']:.1%} at a 16-token block, against "
              f"{facts['waste_reserve']:.0%} for reserve-max. Internal "
              f"fragmentation was never the expensive kind"),
    }
    for key, text in PREDICTIONS.items():
        verdict, why = verdicts[key]
        print(f"{key}. {verdict}\n   claim: {text}\n   why:   {why}\n")


if __name__ == "__main__":
    facts = {}
    section_1_budget()
    print()
    section_2_crossover(facts)
    print()
    section_3_kv_dtype()
    print()
    section_4_allocator(facts)
    print()
    section_5_preemption()
    print()
    score(facts)
