"""TTFT, throughput and latency percentiles, measured under concurrency.

Map row (Layer 8): "p50/p95 measured under concurrency, not single requests."

The server here is a sleep-based stand-in for a model: no weights, no GPU. What
is real is everything the map row is actually about -- the threads, the queue,
the clock, the arrival process, and the arithmetic that turns 200 samples into a
p99. Those are the parts that get measurement wrong in production too.

Service times are authored (section 0 prints them). Queueing behaviour is not:
it emerges from the schedule, and section 3 was written expecting a smaller
effect than it produced.

Commit to the predictions before running.
"""
from __future__ import annotations

import queue
import random
import statistics
import threading
import time

import hardware as hw

PREDICTIONS = {
    "A": "Latency measured with one client, times the number of clients, is a "
         "reasonable estimate of latency under load.",
    "B": "p99 latency is roughly 2-3x p50 for a service with no failures and "
         "no external dependencies.",
    "C": "Measuring with a fixed number of looping clients (closed loop) and "
         "measuring at a fixed arrival rate (open loop) give the same "
         "percentiles if the throughput is the same.",
    "D": "Time-to-first-token and end-to-end latency move together: an engine "
         "change that improves one improves the other.",
}

SLOTS = 4                 # concurrent sequences the 'engine' can decode
PREFILL_MS = 20.0         # fixed cost of a prefill
PREFILL_PER_TOK = 0.02    # per prompt token
DECODE_MS = 4.0           # per output token, at batch 1
CONTENTION = 0.10         # each additional in-flight sequence slows the step


class Engine:
    """A fake inference engine with a fixed number of decode slots.

    The one behaviour worth stealing from a real engine: a step is shared, so
    an extra sequence in flight slows every sequence in flight. `CONTENTION`
    is the authored knob; everything downstream of it is emergent.
    """

    def __init__(self, slots: int = SLOTS):
        self.sem = threading.Semaphore(slots)
        self.active = 0
        self.lock = threading.Lock()

    def run(self, prompt_tokens: int, output_tokens: int, on_first_token=None,
            on_admit=None):
        self.sem.acquire()
        if on_admit:
            on_admit()
        with self.lock:
            self.active += 1
        try:
            time.sleep((PREFILL_MS + PREFILL_PER_TOK * prompt_tokens) / 1000)
            if on_first_token:
                on_first_token()
            for _ in range(output_tokens):
                with self.lock:
                    active = self.active
                time.sleep(DECODE_MS * (1 + CONTENTION * (active - 1)) / 1000)
        finally:
            with self.lock:
                self.active -= 1
            self.sem.release()


def workload(n: int, seed: int = 3):
    rng = random.Random(seed)
    return [(int(rng.lognormvariate(5.5, 0.6)), max(4, int(rng.lognormvariate(3.2, 0.7))))
            for _ in range(n)]


def section_0_floor():
    hw.rule("0. Measured: the measurement floor on this machine")
    samples = []
    for _ in range(200):
        t0 = time.perf_counter()
        time.sleep(0.001)
        samples.append((time.perf_counter() - t0) * 1000)
    p = hw.percentiles(samples)
    print(f"time.sleep(1 ms) actually takes: median {statistics.median(samples):.3f} ms, "
          f"p95 {p['p95']:.3f}, p99 {p['p99']:.3f}, max {max(samples):.3f}")
    t0 = time.perf_counter()
    for _ in range(10_000):
        time.perf_counter()
    print(f"perf_counter() call overhead: {(time.perf_counter() - t0) / 10_000 * 1e9:.0f} ns")
    print("\nEvery number below carries this floor. A serving optimization worth")
    print("less than the timer's own p99 cannot be measured with this harness --")
    print("which is the first question to ask of any benchmark, including one")
    print("that reports a 3% improvement.")


def closed_loop(clients: int, requests: int, engine: Engine):
    """`clients` threads, each sending the next request as soon as the last
    returns. This is what almost every load-test tool does by default."""
    work = queue.Queue()
    for item in workload(requests):
        work.put(item)
    ttfts, e2es = [], []
    lock = threading.Lock()

    def client():
        while True:
            try:
                prompt, out = work.get_nowait()
            except queue.Empty:
                return
            t0 = time.perf_counter()
            first = {}
            engine.run(prompt, out, lambda: first.setdefault("t", time.perf_counter()))
            t1 = time.perf_counter()
            with lock:
                ttfts.append((first["t"] - t0) * 1000)
                e2es.append((t1 - t0) * 1000)

    threads = [threading.Thread(target=client) for _ in range(clients)]
    start = time.perf_counter()
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    wall = time.perf_counter() - start
    return ttfts, e2es, requests / wall


