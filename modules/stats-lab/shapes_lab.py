"""Shapes: predicting them, and the bugs that survive because they matched.

    python shapes_lab.py

Map row (Layer 2): "Predict every tensor shape in a forward pass before running
it."

There is no array library here, so this file implements the twenty lines of
broadcasting that NumPy, PyTorch and JAX all agree on -- right-align the
shapes, a dimension of 1 stretches, anything else must match. Writing the rule
out is the fastest way to stop being surprised by it.

The forward pass is a real one: score six Chinese queries against seventeen
documents from `../zh-retrieval-lab/`, then the same arithmetic in the shape of
one attention head. Sections 2 and 3 introduce two bugs that do not raise, do
not produce NaNs, and change the answer -- and both of them survive for the
same reason, which is that the two shapes involved happened to be equal.

Section 4 asks what an assertion costs against what it catches.

Predict the shape column before running. That is the whole exercise; the code
is here to mark it.
"""
from __future__ import annotations

import math
import os
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")
sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                "..", "zh-retrieval-lab"))

from analyzers import bigram, unigram  # noqa: E402
from corpus import DOCS, QUERIES      # noqa: E402
from metrics import ndcg_at_k, recall_at_k  # noqa: E402

PREDICTIONS = {
    "A": "A shape error is the cheap kind of bug: it raises immediately, so "
         "the ones that get through are logic bugs, not shape bugs.",
    "B": "Reducing over the wrong axis produces obvious nonsense.",
    "C": "Broadcasting a (n,) against a (n,m) does what you meant.",
    "D": "Shape assertions are noise in code that already runs.",
}


# ---------------------------------------------------------------------------
# The broadcasting rule, in full.
# ---------------------------------------------------------------------------
def broadcast(shape_a, shape_b):
    """Right-align; each pair must be equal or contain a 1. Raises otherwise.

    The padding goes on the LEFT. Getting that backwards is the first thing
    this file got wrong: pad (12,) on the right to (12,1) and a (12,64) score
    matrix accepts it, which is the exact bug section 2 is about. Padded on the
    left to (1,12) it raises, correctly.
    """
    pad_a = (1,) * max(0, len(shape_b) - len(shape_a)) + tuple(shape_a)
    pad_b = (1,) * max(0, len(shape_a) - len(shape_b)) + tuple(shape_b)
    out = []
    for a, b in zip(pad_a, pad_b):
        if a == b or a == 1 or b == 1:
            out.append(max(a, b))
        else:
            raise ValueError(f"cannot broadcast {shape_a} against {shape_b}: "
                             f"{a} and {b}")
    return tuple(out)


def matmul_shape(a, b):
    if a[-1] != b[-2]:
        raise ValueError(f"matmul {a} @ {b}: {a[-1]} != {b[-2]}")
    return broadcast(a[:-2], b[:-2]) + (a[-2], b[-1])


def matmul(A, B):
    """2-D only, which is all this file needs. Shape checked by matmul_shape."""
    (n, k), (k2, m) = A["shape"], B["shape"]
    assert k == k2
    a, b = A["data"], B["data"]
    out = [0.0] * (n * m)
    for i in range(n):
        for p in range(k):
            v = a[i * k + p]
            if v:
                base = p * m
                for j in range(m):
                    out[i * m + j] += v * b[base + j]
    return {"shape": (n, m), "data": out}


def row(M, i):
    n, m = M["shape"]
    return M["data"][i * m:(i + 1) * m]


# ---------------------------------------------------------------------------
# The real forward pass: TF-IDF query/document scoring.
# ---------------------------------------------------------------------------
doc_ids = sorted(DOCS)
query_ids = list(QUERIES)
terms = {d: bigram(DOCS[d]) for d in doc_ids}
vocab = sorted({t for ts in terms.values() for t in ts})
col = {t: i for i, t in enumerate(vocab)}
N, V = len(doc_ids), len(vocab)
df = {t: sum(1 for d in doc_ids if t in terms[d]) for t in vocab}
idf = {t: math.log(N / df[t]) for t in vocab}


