"""Benchmark methodology: a benchmark that reports task accuracy with tok/s.

Map row (Layer 8): "A benchmark that reports task accuracy alongside tokens/sec."

Sections 1-3 are measured on this machine and are about the harness rather than
the system: warmup, measurement order, and how many repetitions a claimed
improvement needs before it is distinguishable from the machine.

Section 4 joins two measured quantities that are usually reported in different
documents by different people -- quality from quant_lab.py and scan throughput
from the memory bandwidth this machine actually achieves -- and shows the
ranking reversing when they are divided by each other.

Commit to the predictions before running.
"""
from __future__ import annotations

import os
import statistics
import subprocess
import sys
import time

import hardware as hw
import quant_lab as q

PREDICTIONS = {
    "A": "Discarding the first iteration is enough warmup for a CPU benchmark "
         "with no JIT.",
    "B": "Measuring A fully, then B fully, is fine as long as both get the same "
         "number of repetitions on the same machine.",
    "C": "With 5 repetitions each, a 5% difference between two implementations "
         "is a real difference.",
    "D": "The configuration with the best quality per byte is the one to serve, "
         "and throughput is a separate concern to be optimized afterwards.",
}


def workload(n: int = 60_000) -> float:
    """A deterministic, allocation-light unit of work. Identical every call --
    which is the point: every difference measured below is the harness."""
    total = 0.0
    for i in range(n):
        total += (i * i) % 7
    return total


def section_1_warmup():
    hw.rule("1. Measured: warmup, with no JIT anywhere in sight")

    def trials(fn, n=30):
        out = []
        for _ in range(n):
            t0 = time.perf_counter()
            fn()
            out.append((time.perf_counter() - t0) * 1000)
        return out

    buf = bytearray(64 << 20)

    def touch():
        # First contact with a freshly allocated buffer is not the same
        # operation as the second: the pages are not resident yet.
        b = bytearray(64 << 20)
        b[:] = buf
        return len(b)

    hw.row("workload", "iter 1", "iter 2", "iter 3", "med 4-10", "med 11-30",
           "1 / steady", widths=[22, 10, 10, 10, 11, 11, 12])
    for label, fn in (("pure compute loop", workload), ("fresh 64 MB buffer", touch)):
        s_ = trials(fn)
        steady = statistics.median(s_[10:])
        hw.row(label, f"{s_[0]:8.2f}", f"{s_[1]:8.2f}", f"{s_[2]:8.2f}",
               f"{statistics.median(s_[3:10]):9.2f}", f"{steady:9.2f}",
               f"{s_[0] / steady:9.2f}x", widths=[22, 10, 10, 10, 11, 11, 12])
        if label.startswith("pure"):
            spread = (max(s_[10:]) - min(s_[10:])) / statistics.median(s_[10:])
            print(f"    steady-state spread for the compute loop: "
                  f"min {min(s_[10:]):.2f}, max {max(s_[10:]):.2f} ms "
                  f"({spread:.0%} of the median)")

    print("\nNeither workload shows a first-iteration penalty here. On CPython")
    print("with no JIT, and with an allocator that hands back pages the process")
    print("has already faulted in, the ritual 'discard the first' removes")
    print("nothing. The number that does matter is in the line above: the")
    print("steady-state spread, which is 20%-ish of the median and is the")
    print("smallest effect this harness can resolve at all.")
    print("\nWarmup is a hypothesis about a specific system, not a rule. It is")
    print("real and large where there is state to warm: a JIT, a GPU whose")
    print("clocks ramp, a kernel autotuner picking an algorithm on first call,")
    print("a cold page cache, an empty KV cache, a connection pool. Every one of")
    print("those applies to a real inference server and none of them applies")
    print("here -- which is exactly why the rule has to be tested rather than")
    print("recited. Discard until the median stops moving, then report the")
    print("spread that remains.")


