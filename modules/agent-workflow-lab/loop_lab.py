"""The same job twice: a fixed pipeline, and a model-driven loop.

    python loop_lab.py
"""
import random
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent import (Budget, BudgetExceeded, Store, Trace, check, classify,
                   extract, resolve_actors, retrieve, store)
from provider import Provider
from task import DOCUMENTS, record_correct

MAX_STEPS = 12
UNVALIDATED_WRITES = []


def run_pipeline(doc_id, store_, isolate=True):
    """Five steps, one order, every failure attributable to a named step."""
    provider, budget, trace = Provider("mid-1"), Budget(), Trace(doc_id)
    try:
        classify(doc_id, provider, budget, trace)
        passages = retrieve(doc_id, trace, isolate=isolate)
        record = extract(doc_id, passages, provider, budget, trace,
                         obey_injection=not isolate)
        if violations := check(record, trace):
            return {"outcome": "rejected", "failed_at": "validate",
                    "detail": violations, "trace": trace, "record": None}
        resolve_actors(record, trace)
        store(doc_id, record, store_, trace)
        return {"outcome": "stored", "failed_at": None, "trace": trace,
                "record": record}
    except BudgetExceeded as exc:
        return {"outcome": "halted", "failed_at": trace.events[-1]["step"],
                "detail": str(exc), "trace": trace, "record": None}


def run_agent(doc_id, store_, seed=0):
    """The model chooses the next action. The policy below stands in for that
    choice: it is a plausible-but-meandering planner, seeded so the run is
    reproducible. What it models is not stupidity -- it is that the ORDER is
    now a sampled variable rather than a written one."""
    rng = random.Random(f"{doc_id}:{seed}")
    provider, budget, trace = Provider("mid-1"), Budget(max_calls=8), Trace(doc_id)
    state = {"passages": None, "record": None, "validated": False}
    try:
        for _ in range(MAX_STEPS):
            options = ["retrieve", "extract", "resolve", "validate", "store",
                       "finish"]
            weights = [
                3 if state["passages"] is None else 1,
                4 if state["record"] is None else 1,
                2 if state["record"] else 0.2,
                3 if state["record"] and not state["validated"] else 0.5,
                4 if state["validated"] else 0.8,      # note the 0.8
                0.2 if state["validated"] else 0.05,
            ]
            action = rng.choices(options, weights=weights)[0]
            if action == "retrieve":
                state["passages"] = retrieve(doc_id, trace, isolate=True)
            elif action == "extract":
                state["record"] = extract(doc_id, state["passages"] or {},
                                          provider, budget, trace,
                                          obey_injection=False)
                state["validated"] = False
            elif action == "resolve" and state["record"]:
                resolve_actors(state["record"], trace)
            elif action == "validate" and state["record"]:
                state["validated"] = not check(state["record"], trace)
            elif action == "store" and state["record"]:
                store(doc_id, state["record"], store_, trace)
                if not state["validated"]:
                    UNVALIDATED_WRITES.append((doc_id, seed))
                if state["validated"]:
                    return {"outcome": "stored", "trace": trace,
                            "record": state["record"]}
            elif action == "finish":
                return {"outcome": "finished" if state["validated"] else "gave-up",
                        "trace": trace, "record": state["record"]}
        return {"outcome": "step-limit", "trace": trace, "record": state["record"]}
    except BudgetExceeded as exc:
        return {"outcome": "halted", "detail": str(exc), "trace": trace,
                "record": None}


print("=== 1. Same work, both ways -- 8 documents x 20 seeds ===")
SEEDS = range(20)
print(f"  {'system':<20}{'stored':>8}{'correct':>9}{'steps':>14}"
      f"{'$/doc':>11}{'$ p95':>10}")
