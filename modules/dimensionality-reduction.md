# Dimensionality reduction

**Micro module.** One mechanism, one experiment, three cards. Runs against
[stats-lab/](stats-lab/), over the corpus in [zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** Dimensionality reduction, PCA/SVD intuition (Layer 2, Aware ->
Working). Map evidence: "Reduce your embeddings and explain what the axes
lost."

---

## The problem

Reduction is offered as a free win: fewer dimensions, less memory, faster
search, and 90% of the variance retained so 90% of the quality retained. Three
of those four claims are about the vectors and the fourth is about the task,
and the fourth is the only one anybody cares about.

Seventeen Chinese documents, 240 bigram terms, six queries with graded
judgments -- the same fixture the Layer 6 modules use, so a recall number here
is comparable with one there. Truncated SVD by power iteration on the 17x17
Gram matrix, no library.

## The mechanism

**The first component is a structural property, not a topic.**

```text
                             centred PC1   uncentred PC1
document length (terms)          -0.8519         -0.8733
vector norm                      -0.7477         -0.7731

Top documents by |component 1| score, centred:
  D17  score -14.9344  length  32 terms
  D10  score +1.7002  length  18 terms
  D13  score +1.5767  length  17 terms
```

D17 is nine times the next document's score. It is the corpus's one long
document -- the one `zh-retrieval-lab/corpus.py` authored specifically to
punish term frequency -- and the first principal direction is essentially "is
this D17". Component 1 correlates -0.85 with document length and with nothing
semantic. Before naming an axis, correlate it with the boring things: length,
norm, date, source, language. It is usually one of them, and a reduction whose
top axis is length is spending its most expensive dimension on a field you
already have.

**Variance explained does not predict retrieval quality:**

```text
   k  variance explained  recall@5   nDCG@5     MRR  kendall vs full  distinct
   1              0.1326    0.3333   0.2500  0.2667           0.2486       1.0
   2              0.2094    0.0417   0.0231  0.1852           0.3785      10.7
   3              0.2821    0.0417   0.0365  0.2696           0.5198      11.0
   4              0.3521    0.2500   0.1514  0.1965           0.5254       9.7
   6              0.4826    0.2500   0.1920  0.2501           0.6158      10.2
   8              0.6058    0.4583   0.4113  0.4318           0.6893       9.5
  12              0.8273    0.5833   0.5613  0.5823           0.8475       7.2
  16              1.0000    0.5833   0.6267  0.6962           0.9040       7.3
full              1.0000    0.6667   0.6607  0.6667           1.0000       2.0
```

Recall is **not monotone in k**: 0.3333 at k=1, 0.0417 at k=2, back to 0.2500
at k=4. Variance explained rises smoothly through all of it. The two quantities
are answering different questions -- variance is about reconstructing the
vectors, recall is about preserving an ordering, and nothing connects them.

The `distinct` column is the guard rail. It counts distinct scores among
retrieved documents, and at k=1 it is **1.0**: cosine in one dimension takes
two values, everything ties, and the ranking is whatever the tie-break rule
says. The k=1 row's respectable 0.3333 recall is the alphabet. Any metric
computed over a heavily tied ranking is measuring the sort, and the same trap
sits under `zh-retrieval-lab`'s own zero-score documents -- `pca_lab.py` drops
non-positive scores for exactly that reason, and says so in the code.

**Look at the last two rows.** k=16 is the full rank of the centred data, so
the projection there is a lossless rotation -- yet it scores 0.5833 recall
against the uncentred full run's 0.6667. **Nothing was truncated, so nothing
was lost to truncation; the entire difference is the centring step.**

```text
   k   centred recall@5   uncentred recall@5   difference
   1             0.3333               0.2917      +0.0417
   2             0.0417               0.4583      -0.4167
   4             0.2500               0.5417      -0.2917
   8             0.4583               0.6667      -0.2083
  12             0.5833               0.6667      -0.0833
```

The cosine between the two first axes is **0.9730** -- they are nearly the same
direction -- and the retrieval difference reaches 0.42. This is the practical
content of "LSA is a truncated SVD, not a PCA": centring subtracts the mean
document from every vector, which destroys the non-negativity that made cosine
a similarity in the first place and injects the mean into every comparison.
PCA is defined on centred data; retrieval is not. Choose deliberately.

**The aggregate hides who paid:**

```text
query         full     k=1     k=2     k=3     k=4     k=6     k=8    k=12    k=16
Q1           1.000   1.000   0.000   0.000   1.000   1.000   1.000   1.000   1.000
Q2           1.000   0.000   0.000   0.000   0.500   0.500   0.500   1.000   1.000
Q3           0.000   1.000   0.000   0.000   0.000   0.000   0.000   0.000   0.000
Q4           1.000   0.000   0.000   0.000   0.000   0.000   1.000   1.000   1.000
Q5           1.000   0.000   0.250   0.250   0.000   0.000   0.250   0.500   0.500
Q6           0.000   0.000   0.000   0.000   0.000   0.000   0.000   0.000   0.000
```

Between k=8 and k=16 the aggregate rises from 0.4583 to 0.5833 while Q5 sits at
0.500 and Q3 and Q6 sit at zero throughout. Q4 recovers entirely between k=6
and k=8 and Q2 between k=8 and k=12 -- the choice of k is not one decision, it
is six, and they resolve at different places. Pick k from a per-query table or
you are picking it for whichever queries happen to be in the majority.

## The experiment

```powershell
cd modules\stats-lab
python pca_lab.py
```

## Boundary

- **These are sparse TF-IDF vectors, not learned embeddings.** The geometry
  transfers exactly; the semantics do not. A real embedding's first component
  is also usually structural -- frequency, length, language -- but this fixture
  is not evidence for that, it is an illustration of how to check.
- **Seventeen documents means rank 16 after centring**, so "k=16" and "full
  rank" coincide and there is no regime where truncation is genuinely gentle.
  On a real corpus the interesting k is in the hundreds and the curve is
  smoother; the non-monotonicity would shrink, not vanish.
- **Six queries resolve a large effect.** Per-query recall moves in steps of
  0.25 or 0.5 because the judgment sets are tiny.
- **Nothing here covers the reasons to reduce at all** -- memory, index build
  time, ANN behaviour in high dimensions. See
  [ann-indexes-hnsw.md](ann-indexes-hnsw.md) for the second, and
  [quantization.md](quantization.md) for the lever that usually beats reduction
  on memory anyway.

## Cards

### 1. [misconception] The reduction keeps 90% of the variance, so it keeps about 90% of the retrieval quality.

**Answer:** There is no such relationship. In the lab, k=12 retained 82.7% of
the variance and 87.5% of recall@5, but k=2 retained 20.9% of the variance and
**6.3%** of the recall, and recall was not even monotone in k -- 0.3333 at k=1,
0.0417 at k=2, 0.2500 at k=4, while variance explained rose smoothly
throughout.

**Why:** Variance explained measures how well the vectors are reconstructed.
Retrieval measures whether an ordering survived. A component carrying little
variance can be the one separating two documents a query has to distinguish.

**Boundary:** Choose k by measuring the task metric at several k, on a
per-query table. And check for ties first: at k=1 the lab's rankings had one
distinct score, so the metric was reporting the tie-break rule, not the
reduction.

**Tags:** `pca` `retrieval` `metrics` `misconception` `general-principle`

---

### 2. [mechanism] You run PCA on your document embeddings before retrieval and quality drops even at full rank. What happened?

**Answer:** The centring. At k=16 -- the full rank of the centred data, so a
lossless rotation -- the lab scored 0.5833 recall@5 against 0.6667 for the
uncentred run. Nothing was truncated, so the entire gap is the mean subtraction.

**Why:** PCA is defined on centred data; cosine retrieval is not. Subtracting
the corpus mean puts negative components into every vector and makes each
comparison partly a comparison against the average document. That is why LSA is
a truncated SVD of the term-document matrix rather than a PCA of it.

**Boundary:** The first axes are nearly identical either way -- cosine 0.9730
between them in the lab -- so inspecting the components will not reveal this.
Only the task metric will. If you centre, centre the query with the same mean,
and expect the similarity function's meaning to have changed.

**Tags:** `pca` `lsa` `retrieval` `mechanism` `general-principle`

---

### 3. [failure] What should you check about a principal component before naming it?

**Answer:** Correlate it with the boring structural properties first. In the lab
component 1 correlated -0.85 with document length and -0.75 with vector norm,
and one long document scored -14.93 against +1.70 for the next -- the top axis
was "is this the long document", not a topic.

**Why:** Variance is dominated by whatever varies most, and in a document set
that is usually length, frequency, source, or language. Those are metadata you
already have, so an axis spent on them is a wasted dimension and an
interpretation built on them is a story.

**Boundary:** This is a reason to consider length normalisation *before*
reducing, not a reason to discard component 1 -- on a corpus where length
carries real signal (a filing against a headline), removing it costs you.
Measure both on the task.

**Tags:** `pca` `interpretation` `failure` `general-principle`
