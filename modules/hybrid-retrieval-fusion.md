# Hybrid retrieval and rank fusion

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** hybrid retrieval and fusion (Layer 6, - -> **Deep**). Map
evidence to graduate: "Fusion that beats both parents on the same set." This
module delivers that on a fixture; Deep needs it on Sinoscope's corpus with a
dense parent.

Depends on [bm25-baseline.md](bm25-baseline.md) and
[chinese-segmentation.md](chinese-segmentation.md) -- fusion needs parents, and
you cannot tell whether fusion helped without each parent measured alone.

---

## The problem

[chinese-segmentation.md](chinese-segmentation.md) leaves you with a bad choice.
Unigrams find `芯片制裁 -> D07` that bigrams miss entirely. Bigrams correctly rank
the export-control document above the air-traffic-control one, where unigrams put
the false match first. Each analyzer is the only one that gets some query right,
and picking one means accepting the other's failures permanently.

## The wrong model

**"Combine the systems by adding up their scores."**

BM25 scores are not comparable across retrievers. IDF is corpus-and-analyzer
relative, document lengths differ per analyzer, and the score is unbounded --
and the moment a dense retriever joins, one parent emits cosine similarities in
`[-1, 1]` while the other emits unbounded sums. Adding them means the parent with
the larger numeric range silently wins.

Min-max normalizing first is the usual patch, and it holds only while every
parent's score distribution stays stable -- which is not a property you control,
since it shifts with the corpus and with any reindex.

**Reciprocal rank fusion sidesteps the whole problem by never reading a score.**
Only positions:

```text
  RRF(d) = sum over parents of  1 / (k + rank_i(d)),   k = 60 by convention
```

`k` damps the top ranks so a single parent's rank-1 pick cannot dominate on its
own. A document ranked well by two parents beats one ranked brilliantly by one.

## The mechanism

Fusion pays when parents are **complementary and comparably good**:

- *Complementary* -- they fail on different queries. Two analyzers that fail
  together contribute one signal and one vote.
- *Comparably good* -- a parent much worse than the others does not add a
  perspective, it adds noise with voting rights.

Both conditions are measurable before you fuse, from the per-query table each
parent already produces.

## The experiment

`zh-retrieval-lab/fusion_lab.py`.

**Predict before running: RRF over unigram and bigram -- does it beat both
parents? And does adding dictmatch as a third parent help further?**

```powershell
cd modules\zh-retrieval-lab
python fusion_lab.py
```

Actual:

```text
system                recall@5     MRR   nDCG@5
unigram                 1.0000  0.9167   0.9432
bigram                  0.6667  0.6667   0.6607
dictmatch               0.6250  0.5833   0.5834
RRF uni+bi              1.0000  1.0000   0.9940
RRF uni+bi+dict         1.0000  0.9167   0.9325
RRF bi+dict             0.6667  0.6667   0.6607
```

`RRF uni+bi` beats **both** parents on every metric -- MRR 1.0000 against 0.9167
and 0.6667, nDCG 0.9940 against 0.9432 and 0.6607. Perfect MRR means every query
put a relevant document at rank 1.

Per query, the mechanism is legible:

```text
query                unigram   bigram  dictmatch  RRF uni+bi  RRF uni+bi+dict
Q2 出口管制             0.50     1.00       1.00        1.00             1.00
Q3 动力电池供应           1.00     0.00       0.00        1.00             0.50
Q6 芯片制裁             1.00     0.00       0.00        1.00             1.00
```

Q2: fusion inherits bigram's fix for the cross-sense false match that unigram
alone got wrong. Q6: fusion keeps unigram's win where bigram retrieved nothing.
That is complementarity doing exactly what it promises.

Now the result worth more than the headline. **Adding a third parent makes it
worse** -- MRR falls from 1.0000 to 0.9167, nDCG from 0.9940 to 0.9325 -- and the
whole loss is Q3, where dictmatch's confident wrong answer outvotes unigram's
right one. `RRF bi+dict` is no better than bigram alone, because its two parents
fail on the same queries.

More parents is not better. A parent earns its place by being right where the
others are wrong, and that is a per-query question you can answer before fusing.

## Boundary

- Six queries. `RRF uni+bi` scoring a perfect MRR says the fixture ran out of
  difficulty, not that the system is solved. The gap between fusion and its best
  parent here is far inside what six queries can resolve --
  [eval-set-sample-size.md](eval-set-sample-size.md), with queries as the unit.
- RRF discards score magnitude, so it cannot express "this parent is confident".
  Weighted RRF and learned fusion recover some of that, at the cost of parameters
  that need their own eval set.
- Fusion multiplies cost and latency by the number of parents. `nDCG gain per
  added millisecond` is the metric that decides this, not nDCG alone.
- Every parent must be indexed and maintained, including the analyzer pipeline
  each depends on. Two parents is two chances for an index to go stale.
- The parents here are two analyzers, not lexical-plus-dense. The same arithmetic
  applies with a dense parent, and that is where fusion usually earns most --
  the one query in this set with no lexical overlap at all (`动力电池供应`) is
  the case a dense parent would take.

## Cards

### 1. [mechanism] Why does reciprocal rank fusion combine rankings rather than scores?

**Answer:** Because scores from different retrievers are not comparable -- IDF is
corpus- and analyzer-relative, BM25 is unbounded, and cosine similarity lives in
`[-1, 1]`. RRF reads only positions: `sum of 1/(k + rank)`, `k` around 60.

**Why:** Summing raw scores lets the parent with the larger numeric range decide
every query. Min-max normalization patches it only while each parent's score
distribution stays stable, which the corpus and any reindex can change.

**Boundary:** Discarding magnitude also discards confidence, so RRF cannot
express "this parent is sure". Weighted variants recover that and need their own
eval set to set the weights.

**Tags:** `retrieval` `mechanism` `general-principle`

---

### 2. [decision] Your two-parent fusion beats both parents. Should you add a third retriever?

**Answer:** Only if it is right where the existing parents are wrong. In this
module's data a third parent dropped MRR from 1.0000 to 0.9167, because its
confident wrong answer outvoted a correct one on the query the others disagreed
about.

**Why:** Fusion pays on complementarity and comparable quality. A parent that
fails on the same queries as an existing one contributes a duplicate vote; a
parent much weaker overall contributes noise with voting rights.

**Boundary:** Both conditions are checkable from the per-query table before you
fuse anything -- you do not need to build the fusion to predict whether it will
help.

**Tags:** `retrieval` `decision` `general-principle`

---

### 3. [scenario] Two Chinese analyzers each retrieve documents the other misses entirely. How do you exploit that without choosing one?

**Answer:** Fuse their rankings with RRF and keep both indexes. In this module's
lab that lifts MRR above either parent, inheriting one's precision fix and the
other's only-retriever win.

**Why:** Complementary failure is the precondition for fusion to pay -- each
parent supplies the queries the other cannot reach, and rank-based combination
needs no score calibration between them.

**Boundary:** The cost is two indexes, two analyzer pipelines and roughly double
query latency. Judge it on gain per added millisecond, not on the metric alone.

**Tags:** `retrieval` `scenario` `general-principle`
