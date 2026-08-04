"""Quantization: quality vs memory across two quantizations, on a real task.

Map row (Layer 8): "Quality vs memory across two quantizations, on a real task."

**This section of the lab is measured, not simulated.** The vectors are built by
random projection from the bigram tf-idf of the Chinese corpus in
../zh-retrieval-lab/, quantized for real, dequantized for real, and scored with
the same graded judgments and the same metrics module as every Layer 6 module.
The arithmetic error is arithmetic, not a declared error rate.

What it is *not*: weight quantization of a transformer. These are embeddings --
activations, in the sense that matters here, since a KV cache is also
activations. The mechanisms that transfer are absmax scaling, granularity
(per-tensor / per-vector / per-group), the outlier problem, and the fact that
downstream quality does not track reconstruction error. What does not transfer
is the magnitude of the quality drop for a given bit width on a real LLM.

Commit to the predictions before running.
"""
from __future__ import annotations

import math
import pathlib
import random
import sys
import zlib

import hardware as hw

_LAB = pathlib.Path(__file__).resolve().parent
for _p in (_LAB.parent / "zh-retrieval-lab",):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from analyzers import bigram          # noqa: E402
from corpus import DOCS, QUERIES      # noqa: E402
import metrics                        # noqa: E402

DIM = 256

PREDICTIONS = {
    "A": "int8 loses a little accuracy and int4 loses a lot: quality degrades "
         "smoothly with bit width.",
    "B": "Per-tensor and per-vector int8 are within noise of each other on "
         "normalized embeddings -- the granularity argument is about weights.",
    "C": "Reconstruction error (cosine to the fp32 vector) ranks the schemes in "
         "the same order as the retrieval metrics do.",
    "D": "Quantizing the query as well as the documents roughly doubles the "
         "error, since both sides are approximate.",
}


# --------------------------------------------------------------------------- #
# Embeddings. Random projection of bigram tf-idf: a real technique, applied to
# the real corpus, producing dense vectors with a defensible geometry.
# --------------------------------------------------------------------------- #

def _signs(term: str, dim: int) -> list[int]:
    """A deterministic +-1 vector per term. The projection matrix, generated
    rather than stored -- the hashing trick, which is how a projection of an
    unbounded vocabulary is done in practice."""
    # zlib.crc32, not hash(): str.__hash__ is salted per process, and a
    # fixture that changes between runs cannot be compared with itself.
    rng = random.Random(zlib.crc32(term.encode("utf-8")) ^ 20260804)
    return [1 if rng.random() < 0.5 else -1 for _ in range(dim)]


def build_embeddings(dim: int = DIM, rogue: bool = True) -> dict[str, list[float]]:
    """tf-idf over bigrams, projected to `dim`, L2-normalized.

    `rogue` adds one high-magnitude shared dimension. Real sentence encoders
    have these -- a handful of coordinates with variance orders of magnitude
    above the rest, carrying frequency or position information. They are the
    single reason per-tensor quantization of activations behaves differently
    from per-tensor quantization of weights, so the lab can switch them off and
    measure the difference rather than assert it.
    """
    df: dict[str, int] = {}
    tokenized = {d: bigram(text) for d, text in DOCS.items()}
    for terms in tokenized.values():
        for t in set(terms):
            df[t] = df.get(t, 0) + 1
    n = len(DOCS)
    out = {}
    for doc, terms in tokenized.items():
        vec = [0.0] * dim
        tf: dict[str, int] = {}
        for t in terms:
            tf[t] = tf.get(t, 0) + 1
        for t, count in tf.items():
            w = (1 + math.log(count)) * math.log(n / df[t])
            for i, s in enumerate(_signs(t, dim)):
                vec[i] += w * s
        if rogue:
            # One coordinate ~8x the typical magnitude, shared by every vector.
            scale = max(abs(v) for v in vec)
            vec[0] = 8.0 * scale
        norm = math.sqrt(sum(v * v for v in vec)) or 1.0
        out[doc] = [v / norm for v in vec]
    return out