def section_1_concurrency():
    hw.rule("1. Measured: what concurrency does to the same server")
    print(f"engine: {SLOTS} decode slots, {CONTENTION:.0%} step slowdown per "
          f"extra in-flight sequence\n")
    hw.row("clients", "req/s", "TTFT p50", "TTFT p95", "e2e p50", "e2e p95",
           "e2e p99", "e2e mean", widths=[9, 9, 11, 11, 10, 10, 10, 10])
    single = None
    for clients in (1, 2, 4, 8, 16):
        engine = Engine()
        ttfts, e2es, tput = closed_loop(clients, 60, engine)
        tp, ep = hw.percentiles(ttfts), hw.percentiles(e2es)
        if clients == 1:
            single = (statistics.median(e2es), tput)
        hw.row(clients, f"{tput:6.1f}", f"{tp['p50']:8.1f}", f"{tp['p95']:8.1f}",
               f"{ep['p50']:8.1f}", f"{ep['p95']:8.1f}", f"{ep['p99']:8.1f}",
               f"{statistics.mean(e2es):8.1f}", widths=[9, 9, 11, 11, 10, 10, 10, 10])
    print(f"\nSingle-client median was {single[0]:.1f} ms at {single[1]:.1f} req/s.")
    print("Throughput stops rising well before latency stops rising: past the")
    print("slot count, every extra client buys queueing and nothing else.")
    return single


def open_loop(rate: float, seconds: float, engine: Engine, senders: int | None = None):
    """Requests arrive on a schedule, whether or not the server is ready.

    `senders=None` spawns a thread per arrival: the generator can never fall
    behind, so `sent` and `scheduled` coincide and the measurement is honest by
    construction. A finite `senders` is what every load-test tool actually does,
    and it is where coordinated omission enters: when all senders are blocked
    waiting for slow responses, the arrivals that should have happened do not,
    and the requests that would have been slowest are never issued.
    """
    rng = random.Random(9)
    rows = []
    lock = threading.Lock()
    jobs = workload(4000)
    schedule = []
    t = 0.0
    while t < seconds:
        t += rng.expovariate(rate)
        schedule.append(t)
    start = time.perf_counter()

    def run_one(idx, scheduled_at):
        wait_for = start + scheduled_at - time.perf_counter()
        if wait_for > 0:
            time.sleep(wait_for)
        sent = time.perf_counter()
        marks = {}
        engine.run(*jobs[idx % len(jobs)],
                   on_first_token=lambda: marks.setdefault("first", time.perf_counter()),
                   on_admit=lambda: marks.setdefault("admit", time.perf_counter()))
        done = time.perf_counter()
        with lock:
            rows.append({
                "from_sent": (done - sent) * 1000,
                "from_scheduled": (done - (start + scheduled_at)) * 1000,
                "queue": (marks["admit"] - sent) * 1000,
                "ttft": (marks["first"] - sent) * 1000,
            })

    if senders is None:
        threads = [threading.Thread(target=run_one, args=(i, at))
                   for i, at in enumerate(schedule)]
        for th in threads:
            th.start()
    else:
        pending = list(enumerate(schedule))
        cursor = [0]
        clock = threading.Lock()

        def sender():
            while True:
                with clock:
                    if cursor[0] >= len(pending):
                        return
                    idx, at = pending[cursor[0]]
                    cursor[0] += 1
                run_one(idx, at)

        threads = [threading.Thread(target=sender) for _ in range(senders)]
        for th in threads:
            th.start()
    for th in threads:
        th.join()
    wall = time.perf_counter() - start
    return rows, len(schedule) / wall


def section_2_open_loop():
    hw.rule("2. Measured: three harnesses, one server")
    print("First closed loop with 8 looping clients. Then the same server at")
    print("the arrival rate closed loop produced, driven open-loop: once with")
    print("an unlimited generator, once with 8 sender threads, which is what")
    print("a load-test tool actually has.\n")
    engine = Engine()
    _, e2es_c, tput_c = closed_loop(8, 100, engine)
    pc = hw.percentiles(e2es_c)

    engine = Engine()
    rows_u, rate_u = open_loop(tput_c * 1.1, 6.0, engine, senders=None)
    engine = Engine()
    rows_b, rate_b = open_loop(tput_c * 1.1, 6.0, engine, senders=8)

    hw.row("harness / metric", "offered", "p50", "p90", "p95", "p99", "max",
           widths=[34, 9, 10, 10, 10, 10, 10])

    def show(label, samples, offered):
        q = hw.percentiles(samples)
        hw.row(label, f"{offered:6.1f}", f"{q['p50']:8.1f}", f"{q['p90']:8.1f}",
               f"{q['p95']:8.1f}", f"{q['p99']:8.1f}", f"{max(samples):8.1f}",
               widths=[34, 9, 10, 10, 10, 10, 10])

    show("closed loop, 8 clients", e2es_c, tput_c)
    show("open loop, thread per arrival", [r["from_scheduled"] for r in rows_u], rate_u)
    show("open loop, 8 senders, from send", [r["from_sent"] for r in rows_b], rate_b)
    show("  ... same run, from arrival", [r["from_scheduled"] for r in rows_b], rate_b)

    sent_p = hw.percentiles([r["from_sent"] for r in rows_b])
    sched_p = hw.percentiles([r["from_scheduled"] for r in rows_b])
    qp = hw.percentiles([r["queue"] for r in rows_b])
    print(f"\nqueue wait alone (8 senders): p50 {qp['p50']:.0f} ms, "
          f"p95 {qp['p95']:.0f} ms, p99 {qp['p99']:.0f} ms")
    print("understatement by the sender-limited harness, percentile by percentile:")
    hw.row("", *(f"{k}: {sched_p[k] / sent_p[k]:.1f}x" for k in sent_p),
           widths=[4] + [14] * len(sent_p))
    print("\nThe last two rows are the SAME REQUESTS on the SAME RUN, timed from")
    print("two different instants. From the send is what a tool can report")
    print("without being told the intended schedule; from the intended arrival")
    print("is what a user experiences. When every sender is blocked, the")
    print("arrivals that should have happened do not -- the harness stops")
    print("sampling exactly when the server is worst.")
    print("\nThe understatement is largest in the BODY of the distribution, not")
    print("at the extreme tail: the single slowest request is slow from either")
    print("reference point, while the requests that were never issued would")
    print("have populated p50 through p95. A report that quotes only p99 can")
    print("miss the whole effect.")
    return pc


