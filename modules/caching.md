# Caching

**Micro module.** One mechanism, one experiment, three cards. Runs against
[service-lab/](service-lab/).

**Capability:** Caching (Layer 1b, Aware -> Working). Map evidence: "A cache
with a stated invalidation rule and a measured hit rate."

---

## The problem

Both halves of that evidence line are traps. The measured hit rate answers a
question you are probably not asking, and "stated invalidation rule" sounds
like paperwork right up to the point where the rule is "TTL 60 seconds, plus
whichever write paths remembered".

The workload: 600 requests, 8 hot documents taking 75% of traffic, 40 rare ones
taking 25% and costing 6x each -- because a rare request is usually a long one.
That correlation is declared; the costs themselves come from the provider's
real token counts and price table.

## The mechanism

**A hit rate is an average over requests. You pay in money.**

```text
eviction     size   hit rate   cost saved   gap
LRU           4     39.2%      18.1%        +21.1
LRU           8     59.2%      28.5%        +30.7
LRU          16     73.0%      39.7%        +33.3
LRU          32     86.5%      66.1%        +20.4
cost-aware    8     47.2%      23.9%        +23.3
cost-aware   16     65.2%      39.2%        +25.9
```

The gap column never changes sign: at every capacity the hit rate is higher
than the fraction of money saved. A cache reports how often it answered; you
are paying for what it did not answer. Those are the same metric only when
every request costs the same, which is never true of an LLM workload where one
long document can cost an order of magnitude more than a short one.

**The cost-aware rows are a failed prediction, not a fix.** Evicting the
cheapest entry instead of the least recent was supposed to trade hit rate for
money. At capacity 8 it lost both: **-4.6 points of cost saved and -12.0 points
of hit rate.**

The reason is that cost is not a proxy for value. An entry is worth (how often
it is asked for) x (what it costs to recompute), and dropping the frequency
term throws away entries requested fifty times to keep entries requested three
times -- which loses on money too, because fifty cheap recomputations cost more
than three expensive ones. Half of a product is not an approximation of the
product. Measure cost saved; if you want to act on it, rank by frequency x
cost. The one-line version, "cache the expensive ones", is worse than plain LRU
here.

**Everything expires at once, and everyone notices at once.** 40 concurrent
requests for one key that has just expired:

```text
policy                  provider calls   wasted
plain read-through      40               39 calls
single flight per key    1                0 calls
```

A cache miss is not one miss. Under any concurrency, one expiry becomes as many
upstream calls as there are callers in flight, aimed at the provider at the
exact moment the cache stopped protecting it. On a hot key that is a
self-inflicted load spike with the same shape as the thundering herd in
[backoff-circuit-breaking.md](backoff-circuit-breaking.md) -- and it happens on
a healthy system with no failure anywhere.

Single flight is the fix, with one subtle part: after acquiring the per-key
lock, the waiter must **re-check the cache**, because the first caller finished
while it was waiting. Without that re-check the stampede is serialized rather
than eliminated -- same number of calls, now in a queue. The other half is not
to synchronise the expiries at all: a fixed TTL applied at fill time makes
everything loaded together expire together, so jitter the TTL per entry for the
same reason you jitter a backoff.

**The key is the contract, and it is usually incomplete.**

```text
key                          hits   wrong answers   what it forgot
doc_id                       5      3               tenant and version
tenant + doc_id              4      2               prompt version
tenant + doc_id + version    2      0               --
```

Every value the response depends on has to be in the key, and the list is
longer than it looks: principal, tenant, model, prompt version, schema version,
index version, and any feature flag that changes the answer.

Leave the tenant out and you have reproduced every leak in
[authn-and-authz.md](authn-and-authz.md) with all six authorization checks
correct -- the check ran, it passed, and the cache answered before it. Leave
the model or prompt version out and a deploy invalidates nothing, so the
service serves the previous release's answers for as long as the TTL lasts, on
the day everyone is watching the new release's metrics.
[model-prompt-registry.md](model-prompt-registry.md) found this from the
storage side: a config id belongs on the row, and the same id belongs in the
key.

The counter-pressure is real and belongs in the decision: every field added to
the key divides the hit rate. Correctness costs hit rate. The cheap way to have
both is one `config_id` in the key rather than seven fields -- the same
8-bytes-versus-149 argument the registry module measured.

**A stated invalidation rule, and what each costs:**

