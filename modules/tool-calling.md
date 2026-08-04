# Tool calling

**Micro module.** One mechanism, one experiment, three cards. Runs against
[model-interface-lab/](model-interface-lab/).

**Capability:** tool / function calling (Layer 4, Aware -> Independent). Map
evidence to graduate: "Typed tools with validation on both sides of the
boundary." The experiment is that sentence, measured.

**Gate:** structured outputs. Met by
[structured-outputs.md](structured-outputs.md), whose conclusion this module
inherits in a new place.

---

## The problem

You give the model a function. It sends back arguments. Those arguments go
straight into a Python call, and Python is happy to explain -- at runtime, with a
traceback pointing at your code -- that `lookup_company()` got an unexpected
keyword argument `company`.

## The wrong model

**"The tool schema constrains what the model can send."**

The schema is a **description** transmitted to the model. Unless the provider
enforces it during decoding, it is a request, and a request is not a type system.
Over 320 calls in the lab:

```text
clean                 192    0.600
unknown_arg            46    0.144
wrong_type             34    0.106
out_of_range           29    0.091
missing_required       19    0.059
```

Forty percent of calls violate the tool's own schema, and every one of them
would have reached the function.

## The mechanism

Three checks, at three different places, catching three different things:

| Where | Checks | Catches |
|---|---|---|
| **Provider** (constrained tool decoding) | argument shape | type and required-field violations |
| **Client**, before dispatch | the same schema, independently | everything, including a provider that does not enforce |
| **Inside the tool** | preconditions and referential facts | arguments that are well-typed and refer to nothing |

The third is not redundant. Provider-side enforcement moves the failure; it does
not remove it:

```text
mode                    unvalidated  provider-validated
clean                         0.600               0.734
missing_required              0.059               0.000
out_of_range                  0.091               0.000
unknown_arg                   0.144               0.000
wrong_type                    0.106               0.000
not_in_registry               0.000               0.266
```

Every shape violation is gone and 27% of calls now name a company that does not
exist. `"中国石化集团"` is a string, it is required, it is present -- and it
resolves to nothing. Type-correct and referentially wrong is the permanent
residue, exactly as it was for structured outputs.

## The experiment

```powershell
cd modules\model-interface-lab
python tools_lab.py
```

Section 3 is the part worth running twice. With client-side validation in place:

```text
rejected before execution           128    0.400
executed, found                     117    0.366
executed, not found                  75    0.234
```

Three outcomes that a single `try/except` collapses into one, needing three
different responses:

- **rejected** -> return the violation to the model **as a tool result**, so it
  can correct itself. Raising here ends a run over a recoverable mistake.
- **not found** -> a legitimate answer about the world. The model should see it
  and say so, not retry.
- **TypeError** -> your bug, and it must be unreachable. Skip the check on one
  renamed argument and the lab produces it on demand.

## Boundary

- **A tool result is untrusted input.** The lab plants a registry row whose value
  contains `SYSTEM: ignore all previous instructions`, and it flows back into the
  context beside the model's own output. The boundary to defend is where a tool
  result becomes prompt text, not where a user types --
  [untrusted-content-isolation.md](untrusted-content-isolation.md).
- **Write down each tool's blast radius before granting it.** Reads what, writes
  what, reversible or not. The last column decides which tools may be called
  inside a loop at all, and which need
  [human-approval-boundaries.md](human-approval-boundaries.md). A tool with an
  irreversible effect and no approval gate is an incident with a schedule.
- **Errors returned to the model are part of the interface.** A violation message
  the model can act on ("`year` must be between 1990 and 2030, received 20260")
  costs one extra turn; a stack trace costs the run. Design them like an API
  error surface, because that is what they are.
- **Tool *descriptions* are prompt text and change behaviour.** They belong under
  the same versioning as the prompt itself
  ([prompt-versioning.md](prompt-versioning.md)) -- and note the blind spot named
  there: a byte-identical prompt template with an edited tool description is a
  changed system that hashes the same.

## Cards

### 1. [failure] The model returns tool arguments that pass your JSON schema. Your tool still fails. What class of error is left, and where must it be handled?

**Answer:** Referential errors -- well-typed arguments that refer to nothing. A
company name that is a valid non-empty string and is not in the registry.

**Why:** A schema constrains shape, never reference. In the lab, provider-side
enforcement removed 100% of shape violations and 27% of calls then named a
company that did not exist.

**Boundary:** Handle it inside the tool and return it to the model as a *result*,
not an exception. "Not found" is a fact about the world that the model should
report; it is not a failure to retry.

**Tags:** `tool-calling` `failure` `general-principle`

---

### 2. [decision] Your tool-argument validator rejects a call. Do you raise, retry, or return the error to the model?

**Answer:** Return it to the model as a tool result, with a message specific
enough to act on.

**Why:** A schema violation is a recoverable mistake and the model is the only
component that can correct it. Raising ends the run; a blind retry re-rolls the
same distribution without telling it what was wrong.

**Boundary:** Bound the correction attempts, and count them -- a model that
cannot satisfy the schema after two tries has a prompt or schema problem, and the
loop will otherwise spend your budget discovering that repeatedly.

**Tags:** `tool-calling` `decision` `general-principle`

---

### 3. [scenario] Your provider guarantees tool arguments match the declared schema. Why validate again on your side?

**Answer:** Because the guarantee covers shape only, is version- and
model-specific, and silently does not apply to whatever your gateway, cache, or
replay path inserts between the provider and your dispatch.

**Why:** The cost is a few milliseconds and the failure it prevents is an
unexpected keyword argument arriving inside your function, where the traceback
blames your code.

**Boundary:** Independent validation is not enough on its own -- the third check,
inside the tool, is what catches arguments that are well-typed and refer to
nothing.

**Tags:** `tool-calling` `scenario` `general-principle`
