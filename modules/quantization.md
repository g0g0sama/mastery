# Quantization

**Micro module.** One mechanism, one experiment, three cards. Runs against
[serving-lab/](serving-lab/).

**Capability:** Quantization (Layer 8, Aware -> Working). Map evidence:
"Quality vs memory across two quantizations, on a real task."

---

## The problem

"int8 is fine, int4 is risky" is the received wisdom, and it is the wrong axis.
`quant_lab.py` quantizes real vectors -- built by random projection from the
bigram tf-idf of the Chinese corpus in [zh-retrieval-lab/](zh-retrieval-lab/) --
round-trips them through an integer grid for real, and scores the result with
the same judgments and the same metrics module as every Layer 6 module.

## The mechanism

**Granularity beats bit width, and only on the right axis.**

Seven schemes, mean cosine error against the fp32 vector, on embeddings
containing one high-magnitude "rogue" coordinate shared by every vector:

```text
scheme              bytes/vec   mean cos err   recall@5   top5 unchanged
fp32 (baseline)         1028       0.000000      0.500     6/6
int8 per-tensor          260       0.000527      0.500     1/6
int8 per-vector          260       0.000440      0.500     4/6
int8 per-channel         260       0.000004      0.500     5/6
int8 group-32            288       0.000057      0.500     5/6
int4 per-vector          132       0.116586      0.333     0/6
int4 per-channel         132       0.001283      0.500     3/6
int4 group-32            160       0.015146      0.500     1/6
int4 group-32 asym       160       0.005929      0.500     1/6
```

The spread *within* int4 is 91x. The spread between int8 and int4 at matched
granularity is smaller than the spread between two int4 schemes. Bit width is
one axis and it is not the first one.

**Per-vector scaling is the trap.** It is finer-grained than per-tensor and buys
essentially nothing here (0.000440 vs 0.000527), while per-channel is 136x
better on identical data. Switch the rogue coordinate off and re-run:

```text
scheme              with rogue   without    ratio
int8 per-tensor       0.000527   0.000025   20.9x
int8 per-vector       0.000440   0.000020   22.5x
int8 per-channel      0.000004   0.000011    0.4x
int8 group-32         0.000057   0.000013    4.3x
```

The outlier is present in **every vector**, so every vector's scale is set by it
whether the scale is shared across the matrix or not. Only a granularity aligned
with the axis the outlier lives on -- per-channel, or per-group by the accident
of dimension 0 falling in one group of eight -- confines the damage. That
alignment is the whole of LLM.int8() and of every outlier-aware scheme since:
not better rounding, and not merely smaller scaling units, but units on the
right axis.

Note also that per-channel is *better with the outlier than without it* (0.4x).
A large coordinate given its own scale costs nothing; it is only expensive when
it is sharing.

**Reconstruction error is not the objective, and margins are.**

```text
query               top1-top2   min gap in top6   int8 shift  flip?   int4 shift  flip?
Q1 中石化深圳投资        0.0284            0.0001       0.0055  yes        0.0713  yes
Q3 动力电池供应          0.0014            0.0014       0.0087  no         0.1109  yes
Q5 稀土永磁              0.1577            0.0039       0.0059  no         0.0731  yes

actual top-5 changes: 2/6 at int8, 6/6 at int4
predicted by shift > min gap: 6/6 and 6/6
```

The naive rule over-predicts badly. A shift larger than the gap is *necessary*
but not sufficient: both scores move, usually in the same direction, and most of
the perturbation is common-mode. What survives is the differential error. The
practical form of this: a corpus of near-duplicates has small gaps everywhere
and cannot tolerate the scheme a corpus of distinct documents shrugs off. "int8
is fine" is a claim about a corpus, not about a bit width.

**Asymmetry is free.** Quantizing the query as well as the documents adds ~17%
to the score shift at int8 and ~42% at int4, and costs MRR at int4 (0.427 ->
0.369). There is one query and millions of documents, so keeping the query in
full precision costs nothing. It is the default in every serious index for
exactly this reason.

**Count the scales.** group-32 on 256 dimensions is 8 fp32 scales per vector: 32
bytes, which is 25% on top of an int8 payload and 100% on top of an int4 one. At
low bit widths the metadata can cost more than the data, and a scheme's
"4 bits" is rarely 4 bits.

## The experiment

```powershell
cd modules\serving-lab
python quant_lab.py
```

Then in [bench_lab.py](serving-lab/bench_lab.py) section 4, these same schemes
are divided by scan throughput to produce cost per successful query -- where
int4 per-channel wins by 7.8x over fp32 at identical measured recall.

## Boundary

- **These are embeddings, not transformer weights.** What transfers: absmax
  scaling, granularity and its alignment to the outlier axis, asymmetric
  (zero-point) quantization, and the fact that downstream quality does not track
  reconstruction error. What does not transfer: the magnitude of the quality
  drop for a given bit width on a real LLM.
- **The rogue dimension is authored**, at 8x the typical magnitude. Real encoders
  have such coordinates; this one was placed deliberately so it could be switched
  off and measured rather than asserted.
- **6 queries and 17 documents saturate the retrieval metrics.** Eight of nine
  schemes score identical recall@5. The error column and the top-5 stability
  column are what discriminate here, and on a real set the task metric would.
- **Round-trip only.** The lab dequantizes and computes in fp64. It measures
  grid error, not the accumulation error of an integer kernel, and not the
  latency of one.

## Cards

### 1. [misconception] int8 quantization is safe and int4 is risky.

**Answer:** Bit width is not the first axis; scaling granularity is. In the lab
the spread within int4 was 91x (0.0013 per-channel to 0.117 per-vector), and
int4 per-channel preserved more top-5 lists than int8 per-tensor at half the
bytes.

**Why:** Quantization error is set by the range each scale has to cover. A scale
shared across values with very different magnitudes wastes most of the grid.

**Boundary:** Finer is not automatically better -- per-vector is finer than
per-tensor and bought nothing, because the outlier lives on the channel axis.
And every extra scale is stored: group-32 at int4 is 6 bits per weight, not 4.

**Tags:** `serving` `misconception` `general-principle`

---

### 2. [failure] You switched an embedding index to int8 and recall barely moved, so you switched to int4 and the top result changed on almost every query.

**Answer:** Compare the perturbation to the *smallest adjacent score gap* inside
the top-k, not to the top1-top2 margin. In the lab int8 shifted scores by
~0.006 and flipped 2/6 top-5 lists; int4 shifted by ~0.08 and flipped 6/6, with
two queries whose gap was 0.0014 -- an effective tie no scheme preserves.

**Why:** Ranking is a comparison. Absolute error only matters relative to the
distance between the things being compared.

**Boundary:** The rule over-predicts: it flagged 6/6 at int8 where only 2/6
moved, because most of the error is common-mode and cancels in the comparison.
Use it to decide what to *test*, not to predict the outcome.

**Tags:** `serving` `failure` `general-principle`

---

### 3. [decision] Should the query embedding be quantized to match the index?

**Answer:** No. Keep the query in full precision. It adds error (17% more score
shift at int8, 42% at int4, and measurable MRR loss at int4) and saves the
memory of one vector against millions.

**Why:** The dot product's error has contributions from both sides. Only one
side has a storage cost worth optimizing.

**Boundary:** Some ANN implementations require a symmetric distance for their
index structure, and some SIMD kernels are faster on int8 x int8 than on
int8 x fp32. That is a speed argument to make explicitly and measure, not a
default to inherit.

**Tags:** `serving` `decision` `general-principle`
