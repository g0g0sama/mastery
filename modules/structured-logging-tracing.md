# Structured logging and tracing

**Micro module.** One mechanism, one experiment, three cards. Runs against
[ops-lab/](ops-lab/).

**Capability:** Structured logging and tracing (Layer 9, Aware -> **Independent**).
Map evidence: "One request traced end to end, including model calls."

---

## The problem

"Traceable" is usually asserted, so this module makes it countable: eight
questions an incident actually asks, answered mechanically against three
logging styles. The follow-on questions — what to sample, what it costs, and
what the trace store is and is not evidence for — are where the mistakes live.

## The mechanism

**A request id makes lines joinable. It does not make them informative.** One
request that retried once and then failed validation:

```text
question                                       text log   flat structured events   spans with attributes
which prompt version produced this record      --         --                       v1/a3d18cca
which model, and was it an alias or a version  mid-1      --                       mid-1 alias @c8817f42
what did this request cost                     --         --                       $0.00121
was the model call retried, and with what err  retried    2 attempts               RateLimitError, ok
how much of the latency was the model          --         1555 ms of 1737          1555 of 1737 ms
which retrieval index served the context       --         --                       idx-2026-02-01
which field failed validation                  --         --                       date/missing
which other requests today hit the same fault  --         12 today                 12 today, same stamp
ANSWERED                                       2 of 8     3 of 8                   8 of 8
```

The middle column is the trap. It is structured, it carries a request id on
every line, it satisfies "we have structured logging" — and it answers three
questions, all about timing, because the only things it recorded were step names
and durations.

What the third column adds is not a format. It is a decision about **which
attributes are facts about a request**: the resolved model and prompt hash, the
token counts and cost, the index version, the violation *code* rather than
message, the error class rather than the error text. Every one of those is a
column another module in this repository needed — cost per successful task, the
error taxonomy, the registry, the drift proxy. Tracing is where they get
captured, or they do not exist.

**Sampling is where traces are lost, and there are two independent ways to lose
them.** 3,000 requests, 2.4% failing:

```text
policy                            traces kept   errors kept   errors kept %
head sampling 1%                  30            1             1%
tail sampling: all errors + 1%    95            72            100%
keep everything                   3000          72            100%
```

Head sampling decides before the request has an outcome, so it keeps errors at
the same rate as everything else — which for a rare failure means keeping almost
none of the only traces anyone will look at. Tail sampling keeps all of them for
a few percent more storage.

The second way is subtler and looks equivalent. The same 10% budget:

```text
granularity               spans kept    complete traces   share
per trace                 211           41                10.2%
per span (independent)    212           0                 0.0%

mean spans per trace: 5.1   P(complete trace) at p=0.10 per span: 8.76e-06
```

Both rows stored the same number of spans; one stored no usable traces at all.
The sampling decision has to be made once, at the root, and propagated — which
is what a trace context header is for, and the only reason it has to survive
every service, queue and model call in the path.

**Cost is the question people ask first and it is the wrong one.** Bytes are
measured from `json.dumps`; volume and price per GB are declared:

```text
what is emitted                       bytes/request  GB/month    $/month     vs model spend
text log                              84                  0.6    $0.32         0.004%
flat structured events                533                 4.0    $2.00         0.023%
spans with attributes                1046                 7.8    $3.92         0.044%
spans + prompt and response bodies   1691                12.7    $6.34         0.071%

model spend on the same traffic: $8,869.72/month
```

Full tracing costs 0.04% of the model bill it describes. The row worth thinking
about is the last one, and not because of the price: logging prompts and
responses makes every trace a copy of the corpus, inheriting the corpus's
licence terms, retention policy and PII exposure, plus the leak surface in
[config-and-secrets.md](config-and-secrets.md). Sample payloads, don't log them
by default, give them their own retention.

The metric-side version of the same mistake is cardinality:

```text
metric labels               series in 3000 req      series at 250,000/day
release, slice, outcome     16                      bounded
+ error_class               18                      bounded
+ doc_id                    22                      bounded
+ request_id                3000                    ~250,000+
```

Stated as a test rather than as taste: if a label's distinct-value count grows
with request count, it belongs in a trace attribute, where it is cheap, not in a
metric dimension, where it is a series.

