"""Shared fixture for the Layer 8 modules: inference and serving.

    import hardware as hw
    hw.copy_bandwidth(64 << 20)      # measured, on this machine, GB/s
    hw.kv_bytes(hw.MODELS["7B"], seq=32_768, batch=1)

Three kinds of number appear in this lab and they are not equally trustworthy.
Every lab prints the kind alongside the value, and the modules repeat it:

- **measured** -- came out of `time.perf_counter()` on the machine that ran the
  script. Memory-copy bandwidth, sleep resolution, quantization error, scheduler
  simulation timings.
- **declared** -- copied from a vendor specification sheet. Every GPU number in
  `DEVICES` is declared. No GPU was involved in producing this repository.
- **derived** -- exact arithmetic over the two above. KV cache sizes, roofline
  ridge points, decode ceilings. These are the ones worth carrying, because the
  arithmetic does not care whose hardware it runs on.

The dangerous category is the third one *read as if it were the first*. A
derived decode ceiling of 74 tok/s is an upper bound assuming perfect bandwidth
utilization; real engines reach 60-80% of it. The module says so where it
matters.
"""
from __future__ import annotations

import math
import statistics
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")


# --------------------------------------------------------------------------- #
# Declared hardware. Vendor specification sheets, dense (non-sparse) figures.
# --------------------------------------------------------------------------- #

class Device:
    def __init__(self, name, bandwidth_gbs, tflops_fp16, memory_gb):
        self.name = name
        self.bandwidth = bandwidth_gbs * 1e9      # bytes/s
        self.flops = tflops_fp16 * 1e12           # FLOP/s
        self.memory = memory_gb * 1e9

    @property
    def balance(self) -> float:
        """FLOP per byte the device can sustain -- its ridge point.

        The single most useful number about an accelerator, and the one that
        never appears in the marketing comparison. A kernel below this ratio is
        bandwidth-bound and cannot use the FLOPs at all.
        """
        return self.flops / self.bandwidth


DEVICES = {
    # DDR5-5600, two channels: 5600 MT/s * 8 B * 2 = 89.6 GB/s theoretical.
    # A desktop CPU's fp16 throughput via AVX-512 is generous here.
    "cpu-ddr5":  Device("CPU, DDR5-5600 dual channel", 89.6, 1.5, 64),
    "rtx-4090":  Device("RTX 4090", 1008, 165, 24),
    "a100-80":   Device("A100 80GB SXM", 2039, 312, 80),
    "h100-sxm":  Device("H100 SXM5", 3350, 990, 80),
    "mac-m3max": Device("M3 Max, 128GB unified", 400, 28, 128),
}


# --------------------------------------------------------------------------- #
# Model shapes. Real published configurations, because the arithmetic is only
# interesting if the shapes are the ones actually deployed.
# --------------------------------------------------------------------------- #

class Model:
    def __init__(self, name, params, layers, hidden, heads, kv_heads, head_dim,
                 ffn, vocab=32_000):
        self.name = name
        self.params = params
        self.layers = layers
        self.hidden = hidden
        self.heads = heads
        self.kv_heads = kv_heads      # < heads means GQA; == 1 means MQA
        self.head_dim = head_dim
        self.ffn = ffn
        self.vocab = vocab

    @property
    def attention_scheme(self) -> str:
        if self.kv_heads == self.heads:
            return "MHA"
        return "MQA" if self.kv_heads == 1 else f"GQA {self.heads // self.kv_heads}:1"


MODELS = {
    # Llama-2 7B: multi-head attention, the shape that makes the KV cache hurt.
    "7B-mha":  Model("Llama-2-7B (MHA)", 6.74e9, 32, 4096, 32, 32, 128, 11008),
    # Llama-3 8B: same size class, 8 KV heads. One config line, 4x the context.
    "8B-gqa":  Model("Llama-3-8B (GQA)", 8.03e9, 32, 4096, 32, 8, 128, 14336, 128_256),
    "13B-mha": Model("Llama-2-13B (MHA)", 13.0e9, 40, 5120, 40, 40, 128, 13824),
    "70B-gqa": Model("Llama-2-70B (GQA)", 69.0e9, 80, 8192, 64, 8, 128, 28672),
    # A hypothetical MQA variant of 7B, to price the third point on the curve.
    "7B-mqa":  Model("7B (MQA, hypothetical)", 6.74e9, 32, 4096, 32, 1, 128, 11008),
}

DTYPES = {"fp32": 4, "fp16": 2, "fp8": 1, "int8": 1, "int4": 0.5}


# --------------------------------------------------------------------------- #
# Derived arithmetic. Exact, given the shapes above.
# --------------------------------------------------------------------------- #

