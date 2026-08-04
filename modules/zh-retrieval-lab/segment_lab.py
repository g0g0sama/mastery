"""Three analyzers over the same corpus, queries and judgments.

    python segment_lab.py

Chinese has no spaces, so the analyzer decides what can be matched at all. This
is the single largest lever in Chinese lexical retrieval and it is usually set
by a default nobody measured.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analyzers import ANALYZERS
from corpus import DOCS, QUERIES
from metrics import evaluate, ndcg_at_k, recall_at_k, reciprocal_rank
from retrievers import Index, rank

indexes = {name: Index(name) for name in ANALYZERS}
rankings = {name: {q: rank(ix.bm25(q)) for q in QUERIES} for name, ix in indexes.items()}

print("=== Aggregate, BM25 over each analyzer, k=5 ===")
print(f"{'analyzer':<12}{'recall@5':>10}{'MRR':>8}{'nDCG@5':>9}")
for name in ANALYZERS:
    s = evaluate(rankings[name], QUERIES, k=5)
    print(f"{name:<12}{s['recall@k']:>10.4f}{s['MRR']:>8.4f}{s['nDCG@k']:>9.4f}")
print("\nThe crudest analyzer wins every column. Do not stop reading here.\n")

print("=== Per query: reciprocal rank, and the top result ===")
print(f"{'query':<20}" + "".join(f"{n:>26}" for n in ANALYZERS))
for query, rel in QUERIES.items():
    cells = []
    for name in ANALYZERS:
        ranked = rankings[name][query]
        rr = reciprocal_rank(ranked, rel)
        top = ranked[0] if ranked else "--"
        mark = "" if top in rel else " X"
        cells.append(f"RR {rr:.2f}  top {top}{mark:<2}")
    print(f"{query:<20}" + "".join(f"{c:>26}" for c in cells))
print("  X marks a top result that is not relevant.\n")

print("=== Why unigram won -- the matched terms ===")
for query, doc in (("Q3 动力电池供应", "D04"), ("Q6 芯片制裁", "D07")):
    print(f"  {query}  ->  {doc}  {DOCS[doc]}")
    for name, ix in indexes.items():
        overlap = sorted(set(ix.analyze(query)) & set(ix.terms[doc]))
        print(f"    {name:<10} matched on {overlap if overlap else 'nothing'}")
print("  Single characters. 供 out of 供货协议, 芯 out of 中芯国际. Two of the")
print("  six queries were won by a character collision, not by retrieval.\n")

print("=== Where each analyzer fails ===")
print(f"  Q2 出口管制   unigram top = {rankings['unigram']['Q2 出口管制'][0]} "
      f"({DOCS[rankings['unigram']['Q2 出口管制'][0]]})")
print("    D15 uses 管制 to mean air traffic control and 出口 to mean export")
print("    freight. Unigram cannot see that; bigram and dictmatch rank D03 first.")
print(f"  Q1 中石化...  dictmatch top = {rankings['dictmatch']['Q1 中石化深圳投资'][0]}"
      f"  (should be D01)")
print(f"    dictmatch segments the query as "
      f"{ANALYZERS['dictmatch']('中石化深圳投资')}")
print("    中石化 is not in the dictionary, so the abbreviation shatters into")
print("    characters and 投资 pulls an unrelated investment story to the top.")
print(f"  Q5 稀土永磁   dictmatch segments as {ANALYZERS['dictmatch']('稀土永磁')}")
print("    The out-of-vocabulary compound is exactly where your domain lives.")
