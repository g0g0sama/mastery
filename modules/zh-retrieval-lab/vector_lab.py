"""Dot product against cosine, and where similarity misleads.

    python vector_lab.py

These are sparse TF-IDF vectors, not learned embeddings. The GEOMETRY transfers
exactly -- magnitude, normalization, and the angle/length decomposition are the
same in any inner-product space. The SEMANTICS do not: a real embedding places
paraphrases near each other and these vectors cannot. Do not read a conclusion
about embedding quality out of this file.
"""
import itertools
import math
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from analyzers import bigram
from corpus import DOCS


class Space:
    """TF-IDF vectors over one corpus. Queries MUST use the corpus idf."""

    def __init__(self, docs):
        self.docs = docs
        terms = {d: Counter(bigram(t)) for d, t in docs.items()}
        n = len(docs)
        df = Counter(t for c in terms.values() for t in c)
        self.idf = {t: math.log(n / v) for t, v in df.items()}
        self.vectors = {d: self._weight(c) for d, c in terms.items()}

    def _weight(self, counts):
        return {t: c * self.idf[t] for t, c in counts.items() if self.idf.get(t)}

    def vectorize(self, text):
        return self._weight(Counter(bigram(text)))

    def norm(self, v):
        return math.sqrt(sum(x * x for x in v.values())) or 1.0

    def dot(self, a, b):
        small, large = (a, b) if len(a) < len(b) else (b, a)
        return sum(x * large.get(t, 0.0) for t, x in small.items())

    def rank(self, query, cosine, k=4):
        qv = self.vectorize(query)
        denom = self.norm(qv) if cosine else 1.0
        scored = {d: self.dot(qv, v) / (denom * (self.norm(v) if cosine else 1.0))
                  for d, v in self.vectors.items()}
        scored = {d: s for d, s in scored.items() if s > 0}
        return sorted(scored.items(), key=lambda kv: (-kv[1], kv[0]))[:k]


print("=== 1. The cleanest case: the same document, three times over ===")
padded = dict(DOCS)
padded["D03_x3"] = DOCS["D03"] * 3       # identical direction, three times the length
space = Space(padded)
query = "稀土出口管制"
for label, cosine in (("dot   ", False), ("cosine", True)):
    rows = space.rank(query, cosine)
    print(f"  {label} -> " + ", ".join(f"{d}={s:.3f}" for d, s in rows))
print("  D03_x3 says nothing D03 does not. Under the dot product it wins by")
print("  a factor of three. Under cosine the two are within 0.01 of each other,")
print("  because tripling a vector changes its length and not its direction.")
print("  (Not exactly equal: concatenating the text three times creates two")
print("  junction bigrams at the seams, so it is very nearly, not perfectly,")
print("  a scalar multiple. The residue is the size of that artifact.)")
print()

print("=== 2. Why: dot = |q| * |d| * cos(theta) ===")
qv = space.vectorize(query)
for doc in ("D03", "D03_x3"):
    v = space.vectors[doc]
    d = space.dot(qv, v)
    print(f"  {doc:<8} |d| = {space.norm(v):>6.2f}   dot = {d:>6.3f}   "
          f"cos = {d / (space.norm(qv) * space.norm(v)):.4f}")
print("  Unnormalized similarity scores angle and magnitude together, so length")
print("  leaks into relevance. Cosine divides |d| out and compares direction only.")
print("  This is invisible until documents differ in length -- the same")
print("  precondition as BM25's b parameter, arrived at from the geometry side.")
print()

print("=== 3. The most similar document PAIRS in the corpus ===")
base = Space(DOCS)
pairs = []
for a, b in itertools.combinations(DOCS, 2):
    va, vb = base.vectors[a], base.vectors[b]
    pairs.append((base.dot(va, vb) / (base.norm(va) * base.norm(vb)), a, b))
pairs.sort(reverse=True)
for cos, a, b in pairs[:4]:
    print(f"  cos = {cos:.4f}   {a} / {b}")
    print(f"    {a}: {DOCS[a]}")
    print(f"    {b}: {DOCS[b]}")
print()
print("  Note the absolute values. Even the nearest pair in this corpus scores")
print("  well under 0.2, because short distinct sentences share few bigrams.")
print("  A similarity threshold tuned on one corpus is meaningless on another --")
print("  there is no such thing as 'cosine above 0.8 means related'.")
print("  And the pairs that do rank highest are lexical accidents: unrelated")
print("  senses of a shared word, or two different companies sharing a name")
print("  prefix. A learned embedding removes some of these and adds its own --")
print("  it will place a fluent denial next to the claim it denies. Similarity")
print("  is a hypothesis about relevance, never a judgment of it.")
