"""CPU vs GPU and memory bandwidth: which of your workloads is bandwidth-bound.

Map row (Layer 8): "Predict which of your workloads is bandwidth-bound."

Sections 1 is measured on this machine. Sections 2-5 are exact arithmetic over
declared vendor specifications. The point of running 1 first is that the
arithmetic in 2-5 is otherwise weightless -- a ratio nobody has ever seen fail.

Commit to the four predictions below before running.
"""
from __future__ import annotations

import hardware as hw

PREDICTIONS = {
    "A": "Copy bandwidth is roughly flat across working-set sizes from 1 MB to "
         "256 MB, because a linear copy has no reuse for a cache to exploit.",
    "B": "The ridge point (FLOP/byte) of an H100 is lower than an RTX 4090's, "
         "because the H100's headline advantage is memory bandwidth.",
    "C": "Decode of a 7B fp16 model is bandwidth-bound at batch 1 and becomes "
         "compute-bound at a large enough batch -- around the device's ridge "
         "point, so ~164 concurrent sequences on a 4090.",
    "D": "Quantizing weights to int4 speeds up decode by roughly 4x and prefill "
         "by roughly 4x, since both read the same weights.",
}


def section_1_measure():
    import statistics as st
    hw.rule("1. Measured: memcpy bandwidth vs working-set size (this machine)")
    print("2 x bytes counted (one read + one write), median of 5 trials.")
    print("Sizes below ~64 KB are contaminated by per-call interpreter")
    print("overhead, which is itself worth seeing.\n")
    hw.row("working set", "GB/s median", "GB/s min-max", "ns/call",
           widths=[16, 14, 16, 12])
    sizes = [4 << 10, 64 << 10, 512 << 10, 4 << 20, 16 << 20, 64 << 20, 256 << 20]
    results = {}
    for size in sizes:
        trials = [hw.copy_bandwidth(size, min_seconds=0.15)[0] for _ in range(5)]
        bw = st.median(trials)
        results[size] = bw
        label = f"{size >> 10} KB" if size < (1 << 20) else f"{size >> 20} MB"
        hw.row(label, f"{bw:10.1f}", f"{min(trials):6.1f} - {max(trials):6.1f}",
               f"{2 * size / (bw * 1e9) * 1e9:,.0f}", widths=[16, 14, 16, 12])
    peak = max(results.values())
    dram = results[256 << 20]
    print(f"\npeak {peak:.1f} GB/s cache-resident, {dram:.1f} GB/s at 256 MB "
          f"-- ratio {peak / dram:.2f}x")
    print("Declared DDR5-5600 dual-channel theoretical peak: 89.6 GB/s.")
    print(f"Achieved by ONE thread at 256 MB: {dram / 89.6:.0%} of theoretical.")
    print("That gap is the reason 'memory-bandwidth-bound' is a property of the")
    print("device and not of the core: a single stream cannot keep enough")
    print("requests in flight to saturate the controller.")
    return results


def section_2_ridge():
    hw.rule("2. Derived: the ridge point, FLOP per byte")
    print("Below this ratio a kernel cannot use the device's FLOPs at all.\n")
    hw.row("device", "GB/s", "TFLOP/s", "FLOP/byte", widths=[32, 10, 12, 12])
    for key, d in hw.DEVICES.items():
        hw.row(d.name, f"{d.bandwidth / 1e9:8.0f}", f"{d.flops / 1e12:8.0f}",
               f"{d.balance:8.0f}", widths=[32, 10, 12, 12])
    print("\nRead the last column as: tokens that must be in flight together")
    print("before the accelerator is doing arithmetic rather than waiting.")


def section_3_intensity():
    hw.rule("3. Derived: arithmetic intensity of decode, by batch size")
    model = hw.MODELS["7B-mha"]
    dev = hw.DEVICES["rtx-4090"]
    seq = 2048
    print(f"{model.name}, fp16, seq={seq}, on {dev.name} "
          f"(ridge {dev.balance:.0f} FLOP/byte)\n")
    hw.row("batch", "weights GB", "KV GB", "FLOP/step", "intensity", "bound by",
           widths=[8, 12, 12, 12, 12, 10])
    for batch in (1, 4, 16, 64, 128, 164, 256, 512):
        w = hw.weight_bytes(model)
        kv = hw.kv_bytes(model, seq, batch)
        fl = hw.decode_flops_per_step(model, batch)
        intensity = fl / (w + kv)
        hw.row(batch, f"{w / 1e9:8.2f}", f"{kv / 1e9:8.2f}", f"{fl / 1e9:,.0f} GF",
               f"{intensity:8.1f}",
               "memory" if intensity < dev.balance else "compute",
               widths=[8, 12, 12, 12, 12, 10])

    print("\nIntensity does not grow with batch -- it converges. The asymptote is")
    print("2 x params / KV-bytes-per-sequence: weights amortize, the KV cache")
    print("does not, because every sequence reads its own.\n")
    hw.row("model", "scheme", "KV/token", "seq", "plateau", "ridge 4090", "reachable?",
           widths=[22, 10, 12, 8, 10, 12, 12])
    for key in ("7B-mha", "8B-gqa", "7B-mqa"):
        m = hw.MODELS[key]
        for s in (512, 2048, 8192):
            plateau = 2 * m.params / hw.kv_bytes(m, s)
            hw.row(m.name.split(" (")[0], m.attention_scheme,
                   hw.mb(hw.kv_bytes_per_token(m)).strip(), s,
                   f"{plateau:8.1f}", f"{dev.balance:8.0f}",
                   "yes" if plateau > dev.balance else "NO -- never",
                   widths=[22, 10, 12, 8, 10, 12, 12])
    print("\n'NO -- never' means no batch size on this device makes decode")
    print("compute-bound at that context length. The FLOPs are unreachable and")
    print("the only lever left is moving fewer bytes.")


