"""Approximate nearest neighbour search: what you buy, what it costs, and why
the word "navigable" is in the name.

    python ann_lab.py       (about 20 seconds -- the exact ground truth is O(n^2))

Synthetic vectors, not the Chinese corpus. Seventeen documents cannot exhibit an
ANN trade-off; the whole point of an approximate index is a corpus too large to
scan, and the smallest honest demonstration is a few hundred clustered points in
a few dimensions.

Cost is counted in DISTANCE COMPUTATIONS, not milliseconds. Wall time in pure
Python measures the interpreter; the distance count is the quantity a real
implementation optimizes and the one that transfers.
"""
import random
import sys
from heapq import heappop, heappush

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

RNG = random.Random(7)
N, DIM, CLUSTERS = 800, 16, 12
TOPK = 10

# Clustered, because real embeddings are. A uniform cloud would make every
# index look equally good and hide the only interesting failure.
centers = [[RNG.gauss(0, 1) for _ in range(DIM)] for _ in range(CLUSTERS)]
VECTORS = [[x + RNG.gauss(0, 0.35) for x in centers[i % CLUSTERS]] for i in range(N)]
QUERIES = [[x + RNG.gauss(0, 0.45) for x in centers[i % CLUSTERS]] for i in range(60)]


class Counter:
    """Distance computations are the currency. Count them, do not time them."""

    def __init__(self):
        self.n = 0

    def dist(self, a, b):
        self.n += 1
        return sum((x - y) * (x - y) for x, y in zip(a, b))


def exact(query, counter):
    return [i for _, i in sorted((counter.dist(query, v), i)
                                 for i, v in enumerate(VECTORS))[:TOPK]]


def recall(approx, truth):
    return len(set(approx) & set(truth)) / len(truth)


print("=== 0. Ground truth, and what it costs ===")
c = Counter()
TRUTH = [exact(q, c) for q in QUERIES]
print(f"  exact search: {c.n / len(QUERIES):.0f} distance computations per query,")
print(f"  which is N = {N} exactly. There is no way to skip a vector when any of")
print("  them might be the nearest. That is the problem an ANN index exists for.")
print()

# --- IVF: partition the space, scan a few partitions ----------------------
NLIST = 24


def kmeans(k, iters=12):
    cs = [VECTORS[i] for i in RNG.sample(range(N), k)]
    assign = [0] * N
    for _ in range(iters):
        for i, v in enumerate(VECTORS):
            assign[i] = min(range(k),
                            key=lambda j: sum((x - y) ** 2 for x, y in zip(v, cs[j])))
        for j in range(k):
            members = [VECTORS[i] for i in range(N) if assign[i] == j]
            if members:
                cs[j] = [sum(col) / len(members) for col in zip(*members)]
    return cs, {j: [i for i in range(N) if assign[i] == j] for j in range(k)}


CENTROIDS, LISTS = kmeans(NLIST)


def ivf_search(query, nprobe, counter):
    order = sorted(range(NLIST),
                   key=lambda j: counter.dist(query, CENTROIDS[j]))[:nprobe]
    cand = [i for j in order for i in LISTS[j]]
    return [i for _, i in sorted((counter.dist(query, VECTORS[i]), i)
                                 for i in cand)[:TOPK]]


print("=== 1. IVF: recall against cost ===")
print(f"  {'param':<12}{'recall@10':>12}{'dists/query':>14}{'x speedup':>11}"
      f"{'worst query':>13}")
print("  " + "-" * 62)
ivf_rows = {}
for nprobe in (1, 2, 4, 8, 16, 24):
    c = Counter()
    r = [recall(ivf_search(q, nprobe, c), t) for q, t in zip(QUERIES, TRUTH)]
    per = c.n / len(QUERIES)
    ivf_rows[nprobe] = (sum(r) / len(r), per, min(r))
    print(f"  {'nprobe=' + str(nprobe):<12}{sum(r) / len(r):>12.3f}{per:>14.1f}"
          f"{N / per:>11.1f}{min(r):>13.3f}")
print("  Steeply concave: nprobe=2 buys 0.96 recall for an eighth of the work,")
print("  and everything after nprobe=4 is paying full price for the last 1%.")
print("  This shape is why ANN is worth configuring at all -- and why the last")
print("  point on the curve is never the one to ship.")
print()

# --- graph search ---------------------------------------------------------
print("  building proximity graphs (O(n^2), offline, once) ...")
ORDERED = []
for i, v in enumerate(VECTORS):
    ORDERED.append([j for _, j in sorted((sum((x - y) ** 2 for x, y in zip(v, w)), j)
                                         for j, w in enumerate(VECTORS) if j != i)])

KNN_GRAPH = {i: ORDERED[i][:8] for i in range(N)}          # pure proximity
NSW_GRAPH = {i: ORDERED[i][:6] + RNG.sample(range(N), 2)   # + long-range links
             for i in range(N)}


def reachable(graph, start=0):
    seen, stack = {start}, [start]
    while stack:
        for nb in graph[stack.pop()]:
            if nb not in seen:
                seen.add(nb)
                stack.append(nb)
    return len(seen)


def graph_search(query, graph, ef, counter, entry=0):
    """Greedy best-first over a proximity graph; ef is the candidate list size.

    This is HNSW's search procedure with one layer instead of many.
    """
    d0 = counter.dist(query, VECTORS[entry])
    frontier, best, seen = [(d0, entry)], [(-d0, entry)], {entry}
    while frontier:
        d, node = heappop(frontier)
        if len(best) >= ef and d > -best[0][0]:
            break                                  # nothing closer is reachable
        for nb in graph[node]:
            if nb in seen:
                continue
            seen.add(nb)
            dn = counter.dist(query, VECTORS[nb])
            if len(best) < ef or dn < -best[0][0]:
                heappush(frontier, (dn, nb))
                heappush(best, (-dn, nb))
                if len(best) > ef:
                    heappop(best)
    return [i for _, i in sorted((-d, i) for d, i in best)][:TOPK]


