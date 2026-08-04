# Budget and timeout enforcement

**Micro module.** One mechanism, one experiment, three cards. Runs against
[agent-workflow-lab/](agent-workflow-lab/).

**Capabilities:** budget and timeout enforcement (Layer 7, `-` -> Independent)
and abuse and cost controls (Layer 10, `-` -> Working). Map evidence: "A run
that halts on budget with partial results preserved" and "A runaway loop stopped
by a budget, not by a bill."

They are one module because they are one mechanism seen from two sides.

---

## The problem

A loop whose step count is a distribution ([deterministic-workflows.md](deterministic-workflows.md))
has a tail, and the tail is where the money is: in the lab the agent's p95 cost
was nearly four times its mean. Something has to stop a run that is not stopping
itself, and *the invoice* is the default implementation.

## The wrong model

**"Cap the number of calls."**

One budget always has a hole. Three do not:

```text
budget          stops                               misses
calls           a loop that will not terminate      one expensive call
cost            the expensive call                  a fast infinite loop of cheap calls
wall clock      a hung provider                     everything, until it fires
```

Each column's hole is covered by another row. This is why "max_iterations = 10"
is not a budget: it is one third of one.

## The mechanism

The enforcement point matters more than the numbers, and there is only one
correct one: **before the spend**.

```python
def check(self, estimated_cost=0.0):
    if self.calls + 1 > self.max_calls: raise BudgetExceeded(...)
    if self.cost + estimated_cost > self.max_cost: raise BudgetExceeded(...)
    if time.monotonic() - self.started > self.max_seconds: raise BudgetExceeded(...)
```

Token usage is only known **after** the response ([streaming-cancellation.md](streaming-cancellation.md)),
so a budget enforced by reading the usage field is enforced after the money is
spent. Estimate before, reconcile after.

## The experiment

```powershell
cd modules\agent-workflow-lab
python resilience_lab.py
```

A budget of one call, against a run that needs two:

```text
outcome: halted: call budget 1 exhausted
checkpoint after halt: ['classification', 'done', 'passages']
rows written: 0
trace:
  0  classify    {'is_event': True, 'type_hint': 'regulation'}
  1  retrieve    ['P04', 'P05']
```

That is the evidence line, and three properties make it hold. Drop any one and
the other two stop mattering:

- the budget is checked **before** the spend;
- the partial state is **written on the way out**, not discarded by an exception
  handler that only logs;
- **nothing effectful ran**, so the partial state is resumable rather than merely
  informative.

## Boundary

- **Budget the unit of work, not the request.** A document that takes four calls
  and two retries is one unit; per-call limits let a retry loop multiply a
  per-call budget into an unbounded one. Cap total spend and total latency per
  document, and let the call count fall out.
- **Sub-agents share the parent's budget.** A budget per node in a tree is not a
  budget: the tree's total is the product of the branching factor and the node
  limits, and nobody computes that number before shipping.
- **Halting is a result and must be recorded as one.** A halted run that is
  counted as a failure inflates the error rate; counted as a success it hides a
  cost problem. It is a third outcome, with its own count, in the taxonomy
  ([error-taxonomy.md](error-taxonomy.md)).
- **A budget is not a rate limit and neither is a circuit breaker.** The budget
  bounds one run, the rate limit bounds a tenant, the breaker bounds a dependency
  ([provider-errors-retries.md](provider-errors-retries.md)). Systems that have
  one of the three usually believe they have all three.
- **Timeouts need a cancellation path that works.** A wall-clock timeout that
  raises while the provider keeps generating stops your waiting, not your
  spending.

## Cards

### 1. [misconception] Your agent has `max_iterations = 10`. Why is that not a budget?

**Answer:** It bounds one of the three dimensions. A call cap does not stop a
single very expensive call, and does not stop a fast loop of cheap ones from
running for an hour.

**Why:** Calls, cost, and wall clock each miss what the others catch. Any single
limit has a hole covered by another, which is why all three are enforced
together.

**Boundary:** All three must be checked before the spend. Token usage is only
known after the response, so a limit enforced by reading the usage field is
enforced after the money is gone.

**Tags:** `agents` `cost` `misconception` `general-principle`

---

### 2. [scenario] A run halts on budget. What must be true for the halt to be recoverable rather than merely reported?

**Answer:** Partial state written on the way out, and no effectful step having
run.

**Why:** State discarded by an exception handler that only logs makes the halt
informative and nothing else. An effectful step that already ran makes resuming
unsafe, because resuming would repeat it.

**Boundary:** Halting is a third outcome, not a failure and not a success.
Counted as a failure it inflates the error rate; counted as a success it hides
the cost problem that caused it.

**Tags:** `agents` `workflows` `scenario` `general-principle`

---

### 3. [failure] Each sub-agent in your system has a $0.05 budget and the total bill is far higher than expected. What was miscounted?

**Answer:** A budget per node in a tree is not a budget. The total is the
branching factor times the node limit, compounded at every level.

**Why:** Nobody computes that product before shipping, and the per-node number
looks reassuringly small in review.

**Boundary:** The budget must be shared -- a single allocation passed down and
decremented -- so the parent's cap is the system's cap. Per-node limits are then
a fairness policy inside it, not a spend control.

**Tags:** `agents` `cost` `failure` `general-principle`
