"""Groundedness: the gate chain, the denominator, the unit, and the retriever.

    python grounding_lab.py

Two systems emit the SAME twelve claims and differ only in what they cite.
Four questions, in the order a pipeline can afford to ask them:

  1. Does the citation resolve?   -- string containment, free, no labels
  2. Does the span support it?    -- needs a judgment; no string metric separates
  3. Over what denominator, and in what unit, do we report the rate?
  4. Was the supporting span even retrieved?
"""
import re
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analyzers import bigram
from citations import CLAIMS, QUERIES, SYSTEMS
from documents import LONG_DOCS
from retrievers import Index, rank

SECTION = re.compile(r"(【[^】]*】)")
ATOMS = [(c, a) for c in CLAIMS for a in c["atoms"]]
SUPPORTABLE = [(c, a) for c, a in ATOMS if a["evidence"] is not None]


def resolves(doc, quote):
    """Gate 1. A quote that is not in the document is a fabricated citation."""
    return quote in LONG_DOCS[doc]


def covered(claim, atom, quotes):
    """Gate 2, in the fixture's stipulated form: the atom's supporting span lies
    inside a quote that resolves. Real gate 2 is entailment and needs a judge --
    see ../rubric-graders.md for what that costs and where it fails."""
    if atom["evidence"] is None:
        return False
    return any(resolves(claim["doc"], q) and atom["evidence"] in q for q in quotes)


def grade(cites):
    """Per claim: (resolving quotes, atoms covered, atoms total)."""
    out = {}
    for claim in CLAIMS:
        quotes = cites.get(claim["id"], [])
        ok = [q for q in quotes if resolves(claim["doc"], q)]
        hits = sum(covered(claim, a, quotes) for a in claim["atoms"])
        out[claim["id"]] = (quotes, ok, hits, len(claim["atoms"]))
    return out


# ---------------------------------------------------------------- part 1
print("PART 1 -- gate 1: does the citation resolve? (free, no labels)")
print(f"{'system':<24}{'cited':>7}{'quotes':>8}{'resolve':>9}{'rate':>8}   fabricated")
print("-" * 72)
graded = {name: grade(cites) for name, cites in SYSTEMS.items()}
for name, g in graded.items():
    quotes = sum(len(q) for q, _, _, _ in g.values())
    ok = sum(len(o) for _, o, _, _ in g.values())
    bad = [cid for cid, (q, o, _, _) in g.items() if len(o) < len(q)]
    cited = sum(1 for q, _, _, _ in g.values() if q)
    print(f"{name:<24}{cited:>7}{quotes:>8}{ok:>9}{ok / quotes:>8.4f}   {' '.join(bad) or '-'}")

# ---------------------------------------------------------------- part 2
print()
print("PART 2 -- gate 2: can a string metric stand in for the judge?")
print("Bigram Jaccard between the claim and its cited span, system A, resolving")
print("citations only. 'support' is gold: every atom of the claim covered.")
print()
print(f"{'claim':<8}{'jaccard':>9}{'support':>10}   note")
print("-" * 58)
NOTE = {"K01": "second date not in the quote", "K04": "quote unrelated to the claim",
        "K06": "capacity atom not in the quote", "K08": "one digit changed",
        "K11": "second finding not in the quote", "K12": "hedge dropped"}
rows = []
for claim in CLAIMS:
    quotes, ok, hits, total = graded["A cite-everything"][claim["id"]]
    if not ok or len(ok) < len(quotes):
        continue
    a, b = set(bigram(claim["text"])), set(bigram("".join(ok)))
    j = len(a & b) / len(a | b)
    rows.append((j, claim["id"], hits == total))
for j, cid, full in sorted(rows, reverse=True):
    print(f"{cid:<8}{j:>9.4f}{('yes' if full else 'NO'):>10}   {NOTE.get(cid, '')}")
lo = min(j for j, _, full in rows if full)
hi = max(j for j, _, full in rows if not full)
print()
print(f"lowest supported = {lo:.4f}   highest unsupported = {hi:.4f}   "
      f"separable = {hi < lo}")