print()
print("=== 2. Break it first: the obvious graph, which does not work ===")
print("  Connect every vector to its 8 nearest neighbours and search greedily.")
print("  Predict the recall at ef=100 before reading on -- ef=100 examines an")
print("  eighth of the corpus, and every edge in this graph is a true nearest")
print("  neighbour, so the graph is as accurate as a graph can be.")
print()
print(f"  {'graph':<14}{'ef':>6}{'recall@10':>12}{'dists/query':>14}")
print("  " + "-" * 46)
for ef in (10, 50, 100):
    c = Counter()
    r = [recall(graph_search(q, KNN_GRAPH, ef, c), t) for q, t in zip(QUERIES, TRUTH)]
    print(f"  {'k-NN (8)':<14}{ef:>6}{sum(r) / len(r):>12.3f}{c.n / len(QUERIES):>14.1f}")
print()
print(f"  Diagnosis, one line: nodes reachable from the entry point = "
      f"{reachable(KNN_GRAPH)} of {N}")
print(f"  ({CLUSTERS} clusters, and a pure nearest-neighbour graph never leaves")
print("  the one it starts in.) The recall is not a tuning failure. It is")
print(f"  {1 / CLUSTERS:.3f} -- the fraction of queries whose answer happens to")
print("  live in the entry point's cluster. Raising ef cannot help, because ef")
print("  controls how thoroughly you search a region you cannot reach.")
print()

print("=== 3. The fix, and the reason it is called a NAVIGABLE small world ===")
print("  Same search. Same budget. Replace two of the eight proximity edges per")
print("  node with two random long-range edges.")
print()
print(f"  {'graph':<14}{'ef':>6}{'recall@10':>12}{'dists/query':>14}{'worst':>9}")
print("  " + "-" * 55)
nsw_rows = {}
for ef in (5, 10, 20, 50, 100):
    c = Counter()
    r = [recall(graph_search(q, NSW_GRAPH, ef, c), t) for q, t in zip(QUERIES, TRUTH)]
    per = c.n / len(QUERIES)
    nsw_rows[ef] = (sum(r) / len(r), per, min(r))
    print(f"  {'NSW (6+2)':<14}{ef:>6}{sum(r) / len(r):>12.3f}{per:>14.1f}"
          f"{min(r):>9.3f}")
print(f"  nodes reachable from the entry point = {reachable(NSW_GRAPH)} of {N}")
print()
print("  Six proximity edges are WORSE at describing the neighbourhood than")
print("  eight, and the graph that knows less is the one that works, because the")
print("  long edges make the corpus navigable in a few hops. That is the whole")
print("  small-world idea. HNSW replaces the random long edges with a hierarchy")
print("  of layers -- sparse at the top, dense at the bottom -- which is a better")
print("  way to buy the same property: arrive in the right neighbourhood before")
print("  the fine-grained descent begins. The layers are an entry-point strategy,")
print("  not a different search algorithm.")
print()

print("=== 4. The mean hides the tail ===")
print(f"  {'index':<16}{'param':>10}{'mean recall':>13}{'worst query':>13}")
print("  " + "-" * 52)
for nprobe in (1, 2, 4):
    mean, _, worst = ivf_rows[nprobe]
    print(f"  {'IVF':<16}{'nprobe=' + str(nprobe):>10}{mean:>13.3f}{worst:>13.3f}")
for ef in (10, 50):
    mean, _, worst = nsw_rows[ef]
    print(f"  {'NSW graph':<16}{'ef=' + str(ef):>10}{mean:>13.3f}{worst:>13.3f}")
print("  A 0.96 mean recall is not 'every result 4% worse'. It is most queries")
print("  perfect and a minority badly served, and the minority is not random --")
print("  it is the queries near a partition boundary, which is a stable property")
print("  of the query, not noise. The same user hits it every time. Report the")
print("  distribution, or ship a system that tests well and fails one class of")
print("  user permanently.")
print()

print("=== 5. The number that is not the number you care about ===")
c = Counter()
approx = [ivf_search(q, 2, c) for q in QUERIES]
ann_recall = sum(recall(a, t) for a, t in zip(approx, TRUTH)) / len(QUERIES)
top1 = sum(1 for a, t in zip(approx, TRUTH) if a and a[0] == t[0]) / len(QUERIES)
top3 = sum(1 for a, t in zip(approx, TRUTH)
           if set(a[:3]) == set(t[:3])) / len(QUERIES)
print(f"  IVF nprobe=2:  recall@10 against exact search = {ann_recall:.3f}")
print(f"                 rank 1 identical to exact       = {top1:.3f}")
print(f"                 top 3 identical to exact        = {top3:.3f}")
print("  ANN recall measures agreement with brute force, which is not relevance.")
print("  Brute force is not a gold standard -- it is the same embedding, scored")
print("  exhaustively, and ../vector-similarity.md is about how wrong that can")
print("  be. A 0.9 ANN recall can cost nothing end to end, or everything, and")
print("  the two cases look identical from inside the index. The acceptance")
print("  criterion is nDCG on your own judgments (../retrieval-metrics.md), with")
print("  ANN recall underneath it as a diagnostic.")