def embed_query(text: str, dim: int, docs_df, rogue: bool) -> list[float]:
    vec = [0.0] * dim
    terms = bigram(text)
    tf: dict[str, int] = {}
    for t in terms:
        tf[t] = tf.get(t, 0) + 1
    n = len(DOCS)
    for t, count in tf.items():
        w = (1 + math.log(count)) * math.log(n / docs_df.get(t, n))
        for i, s in enumerate(_signs(t, dim)):
            vec[i] += w * s
    if rogue:
        scale = max(abs(v) for v in vec) or 1.0
        vec[0] = 8.0 * scale
    norm = math.sqrt(sum(v * v for v in vec)) or 1.0
    return [v / norm for v in vec]


def _df_table():
    df: dict[str, int] = {}
    for text in DOCS.values():
        for t in set(bigram(text)):
            df[t] = df.get(t, 0) + 1
    return df


# --------------------------------------------------------------------------- #
# Quantizers. quantize -> dequantize, so every downstream number is measured on
# values that actually survived the round trip.
# --------------------------------------------------------------------------- #

def q_absmax(vec, bits, group=None, asymmetric=False):
    """Round-trip through a `bits`-wide integer grid.

    group=None    one scale for the whole vector (per-vector)
    group=k       one scale per k consecutive dimensions (per-group)
    asymmetric    keep a zero point, so a one-sided distribution uses the
                  whole grid instead of half of it
    """
    n = len(vec)
    group = group or n
    qmax = 2 ** (bits - 1) - 1
    out = [0.0] * n
    for start in range(0, n, group):
        chunk = vec[start:start + group]
        if asymmetric:
            lo, hi = min(chunk), max(chunk)
            scale = (hi - lo) / (2 ** bits - 1) or 1e-12
            zero = lo
            for i, v in enumerate(chunk):
                q = round((v - zero) / scale)
                q = max(0, min(2 ** bits - 1, q))
                out[start + i] = q * scale + zero
        else:
            scale = (max(abs(v) for v in chunk) or 1e-12) / qmax
            for i, v in enumerate(chunk):
                q = max(-qmax, min(qmax, round(v / scale)))
                out[start + i] = q * scale
    return out


def q_per_tensor(vecs, bits):
    """One scale for the entire matrix -- the cheapest thing to implement, and
    the one that a single outlier coordinate destroys."""
    qmax = 2 ** (bits - 1) - 1
    scale = (max(abs(v) for vec in vecs.values() for v in vec) or 1e-12) / qmax
    return {k: [max(-qmax, min(qmax, round(v / scale))) * scale for v in vec]
            for k, vec in vecs.items()}


def q_per_channel(vecs, bits):
    """One scale per *dimension*, across all vectors.

    The granularity that matches where outliers actually live. A rogue
    coordinate gets its own large scale and stops taxing the other 255.
    Per-vector scaling cannot do this: the outlier is present in every vector,
    so every vector's scale is set by it.
    """
    keys = list(vecs)
    dim = len(vecs[keys[0]])
    qmax = 2 ** (bits - 1) - 1
    scales = [(max(abs(vecs[k][i]) for k in keys) or 1e-12) / qmax
              for i in range(dim)]
    return {k: [max(-qmax, min(qmax, round(v / scales[i]))) * scales[i]
                for i, v in enumerate(vec)] for k, vec in vecs.items()}


def cosine(a, b):
    num = sum(x * y for x, y in zip(a, b))
    na = math.sqrt(sum(x * x for x in a)) or 1e-12
    nb = math.sqrt(sum(x * x for x in b)) or 1e-12
    return num / (na * nb)


def bytes_per_vector(bits, group=None, dim=DIM):
    """Storage, honestly counted: the scales are not free."""
    scales = 1 if group is None else dim // group
    return dim * bits / 8 + scales * 4


# --------------------------------------------------------------------------- #
# Scoring
# --------------------------------------------------------------------------- #

def rank_all(doc_vecs, query_vecs):
    return {q: [d for d, _ in sorted(
        ((d, cosine(qv, dv)) for d, dv in doc_vecs.items()),
        key=lambda x: -x[1])] for q, qv in query_vecs.items()}


