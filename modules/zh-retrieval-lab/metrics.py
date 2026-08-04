"""recall@k, MRR and nDCG@k. Same definitions as extraction-eval-sets/lab/ranking.py."""
import math


def recall_at_k(ranked, rel, k):
    return sum(1 for d in ranked[:k] if d in rel) / len(rel) if rel else None


def reciprocal_rank(ranked, rel):
    if not rel:
        return None
    for i, d in enumerate(ranked, start=1):
        if d in rel:
            return 1 / i
    return 0.0


def ndcg_at_k(ranked, rel, k):
    if not rel:
        return None
    dcg = sum((2 ** rel.get(d, 0) - 1) / math.log2(i + 1)
              for i, d in enumerate(ranked[:k], start=1))
    ideal = sorted(rel.values(), reverse=True)[:k]
    idcg = sum((2 ** g - 1) / math.log2(i + 1) for i, g in enumerate(ideal, start=1))
    return dcg / idcg if idcg else None


def evaluate(rankings, queries, k=5):
    """Mean recall@k, MRR and nDCG@k over all queries."""
    r, rr, nd = [], [], []
    for query, rel in queries.items():
        ranked = rankings[query]
        r.append(recall_at_k(ranked, rel, k))
        rr.append(reciprocal_rank(ranked, rel))
        nd.append(ndcg_at_k(ranked, rel, k))
    n = len(queries)
    return {"recall@k": sum(r) / n, "MRR": sum(rr) / n, "nDCG@k": sum(nd) / n}
