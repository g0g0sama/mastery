# Analyzers and Chinese segmentation

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** analyzers and Chinese segmentation (Layer 6, - -> **Deep**). Map
evidence to graduate: "Measured recall difference across segmentation choices."

This is a Deep target and part of the differentiating capability on the map --
everything Chinese routes through this decision. This module is the
Aware-to-Working step; Deep needs the measurement repeated on Sinoscope's own
corpus with a real segmenter.

---

## The problem

`中国石化宣布在深圳新建研发中心` is fourteen characters and no spaces. Before
anything can be indexed, something has to decide where the terms are -- and
unlike English, where whitespace hands you a defensible default, in Chinese that
decision is a model with failure modes.

Get it wrong and no scoring function can recover: a term the analyzer never
produced has no postings list and is unreachable.

## The wrong model

Two of them, and they fail in opposite directions.

**"Just split into characters."** Maximum recall, no notion of a word. `中国` now
matches every document containing 中 or 国 anywhere, in any sense. Precision
collapses in a way that aggregate metrics on a small set will hide from you.

**"Use a word segmenter, that is what they are for."** A dictionary-based
segmenter is only as good as its dictionary, and it fails hardest on exactly the
vocabulary you care about: domain compounds, new company names, and
abbreviations. `稀土永磁` is not in the lab dictionary and shatters into
`稀土 / 永 / 磁`; `中石化`, the everyday abbreviation for Sinopec, shatters into
three characters and drags an unrelated document to rank 1.

The honest default is **character bigrams** -- overlapping two-character terms.
No dictionary to go stale, far more selective than unigrams. It is what you
should beat, not what you should assume.

## The mechanism

| Analyzer | `中国石化宣布` becomes | Trades |
|---|---|---|
| unigram | 中 国 石 化 宣 布 | recall for precision, absolutely |
| bigram | 中国 国石 石化 化宣 宣布 | index size for robustness; no dictionary |
| dictmatch | 中国石化 宣布 | precision for coverage; fails out of vocabulary |

Bigrams work because a two-character window is long enough to be selective and
short enough to survive any segmentation disagreement -- a query and a document
that segment the same span differently still share bigrams across the boundary.

## The experiment

`zh-retrieval-lab/segment_lab.py`. BM25 held constant, only the analyzer varies.

**Predict before running: rank the three analyzers on recall@5, MRR and nDCG@5.**

```powershell
cd modules\zh-retrieval-lab
python segment_lab.py
```

Aggregate:

```text
analyzer      recall@5     MRR   nDCG@5
unigram         1.0000  0.9167   0.9432
bigram          0.6667  0.6667   0.6607
dictmatch       0.6250  0.5833   0.5834
```

The crudest analyzer wins every column, by 33 points of recall. If the module
stopped here it would have taught you something false.

Per query, with X marking a top result that is not relevant:

```text
query                unigram          bigram         dictmatch
Q1 中石化深圳投资      RR 1.00 D01     RR 1.00 D01     RR 0.50 D09 X
Q2 出口管制           RR 0.50 D15 X   RR 1.00 D03     RR 1.00 D03
Q3 动力电池供应        RR 1.00 D04     RR 0.00 --  X   RR 0.00 D17 X
Q4 光伏减产           RR 1.00 D11     RR 1.00 D11     RR 1.00 D11
Q5 稀土永磁           RR 1.00 D14     RR 1.00 D14     RR 1.00 D14
Q6 芯片制裁           RR 1.00 D07     RR 0.00 --  X   RR 0.00 --  X
```

Unigram's margin is Q3 and Q6. The script prints what it matched on:

```text
  Q3 动力电池供应  ->  D04  宁德时代与宝马集团签署长期供货协议
    unigram    matched on ['供']
  Q6 芯片制裁      ->  D07  美国商务部将中芯国际列入实体清单
    unigram    matched on ['芯']
```