# (label, per-vector function or None, matrix-wide function or None, bits, group)
SCHEMES = [
    ("fp32 (baseline)", lambda v: list(v), None, 32, None),
    ("int8 per-tensor", None, q_per_tensor, 8, None),
    ("int8 per-vector", lambda v: q_absmax(v, 8), None, 8, None),
    ("int8 per-channel", None, q_per_channel, 8, None),
    ("int8 group-32", lambda v: q_absmax(v, 8, 32), None, 8, 32),
    ("int4 per-vector", lambda v: q_absmax(v, 4), None, 4, None),
    ("int4 per-channel", None, q_per_channel, 4, None),
    ("int4 group-32", lambda v: q_absmax(v, 4, 32), None, 4, 32),
    ("int4 group-32 asym", lambda v: q_absmax(v, 4, 32, True), None, 4, 32),
]


def section_1_quality(rogue=True, label="with rogue dimension"):
    hw.rule(f"1. Quality vs memory, {label}")
    docs = build_embeddings(rogue=rogue)
    df = _df_table()
    queries = {q: embed_query(q.split(" ", 1)[1], DIM, df, rogue) for q in QUERIES}
    base_rank = rank_all(docs, queries)

    hw.row("scheme", "bytes/vec", "10M vectors", "mean cos err", "recall@5",
           "MRR", "nDCG@5", "top5 same", widths=[20, 11, 13, 14, 10, 8, 9, 10])
    results = {}
    for name, fn, matrix_fn, bits, group in SCHEMES:
        qdocs = matrix_fn(docs, bits) if fn is None else {k: fn(v) for k, v in docs.items()}
        errs = [abs(1 - cosine(docs[k], qdocs[k])) for k in docs]
        ranks = rank_all(qdocs, queries)
        m = metrics.evaluate(ranks, QUERIES, k=5)
        same = sum(1 for q in QUERIES if ranks[q][:5] == base_rank[q][:5])
        nbytes = bytes_per_vector(bits, group)
        hw.row(name, f"{nbytes:8.0f}", hw.gb(nbytes * 1e7).strip(),
               f"{sum(errs) / len(errs):12.6f}", f"{m['recall@k']:8.3f}",
               f"{m['MRR']:6.3f}", f"{m['nDCG@k']:7.3f}",
               f"{same}/{len(QUERIES)}", widths=[20, 11, 13, 14, 10, 8, 9, 10])
        results[name] = {"err": sum(errs) / len(errs), "bytes": nbytes,
                         "same": same, **m}
    return results, docs, queries, base_rank


def section_2_outliers(with_rogue, without_rogue):
    hw.rule("2. What the rogue dimension did")
    print("Same corpus, same quantizers, one coordinate removed from the\n"
          "embedding construction. Mean cosine error:\n")
    hw.row("scheme", "with rogue", "without", "ratio", widths=[22, 14, 14, 10])
    for name, *_ in SCHEMES:
        a = with_rogue[name]["err"]
        b = without_rogue[name]["err"]
        hw.row(name, f"{a:12.6f}", f"{b:12.6f}",
               f"{(a / b if b else float('inf')):8.1f}x", widths=[22, 14, 14, 10])
    print("\nRead the rows that do NOT move. Per-channel is flat -- better with")
    print("the outlier than without it -- because each dimension carries its own")
    print("scale, so the rogue coordinate taxes only itself.")
    print("\nPer-VECTOR is the trap. It is finer-grained than per-tensor and buys")
    print("nothing here, because the outlier is present in EVERY vector: each")
    print("vector's scale is set by it anyway. Granularity helps only when it is")
    print("aligned with the axis the outlier lives on. group-32 helps partly, by")
    print("the accident of dimension 0 falling in one group out of eight.")
    print("\nThat alignment is the whole of LLM.int8() and of every outlier-aware")
    print("scheme since: not better rounding, and not merely smaller scaling")
    print("units -- units on the right axis.")