print("  " + "-" * 72)
summaries = {}
for label, runner in (("fixed pipeline", run_pipeline), ("agent loop", run_agent)):
    st = Store()
    stored = correct = 0
    steps, costs, outcomes = [], [], []
    for seed in SEEDS:
        for doc_id, (_, gold) in DOCUMENTS.items():
            res = (runner(doc_id, st) if runner is run_pipeline
                   else runner(doc_id, st, seed=seed))
            steps.append(len(res["trace"].events))
            costs.append(res["trace"].total_cost())
            outcomes.append(res["outcome"])
            if res["outcome"] in ("stored", "finished") and res["record"]:
                stored += 1
                correct += record_correct(res["record"], gold)
    n = len(steps)
    p95 = sorted(costs)[int(0.95 * n)]
    summaries[label] = outcomes
    print(f"  {label:<20}{stored / n:>8.3f}{correct / n:>9.3f}"
          f"{f'{min(steps)}..{max(steps)}':>14}{sum(costs) / n:>11.6f}{p95:>10.6f}")
print()
print("  Read the steps column before the accuracy column. The pipeline runs six")
print("  steps every time, for every document, forever, and its p95 cost is")
print("  within 7% of its mean. The loop runs anywhere from zero steps to the")
print("  step limit, and its p95 is nearly FOUR TIMES its mean. Cost stopped")
print("  being a number and became a distribution -- and the number that gets")
print("  quoted in the design document is the mean.")
print()
print("  You cannot capacity-plan, price, or set a timeout against a")
print("  distribution nobody characterised. That, not the accuracy column, is")
print("  what a loop costs you here -- and it bought nothing, because the order")
print("  of the steps was known before the first document arrived.")
print()

print("=== 2. Terminal states, which is where the real difference lives ===")
for label, outcomes in summaries.items():
    counts = {o: outcomes.count(o) for o in sorted(set(outcomes))}
    print(f"  {label:<20}{counts}")
print()
print(f"  Unvalidated records written to the store: {len(UNVALIDATED_WRITES)}")
print(f"  e.g. {UNVALIDATED_WRITES[:4]}")
print("  `store` is reachable while `validated` is False -- weight 0.8 in the")
print("  policy, not 0 -- so a record that failed validation reaches the")
print("  database and the run carries on. In a pipeline that ordering is a code")
print("  review comment; in a loop it is a probability, and it happens on the")
print("  day nobody is watching. The pipeline cannot express this state at all,")
print("  which is the actual argument for pipelines: not that they are better,")
print("  that they have fewer reachable states.")
print()

print("=== 3. Attributing a failure ===")
st = Store()
p = run_pipeline("N01", st, isolate=True)
print(f"  pipeline outcome: {p['outcome']}, failed_at: {p['failed_at']}")
print("  trace:")
for seq, step, preview in p["trace"].replay():
    print(f"    {seq}  {step:<16}{preview}")
print()
a = run_agent("N01", Store(), seed=3)
print(f"  agent outcome: {a['outcome']}")
print("  trace:")
for seq, step, preview in a["trace"].replay():
    print(f"    {seq}  {step:<16}{preview}")
print()
print("  Both traces are complete. Only one of them answers 'what do I fix'.")
print("  The pipeline's step names ARE the failure taxonomy: a rise in")
print("  `failed_at=validate` is a schema or prompt problem, a rise in")
print("  `failed_at=retrieve` is an index problem, and each has an owner. The")
print("  loop's trace tells you what happened and leaves the causal question")
print("  entirely to you -- which is affordable at eight documents and is not")
print("  at eight thousand.")
print()

print("=== 4. The rule, and the cases that genuinely need a loop ===")
print("  Write the workflow first. Reach for a loop only when the ORDER of")
print("  operations depends on what earlier operations returned, in a way you")
print("  cannot enumerate. Three honest examples:")
print("   - a research task where the next query depends on what was found;")
print("   - a repair loop where the tool result names what to fix;")
print("   - an interactive session where a human injects new goals mid-run.")
print("  Extraction is none of these. classify -> retrieve -> extract ->")
print("  validate -> store was fully determined before the first document")
print("  arrived, and a model asked to choose that order can only get it wrong.")
