"""Fixed-size against structure-aware chunking, measured on answer recall.

    python chunk_lab.py
"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from documents import ANSWERS, LONG_DOCS
from metrics import reciprocal_rank
from retrievers import Index, rank

SECTION = re.compile(r"(【[^】]*】)")


def fixed(text, size=60, overlap=0):
    step = size - overlap
    return [text[i:i + size] for i in range(0, len(text), step) if text[i:i + size]]


def structure(text, with_heading=False):
    """Split on section headings, then on sentence boundaries."""
    parts, heading = [], ""
    for piece in SECTION.split(text):
        if not piece:
            continue
        if SECTION.fullmatch(piece):
            heading = piece
            continue
        for sentence in filter(None, piece.split("。")):
            parts.append((heading + sentence if with_heading else sentence) + "。")
    return parts


STRATEGIES = {
    "fixed-60, no overlap": lambda t: fixed(t, 60, 0),
    "fixed-60, overlap 20": lambda t: fixed(t, 60, 20),
    "structure-aware": lambda t: structure(t, with_heading=False),
    "structure + heading": lambda t: structure(t, with_heading=True),
}


def build(strategy):
    chunks = {}
    for doc, text in LONG_DOCS.items():
        for i, chunk in enumerate(strategy(text)):
            chunks[f"{doc}#{i:02d}"] = chunk
    return chunks


print(f"{'strategy':<24}{'chunks':>8}{'avg len':>9}{'answer R@1':>12}"
      f"{'R@3':>7}{'MRR':>7}")
print("-" * 67)
detail = {}
for label, strategy in STRATEGIES.items():
    chunks = build(strategy)
    ix = Index("bigram", docs=chunks)
    r1 = r3 = 0
    rrs = []
    per_query = {}
    for query, (_doc, answer) in ANSWERS.items():
        ranked = rank(ix.bm25(query))
        # A chunk is relevant iff it contains the answer span.
        rel = {cid: 2 for cid, text in chunks.items() if answer in text}
        hit1 = bool(ranked[:1]) and ranked[0] in rel
        hit3 = any(c in rel for c in ranked[:3])
        r1 += hit1
        r3 += hit3
        rrs.append(reciprocal_rank(ranked, rel) if rel else 0.0)
        per_query[query] = (bool(rel), hit1, hit3)
    detail[label] = per_query
    n = len(ANSWERS)
    avg = sum(len(c) for c in chunks.values()) / len(chunks)
    print(f"{label:<24}{len(chunks):>8}{avg:>9.1f}{r1 / n:>12.4f}"
          f"{r3 / n:>7.4f}{sum(rrs) / n:>7.4f}")

print()
print("SPLIT means the answer span exists in no chunk -- it was cut across a")
print("boundary and is unretrievable at any k, by any scorer. 'ok' means the")
print("span survived; '+hit' means that chunk was also ranked first.")
SHORT = {"fixed-60, no overlap": "fixed", "fixed-60, overlap 20": "overlap",
         "structure-aware": "structure", "structure + heading": "str+head"}
print(f"{'query':<30}" + "".join(f"{SHORT[l]:>12}" for l in STRATEGIES))
print("-" * (30 + 12 * len(STRATEGIES)))
for query in ANSWERS:
    cells = []
    for label in STRATEGIES:
        intact, hit1, _ = detail[label][query]
        cells.append(("SPLIT" if not intact else ("ok +hit" if hit1 else "ok")))
    print(f"{query:<30}" + "".join(f"{c:>12}" for c in cells))