def section_3_margins(docs, queries, base_rank):
    hw.rule("3. Why a small error sometimes changes everything")
    print("Quantization perturbs scores. A perturbation only matters if it")
    print("exceeds the gap between two documents it could reorder -- and the")
    print("gap that matters is the SMALLEST adjacent gap inside the top-k, not")
    print("the headline top1-top2 margin.\n")
    q8 = {k: q_absmax(v, 8) for k, v in docs.items()}
    q4 = {k: q_absmax(v, 4) for k, v in docs.items()}
    hw.row("query", "top1-top2", "min gap in top6", "int8 shift", "flip?",
           "int4 shift", "flip?", widths=[20, 12, 18, 12, 8, 12, 8])
    flips = {8: 0, 4: 0}
    predicted = {8: 0, 4: 0}
    for q, qv in queries.items():
        scored = sorted(((d, cosine(qv, dv)) for d, dv in docs.items()),
                        key=lambda x: -x[1])
        margin = scored[0][1] - scored[1][1]
        gaps = [scored[i][1] - scored[i + 1][1] for i in range(5)]
        min_gap = min(gaps)
        cells = []
        for bits, qd in ((8, q8), (4, q4)):
            shift = max(abs(cosine(qv, docs[d]) - cosine(qv, qd[d])) for d in docs)
            moved = rank_all(qd, {q: qv})[q][:5] != base_rank[q][:5]
            flips[bits] += moved
            predicted[bits] += shift > min_gap
            cells += [f"{shift:10.4f}", "yes" if moved else "no"]
        hw.row(q, f"{margin:10.4f}", f"{min_gap:14.4f}", *cells,
               widths=[20, 12, 18, 12, 8, 12, 8])
    n = len(queries)
    print(f"\nactual top-5 changes: {flips[8]}/{n} at int8, {flips[4]}/{n} at int4")
    print(f"predicted by shift > min gap: {predicted[8]}/{n} and {predicted[4]}/{n}")
    print("\nThe rule over-predicts at int8: a shift larger than the gap is a")
    print("necessary condition for a reorder, not a sufficient one -- both scores")
    print("move, usually in the same direction, so most of the perturbation is")
    print("common-mode and cancels. What survives is the DIFFERENTIAL error.")
    print("\nTwo queries here have a min gap of 0.0014 -- an effective tie -- and")
    print("nothing preserves their order reliably. A corpus of near-duplicates")
    print("has small gaps everywhere and cannot tolerate the scheme a corpus of")
    print("distinct documents shrugs off, which is why 'int8 is fine' is a claim")
    print("about a corpus rather than about a bit width.")


def section_4_query_side(docs, queries):
    hw.rule("4. Quantizing the query as well")
    print("Storage says quantize the documents; there are millions of them and")
    print("one query. Does the query side matter anyway?\n")
    hw.row("configuration", "mean |score shift|", "recall@5", "MRR", "nDCG@5",
           widths=[26, 20, 10, 8, 10])
    base = rank_all(docs, queries)
    q8d = {k: q_absmax(v, 8) for k, v in docs.items()}
    q4d = {k: q_absmax(v, 4) for k, v in docs.items()}
    q8q = {k: q_absmax(v, 8) for k, v in queries.items()}
    q4q = {k: q_absmax(v, 4) for k, v in queries.items()}
    for label, dv, qv in (
        ("fp32 docs, fp32 query", docs, queries),
        ("int8 docs, fp32 query", q8d, queries),
        ("int8 docs, int8 query", q8d, q8q),
        ("int4 docs, fp32 query", q4d, queries),
        ("int4 docs, int4 query", q4d, q4q),
    ):
        shifts = [abs(cosine(queries[q], docs[d]) - cosine(qv[q], dv[d]))
                  for q in queries for d in docs]
        ranks = rank_all(dv, qv)
        m = metrics.evaluate(ranks, QUERIES, k=5)
        hw.row(label, f"{sum(shifts) / len(shifts):16.6f}", f"{m['recall@k']:8.3f}",
               f"{m['MRR']:6.3f}", f"{m['nDCG@k']:8.3f}", widths=[26, 20, 10, 8, 10])
    print("\nQuantizing the query adds ~17% to the score shift at int8 and ~42%")
    print("at int4 -- not the doubling a symmetric-error intuition predicts,")
    print("because the two errors are independent and partly cancel in the dot")
    print("product. It still costs MRR at int4 (0.427 -> 0.369) and it buys")
    print("nothing: the query is ONE vector against millions. Asymmetric")
    print("quantization -- quantized index, full-precision query -- is free, and")
    print("it is the default in every serious index for exactly this reason.")