def section_4_ceiling():
    hw.rule("4. Derived: decode ceiling, tokens/s at batch 1")
    print("bandwidth / bytes-per-step. An upper bound: real engines reach")
    print("60-80% of it. Nothing here depends on the FLOPs.\n")
    seq = 2048
    hw.row("model / dtype", *(d.name.split(",")[0] for d in hw.DEVICES.values()),
           widths=[26] + [15] * len(hw.DEVICES))
    for key in ("7B-mha", "13B-mha", "70B-gqa"):
        model = hw.MODELS[key]
        for dtype in ("fp16", "int8", "int4"):
            cells = []
            for d in hw.DEVICES.values():
                by = hw.decode_bytes_per_step(model, 1, seq, dtype)
                fits = hw.weight_bytes(model, dtype) + hw.kv_bytes(model, seq) < d.memory
                tps = d.bandwidth / by
                cells.append(f"{tps:7.0f}" + ("" if fits else "  (OOM)"))
            hw.row(f"{model.name.split(' ')[0]} {dtype}", *cells,
                   widths=[26] + [15] * len(hw.DEVICES))
    print("\n(OOM) = weights + a 2048-token cache exceed the device's memory.")


def section_5_prefill():
    hw.rule("5. Derived: prefill and decode are two different machines")
    model = hw.MODELS["7B-mha"]
    dev = hw.DEVICES["rtx-4090"]
    print(f"{model.name} fp16 on {dev.name}\n")
    hw.row("phase", "bytes", "FLOP", "mem ms", "compute ms", "bound by",
           widths=[24, 12, 12, 11, 12, 10])
    for tokens in (1, 128, 2048):
        by = hw.decode_bytes_per_step(model, 1, 2048)
        fl = hw.prefill_flops(model, tokens)
        mem_ms = by / dev.bandwidth * 1000
        cmp_ms = fl / dev.flops * 1000
        phase = "decode, 1 token" if tokens == 1 else f"prefill, {tokens} tokens"
        hw.row(phase, hw.gb(by).strip(), f"{fl / 1e12:6.2f} TF",
               f"{mem_ms:8.2f}", f"{cmp_ms:9.2f}",
               "memory" if mem_ms > cmp_ms else "compute", widths=[24, 12, 12, 11, 12, 10])
    print("\nSame weights, same device, opposite bottleneck. A quantization that")
    print("halves the bytes halves decode time and does nothing for prefill;")
    print("a faster kernel does the reverse. 'Which is faster' has no answer")
    print("until the phase is named.")

    print("\nWhat int4 actually buys, per phase:")
    hw.row("dtype", "decode tok/s", "prefill 2048 ms", widths=[10, 16, 18])
    for dtype in ("fp16", "int8", "int4"):
        by = hw.decode_bytes_per_step(model, 1, 2048, dtype)
        dec = dev.bandwidth / by
        pre = max(hw.prefill_flops(model, 2048) / dev.flops,
                  hw.weight_bytes(model, dtype) / dev.bandwidth) * 1000
        hw.row(dtype, f"{dec:8.0f}", f"{pre:10.1f}", widths=[10, 16, 18])


def score():
    hw.rule("6. The predictions")
    verdicts = {
        "A": ("WRONG (measured)", "the small end is faster, and not because of "
              "caching alone -- see the ns/call column"),
        "B": ("WRONG (derived)", "H100 balance 296 vs 4090 164: the compute grew "
              "faster than the bandwidth, so the newer device needs a LARGER batch"),
        "C": ("WRONG (derived)", "there is no crossover. Intensity converges to "
              "12.6 at seq=2048 with MHA, because KV traffic scales with the "
              "batch that was supposed to amortize the weights"),
        "D": ("HALF RIGHT (derived)", "decode ~3.7x, prefill unchanged: prefill "
              "is compute-bound and int4 moves bytes, not FLOPs"),
    }
    for key, text in PREDICTIONS.items():
        verdict, why = verdicts[key]
        print(f"{key}. {verdict}\n   claim: {text}\n   why:   {why}\n")


if __name__ == "__main__":
    section_1_measure()
    print()
    section_2_ridge()
    print()
    section_3_intensity()
    print()
    section_4_ceiling()
    print()
    section_5_prefill()
    print()
    score()
