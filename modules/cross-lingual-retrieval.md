# Cross-lingual retrieval

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/), the same fixture as the five Layer 6
modules before it.

**Capability:** multilingual and cross-lingual retrieval (Layer 6, `-` ->
**Deep**). Map evidence to graduate: "zh query -> en document retrieval,
scored." This module scores it on 16 documents, which is exposure, not the
graduate evidence -- that needs Sinoscope's own corpus and judgments.

**Gate:** embedding spaces and similarity. Partly met by
[vector-similarity.md](vector-similarity.md); the geometry is in place, the
learned semantics are not, and this module is built so that gap stays visible.

---

## The problem

Sinoscope's sources are Chinese. Some of what it must retrieve is not --
English filings, wire copy, supplier documentation. A query typed in Chinese
against an English corpus does not score badly. It scores **zero**:

```text
system                recall@5     MRR   nDCG@5
A zh-lexical            0.0000  0.0000   0.0000
```

Not a tuning problem. The query and the corpus share no character, so the
inverted index has nothing to intersect. Every parameter in
[bm25-baseline.md](bm25-baseline.md) and every analyzer in
[chinese-segmentation.md](chinese-segmentation.md) is irrelevant here, because
they all operate after a term match that never happens.

## The wrong model

**"Cross-lingual retrieval is a translation problem."**

It is tempting because the first fix works. Translate the query, run BM25,
recall goes from 0.00 to 0.83, and it looks solved. It is not, and the reason is
worth more than the fix: translation is the easy half of the gap. The hard half
is that two documents about the same thing use different words **within** a
language, and translating merely relocates you into a language where you still
have that problem -- now with one guessed surface form instead of the several
the corpus might use.

The second wrong model is the mirror image, and more expensive: **"a
multilingual embedding removes the need for lexical retrieval."** It does not.
It fails precisely where news queries live -- abbreviations, tickers, company
aliases -- and it fails silently, returning a shorter vector rather than an
error.

## The mechanism

Three systems, and each is a different theory of where the gap is:

| System | Bridge | Fails when |
|---|---|---|
| **Query translation + BM25** | a glossary, applied before the index | the corpus uses a different word for the translated concept |
| **Shared embedding space** | both languages projected into one vector space | the query names an entity the space never learned |
| **Fusion of both** | rank-level, no shared scale needed | the parents fail on the same queries |

The lab's shared space is a hand-typed concept lexicon, which is a bilingual
dictionary in a costume. That is stated at the top of `bilingual.py` and it
matters: what transfers to a real encoder is the geometry and the failure
shapes, not the coverage. A real encoder has an opinion about every string, and
its gaps are invisible rather than listed in a `dict` literal.

## The experiment

```powershell
cd modules\zh-retrieval-lab
python cross_lingual_lab.py
```

**Predict before running.** Query translation is correct English every time in
this fixture -- check the printed translations in section 3 and you will agree
with all six. On how many of the six queries does correct translation still
fail to put the right document first?

Actual:

```text
system                recall@5     MRR   nDCG@5
A zh-lexical            0.0000  0.0000   0.0000
B translate+BM25        0.8333  0.7500   0.7645
C shared space          1.0000  0.8889   0.9107
D RRF(B,C)              1.0000  0.9167   0.9432
```

```text
query                B translate+BM25   C shared space   D RRF(B,C)
Q1 中石化深圳投资                 1.00             0.33         1.00
Q2 出口管制                      0.50             1.00         0.50
Q6 芯片制裁                      0.00             1.00         1.00
```

Two of six. And the two failures have nothing in common:

**Q6 -- the vocabulary gap survives translation.** `芯片制裁` becomes `chip
sanction`, which is correct, and retrieves nothing. The target document reads
*"The US Commerce Department adds SMIC to the entity list"*: sanctions are
expressed in this domain as **entity list**, and the chip is **named** rather
than described. No translator error, no analyzer error, zero results. The
shared space maps both `制裁` and `entity list` onto one concept and lands the
document at rank 1.

**Q1 -- the entity gap defeats the shared space.** `中石化` is the everyday
abbreviation for Sinopec. It is not in the concept lexicon, so the space quietly
drops it and ranks **PetroChina** first -- the same shared-prefix distractor as
the monolingual corpus, arriving by a different route. The glossary holds the
alias, so translation resolves the entity outright and scores 1.00.

