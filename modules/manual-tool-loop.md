# The manual tool loop

**Micro module.** One mechanism, one experiment, three cards. Runs against
[agent-workflow-lab/](agent-workflow-lab/), the same `loop_lab.py` as
[deterministic-workflows.md](deterministic-workflows.md) -- read that one first,
because it is the argument for not needing this one.

**Capability:** manual tool loop, no framework (Layer 7, `-` -> Independent).
Map evidence to graduate: "The loop written by hand, with the control flow
visible."

**Gate:** tool calling. Met by [tool-calling.md](tool-calling.md).

---

## The problem

You have decided a loop is genuinely required. The next decision is whether to
write it or adopt one, and the honest answer is: write it once, so that when you
later adopt one you can read its source and know what it is doing to you.

## The wrong model

**"The loop is the hard part."**

The loop is eleven lines:

```python
while steps < limit:
    action = choose_next(state)          # the model call
    if action == "finish":
        return state
    state = apply(action, state)         # the dispatch
    steps += 1
```

Everything difficult is in the four things that surround it: what goes into
`state`, what `apply` is allowed to do, what stops the loop, and what is recorded
about each pass. A framework supplies opinionated versions of all four and hides
which one is failing.

## The mechanism

The loop body, made explicit -- this is the whole content of the module:

| Element | Question | Failure if left implicit |
|---|---|---|
| **State** | what does the model see next turn | context grows until the budget or the window ends the run |
| **Action set** | what may it call, from this state | `store` reachable before `validate` -- 47 times in the lab |
| **Dispatch** | who validates arguments, who executes | a `TypeError` from inside your tool ([tool-calling.md](tool-calling.md)) |
| **Termination** | step limit, budget, explicit finish, error | four terminal states, three of which are not success |
| **Record** | what is written per pass | a trace that cannot answer "why" ([trajectory-tracing.md](trajectory-tracing.md)) |

Termination is the one with the most ways to be wrong. In the lab, 160 runs
produced:

```text
{'finished': 5, 'gave-up': 11, 'step-limit': 19, 'stored': 125}
```

Nineteen runs ended by hitting the step limit. A step limit is a **backstop**,
not a termination condition -- when it fires regularly it means the real
condition is missing, and it will fire on the longest, most expensive runs
because those are the ones that reach it.

## The experiment

```powershell
cd modules\agent-workflow-lab
python loop_lab.py
```

`run_agent` in `loop_lab.py` is the loop, and its policy function is written out
rather than delegated -- including the line that makes `store` reachable from an
unvalidated state, which is a weight of `0.8` and not a bug in the model. Read
that function before reading any framework's.

The trace of a single run is what the loop is for:

```text
0  extract      1  extract      2  extract      3  retrieve
4  extract      5  retrieve     6  retrieve     7  validate
8  resolve      9  resolve     10  store
```

Four extractions and three retrievals for one document. Nothing failed; the
policy simply chose. **When you own the loop this is a tuning problem you can
see. When you do not, it is a bill.**

## Boundary

- **Do not add a framework to fix a loop you have not measured.** Adopt one
  against a named need -- a state machine you keep reimplementing, a persistence
  layer, an integration you would otherwise write -- and record the need. That
  is the map's deliberate ordering: agent frameworks are the **last** row in
  Layer 7 and target Aware, not Working.
- **Bound the action set by state, not by prompt.** "Do not store before
  validating" in the system prompt is a request; removing `store` from the
  available actions until `validated` is true is a control. Same distinction as
  [prompt-injection.md](prompt-injection.md), one layer up.
- **Context growth is the hidden termination condition.** Each pass appends a
  tool result; the window is finite and the cost is superlinear in it. Decide
  what gets summarised or dropped, deliberately, before the loop discovers a
  policy for you by truncating.
- **A loop that can call a loop is a different system.** Sub-agents multiply
  every distribution in this module, and the budget must be shared across the
  tree rather than per node ([budgets-and-timeouts.md](budgets-and-timeouts.md)).

## Cards

### 1. [mechanism] In a hand-written tool loop, which five elements must be explicit, and which is most often left implicit?

**Answer:** State, action set, dispatch, termination, and what is recorded per
pass. Termination is the one usually left to a step limit.

**Why:** A step limit is a backstop, not a termination condition. In the lab, 19
of 160 runs ended by hitting it -- and it fires on the longest and most expensive
runs, because those are the ones that reach it.

**Boundary:** The action set is the close second: constraining it by state is a
control, while asking the model in the prompt not to call something is a request.

**Tags:** `agents` `mechanism` `general-principle`

---

### 2. [decision] Why write the agent loop by hand before adopting a framework?

**Answer:** So that the five elements above are decisions you made, and so you
can read a framework's source later and recognise what it decided for you.

**Why:** Frameworks supply opinionated versions of state handling, action gating,
termination, and tracing, and hide which one is responsible when a run costs four
times its median.

**Boundary:** This is an ordering, not a prohibition. Adopt a framework against a
measured need -- repeated state-machine work, persistence, an integration -- and
record the need, so the adoption is reversible.

**Tags:** `agents` `decision` `general-principle`

---

### 3. [failure] Your agent's median run costs $0.002 and its p95 costs $0.005, with no errors. Where do you look first?

**Answer:** The action distribution per run -- repeated calls to the same tool
without new information between them.

**Why:** In the lab a single document produced four extractions and three
retrievals in one run. Nothing failed and nothing was logged as wrong; the policy
simply chose actions that were available.

**Boundary:** Fixing it in the prompt is the weakest available fix. Preconditions
in the dispatch layer -- "retrieve is unavailable while context is unchanged" --
remove the state instead of discouraging it.

**Tags:** `agents` `cost` `failure` `general-principle`
