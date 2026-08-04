# Full-text search on Chinese

**Micro module.** One mechanism, one experiment, three cards. Runs against
[store-lab/](store-lab/).

**Capability:** Postgres full-text search (Layer 1c, Aware -> Independent), with
the analyzer row from Layer 6 (**Deep**). Map evidence: "Chinese-language FTS
with the right analyzer, measured recall."

---

## The problem

[chinese-segmentation.md](chinese-segmentation.md) measured what segmentation
does to recall in a BM25 implementation written by hand. This module asks the
question the project actually faces: what does the *database* do, out of the
box, on the same corpus and the same six queries.

The answer is worse.

## The wrong model

**"Full-text search is a feature the database has. Turn it on, tune the ranking
later."**

```text
strategy          recall@5     MRR   nDCG@5
default              0.000   0.000    0.000
```

Zero. Not poor ranking -- no results at all, for every query.

## The mechanism

`unicode61`, the FTS5 default, splits on character *class*: it breaks at
punctuation and at script boundaries. Han characters are all one class, so a
sentence with no spaces and no punctuation is **one token**. The seventeen-
document index contains seventeen distinct terms, the longest 33 characters
long. It is not a word index; it is a list of whole sentences, and nothing
matches unless the query is an entire document.

Postgres fails identically: `to_tsvector('simple', '稀土出口管制')` yields one
lexeme, for the same reason, and there is no bundled `'zh'` configuration.

Four remedies, scored on the same judged query set:

```text
strategy          recall@5     MRR   nDCG@5   note
default              0.000   0.000    0.000   one token per sentence
trigram              0.292   0.500    0.414   built-in, substring matching
unigram-split        1.000   0.917    0.943   every character a term
bigram-split         0.667   0.667    0.661   the standard CJK baseline
dict-split           0.625   0.583    0.583   forward maximum matching
```

Two of those rows need reading carefully. `unigram-split`'s perfect recall is a
property of a 17-document corpus -- every character matches something and there
is nothing for the noise to bury; the precision side of that trade is in
[chinese-segmentation.md](chinese-segmentation.md), and together they argue for
bigrams as the default. `trigram` looks weak because it does *literal substring
matching*: excellent for "is 出口管制 inside this document", useless for "is
this document about 动力电池 supply", and four of these six queries are
paraphrases. Trigram is the right tool for identifier and code search.

**Two further defaults, neither of them chosen.**

The operator between two bare terms is `AND` -- in FTS5 and in Postgres's
`plainto_tsquery`:

```text
strategy          recall@5 (OR)  recall@5 (AND)
unigram-split             1.000           0.292
bigram-split              0.667           0.292
dict-split                0.625           0.292
```

On segmented Chinese a four-character query becomes three or four *mandatory*
terms. Neither operator is right in general -- AND is precision-first and
correct for a filter, OR with a good ranker is recall-first and correct for
search. The failure is having it decided by not writing an operator.

And the query must be tokenized exactly as the document was:

```text
query 稀土永磁 -> segmented as ['稀土', '永', '磁']
dict-split, query segmented   ->  ['D14', 'D17', 'D03']
dict-split, query raw         ->  []
```

A silent zero, not an error. Any pipeline that segments at write time and
forgets at read time -- or changes the dictionary without reindexing -- gets
exactly this, reported months later as "search got worse". It is the same shape
as the failure in [eval-set-versioning.md](eval-set-versioning.md): two sides of
a comparison that must be produced by the same code, with nothing in the schema
forcing it.

## The experiment

```powershell
cd modules\store-lab
python fts_lab.py
```

## Boundary

- **What transfers to Postgres:** the section-1 failure, exactly and for the
  same reason; the analyzer/query symmetry requirement; and the AND default via
  `plainto_tsquery`.
- **What does not:** the `trigram` tokenizer (Postgres's `pg_trgm` is a
  similarity operator with different semantics, not an FTS parser), and ranking
  (`bm25()` here, `ts_rank_cd` there, different formulas). The Postgres remedy
  is an extension -- `zhparser` or `pg_jieba` -- which is an operational
  decision, not a configuration one, on managed hosting.
- **Six queries over seventeen documents cannot rank these strategies.** The
  0.000 is real and the ordering of the other four is fixture noise. What the
  numbers support is "the default is unusable"; what they do not support is
  "bigram beats dictmatch".
- **Segmentation is not the only lever.** Stopwords, normalization
  (traditional/simplified, full-width/half-width), and synonym expansion all sit
  in the same pipeline and all have to be applied identically at write and read
  time. Each one added is another opportunity for the symmetry failure above.
- **This is lexical retrieval only.** The paraphrase query 动力电池 matches no
  document under any tokenization, which is the honest argument for a dense
  retriever alongside -- see [hybrid-retrieval-fusion.md](hybrid-retrieval-fusion.md).

## Cards

### 1. [failure] You enable your database's built-in full-text search, the tests pass on English fixtures, and every Chinese query returns nothing. What happened?

**Answer:** The default tokenizer splits on character class. Han script is one
class with no spaces, so an entire sentence becomes a single token and only an
exact whole-document query can match.

**Why:** Measured: recall@5 of 0.000 across six queries, and an index holding 17
terms for 17 documents with the longest term 33 characters long. FTS5's
`unicode61` and Postgres's `simple`/`english` configurations both do this.

**Boundary:** It reads to a user as "no results", which is indistinguishable
from a genuinely empty corpus. Nothing errors, nothing logs, and the feature
ships.

**Tags:** `search` `failure` `project-specific`

---

### 2. [decision] You segment Chinese text before indexing it. What else must change, and what happens if it does not?

**Answer:** The query path must use the identical segmenter, and the index must
be stamped with the analyzer version so a mismatch can be refused. Otherwise the
index holds terms the query can never produce.

**Why:** In the lab, a raw query against a segmented index returned an empty
result while the same query segmented returned the correct three documents. No
error was raised in either case.

**Boundary:** The failure also arrives without a code change -- adding a word to
the dictionary changes segmentation and silently invalidates the existing index
for those terms. Reindexing is part of the dictionary change, not a follow-up.

**Tags:** `search` `decision` `project-specific`

---

### 3. [misconception] Your search returns too few results on multi-word Chinese queries. Is the tokenizer the first thing to check?

**Answer:** Check the boolean operator first. The implicit operator between bare
terms is AND in both FTS5 and `plainto_tsquery`, so a segmented four-character
query becomes three or four mandatory terms.

**Why:** In the lab, switching AND to OR moved recall@5 from 0.292 to between
0.625 and 1.000 on identical indexes and identical tokenization -- a larger
effect than the difference between two reasonable segmenters.

**Boundary:** OR is not simply better. AND is correct for a filter, and OR is
only safe when the ranker can push the accidental matches down -- which is a
statement about your ranking function, measured on judged queries, not an
assumption.

**Tags:** `search` `misconception` `general-principle`