**Q2 -- the sense collision crosses the boundary unharmed.**

```text
E03  cos=0.7071  ['CONTROL', 'EXPORT', 'GOVERNMENT', 'RARE_EARTH']   (relevant)
E15  cos=0.5000  ['AVIATION', 'CONTROL', 'EXPORT', 'SHENZHEN', ...]  (not relevant)
E14  cos=0.3536  ['EXPORT', 'MAGNET', 'PRICE', 'RARE_EARTH']         (relevant)
```

*Air traffic control ... affect export freight* outranks a genuinely relevant
document, because it matches **both** query concepts in the wrong senses while
the relevant one matches a single concept in the right sense. Two wrong matches
beat one right match. A concept vector records that a concept is present and
nothing about which reading of it -- and unlike the monolingual case, you can no
longer grep for the term that caused it.

## Boundary

- **Fusion bought the aggregate by losing a query.** RRF beats both parents at
  0.9432, and on Q2 it inherits translation's error and drops the shared space's
  1.00 to 0.50. Report per-query or you will ship a system that is better on
  average and worse on the query class you care about.
- **The precondition for fusion is disjoint failure**, and it is visible here:
  translation fails Q6 on vocabulary, the shared space fails Q1 on entities.
  Two systems that fail on the same queries fuse to no gain and two indexes of
  cost. Check the per-query table before adding a second retriever, not after.
- **Six queries.** These are large effects (0.00 vs 0.83) and the fixture can
  carry them. The 0.9107 vs 0.9432 difference it cannot -- see
  [eval-set-sample-size.md](eval-set-sample-size.md).
- **The real system has a fourth option this lab cannot show:** translate the
  *documents* at index time. It costs a batch translation of the whole corpus
  and buys monolingual retrieval forever after, with all the analyzer control
  that implies. For a corpus that changes slowly and queries that do not, it is
  usually the right answer, and it is the one people skip because it is less
  interesting than the other three.

## Cards

### 1. [misconception] A Chinese query scores 0.00 against an English corpus. You translate the query and recall jumps to 0.83. Why is the problem not solved?

**Answer:** Translation closes the language gap, not the vocabulary gap. The
corpus can express the translated concept with a different word, and a
single-best translation commits to one surface form.

**Why:** In the lab, `芯片制裁` translates correctly to `chip sanction` and
retrieves nothing, because the target document says *entity list* and names
*SMIC*. No component made an error and the result is zero.

**Boundary:** The fix is not a better translator -- it is a second retrieval
path that matches on meaning, or a translator that emits alternatives rather
than one string.

**Tags:** `retrieval` `multilingual` `misconception` `general-principle`

---

### 2. [failure] A multilingual embedding beats query translation on aggregate nDCG. Which query class should you check before replacing translation with it?

**Answer:** Queries naming entities, abbreviations, tickers, or aliases. The
shared space fails these and fails silently -- it returns a shorter vector, not
an error.

**Why:** In the lab, `中石化` is absent from the concept lexicon, so the query
`中石化深圳投资` retrieves **PetroChina** at rank 1 and the correct Sinopec
document at rank 3, while translation with an alias table scores 1.00.

**Boundary:** This is why the two fuse well: they fail on disjoint causes.
Fusion between two systems that fail on the same queries buys nothing and costs
a second index.

**Tags:** `retrieval` `multilingual` `failure` `general-principle`

---

### 3. [mechanism] Retrieving into a shared multilingual space, an irrelevant document outranks a relevant one. Both share terms with the query. What is the first explanation to test?

**Answer:** A sense collision -- the irrelevant document matches more query
concepts than the relevant one, in the wrong senses.

**Why:** A concept or embedding dimension records that a meaning is present, not
which reading of it. Two wrong matches outscore one right match. The lab's
*air traffic control ... export freight* document beats a genuine export-controls
document on exactly this arithmetic.

**Boundary:** In a lexical index you can grep the offending term and fix the
analyzer. Once both languages are projected into a vector space the collision is
still there and the term that caused it is not recoverable from the score --
which is the real cost of moving retrieval into an embedding.

**Tags:** `retrieval` `multilingual` `mechanism` `general-principle`