def dense(tokens):
    v = [0.0] * V
    for t in tokens:
        if t in col:
            v[col[t]] += idf[t]
    return v


D = {"shape": (N, V), "data": [x for d in doc_ids for x in dense(terms[d])]}
Q = {"shape": (len(query_ids), V),
     "data": [x for q in query_ids for x in dense(bigram(q))]}
DT = {"shape": (V, N),
      "data": [D["data"][i * V + j] for j in range(V) for i in range(N)]}

print("=" * 76)
print("1. Every shape in the pass, predicted then checked")
print("=" * 76)
print(f"{len(query_ids)} queries, {N} documents, {V} bigram terms")
print()
steps = [
    ("Q  query matrix", Q["shape"]),
    ("D  document matrix", D["shape"]),
    ("D.T", DT["shape"]),
    ("S = Q @ D.T", matmul_shape(Q["shape"], DT["shape"])),
    ("query norms, keepdims", (len(query_ids), 1)),
    ("doc norms, keepdims", (1, N)),
    ("S / (qn * dn)", broadcast(broadcast(matmul_shape(Q["shape"], DT["shape"]),
                                          (len(query_ids), 1)), (1, N))),
    ("top-1 index per query", (len(query_ids),)),
]
print(f"{'step':<26}{'shape':>14}")
for label, shape in steps:
    print(f"{label:<26}{str(shape):>14}")
print()
print("The same arithmetic in the shape of one attention head, so the rule is")
print("visibly the same rule (declared sizes; nothing is trained here):")
n_tok, d_k, d_v = 12, 64, 64
head = [
    ("X  tokens x model dim", (n_tok, 512)),
    ("W_q", (512, d_k)),
    ("Q = X @ W_q", matmul_shape((n_tok, 512), (512, d_k))),
    ("K = X @ W_k", matmul_shape((n_tok, 512), (512, d_k))),
    ("K.T", (d_k, n_tok)),
    ("scores = Q @ K.T", matmul_shape((n_tok, d_k), (d_k, n_tok))),
    ("causal mask", (n_tok, n_tok)),
    ("rowmax, keepdims", (n_tok, 1)),
    ("softmax(scores)", (n_tok, n_tok)),
    ("V = X @ W_v", matmul_shape((n_tok, 512), (512, d_v))),
    ("out = P @ V", matmul_shape((n_tok, n_tok), (n_tok, d_v))),
]
for label, shape in head:
    print(f"{label:<26}{str(shape):>14}")
print()
print("The one worth naming: `scores` is (tokens x tokens) and has nothing to")
print("do with the model dimension, which is why context length costs quadratic")
print("memory and width does not.")

print()
print("=" * 76)
print("2. The subtraction that raises, and the one that does not")
print("=" * 76)
print("Softmax needs the row maximum subtracted for stability. Written as a")
print("(n,) instead of an (n,1), it right-aligns against the LAST axis:")
print()
for label, s_shape, m_shape in (
    ("scores (12,12), rowmax (12,)   -- square", (12, 12), (12,)),
    ("scores (12,64), rowmax (12,)   -- not square", (12, 64), (12,)),
    ("scores (12,12), rowmax (12,1)  -- correct", (12, 12), (12, 1)),
):
    try:
        result = broadcast(s_shape, m_shape)
        print(f"  {label:<40} -> {str(result):<10} no error")
    except ValueError as exc:
        print(f"  {label:<40} -> raises: {exc}")
print()
print("The square case is the one that ships. It subtracts the maximum of")
print("COLUMN j from row i instead of the maximum of row i, which is silent")
print("because softmax renormalises afterwards and the output still sums to 1.")
print()