**And the one that costs a week.** The trace store is a stratified sample whose
sampling rate differs by outcome:

```text
true failure rate over all requests               0.024
failure rate counted in the trace store           0.774
same store, weighted by 1 / sampling rate         0.033
weighted estimate, mean of 200 resamples          0.024
       and its 95% interval                       [0.024, 0.025]

overstatement if read naively: 32x
```

The property that makes tail sampling useful is exactly the property that makes
its store unusable as a denominator. Rates come from metrics, which count every
request; traces explain the numerator. The weighted estimator recovers the true
rate and is imprecise in a single store — that one's denominator rested on 21
sampled successes standing in for 2,928. The same argument applies to any
dataset built from the trace store: an error taxonomy sampled this way
over-represents failures by construction, which is fine, and a claim about *how
often* a class occurs is not recoverable without the weights. Store the sampling
rate on the trace.

## The experiment

```powershell
cd modules\ops-lab
python logging_lab.py      # ~2 s
```

## Boundary

- **No collector, no exporter, no context propagation across a process
  boundary.** Spans here are dicts in one process. What that hides is the part
  that actually breaks in production: propagation through a queue, a retry, a
  thread pool, or a provider SDK that starts its own span.
- **The eight questions are this system's questions.** The transferable move is
  writing your own list from the last three incidents and checking your
  telemetry against it — not the list.
- **Latency numbers are declared**, derived from the provider's declared
  latency. Nothing here is a measurement of a real service's timing; see
  [latency-percentiles.md](latency-percentiles.md) for the part that is.
- **Log volume is priced at a flat $/GB.** Real platforms price ingest,
  indexing, retention and query separately, and indexing is usually what makes
  high-cardinality attributes expensive.

## Cards

### 1. [misconception] We have structured logging: every line is JSON with a request id.

**Answer:** Those are two different problems. The id makes lines *joinable*; it
does nothing about whether the joined lines contain anything. In the lab,
structured events with an id on every line answered 3 of 8 incident questions —
all about timing — while spans carrying the resolved model, prompt hash, token
counts, index version, violation code and error class answered 8 of 8.

**Why:** The format is not the content. What makes a trace useful is a decision
about which attributes are facts about the request, taken before the incident.

**Boundary:** The attributes worth carrying are the ones other systems need as
columns: cost per successful task, the error taxonomy, the registry stamp, the
drift proxy. If no downstream consumer exists for an attribute, it is a log
line, not a span attribute.

**Tags:** `observability` `misconception` `general-principle`

---

### 2. [failure] There is a trace for the request, but half its spans are missing.

**Answer:** Look for a sampling decision taken per span rather than per trace.
At a 10% budget, per-trace sampling kept 10.2% of traces complete and
independent per-span sampling kept **0%** complete while storing the same number
of spans — P(complete) is 0.1^5.1 ≈ 9e-06 for this pipeline. The decision must
be made once at the root and propagated in the trace context.

**Why:** A trace is only meaningful whole; sampling is a decision about traces
that happens to be implemented on spans.

**Boundary:** Head sampling at the root is complete but blind to outcome — 1%
head sampling kept 1 of 72 failures. Tail sampling keeps every error for a few
percent more storage and is the default worth arguing for; its cost is buffering
spans until the trace ends.

**Tags:** `observability` `failure` `general-principle`

---

### 3. [decision] The dashboard and the trace store disagree about the error rate. Which is right?

**Answer:** The metric. A tail-sampled trace store keeps 100% of errors and 1%
of successes, so the rate counted inside it was 0.774 against a true 0.024 — a
32x overstatement. Weighting each trace by the inverse of its sampling rate
recovers 0.024 on average, but a single store's estimate rested on 21 sampled
successes and read 0.033.

**Why:** Traces are a stratified sample by design. Rates need a denominator that
counted every request.

**Boundary:** This applies to anything derived from the trace store, including
an error taxonomy or an eval set drawn from failures. Sampling from it is the
right way to *find* failure classes and the wrong way to estimate how often they
happen — unless the sampling rate is stored on the trace, which costs four bytes.

**Tags:** `observability` `decision` `general-principle`
