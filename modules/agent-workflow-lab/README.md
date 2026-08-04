# agent-workflow-lab

A shared fixture for eight micro modules covering Layer 7 (agents and tool
workflows) and Layer 10 (security and governance). Not a module itself.

```powershell
cd modules\agent-workflow-lab
python loop_lab.py        # ../deterministic-workflows.md, ../manual-tool-loop.md
python resilience_lab.py  # ../checkpoints-and-resumability.md,
                          # ../budgets-and-timeouts.md, ../trajectory-tracing.md
python safety_lab.py      # ../prompt-injection.md,
                          # ../untrusted-content-isolation.md,
                          # ../human-approval-boundaries.md
```

CPython 3.14, stdlib only. Reuses the fake provider and the extraction task from
[../model-interface-lab/](../model-interface-lab/) via a `sys.path` insert, so
every limitation stated in that README applies here unchanged.

| File | Role |
|---|---|
| `agent.py` | the steps, the tools, the trace, the budget, the checkpoint, the approval queue, and six retrieval passages of which two are poisoned |
| `loop_lab.py` | the same job as a fixed pipeline and as a model-driven loop |
| `resilience_lab.py` | a killed process, a budget halt, and what a trace must contain |
| `safety_lab.py` | indirect injection, authorization outside the model, the approval boundary |

## Why one task for all eight

`classify -> retrieve -> extract -> validate -> store` on the same eight Chinese
sentences as the extraction and model-interface labs. Layer 7 and Layer 10 are
usually taught on toy tasks that have no failure signature of their own, which
makes every security demonstration look like a magic trick. Here the injected
payload produces **exactly** the failure that
[../structured-outputs.md](../structured-outputs.md) measured as an ordinary
model error -- a fetch date substituted for an event date -- so the point that an
attack and a quality problem are indistinguishable from the output is
demonstrated rather than asserted.

## What the agent loop is, and is not

`run_agent` in `loop_lab.py` does not call a model to choose its next action. It
uses a seeded weighted policy that stands in for that choice, and the file says
so. What that models is not stupidity: it is that **the order of operations
becomes a sampled variable**. The consequences measured -- cost as a
distribution, four terminal states, 47 unvalidated writes out of 160 runs -- are
consequences of that property, and they are real arithmetic.

What it cannot show is anything about how well a real model plans. No claim in
these modules depends on that, deliberately.

## Reading order

`loop_lab` -> `resilience_lab` -> `safety_lab`. Whether to build a loop at all;
what a loop needs to survive contact with a real process; and what it must never
be allowed to do.
