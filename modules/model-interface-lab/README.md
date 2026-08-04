# model-interface-lab

A shared fixture for eight micro modules, covering Layer 3 (tokenization,
decoding) and all of Layer 4. Not a module itself -- no explainer, no card deck,
only the task and the code the modules run.

```powershell
cd modules\model-interface-lab
python token_lab.py      # ../tokenization.md
python schema_lab.py     # ../structured-outputs.md          (Deep target)
python decoding_lab.py   # ../sampling-and-decoding.md
python tools_lab.py      # ../tool-calling.md
python stream_lab.py     # ../streaming-cancellation.md
python retry_lab.py      # ../provider-errors-retries.md
python routing_lab.py    # ../routing-and-fallback.md
python prompt_lab.py     # ../prompt-versioning.md
```

CPython 3.14, stdlib only. **No network, no API key, no cost.**

| File | Role |
|---|---|
| `task.py` | 8 Chinese sentences, gold records, a JSON Schema subset, a validator |
| `tokenizer.py` | a toy subword tokenizer, and a statement of what it is not |
| `provider.py` | the fake provider: pricing, errors, streaming, tools, prompt variants |

## The one thing to understand before reading any number here

`provider.py` is **not a model**. Its failure distribution is declared in
`_modes()` rather than discovered, and the two structural claims baked into it
are stated in the code where they are asserted:

- constrained decoding removes every syntax and shape failure **by
  construction**; and
- it raises semantic failures, because the decoder must emit a value for every
  required field, so the model fills where it would otherwise omit.

Everything the labs report is real arithmetic over that distribution -- the
consequences are genuinely computed and several of them are not obvious even
knowing the generator. But the distribution itself is a stand-in. Every claim
here should be re-measured against a real provider before it decides anything,
and the modules say so individually.

The same applies to `tokenizer.py`, harder: it reproduces the *rule* that a
vocabulary hit costs one token and a byte fallback costs two or three, and none
of the data. Never budget a real batch with it.

## Why one task for all eight modules

The task is event extraction from a Chinese news sentence -- deliberately the
same task as [extraction-eval-sets/](../extraction-eval-sets/), so a number
produced here can be read against a number produced there. What differs is the
subject: that lab studies the eval set, this one studies the interface.

Sharing the task also makes the cross-module claims checkable. When
[structured-outputs.md](../structured-outputs.md) says the residual failure is a
fetch date substituted for an event date, and
[prompt-versioning.md](../prompt-versioning.md) fixes it with one sentence and
breaks the `regulation` slice doing so, those are the same eight documents and
the same gold labels.

## What this fixture cannot do

Eight documents. Draws are repeated (25 to 100 per cell) to give the *provider's*
variance room to show, which is not the same as corpus variance -- resampling one
document a hundred times tells you nothing about the hundred-and-first document.
Where a module leans on a difference the fixture cannot carry, it says so and
points at [eval-set-sample-size.md](../eval-set-sample-size.md).

## Reading order

`token_lab` -> `schema_lab` -> `decoding_lab` -> `tools_lab` -> `stream_lab` ->
`retry_lab` -> `routing_lab` -> `prompt_lab`.

Each depends on the previous one's result: what a request costs, what a schema
does and does not buy, what temperature does to that, what happens when the model
calls out, what happens when the response arrives in pieces, what happens when it
does not arrive, which model should have been called, and which prompt asked.
