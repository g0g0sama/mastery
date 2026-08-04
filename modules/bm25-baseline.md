# Inverted indexes, TF-IDF and BM25

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** inverted indexes, TF-IDF, BM25 (Layer 6, Aware -> Independent).
Map evidence to graduate: "BM25 baseline beating your first dense attempt on
some queries."

The map's sequencing note again: **baseline before technique.** This is the
number every later retrieval result is read against.

---

## The problem

You are going to build dense retrieval, and you will get a number -- recall@5 of
0.83, say. Is that good? Without a lexical baseline the question has no answer,
and the honest situation is worse than ignorance: the baseline is often
competitive, sometimes better, and always cheaper, and you will not find that out
after committing to an index.

## The wrong model

**"BM25 is TF-IDF with extra steps."**

They agree on the skeleton -- rare terms matter more, matching terms accumulate --
and differ in two places that exist because the naive version misbehaves:

- **Term frequency saturates.** A document containing your query term twenty
  times is not twenty times more relevant than one containing it twice. BM25's
  `k1` controls how fast the gain flattens; linear tf has no such brake.
- **Length is normalized, adjustably.** A long document has more chances to match
  by accident. BM25's `b` interpolates between ignoring length entirely (`b=0`)
  and dividing it out fully (`b=1`).

The second wrong model is the one this experiment actually kills: **"BM25 with
tuned parameters beats TF-IDF, so tune the parameters."** Both parameters act on
*variance*. If your corpus has no length variance and no repeated terms, they
have nothing to act on, and tuning them is a week spent moving a number that
cannot move.

## The mechanism

The **inverted index** maps each term to the documents containing it. Scoring
then touches only documents that can match -- in this lab, 4 of 17 for a
two-term query. That reduction *is* the index; everything after it is arithmetic.

BM25 scores a query-document pair as, summed over query terms:

```text
                        tf * (k1 + 1)
  IDF(t)  *  --------------------------------------
              tf + k1 * (1 - b + b * |d| / avgdl)

  IDF(t) = ln(1 + (N - df + 0.5) / (df + 0.5))
```

Read the denominator: as `tf` grows the ratio approaches `k1 + 1` and stops --
that is saturation. The `b` term inflates the denominator for documents longer
than average, demoting them.

## The experiment

`zh-retrieval-lab/bm25_lab.py`. Standalone, stdlib only.

**Predict before running: TF-IDF cosine against BM25 on the same 6 queries and
the same analyzer -- how large is the gap, and which wins?**

```powershell
cd modules\zh-retrieval-lab
python bm25_lab.py
```

Part 1, the index doing its job:

```text
query '出口管制' -> terms ['出口', '口管', '管制']
  postings[出口] = ['D03', 'D14', 'D15', 'D17']  df=4
  postings[口管] = ['D03']  df=1
  postings[管制] = ['D03', 'D15']  df=2
candidates scored: 4 of 17 documents
```

Part 2, the comparison:

```text
  tfidf_cosine  recall@k 0.6667  MRR 0.6667  nDCG@k 0.6607
  bm25          recall@k 0.6667  MRR 0.6667  nDCG@k 0.6607
```

**Identical to four decimal places.** Not a bug. Part 3 says why:

```text
  document length in terms: min 11, median 14, max 32, avg 15.4
  term occurrences with tf > 1 across the whole corpus: 2
```

Near-uniform lengths and almost no repeated terms. Sweeping `b` across
0.0 / 0.35 / 0.75 / 1.0 and `k1` across 0.1 / 1.2 / 3.0 / 10.0 changes **nothing**
-- not a ranking, not a decimal.

Part 4 builds a corpus that does have the variance, and both parameters come
alive immediately:

```text
  lengths: S_short=5, S_long=110, S_spam=25, S_other=7

  b=0.0  (no length norm)  ['S_long', 'S_short', 'S_spam']
  b=0.75 (default)         ['S_short', 'S_long', 'S_spam']
  k1=1.2 (default)         ['S_short', 'S_long', 'S_spam']
  k1=20  (near-linear tf)  ['S_short', 'S_spam', 'S_long']
```

At `b=0` the padded document wins on raw match count. At `k1=20` the
keyword-stuffed document climbs past it. The mechanism is real and it was dormant.

The transferable result is not "BM25 equals TF-IDF". It is: **a parameter only
matters when your corpus exercises it, and which parameters those are is a
measurement, not a default.** On short, uniform news headlines, reach for the
analyzer before the parameters -- see
[chinese-segmentation.md](chinese-segmentation.md), where the same corpus shows a
33-point spread.

## Boundary

- Six queries and 17 documents cannot resolve a small difference. This fixture
  demonstrates mechanisms; effect sizes need the sample-size arithmetic in
  [eval-set-sample-size.md](eval-set-sample-size.md), with queries as the unit.
- BM25 cannot match a paraphrase. Query `动力电池供应` retrieves nothing useful
  under two of three analyzers because the phrase appears in no document. That
  is the real argument for dense retrieval, and it is one query in six here --
  measure the proportion on your own queries before deciding how much it is
  worth.
- IDF is corpus-relative, so scores are not comparable across corpora or across
  analyzers. This matters the moment you fuse rankings --
  [hybrid-retrieval-fusion.md](hybrid-retrieval-fusion.md).
- Postgres full-text search implements a variant of this with its own weighting
  and its own analyzer pipeline. Read its documentation for what it actually
  does rather than assuming these formulas; the concepts transfer, the constants
  do not.

## Cards

### 1. [mechanism] What does an inverted index contribute to retrieval that the scoring function does not?

**Answer:** It decides which documents are never scored at all -- mapping each
term to its postings list, so only documents containing a query term are
considered.

**Why:** Scoring is linear in candidates. In this module's lab a two-term query
reduces 17 documents to 4; at corpus scale that is the difference between a query
and a full scan.

**Boundary:** The index also fixes what is matchable. A term the analyzer never
produced has no postings list and is unreachable regardless of the scorer.

**Tags:** `retrieval` `mechanism` `general-principle`

---

### 2. [comparison] What do BM25's `k1` and `b` add over TF-IDF, and under what corpus conditions does each stop mattering?

**Answer:** `k1` saturates term frequency so repetition stops paying linearly;
`b` normalizes by document length. `k1` is inert when terms rarely repeat, `b`
when document lengths are uniform.

**Why:** Both act on variance. In this module's corpus -- news headlines, lengths
11 to 32 terms, two repeated terms in total -- sweeping both changes no ranking,
and BM25 ties TF-IDF to four decimals.

**Boundary:** On a corpus with real length variance the same sweep flips the top
result: at `b=0` a padded document outranks an exact short match.

**Tags:** `retrieval` `comparison` `general-principle`

---

### 3. [best-practice] Why build a BM25 baseline before evaluating a dense retriever?

**Answer:** Because a dense recall@5 of 0.83 is uninterpretable alone. The
lexical baseline is what makes it a result, and it is cheap, explainable, and
sometimes better.

**Why:** Baselines also localize the argument for the expensive option: here
exactly one query in six fails purely because the phrasing shares no characters
with any document, and that proportion is the size of the prize.

**Boundary:** The baseline must use a competitive analyzer. A BM25 baseline built
on a bad Chinese analyzer understates lexical retrieval and flatters whatever you
compare it to.

**Tags:** `retrieval` `best-practice` `general-principle`
