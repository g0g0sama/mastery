"""Dimensionality reduction: what the axes lost, and who paid for it.

    python pca_lab.py

Map row (Layer 2): "Reduce your embeddings and explain what the axes lost."

The vectors are the sparse TF-IDF vectors from `../zh-retrieval-lab/`, over the
same seventeen documents and six queries the Layer 6 modules use, so a recall
number here is directly comparable with one there. The reduction is a truncated
SVD computed by power iteration on the 17x17 Gram matrix -- no library, and
small enough to check by hand.

Four questions:

  1. What does the first component actually encode? It is nearly always
     something structural rather than semantic, and knowing which is the
     difference between a reduction and a superstition.
  2. Does centering matter? PCA is defined on centred data and cosine
     retrieval is usually run on uncentred data, and the two conventions
     disagree about what the first axis is.
  3. How much retrieval quality survives k components -- and does variance
     explained predict it?
  4. Which query pays? An aggregate that holds up while one query collapses is
     the same failure `structured-outputs.md` found in a sliced prompt gain.

Seventeen documents resolve a large effect and nothing subtle. What transfers
is the geometry and the shape of the loss; the specific k at which a query dies
is a property of this corpus.
"""
from __future__ import annotations

import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "zh-retrieval-lab"))

from analyzers import bigram          # noqa: E402
from corpus import DOCS, QUERIES      # noqa: E402
from metrics import ndcg_at_k, recall_at_k  # noqa: E402

PREDICTIONS = {
    "A": "The first principal component of a TF-IDF document set is the "
         "corpus's dominant topic.",
    "B": "Centring is a detail; PCA with and without it gives nearly the same "
         "first axis.",
    "C": "Retaining 90% of the variance retains roughly 90% of the retrieval "
         "quality.",
    "D": "Reduction degrades every query about equally, so the aggregate "
         "recall is a fair summary of the cost.",
}

K_EVAL = 5

# ---------------------------------------------------------------------------
# Dense TF-IDF matrix over the corpus vocabulary.
# ---------------------------------------------------------------------------
doc_ids = sorted(DOCS)
terms = {d: bigram(DOCS[d]) for d in doc_ids}
vocab = sorted({t for ts in terms.values() for t in ts})
col = {t: i for i, t in enumerate(vocab)}
N = len(doc_ids)
df = {t: sum(1 for d in doc_ids if t in terms[d]) for t in vocab}
idf = {t: math.log(N / df[t]) for t in vocab}


def vectorize(tokens):
    v = [0.0] * len(vocab)
    for t in tokens:
        if t in col:
            v[col[t]] += idf[t]
    return v


X = [vectorize(terms[d]) for d in doc_ids]
mean = [sum(row[j] for row in X) / N for j in range(len(vocab))]


def sub(a, b):
    return [x - y for x, y in zip(a, b)]


def dot(a, b):
    return sum(x * y for x, y in zip(a, b))


def norm(a):
    return math.sqrt(dot(a, a))


def scale(a, s):
    return [x * s for x in a]


def components(rows, n_comp):
    """Top principal directions of `rows`, by power iteration on the Gram
    matrix. Returns (list of unit vectors in term space, singular values^2)."""
    work = [list(r) for r in rows]
    out, energies = [], []
    for _ in range(n_comp):
        gram = [[dot(a, b) for b in work] for a in work]
        # NOT the uniform vector. Centred rows sum to zero, so the all-ones
        # direction is exactly in the Gram matrix's null space and the
        # iteration returns 7.6e-15 forever. Deterministic, arbitrary, and
        # outside that subspace is what is wanted.
        u = [math.sin(i + 1.0) for i in range(len(work))]
        un = math.sqrt(sum(x * x for x in u))
        u = [x / un for x in u]
        val = 0.0
        for _ in range(400):
            nu = [sum(gram[i][j] * u[j] for j in range(len(work)))
                  for i in range(len(work))]
            val = math.sqrt(sum(x * x for x in nu))
            if val < 1e-12:
                break
            u = [x / val for x in nu]
        direction = [sum(u[i] * work[i][j] for i in range(len(work)))
                     for j in range(len(vocab))]
        n = norm(direction)
        if n < 1e-9:
            break
        direction = scale(direction, 1 / n)
        out.append(direction)
        energies.append(val)
        # Deflate: remove this direction from every row.
        work = [sub(r, scale(direction, dot(r, direction))) for r in work]
    return out, energies


def project(vec, basis, centre):
    base = sub(vec, mean) if centre else vec
    return [dot(base, b) for b in basis]


def cosine(a, b):
    na, nb = norm(a), norm(b)
    return dot(a, b) / (na * nb) if na and nb else 0.0