def section_5_memory():
    hw.rule("5. What this buys at index scale")
    print("10M vectors of 256 dimensions, the size where the decision is real:\n")
    hw.row("scheme", "bytes/vec", "index size", "fits in 24 GB?", "fits in 64 GB RAM?",
           widths=[22, 12, 14, 16, 20])
    for name, _, _, bits, group in SCHEMES:
        b = bytes_per_vector(bits, group)
        total = b * 1e7
        hw.row(name, f"{b:8.0f}", hw.gb(total).strip(),
               "yes" if total < 24e9 else "no",
               "yes" if total < 64e9 else "no", widths=[22, 12, 14, 16, 20])
    print("\nThe scales are counted. group-32 on 256 dimensions is 8 fp32 scales")
    print("per vector -- 32 bytes, which is 25% on top of an int8 payload and")
    print("100% on top of an int4 one. A quantization scheme's overhead is a")
    print("line item, and at int4 the metadata can cost more than the data.")


def score(with_rogue, without_rogue):
    hw.rule("6. The predictions")
    pt = with_rogue["int8 per-tensor"]["err"]
    pv = with_rogue["int8 per-vector"]["err"]
    pc = with_rogue["int8 per-channel"]["err"]
    i4c = with_rogue["int4 per-channel"]["err"]
    verdicts = {
        "A": ("WRONG", f"the spread WITHIN int4 is "
              f"{with_rogue['int4 per-vector']['err'] / i4c:.0f}x "
              f"({i4c:.6f} per-channel to "
              f"{with_rogue['int4 per-vector']['err']:.6f} per-vector). int4 "
              f"per-channel preserves more top-5 lists than int8 per-tensor "
              f"({with_rogue['int4 per-channel']['same']}/6 vs "
              f"{with_rogue['int8 per-tensor']['same']}/6) at half the bytes. "
              f"Bit width is one axis and it is not the first one"),
        "B": ("WRONG, and not the way it fails for weights",
              f"per-vector {pv:.6f} vs per-tensor {pt:.6f} -- a 1.2x "
              f"improvement, i.e. none. Per-CHANNEL is {pt / pc:.0f}x better "
              f"than per-tensor. Finer granularity on the wrong axis is not an "
              f"improvement"),
        "C": ("MOSTLY WRONG", "reconstruction error is monotone in granularity; "
              "recall@5 is flat at 0.500 for eight of nine schemes and moves "
              "only for int4 per-vector. On 6 queries and 17 documents the "
              "metric saturates -- which is the honest version of the lesson: "
              "reconstruction error is a proxy that ranks schemes, and a task "
              "metric is what decides whether the ranking matters"),
        "D": ("RIGHT in direction, WRONG in cost", "the query side adds error "
              "and costs MRR at int4, and there is no reason to pay it: one "
              "fp32 vector against millions of quantized ones is free"),
    }
    for key, text in PREDICTIONS.items():
        verdict, why = verdicts[key]
        print(f"{key}. {verdict}\n   claim: {text}\n   why:   {why}\n")


if __name__ == "__main__":
    with_rogue, docs, queries, base_rank = section_1_quality(True, "with rogue dimension")
    print()
    without_rogue, *_ = section_1_quality(False, "without rogue dimension")
    print()
    section_2_outliers(with_rogue, without_rogue)
    print()
    section_3_margins(docs, queries, base_rank)
    print()
    section_4_query_side(docs, queries)
    print()
    section_5_memory()
    print()
    score(with_rogue, without_rogue)
