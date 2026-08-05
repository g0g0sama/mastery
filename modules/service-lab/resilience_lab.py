"""A client that degrades, and the four ways one amplifies instead.

    python resilience_lab.py      # ~35 s, real servers and real clocks

Map evidence line: "a provider client that degrades instead of amplifying an
outage". Every request below is a real HTTP request to a real listener that
counts what arrived, so the amplification figures are hit counts rather than
arithmetic.

The upstream is down for the first 600 ms of each run and healthy afterwards.
60 logical requests are issued over 1.2 s, so roughly half of them meet a
failing server. That is the shape of a short provider incident, and the whole
question is what the client does to the second half.
"""
from __future__ import annotations

import random
import statistics
import threading
import time

import service as s

N = 60
SPAN = 1.2              # seconds over which the 60 requests are issued
OUTAGE = 0.6            # upstream returns 503 until this many seconds in


# --------------------------------------------------------------------------- #
class Upstream(s.Handler):
    """Counts every arrival. Fails while `t0 + OUTAGE` is in the future."""

    lock = threading.Lock()
    hits: list = []
    t0 = 0.0
    outage = OUTAGE

    @classmethod
    def reset(cls):
        with cls.lock:
            cls.hits = []
            cls.t0 = time.perf_counter()

    def do_GET(self):                                   # noqa: N802
        now = time.perf_counter()
        with type(self).lock:
            type(self).hits.append(now - type(self).t0)
            n = len(type(self).hits)
        if now - type(self).t0 < type(self).outage:
            return self.send_json(503, {"error": "overloaded", "n": n})
        return self.send_json(200, {"ok": True, "n": n})


class Breaker:
    """closed -> (failures) -> open -> (cooldown) -> half_open -> closed|open."""

    def __init__(self, threshold=5, cooldown=0.3, probes=1):
        self.threshold, self.cooldown, self.probes = threshold, cooldown, probes
        self.state, self.failures, self.opened_at = "closed", 0, 0.0
        self.in_flight_probes = 0
        self.short_circuited = 0
        self.lock = threading.Lock()

    def allow(self) -> bool:
        with self.lock:
            if self.state == "open":
                if time.perf_counter() - self.opened_at < self.cooldown:
                    self.short_circuited += 1
                    return False
                self.state, self.in_flight_probes = "half_open", 0
            if self.state == "half_open":
                if self.in_flight_probes >= self.probes:
                    self.short_circuited += 1
                    return False
                self.in_flight_probes += 1
            return True

    def record(self, ok: bool) -> None:
        with self.lock:
            if ok:
                self.state, self.failures = "closed", 0
            else:
                self.failures += 1
                if self.state == "half_open" or self.failures >= self.threshold:
                    self.state, self.opened_at = "open", time.perf_counter()


class Budget:
    """Retries as a fraction of traffic, not a count per request."""

    def __init__(self, ratio=0.1):
        self.ratio, self.calls, self.retries = ratio, 0, 0
        self.lock = threading.Lock()

    def first(self):
        with self.lock:
            self.calls += 1

    def allow_retry(self) -> bool:
        with self.lock:
            if self.retries + 1 > self.ratio * max(self.calls, 10):
                return False
            self.retries += 1
            return True


def client(base, *, tries=1, backoff=0.05, jitter=False,
           breaker: Breaker | None = None, budget: Budget | None = None):
    """One logical request, with whatever policy is switched on."""
    if budget:
        budget.first()
    for attempt in range(tries):
        if breaker and not breaker.allow():
            return "short_circuited"
        status, _ = s.get(base, "/call")
        ok = status == 200
        if breaker:
            breaker.record(ok)
        if ok:
            return "ok"
        if attempt == tries - 1:
            return "failed"
        if budget and not budget.allow_retry():
            return "failed (budget)"
        delay = backoff * (2 ** attempt)
        time.sleep(random.uniform(0, delay) if jitter else delay)
    return "failed"


