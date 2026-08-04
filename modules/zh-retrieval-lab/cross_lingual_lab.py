"""Chinese queries against English documents, four ways.

    python cross_lingual_lab.py

Read ../cross-lingual-retrieval.md alongside this. The three warnings at the top
of bilingual.py apply to every number printed here.
"""
import math
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from bilingual import (DOCS_EN, DOC_VECTORS, QUERIES_ZH, en_vector, translate,
                       zh_vector)
from metrics import evaluate, reciprocal_rank
from retrievers import Index, rank

index = Index(analyzer="english", docs=DOCS_EN)


def cosine(a, b):
    if not a or not b:
        return 0.0
    dot = sum(v * b.get(t, 0.0) for t, v in a.items())
    na = math.sqrt(sum(v * v for v in a.values()))
    nb = math.sqrt(sum(v * v for v in b.values()))
    return dot / (na * nb) if na and nb else 0.0


def concept_scores(query):
    qv = zh_vector(query)
    return {d: c for d, v in DOC_VECTORS.items() if (c := cosine(qv, v)) > 0}


def rrf(ranked_lists, k=60):
    scores = defaultdict(float)
    for ranked in ranked_lists:
        for position, doc in enumerate(ranked, start=1):
            scores[doc] += 1 / (k + position)
    return [d for d, _ in sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))]


text = {q: q.split(" ", 1)[1] for q in QUERIES_ZH}

systems = {}
systems["A zh-lexical"] = {q: rank(index.bm25(text[q])) for q in QUERIES_ZH}
systems["B translate+BM25"] = {q: rank(index.bm25(translate(text[q]))) for q in QUERIES_ZH}
systems["C shared space"] = {q: rank(concept_scores(text[q])) for q in QUERIES_ZH}
systems["D RRF(B,C)"] = {q: rrf([systems["B translate+BM25"][q],
                                 systems["C shared space"][q]]) for q in QUERIES_ZH}

print("=== 1. Four systems, same queries, same judgments ===")
print(f"{'system':<20}{'recall@5':>10}{'MRR':>8}{'nDCG@5':>9}")
print("-" * 47)
for label, ranked in systems.items():
    s = evaluate(ranked, QUERIES_ZH, k=5)
    print(f"{label:<20}{s['recall@k']:>10.4f}{s['MRR']:>8.4f}{s['nDCG@k']:>9.4f}")
print()
print("  System A is the baseline nobody writes down: the query and the corpus")
print("  share no character. Its score is the size of the problem.")
print()

print("=== 2. Per-query reciprocal rank -- where each system earns its place ===")
cols = list(systems)
print(f"{'query':<20}" + "".join(f"{c:>19}" for c in cols))
for query, rel in QUERIES_ZH.items():
    row = [reciprocal_rank(systems[c][query], rel) for c in cols]
    print(f"{query:<20}" + "".join(f"{v:>19.2f}" for v in row))
print()

print("=== 3. What each query actually became ===")
for query in QUERIES_ZH:
    q = text[query]
    print(f"  {query}")
    print(f"    translated -> {translate(q)!r}")
    print(f"    concepts   -> {sorted(zh_vector(q)) or '(empty)'}")
print()

print("=== 4. The entity failure: Q1 ===")
q1 = text["Q1 中石化深圳投资"]
print(f"  concept vector for {q1!r}: {zh_vector(q1)}")
print(f"  translated: {translate(q1)!r}")
print(f"  B ranks: {systems['B translate+BM25']['Q1 中石化深圳投资'][:3]}")
print(f"  C ranks: {systems['C shared space']['Q1 中石化深圳投资'][:3]}")
print("  中石化 is an abbreviation the concept lexicon does not hold, and the")
print("  concept space has no way to say so -- it returns a vector, silently")
print("  shorter. The glossary holds the alias, so translation resolves the")
print("  entity outright. Named entities and abbreviations are where a lookup")
print("  table beats a learned space, and they are most of a news query.")
print()

print("=== 5. The vocabulary failure, in the other direction: Q6 ===")
q6 = text["Q6 芯片制裁"]
print(f"  document E07: {DOCS_EN['E07']}")
print(f"  translated query: {translate(q6)!r}")
print(f"  E07 concepts: {sorted(en_vector(DOCS_EN['E07']))}")
print(f"  B ranks: {systems['B translate+BM25']['Q6 芯片制裁'][:3] or '(nothing)'}")
print(f"  C ranks: {systems['C shared space']['Q6 芯片制裁'][:3]}")
print("  The translation is correct English and retrieves nothing, because E07")
print("  contains neither word: sanctions are expressed in this domain as")
print("  'entity list', and the chip is named SMIC rather than described. The")
print("  concept space maps both 制裁 and 'entity list' to SANCTION and crosses")
print("  the gap. This is what dense cross-lingual retrieval is actually for --")
print("  not translation, which is the easy half, but the synonymy that survives")
print("  it. Note also what Q3 shows in the table above: when the corpus happens")
print("  to use the word the translator chose, translation is fine and cheaper.")
print()

print("=== 6. The sense collision survives the language boundary: Q2 ===")
q2 = text["Q2 出口管制"]
print(f"  query concepts: {sorted(zh_vector(q2))}")
for doc in ("E03", "E14", "E15"):
    v = en_vector(DOCS_EN[doc])
    print(f"  {doc}  cos={cosine(zh_vector(q2), v):.4f}  concepts={sorted(v)}")
    print(f"       {DOCS_EN[doc]}")
print("  E15 is about air traffic control and export freight -- two unrelated")
print("  senses -- and it lands at rank 2, above E14, which is judged relevant.")
print("  WHY: E15 matches BOTH query concepts, in the wrong senses; E14 matches")
print("  one, in the right sense. Two wrong matches outscore one right match,")
print("  because a concept vector records that a concept is present and nothing")
print("  about which reading of it. Translating into a shared space does not")
print("  remove a sense collision; it relocates it, and removes your ability to")
print("  grep for the term that caused it. The monolingual version of exactly")
print("  this document is D15 in corpus.py -- the failure is not cross-lingual,")
print("  it is what cross-lingual retrieval fails to fix.")
print()

print("=== 7. Fusion, and the honest size of this result ===")
b = evaluate(systems["B translate+BM25"], QUERIES_ZH, k=5)
c = evaluate(systems["C shared space"], QUERIES_ZH, k=5)
d = evaluate(systems["D RRF(B,C)"], QUERIES_ZH, k=5)
print(f"  B nDCG@5 = {b['nDCG@k']:.4f}   C nDCG@5 = {c['nDCG@k']:.4f}   "
      f"RRF = {d['nDCG@k']:.4f}")
print("  Six queries. A difference of this size on six queries is a direction to")
print("  investigate, not a decision to ship -- see ../eval-set-sample-size.md")
print("  for the interval this set cannot beat. What the per-query table does")
print("  support is the structural claim: B fails Q6 outright and C fails Q1,")
print("  on DISJOINT causes -- vocabulary gap against missing entity -- and that")
print("  disjointness is the precondition under which fusion earns its second")
print("  index. Fusion is not free either: on Q2 it inherits B's error and drops")
print("  C's 1.00 to 0.50. It bought the aggregate by losing a query.")