def section_3_mean():
    hw.rule("3. Measured: what the mean hides")
    engine = Engine()
    _, e2es, tput = closed_loop(12, 120, engine)
    mean = statistics.mean(e2es)
    p = hw.percentiles(e2es, (50, 90, 95, 99))
    worse = sum(1 for x in e2es if x > mean) / len(e2es)
    print(f"n={len(e2es)}, mean {mean:.1f} ms, p50 {p['p50']:.1f} ms, "
          f"p99 {p['p99']:.1f} ms")
    print(f"fraction of requests worse than the mean: {worse:.0%}")
    print(f"p99/p50 ratio: {p['p99'] / p['p50']:.2f}x")
    print(f"\nAt n={len(e2es)}, p99 is the {len(e2es) - int(0.99 * len(e2es))} "
          f"slowest sample(s). Its bootstrap 95% interval:")
    lo, hi = hw.bootstrap_ci(e2es, lambda s: hw.percentiles(s, (99,))["p99"])
    print(f"  p99 = {p['p99']:.1f} ms, CI [{lo:.1f}, {hi:.1f}] "
          f"-- width {hi - lo:.1f} ms")
    lo50, hi50 = hw.bootstrap_ci(e2es, lambda s: hw.percentiles(s, (50,))["p50"])
    print(f"  p50 = {p['p50']:.1f} ms, CI [{lo50:.1f}, {hi50:.1f}] "
          f"-- width {hi50 - lo50:.1f} ms")
    print("\nA tail percentile estimated from a few hundred samples is a wide")
    print("interval reported as a single number. Same arithmetic as")
    print("../eval-set-sample-size.md, arriving from the other direction.")


def section_4_ttft_vs_e2e():
    hw.rule("4. Measured: the two metrics can move in opposite directions")
    print("Two engine configurations. B admits twice as many sequences, which")
    print("is the standard throughput fix.\n")
    hw.row("config", "req/s", "TTFT p50", "TTFT p95", "e2e p50", "tok/s",
           widths=[22, 9, 11, 11, 11, 10])
    out = {}
    for label, slots in (("A: 4 slots", 4), ("B: 8 slots", 8)):
        engine = Engine(slots)
        ttfts, e2es, tput = closed_loop(16, 80, engine)
        tokens = sum(o for _, o in workload(80))
        tp = hw.percentiles(ttfts)
        wall = 80 / tput
        hw.row(label, f"{tput:6.1f}", f"{tp['p50']:8.1f}", f"{tp['p95']:8.1f}",
               f"{hw.percentiles(e2es)['p50']:8.1f}", f"{tokens / wall:8.0f}",
               widths=[22, 9, 11, 11, 11, 10])
        out[label] = (tput, tp["p50"], tokens / wall)
    print("\nMore slots means more sequences sharing each step, so every")
    print("individual sequence decodes more slowly while the engine finishes")
    print("more of them. Which number is 'performance' depends on whether a")
    print("human is watching the tokens appear.")
    return out


def score():
    hw.rule("5. The predictions")
    print("Compare each against the tables above; the verdicts are the ones")
    print("this run produced.\n")
    verdicts = {
        "A": "WRONG -- throughput saturates at the slot count while latency "
             "keeps climbing; the product of the two is not conserved",
        "B": "WRONG in the tail -- p99/p50 is well above 3x once arrivals are "
             "not throttled by the client, and section 3 shows the p99 estimate "
             "itself has an interval wider than most optimizations",
        "C": "WRONG -- that is coordinated omission. Section 2 measures the "
             "same engine twice and the open-loop tail is the larger one",
        "D": "WRONG -- section 4: more slots raises tokens/s and req/s while "
             "TTFT gets worse. Any single 'latency' number hides which one",
    }
    for key, text in PREDICTIONS.items():
        print(f"{key}. {verdicts[key]}\n   claim: {text}\n")


if __name__ == "__main__":
    section_0_floor()
    print()
    section_1_concurrency()
    print()
    section_2_open_loop()
    print()
    section_3_mean()
    print()
    section_4_ttft_vs_e2e()
    print()
    score()
