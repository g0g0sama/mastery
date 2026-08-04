# ANN indexes and HNSW intuition

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/), on synthetic vectors rather than the
Chinese corpus -- 17 documents cannot exhibit an approximation trade-off.

**Capability:** ANN indexes and HNSW intuition (Layer 6, `-` -> Working). Map
evidence to graduate: "Recall/latency trade-off curve for your index
parameters." The curve is below. It is measured in **distance computations**,
not milliseconds, because wall time in pure Python measures the interpreter and
the distance count is what a real implementation optimizes.

**Gate:** embeddings. Met as exposure by
[vector-similarity.md](vector-similarity.md), whose conclusion section 5 leans
on.

---

## The problem

Exact nearest-neighbour search costs one distance computation per stored vector.
There is no way to skip one, because any of them might be the nearest:

```text
exact search: 800 distance computations per query, which is N = 800 exactly.
```

At 800 vectors that is a non-issue. At ten million it is the entire latency
budget, per query, forever. Every ANN index is a way of buying a large reduction
in that number by giving up the guarantee.

## The wrong model

**"An ANN index is an exact index with an accuracy knob."**

Under that model you pick a recall target, turn the knob, and the only risk is
setting it too low. Two things break it, and the lab shows both.

The first is that **the mean recall is not what users experience.** At IVF
`nprobe=2` the mean is 0.962 and the worst query gets 0.400. Those misses are not
noise -- they are the queries that sit near a partition boundary, which is a
stable property of the query. The same user hits it every time.

The second is worse, and it is the thing worth knowing about graph indexes:
**there is no knob at all until the graph is connected.**

## The mechanism

Two families, and they fail in different places:

| Family | Idea | Parameter | Fails when |
|---|---|---|---|
| **IVF** | partition into lists, scan the nearest few | `nprobe` | the answer is in a list you did not probe |
| **Graph / HNSW** | greedy descent over a proximity graph | `ef` (candidate list size) | the answer is not reachable from where you started |

`ef` and `nprobe` look like the same knob. They are not. `nprobe` widens the
region you scan; `ef` deepens the search of a region you can already reach.

## The experiment

```powershell
cd modules\zh-retrieval-lab
python ann_lab.py
```

IVF first, and it behaves the way the wrong model expects -- which is why it is
shown first:

```text
param          recall@10   dists/query  x speedup  worst query
nprobe=1           0.787          69.8       11.5        0.200
nprobe=2           0.962         102.4        7.8        0.400
nprobe=4           0.993         184.8        4.3        0.800
nprobe=8           1.000         317.2        2.5        1.000
nprobe=24          1.000         824.0        1.0        1.000
```

Steeply concave: `nprobe=2` buys 0.96 recall for an eighth of the work, and
everything past `nprobe=4` is paying full price for the last one percent. Note
the last row -- exhaustive probing costs *more* than brute force, because you
also paid for the centroids.

**Now predict.** Build the obvious graph: connect every vector to its 8 true
nearest neighbours, search greedily with `ef=100` -- an eighth of the corpus
examined, and every edge in the graph is a genuine nearest neighbour, so the
graph is as accurate as a graph can be. What recall?

```text
graph             ef   recall@10   dists/query
k-NN (8)          10       0.070          38.8
k-NN (8)          50       0.078          59.0
k-NN (8)         100       0.078          60.0
```

Seven percent, flat in `ef`. One line of diagnosis explains all of it:

```text
nodes reachable from the entry point = 60 of 800
```

The data has 12 clusters and **a pure nearest-neighbour graph never leaves the
cluster it starts in**. 0.078 is approximately 1/12: the fraction of queries
whose answer happens to live in the entry point's cluster. Raising `ef` cannot
help, because `ef` controls how thoroughly you search a region you cannot reach.

The fix is the name of the algorithm. Replace two of the eight proximity edges
per node with two **random** long-range edges:

```text
graph             ef   recall@10   dists/query    worst
NSW (6+2)         10       0.805          81.9    0.000
NSW (6+2)         20       0.922         111.2    0.700
NSW (6+2)         50       0.972         173.5    0.700
NSW (6+2)        100       0.980         294.4    0.800
nodes reachable from the entry point = 796 of 800
```

