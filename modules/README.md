# Modules

Output from `/technical-mastery`. One directory per capability, named after the
capability rather than a topic area:

```text
extraction-eval-sets/
  README.md      learning target, concepts, evidence contract, project transfer
  explainer.md   standard and deep modules only
  lab/           starter files, verify script, break-it script
  cards.md
```

Micro modules are a single file, `<capability>.md`, holding the mechanism, the
one experiment, and three cards. Most modules should be micro.

Where a micro module's experiment runs against an existing lab's data, the script
lives in that lab and the module stays a single file. Six currently do, all
against `extraction-eval-sets/lab/`:

| Module | Experiment | Capability (Layer 5 unless noted) |
|---|---|---|
| `inter-annotator-agreement.md` | `kappa.py` | building a labelled eval set |
| `error-taxonomy.md` | `errors.py` | error taxonomy (**Deep** target) |
| `deterministic-graders.md` | `graders.py` | deterministic graders |
| `rubric-graders.md` | `rubric.py` | model-based and rubric graders |
| `adversarial-examples.md` | `adversarial.py` | adversarial and negative examples |
| `eval-set-sample-size.md` | `interval.py` | confidence intervals (Layer 2) |
| `eval-gates.md` | `gate.py` | regression suites and eval gates |
| `eval-set-versioning.md` | `version.py` | dataset and label versioning (Layer 1c) |
| `retrieval-metrics.md` | `ranking.py` | retrieval metrics |

Coupling them to a lab that already runs is cheaper than standing up nine more
fixtures, and it keeps every number in the set directly comparable. None of these
is an open cycle; they are exposure against the one cycle in progress, and the
map moves only on that cycle's evidence contract.

Ten run against `zh-retrieval-lab/`, a second shared fixture. They are Layer 6
and deliberately came **after** `retrieval-metrics.md`, per the map's sequencing
note -- the metrics are the instrument that measures them:

| Module | Experiment | Capability (Layer 6 unless noted) |
|---|---|---|
| `bm25-baseline.md` | `bm25_lab.py` | inverted indexes, TF-IDF, BM25 |
| `chinese-segmentation.md` | `segment_lab.py` | analyzers and segmentation (**Deep**) |
| `hybrid-retrieval-fusion.md` | `fusion_lab.py` | hybrid retrieval and fusion (**Deep**) |
| `query-rewriting.md` | `rewrite_lab.py` | query rewriting |
| `chunking-and-metadata.md` | `chunk_lab.py` | chunking and metadata (**Deep**) |
| `vector-similarity.md` | `vector_lab.py` | vector geometry (Layer 2) |
| `cross-lingual-retrieval.md` | `cross_lingual_lab.py` | multilingual retrieval (**Deep**) |
| `reranking-multistage.md` | `rerank_lab.py` | reranking and multi-stage |
| `ann-indexes-hnsw.md` | `ann_lab.py` | ANN indexes and HNSW intuition |
| `retrieval-freshness-deletion.md` | `freshness_lab.py` | freshness, deletion, ACL filtering |

Read in that order. Each depends on the previous one's numbers: the baseline,
then the analyzer that moves it most, then fusing the analyzers, then rewriting
the queries that still fail, then what was destroyed before indexing ever
happened, then the geometry underneath all of it, then the language boundary,
then the second stage, then the index that makes it affordable, and finally the
question none of the others ask -- whether the documents that came back were
allowed to.

Eight run against `model-interface-lab/`, a third fixture with its own fake
provider. These are Layer 4 and the Layer 3 rows that gate it:

| Module | Experiment | Capability (Layer 4 unless noted) |
|---|---|---|
| `tokenization.md` | `token_lab.py` | tokenization (Layer 3) + token accounting |
| `structured-outputs.md` | `schema_lab.py` | structured outputs (**Deep**) |
| `sampling-and-decoding.md` | `decoding_lab.py` | sampling and decoding (Layer 3) |
| `tool-calling.md` | `tools_lab.py` | tool / function calling |
| `streaming-cancellation.md` | `stream_lab.py` | streaming and cancellation |
| `provider-errors-retries.md` | `retry_lab.py` | provider errors, retries, idempotency |
| `routing-and-fallback.md` | `routing_lab.py` | routing, fallback, model versioning |
| `prompt-versioning.md` | `prompt_lab.py` | prompt versioning and regression |

Eight more run against `agent-workflow-lab/`, which reuses that provider. Layer
7 and Layer 10, and they come last on purpose -- the map's sequencing note puts
evaluation before retrieval and retrieval before agents:

| Module | Experiment | Capability |
|---|---|---|
| `deterministic-workflows.md` | `loop_lab.py` | deterministic workflows (L7) |
| `manual-tool-loop.md` | `loop_lab.py` | manual tool loop (L7) |
| `checkpoints-and-resumability.md` | `resilience_lab.py` | state machines, checkpoints (L7) |
| `budgets-and-timeouts.md` | `resilience_lab.py` | budget enforcement (L7) + cost controls (L10) |
| `trajectory-tracing.md` | `resilience_lab.py` | trajectory tracing (L7) + tracing (L9) |
| `prompt-injection.md` | `safety_lab.py` | prompt injection (L10) |
| `untrusted-content-isolation.md` | `safety_lab.py` | isolation, output handling, authz (L10) |
| `human-approval-boundaries.md` | `safety_lab.py` | approval boundaries (L7) + least privilege (L10) |

Seven run against `store-lab/`, a fourth fixture and the only one whose subject
is not simulated -- SQLite plans the queries, picks the indexes, runs the FTS
tokenizer and rewrites the tables. Layer 1c, the data-systems layer everything
above it stands on:

| Module | Experiment | Capability (Layer 1c) |
|---|---|---|
| `sql-schema-design.md` | `schema_lab.py` | SQL and schema design |
| `jsonb-vs-relational.md` | `json_lab.py` | JSONB vs relational modelling |
| `indexes-and-query-plans.md` | `plan_lab.py` | indexes and query plans |
| `fulltext-search-zh.md` | `fts_lab.py` | Postgres FTS + analyzers (L6, **Deep**) |
| `migrations-and-versioning.md` | `migrate_lab.py` | migrations and schema versioning |
| `incremental-pipelines.md` | `pipeline_lab.py` | batch and incremental pipelines |
| `provenance-and-lineage.md` | `provenance_lab.py` | provenance, lineage, data quality |

Read in that order: the grain, then where the fields that have not earned a
column live, then what it costs to ask a question of either shape, then the one
question an index cannot answer, then changing all of it with the code still
running, then keeping it current without losing rows, and finally knowing where
every value came from.

Six run against `serving-lab/`, a fifth fixture. Layer 8, the layer that
decides what any of the above costs to run:

| Module | Experiment | Capability (Layer 8) |
|---|---|---|
| `memory-bandwidth-roofline.md` | `roofline_lab.py` | CPU vs GPU, memory bandwidth |
| `kv-cache-sizing.md` | `memory_lab.py` | weights, runtime memory, KV cache sizing |
| `quantization.md` | `quant_lab.py` | quantization |
| `latency-percentiles.md` | `latency_lab.py` | TTFT, throughput, latency percentiles |
| `batching-and-scheduling.md` | `batching_lab.py` | batching and request scheduling |
| `benchmark-methodology.md` | `bench_lab.py` | benchmark methodology |

Read in that order: which resource you are spending, what fits in memory, the
lever that moves bytes, how to measure any of it without lying, the knob that
trades throughput against latency, and finally how to report it so a second
person can act on it. Reversing the last two is the standard mistake -- a
scheduler tuned against a closed-loop harness is tuned against a client that
refuses to queue.

`quant_lab.py` and `bench_lab.py` score retrieval quality with the corpus,
judgments and metrics from `zh-retrieval-lab/`, so the quality numbers in the
Layer 8 modules are directly comparable with the Layer 6 ones.

## A note on the fixtures

`zh-retrieval-lab/`, `model-interface-lab/` and `agent-workflow-lab/` all run on
invented data, and the last two run against a provider whose failure
distribution is declared rather than discovered. Each README says so at the top,
in the same words, because it is the single easiest thing to forget while
reading a table of numbers.

`serving-lab/` is a third case and the one most easily over-read: its GPU
numbers are **declared** from vendor specification sheets, its sizing results
are **derived** arithmetic over those, and only its bandwidth curve, contention
effects, quantization error and latency percentiles are **measured**. No GPU was
involved in producing this repository. Each lab prints which kind of number it
is reporting, because a derived decode ceiling read as a measurement is the
easiest mistake in the fixture.

`store-lab/` is the exception and is labelled as such: the engine is real, the
data is not. Every plan string, timing and recall number in those seven modules
came out of a database, and two of the six predictions written into
`plan_lab.py` before it ran turned out to be wrong. What remains authored is the
cardinality and value distribution of the rows -- which is precisely what a query
planner keys on, so the direction of each result is evidence and the magnitude
is fixture-specific.

What the labs compute is real arithmetic, and several results are genuinely
surprising given the generator -- a pure k-NN graph that reaches 7% recall, a
constrained decoder that lowers per-field accuracy on two fields out of four, a
prompt improvement that costs a slice 15 points. What none of them is, is
evidence about a real model, a real corpus, or a real index. Every module names
the effect it demonstrates and the effect it cannot.

A module here is evidence of exposure, not of level. Levels move in
[../capability-map.md](../capability-map.md), and only on the five conditions in
the cycle's evidence contract. Forty-one modules and five fixtures do not move
a single row, which is the point of keeping the two files separate.

The finished Python track lives separately in `../patterns/` -- ten standard
modules, kept there because it is a complete curriculum in its own right rather
than an artifact of a cycle.
