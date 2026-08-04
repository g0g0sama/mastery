# Trajectory tracing

**Micro module.** One mechanism, one experiment, three cards. Runs against
[agent-workflow-lab/](agent-workflow-lab/).

**Capabilities:** trajectory tracing (Layer 7, `-` -> Independent) and structured
logging and tracing (Layer 9, Aware -> **Independent**). Map evidence: "Every
step, input, and tool result reconstructable" and "One request traced end to end,
including model calls."

---

## The problem

A record in the database is wrong. It was produced three weeks ago by a run that
made two model calls, retrieved four passages, and resolved two entities. None of
that exists any more. What exists is the record, and the record does not say what
made it.

## The wrong model

**"Log the inputs and outputs."**

Two failures follow from it. The first is that a run is not one input and one
output -- it is a sequence, and a sequence logged as endpoints cannot answer *at
which step* things went wrong. The second is subtler and worse: **logging
payloads is expensive, expense forces sampling, and sampling drops the rare
failure you needed the trace for.**

## The mechanism

One event per step, with digests where payloads would be:

```text
seq             2
step            extract
inputs          {'doc': '4a7c1e2b90', 'passages': 'c0d81f6a4e'}
output          '9b21fe0a73'
output_preview  {'event_type': 'investment', 'actors': ['中国石化'], 'date': '20
cost            0.00117
model           mid-1
```

The digests are what make the trace **affordable**, and affordability is the
design constraint. Digests are enough to answer the questions you actually ask:
did this step see the same input as that step; did the passages change between
attempt one and attempt two; is this the same record we stored yesterday. Store
digests always, and full payloads for the failures.

What must be reconstructable, in the order you will want it:

1. which steps ran, in what order
2. with what inputs
3. at what cost
4. against which model and prompt version

The last one is stamped by [routing-and-fallback.md](routing-and-fallback.md).
Without it, a trace tells you what happened and not what to change -- a fallback
to a weaker model looks identical to a prompt regression.

## The experiment

```powershell
cd modules\agent-workflow-lab
python resilience_lab.py     # sections 3 and 5
python loop_lab.py           # section 3, the two traces side by side
```

The comparison in `loop_lab.py` is the argument. Both traces are complete; only
one is diagnostic:

```text
pipeline: classify -> retrieve -> extract -> validate -> resolve_actors -> store
agent:    extract, extract, extract, retrieve, extract, retrieve, retrieve,
          validate, resolve_actors, resolve_actors, store
```

The pipeline's step names are a taxonomy: `failed_at=validate` and
`failed_at=retrieve` are different problems with different owners, countable
across runs. The agent's trace is a narrative, and narratives do not aggregate.

**A trace's value is set by whether its steps have names you can count.**

## Boundary

- **A trace is not a log line with more fields.** It needs a run id shared across
  every event, a sequence, and parent/child links if there are sub-agents.
  Without those you have logs that happen to mention the same request.
- **Sampling drops what you need.** Sample the *successes* if you must sample.
  Never sample by request id, which drops failures at the same rate as everything
  else -- and failures are why the system exists.
- **Digests only answer equality questions.** "Did the input change" is
  answerable; "what was in it" is not. So keep full payloads on the failure path,
  and accept that the decision of what counts as a failure is now part of your
  observability design.
- **Traces contain untrusted content and personal data.** Retrieved passages,
  extracted names, user text. Retention, redaction, and who may read them are
  Layer 10 questions that arrive with the first trace, not later.
- **The trace is the input to the error taxonomy**, not a replacement for it.
  Counting `failed_at` is a taxonomy of *where*; the taxonomy of *what*
  ([error-taxonomy.md](error-taxonomy.md)) still has to be built from the
  failures themselves.

## Cards

### 1. [misconception] Why is "log the input and the output of each run" insufficient for an agent or a multi-step pipeline?

**Answer:** A run is a sequence. Endpoints cannot say at which step things went
wrong, and the intermediate state -- what was retrieved, what a tool returned --
is gone.

**Why:** Diagnosis needs the step at which the input stopped being the thing you
expected. In the lab, a run made four extraction calls and three retrievals; the
endpoints show one document in and one record out.

**Boundary:** The step names must be countable across runs. A trace that reads as
a narrative can be inspected one at a time and never aggregated into a rate.

**Tags:** `observability` `misconception` `general-principle`

---

### 2. [decision] Storing full payloads for every trace event is too expensive. What do you store instead?

**Answer:** Digests of inputs and outputs, a short preview, cost, and the model
and prompt version -- with full payloads kept on the failure path.

**Why:** Digests answer the questions you actually ask (did this input change,
is this the same record) at a fraction of the size, so the trace survives being
kept for everything rather than sampled.

**Boundary:** Digests only answer equality questions. Deciding what counts as a
failure now becomes part of your observability design, because that decision
determines what you can ever reconstruct.

**Tags:** `observability` `decision` `general-principle`

---

### 3. [failure] Your traces are sampled at 5% to control cost, and you cannot diagnose a rare failure. What is the fix, and what is the trap in the obvious version?

**Answer:** Sample the successes, not the requests. Keep every failed or halted
run in full.

**Why:** Uniform sampling by request id drops failures at the same rate as
everything else, and failures are the reason the trace exists. Rare failures are
exactly the ones a 5% sample will not contain.

**Boundary:** This requires a definition of failure available *at trace time* --
including "halted on budget", which is neither a success nor an error and is
routinely counted as whichever is more convenient.

**Tags:** `observability` `failure` `general-principle`
