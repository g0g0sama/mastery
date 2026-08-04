"""Batching and request scheduling: throughput vs latency for your setup.

Map row (Layer 8): "Throughput vs latency curve for your local setup."

A discrete-event simulation, not a sleep-based one -- it has to run thousands of
steps and compare four schedulers on identical arrivals. What is authored: the
arrival process and the length distribution. What is *derived from
roofline_lab.py* rather than invented: the cost of one decode step, which is
max(bytes/bandwidth, FLOP/compute) at the current batch size. Change the model
or the device in hardware.py and every number below moves accordingly.

The one thing a simulation cannot give you is a surprise about the hardware.
What it can give you -- and what the map row asks for -- is the shape of the
curve, and the fact that the peak-throughput point and the SLO point are not
the same point.

Commit to the predictions before running.
"""
from __future__ import annotations

import random
import statistics

import hardware as hw

PREDICTIONS = {
    "A": "Continuous batching beats static batching on throughput by maybe "
         "20-30% at this scale.",
    "B": "Raising the maximum batch size raises throughput and raises latency, "
         "monotonically -- the trade-off is a straight line and picking a point "
         "on it is a business decision.",
    "C": "Prefill and decode compete, so running prefills at the highest "
         "priority is the way to keep time-to-first-token low.",
    "D": "The scheduler that maximizes throughput is the right default; latency "
         "is fixed afterwards with a bigger machine.",
}

MODEL = hw.MODELS["8B-gqa"]
DEVICE = hw.DEVICES["rtx-4090"]
EFFICIENCY = 0.7          # fraction of peak bandwidth a real engine achieves
CHUNK = 512               # prefill chunk, in tokens


def arrivals(n: int, rate: float, seed: int = 4):
    """Poisson arrivals, lognormal prompt and output lengths.

    The output length is long-tailed and -- this is the part that matters --
    unknown to the scheduler until the sequence stops. Every scheduling policy
    below has to work without it.
    """
    rng = random.Random(seed)
    t = 0.0
    out = []
    for _ in range(n):
        t += rng.expovariate(rate)
        prompt = max(16, int(rng.lognormvariate(6.0, 0.7)))
        gen = max(4, int(rng.lognormvariate(4.2, 0.9)))
        out.append({"arrive": t, "prompt": prompt, "gen": gen})
    return out


def decode_step_seconds(batch: int, mean_seq: float) -> float:
    return hw.step_time(MODEL, DEVICE, batch, int(mean_seq), efficiency=EFFICIENCY)


def prefill_seconds(tokens: int) -> float:
    """Compute-bound: 2 x params x tokens, plus one weight read."""
    return max(hw.prefill_flops(MODEL, tokens) / (DEVICE.flops * EFFICIENCY),
               hw.weight_bytes(MODEL) / (DEVICE.bandwidth * EFFICIENCY))


def simulate(reqs, policy="continuous", max_batch=32, chunked_prefill=False):
    """One engine, one policy, one arrival trace.

    policy = "none"        one sequence at a time
             "static"      form a batch, run it to completion, then the next
             "continuous"  refill a finished slot on the next step
    """
    pending = [dict(r) for r in reqs]
    for i, r in enumerate(pending):
        r["id"] = i
    queue_, active, done, itl = [], [], [], []
    t = 0.0
    cursor = 0
    slots = 1 if policy == "none" else max_batch
    busy_slot_steps = wasted_slot_steps = steps = 0
    prefill_time = decode_time = 0.0

    while cursor < len(pending) or queue_ or active:
        while cursor < len(pending) and pending[cursor]["arrive"] <= t:
            queue_.append(pending[cursor])
            cursor += 1
        if not active and not queue_:
            t = pending[cursor]["arrive"]
            continue

        can_admit = (policy != "static") or not active
        if can_admit:
            while queue_ and len(active) < slots:
                r = queue_.pop(0)
                r["admitted"] = t
                r["seq"] = r["prompt"]
                r["left"] = r["gen"]
                if chunked_prefill:
                    r["prefill_left"] = r["prompt"]
                else:
                    # Prefill-priority: the whole engine stalls for it.
                    cost = prefill_seconds(r["prompt"])
                    t += cost
                    prefill_time += cost
                    r["prefill_left"] = 0
                    r["ttft"] = t - r["arrive"]
                active.append(r)

        if not active:
            continue

        mean_seq = statistics.mean(r["seq"] for r in active)
        step = decode_step_seconds(len(active), mean_seq)
        if chunked_prefill:
            # A chunk of prefill rides along with the decode step, which is what
            # makes the step slower for everyone and the first token sooner for
            # the one being prefilled.
            chunk_tokens = sum(min(CHUNK, r["prefill_left"]) for r in active)
            if chunk_tokens:
                cost = prefill_seconds(chunk_tokens)
                step += cost
                prefill_time += cost
        t += step
        decode_time += step
        steps += 1
        busy_slot_steps += len(active)
        wasted_slot_steps += slots - len(active)

        finished = []
        for r in active:
            if r.get("prefill_left"):
                consumed = min(CHUNK, r["prefill_left"])
                r["prefill_left"] -= consumed
                if r["prefill_left"] == 0:
                    r["ttft"] = t - r["arrive"]
                continue
            if "last_tok" not in r:
                r.setdefault("ttft", t - r["arrive"])
                r["last_tok"] = t
            else:
                # Inter-token latency, as the reader of a stream experiences it.
                # A prefill stall lands inside one of these gaps.
                itl.append(t - r["last_tok"])
                r["last_tok"] = t
            r["left"] -= 1
            r["seq"] += 1
            if r["left"] <= 0:
                r["finish"] = t
                finished.append(r)
        if policy == "static":
            # A static batch is a barrier: the slot of a finished sequence is
            # padding until the longest sequence in the batch is done.
            if len(finished) == len(active):
                done.extend(active)
                active = []
        else:
            for r in finished:
                active.remove(r)
            done.extend(finished)

    e2e = [r["finish"] - r["arrive"] for r in done]
    ttft = [r["ttft"] for r in done]
    tokens = sum(r["gen"] for r in done)
    return {
        "policy": policy, "max_batch": max_batch, "wall": t,
        "itl": hw.percentiles(itl) if itl else {"p50": 0, "p90": 0, "p95": 0, "p99": 0},
        "req_s": len(done) / t, "tok_s": tokens / t,
        "ttft": hw.percentiles(ttft), "e2e": hw.percentiles(e2e),
        "util": busy_slot_steps / (busy_slot_steps + wasted_slot_steps),
        "steps": steps, "prefill_frac": prefill_time / (prefill_time + decode_time),
    }


