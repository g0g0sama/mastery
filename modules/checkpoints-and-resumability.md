# State machines, checkpoints, resumability

**Micro module.** One mechanism, one experiment, three cards. Runs against
[agent-workflow-lab/](agent-workflow-lab/).

**Capability:** state machines, checkpoints, resumability (Layer 7, Aware ->
Independent). Map evidence to graduate: "A workflow resumed mid-run after a
killed process."

**Gate:** background jobs. Partly met; the queue half is Layer 1b.

---

## The problem

A twenty-step run dies at step seventeen. The process is gone, the work is gone,
and the only recovery available is to start again -- paying for every model call
before the failure, a second time.

## The wrong model

**"Save the state and restore it."**

Persisting state is the easy half and it is not the half that is wrong. The
question resumability actually asks is **which steps may be re-executed**:

```text
classify    pure
retrieve    pure
extract     pure-but-paid
validate    pure
store       EFFECTFUL
```

A resume that re-runs `store` produces the duplicate row from
[provider-errors-retries.md](provider-errors-retries.md), and it does so on the
recovery path -- during an incident, when nobody is reading the logs.

`pure-but-paid` is the category people forget. Re-running `extract` is safe and
not free, which is exactly why the checkpoint is written after it rather than at
the end of the run.

## The mechanism

Three properties, and the third is the one that makes it work:

1. **The state is keyed by the work**, not by the attempt -- `doc_id` plus prompt
   version. A key minted per attempt finds no checkpoint and resumes nothing.
2. **The checkpoint is written after each step**, before the next one begins.
   Written at the end, it records only runs that did not need it.
3. **The checkpoint key and the idempotency key are the same key.** Two keys for
   one identity is precisely how a system resumes correctly and writes twice.

## The experiment

```powershell
cd modules\agent-workflow-lab
python resilience_lab.py
```

The process is killed entering `store`, then restarted:

```text
no resume      first run: halted: process died during store
               restart:   stored, model calls 2 then 2
               steps replayed: ['classify','retrieve','extract','validate','store']

with resume    first run: halted: process died during store
               restart:   stored, model calls 2 then 0
               steps replayed: ['skip:classify','skip:retrieve','skip:extract',
                                'skip:validate','store']
```

Zero model calls on the resumed restart against two on the cold one. At two calls
per document that is a rounding error; **at a twenty-step research run it is the
difference between a retry and a rewrite**, and that is the regime where an agent
loop lives ([manual-tool-loop.md](manual-tool-loop.md)).

## Boundary

- **Checkpoint the inputs, not only the outputs.** A state that records "extract
  produced X" without recording which passages and which prompt version produced
  it cannot be resumed *correctly* after a prompt change -- it will resume onto a
  record the current system would not have made.
- **Granularity is a cost trade, and the units differ.** Checkpoint writes cost
  I/O; skipped steps save money and latency. Checkpoint after every *paid* step
  at minimum; after every step if the steps are cheap and the runs are long.
- **A checkpoint that survives a deploy must survive a schema change.** Version
  the checkpoint payload, or a mid-flight run resumes into code that cannot read
  it -- and the failure appears days later, in the tail of a queue.
- **Resumability makes a partial run visible, which is its second job.** The
  halted state in section 3 of the lab is inspectable: which steps ran, what they
  produced, what it cost. A run that vanishes leaves you with a bill and no
  record.
- **This is a state machine whether or not you call it one.** Naming the states
  and writing the legal transitions is what stops `store` from being reachable
  before `validate` ([deterministic-workflows.md](deterministic-workflows.md)).

## Cards

### 1. [misconception] Resumability is often described as "save the state and restore it". What does that description leave out?

**Answer:** Which steps may be re-executed. Pure steps can re-run freely;
effectful steps must not; and paid-but-pure steps are safe to re-run and
expensive.

**Why:** A resume that re-runs a write produces duplicate rows -- on the recovery
path, during an incident. Classifying each step is the actual work; persisting
state is bookkeeping.

**Boundary:** The classification must be per step, not per run. In the lab only
`store` was effectful, and the checkpoint was written after `extract` precisely
because that step was paid.

**Tags:** `workflows` `misconception` `general-principle`

---

### 2. [mechanism] Why must the checkpoint key and the idempotency key be the same key?

**Answer:** Because they identify the same thing -- the unit of work -- and two
keys for one identity lets a run resume correctly while still writing twice.

**Why:** The resume path looks up the checkpoint by one key and the write
deduplicates by another; if they disagree, a resumed run skips the steps it
already did and re-executes the write it already performed.

**Boundary:** The key must be derived from the work -- document id plus prompt
version -- not from the attempt. A per-attempt key finds no checkpoint and
deduplicates nothing.

**Tags:** `workflows` `idempotency` `mechanism` `general-principle`

---

### 3. [scenario] You add checkpointing and later change the prompt. A run that was mid-flight resumes. What can go wrong?

**Answer:** It resumes onto intermediate results produced by the old prompt and
finishes as if the new one had made them.

**Why:** The stored record is then attributable to a prompt version that did not
produce it, which corrupts exactly the attribution
[prompt-versioning.md](prompt-versioning.md) exists to provide.

**Boundary:** Include the prompt version in the checkpoint key, so a changed
prompt is a different unit of work and starts fresh. Version the checkpoint
payload too, or a deploy strands in-flight runs on a shape the new code cannot
read.

**Tags:** `workflows` `versioning` `scenario` `general-principle`