def weight_bytes(model: Model, dtype: str = "fp16") -> float:
    return model.params * DTYPES[dtype]


def kv_bytes_per_token(model: Model, dtype: str = "fp16") -> float:
    """2 (K and V) * layers * kv_heads * head_dim * dtype.

    No batch, no sequence -- this is the per-token constant, and it is the
    number to memorize for a model you serve. Multiply by tokens in flight.
    """
    return 2 * model.layers * model.kv_heads * model.head_dim * DTYPES[dtype]


def kv_bytes(model: Model, seq: int, batch: int = 1, dtype: str = "fp16") -> float:
    return kv_bytes_per_token(model, dtype) * seq * batch


def decode_bytes_per_step(model: Model, batch: int, seq: int,
                          w_dtype: str = "fp16", kv_dtype: str = "fp16") -> float:
    """Bytes that must cross the memory bus for one decode step.

    Weights are read once for the whole batch -- that is the entire reason
    batching works. The KV cache is read once per sequence, so it scales with
    batch * seq and eventually overtakes the weights.
    """
    return weight_bytes(model, w_dtype) + kv_bytes(model, seq, batch, kv_dtype)


def decode_flops_per_step(model: Model, batch: int) -> float:
    """~2 FLOP per parameter per token. Attention over the cache is extra and
    small at short context; ignored here and named as ignored."""
    return 2 * model.params * batch


def prefill_flops(model: Model, tokens: int) -> float:
    return 2 * model.params * tokens


def step_time(model: Model, device: Device, batch: int, seq: int,
              w_dtype: str = "fp16", efficiency: float = 1.0) -> float:
    """Roofline step time: max(bytes/bandwidth, flops/compute), seconds.

    `efficiency` scales the achieved bandwidth. 1.0 is the ceiling nobody hits;
    0.7 is a plausible real engine. The labs print the ceiling and say so.
    """
    mem = decode_bytes_per_step(model, batch, seq, w_dtype) / (device.bandwidth * efficiency)
    cmp_ = decode_flops_per_step(model, batch) / (device.flops * efficiency)
    return max(mem, cmp_)


def gb(x: float) -> str:
    return f"{x / 1e9:8.2f} GB"


def mb(x: float) -> str:
    return f"{x / 1e6:8.2f} MB"


# --------------------------------------------------------------------------- #
# Measured. Everything below touches the clock on this machine.
# --------------------------------------------------------------------------- #

def copy_bandwidth(size_bytes: int, min_seconds: float = 0.25) -> tuple[float, int]:
    """Achieved memcpy bandwidth in GB/s, counting read + write as 2x bytes.

    `bytearray[:] = other` lowers to memcpy, so this measures the machine and
    not the interpreter -- provided `size_bytes` is large enough that the
    per-call interpreter overhead (~0.3 us) is a rounding error. Below ~64 KB
    it is not, and the curve in roofline_lab.py shows exactly where that starts.
    """
    src = bytearray(size_bytes)
    dst = bytearray(size_bytes)
    reps, elapsed = 0, 0.0
    t0 = time.perf_counter()
    while elapsed < min_seconds:
        dst[:] = src
        reps += 1
        elapsed = time.perf_counter() - t0
    return (2 * size_bytes * reps / elapsed) / 1e9, reps


def percentiles(samples, ps=(50, 90, 95, 99)) -> dict:
    """Nearest-rank percentiles. Explicit because the interpolated variety
    invents a value that no request experienced, and at n=200 the difference
    between p99 definitions is larger than most optimizations."""
    ordered = sorted(samples)
    n = len(ordered)
    out = {}
    for p in ps:
        rank = max(1, math.ceil(p / 100 * n))
        out[f"p{p}"] = ordered[rank - 1]
    return out


def bootstrap_ci(samples, statistic=statistics.mean, resamples: int = 2000,
                 seed: int = 11, level: float = 0.95) -> tuple[float, float]:
    """Percentile bootstrap. Same helper as extraction-eval-sets/lab/interval.py,
    reused here because a timing comparison is an estimate like any other."""
    import random
    rng = random.Random(seed)
    n = len(samples)
    stats = []
    for _ in range(resamples):
        stats.append(statistic([samples[rng.randrange(n)] for _ in range(n)]))
    stats.sort()
    lo = stats[int((1 - level) / 2 * resamples)]
    hi = stats[int((1 + level) / 2 * resamples) - 1]
    return lo, hi


def rule(title: str) -> None:
    print(f"=== {title} ===")


def row(*cells, widths=None) -> None:
    widths = widths or [22] + [12] * (len(cells) - 1)
    print("".join(str(c).ljust(w) for c, w in zip(cells, widths)))
