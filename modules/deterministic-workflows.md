# Deterministic workflows before agents

**Micro module.** One mechanism, one experiment, three cards. Runs against
[agent-workflow-lab/](agent-workflow-lab/).

**Capability:** deterministic workflows before agents (Layer 7, Aware ->
Independent). Map evidence to graduate: "classify -> retrieve -> extract ->
validate -> store, running." It runs in `loop_lab.py`.

**Gate:** tool calling. Met by [tool-calling.md](tool-calling.md).

---

## The problem

The task is: turn a document into a stored event record. There are two ways to
build it. One writes the order of operations in Python. The other gives the model
the tools and lets it decide. The second is more interesting to build, demos
better, and is the default in most current material.

## The wrong model

**"An agent is a more capable workflow."**

Capability is not what changes. What changes is that the **order of operations
becomes a sampled variable**, and everything downstream of that -- cost,
latency, reachable states, testability -- becomes a distribution instead of a
number.

## The mechanism

Eight documents, twenty seeds, the same five capabilities available to both:

```text
system                stored  correct         steps      $/doc     $ p95
fixed pipeline         1.000    0.875          6..6   0.001176  0.001262
agent loop             0.812    0.719          0..12  0.001821  0.004644
```

Read the steps column before the accuracy column. The pipeline runs six steps
every time, and its p95 cost is within 7% of its mean. The loop runs anywhere
from zero steps to the step limit, and its **p95 is nearly four times its mean**.

You cannot capacity-plan, price, or set a timeout against a distribution nobody
characterised -- and the number that reaches the design document is the mean.

The reachable states are the deeper difference:

```text
fixed pipeline      {'stored': 160}
agent loop          {'finished': 5, 'gave-up': 11, 'step-limit': 19, 'stored': 125}

Unvalidated records written to the store: 47
```

Four terminal states, three of which are neither success nor a raised error. And
`store` is reachable while `validated` is `False` -- so a record that failed
validation reaches the database and the run carries on. In a pipeline that
ordering is a code review comment. In a loop it is a probability.

**The pipeline cannot express that state at all.** That is the argument for
pipelines: not that they are better, that they have fewer reachable states.

## The experiment

```powershell
cd modules\agent-workflow-lab
python loop_lab.py
```

**Predict before running.** Both systems have the same tools and the same model.
Write down the ratio between the loop's p95 cost and its mean, and the number of
distinct terminal states you expect from 160 runs.

Section 3 compares two traces of the same document. Both are complete. Only one
answers "what do I fix":

```text
pipeline: classify -> retrieve -> extract -> validate -> resolve_actors -> store
agent:    extract, extract, extract, retrieve, extract, retrieve, retrieve,
          validate, resolve_actors, resolve_actors, store
```

The pipeline's step names **are** the failure taxonomy. A rise in
`failed_at=validate` is a schema or prompt problem; a rise in `failed_at=retrieve`
is an index problem; each has an owner. The loop's trace tells you what happened
and leaves the causal question entirely to you -- affordable at eight documents,
not at eight thousand.

## Boundary

- **Loops earn their place when the order depends on results you cannot
  enumerate.** Three honest cases: research where the next query depends on what
  was found; a repair loop where the tool result names what to fix; an
  interactive session where a human injects new goals mid-run. Extraction is none
  of these.
- **The comparison here is deliberately unfair to the loop, in the loop's
  favour**: both got the same tools, the same model, and a task with a known
  order. A loop on a task that genuinely needs planning would look different --
  and would need a different fixture to show it.
- **This is not an argument against models making decisions.** `classify` is a
  model call that chooses a branch. The distinction is between a model choosing
  *within* a step and a model choosing *which step comes next*.
- **The pipeline's steps are individually unit-testable**; the loop can only be
  tested end to end, over a distribution, which needs far more runs to detect the
  same regression ([eval-set-sample-size.md](eval-set-sample-size.md)).

## Cards

### 1. [comparison] What changes when you replace a fixed pipeline with a model-driven loop, holding the tools and the model constant?

**Answer:** The order of operations becomes a sampled variable, so cost, latency,
and reachable states become distributions rather than numbers.

**Why:** In the lab the pipeline ran 6 steps every time with p95 cost within 7%
of its mean; the loop ran 0 to 12 steps with a p95 nearly 4x its mean, and
produced four distinct terminal states across 160 runs.

**Boundary:** Accuracy barely moved. The argument for pipelines is not quality --
it is that they have fewer reachable states, and every reachable state is one you
must eventually handle.

**Tags:** `agents` `comparison` `general-principle`

---

### 2. [failure] Your agent occasionally writes records that failed validation, and no error is logged. What is the structural cause?

**Answer:** The store action is reachable from a state where validation has not
passed. In a loop, step order is a probability rather than a guarantee.

**Why:** In the lab, 47 of 160 runs wrote an unvalidated record, because `store`
had non-zero weight whenever a record existed. Nothing raised: the loop simply
chose an available action.

**Boundary:** The fix is not a better prompt. It is a precondition enforced by
the tool -- `store` refuses a record that has not been validated in this run --
which is the same reasoning as the approval boundary for irreversible tools.

**Tags:** `agents` `failure` `general-principle`

---

### 3. [decision] When is a model-driven loop the right choice over a written workflow?

**Answer:** When the order of operations depends on what earlier operations
returned, in a way you cannot enumerate in advance.

**Why:** Research where the next query depends on the last result, a repair loop
driven by tool errors, or an interactive session where goals change mid-run. If
you can draw the flowchart, the flowchart is cheaper, testable per step, and
attributable when it fails.

**Boundary:** This is not a ban on model decisions inside a workflow -- a
classification step choosing a branch is fine. The distinction is between
choosing *within* a step and choosing *which step is next*.

**Tags:** `agents` `decision` `general-principle`
