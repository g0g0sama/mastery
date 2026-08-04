# Vector similarity: dot product, cosine, and what neither means

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** vector geometry -- dot product, norms, cosine (Layer 2, Aware ->
Independent). Map evidence to graduate: "Explain why normalization changes
ranking, and show it on your data."

Learned **inside** the module that uses it, per the map's rule that a Layer 2 row
should never be the active cycle on its own.

> **Scope, stated up front.** The vectors here are sparse TF-IDF, not learned
> embeddings. The geometry transfers exactly -- magnitude, normalization, and the
> angle/length decomposition are identical in any inner-product space, including
> a 1024-dimensional embedding space. The semantics do not transfer: a real
> embedding places paraphrases near each other and these vectors cannot. Do not
> read a conclusion about embedding quality out of this module.

---

## The problem

You have vectors and you need "similar". Two functions are available, they differ
by a division, and every library defaults differently. Choosing by default means
your ranking is decided by a library author's assumption about your data.

## The wrong model

**"Dot product and cosine rank the same way -- cosine is just a normalized dot,
and normalization is monotonic, so the order is preserved."**

The last clause is the error. Dividing every score by *the same* constant would
preserve order. Cosine divides each document's score by **that document's own
norm**, which is a different divisor per document. That is not a rescaling of the
ranking; it is a different ranking.

Concretely: `dot(q, d) = |q| * |d| * cos(theta)`. The dot product scores angle
**and** magnitude together, and in a TF-IDF or bag-of-words space magnitude is
essentially document length. Rank by dot product and you have made "longer" part
of "more relevant".

## The mechanism

```text
  dot(q, d)    = sum over terms of  q_t * d_t         angle AND length
  cos(q, d)    = dot(q, d) / (|q| * |d|)              angle only, in [-1, 1]
```

Since `|q|` is constant across documents for a given query, the only term that
changes the ranking is `1 / |d|`. So:

- **Documents of near-uniform length** -> `|d|` is near-constant -> the two rank
  almost identically, and the choice does not matter.
- **Documents of varying length** -> `|d|` varies -> the two rank differently,
  and the dot product systematically prefers the long ones.

That precondition is the same one BM25's `b` parameter needs, reached from the
geometry side rather than the scoring side -- see
[bm25-baseline.md](bm25-baseline.md), where the same corpus made `b` inert.

## The experiment

`zh-retrieval-lab/vector_lab.py`.

**Predict before running: a document is added to the corpus consisting of an
existing document's text repeated three times. Under dot product and under
cosine, where does the copy rank relative to the original?**

```powershell
cd modules\zh-retrieval-lab
python vector_lab.py
```

Actual, for the query `稀土出口管制`:

```text
  dot    -> D03_x3=43.591, D03=14.530, D17=13.055, D15=4.851
  cosine -> D03=0.421, D03_x3=0.411, D17=0.216, D15=0.121
```

The tripled document contains no information the original lacks. Under the dot
product it wins by a factor of three. Under cosine the two are within 0.01 --
tripling a vector changes its length, not its direction. (Not exactly equal:
concatenating the text creates two junction bigrams at the seams, so it is very
nearly rather than perfectly a scalar multiple, and 0.01 is the size of that
artifact.)

The decomposition, printed:

```text
  D03      |d| =   9.06   dot = 14.530   cos = 0.4206
  D03_x3   |d| =  27.79   dot = 43.591   cos = 0.4114
```

Both the dot and the norm scale by ~3; their ratio does not. That ratio is the
cosine, and it is the part that carries meaning.

Then part 3, the most similar document **pairs** in the corpus:

```text
  cos = 0.1405   D16 / D17      稀土 in both, different topics
  cos = 0.1253   D14 / D17
  cos = 0.0926   D03 / D17
  cos = 0.0773   D01 / D02      中国石化 and 中国石油 -- different companies
```

Two things to take from those numbers.

**The scale is corpus-dependent.** The *nearest* pair in this corpus scores
0.14. There is no such thing as "cosine above 0.8 means related" -- a threshold
tuned on one corpus is meaningless on another, and on a different analyzer it is
meaningless on the same corpus.

**The top pairs are lexical accidents.** D01/D02 are two different companies
sharing a name prefix. A learned embedding removes accidents of this kind and
introduces its own: it will place a fluent denial next to the claim it denies,
because they are about the same thing. In both cases similarity is a hypothesis
about relevance, never a judgment of it -- which is why the relevance judgments
in [retrieval-metrics.md](retrieval-metrics.md) are written by a person.

## Boundary

- Sparse lexical vectors. Dense embeddings add behaviours not visible here --
  anisotropy, hubness (a few vectors that are near-neighbours of everything), and
  sensitivity to the pooling strategy. Those need real embeddings to study.
- Normalize once, at index time, and store unit vectors; then the dot product
  *is* the cosine and the choice disappears. Most vector databases assume you did
  this, which is why they expose "inner product" and "cosine" as separate metrics
  and quietly expect the former to be used on normalized data.
- Cosine ignores magnitude entirely, and sometimes magnitude is signal -- a
  near-empty chunk and a rich one can point the same direction. If that matters,
  it belongs in a filter or a length prior, not in the similarity function.
- Euclidean distance ranks identically to cosine **on normalized vectors** and
  differently otherwise. Check what your index normalizes before assuming which.

## Cards

### 1. [misconception] Ranking by dot product versus by cosine similarity is just a rescaling, so the order is the same. Why is that wrong?

**Answer:** Cosine divides each document's score by **that document's own norm**
-- a different divisor per document -- so it is a different ranking, not a
rescaling. A single shared constant would preserve order; a per-document one does
not.

**Why:** `dot(q,d) = |q| * |d| * cos(theta)`. Since `|q|` is constant for a given
query, `1/|d|` is the only factor that reorders, and in a bag-of-words space
`|d|` is essentially document length.

**Boundary:** When all documents have near-uniform length the two rankings do
nearly coincide -- which is why the difference can stay hidden until a corpus
with varying lengths arrives.

**Tags:** `vectors` `misconception` `general-principle`

---

### 2. [scenario] A document that is another document's text repeated three times outranks the original in your search results. What is the similarity function, and what is the fix?

**Answer:** An unnormalized dot product. It scores angle and magnitude together,
so triple the length is triple the score. Cosine -- or normalizing vectors at
index time -- makes the two rank equally.

**Why:** Repetition changes a vector's length, not its direction. Only a
similarity that divides by `|d|` is measuring the direction.

**Boundary:** Normalizing at index time and then using the plain inner product is
the usual production form, since it moves the division out of the query path
entirely.

**Tags:** `vectors` `scenario` `general-principle`

---

### 3. [best-practice] Why is a fixed cosine-similarity threshold -- "keep results above 0.8" -- unsafe as a relevance cutoff?

**Answer:** Because the scale is a property of the corpus and the representation,
not of relevance. In this module's corpus the *most* similar pair of documents
scores 0.14.

**Why:** Similarity magnitude shifts with vocabulary overlap, analyzer, dimension
and embedding model, so a threshold tuned in one setting carries no meaning in
another -- and silently changes behaviour after any reindex.

**Boundary:** Prefer a rank cutoff, or a threshold calibrated against labelled
judgments and re-checked whenever the representation changes -- pin it with the
fingerprints in [eval-set-versioning.md](eval-set-versioning.md).

**Tags:** `vectors` `best-practice` `general-principle`
