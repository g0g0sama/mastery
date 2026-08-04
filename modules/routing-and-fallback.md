# Routing, fallback, model versioning

**Micro module.** One mechanism, one experiment, three cards. Runs against
[model-interface-lab/](model-interface-lab/).

**Capability:** routing, fallback, model versioning (Layer 4, `-` ->
Independent). Map evidence to graduate: "A pinned model per task, with a
documented fallback path."

**Gate:** gateway. Not met as infrastructure. What this module supplies is the
decision content a gateway would enforce -- which is the part that has to exist
before the gateway is worth building.

---

## The problem

Three models, an order of magnitude apart in price, and the choice between them
is currently a string in a config file that someone set during a spike.

## The wrong model

**"Route the hard documents to the big model."**

The trouble is *hard* is not observable before the call. What you can observe is
what the cheap model told you about itself, and a schema violation is the only
signal it gives away for free:

```text
strategy                           correct       $/doc   $/accepted
always tiny-1                        0.600    0.000098     0.000164
always mid-1                         0.800    0.001172     0.001465
always large-1                       0.905    0.005796     0.006404
tiny-1, escalate on invalid          0.695    0.000408     0.000587
(11/200 documents escalated)
```

The cascade is real and it is bounded by the wrong thing. Only 11 of 200
documents escalated, because tiny-1's dominant failure is not invalid output --
it is a **confident, well-formed, wrong** record, which no validator sees. A
cascade works when the cheap model's failures are loud. Measure that ratio before
building one; the architecture is worthless without it.

## The mechanism

Three separate things wearing the same word:

| | Question | Decided by |
|---|---|---|
| **Routing** | which model should do this task | task and document properties, declaratively |
| **Fallback** | what happens when that model is unavailable | an availability policy |
| **Versioning** | which exact model ran | a pinned identifier, recorded per record |

They are separate because they fail separately, and the second is the one that
fails invisibly.

## The experiment

```powershell
cd modules\model-interface-lab
python routing_lab.py
```

```text
normal operation            correct 0.905   $/doc 0.005796   {'large-1': 200}
during a primary outage     correct 0.800   $/doc 0.001172   {'mid-1': 200}
```

**Every signal points the wrong way.** No error reaches the caller. Latency
improves, because the fallback is faster. Cost drops. Quality falls by ten
points. There is nothing in the request path that looks like an incident.

The fix is not in the router. It is in the record:

```json
{
  "event_type": "investment",
  "actors": ["中国石化"],
  "_model": "mid-1",
  "_model_pinned": "mid-1@2026-02-14",
  "_prompt_version": "v2",
  "_constrained": true,
  "_temperature": 0.0,
  "_usage": {"input": 90, "output": 61}
}
```

Five fields, none of them interesting until the day they are the only thing that
explains a number. **The pinned version is the one people omit:** `mid-1` is a
moving alias and a provider may repoint it without telling you, producing a
quality change with no diff, no deploy, and no cause.

## Boundary

- **Route on the document and the task** -- length, language, schema depth,
  whether the output is stored or shown. Routing on the user, the tenant, or the
  time of day is defensible only if the key is recorded, because a routing key
  absent from the record is a hidden variable in every subsequent measurement.
- **Keep the routing table declarative.** A router written as branching code at
  the call site cannot be enumerated, so it cannot be tested, and the first
  symptom is a document class that has been quietly going to the wrong model for
  a month.
- **A fallback is a quality decision disguised as an availability decision.**
  Decide in advance whether degraded output is better than an error for this
  task. For a user-facing summary, usually yes. For a record written to a
  database and never reviewed, usually **no** -- fail and queue it.
- **The escalation cascade needs its own eval.** Its accuracy is not either
  parent's, and its cost depends on an escalation rate that moves with your
  corpus. Both belong on the same fixed set as everything else
  ([eval-gates.md](eval-gates.md)).
- **Scheduled evals are how you catch a repointed alias.** The stamp tells you
  what ran; only a periodic run on a frozen set tells you it changed.

## Cards

### 1. [failure] After an incident, your extraction quality is down ten points with no code change, no deploy, and no errors in the logs. What are the two first hypotheses?

**Answer:** A fallback path ran during a primary outage, or the provider
repointed the model alias you were using.

**Why:** Both change the model without changing your code. A fallback also
*improves* latency and *reduces* cost, so every operational signal points away
from the cause.

**Boundary:** Neither is diagnosable after the fact unless the model name and the
pinned dated version were stored on each produced record. Without the stamp you
will look for the cause in your prompt.

**Tags:** `routing` `failure` `general-principle`

---

### 2. [decision] You want to save money with a cascade: cheap model first, escalate to the expensive one on failure. What must you measure before building it?

**Answer:** What fraction of the cheap model's errors are *detectable* --
invalid, missing, out-of-schema -- versus confident and wrong.

**Why:** Escalation can only trigger on a signal. In the lab only 11 of 200
documents escalated, because the cheap model's dominant failure was a
well-formed wrong record that no validator sees; accuracy landed at 0.695 rather
than the expensive model's 0.905.

**Boundary:** A cascade is still often the right call -- 0.695 at a seventh of
mid-tier cost is a real point on the curve. It just has to be evaluated as its
own system, not as the better parent with a discount.

**Tags:** `routing` `cost` `decision` `general-principle`

---

### 3. [best-practice] Which fields belong on every record produced by a model call, and why each?

**Answer:** The pinned model version, the prompt version or hash, the decoding
parameters, and the token usage.

**Why:** They are the only way to attribute a later change in scores. A moving
alias, a fallback, a prompt edit, and a temperature change all produce quality
movement with no diff in your repository.

**Boundary:** Stamping is not enough on its own -- you also need a scheduled eval
on a frozen set to notice the change. The stamp answers *what* changed; the eval
tells you *that* something did.

**Tags:** `routing` `observability` `best-practice` `general-principle`
