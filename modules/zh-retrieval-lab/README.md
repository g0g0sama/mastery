# zh-retrieval-lab

A shared fixture for ten micro modules. Not a module itself -- there is no
explainer or card deck here, only the corpora and the code the modules run.

**Why it exists before any retrieval work.** The map's sequencing note says
evaluation before retrieval: building index intuition before you can measure
recall means you will not know whether the index helped. The metrics came first
in [../retrieval-metrics.md](../retrieval-metrics.md); this is the first thing
measured with them.

```powershell
cd modules\zh-retrieval-lab
python bm25_lab.py       # ../bm25-baseline.md
python segment_lab.py    # ../chinese-segmentation.md
python fusion_lab.py     # ../hybrid-retrieval-fusion.md
python rewrite_lab.py    # ../query-rewriting.md
python chunk_lab.py      # ../chunking-and-metadata.md
python vector_lab.py     # ../vector-similarity.md
python cross_lingual_lab.py   # ../cross-lingual-retrieval.md
python rerank_lab.py          # ../reranking-multistage.md
python ann_lab.py             # ../ann-indexes-hnsw.md    (~20s)
python freshness_lab.py       # ../retrieval-freshness-deletion.md
```

CPython 3.14, stdlib only. No index server, no embedding model, no network. Every
number is arithmetic over 17 documents you can read.

| File | Role |
|---|---|
| `corpus.py` | 17 Chinese documents, 6 queries, graded relevance judgments |
| `analyzers.py` | unigram, bigram, dictionary maximum-matching |
| `retrievers.py` | inverted index, TF-IDF cosine, BM25 |
| `metrics.py` | recall@k, MRR, nDCG@k -- same definitions as the extraction lab's `ranking.py` |
| `documents.py` | 3 long structured documents, 7 answer-span judgments |
| `bm25_lab.py` | the index, TF-IDF vs BM25, and when the parameters matter |
| `segment_lab.py` | three analyzers, aggregate and per query |
| `fusion_lab.py` | reciprocal rank fusion over analyzers |
| `rewrite_lab.py` | query rewrites, including one that hurts |
| `chunk_lab.py` | fixed-size vs structure-aware chunking, on answer recall |
| `vector_lab.py` | dot product vs cosine, and where similarity misleads |
| `bilingual.py` | 16 English documents, a hand-built concept space, a glossary |
| `cross_lingual_lab.py` | zh query -> en document, four ways |
| `rerank_lab.py` | two-stage retrieval, depth, and the cost of replacing a score |
| `ann_lab.py` | IVF and graph search over 800 synthetic vectors |
| `freshness_lab.py` | deletion, ACL filtering, staleness -- correctness, not ranking |

## What this fixture is not

Seventeen documents and six queries. That is a **worked example**, not a
benchmark: it cannot resolve a small difference between two systems, and the
judgments are one person's. Every module here names the effect it demonstrates
and the effect size it cannot.

The corpus was authored to exercise specific behaviours, and they are marked in
`corpus.py`: a shared-prefix collision (中国石化 against 中国石油), a cross-sense
false match (管制 as air traffic control), an out-of-vocabulary compound
(稀土永磁), an abbreviation the dictionary lacks (中石化), and one query with no
lexical overlap at all (动力电池供应). The last of those is the honest argument
for dense retrieval, and it is in the set so that argument can be made with a
number rather than a claim.

`analyzers.py`'s dictionary is deliberately incomplete, as every real one is.

`documents.py` holds a second fixture for `chunk_lab.py`: three long documents
with explicit section markers, judged by ANSWER SPAN rather than chunk id. Chunk
ids differ between chunking strategies, so span judgments are the only way to
compare strategies on the same footing.

`bilingual.py` holds a third: 16 English documents judged against the same six
Chinese queries, deliberately **comparable rather than parallel**, so the
paraphrase gap survives the language gap. Its concept lexicon is a bilingual
dictionary in a costume and says so at the top -- what transfers from it is the
geometry and the failure shapes, never the coverage.

`ann_lab.py` uses neither corpus. Seventeen documents cannot exhibit an
approximation trade-off, so it generates 800 clustered vectors and counts
distance computations rather than milliseconds. It is the one file here whose
data is synthetic, and the reason is stated in it.

## Transfer to Sinoscope

None of this replaces Postgres full-text search or a real segmenter -- it makes
the choice between them measurable. Before adopting a segmenter, run its output
through `metrics.py` against judgments you wrote, on your own documents. The
result that decides it will be per-query, not aggregate; see
[../chinese-segmentation.md](../chinese-segmentation.md) for why the aggregate
lied here.
