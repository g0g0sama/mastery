"""Reciprocal rank fusion over analyzers, and whether it beats its parents.

    python fusion_lab.py
"""
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analyzers import ANALYZERS
from corpus import QUERIES
from metrics import evaluate, reciprocal_rank
from retrievers import Index, rank

RRF_K = 60

indexes = {name: Index(name) for name in ANALYZERS}
parents = {name: {q: rank(ix.bm25(q)) for q in QUERIES} for name, ix in indexes.items()}


def rrf(ranked_lists, k=RRF_K):
    """Rank-based fusion: only positions matter, never the raw scores."""
    scores = defaultdict(float)
    for ranked in ranked_lists:
        for position, doc in enumerate(ranked, start=1):
            scores[doc] += 1 / (k + position)
    return [d for d, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


def minmax_fusion(score_dicts):
    """Score-based fusion. Requires the scores to be comparable, and they are not."""
    scores = defaultdict(float)
    for raw in score_dicts:
        if not raw:
            continue
        lo, hi = min(raw.values()), max(raw.values())
        span = (hi - lo) or 1.0
        for doc, value in raw.items():
            scores[doc] += (value - lo) / span
    return [d for d, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


combos = {
    "unigram": [parents["unigram"]],
    "bigram": [parents["bigram"]],
    "dictmatch": [parents["dictmatch"]],
    "RRF uni+bi": [parents["unigram"], parents["bigram"]],
    "RRF uni+bi+dict": [parents["unigram"], parents["bigram"], parents["dictmatch"]],
    "RRF bi+dict": [parents["bigram"], parents["dictmatch"]],
}

print(f"{'system':<20}{'recall@5':>10}{'MRR':>8}{'nDCG@5':>9}")
print("-" * 47)
results = {}
for label, sources in combos.items():
    ranked = ({q: sources[0][q] for q in QUERIES} if len(sources) == 1
              else {q: rrf([s[q] for s in sources]) for q in QUERIES})
    results[label] = ranked
    s = evaluate(ranked, QUERIES, k=5)
    print(f"{label:<20}{s['recall@k']:>10.4f}{s['MRR']:>8.4f}{s['nDCG@k']:>9.4f}")

print()
print("Per-query reciprocal rank. Watch Q2, Q3 and Q6.")
cols = ("unigram", "bigram", "dictmatch", "RRF uni+bi", "RRF uni+bi+dict")
print(f"{'query':<20}" + "".join(f"{c:>17}" for c in cols))
for query, rel in QUERIES.items():
    row = [reciprocal_rank(results[c][query], rel) for c in cols]
    print(f"{query:<20}" + "".join(f"{v:>17.2f}" for v in row))
print()
print("  Q2: fusion inherits bigram's fix for the cross-sense false match.")
print("  Q6: fusion keeps unigram's only-retriever win.")
print("  Q3: adding dictmatch as a third parent COSTS the fusion this query --")
print("      its wrong answer outvotes unigram's right one. More parents is not")
print("      better; a parent that is wrong in a correlated way is a liability.")

print()
print("=== Rank fusion vs score fusion on one query ===")
query = "Q2 出口管制"
raw = [indexes[n].bm25(query.split(" ", 1)[1]) for n in ANALYZERS]
for name, scores in zip(ANALYZERS, raw):
    top = sorted(scores.items(), key=lambda kv: -kv[1])[:3]
    print(f"  {name:<10} raw scores: " + ", ".join(f"{d}={v:.3f}" for d, v in top))
print(f"  RRF    -> {rrf([parents[n][query] for n in ANALYZERS])[:3]}")
print(f"  minmax -> {minmax_fusion(raw)[:3]}")
print("  Here the two agree. The reason to default to RRF anyway is that it never")
print("  reads a score: BM25 is unbounded and analyzer-dependent, and a dense")
print("  retriever's cosine lives in [-1,1]. Min-max rescues that only while every")
print("  parent's score distribution stays stable, which is not a property you")
print("  control. This corpus does not exhibit that failure -- do not conclude")
print("  from it that score fusion is safe.")
