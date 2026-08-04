"""Checkpoints, budgets, and traces: what survives a killed process.

    python resilience_lab.py
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent import (Budget, BudgetExceeded, Checkpoint, Store, Trace, check,
                   classify, extract, resolve_actors, retrieve, store)
from provider import Provider
from task import DOCUMENTS

# Steps, in order, tagged with whether re-running one is free of consequences.
# This table is the whole of resumability. Everything else is bookkeeping.
STEPS = [
    ("classify", "pure"),
    ("retrieve", "pure"),
    ("extract", "pure-but-paid"),
    ("validate", "pure"),
    ("store", "EFFECTFUL"),
]


class Killed(Exception):
    pass


def run(doc_id, store_, ckpt, budget, kill_at=None, resume=True):
    """One document, resumable. State is keyed by the WORK -- doc id plus
    prompt version -- so a retry of the same work finds the same checkpoint and
    a genuinely new run does not."""
    run_id = f"{doc_id}:v1"
    state = ckpt.load(run_id) if resume else {}
    trace = Trace(run_id)
    provider = Provider("mid-1")
    try:
        for name, kind in STEPS:
            if name in state.get("done", []):
                trace.record(f"skip:{name}", {"doc": doc_id}, "from checkpoint")
                continue
            if kill_at == name:
                raise Killed(f"process died during {name}")
            if name == "classify":
                state["classification"] = classify(doc_id, provider, budget, trace)
            elif name == "retrieve":
                state["passages"] = list(retrieve(doc_id, trace, isolate=True))
            elif name == "extract":
                state["record"] = extract(doc_id, {}, provider, budget, trace)
            elif name == "validate":
                state["violations"] = check(state.get("record"), trace)
                if state["violations"]:
                    state.setdefault("done", []).append(name)
                    ckpt.save(run_id, state)
                    return "rejected", trace
            elif name == "store":
                state["stored"] = store(doc_id, state.get("record"), store_,
                                        trace, key=run_id)
            state.setdefault("done", []).append(name)
            ckpt.save(run_id, state)          # after each step, before the next
        return "stored", trace
    except (Killed, BudgetExceeded) as exc:
        ckpt.save(run_id, state)              # the partial result is preserved
        return f"halted: {exc}", trace


print("=== 1. A killed process, with and without a checkpoint ===")
for resume in (False, True):
    st, ck, bg = Store(), Checkpoint(), Budget(max_calls=20, max_cost=1.0)
    outcome, t1 = run("N02", st, ck, bg, kill_at="store", resume=resume)
    calls_before = bg.calls
    outcome2, t2 = run("N02", st, ck, bg, resume=resume)
    label = "with resume" if resume else "no resume"
    print(f"  {label:<14} first run: {outcome}")
    print(f"  {'':<14} restart:   {outcome2}, "
          f"model calls {calls_before} then {bg.calls - calls_before}")
    print(f"  {'':<14} steps replayed on restart: "
          f"{[s for _, s, _ in t2.replay()]}")
print()
print("  Without a checkpoint the restart re-pays for classify and extract --")
print("  every paid step before the failure, every time. With one it replays")
print("  four skips and one real step. At two model calls per document that is")
print("  a rounding error; at a twenty-step research run it is the difference")
print("  between a retry and a rewrite.")
print()

print("=== 2. The only classification that matters ===")
for name, kind in STEPS:
    print(f"  {name:<12}{kind}")
print()
print("  Resumability is not 'save the state'. It is knowing which steps may be")
print("  re-executed. `store` is the one that may not, and a resume that")
print("  re-runs it produces the duplicate row from")
print("  ../provider-errors-retries.md -- so the checkpoint key and the")
print("  idempotency key must be THE SAME KEY, derived from the work. Two keys")
print("  for one identity is how a system resumes correctly and writes twice.")
print()
print("  `pure-but-paid` is the category people forget. Re-running extract is")
print("  safe and not free, which is why the checkpoint is written after it and")
print("  not at the end of the run.")
print()

print("=== 3. Halting on budget, with partial results preserved ===")
st, ck = Store(), Checkpoint()
tight = Budget(max_calls=1)                 # enough for classify, not extract
outcome, trace = run("N03", st, ck, tight)
print(f"  outcome: {outcome}")
print(f"  checkpoint after halt: {sorted(ck.load('N03:v1'))}")
print(f"  rows written: {len(st.rows)}")
print("  trace:")
for seq, step, preview in trace.replay():
    print(f"    {seq}  {step:<12}{preview}")
print()
print("  That is the map's evidence line for this row: a run that halts on")
print("  budget with partial results preserved. Three properties make it work,")
print("  and dropping any one of them makes the other two pointless:")
print("   - the budget is checked BEFORE the spend, because usage is only")
print("     known afterwards (../streaming-cancellation.md);")
print("   - the partial state is written on the way out, not discarded by an")
print("     exception handler that only logs;")
print("   - nothing effectful ran, so the partial state is resumable rather")
print("     than merely informative.")
print()

print("=== 4. Three budgets, not one ===")
print(f"  {'budget':<16}{'stops':<34}{'misses'}")
print("  " + "-" * 74)
print(f"  {'calls':<16}{'a loop that will not terminate':<34}"
      "one expensive call")
print(f"  {'cost':<16}{'the expensive call':<34}"
      "a fast infinite loop of cheap calls")
print(f"  {'wall clock':<16}{'a hung provider':<34}"
      "everything, until it fires")
print("  Any single budget has a hole the other two cover. A runaway loop")
print("  stopped by a bill instead of by a budget is the Layer 10 row, and it")
print("  is the same three numbers seen from the security side.")
print()

print("=== 5. What a trace has to contain to be worth keeping ===")
st, ck, bg = Store(), Checkpoint(), Budget(max_calls=20, max_cost=1.0)
_, trace = run("N01", st, ck, bg)
event = trace.events[2]
for k, v in event.items():
    print(f"    {k:<16}{v}")
print()
print("  Inputs as digests, output as a digest plus a short preview, cost, and")
print("  the model that produced it. The digests are what make the trace")
print("  affordable, and affordability is the whole design constraint: a trace")
print("  you cannot afford to keep gets sampled, and sampling drops the rare")
print("  failure you needed it for. Store digests always, payloads for the")
print("  failures, and never the other way round.")
print()
print("  What must be reconstructable from a trace, in the order you will want")
print("  it: which steps ran, in what order, with what inputs, at what cost,")
print("  against which model and prompt version. The last two are stamped in")
print("  ../routing-and-fallback.md; without them the trace tells you what")
print("  happened and not what to change.")