def order(scored):
    """Rank, dropping non-positive scores.

    The filter is not cosmetic. With it removed, every document a query cannot
    match at all stays in the ranking at score 0.0 and is ordered by document
    id, so recall@5 over a 17-document corpus measures the alphabet. Q3 -- the
    query the corpus was built to be unmatchable by -- scores a clean 1.000
    that way. `zh-retrieval-lab/vector_lab.py` filters for the same reason.
    """
    return [d for d, s in sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))
            if s > 0]


def scores_reduced(query, basis, centre, k):
    qv = vectorize(bigram(query))
    q = project(qv, basis[:k], centre)
    return {d: cosine(q, project(X[i], basis[:k], centre))
            for i, d in enumerate(doc_ids)}


def rank_reduced(query, basis, centre, k):
    return order(scores_reduced(query, basis, centre, k))


def distinct_scores(query, basis, centre, k):
    kept = [round(s, 9) for s in scores_reduced(query, basis, centre, k).values()
            if s > 0]
    return len(set(kept))


def rank_full(query):
    qv = vectorize(bigram(query))
    return order({d: cosine(qv, X[i]) for i, d in enumerate(doc_ids)})


centred = [sub(row, mean) for row in X]
basis_c, energy_c = components(centred, N - 1)
basis_u, energy_u = components(X, N - 1)
total_c = sum(energy_c)

print("=" * 74)
print("1. What the first component is")
print("=" * 74)
print(f"{len(doc_ids)} documents, {len(vocab)} bigram terms, "
      f"{len(basis_c)} usable components after centring")
print()
print("Correlation of each document's score on component 1 with two structural")
print("properties of the document, and with nothing semantic:")
lengths = [len(terms[d]) for d in doc_ids]
norms = [norm(row) for row in X]
pc1_c = [dot(sub(X[i], mean), basis_c[0]) for i in range(N)]
pc1_u = [dot(X[i], basis_u[0]) for i in range(N)]


def pearson(a, b):
    ma, mb = sum(a) / len(a), sum(b) / len(b)
    da, db = [x - ma for x in a], [y - mb for y in b]
    d = math.sqrt(sum(x * x for x in da) * sum(y * y for y in db))
    return sum(x * y for x, y in zip(da, db)) / d if d else 0.0


print(f"{'':<26}{'centred PC1':>14}{'uncentred PC1':>16}")
print(f"{'document length (terms)':<26}{pearson(pc1_c, lengths):>14.4f}"
      f"{pearson(pc1_u, lengths):>16.4f}")
print(f"{'vector norm':<26}{pearson(pc1_c, norms):>14.4f}"
      f"{pearson(pc1_u, norms):>16.4f}")
print()
print("Cosine between the centred and uncentred first axes: "
      f"{abs(cosine(basis_c[0], basis_u[0])):.4f}")
print("Cosine between the uncentred first axis and the corpus mean vector: "
      f"{abs(cosine(basis_u[0], mean)):.4f}")
print()
print("Top documents by |component 1| score, centred (ids only -- no CJK to stdout):")
ordered = sorted(range(N), key=lambda i: -abs(pc1_c[i]))
for i in ordered[:4]:
    print(f"  {doc_ids[i]}  score {pc1_c[i]:+.4f}  length {lengths[i]:>3} terms")

print()
print("=" * 74)
print("2. Variance explained, and what it does not buy")
print("=" * 74)
print("`distinct` is the mean number of distinct scores among the documents a")
print("query retrieves. Cosine in k dimensions cannot separate more than it")
print("has room to: at k=1 it takes two values, everything ties, and the")
print("ranking is the tie-break rule. Read the recall column against it.")
print()
print(f"{'k':>4}{'variance explained':>20}{'recall@5':>10}{'nDCG@5':>9}"
      f"{'MRR':>8}{'kendall vs full':>17}{'distinct':>10}")
full_rankings = {q: rank_full(q) for q in QUERIES}
full = {"recall@k": sum(recall_at_k(full_rankings[q], rel, K_EVAL)
                        for q, rel in QUERIES.items()) / len(QUERIES),
        "nDCG@k": sum(ndcg_at_k(full_rankings[q], rel, K_EVAL)
                      for q, rel in QUERIES.items()) / len(QUERIES)}


def mrr(rankings):
    total = 0.0
    for q, rel in QUERIES.items():
        for i, d in enumerate(rankings[q], start=1):
            if d in rel:
                total += 1 / i
                break
    return total / len(QUERIES)