def softmax_rows(M, wrong_axis=False):
    n, m = M["shape"]
    out = []
    if wrong_axis:
        # rowmax as a (n,) broadcast against the last axis -- the bug.
        colmax = [max(M["data"][i * m + j] for i in range(n)) for j in range(m)]
        for i in range(n):
            ex = [math.exp(M["data"][i * m + j] - colmax[j]) for j in range(m)]
            s = sum(ex)
            out += [e / s for e in ex]
    else:
        for i in range(n):
            r = row(M, i)
            hi = max(r)
            ex = [math.exp(x - hi) for x in r]
            s = sum(ex)
            out += [e / s for e in ex]
    return {"shape": (n, m), "data": out}


sq = {"shape": (12, 12),
      "data": [math.sin(i * 1.7 + j * 0.3) * 6 for i in range(12) for j in range(12)]}
good = softmax_rows(sq)
bad = softmax_rows(sq, wrong_axis=True)
print(f"{'check':<38}{'correct':>12}{'buggy':>12}")
print(f"{'every row sums to 1':<38}"
      f"{all(abs(sum(row(good, i)) - 1) < 1e-9 for i in range(12)):>12}"
      f"{all(abs(sum(row(bad, i)) - 1) < 1e-9 for i in range(12)):>12}")
print(f"{'all entries in [0,1]':<38}"
      f"{all(0 <= x <= 1 for x in good['data']):>12}"
      f"{all(0 <= x <= 1 for x in bad['data']):>12}")
print(f"{'no NaN or inf':<38}"
      f"{all(math.isfinite(x) for x in good['data']):>12}"
      f"{all(math.isfinite(x) for x in bad['data']):>12}")
print(f"{'argmax per row unchanged':<38}{'--':>12}"
      f"{sum(1 for i in range(12) if row(good, i).index(max(row(good, i))) == row(bad, i).index(max(row(bad, i)))):>9}/12")
print(f"{'max absolute difference':<38}{'--':>12}"
      f"{max(abs(a - b) for a, b in zip(good['data'], bad['data'])):>12.6f}")
print()
print("Every assertion a reviewer would write passes. The distribution is")
print("different and, on this input, so is the argmax on some rows.")

print()
print("=" * 76)
print("3. Normalising over the wrong axis, scored on a real task")
print("=" * 76)
def build_space(analyze):
    t = {d: analyze(DOCS[d]) for d in doc_ids}
    vc = sorted({x for ts in t.values() for x in ts})
    c = {x: i for i, x in enumerate(vc)}
    d_f = {x: sum(1 for d in doc_ids if x in t[d]) for x in vc}
    i_f = {x: math.log(N / d_f[x]) for x in vc}

    def vec(tokens):
        v = [0.0] * len(vc)
        for x in tokens:
            if x in c:
                v[c[x]] += i_f[x]
        return v

    Dm = {"shape": (N, len(vc)), "data": [x for d in doc_ids for x in vec(t[d])]}
    Qm = {"shape": (len(query_ids), len(vc)),
          "data": [x for q in query_ids for x in vec(analyze(q))]}
    DTm = {"shape": (len(vc), N),
           "data": [Dm["data"][i * len(vc) + j] for j in range(len(vc))
                    for i in range(N)]}
    return Dm, Qm, DTm, len(vc), analyze


def run_space(analyze):
    Dm, Qm, DTm, Vn, _ = build_space(analyze)
    Sm = matmul(Qm, DTm)
    qn = [math.sqrt(sum(x * x for x in row(Qm, i))) or 1.0
          for i in range(len(query_ids))]
    # Correct: one norm per DOCUMENT, reducing over the term axis. Length N.
    dn = [math.sqrt(sum(Dm["data"][i * Vn + j] ** 2 for j in range(Vn))) or 1.0
          for i in range(N)]
    # The bug: reduce over the document axis instead and get one norm per TERM.
    # Length Vn. Nothing raises, because Vn > N, so indexing it by document id
    # works and silently returns the norm of an unrelated column.
    tn = [math.sqrt(sum(Dm["data"][i * Vn + j] ** 2 for i in range(N))) or 1.0
          for j in range(Vn)]

    def rank(normalise):
        out = {}
        for i, q in enumerate(query_ids):
            scored = {}
            for j, d in enumerate(doc_ids):
                s = Sm["data"][i * N + j]
                if normalise == "correct":
                    s /= qn[i] * dn[j]
                elif normalise == "doc_only":
                    s /= dn[j]
                elif normalise == "wrong_axis":
                    s /= qn[i] * tn[j]
                scored[d] = s
            out[q] = [d for d, v in sorted(scored.items(),
                                           key=lambda kv: (-kv[1], kv[0])) if v > 0]
        return out
    return rank, Vn


