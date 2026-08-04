"""Recall@k, MRR and nDCG over the same two rankings.

    python ranking.py

No retrieval system here on purpose -- these are ranked lists and graded
judgments, and the metrics are arithmetic over them. Build the measurement
before the index, or you will not know whether the index helped.

Graded relevance: 2 = directly answers the query, 1 = related and useful,
absent = not relevant. Constructed fixture.
"""
import math
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# Chinese-language queries; documents are ids so nothing depends on printing CJK.
QUERIES = {
    "Q1 稀土出口管制":   {"D03": 2, "D07": 1, "D09": 1},
    "Q2 宁德时代 投资":   {"D02": 2, "D05": 1},
    "Q3 半导体 制裁":     {"D11": 2, "D01": 1, "D04": 1},
    "Q4 比亚迪 新工厂":   {"D06": 2, "D08": 1},
    "Q5 航运 运价 仲裁":  {"D10": 2, "D12": 1, "D03": 1},
    "Q6 光伏 产能 出清":  {},          # nothing relevant exists in the corpus
}

RANKINGS = {
    "system_a": {  # surfaces *a* relevant document immediately, the best one late
        "Q1 稀土出口管制":  ["D07","D01","D02","D04","D05","D06","D08","D03","D09","D10"],
        "Q2 宁德时代 投资":  ["D05","D01","D03","D04","D06","D07","D08","D09","D02","D10"],
        "Q3 半导体 制裁":    ["D01","D02","D03","D05","D06","D07","D08","D09","D04","D11"],
        "Q4 比亚迪 新工厂":  ["D08","D01","D02","D03","D04","D05","D07","D09","D10","D06"],
        "Q5 航运 运价 仲裁": ["D12","D01","D02","D04","D05","D06","D07","D03","D09","D10"],
        "Q6 光伏 产能 出清": ["D01","D02","D03","D04","D05","D06","D07","D08","D09","D10"],
    },
    "system_b": {  # nothing at rank 1, but the best document at rank 2
        "Q1 稀土出口管制":  ["D01","D03","D02","D04","D07","D05","D06","D08","D09","D10"],
        "Q2 宁德时代 投资":  ["D01","D02","D03","D04","D05","D06","D07","D08","D09","D10"],
        "Q3 半导体 制裁":    ["D02","D11","D03","D01","D05","D04","D06","D07","D08","D09"],
        "Q4 比亚迪 新工厂":  ["D01","D06","D02","D03","D08","D04","D05","D07","D09","D10"],
        "Q5 航运 运价 仲裁": ["D01","D10","D02","D03","D04","D05","D12","D06","D07","D08"],
        "Q6 光伏 产能 出清": ["D02","D01","D04","D03","D06","D05","D08","D07","D10","D09"],
    },
}


def recall_at_k(ranked, rel, k):
    if not rel:
        return None                      # undefined: nothing to recall
    return sum(1 for d in ranked[:k] if d in rel) / len(rel)


def precision_at_k(ranked, rel, k):
    return sum(1 for d in ranked[:k] if d in rel) / k


def reciprocal_rank(ranked, rel):
    if not rel:
        return None                      # undefined: no relevant document exists
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


def mean(values, missing_as=None):
    kept = [v if v is not None else missing_as for v in values]
    kept = [v for v in kept if v is not None]
    return sum(kept) / len(kept) if kept else float("nan")


print(f"{'query':<22}{'system':<11}{'R@3':>7}{'R@10':>7}{'P@3':>7}{'RR':>7}{'nDCG@10':>9}")
print("-" * 70)
rows = {s: {"r3": [], "r10": [], "p3": [], "rr": [], "nd": []} for s in RANKINGS}
for query, rel in QUERIES.items():
    for system, per_query in RANKINGS.items():
        ranked = per_query[query]
        r3, r10 = recall_at_k(ranked, rel, 3), recall_at_k(ranked, rel, 10)
        p3, rr = precision_at_k(ranked, rel, 3), reciprocal_rank(ranked, rel)
        nd = ndcg_at_k(ranked, rel, 10)
        rows[system]["r3"].append(r3); rows[system]["r10"].append(r10)
        rows[system]["p3"].append(p3); rows[system]["rr"].append(rr)
        rows[system]["nd"].append(nd)
        fmt = lambda v: f"{v:.3f}" if v is not None else "  --"
        print(f"{query:<22}{system:<11}{fmt(r3):>7}{fmt(r10):>7}"
              f"{fmt(p3):>7}{fmt(rr):>7}{fmt(nd):>9}")
    print()

print(f"{'AGGREGATE':<22}{'system':<11}{'R@3':>7}{'R@10':>7}{'P@3':>7}{'MRR':>7}{'nDCG@10':>9}")
print("-" * 70)
for system, v in rows.items():
    print(f"{'(Q6 excluded)':<22}{system:<11}{mean(v['r3']):>7.3f}{mean(v['r10']):>7.3f}"
          f"{mean(v['p3']):>7.3f}{mean(v['rr']):>7.3f}{mean(v['nd']):>9.3f}")
print()
for system, v in rows.items():
    print(f"{'(Q6 scored 0)':<22}{system:<11}{'':>7}{'':>7}{'':>7}"
          f"{mean(v['rr'], missing_as=0.0):>7.3f}{mean(v['nd'], missing_as=0.0):>9.3f}")