Six proximity edges describe the neighbourhood **worse** than eight, and the
graph that knows less is the one that works. Long edges make the corpus
navigable in a few hops -- the small-world property, and the reason the family is
called *navigable* small world. HNSW replaces the random long edges with a
hierarchy of layers, sparse at the top and dense at the bottom, which buys the
same property more cheaply: arrive in the right neighbourhood, then descend.
**The layers are an entry-point strategy, not a different search algorithm.**

## Boundary

- **ANN recall is agreement with brute force, not relevance.** At `nprobe=2` the
  index agrees with exact search 0.962 of the time and reproduces the exact rank
  1 on 0.950 of queries. Whether that costs anything depends on whether the
  missed vectors were relevant, and brute force does not know either -- it is the
  same embedding, scored exhaustively. Accept on nDCG against your own judgments
  ([retrieval-metrics.md](retrieval-metrics.md)); keep ANN recall underneath as a
  diagnostic.
- **Report the distribution.** Mean recall 0.962 with a worst query at 0.400 is
  a different system from mean 0.962 with a worst query at 0.900, and they are
  indistinguishable in the summary.
- **The graph is built once and searched forever.** The lab's O(n^2) construction
  is honest about being offline; a real HNSW build is incremental and its
  parameters (`M`, `efConstruction`) set the connectivity this module is about.
  A badly built graph cannot be rescued at query time by any `ef`.
- **Deletion is the part this lab does not model**, and it is where graph
  indexes hurt in production -- removing a node can disconnect the neighbourhood
  it was bridging. See
  [retrieval-freshness-deletion.md](retrieval-freshness-deletion.md).
- **800 vectors in 16 dimensions.** The shapes -- concave curve, connectivity
  cliff, tail behaviour -- are structural and transfer. The specific speedups do
  not; high-dimensional data concentrates distances and makes every index worse.

## Cards

### 1. [failure] You build a graph index by connecting each vector to its true 8 nearest neighbours. Recall@10 is 0.08 and does not move when you raise `ef` from 10 to 100. What is wrong?

**Answer:** The graph is disconnected. Greedy search cannot leave the cluster
containing the entry point, so `ef` is deepening a search of a region that does
not hold the answer.

**Why:** A pure proximity graph has no edges between clusters -- every edge is
short by construction. In the lab, 60 of 800 nodes were reachable from the entry
point across 12 clusters, and 0.078 recall is just 1/12.

**Boundary:** The fix is long-range edges, not more of them: replacing two of the
eight proximity edges with two random links took recall to 0.98. The graph that
describes the neighbourhood *less* accurately is the one that is navigable.

**Tags:** `retrieval` `ann` `failure` `general-principle`

---

### 2. [comparison] `nprobe` in an IVF index and `ef` in a graph index are both "search harder" knobs. What is the difference that matters?

**Answer:** `nprobe` widens the region searched; `ef` deepens the search of a
region already reachable.

**Why:** IVF misses when the answer sits in an unprobed partition, which more
probes fix directly. Graph search misses when the answer is unreachable from the
entry point, which no `ef` fixes -- that is a property of graph construction and
entry-point strategy.

**Boundary:** Both curves are steeply concave. In the lab `nprobe=2` reached 0.96
recall at an eighth of brute-force cost and `nprobe=24` cost *more* than brute
force, because the centroid scan is not free.

**Tags:** `retrieval` `ann` `comparison` `general-principle`

---

### 3. [misconception] Your ANN index reports recall@10 of 0.95 against exact search. Why is that not sufficient to accept it?

**Answer:** It measures agreement with brute force over the same embedding, not
relevance to the query.

**Why:** Exact search is not ground truth -- it is the same similarity function,
scored exhaustively, with all of that function's errors intact. A 0.95 ANN recall
costs nothing if the missed vectors were irrelevant and costs a great deal if the
misses land at rank 1.

**Boundary:** Mean recall also hides its tail. In the lab, a mean of 0.962 came
with a worst query at 0.400, and those misses concentrate near partition
boundaries -- a stable property of the query, so the same user hits it every time.

**Tags:** `retrieval` `ann` `misconception` `general-principle`