def kendall_top(rankings):
    """Fraction of document pairs ordered the same way as the full-rank run,
    averaged over queries. A blunt but honest stability measure."""
    total, agree = 0, 0
    end = len(doc_ids)
    for q in QUERIES:
        pos_full = {d: i for i, d in enumerate(full_rankings[q])}
        pos_red = {d: i for i, d in enumerate(rankings[q])}
        for a in range(len(doc_ids)):
            for b in range(a + 1, len(doc_ids)):
                da, db = doc_ids[a], doc_ids[b]
                fa, fb = pos_full.get(da, end), pos_full.get(db, end)
                ra, rb = pos_red.get(da, end), pos_red.get(db, end)
                if fa == fb:          # both unretrieved by the full run
                    continue
                total += 1
                if (fa < fb) == (ra < rb):
                    agree += 1
    return agree / total if total else 1.0


rows = []
for k in (1, 2, 3, 4, 6, 8, 12, len(basis_c)):
    rankings = {q: rank_reduced(q, basis_c, True, k) for q in QUERIES}
    rec = sum(recall_at_k(rankings[q], rel, K_EVAL)
              for q, rel in QUERIES.items()) / len(QUERIES)
    nd = sum(ndcg_at_k(rankings[q], rel, K_EVAL)
             for q, rel in QUERIES.items()) / len(QUERIES)
    ve = sum(energy_c[:k]) / total_c
    dis = sum(distinct_scores(q, basis_c, True, k) for q in QUERIES) / len(QUERIES)
    rows.append((k, ve, rec, nd, rankings))
    print(f"{k:>4}{ve:>20.4f}{rec:>10.4f}{nd:>9.4f}{mrr(rankings):>8.4f}"
          f"{kendall_top(rankings):>17.4f}{dis:>10.1f}")
full_distinct = sum(len({round(s, 9) for s in
                         {d: cosine(vectorize(bigram(q)), X[i])
                          for i, d in enumerate(doc_ids)}.values() if s > 0})
                    for q in QUERIES) / len(QUERIES)
print(f"{'full':>4}{1.0:>20.4f}{full['recall@k']:>10.4f}"
      f"{full['nDCG@k']:>9.4f}{mrr(full_rankings):>8.4f}{1.0:>17.4f}"
      f"{full_distinct:>10.1f}")
print()
first90 = next((k for k, ve, *_ in rows if ve >= 0.90), None)
if first90:
    row = next(r for r in rows if r[0] == first90)
    print(f"k={first90} retains {row[1]:.1%} of the variance and "
          f"{row[2] / full['recall@k']:.1%} of the recall@5.")

print()
print("=" * 74)
print("3. Per query -- who paid for the aggregate")
print("=" * 74)
header = f"{'query':<10}{'full':>8}"
ks = [k for k, *_ in rows]
for k in ks:
    header += f"{'k=' + str(k):>8}"
print(header + "   (recall@5)")
for i, (q, rel) in enumerate(QUERIES.items(), start=1):
    line = f"{'Q' + str(i):<10}{recall_at_k(full_rankings[q], rel, K_EVAL):>8.3f}"
    for _, _, _, _, rankings in rows:
        line += f"{recall_at_k(rankings[q], rel, K_EVAL):>8.3f}"
    print(line)
print()
worst = None
for i, (q, rel) in enumerate(QUERIES.items(), start=1):
    base = recall_at_k(full_rankings[q], rel, K_EVAL)
    for k, ve, rec, nd, rankings in rows:
        if ve >= 0.80:
            drop = base - recall_at_k(rankings[q], rel, K_EVAL)
            if worst is None or drop > worst[1]:
                worst = (f"Q{i} at k={k}", drop, ve)
            break
if worst:
    print(f"Largest single-query loss at the first k retaining 80% of the "
          f"variance: {worst[0]}, {worst[1]:+.3f} recall@5")

print()
print("=" * 74)
print("4. Centred against uncentred, at the same k")
print("=" * 74)
print(f"{'k':>4}{'centred recall@5':>19}{'uncentred recall@5':>21}{'difference':>13}")
for k in (1, 2, 4, 8, 12):
    rc = sum(recall_at_k(rank_reduced(q, basis_c, True, k), rel, K_EVAL)
             for q, rel in QUERIES.items()) / len(QUERIES)
    ru = sum(recall_at_k(rank_reduced(q, basis_u, False, k), rel, K_EVAL)
             for q, rel in QUERIES.items()) / len(QUERIES)
    print(f"{k:>4}{rc:>19.4f}{ru:>21.4f}{rc - ru:>+13.4f}")

print()
print("=" * 74)
print("Predictions")
print("=" * 74)
for k, v in PREDICTIONS.items():
    print(f"  {k}: {v}")
