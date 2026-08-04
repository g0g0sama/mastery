"""Two-stage retrieval: a cheap ranker over everything, an expensive one over few.

    python rerank_lab.py

The reranker here is a term-proximity scorer, not a cross-encoder. It stands in
for one structurally: it reads the document text rather than a posting list, it
costs time proportional to document length, and it can see something the first
stage cannot -- where the matched terms sit relative to each other. A real
cross-encoder is the same shape and three orders of magnitude more expensive,
which only sharpens every trade-off below.
"""
import math
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analyzers import bigram
from corpus import DOCS, QUERIES
from metrics import evaluate, ndcg_at_k, recall_at_k
from retrievers import Index, rank

# Stage 1 is the UNIGRAM index on purpose. The job of a first stage is recall,
# not precision -- it is allowed to be sloppy because a second stage will clean
# up, and choosing the precise analyzer here would leave the reranker nothing to
# do while capping what it can ever reach. ../chinese-segmentation.md has the
# per-query numbers behind that choice.
stage1 = Index("unigram")

# The reranker has its OWN features and therefore its own statistics. Scoring
# bigram spans against unigram idf silently yields zero for every term, which
# reorders the candidates alphabetically and looks like a working reranker on
# the aggregate -- the first bug this file had, and worth stating out loud.
_features = Index("bigram")
IDF = {t: math.log(1 + (_features.N - _features.df(t) + 0.5) / (_features.df(t) + 0.5))
       for t in _features.postings}


def min_window(positions):
    """Smallest character span containing one occurrence of every matched term.

    The feature stage 1 structurally cannot compute: an inverted index stores
    which documents contain a term, not where, and a bag-of-terms score is
    identical for a document that says the terms together and one that says
    them in unrelated sentences.
    """
    events = sorted((p, t) for t, ps in positions.items() for p in ps)
    need, have, best, left = len(positions), {}, math.inf, 0
    for right, (pos, term) in enumerate(events):
        have[term] = have.get(term, 0) + 1
        while len(have) == need:
            best = min(best, pos - events[left][0] + 2)
            lt = events[left][1]
            have[lt] -= 1
            if not have[lt]:
                del have[lt]
            left += 1
    return best


def rerank_score(query, text):
    terms = set(bigram(query))
    positions = {t: [i for i in range(len(text) - 1) if text[i:i + 2] == t]
                 for t in terms}
    positions = {t: p for t, p in positions.items() if p}
    if not positions:
        return 0.0
    base = sum(IDF.get(t, 0.0) for t in positions)
    if len(positions) < 2:
        return base
    span = min_window(positions)
    tight = 2 * len(positions)               # terms packed adjacently
    return base * (1 + tight / span)


def two_stage(query, depth):
    """Stage 2 REPLACES the stage-1 order within the candidate window."""
    full = rank(stage1.bm25(query))
    candidates = full[:depth]
    scored = {d: rerank_score(query, DOCS[d]) for d in candidates}
    reordered = sorted(candidates, key=lambda d: (-scored[d], d))
    return reordered + full[depth:]


def fused_stage(query, depth, k=60):
    """Stage 2 is fused with stage 1 by rank, so neither can overrule alone."""
    full = rank(stage1.bm25(query))
    candidates = full[:depth]
    scored = {d: rerank_score(query, DOCS[d]) for d in candidates}
    by_rerank = sorted(candidates, key=lambda d: (-scored[d], d))
    points = {d: 1 / (k + i) for i, d in enumerate(candidates, start=1)}
    for i, d in enumerate(by_rerank, start=1):
        points[d] += 1 / (k + i)
    ordered = sorted(candidates, key=lambda d: (-points[d], d))
    return ordered + full[depth:]


text = {q: q.split(" ", 1)[1] for q in QUERIES}
baseline = {q: rank(stage1.bm25(text[q])) for q in QUERIES}

print("=== 1. Stage 1 is a ceiling, not a starting point ===")
print("  Recall@depth of the BM25 candidate set. A reranker cannot retrieve;")
print("  it can only reorder what stage 1 already handed it.")
print(f"  {'depth':<8}{'mean recall@depth':>20}")
for depth in (1, 3, 5, 10, 17):
    r = sum(recall_at_k(baseline[q], rel, depth) for q, rel in QUERIES.items())
    print(f"  {depth:<8}{r / len(QUERIES):>20.4f}")
print("  Whatever the ceiling is at your chosen depth, that is the best nDCG a")
print("  perfect reranker could reach. Measure it before buying a reranker.")
print()

print("=== 2. nDCG@5 and cost against rerank depth ===")
REPS = 200
print(f"  {'system':<22}{'nDCG@5':>9}{'MRR':>8}{'ms/query':>11}{'gain/ms':>10}")
print("  " + "-" * 60)

start = time.perf_counter()
for _ in range(REPS):
    for q in QUERIES:
        rank(stage1.bm25(text[q]))
base_ms = (time.perf_counter() - start) * 1000 / (REPS * len(QUERIES))
base_score = evaluate(baseline, QUERIES, k=5)
print(f"  {'BM25 only':<22}{base_score['nDCG@k']:>9.4f}"
      f"{base_score['MRR']:>8.4f}{base_ms:>11.3f}{'--':>10}")

