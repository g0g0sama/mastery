"""A hit rate of 59% that saves 28%, and three keys that serve the wrong answer.

    python cache_lab.py       # ~20 s, real threads and a real clock

Map evidence line: "a cache with a stated invalidation rule and a measured hit
rate". Both halves are here and the second is the one that misleads: a hit rate
is an average over requests, and the thing you are trying to save is not
distributed like requests.

Declared, and stated once: the request mix (Zipf over 8 documents plus a rare
tail), and the correlation that rare requests are expensive ones. The costs
themselves are real -- they come from ../model-interface-lab's price table and
token counts -- and every timing, race and eviction below is real.
"""
from __future__ import annotations

import random
import threading
import time

import service as s

PROVIDER_MS = 0.04
random.seed(11)


# --------------------------------------------------------------------------- #
class Cache:
    """Enough cache to have the arguments about. LRU, TTL, optional lock."""

    def __init__(self, capacity=4, ttl=10.0, single_flight=False, cost_of=None):
        self.capacity, self.ttl = capacity, ttl
        self.single_flight = single_flight
        self.cost_of = cost_of                 # None = plain LRU eviction
        self.data: dict = {}                   # key -> (value, stored_at)
        self.order: list = []
        self.hits = self.misses = 0
        self.lock = threading.Lock()
        self.keylocks: dict = {}

    def _fresh(self, key):
        entry = self.data.get(key)
        if entry and time.time() - entry[1] < self.ttl:
            return entry[0]
        return None

    def get_or_load(self, key, loader):
        with self.lock:
            v = self._fresh(key)
            if v is not None:
                self.hits += 1
                self.order.remove(key)
                self.order.append(key)
                return v, True
            self.misses += 1
            if self.single_flight:
                kl = self.keylocks.setdefault(key, threading.Lock())
        if self.single_flight:
            with kl:
                # Re-check: while waiting for this lock, the first caller may
                # have finished. Without this line single-flight collapses to
                # "serialize the stampede" rather than "eliminate it".
                with self.lock:
                    v = self._fresh(key)
                    if v is not None:
                        return v, True
                value = loader()
                self.put(key, value)
                return value, False
        value = loader()
        self.put(key, value)
        return value, False

    def put(self, key, value):
        with self.lock:
            self.data[key] = (value, time.time())
            if key in self.order:
                self.order.remove(key)
            self.order.append(key)
            while len(self.order) > self.capacity:
                if self.cost_of is None:
                    victim = self.order.pop(0)          # plain LRU
                else:
                    # Cost-aware: among the least-recently-used half, drop the
                    # cheapest to recompute. This is the HYPOTHESIS under test
                    # in section 1, not the recommendation -- it loses to plain
                    # LRU on both metrics, because it drops the frequency term.
                    half = self.order[: max(1, len(self.order) // 2)]
                    victim = min(half, key=self.cost_of)
                    self.order.remove(victim)
                self.data.pop(victim, None)

    def invalidate(self, key):
        with self.lock:
            self.data.pop(key, None)
            if key in self.order:
                self.order.remove(key)


# --------------------------------------------------------------------------- #
# The workload. Zipf over the 8 documents, plus a rare long tail. Rare items
# are expensive -- declared, because that correlation is the whole of section 1
# and it would be dishonest to present it as discovered.
# --------------------------------------------------------------------------- #

provider = s.Provider("mid-1")
DOC_COST = {}
for doc_id in s.DOC_IDS:
    r = provider.complete(doc_id)
    DOC_COST[doc_id] = r.cost

RARE = [f"R{i:02d}" for i in range(40)]
# a rare document is a long one: 6x the tokens, so 6x the cost
for r_id in RARE:
    DOC_COST[r_id] = statistics_mean = sum(DOC_COST[d] for d in s.DOC_IDS) / 8 * 6


def workload(n=600):
    """Zipf-ish: the 8 hot documents get 75% of traffic, the 40 rare ones 25%."""
    out = []
    for _ in range(n):
        if random.random() < 0.75:
            w = [1 / (i + 1) for i in range(len(s.DOC_IDS))]
            out.append(random.choices(s.DOC_IDS, weights=w)[0])
        else:
            out.append(random.choice(RARE))
    return out


print("600 requests. 8 hot documents take 75% of the traffic; 40 rare ones take\n"
      "25% and cost 6x each, because a rare request is usually a long one.\n")

# --------------------------------------------------------------------------- #
s.rule("1. The hit rate is an average over requests, not over money")
# --------------------------------------------------------------------------- #
reqs = workload()
total_cost = sum(DOC_COST[d] for d in reqs)


def measure(cap, cost_aware=False):
    c = Cache(capacity=cap, ttl=1e6,
              cost_of=(lambda k: DOC_COST[k]) if cost_aware else None)
    spent = [0.0]
    for doc in reqs:
        def load(doc=doc):
            spent[0] += DOC_COST[doc]
            return doc
        c.get_or_load(doc, load)
    return c.hits / (c.hits + c.misses), 1 - spent[0] / total_cost


s.row("eviction", "size", "hit rate", "cost saved", "gap",
      widths=[16, 8, 12, 14, 10])
gaps = {}
for cap in (4, 8, 16, 32):
    rate, saved = measure(cap)
    gaps[cap] = (rate, saved)
    s.row("LRU", cap, s.pct(rate), s.pct(saved), f"{(rate - saved) * 100:+.1f}",
          widths=[16, 8, 12, 14, 10])
deltas = {}
for cap in (8, 16):
    rate, saved = measure(cap, cost_aware=True)
    base_rate, base_saved = gaps[cap]
    deltas[cap] = (rate - base_rate, saved - base_saved)
    s.row("cost-aware", cap, s.pct(rate), s.pct(saved),
          f"{(rate - saved) * 100:+.1f}", widths=[16, 8, 12, 14, 10])
    print(f"{'':24}vs LRU at the same size: {(rate - base_rate) * 100:+.1f} pts "
          f"hit rate, {(saved - base_saved) * 100:+.1f} pts cost saved")
print(f"""
  The gap column is the first finding and its sign never changes: at every
  capacity the hit rate is higher than the fraction of money saved. A cache
  reports how often it answered; you are paying for what it did not answer.
  Those are the same metric only when every request costs the same, which is
  never true of an LLM workload where one long document can cost an order of
  magnitude more than a short one. Report cost saved, not hit rate -- the same
  totals-versus-ratios argument ../metrics-and-cost-monitoring.md makes about
  spend.

  The second finding is the cost-aware rows, and it is a failed prediction
  rather than a fix. Evicting the cheapest entry instead of the least recent
  was supposed to buy cost saving at the price of hit rate. At capacity 8 it
  lost **both**: {deltas[8][1] * 100:+.1f} points of cost saved and \
{deltas[8][0] * 100:+.1f} points of hit rate.

  The reason is that cost is not a proxy for value. What an entry is worth is
  (how often it is asked for) x (what it costs to recompute), and dropping the
  frequency term threw away entries requested fifty times to keep entries
  requested three times -- which loses on money too, because fifty cheap
  recomputations cost more than three expensive ones. The correct score is the
  product, and half of it is not an approximation of it.

  So: measure cost saved, and if you want to act on it, rank candidates by
  frequency x cost. The one-line version -- "cache the expensive ones" -- is
  worse than plain LRU on this workload.
""")

# --------------------------------------------------------------------------- #
s.rule("2. Everything expires at once, and everyone notices at once")
# --------------------------------------------------------------------------- #
print("40 concurrent requests for the same key, which has just expired.\n"
      f"Each miss costs a real {PROVIDER_MS * 1000:.0f} ms provider call.\n")
s.row("policy", "provider calls", "wall time", "wasted", widths=[26, 17, 14, 12])
for label, sf in (("plain read-through", False), ("single flight per key", True)):
    calls, lock = [0], threading.Lock()
    c = Cache(capacity=8, ttl=5.0, single_flight=sf)

    def load():
        with lock:
            calls[0] += 1
        time.sleep(PROVIDER_MS)
        return "record"

    t0 = time.perf_counter()
    ts = [threading.Thread(target=lambda: c.get_or_load("N01", load))
          for _ in range(40)]
    for t in ts:
        t.start()
    for t in ts:
        t.join()
    elapsed = time.perf_counter() - t0
    s.row(label, calls[0], f"{elapsed:.2f} s", f"{calls[0] - 1} calls",
          widths=[26, 17, 14, 12])
print("""
  A cache miss is not one miss. Under any concurrency at all, one expiry
  becomes as many upstream calls as there are callers in flight, aimed at the
  provider, at the exact moment the cache stopped protecting it. On a hot key
  that is a self-inflicted load spike with the same shape as the thundering
  herd in ../backoff-circuit-breaking.md -- and it happens on a *healthy*
  system, with no failure anywhere.

  Single flight is the fix and it has one subtle part: after acquiring the
  per-key lock the waiter must re-check the cache, because the first caller
  finished while it was waiting. Without that re-check the stampede is
  serialized rather than eliminated, which is worse -- same number of calls,
  now in a queue.

  The other half is not to synchronise the expiries in the first place. A fixed
  TTL applied at fill time makes everything loaded together expire together, so
  jitter the TTL per entry for the same reason section 3 of
  ../backoff-circuit-breaking.md jitters a backoff.
""")

# --------------------------------------------------------------------------- #
s.rule("3. The key is the contract, and it is usually incomplete")
# --------------------------------------------------------------------------- #
print("Same cache, three key designs, over a mixed workload:\n")
s.row("key", "hits", "wrong answers served", "what it forgot",
      widths=[30, 8, 24, 26])

requests = [("acme", "N01", "v1"), ("globex", "N01", "v1"),
            ("acme", "N01", "v1"), ("acme", "N01", "v2"),
            ("globex", "N01", "v2"), ("acme", "N01", "v1")]
ALLOWED = {("acme", "N01"): "acme sees N01",
           ("globex", "N01"): "globex must NOT see N01"}

for label, keyfn, forgot in (
        ("doc_id", lambda t, d, v: d, "tenant and version"),
        ("tenant + doc_id", lambda t, d, v: f"{t}/{d}", "prompt version"),
        ("tenant + doc_id + version", lambda t, d, v: f"{t}/{d}/{v}", "--")):
    c = Cache(capacity=32, ttl=1e6)
    wrong = 0
    for tenant, doc, ver in requests:
        key = keyfn(tenant, doc, ver)
        value, hit = c.get_or_load(key, lambda t=tenant, d=doc, v=ver: (t, d, v))
        if hit and value != (tenant, doc, ver):
            wrong += 1
    s.row(label, c.hits, wrong, forgot, widths=[30, 8, 24, 26])
print("""
  Every value a response depends on has to be in the key, and the list is
  longer than it looks: the principal, the tenant, the model, the prompt
  version, the schema version, the index version, and any feature flag that
  changes the answer. Leave the tenant out and you have reproduced every leak
  in ../authn-and-authz.md with all six authorization checks correct -- the
  check ran, it passed, and the cache answered before it.

  Leave the model or prompt version out and a deploy does not invalidate
  anything, so the service serves the previous release's answers for as long as
  the TTL lasts, on a day when everybody is looking at the new release's
  metrics. ../model-prompt-registry.md found this from the storage side: a
  config id belongs on the row, and the same id belongs in the cache key.

  The counter-pressure is real and should be stated: every field added to the
  key divides the hit rate. That is the trade -- correctness costs hit rate --
  and the way to have it cheaply is a single `config_id` in the key rather than
  seven fields, which is the same 8-bytes-versus-149 argument the registry
  module measured.
""")

# --------------------------------------------------------------------------- #
s.rule("4. A stated invalidation rule, and what each one costs")
# --------------------------------------------------------------------------- #
print("A document is corrected at t=0. When does the cache stop lying?\n")
s.row("rule", "stale window", "invalidations", "cost when wrong",
      widths=[30, 16, 16, 26])
s.row("TTL 60 s", "up to 60 s", "0", "60 s of wrong answers",
      widths=[30, 16, 16, 26])
s.row("TTL 60 s + invalidate", "~0 s", "1 per write",
      "0 if every writer remembers", widths=[30, 16, 16, 28])
s.row("write-through", "0 s", "n/a", "the writer owns cache failures",
      widths=[30, 16, 16, 26])

c = Cache(capacity=8, ttl=60.0)
c.get_or_load("N01", lambda: "old text")
c.invalidate("N01")
v, hit = c.get_or_load("N01", lambda: "corrected text")
print(f"\n  measured: after invalidate, the next read returned "
      f"{v!r} (hit={hit})\n")
print("""  The stated rule matters more than which rule it is. "TTL 60 s" is a complete
  and defensible answer -- it says the data may be up to a minute old and
  everything downstream can plan around that. What is not defensible is the
  common third option, which is a TTL that exists because someone typed a
  number, plus invalidation on the two write paths that were known at the time.
  That combination has a stale window of "60 seconds, except when it is
  forever, and you cannot tell which from the outside".

  One more rule that is always missing: **negative caching**. Caching a 404 for
  60 s is what stops a hot missing key from hammering the origin, and it is
  also how a document that arrives at t=10 s stays invisible until t=60 s. Give
  negative entries their own much shorter TTL, and invalidate them on the
  create path -- which means the create path has to know that a cache exists,
  which is the real cost of the whole mechanism.
""")