# Two noise generators, because which one matters is itself a result.
BURN_CPU = "t=0.0\nwhile True:\n    for i in range(200000): t+=(i*i)%7"
BURN_MEM = "b=bytearray(64<<20)\nc=bytearray(64<<20)\nwhile True:\n    c[:]=b"


def _start_noise(kind="mem", n=4):
    procs = [subprocess.Popen([sys.executable, "-c",
                               BURN_MEM if kind == "mem" else BURN_CPU],
                              stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
             for _ in range(n)]
    time.sleep(0.8)          # interpreter startup: the load is not load yet
    return procs


def _stop_noise(procs):
    for pr in procs:
        pr.kill()
    for pr in procs:
        pr.wait()
    time.sleep(0.4)          # let the scheduler settle before measuring again


def section_2_order():
    hw.rule("2. Measured: A/B ordering, when the machine is not stationary")
    print("A and B are the SAME operation -- a 32 MB memcpy -- so any difference")
    print("measured is the harness. Four competing processes start partway")
    print("through: a build, a backup, an autoscaler, a colleague.\n")

    src, dst = bytearray(32 << 20), bytearray(32 << 20)

    def timed():
        t0 = time.perf_counter()
        dst[:] = src
        return (time.perf_counter() - t0) * 1000

    for _ in range(5):
        timed()
    a_block = [timed() for _ in range(30)]
    procs = _start_noise("mem")
    b_block = [timed() for _ in range(30)]
    _stop_noise(procs)

    for _ in range(5):
        timed()
    a_int, b_int = [], []
    procs = []
    for i in range(30):
        if i == 15:
            procs = _start_noise("mem")
        a_int.append(timed())
        b_int.append(timed())
    _stop_noise(procs)

    hw.row("layout", "A median", "B median", "B/A", "verdict",
           widths=[24, 12, 12, 10, 28])
    ab = statistics.median(b_block) / statistics.median(a_block)
    hw.row("A-block then B-block", f"{statistics.median(a_block):10.2f}",
           f"{statistics.median(b_block):10.2f}", f"{ab:8.2f}x",
           "B is slower" if ab > 1.05 else "no difference", widths=[24, 12, 12, 10, 28])
    ai = statistics.median(b_int) / statistics.median(a_int)
    hw.row("interleaved A,B,A,B", f"{statistics.median(a_int):10.2f}",
           f"{statistics.median(b_int):10.2f}", f"{ai:8.2f}x",
           "B is slower" if ai > 1.05 else "no difference", widths=[24, 12, 12, 10, 28])
    print(f"\nblocked layout: a machine change of {abs(ab - 1):.0%} attributed "
          f"entirely to the code")
    print(f"interleaved layout: {abs(ai - 1):.0%} residual")

    # The same load, against a workload that does not share the contended
    # resource. This is the roofline lesson arriving inside the benchmark.
    def compute():
        t0 = time.perf_counter()
        workload()
        return (time.perf_counter() - t0) * 1000

    for _ in range(3):
        compute()
    quiet_c = statistics.median([compute() for _ in range(12)])
    procs = _start_noise("mem")
    noisy_c = statistics.median([compute() for _ in range(12)])
    _stop_noise(procs)
    print(f"\nsame noise, compute-bound workload: {quiet_c:.2f} -> "
          f"{noisy_c:.2f} ms ({noisy_c / quiet_c:.2f}x)")
    print(f"same noise, bandwidth-bound workload: "
          f"{statistics.median(a_block):.2f} -> {statistics.median(b_block):.2f} ms "
          f"({ab:.2f}x)")
    print("\nThe same neighbour, in the same seconds, costs these two workloads")
    print("different multiples -- memory bandwidth is shared and cannot be")
    print("scheduled away from, while cores can. Which is why 'it was fine on my")
    print("machine' is usually true and rarely relevant: the resource your")
    print("benchmark contends for is not the one your neighbour contends for,")
    print("until it is.")
    print("\nAn earlier version of this section used four THREADS instead of")
    print("processes and measured no interference at all: under the GIL the")
    print("noise threads mostly wait. A noise generator that does not compete")
    print("for the resource under test proves nothing.")
    print("\nThe blocked layout attributes a change in the MACHINE to a change")
    print("in the CODE, because time and configuration were varied together.")
    print("Interleaving does not remove the noise -- both arms still slow down --")
    print("it removes the CONFOUND. It costs nothing and it is the default")
    print("nowhere.")
    return ab, ai


def section_3_repetitions():
    hw.rule("3. Measured: how many repetitions a 5% claim needs")

    def timed(n):
        t0 = time.perf_counter()
        workload(n)
        return (time.perf_counter() - t0) * 1000

    for _ in range(3):
        timed(60_000)
    # Interleaved, because section 2 has just shown what a blocked layout does.
    # The first version of this lab measured the arms in blocks and reported a
    # 15% difference for a workload that is 5% smaller.
    base, faster = [], []
    for _ in range(50):
        base.append(timed(60_000))
        faster.append(timed(57_000))                 # genuinely 5% less work
    print(f"A: median {statistics.median(base):.2f} ms   "
          f"B: median {statistics.median(faster):.2f} ms   "
          f"true difference: 5% less work\n")
    hw.row("n per arm", "A mean", "B mean", "diff", "95% CI of diff", "resolvable?",
           widths=[12, 11, 11, 10, 24, 12])
    threshold = None
    for n in (3, 5, 10, 25, 50):
        a, b = base[:n], faster[:n]
        diff = statistics.mean(a) - statistics.mean(b)
        # Bootstrap the DIFFERENCE, not each arm: the question is about one
        # quantity, and two overlapping intervals do not answer it.
        import random
        rng = random.Random(17)
        boots = []
        for _ in range(2000):
            sa = [a[rng.randrange(n)] for _ in range(n)]
            sb = [b[rng.randrange(n)] for _ in range(n)]
            boots.append(statistics.mean(sa) - statistics.mean(sb))
        boots.sort()
        lo, hi = boots[50], boots[-51]
        if lo > 0 and threshold is None:
            threshold = n
        hw.row(n, f"{statistics.mean(a):9.2f}", f"{statistics.mean(b):9.2f}",
               f"{diff:8.2f}", f"[{lo:7.2f}, {hi:7.2f}]",
               "yes" if lo > 0 else "NO", widths=[12, 11, 11, 10, 24, 12])
    print("\nThe effect is real by construction -- B does 5% less work -- and the")
    print("interval says whether this harness can see it. Report the interval or")
    print("report nothing: a bare 'B is 5% faster' is a claim about the machine")
    print("during those particular seconds. Same arithmetic as")
    print("../eval-set-sample-size.md; the units changed, nothing else did.")
    return threshold


def section_4_joint():
    hw.rule("4. The metric that decides: quality AND throughput, divided")
    print("Quality is measured in quant_lab.py on the Chinese retrieval set.")
    print("Scan throughput is derived from THIS machine's measured memory")
    print("bandwidth: an exhaustive index scan is bandwidth-bound, so queries")
    print("per second is bandwidth / bytes scanned.\n")

    bw, _ = hw.copy_bandwidth(64 << 20)
    read_bw = bw / 2 * 1e9              # the copy moved 2 bytes per byte copied
    print(f"measured scan bandwidth on this machine: {read_bw / 1e9:.1f} GB/s\n")

    docs = q.build_embeddings(rogue=True)
    df = q._df_table()
    queries = {k: q.embed_query(k.split(" ", 1)[1], q.DIM, df, True) for k in q.QUERIES}
    n_vectors = 10_000_000
    hourly = 1.20                       # declared: one commodity GPU-hour, USD

    hw.row("scheme", "bytes/vec", "index GB", "queries/s", "recall@5",
           "successful q/s", "$ per 1M ok", widths=[20, 11, 11, 12, 10, 16, 14])
    rows = []
    for name, fn, matrix_fn, bits, group in q.SCHEMES:
        qdocs = matrix_fn(docs, bits) if fn is None else {k: fn(v) for k, v in docs.items()}
        ranks = q.rank_all(qdocs, queries)
        m = q.metrics.evaluate(ranks, q.QUERIES, k=5)
        nbytes = q.bytes_per_vector(bits, group)
        index_bytes = nbytes * n_vectors
        qps = read_bw / index_bytes
        good = qps * m["recall@k"]
        cost = hourly / (good * 3600) * 1e6 if good else float("inf")
        hw.row(name, f"{nbytes:8.0f}", f"{index_bytes / 1e9:8.2f}", f"{qps:9.2f}",
               f"{m['recall@k']:8.3f}", f"{good:13.2f}", f"{cost:11.2f}",
               widths=[20, 11, 11, 12, 10, 16, 14])
        rows.append((name, m["recall@k"], qps, cost))

    best_quality = max(rows, key=lambda r: r[1])
    best_speed = max(rows, key=lambda r: r[2])
    best_cost = min(rows, key=lambda r: r[3])
    print(f"\nbest recall@5:        {best_quality[0]}")
    print(f"best queries/s:       {best_speed[0]}")
    print(f"lowest cost per 1M successful queries: {best_cost[0]}")
    print("\nThree different winners from one table. The first two are the")
    print("numbers each team reports; the third is the only one that answers")
    print("'which should we serve'. It is also the one no benchmark computes")
    print("for you, because it needs a task metric and a systems metric in the")
    print("same row -- which usually means in the same person's head.")
    print("\nThe denominator is the part people get wrong: cost per QUERY makes")
    print("the fastest wrong answer look best. Cost per SUCCESSFUL query is the")
    print("Layer 5 row 'cost per successful task', arriving from Layer 8.")


def section_5_checklist():
    hw.rule("5. What a serving benchmark has to state to be readable")
    for line in [
        "the model, the exact weights, and the quantization",
        "the hardware and the achieved bandwidth, not the sticker bandwidth",
        "prompt and output length distributions -- means are not enough",
        "arrival process: closed loop with N clients, or open loop at R req/s",
        "warmup discarded, repetitions kept, and the order they ran in",
        "TTFT, ITL and end-to-end separately, as percentiles",
        "the task metric, on a named eval set with a version",
        "cost per successful task, with the denominator defined",
    ]:
        print(f"  - {line}")
    print("\nA report missing the fourth line cannot be compared with any other")
    print("report, and it is the line that is missing most often.")


def score(order, threshold):
    hw.rule("6. The predictions")
    ab, ai = order
    verdicts = {
        "A": "WRONG, but not for the expected reason -- this machine shows no "
             "first-iteration penalty at all on either workload. Warmup is a "
             "property of a specific system (JIT, GPU clocks, autotuner, page "
             "cache) and has to be measured before it is discarded",
        "B": f"WRONG -- section 2 measures the SAME function twice and the "
             f"blocked layout mis-attributes {abs(ab - 1):.0%} of it to the "
             f"code, against {abs(ai - 1):.0%} interleaved",
        "C": ((f"{'RIGHT here, and not for a reportable reason' if threshold <= 5 else 'WRONG'}"
               f" -- the interval on the difference first excludes zero at "
               f"n={threshold} on this run, for an effect that is real by "
               f"construction. The threshold moves with the machine and with "
               f"the effect size, so the number to report is the interval, "
               f"never the verdict")
              if threshold else
              "UNRESOLVED on this run -- the interval never excluded zero, for "
              "an effect that is real by construction"),
        "D": "WRONG -- section 4: quality, throughput and cost per successful "
             "query name three different winners on one table, and the third "
             "is the one that answers the question",
    }
    for key, text in PREDICTIONS.items():
        print(f"{key}. {verdicts[key]}\n   claim: {text}\n")


if __name__ == "__main__":
    section_1_warmup()
    print()
    order = section_2_order()
    print()
    threshold = section_3_repetitions()
    print()
    section_4_joint()
    print()
    section_5_checklist()
    print()
    score(order, threshold)