**A single character each.** 供 out of 供货协议, 芯 out of 中芯国际. Two of six
queries were won by a character collision, and both happen to be right. On Q2 the
same behaviour is wrong and visible: unigram ranks D15 first --
`深圳机场空域管制调整影响出口货运`, where 管制 means air traffic control and 出口
means export freight -- above the document that is actually about export
controls.

So the aggregate ranking is real *and* it is not evidence that unigram retrieves
better. It is evidence that on a 17-document corpus, recall dominates the metric
and lucky collisions are indistinguishable from matches. On a corpus of a hundred
thousand documents those collisions multiply and the precision cost that is
currently one query in six becomes the whole system.

The other two failures are the ones to remember, because they are properties of
the method rather than of this fixture:

```text
  dictmatch segments 中石化深圳投资 as ['中','石','化','深圳','投资']
  dictmatch segments 稀土永磁      as ['稀土','永','磁']
```

Abbreviation and out-of-vocabulary compound. Both are where a domain lives.

## Boundary

- **This does not license unigram.** Six queries, 17 documents, one labeller. The
  aggregate is dominated by recall because there is nowhere for a false match to
  hide. Re-run on your own corpus before choosing; the per-query table is the
  output that decides, not the mean.
- A real segmenter (jieba, pkuseg, a Postgres extension) is far better than this
  lab's maximum-matching toy, and shares its failure mode: an out-of-vocabulary
  domain term. User dictionaries exist precisely for this and must be maintained.
- The analyzer must be **identical at index time and query time**. A mismatch
  fails silently -- no error, just nothing found.
- Bigrams roughly double index size versus words, and unigrams inflate postings
  lists severely. That is a real cost at scale and invisible at 17 documents.
- Do not choose one. Fusing analyzers beats every single one here --
  [hybrid-retrieval-fusion.md](hybrid-retrieval-fusion.md).

## Cards

### 1. [comparison] Compare character unigrams, character bigrams and dictionary segmentation for Chinese retrieval. What does each trade?

**Answer:** Unigrams maximize recall and destroy precision -- any shared
character matches. Dictionary segmentation is precise on in-vocabulary text and
fails on abbreviations and new compounds. Bigrams need no dictionary and are
selective enough to be the default you must beat.

**Why:** A two-character window is long enough to be discriminating and short
enough to survive segmentation disagreement, since a query and a document still
share bigrams across a boundary they split differently.

**Boundary:** Bigrams roughly double index size against word terms, and unigrams
inflate postings lists badly -- costs invisible on a small corpus.

**Tags:** `retrieval` `comparison` `general-principle`

---

### 2. [failure] Your crudest Chinese analyzer wins every aggregate retrieval metric on a 17-document evaluation. What must you check before adopting it?

**Answer:** Which terms actually produced each win, per query. In this module's
data two of six queries were won on a single shared character -- 供 and 芯 -- and
one query was lost by ranking a cross-sense false match first.

**Why:** On a small corpus there is nowhere for a false match to hide, so recall
dominates the aggregate and lucky collisions are indistinguishable from
retrieval. Both effects invert as the corpus grows.

**Boundary:** The fix is not a different aggregate metric -- it is per-query
inspection plus a corpus large enough that precision has somewhere to fail.

**Tags:** `retrieval` `failure` `general-principle`

---

### 3. [mechanism] Why does a dictionary-based Chinese segmenter fail hardest on exactly the terms a domain system cares about?

**Answer:** Because domain vocabulary is what dictionaries lack -- new company
names, technical compounds, and everyday abbreviations are all out of vocabulary
and shatter into single characters.

**Why:** Maximum matching falls back to characters on an unmatched span, so
`稀土永磁` becomes `稀土 / 永 / 磁` and the abbreviation `中石化` becomes three
characters that then match unrelated documents strongly.

**Boundary:** User dictionaries fix named cases and must be maintained as an
ongoing obligation; they cannot fix the general case, which is why bigrams
survive as a fallback or a fusion partner.

**Tags:** `retrieval` `mechanism` `general-principle`