def storm(base, **policy):
    """60 logical requests spread over SPAN seconds, all at once from threads."""
    out, lock = [], threading.Lock()

    def one(i):
        time.sleep(i * SPAN / N)
        r = client(base, **policy)
        with lock:
            out.append(r)

    threads = [threading.Thread(target=one, args=(i,)) for i in range(N)]
    for t in threads:
        t.start()
    for t in threads:
        t.join()
    return out


print(f"{N} logical requests over {SPAN}s. The upstream returns 503 for the "
      f"first {OUTAGE}s.\n")

# --------------------------------------------------------------------------- #
s.rule("1. What each policy sends at a server that is already failing")
# --------------------------------------------------------------------------- #
s.row("client policy", "requests sent", "amplification", "succeeded",
      widths=[34, 15, 16, 12])
POLICIES = [
    ("no retry", dict(tries=1)),
    ("retry 3x, fixed backoff", dict(tries=3, backoff=0.05)),
    ("retry 3x, full jitter", dict(tries=3, backoff=0.05, jitter=True)),
    ("retry 3x + retry budget 10%", dict(tries=3, backoff=0.05, jitter=True)),
    ("retry 3x + circuit breaker", dict(tries=3, backoff=0.05, jitter=True)),
]
results = {}
for label, policy in POLICIES:
    p = dict(policy)
    if "budget" in label:
        p["budget"] = Budget(0.10)
    if "circuit" in label:
        p["breaker"] = Breaker(threshold=5, cooldown=0.3)
    Upstream.reset()
    with s.serve(Upstream, outage=OUTAGE) as base:
        out = storm(base, **p)
        sent = len(Upstream.hits)
    results[label] = (sent, out)
    ok = sum(1 for r in out if r == "ok")
    s.row(label, sent, f"{sent / N:.2f}x", f"{ok}/{N}", widths=[34, 15, 16, 12])
print("""
  Read the first two rows together. Retrying bought real successes -- that is
  what it is for -- and it bought them by sending roughly twice the traffic at
  a server whose problem was, quite possibly, traffic. The client cannot tell
  the difference between "this instance is unlucky" and "this service is
  saturated", and the same policy is correct for the first and harmful for the
  second.

  The budget row is the one to copy. A per-request retry count scales with
  traffic, so it is largest exactly when the provider is least able to absorb
  it; a budget expressed as a fraction of calls has a ceiling that does not
  move during an incident. Nothing else in this file has that property.
""")

# --------------------------------------------------------------------------- #
s.rule("2. Retries multiply through layers, they do not add")
# --------------------------------------------------------------------------- #
print("Real servers chained -- client -> gateway -> ... -> upstream -- each middle\n"
      "layer retrying 3x. The upstream is down for the whole run. 10 logical\n"
      "requests enter at the top.\n")


class Middle(s.Handler):
    """A service that is itself a client of the next one down."""
    target = ""
    tries = 3

    def do_GET(self):                                   # noqa: N802
        for attempt in range(self.tries):
            status, _ = s.get(self.target, "/call")
            if status == 200:
                return self.send_json(200, {"ok": True})
            if attempt < self.tries - 1:
                time.sleep(0.02)
        return self.send_json(503, {"error": "downstream failed"})


s.row("layers retrying", "upstream hits", "amplification", "predicted",
      widths=[20, 16, 16, 12])