# ---------------------------------------------------------------- part 3
print()
print("PART 3 -- the denominator and the unit. Same citations, five numbers.")
print()
print(f"{'':<34}{'A cite-everything':>19}{'B conservative':>17}")
print("-" * 70)
stats = {}
for name, g in graded.items():
    stats[name] = dict(
        cited=sum(1 for q, _, _, _ in g.values() if q),
        resolvable=sum(1 for _, o, _, _ in g.values() if o),
        full=sum(1 for _, _, h, t in g.values() if h == t),
        partial=sum(1 for _, _, h, t in g.values() if 0 < h < t),
        any_hit=sum(1 for _, _, h, _ in g.values() if h),
        atoms=sum(h for _, _, h, _ in g.values()),
    )
A, B = stats["A cite-everything"], stats["B cite-conservatively"]


def row(label, fa, fb, fmt="{:>19.4f}{:>17.4f}"):
    print(f"{label:<34}" + fmt.format(fa, fb))


row("claims emitted", len(CLAIMS), len(CLAIMS), "{:>19d}{:>17d}")
row("claims cited", A["cited"], B["cited"], "{:>19d}{:>17d}")
row("claims whose citation resolves", A["resolvable"], B["resolvable"], "{:>19d}{:>17d}")
print()
row("supported / claims that resolve", A["any_hit"] / A["resolvable"],
    B["any_hit"] / B["resolvable"])
row("supported / cited claim", A["any_hit"] / A["cited"], B["any_hit"] / B["cited"])
row("supported / ALL claims", A["any_hit"] / len(CLAIMS), B["any_hit"] / len(CLAIMS))
row("FULLY supported / ALL claims", A["full"] / len(CLAIMS), B["full"] / len(CLAIMS))
row("atoms covered / ALL atoms", A["atoms"] / len(ATOMS), B["atoms"] / len(ATOMS))
print()
print(f"partially supported claims (counted as supported at claim level): "
      f"A={A['partial']}  B={B['partial']}")

# ---------------------------------------------------------------- part 4
print()
print("PART 4 -- grounded in the DOCUMENT is not grounded in what was RETRIEVED.")


def structure(text):
    parts, heading = [], ""
    for piece in SECTION.split(text):
        if not piece:
            continue
        if SECTION.fullmatch(piece):
            heading = piece
            continue
        for sentence in filter(None, piece.split("。")):
            parts.append(heading + sentence + "。")
    return parts


chunks = {f"{d}#{i:02d}": c for d, t in LONG_DOCS.items()
          for i, c in enumerate(structure(t))}
ix = Index("bigram", docs=chunks)
print(f"{len(chunks)} chunks, structure-aware, one sentence each with its heading.")
print()
print(f"{'k':>3}{'atoms in a retrieved chunk':>29}{'rate':>8}   atoms lost")
print("-" * 72)
for k in (1, 3, 5, 10):
    retrieved = {}
    for doc, query in QUERIES.items():
        top = rank(ix.bm25(query), k)
        retrieved[doc] = [chunks[c] for c in top]
    hit, lost = 0, []
    for claim, atom in SUPPORTABLE:
        if any(atom["evidence"] in c for c in retrieved[claim["doc"]]):
            hit += 1
        else:
            lost.append(atom["id"])
    print(f"{k:>3}{hit:>29}{hit / len(SUPPORTABLE):>8.4f}   {' '.join(lost) or '-'}")
print()
print("Why k stops mattering: BM25 can only score chunks the inverted index")
print("offers as candidates, and a chunk sharing no term with the query is not")
print("one. Raising k past the candidate count changes nothing.")
print(f"{'query':<10}{'candidate chunks':>18}{'of':>4}{'total':>7}")
for doc, query in QUERIES.items():
    print(f"{doc:<10}{len(ix.bm25(query)):>18}{'of':>4}{len(chunks):>7}")
print()
print(f"ceiling: {len(SUPPORTABLE)} of {len(ATOMS)} atoms are supportable at all.")
print("An atom whose span is not retrieved cannot be grounded by any generator,")
print("however well it cites. Groundedness is bounded above by retrieval.")