for analyzer_name, analyze in (("bigram", bigram), ("unigram", unigram)):
    rank, Vn = run_space(analyze)
    base = rank("correct")
    candidates = sum(len(base[q]) for q in query_ids) / len(query_ids)
    print(f"--- {analyzer_name} analyzer: {Vn} terms, "
          f"{candidates:.1f} candidate documents per query on average ---")
    print(f"{'normalisation':<20}{'recall@5':>10}{'nDCG@5':>9}{'MRR':>8}"
          f"{'same ranking':>14}{'same top-1':>12}")
    for label in ("correct", "doc_only", "none", "wrong_axis"):
        r = rank(label)
        rec = sum(recall_at_k(r[q], rel, 5) for q, rel in QUERIES.items()) / len(QUERIES)
        nd = sum(ndcg_at_k(r[q], rel, 5) for q, rel in QUERIES.items()) / len(QUERIES)
        mrr = 0.0
        for q, rel in QUERIES.items():
            for i, d in enumerate(r[q], start=1):
                if d in rel:
                    mrr += 1 / i
                    break
        same = sum(1 for q in query_ids if r[q] == base[q])
        top1 = sum(1 for q in query_ids
                   if (r[q][:1] or [None]) == (base[q][:1] or [None]))
        print(f"{label:<20}{rec:>10.4f}{nd:>9.4f}{mrr / len(QUERIES):>8.4f}"
              f"{f'{same}/{len(query_ids)}':>14}{f'{top1}/{len(query_ids)}':>12}")
    print()

print("Two things in that table, and the second is the useful one.")
print()
print("`correct` and `doc_only` are identical on every query under both")
print("analyzers, and that is a theorem rather than a coincidence: dividing")
print("all of one query's scores by one constant cannot reorder that query's")
print("own results. Query-side normalisation matters only when scores are")
print("compared ACROSS queries or against a threshold -- which is what a")
print("retrieval cut-off is.")
print()
print("`wrong_axis` is the shape bug, and whether it is detectable is a")
print("property of the DATA, not of the bug. Under the bigram analyzer each")
print("query retrieves a couple of documents and there is nothing to reorder,")
print("so every metric is identical and a smoke test passes. Change one line")
print("of the analyzer and the same bug moves the numbers.")

print()
print("=" * 76)
print("4. What an assertion costs")
print("=" * 76)
print("Two surviving bugs, and which check would have caught each:")
print()
checks = [
    ("shapes broadcast at all", "raises on (12,64) vs (12,)", "caught by the runtime"),
    ("output sums to 1", "the wrong-axis softmax", "NOT caught"),
    ("output in [0,1], finite", "the wrong-axis softmax", "NOT caught"),
    ("assert m.shape == (n, 1)", "the wrong-axis softmax", "caught, 1 line"),
    ("assert len(d_norm) == n_docs", "wrong_axis normalisation", "caught, 1 line"),
]
print(f"{'check':<34}{'bug':<32}{'result'}")
for a, b, c in checks:
    print(f"{a:<34}{b:<32}{c}")
print()
print("Both surviving bugs need the SAME one-line assertion class: state the")
print("shape you meant, next to the operation. The runtime can only check")
print("consistency; it has no way to know which of two compatible shapes was")
print("intended, and a square matrix makes every wrong answer compatible.")

print()
print("=" * 76)
print("Predictions")
print("=" * 76)
for k, v in PREDICTIONS.items():
    print(f"  {k}: {v}")
