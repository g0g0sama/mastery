# Matmul and shapes

**Micro module.** One mechanism, one experiment, three cards. Runs against
[stats-lab/](stats-lab/), over the corpus in [zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** Matrix multiplication and shapes (Layer 2, Aware -> Working).
Map evidence: "Predict every tensor shape in a forward pass before running it."

---

## The problem

Shape bugs have a reputation for being cheap: they raise, you fix them, you
move on. That reputation is earned by the ones that raise. The ones that matter
are the ones where two shapes happened to be compatible, nothing raised,
nothing produced a NaN, every assertion a reviewer would write passed, and the
answer changed.

There is no array library here, so the lab writes out the twenty lines of
broadcasting that NumPy, PyTorch and JAX agree on. That was not incidental:
**the first version of the rule in this lab padded on the right instead of the
left**, which made the exact bug section 2 is about invisible to the checker
written to detect it. The comment recording that is still in the file.

## The mechanism

**The shape table for a real forward pass** -- six Chinese queries against
seventeen documents -- and the same arithmetic in the shape of one attention
head. Predict the column before reading it; that is the whole exercise.

```text
step                               shape        step                     shape
Q  query matrix                 (6, 240)        X  tokens x model   (12, 512)
D  document matrix             (17, 240)        W_q                 (512, 64)
D.T                            (240, 17)        Q = X @ W_q          (12, 64)
S = Q @ D.T                      (6, 17)        K.T                  (64, 12)
query norms, keepdims             (6, 1)        scores = Q @ K.T     (12, 12)
doc norms, keepdims              (1, 17)        rowmax, keepdims      (12, 1)
S / (qn * dn)                    (6, 17)        softmax(scores)      (12, 12)
top-1 index per query               (6,)        out = P @ V          (12, 64)
```

The one worth naming: `scores` is (tokens x tokens) and contains no model
dimension at all, which is why context length costs quadratic memory and width
does not.

**The subtraction that raises, and the one that does not.** Softmax needs the
row maximum subtracted for stability. Written as an `(n,)` instead of an
`(n,1)`, the rule left-pads it to `(1,n)` and aligns it against the last axis:

```text
scores (12,12), rowmax (12,)   -- square       -> (12, 12)   no error
scores (12,64), rowmax (12,)   -- not square   -> raises: 64 and 12
scores (12,12), rowmax (12,1)  -- correct      -> (12, 12)   no error
```

**The square case is the one that ships.** It subtracts the maximum of column j
from row i instead of the maximum of row i. What the resulting tensor looks
like:

```text
check                                correct       buggy
every row sums to 1                        1           1
all entries in [0,1]                       1           1
no NaN or inf                              1           1
argmax per row unchanged                  --       10/12
max absolute difference                   --    0.031634
```

Every property a reviewer would assert holds, because softmax renormalises
afterwards. The distribution is different and on two of twelve rows the argmax
moved. In a self-attention layer that is a different token attended to, in a
model that still produces fluent output.

**Whether a shape bug is detectable is a property of the data.** The second bug
computes the document norms by reducing over the wrong axis -- one norm per
*term* instead of per document. It does not raise, because there are 240 terms
and 17 documents, so indexing the term array by document id succeeds and
silently returns the norm of an unrelated column.

```text
--- bigram analyzer: 240 terms, 2.0 candidate documents per query ---
normalisation         recall@5   nDCG@5     MRR  same ranking  same top-1
correct                 0.6667   0.6607  0.6667           6/6         6/6
doc_only                0.6667   0.6607  0.6667           6/6         6/6
none                    0.6667   0.6607  0.6667           6/6         6/6
wrong_axis              0.6667   0.6607  0.6667           6/6         6/6

--- unigram analyzer: 184 terms, 4.5 candidate documents per query ---
correct                 1.0000   0.9432  0.9167           6/6         6/6
doc_only                1.0000   0.9432  0.9167           6/6         6/6
none                    1.0000   0.9670  1.0000           1/6         4/6
wrong_axis              1.0000   0.9055  0.9167           0/6         3/6
```

Under the bigram analyzer every arm is identical to four decimal places and a
smoke test passes cleanly -- each query retrieves about two documents and there
is nothing to reorder. Change one line of the analyzer and the same bug
reorders **every** query and moves the top result on half of them. A test suite
that exercises a sparse path cannot see a bug that needs candidates to express
itself.

The table also contains a theorem, and it is worth separating from the bug:
`correct` and `doc_only` are identical under both analyzers because dividing
all of one query's scores by one constant cannot reorder that query's own
results. Query-side normalisation matters only when scores are compared across
queries or against a threshold -- which is exactly what a retrieval cut-off is.

**What catches them:**

```text
check                             bug                          result
shapes broadcast at all           (12,64) against (12,)        caught by the runtime
output sums to 1                  the wrong-axis softmax       NOT caught
output in [0,1], finite           the wrong-axis softmax       NOT caught
assert m.shape == (n, 1)          the wrong-axis softmax       caught, 1 line
assert len(d_norm) == n_docs      wrong-axis normalisation     caught, 1 line
```

Both survivors need the same one-line assertion class: state the shape you
meant, next to the operation. The runtime can only check *consistency*; it has
no way to know which of two compatible shapes was intended, and a square matrix
makes every wrong answer compatible.

## The experiment

```powershell
cd modules\stats-lab
python shapes_lab.py
```

## Boundary

- **The attention block is declared sizes only.** Nothing is trained and no
  weights exist; it is there because the broadcasting rule is the same rule and
  the (tokens x tokens) shape is the one people mis-predict.
- **The bug magnitudes are corpus-specific.** That the wrong-axis normalisation
  reorders 6/6 queries under one analyzer and 0/6 under another is a property
  of how many documents each query matches, which is the whole point of the
  section but not a number to carry anywhere.
- **`none` scoring higher than `correct`** under the unigram analyzer is a
  dot-versus-cosine result, not a shape result; it belongs to
  [vector-similarity.md](vector-similarity.md).
- **Nothing here covers device placement, dtype, strides, or contiguity**,
  which are the other half of real tensor bugs and need a real array library to
  demonstrate.
- **No performance claim is made.** The matmul is pure Python and slow, and
  counting its cost would measure the interpreter. See
  [memory-bandwidth-roofline.md](memory-bandwidth-roofline.md) for the arithmetic
  that matters.

## Cards

### 1. [failure] Why is a square matrix the dangerous case for a broadcast bug?

**Answer:** Because both wrong orientations are compatible. In the lab, `scores
(12,64)` against a `rowmax (12,)` raises immediately -- the rule left-pads to
`(1,12)` and 64 does not match 12. The same mistake on `scores (12,12)`
broadcasts cleanly and subtracts the column maximum from each row instead of
the row maximum. Row sums stayed 1, values stayed in [0,1], nothing was NaN,
and the argmax moved on 2 of 12 rows.

**Why:** Broadcasting checks consistency, not intent. When the two axes have
equal length there is no inconsistency to find.

**Boundary:** Attention scores, confusion matrices, pairwise similarity and
adjacency are all square by construction, so this is not a rare shape -- it is
the shape most of the risky code operates on. Test with an asymmetric size
(n != m) even when production is square; that turns a silent bug into an
exception.

**Tags:** `shapes` `broadcasting` `failure` `general-principle`

---

### 2. [mechanism] A reduction over the wrong axis passed every test. What made it invisible, and what would have made it visible?

**Answer:** The data. In the lab, per-term norms were used in place of
per-document norms -- no error, because 240 > 17 so the index is valid. Under
the bigram analyzer each query retrieved 2.0 documents, every metric was
identical to four decimals, and the suite passed. Under the unigram analyzer
each query retrieved 4.5 documents and the same bug reordered 6/6 queries and
changed the top result on 3/6.

**Why:** A bug in a ranking can only show up if there is something to reorder.
A sparse retrieval path returns too few candidates for the ordering to carry
information.

**Boundary:** The general lesson is not "use the unigram analyzer" -- it is that
a green suite on a sparse fixture is weak evidence. Assert the length of a
reduced array against what it should index (`assert len(d_norm) == n_docs`),
which costs one line and does not depend on the data at all.

**Tags:** `shapes` `testing` `retrieval` `mechanism` `general-principle`

---

### 3. [misconception] Shape assertions are noise in code that already runs.

**Answer:** They are the only thing that catches the class of bug that already
runs. The runtime raised on one of the three bugs in the lab; the two that
survived were both caught by a single-line `assert x.shape == (n, 1)` next to
the operation.

**Why:** The runtime enforces consistency between operands. It cannot enforce
intent, and every silent shape bug is precisely a case where the intended shape
and an unintended one are both consistent.

**Boundary:** The assertion has to state the shape you *meant*, not re-derive it
from the tensor -- `assert m.shape == (n, 1)` works, `assert m.shape[0] ==
n` does not, since that is what already held. Named dimensions or a shape-typing
library do this systematically; a comment does not.

**Tags:** `shapes` `assertions` `misconception` `general-principle`