```text
rule                      stale window   invalidations   cost when wrong
TTL 60 s                  up to 60 s     0               60 s of wrong answers
TTL 60 s + invalidate     ~0 s           1 per write     0 if every writer remembers
write-through             0 s            n/a             the writer owns cache failures
```

The stated rule matters more than which rule it is. "TTL 60 s" is complete and
defensible: the data may be up to a minute old and everything downstream can
plan around that. What is not defensible is the common third option -- a TTL
that exists because someone typed a number, plus invalidation on the two write
paths that were known at the time. That has a stale window of "60 seconds,
except when it is forever, and you cannot tell which from the outside".

The rule that is always missing is **negative caching**. Caching a 404 for 60 s
is what stops a hot missing key from hammering the origin, and it is also how a
document that arrives at t=10 s stays invisible until t=60 s. Give negative
entries a much shorter TTL and invalidate them on the create path -- which
means the create path has to know a cache exists, and that is the real cost of
the whole mechanism.

## The experiment

```powershell
cd modules\service-lab
python cache_lab.py     # ~20 s, real threads and a real clock
```

## Boundary

- **The cost/frequency correlation is declared**, not discovered: this fixture
  asserts that rare requests are 6x more expensive. If your rare requests are
  *cheap*, the gap between hit rate and cost saved narrows and may invert.
  Measure it on your own traffic before quoting either number -- that
  measurement is the point of the section, not the specific percentages.
- **The cache is in-process.** A shared cache (Redis, memcached) adds a network
  hop, its own failure modes, serialization cost, and the question of what
  happens when it is down -- and "the cache is down so everything hits the
  origin at once" is section 2 at production scale.
- **Single flight here is per process.** Ten replicas with a shared backing
  store still produce ten concurrent misses on the same key; suppressing that
  needs a distributed lock, which brings its own lease-expiry problem
  ([background-jobs-queues.md](background-jobs-queues.md) section 2).
- **Nothing here covers cache warming, tiering, or coherence between layers**
  (browser, CDN, app, database buffer pool), where the stale windows compose.

## Cards

### 1. [misconception] The cache reports an 86% hit rate, so it is saving most of the cost.

**Answer:** It is not. In the lab an 86.5% hit rate corresponded to 66.1% of
cost saved, and at smaller sizes the gap was over 30 points -- the hit rate is
higher than the cost saved at every capacity.

**Why:** A hit rate averages over requests; spend is distributed over requests
by price. They agree only when every request costs the same, which is untrue of
any workload where document length varies.

**Boundary:** Do not "fix" it by evicting the expensive entries -- that was
tested and lost on *both* metrics, because value is frequency x cost and
dropping the frequency term keeps items asked for three times over items asked
for fifty. Report cost saved; rank candidates by the product. And if the cache
exists for latency rather than spend, hit rate is the right metric after all.

**Tags:** `caching` `metrics` `misconception` `general-principle`

---

### 2. [failure] A popular cache key expires and the upstream provider sees a burst of identical requests. What is the fix, and what is the easy way to get it wrong?

**Answer:** Single flight -- one loader per key, everyone else waits. In the
lab 40 concurrent requests for one expired key made 40 provider calls; with
single flight, one. The easy mistake is to omit the re-check after acquiring
the per-key lock, which serializes the stampede instead of eliminating it: the
same number of calls, now in a queue.

**Why:** A miss is per caller, not per key. Expiry removes the protection at
the exact moment demand for that key is highest.

**Boundary:** Also jitter the TTL per entry, or everything loaded together
expires together and you get the burst on a schedule. Across replicas, single
flight is per process -- ten replicas still make ten calls unless you take a
distributed lock, which brings its own lease-expiry problems.

**Tags:** `caching` `stampede` `failure` `general-principle`

---

### 3. [mechanism] What has to be in a cache key, and what is the cost of getting it complete?

**Answer:** Every input the response depends on: principal/tenant, model,
prompt version, schema version, index version, and any feature flag that
changes the answer. In the lab, omitting the tenant served another tenant's
answer with all authorization checks passing; omitting the prompt version
served the previous release's answers for the length of the TTL.

**Why:** The key *is* the equivalence claim -- "these two requests deserve the
same answer". Anything left out is an assertion that it does not affect the
result.

**Boundary:** Every field added divides the hit rate, so completeness is a real
trade rather than a free win. Carry one `config_id` that identifies the whole
configuration instead of seven separate fields.

**Tags:** `caching` `mechanism` `general-principle`
