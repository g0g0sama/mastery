# Capability map

> **Status: DRAFT levels.** Everything in the `Now` column below is my inference
> from the `lab/patterns` track and your own assessment, not from watching you
> work. Correct it in the first cycle -- an overstated level produces a module
> built on a gap, and an understated one wastes a cycle. Levels are defined in
> [README.md](README.md#level-definitions).

**How to read a row.** `Gate` is what must already be at Working before this can
be opened. `Pull` is the real project that needs it -- `S` Sinoscope, `SI`
supplier intelligence, `B` general backend work, `-` nothing yet. A row with no
pull is a row that should not be next, whatever its level.

**Deep targets.** Only two: multilingual retrieval and structured extraction.
Those differentiate the work. Everything else stops at Independent or lower, on
purpose -- a map where many rows target Deep is a map that will not be finished.

---

## Layer 1a -- Python engineering

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| Object model, aliasing, hashability | Working | Independent | - | B | Diagnose an aliasing bug in unfamiliar code without running it |
| Functions, closures, decorators, DI | Working | Independent | - | B | Write a parameterized decorator that preserves signature and errors |
| Iterators, generators, lazy pipelines | Working | Independent | - | S | Build an ingestion pipeline that streams a file larger than memory |
| Context managers, resource scope | Working | Independent | - | B | Express a transaction boundary that survives every exit path |
| Error modelling, exception boundaries | Working | Independent | - | B | One translation boundary; domain errors carry data |
| Typing, protocols, generics | Working | Independent | - | B | A generic repository protocol that mypy checks in CI |
| Async I/O, cancellation, backpressure | Working | Independent | 09 lab | S SI | A bounded worker pool with correct cancellation under timeout |
| Pydantic validation and serialization | Aware | Independent | typing | S SI | Model versioning across a schema change without breaking readers |
| Profiling, memory investigation | Aware | Working | - | S | Find and fix one real hot path with cProfile + tracemalloc evidence |
| Packaging, environments, locking | Aware | Working | - | B | An installable package with pinned lock and a reproducible env |
| Testing: fixtures, fakes, property-based | Working | Independent | - | B | A contract suite plus one property-based test that finds a real bug |

## Layer 1b -- Backend systems

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| HTTP semantics and streaming responses | Working | Independent | - | S SI | Stream a model response with correct cancellation on client disconnect |
| AuthN / AuthZ | Aware | Independent | - | SI | Authorization enforced outside the model, tested with a denied case |
| Idempotency and retry policy | Working | Independent | 08 lab | SI | An idempotent write endpoint with a durable key and fingerprint |
| Backoff, circuit breaking, rate limits | Aware | Independent | async | S SI | A provider client that degrades instead of amplifying an outage |
| Background jobs and queues | Aware | Independent | async | S | A durable job with supervision, retry, and idempotent execution |
| Transactions and consistency | Working | Independent | - | S | Correct boundary across two repositories under a seeded failure |
| Caching | Aware | Working | - | S | A cache with a stated invalidation rule and a measured hit rate |
| Object storage and file handling | Aware | Working | - | S | Ingest documents with content-addressed storage and dedup |

## Layer 1c -- Data systems

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| SQL and schema design | Working | Independent | - | S | A schema for events + sources + claims that survives three new fields |
| JSONB vs relational modelling | Aware | Independent | SQL | S | A defended choice per field, with the query that decided it |
| Indexes and query plans | Aware | Independent | SQL | S | Read an `EXPLAIN ANALYZE` and predict the effect of an index first |
| Postgres full-text search | Aware | Independent | SQL | S | Chinese-language FTS with the right analyzer, measured recall |
| Migrations and schema versioning | Aware | Working | SQL | S | A backward-compatible migration run against real data |
| Batch and incremental pipelines | Aware | Independent | generators | S | Incremental ingestion with watermarks and reprocessing |
| Provenance, lineage, data quality | Aware | Independent | pipelines | S SI | Every extracted claim traceable to source span and fetch time |
| Dataset and label versioning | - | Independent | provenance | S | An eval set with a version, a changelog, and a frozen holdout |

## Layer 2 -- Mathematical and ML literacy

Learn these **inside** the module that uses them. A row here should never be the
active cycle on its own -- that is the prerequisite spiral, and it does not end.

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| Vector geometry: dot product, norms, cosine | Aware | Independent | - | S | Explain why normalization changes ranking, and show it on your data |
| Matrix multiplication and shapes | Aware | Working | - | S | Predict every tensor shape in a forward pass before running it |
| Dimensionality reduction, PCA/SVD intuition | Aware | Working | vectors | S | Reduce your embeddings and explain what the axes lost |
| Probability, expectation, sampling | Aware | Working | - | S | Explain temperature and top-p in terms of the distribution |
| Confidence intervals and significance | Aware | Independent | probability | S | State whether a 3-point eval gain is real, given your set size |
| Calibration and thresholds | Aware | Independent | probability | S | Pick a confidence threshold from a precision/recall curve |
| Gradients, loss, backprop | Aware | Working | calculus | - | Follow a training loop and say what each line changes |
| Entropy, cross-entropy, KL, perplexity | Aware | Working | probability | - | Explain what perplexity does and does not tell you about quality |
| Classical ML: regression, trees, clustering | Aware | Working | probability | S | A baseline classifier that your LLM approach must beat |
| Leakage, distribution shift, imbalance | Aware | Independent | classical ML | S | Find the leak in a naively split dataset |

## Layer 3 -- Neural networks and transformers

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| Tensors, autograd, training loop | Aware | Working | gradients | - | Train a tiny classifier in PyTorch from scratch |
| Tokenization | Aware | Independent | - | S | Explain why Chinese text costs the tokens it does, measured |
| Embeddings and pooling | Aware | Independent | vectors | S | Compare pooling strategies on your own retrieval set |
| Self-attention, multi-head, positions | Aware | Working | tensors | - | Implement single-head attention and match a reference output |
| Decoder vs encoder architectures | Aware | Working | attention | S | Choose the right family for extraction vs generation, and say why |
| Pretraining, instruction tuning, preference opt | Aware | Working | training loop | - | Explain what each stage changed about model behavior |
| Context windows, KV cache | Aware | Working | attention | SI | Predict memory growth with context length before measuring |
| Sampling and decoding | Aware | Independent | probability | S | Show how decoding params change schema-validity rate |
| Fine-tuning / LoRA | - | Aware | training loop | - | Deferred until an eval proves prompting has plateaued |

## Layer 4 -- Model-interface engineering

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| Raw API requests, message representation | Working | Independent | HTTP | S SI | A client with no framework between you and the wire |
| Token accounting and context budgeting | Aware | Independent | tokenization | S | Predict cost per document before running a batch |
| Structured outputs and JSON schema | Aware | **Deep** | typing | S | Schema-validity rate measured, failure modes taxonomized |
| Tool / function calling | Aware | Independent | schemas | SI | Typed tools with validation on both sides of the boundary |
| Streaming and cancellation | Aware | Independent | async | S | Cancel a stream and prove no partial write persisted |
| Provider errors, retries, idempotency | Aware | Independent | idempotency | S SI | Retry policy that distinguishes transient from terminal |
| Routing, fallback, model versioning | - | Independent | gateway | S SI | A pinned model per task, with a documented fallback path |
| Prompt versioning and regression | - | Independent | evaluation | S | A prompt change gated by an eval run, with the diff recorded |

## Layer 5 -- Evaluation and dataset engineering

**Highest priority layer.** This is the one that converts everything else from
demonstration into engineering.

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| Task definition and success criteria | Aware | **Deep** | - | S SI | A written spec that two people would label identically |
| Building a labelled eval set | - | **Deep** | task def | S | 50+ labelled Sinoscope records, frozen holdout, versioned |
| Adversarial and negative examples | - | Independent | eval set | S SI | Cases that break your current system, in the set, failing |
| Deterministic graders | Aware | Independent | eval set | S | Schema, field-match, and no-side-effect assertions |
| Model-based and rubric graders | - | Independent | det. graders | S | Grader agreement measured against your own labels |
| Extraction metrics: field P/R/F1, record accuracy | Aware | **Deep** | eval set | S | Per-field scores that locate which field is failing |
| Retrieval metrics: recall@k, MRR, nDCG | Aware | Independent | eval set | S | Ranked judgments on Chinese queries, scores reproducible |
| Groundedness and citation accuracy | - | Independent | retrieval | S | Every generated claim traced to a retrieved span, scored |
| Regression suites and eval gates | - | Independent | graders | S SI | A change that fails the gate and is therefore not shipped |
| Error taxonomy | - | **Deep** | eval set | S | Named failure classes with counts, driving the next fix |
| Cost per successful task | - | Independent | metrics | S SI | The metric that decides model choice, computed |

## Layer 6 -- Search, embeddings, retrieval

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| Inverted indexes, TF-IDF, BM25 | Aware | Independent | - | S | BM25 baseline beating your first dense attempt on some queries |
| Analyzers and Chinese segmentation | - | **Deep** | FTS | S | Measured recall difference across segmentation choices |
| Embedding spaces and similarity | Aware | **Deep** | vectors | S | Show where cosine similarity misleads on your corpus |
| Multilingual and cross-lingual retrieval | - | **Deep** | embeddings | S | zh query -> en document retrieval, scored |
| ANN indexes and HNSW intuition | - | Working | embeddings | S | Recall/latency trade-off curve for your index parameters |
| Chunking and metadata design | Aware | **Deep** | - | S | Structure-aware chunking beating fixed-size, measured |
| Hybrid retrieval and fusion | - | **Deep** | BM25 + dense | S | Fusion that beats both parents on the same set |
| Query rewriting | - | Independent | retrieval eval | S | Rewrites that help, with the cases where they hurt named |
| Reranking and multi-stage | - | Independent | hybrid | S | nDCG gain per added millisecond, tabulated |
| Freshness, deletion, access-control filtering | - | Independent | pipelines | SI | A deleted document provably unreachable through retrieval |

## Layer 7 -- Agents and tool workflows

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| Deterministic workflows before agents | Aware | Independent | tool calling | SI | classify -> retrieve -> extract -> validate -> store, running |
| Manual tool loop, no framework | - | Independent | tool calling | SI | The loop written by hand, with the control flow visible |
| State machines, checkpoints, resumability | Aware | Independent | jobs | SI | A workflow resumed mid-run after a killed process |
| Trajectory tracing | - | Independent | observability | SI | Every step, input, and tool result reconstructable |
| Budget and timeout enforcement | - | Independent | async | SI | A run that halts on budget with partial results preserved |
| Human approval boundaries | - | Independent | workflows | SI | A consequential action that cannot execute unapproved |
| Agent frameworks | - | Aware | manual loop | - | Deliberately last. Adopt only against a measured need |

## Layer 8 -- Inference and serving

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| CPU vs GPU, memory bandwidth | Aware | Working | - | S | Predict which of your workloads is bandwidth-bound |
| Weights, runtime memory, KV cache sizing | Aware | Working | context | S | Predict RAM for a context length before loading |
| Quantization | Aware | Working | - | S | Quality vs memory across two quantizations, on a real task |
| TTFT, throughput, latency percentiles | Aware | Independent | - | S | p50/p95 measured under concurrency, not single requests |
| Batching and request scheduling | - | Working | throughput | S | Throughput vs latency curve for your local setup |
| Benchmark methodology | Aware | Independent | evaluation | S | A benchmark that reports task accuracy alongside tokens/sec |

## Layer 9 -- Production AI and LLMOps

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| Containerization and CI/CD | Working | Independent | packaging | B | Reproducible build and deploy of a model-backed service |
| Config and secret management | Working | Independent | - | B | No provider key reachable from application code paths |
| Structured logging and tracing | Aware | **Independent** | - | S SI | One request traced end to end, including model calls |
| Metrics and cost monitoring | - | Independent | tracing | S SI | Cost per task on a dashboard, alerting on drift |
| Drift and quality degradation | - | Independent | evaluation | S | A scheduled eval run detecting a real regression |
| Failure queues and replay | - | Working | jobs | S | Failed extractions replayable after a fix |
| Model and prompt registry | - | Working | versioning | S | Which prompt and model produced a given stored record |

## Layer 10 -- Security, safety, governance

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| Prompt injection, direct and indirect | Aware | Independent | tool calling | SI | Injection payloads in your corpus, caught by a test |
| Untrusted content isolation | Aware | Independent | injection | SI | Fetched web content never reaching a privileged path |
| Insecure output handling | Aware | Independent | - | SI | Model output treated as untrusted input everywhere it lands |
| Authorization outside the model | Aware | **Independent** | authz | SI | Deterministic checks, provable without reading a prompt |
| Least privilege and excessive agency | - | Independent | tools | SI | Each tool's blast radius written down and enforced |
| PII handling and auditability | Aware | Working | logging | S SI | What is stored, for how long, and who can read it |
| Abuse and cost controls | - | Working | metrics | S SI | A runaway loop stopped by a budget, not by a bill |

## Layer 11 -- Specialization (choose by project, not upfront)

| Capability | Now | Target | Gate | Pull | Evidence to graduate |
|---|---|---|---|---|---|
| Multilingual NLP (zh) | Aware | **Deep** | retrieval | S | The differentiating capability. Everything zh routes here |
| Structured information extraction | Aware | **Deep** | evaluation | S | The second differentiator |
| Document intelligence / OCR / layout | - | Working | extraction | SI | Only when a real document format demands it |
| Knowledge graphs and graph retrieval | - | Aware | extraction | S | Deferred; revisit when entity linking becomes the bottleneck |
| Recommendation and ranking | - | Aware | retrieval | - | Deferred |
| RL, distributed training, kernel optimization | - | Aware | - | - | Deferred indefinitely. Read about them; do not study them |

---

## Review queue

Capabilities at Independent or Deep decay. Reviewed means: reconstructed the
mechanism cold, or used it in anger, within the window.

| Capability | Level | Last reviewed | Next due |
|---|---|---|---|
| _(populated as cycles close)_ | | | |

## Notes on sequencing

Three orderings that are easy to get wrong, stated once:

- **Evaluation before retrieval, retrieval before agents.** Building HNSW
  intuition before you can measure recall means you will not know whether the
  index helped. Building an agent before either means you cannot tell a bad plan
  from a bad retrieval.
- **Baseline before technique.** BM25 before dense, regex before LLM, one prompt
  before a pipeline. The baseline is what makes the next number mean something.
- **Math inside the module that needs it.** Cosine similarity is learned while
  debugging why normalization changed your ranking, not in a linear algebra
  cycle that precedes retrieval by two months.