for depth in (1, 2, 3, 4):
    Upstream.reset()
    with s.serve(Upstream, outage=10.0) as up:          # down for the whole run
        stack = [up]
        servers = []
        ctxs = []
        for _ in range(depth - 1):
            cm = s.serve(type(f"M{len(ctxs)}", (Middle,), {}),
                         target=stack[-1], tries=3)
            base = cm.__enter__()
            ctxs.append(cm)
            stack.append(base)
        entry = stack[-1]
        n_logical = 10
        threads = [threading.Thread(target=lambda: s.get(entry, "/call"))
                   for _ in range(n_logical)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()
        hits = len(Upstream.hits)
        for cm in reversed(ctxs):
            cm.__exit__(None, None, None)
    s.row(f"{depth - 1}", hits, f"{hits / n_logical:.1f}x",
          f"3^{depth - 1} = {3 ** (depth - 1)}x", widths=[20, 16, 16, 12])
print("""
  Each layer's retry policy is defensible on its own and nobody owns the
  product. Three layers of a modest 3x is 27 requests for one user action, and
  the layers are usually written by different teams reading different runbooks.

  Two rules fall out. Retry at exactly one layer -- normally the one closest to
  the failure, which knows whether the error is transient. And make the deadline
  travel with the request: a layer that has 200 ms of budget left must not start
  a retry that takes 300 ms, which is what a deadline in the request (rather
  than a timeout per call) enforces.
""")

# --------------------------------------------------------------------------- #
s.rule("3. Jitter is not a rounding detail")
# --------------------------------------------------------------------------- #
print("60 clients all fail at the same instant, then retry after the same 200 ms\n"
      "ceiling. Arrivals are timestamped by the server as they are accepted:\n")
s.row("backoff", "peak / 50 ms", "connections lost", "drain time",
      widths=[24, 15, 19, 14])
for label, jitter in (("fixed 200 ms", False), ("full jitter 0-200 ms", True)):
    Upstream.reset()
    dropped = []
    with s.serve(Upstream, outage=0.0) as base:
        def one():
            time.sleep(random.uniform(0, 0.2) if jitter else 0.2)
            try:
                s.get(base, "/call", timeout=5.0)
            except OSError as exc:          # the backlog, not the application
                dropped.append(type(exc).__name__)
        ts = [threading.Thread(target=one) for _ in range(60)]
        for t in ts:
            t.start()
        for t in ts:
            t.join()
        arrivals = sorted(Upstream.hits)
    buckets = {}
    for a in arrivals:
        buckets[int(a / 0.05)] = buckets.get(int(a / 0.05), 0) + 1
    s.row(label, max(buckets.values()), f"{len(dropped)} of 60",
          f"{(arrivals[-1] - arrivals[0]) * 1000:.0f} ms",
          widths=[24, 15, 19, 14])
print("""
  Same 60 requests, same total load, same backoff ceiling. The third column was
  not part of the plan: the synchronised burst overflows the listener's accept
  backlog and the OS resets connections that the application never sees. Those
  clients get a transport error, which their retry policy reads as transient,
  so they retry -- and they retry in unison, because they failed in unison.

  The drain column is the rest of it. The burst does not arrive faster for
  having been sent together; it arrives together and then waits, behind itself,
  and every client pays that queueing delay on top of the 200 ms it already
  slept. Put that spike on a server that has just come back -- cold caches,
  empty pools, cold JIT -- and it fails again, everyone backs off in unison
  again, and the synchronisation gets *tighter* each round rather than looser.
  That is the mechanism behind a service that will not come up until traffic is
  shed by hand.

  Full jitter -- `sleep(random(0, ceiling))` instead of `sleep(ceiling)` -- is
  one function call and it is the difference between a queue and a wall.
""")

# --------------------------------------------------------------------------- #
s.rule("4. What the breaker is actually for, and its two failure modes")
# --------------------------------------------------------------------------- #
print("A 600 ms outage, 60 requests, three breaker configurations:\n")
s.row("breaker", "upstream hits", "short-circuited", "succeeded",
      widths=[30, 16, 18, 12])
for label, kw in (("none", None),
                  ("threshold 5, cooldown 300ms", dict(threshold=5, cooldown=0.3)),
                  ("threshold 5, cooldown 3s", dict(threshold=5, cooldown=3.0))):
    br = Breaker(**kw) if kw else None
    Upstream.reset()
    with s.serve(Upstream, outage=OUTAGE) as base:
        out = storm(base, tries=3, backoff=0.05, jitter=True, breaker=br)
        sent = len(Upstream.hits)
    ok = sum(1 for r in out if r == "ok")
    s.row(label, sent, br.short_circuited if br else 0, f"{ok}/{N}",
          widths=[30, 16, 18, 12])
print("""
  The breaker's job is not to make the client succeed -- it makes the client
  fail *faster and cheaper*, which is a different and less popular product.
  What it buys is the upstream's chance to recover, and a caller that gets an
  instant error instead of holding a connection for three timeouts.

  Both failure modes are visible above. A cooldown longer than the outage
  converts a 600 ms incident into a self-inflicted one, and it is the setting
  that gets raised after every incident review. A cooldown that closes the
  breaker fully on the first success sends the entire held-back load at a
  server that has proven exactly one request -- which is why half-open admits a
  bounded number of probes rather than opening the gate.

  Two things a breaker must not do, and both are common. It must not count
  4xx-class errors: a schema violation is a fact about the request, and
  breaking the circuit on it takes the service down for one bad caller. And it
  must not be global across tenants or routes if the failure is not -- see
  ../provider-errors-retries.md for the transient/terminal split this depends
  on entirely.
""")

# --------------------------------------------------------------------------- #
s.rule("5. Rate limits: the same limit, three meanings")
# --------------------------------------------------------------------------- #
print("Limit: 10 requests per second. A client sends 10 at t=0.9s and 10 at\n"
      "t=1.0s -- polite by its own reading of the rule.\n")

arrivals = [0.9] * 10 + [1.0] * 10


def fixed_window(times, limit=10, window=1.0):
    counts, admitted = {}, []
    for t in times:
        w = int(t / window)
        counts[w] = counts.get(w, 0) + 1
        admitted.append(counts[w] <= limit)
    return admitted


def sliding_log(times, limit=10, window=1.0):
    seen, admitted = [], []
    for t in times:
        seen = [x for x in seen if x > t - window]
        admitted.append(len(seen) < limit)
        if admitted[-1]:
            seen.append(t)
    return admitted


def token_bucket(times, rate=10.0, capacity=10.0):
    tokens, last, admitted = capacity, times[0], []
    for t in times:
        tokens = min(capacity, tokens + (t - last) * rate)
        last = t
        if tokens >= 1:
            tokens -= 1
            admitted.append(True)
        else:
            admitted.append(False)
    return admitted


def worst_second(times, admitted):
    """Most requests admitted in any 1-second sliding window."""
    ok = [t for t, a in zip(times, admitted) if a]
    return max((sum(1 for x in ok if t <= x < t + 1.0) for t in ok), default=0)


s.row("limiter", "admitted of 20", "worst 1s window", "burst vs limit",
      widths=[22, 17, 18, 16])
for label, fn in (("fixed window", fixed_window), ("sliding log", sliding_log),
                  ("token bucket", token_bucket)):
    adm = fn(arrivals)
    s.row(label, sum(adm), worst_second(arrivals, adm),
          f"{worst_second(arrivals, adm) / 10:.1f}x", widths=[22, 17, 18, 16])
print("""
  The fixed window admits twice its own limit across the boundary and is still
  the most commonly implemented one, because it is a counter and a modulo. If
  your provider's limit is enforced with a sliding window and yours is a fixed
  one, you are 429ing on their side while your dashboard says you are under the
  limit -- and the reverse pairing hands you an outage you cannot see coming.

  Token bucket is the one to reach for when the limit is about protecting a
  resource: capacity is the burst you are willing to absorb and rate is the
  refill, which are the two numbers you actually have opinions about. Sliding
  log is exact and stores every timestamp, so it costs memory per key.

  Whichever you choose, the 429 must carry `Retry-After` and the client must
  read it. A limiter whose response is indistinguishable from a 503 turns every
  well-behaved client into section 1's first row.
""")