for depth in (3, 5, 10, 17):
    ranked = {q: two_stage(text[q], depth) for q in QUERIES}
    start = time.perf_counter()
    for _ in range(REPS):
        for q in QUERIES:
            two_stage(text[q], depth)
    ms = (time.perf_counter() - start) * 1000 / (REPS * len(QUERIES))
    s = evaluate(ranked, QUERIES, k=5)
    added = ms - base_ms
    gain = (s["nDCG@k"] - base_score["nDCG@k"]) / added if added > 0 else 0.0
    print(f"  {'+ rerank top-' + str(depth):<22}{s['nDCG@k']:>9.4f}"
          f"{s['MRR']:>8.4f}{ms:>11.3f}{gain:>10.4f}")
print()
print("  The rightmost column is the map's evidence line for this row: nDCG gain")
print("  per added millisecond. Note that it goes NEGATIVE past depth 3. Deeper")
print("  reranking is not a weaker version of the same win -- it is a different")
print("  outcome, because every extra candidate is another chance for the second")
print("  stage to promote something the first stage had correctly buried. Cost")
print("  rises linearly with depth; quality does not rise with it at all.")
print()

print("=== 3. Per-query, so the aggregate cannot hide the mechanism ===")
depths = (3, 5, 10)
runs = {d: {q: two_stage(text[q], d) for q in QUERIES} for d in depths}
print(f"  {'query':<20}{'BM25':>8}" + "".join(f"{'top-' + str(d):>8}" for d in depths))
for query, rel in QUERIES.items():
    row = [ndcg_at_k(baseline[query], rel, 5)]
    row += [ndcg_at_k(runs[d][query], rel, 5) for d in depths]
    print(f"  {query:<20}" + "".join(f"{v:>8.3f}" for v in row))
print()

print("=== 4. The query the reranker fixes, and the one it cannot touch ===")
q2 = "出口管制"
print(f"  Q2 {q2}: BM25 -> {baseline['Q2 出口管制'][:3]}, "
      f"reranked -> {runs[5]['Q2 出口管制'][:3]}")
for doc in ("D03", "D15"):
    print(f"    {doc} bm25={stage1.bm25(q2).get(doc, 0):.3f} "
          f"rerank={rerank_score(q2, DOCS[doc]):.3f}  {DOCS[doc]}")
print("    D15 uses 管制 for air traffic control and 出口 for freight, far apart")
print("    in the sentence. Bag-of-terms scores it as a match; a scorer that can")
print("    see position does not. This is the class of error reranking exists for.")
print()
q6 = "芯片制裁"
print(f"  Q6 {q6}: BM25 -> {baseline['Q6 芯片制裁'][:3]}, "
      f"reranked@5 -> {runs[5]['Q6 芯片制裁'][:3]}")
print(f"    D07 bm25={stage1.bm25(q6).get('D07', 0):.3f} "
      f"rerank={rerank_score(q6, DOCS['D07']):.3f}  {DOCS['D07']}")
print("    芯片 does not occur in D07; 芯 does, inside 中芯国际. Stage 1 matched")
print("    on that single character and was right. The reranker's features are")
print("    bigrams, finds nothing, scores exactly 0.000, and a relevant document")
print("    at rank 1 falls below noise. nDCG@5 on this query: 1.000 -> 0.631.")
print("    A reranker that REPLACES the first-stage score throws away the only")
print("    evidence it has whenever its own features miss.")
print()

print("=== 5. The fix: fuse the two stages instead of overwriting one ===")
print(f"  {'system':<26}{'nDCG@5':>9}{'MRR':>8}")
print("  " + "-" * 43)
print(f"  {'BM25 only':<26}{base_score['nDCG@k']:>9.4f}{base_score['MRR']:>8.4f}")
for depth in (5, 10):
    replaced = evaluate({q: two_stage(text[q], depth) for q in QUERIES}, QUERIES, k=5)
    fused = evaluate({q: fused_stage(text[q], depth) for q in QUERIES}, QUERIES, k=5)
    print(f"  {'replace @' + str(depth):<26}{replaced['nDCG@k']:>9.4f}"
          f"{replaced['MRR']:>8.4f}")
    print(f"  {'RRF(stage1,rerank) @' + str(depth):<26}{fused['nDCG@k']:>9.4f}"
          f"{fused['MRR']:>8.4f}")
print()
print("  Rank fusion between the two stages keeps Q2's fix and stops Q6's")
print("  collapse, because a document has to be bad under BOTH scorers to fall.")
print("  The same argument as ../hybrid-retrieval-fusion.md, one layer later:")
print("  rank-level because a BM25 score and a reranker score share no scale.")
print()
d04 = rerank_score("动力电池供应", DOCS["D04"])
print("  Reranking is a precision instrument in any case. Q3 is retrieved only")
print("  because unigram matched incidental characters; the reranker scores the")
print(f"  target D04 at {d04:.3f}, and it holds rank 1 on an alphabetical")
print("  tie-break, which is luck rather than ranking. A real recall gap needs a")
print("  different retriever -- ../cross-lingual-retrieval.md and")
print("  ../hybrid-retrieval-fusion.md -- never a better second stage.")
