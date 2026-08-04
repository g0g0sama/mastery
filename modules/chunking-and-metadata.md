# Chunking and metadata design

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** chunking and metadata design (Layer 6, Aware -> **Deep**). Map
evidence to graduate: "Structure-aware chunking beating fixed-size, measured."

---

## The problem

Retrieval returns chunks, not documents. So before any index exists, something
decided where each document was cut -- and a fact cut in half exists in no chunk.
It is not ranked badly. It is **absent**, and no scorer, no reranker and no
larger `k` can recover it.

This is the earliest irreversible decision in a retrieval system and it is
usually made by a default parameter in a library.

## The wrong model

**"Chunk size is a tuning knob -- try 256, try 512, see which scores better."**

Size is the *third* question. The first is where the boundaries fall, and the
second is what context the chunk loses by being separated from its document. A
fixed-size chunker cuts mid-sentence and mid-fact regardless of its size; making
it bigger reduces how often, and never fixes what happens when it does.

The related error: **"a chunk is a piece of text."** A chunk is a piece of text
*plus whatever context you attach to it*. Cut a section body away from its
heading and a query phrased in the heading's vocabulary can no longer reach it,
even though the answer is sitting in the chunk.

## The mechanism

Four strategies, in increasing respect for the document:

| Strategy | Boundaries at | Cost |
|---|---|---|
| fixed-size | arbitrary character offsets | cuts facts in half |
| fixed + overlap | arbitrary, but duplicated | index size, duplicate hits |
| structure-aware | headings, then sentences | needs parseable structure |
| structure + metadata | as above, heading carried into the chunk | slight dilution of the body |

The measurement has to be **strategy-independent**, or you cannot compare them:
chunk ids differ between strategies, so chunk-id judgments are uncomparable by
construction. The fix is to judge an **answer span** -- a chunk is relevant if it
*contains* the answer text. That makes "the span was cut in half" a measurable
outcome rather than an invisible one.

## The experiment

`zh-retrieval-lab/chunk_lab.py`, over three long structured Chinese documents
with seven answer-span queries.

**Predict before running: how many of the seven answer spans survive a 60-character
fixed chunker with no overlap?**

```powershell
cd modules\zh-retrieval-lab
python chunk_lab.py
```

Actual:

```text
strategy                  chunks  avg len  answer R@1    R@3    MRR
fixed-60, no overlap          10     51.6      0.4286 0.5714 0.5000
fixed-60, overlap 20          14     51.9      0.7143 1.0000 0.8095
structure-aware               19     23.8      0.7143 1.0000 0.8095
structure + heading           19     31.1      0.8571 1.0000 0.9048
```

Per query, where SPLIT means the span exists in no chunk at all:

```text
query                                fixed     overlap   structure    str+head
稀土管制何时实施                             SPLIT          ok          ok          ok
稀土管制过渡期交付期限                        ok +hit     ok +hit     ok +hit     ok +hit
首批纳入名单的企业                          ok +hit     ok +hit     ok +hit     ok +hit
宁德时代新产线年产能                         ok +hit     ok +hit     ok +hit     ok +hit
电池价格如何调整                             SPLIT     ok +hit     ok +hit     ok +hit
实体清单对成熟制程的影响                            ok          ok     ok +hit     ok +hit
稀土管制实施时间                             SPLIT     ok +hit          ok     ok +hit
```

**Three of seven answer spans are destroyed by the fixed chunker.** Not
misranked -- destroyed. Those three queries have a ceiling of zero no matter what
is done downstream, and nothing in a recall@k number explains why.

Then two results that are easy to misread. Overlap and structure-aware post
**identical aggregates** (0.7143 / 0.8095) and are not the same system: overlap
wins `稀土管制实施时间`, structure-aware wins `实体清单对成熟制程的影响`. Same
number, different failures -- the same shape as the two extraction systems in
[extraction-eval-sets/](extraction-eval-sets/), and the reason the per-query
table is the report.

And the metadata result. `structure + heading` differs from `structure-aware` by
one thing -- each chunk carries its section heading -- and wins exactly the query
phrased in heading vocabulary: `稀土管制实施时间` against the section 【实施时间】,
whose body sentence never contains the word 时间. That is the whole argument for
chunk metadata, and it is worth one query in seven here.

## Boundary

- Seven queries and three documents. This demonstrates mechanisms; effect sizes
  need many more -- [eval-set-sample-size.md](eval-set-sample-size.md).
- Structure-aware chunking **requires structure**. These documents have explicit
  section markers; scraped HTML, OCR output and plain-text filings often do not,
  and a structure-aware chunker over unstructured input degrades to a sentence
  splitter. Check what your ingestion actually preserves before designing around
  headings.
- Sentence splitting in Chinese is not trivial. Splitting on 。 is a reasonable
  first pass and mishandles quotations, enumerations and abbreviations.
- Overlap costs index size and produces duplicate near-identical hits that
  consume slots in the top-k. Deduplicate after retrieval or the overlap eats
  your context budget.
- Smaller chunks raise answer recall and lower the context each hit carries.
  Retrieval recall is not the objective -- what the downstream model can do with
  the chunk is. That end-to-end measurement is a later cycle.
- Answer-span judgments only work for extractive questions. A query whose answer
  is synthesized across sections has no single containing chunk, and this
  measurement will call every strategy wrong.

## Cards

### 1. [failure] Your retrieval evaluation shows several queries at zero recall regardless of `k` or scorer. What should you check about the index before touching retrieval?

**Answer:** Whether the answer text survives chunking at all. A fixed-size
chunker cuts facts across boundaries, and a span that exists in no chunk is
unretrievable at any `k` by any scorer.

**Why:** Chunking happens before indexing, so it sets a hard ceiling nothing
downstream can lift. In this module's data a 60-character fixed chunker destroys
three of seven answer spans.

**Boundary:** Diagnose it by judging answer spans rather than chunk ids -- span
judgments are strategy-independent and make "the fact was cut in half" a visible
outcome.

**Tags:** `retrieval` `failure` `general-principle`

---

### 2. [mechanism] Why does attaching a section heading to each chunk improve retrieval, and what does it cost?

**Answer:** Because the chunk body often does not contain the vocabulary the
section title supplies, so a query phrased in heading terms cannot otherwise
reach it.

**Why:** Chunking severs a passage from its document context. In this module's
data the query 稀土管制实施时间 matches the heading 【实施时间】, whose body
sentence never contains 时间 -- and only the heading-carrying strategy retrieves
it at rank 1.

**Boundary:** The heading is added text and slightly dilutes the body's term
weighting, and it only helps for queries that use that vocabulary -- one in seven
here.

**Tags:** `retrieval` `mechanism` `general-principle`

---

### 3. [comparison] Fixed-size chunking with overlap versus structure-aware chunking: what does each fix, and what does each still miss?

**Answer:** Overlap fixes spans cut at a boundary by duplicating the boundary
region, but boundaries remain arbitrary. Structure-aware puts boundaries at
semantic units, but requires the document to have parseable structure.

**Why:** They address different causes, which is why they can post identical
aggregate scores while succeeding on different queries -- as they do in this
module's data.

**Boundary:** Overlap costs index size and emits near-duplicate hits that consume
top-k slots; structure-aware degrades to a sentence splitter on scraped or OCR'd
input that has no structure left.

**Tags:** `retrieval` `comparison` `general-principle`
