"""Query rewriting: which rewrites help, which hurt, and how you tell.

    python rewrite_lab.py

Rewrites are applied to the QUERY only. The index, the analyzer and the scorer
are untouched, so every difference below is attributable to the rewrite.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from corpus import DOCS, QUERIES
from metrics import evaluate, reciprocal_rank
from retrievers import Index, rank

# Hand-built, as a first rewriter always is. Each entry is a hypothesis.
EXPANSIONS = {
    "中石化": "中国石化",          # abbreviation -> registered short name
    "动力电池": "电池供货",         # paraphrase -> vocabulary the corpus uses
    "芯片": "芯片半导体中芯",       # near-synonyms, deliberately over-broad
    "减产": "减产停产",            # related-sense expansion
    # Domain-adjacent trade vocabulary. Plausible, and it is the one that hurts.
    "出口": "出口货运贸易",
}


def expand(query):
    """Append the expansion, keeping the original terms. Never replace."""
    added = [v for k, v in EXPANSIONS.items() if k in query]
    return query + "".join(added) if added else query


ix = Index("bigram")
variants = {
    "bigram raw": lambda q: q,
    "bigram + rewrite": expand,
}

print("Rewrites applied:")
for query in QUERIES:
    text = query.split(" ", 1)[1]
    rewritten = expand(text)
    if rewritten != text:
        print(f"  {text}  ->  {rewritten}")
print()

rankings = {}
for label, fn in variants.items():
    rankings[label] = {q: rank(ix.bm25(fn(q.split(" ", 1)[1]))) for q in QUERIES}

print(f"{'system':<20}{'recall@5':>10}{'MRR':>8}{'nDCG@5':>9}")
print("-" * 47)
for label in variants:
    s = evaluate(rankings[label], QUERIES, k=5)
    print(f"{label:<20}{s['recall@k']:>10.4f}{s['MRR']:>8.4f}{s['nDCG@k']:>9.4f}")
print()

print(f"{'query':<20}{'raw RR':>9}{'rewritten RR':>15}{'verdict':>12}")
print("-" * 56)
for query, rel in QUERIES.items():
    before = reciprocal_rank(rankings["bigram raw"][query], rel)
    after = reciprocal_rank(rankings["bigram + rewrite"][query], rel)
    verdict = "helped" if after > before else ("HURT" if after < before else "--")
    print(f"{query:<20}{before:>9.2f}{after:>15.2f}{verdict:>12}")
print()

print("Where it hurt, and why:")
for query, rel in QUERIES.items():
    before = reciprocal_rank(rankings["bigram raw"][query], rel)
    after = reciprocal_rank(rankings["bigram + rewrite"][query], rel)
    if after < before:
        text = query.split(" ", 1)[1]
        top = rankings["bigram + rewrite"][query][0]
        print(f"  {query}: {text} -> {expand(text)}")
        print(f"    now ranks {top} first: {DOCS[top]}")
        print(f"    the added terms matched a document the original query could not reach")
