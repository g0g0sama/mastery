"""Inverted index, TF-IDF cosine, BM25 -- and when BM25's parameters matter.

    python bm25_lab.py
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from corpus import DOCS, QUERIES
from metrics import evaluate
from retrievers import Index, rank

ix = Index("bigram")

print("=== 1. The inverted index ===")
q = "出口管制"
terms = ix.analyze(q)
print(f"query {q!r} -> terms {terms}")
for t in terms:
    print(f"  postings[{t}] = {sorted(ix.postings.get(t, []))}  df={ix.df(t)}")
print(f"candidates scored: {len(ix.candidates(terms))} of {ix.N} documents")
print("That reduction is the entire point of the index. Everything after this is")
print("scoring; the index decides what never has to be scored at all.\n")

print("=== 2. TF-IDF cosine vs BM25, same analyzer, same queries ===")
for label, fn in (("tfidf_cosine", ix.tfidf_cosine), ("bm25", ix.bm25)):
    scores = evaluate({query: rank(fn(query)) for query in QUERIES}, QUERIES, k=5)
    print(f"  {label:<14}" + "  ".join(f"{k} {v:.4f}" for k, v in scores.items()))
print("Identical. Not a bug -- see part 3.\n")

print("=== 3. Why: this corpus does not exercise either parameter ===")
lengths = sorted(ix.length.values())
print(f"  document length in terms: min {lengths[0]}, median "
      f"{lengths[len(lengths) // 2]}, max {lengths[-1]}, avg {ix.avgdl:.1f}")
repeated = sum(1 for c in ix.terms.values() for v in c.values() if v > 1)
print(f"  term occurrences with tf > 1 across the whole corpus: {repeated}")
print("  b normalizes by length, and these lengths barely vary.")
print("  k1 saturates term frequency, and almost no term repeats.")
print("  Both parameters are acting on variance the corpus does not have.\n")

print("=== 4. A stress corpus that does exercise them ===")
BOILER = "本报讯记者从有关部门获悉根据最新发布的行业通报相关情况说明如下详见后文"
STRESS = {
    "S_short": "稀土出口管制",
    "S_long": BOILER + "稀土出口管制" + BOILER + BOILER,
    "S_spam": "稀土" * 12 + "价格",
    "S_other": "光伏组件价格下降",
}
sx = Index("bigram", docs=STRESS)
print(f"  lengths: " + ", ".join(f"{d}={sx.length[d]}" for d in STRESS))
print()
print(f"  {'params':<22}{'ranking for 稀土出口管制'}")
for label, kwargs in (("b=0.0  (no length norm)", {"b": 0.0}),
                      ("b=0.75 (default)", {"b": 0.75}),
                      ("b=1.0  (full length norm)", {"b": 1.0}),
                      ("k1=0.3 (fast saturation)", {"k1": 0.3}),
                      ("k1=1.2 (default)", {"k1": 1.2}),
                      ("k1=20  (near-linear tf)", {"k1": 20.0})):
    print(f"  {label:<22}{rank(sx.bm25('稀土出口管制', **kwargs))}")
print()
print("  tfidf_cosine          " + str(rank(sx.tfidf_cosine("稀土出口管制"))))