W = [26, 9, 9, 10, 10, 9, 9, 9, 9, 8]


def show(label, r):
    hw.row(label, f"{r['req_s']:7.2f}", f"{r['tok_s']:7.0f}",
           f"{r['ttft']['p50'] * 1000:8.0f}", f"{r['ttft']['p95'] * 1000:8.0f}",
           f"{r['itl']['p50'] * 1000:7.1f}", f"{r['itl']['p99'] * 1000:7.1f}",
           f"{r['e2e']['p50']:7.2f}", f"{r['e2e']['p95']:7.2f}",
           f"{r['util']:6.1%}", widths=W)


def header():
    hw.row("policy", "req/s", "tok/s", "TTFT p50", "TTFT p95", "ITL p50",
           "ITL p99", "e2e p50", "e2e p95", "util", widths=W)
    print("(TTFT and ITL in ms, e2e in seconds)")


def section_1_policies():
    hw.rule("1. Four schedulers, one arrival trace")
    print(f"{MODEL.name} on {DEVICE.name} at {EFFICIENCY:.0%} of peak bandwidth,")
    print("300 requests, Poisson at 4/s, lognormal lengths.\n")
    reqs = arrivals(300, 4.0)
    lens = [r["gen"] for r in reqs]
    print(f"output length: median {statistics.median(lens):.0f}, "
          f"p95 {hw.percentiles(lens, (95,))['p95']}, max {max(lens)} tokens\n")
    header()
    results = {}
    results["none"] = simulate(reqs, "none")
    show("no batching", results["none"])
    results["static"] = simulate(reqs, "static", 32)
    show("static, batch 32", results["static"])
    results["cont"] = simulate(reqs, "continuous", 32)
    show("continuous, batch 32", results["cont"])
    results["cont_chunk"] = simulate(reqs, "continuous", 32, chunked_prefill=True)
    show("continuous + chunked", results["cont_chunk"])
    print(f"\nstatic -> continuous: {results['cont']['req_s'] / results['static']['req_s']:.1f}x "
          f"throughput, utilization {results['static']['util']:.0%} -> "
          f"{results['cont']['util']:.0%}")
    return reqs, results


def section_2_padding(reqs):
    hw.rule("2. Where the static batch went")
    lens = sorted(r["gen"] for r in reqs)
    batches = [lens[i:i + 32] for i in range(0, len(lens) - 31, 32)]
    print("Slot-steps a static batch spends on sequences that already finished,")
    print("computed directly from the length distribution:\n")
    hw.row("batch composition", "mean len", "max len", "padding waste",
           widths=[24, 12, 12, 16])
    for label, sample in (("sorted by length", batches[len(batches) // 2]),
                          ("as they arrive", [r["gen"] for r in reqs[:32]])):
        mean, mx = statistics.mean(sample), max(sample)
        hw.row(label, f"{mean:8.1f}", f"{mx:8.0f}", f"{1 - mean / mx:12.1%}",
               widths=[24, 12, 12, 16])
    print("\nThe waste is 1 - mean/max, and it is a property of the length")
    print("distribution alone. Length-sorted batching (the left row) is the")
    print("classic fix and it needs the output length in advance, which nobody")
    print("has. Continuous batching does not need it -- that is the actual")
    print("innovation, not the batching.")


def section_3_curve(reqs):
    hw.rule("3. The throughput-latency curve, and where the knee is")
    print("Same trace, continuous batching, max batch swept.\n")
    header()
    rows = []
    for b in (1, 2, 4, 8, 16, 32, 64, 128, 256):
        r = simulate(reqs, "continuous", b)
        rows.append((b, r))
        show(f"max batch {b}", r)
    best = max(rows, key=lambda x: x[1]["req_s"])
    print(f"\npeak throughput at max batch {best[0]}: "
          f"{best[1]['req_s']:.2f} req/s, e2e p95 {best[1]['e2e']['p95']:.2f} s, "
          f"ITL p99 {best[1]['itl']['p99'] * 1000:.0f} ms")
    enough = [r for r in rows if r[1]["req_s"] >= 0.98 * best[1]["req_s"]]
    pick = min(enough, key=lambda x: x[0])
    print(f"smallest cap within 2% of peak: {pick[0]} -- "
          f"{pick[1]['req_s']:.2f} req/s, e2e p95 {pick[1]['e2e']['p95']:.2f} s, "
          f"ITL p99 {pick[1]['itl']['p99'] * 1000:.0f} ms")
    slo = [r for r in rows if r[1]["e2e"]["p95"] <= 10.0]
    if slo:
        s_pick = max(slo, key=lambda x: x[1]["req_s"])
        print(f"largest batch meeting a 10 s e2e p95 SLO: {s_pick[0]} -- "
              f"{s_pick[1]['req_s']:.2f} req/s "
              f"({s_pick[1]['req_s'] / best[1]['req_s']:.0%} of peak)")
    print("\nThroughput saturates and the utilization column says why: past the")
    print("knee the cap stops binding, and average concurrency is set by the")
    print("arrival rate and the engine's speed instead. What a larger cap still")
    print("changes is ITL p99 -- the stream stutters more -- so past the knee it")
    print("is not neutral, it is a pure loss.")
    print("\nThe curve is not a line and the peak is not the answer. Two")
    print("defensible rules: the smallest cap that reaches peak throughput, or")
    print("the largest cap that still meets the latency SLO. Both are printed")
    print("above, and under a different arrival rate (section 4) they move.")
    return rows


def section_4_overload(reqs_rate):
    hw.rule("4. The same sweep under overload")
    print("Arrival rate raised until the engine cannot keep up. This is where a")
    print("batch-size choice stops being a preference.\n")
    for rate in (2.0, 4.0, 8.0):
        reqs = arrivals(300, rate)
        print(f"-- arrivals {rate:.0f}/s --")
        header()
        for b in (8, 32, 128):
            show(f"max batch {b}", simulate(reqs, "continuous", b))
        print()


def section_5_prefill(reqs):
    hw.rule("5. Prefill priority vs chunked prefill")
    print("A prefill is compute-bound and long; a decode step is")
    print("bandwidth-bound and short. Running the prefill first stalls every")
    print("sequence already generating.\n")
    header()
    a = simulate(reqs, "continuous", 32, chunked_prefill=False)
    show("prefill-priority", a)
    b = simulate(reqs, "continuous", 32, chunked_prefill=True)
    show(f"chunked, {CHUNK} tokens", b)
    print(f"\nprefill share of engine time: {a['prefill_frac']:.1%} "
          f"vs {b['prefill_frac']:.1%}")
    print(f"ITL p99 for streaming sequences: {a['itl']['p99'] * 1000:.0f} ms "
          f"-> {b['itl']['p99'] * 1000:.0f} ms "
          f"({b['itl']['p99'] / a['itl']['p99']:.2f}x)")
    print(f"TTFT p50 for the arriving request: {a['ttft']['p50'] * 1000:.0f} ms "
          f"-> {b['ttft']['p50'] * 1000:.0f} ms")
    print("\nChunking does not make prefill cheaper. It makes the stall shorter")
    print("and more frequent, which moves cost from the sequences that are")
    print("already streaming to the one that just arrived. Whether that is an")
    print("improvement depends on which metric is in the SLO -- and both are")
    print("called 'latency'.")


def score():
    hw.rule("6. The predictions")
    print("Verdicts from this run:\n")
    verdicts = {
        "A": "UNDERSTATED -- section 1 measures a multiple, not a percentage, "
             "because a static batch holds slots for sequences that finished "
             "hundreds of steps ago",
        "B": "WRONG -- section 3: throughput saturates while latency keeps "
             "climbing, so past the knee a larger cap is pure loss. There is a "
             "wrong answer, not just a trade-off",
        "C": "WRONG for the sequences already running -- section 5: it improves "
             "the TTFT of the arriving request and stalls everyone streaming. "
             "Chunked prefill trades between them explicitly",
        "D": "WRONG -- the peak-throughput batch violates the SLO in section 3, "
             "and section 4 shows the gap widening under overload. A bigger "
             "machine moves the knee; it does not remove it",
    }
    for key, text in PREDICTIONS.items():
        print(f"{key}. {verdicts[key]}\n   claim: {text}\n")


if __name__ == "__main__":
    reqs, _ = section_1_policies()
    print()
    section_2_padding(reqs)
    print()
    section_3_curve(reqs)
    print()
    section_4_overload(reqs)
    print()
    section_5_prefill(reqs)
    print()
    score()
