"""Sampling and decoding: what temperature costs you, and what it buys.

    python decoding_lab.py
"""
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provider import Provider, repair
from task import DOCUMENTS, record_correct, validate

DRAWS = 50


def sample(provider, doc_id, temperature, constrained, attempt):
    r = provider.complete(doc_id, temperature=temperature,
                          constrained=constrained, attempt=attempt)
    try:
        obj = json.loads(r.text)
    except json.JSONDecodeError:
        obj = None
    return obj, (validate(obj) if obj is not None else ["unparseable"]), r


print("=== 1. Temperature against schema validity ===")
print(f"  {'T':>6}{'valid (free-form)':>20}{'correct':>10}"
      f"{'valid (constrained)':>22}{'correct':>10}")
print("  " + "-" * 70)
provider = Provider("mid-1")
for t in (0.0, 0.2, 0.5, 0.8, 1.0):
    row = [t]
    for constrained in (False, True):
        valid = correct = n = 0
        for doc_id, (_, gold) in DOCUMENTS.items():
            for a in range(DRAWS):
                obj, viol, _ = sample(provider, doc_id, t, constrained, a)
                n += 1
                if not viol:
                    valid += 1
                    correct += record_correct(obj, gold)
        row += [valid / n, correct / n]
    print(f"  {row[0]:>6.1f}{row[1]:>20.3f}{row[2]:>10.3f}"
          f"{row[3]:>22.3f}{row[4]:>10.3f}")
print()
print("  Free-form validity collapses from 0.900 to 0.268 and free-form")
print("  correctness from 0.757 to 0.100 -- three quarters of the loss is")
print("  packaging, and the rest is the model committing to different content.")
print("  Constrained validity does not move at all, and cannot: the decoder")
print("  forbids the failure.")
print()
print("  HONEST LIMIT OF THIS FIXTURE: the constrained CORRECTNESS column is")
print("  temperature-independent by construction -- provider.py's constrained")
print("  branch ignores temperature. The wiggle you see is noise over 400 draws,")
print("  not a finding. In reality temperature does change content under a")
print("  schema, because the constraint applies to the token grammar and not to")
print("  the distribution over values. This lab can show you that the free-form")
print("  collapse is mostly formatting; it cannot tell you the size of the")
print("  content effect, and neither can any lab that is not your own corpus.")
print()

print("=== 2. Where does temperature > 0 pay for itself? ===")
print("  Self-consistency: three samples at T=0.7, majority vote per field,")
print("  against one sample at T=0.0. Cost is measured, not assumed.")
print()
print(f"  {'strategy':<28}{'correct':>10}{'$/doc':>12}{'$/accepted':>13}")
print("  " + "-" * 63)

greedy_correct = greedy_cost = 0
for doc_id, (_, gold) in DOCUMENTS.items():
    obj, viol, r = sample(provider, doc_id, 0.0, True, 0)
    greedy_cost += r.cost
    greedy_correct += bool(not viol and record_correct(obj, gold))
n = len(DOCUMENTS)
print(f"  {'greedy, 1 sample':<28}{greedy_correct / n:>10.3f}"
      f"{greedy_cost / n:>12.6f}{greedy_cost / max(greedy_correct, 1):>13.6f}")

vote_correct = vote_cost = 0
for doc_id, (_, gold) in DOCUMENTS.items():
    votes, objs = Counter(), []
    for a in range(3):
        obj, viol, r = sample(provider, doc_id, 0.7, True, a)
        vote_cost += r.cost
        if not viol:
            objs.append(obj)
    merged = {}
    for field in ("event_type", "date", "location"):
        c = Counter(json.dumps(o.get(field), ensure_ascii=False) for o in objs)
        merged[field] = json.loads(c.most_common(1)[0][0]) if c else None
    c = Counter(json.dumps(sorted(o.get("actors", [])), ensure_ascii=False)
                for o in objs)
    merged["actors"] = json.loads(c.most_common(1)[0][0]) if c else []
    vote_correct += record_correct(merged, DOCUMENTS[doc_id][1])
print(f"  {'majority of 3 @ T=0.7':<28}{vote_correct / n:>10.3f}"
      f"{vote_cost / n:>12.6f}{vote_cost / max(vote_correct, 1):>13.6f}")
print()
print(f"  Eight documents, so that gap is ONE record. It is a direction, not a")
print("  result -- ../eval-set-sample-size.md is the arithmetic. What the table")
print("  does establish without any statistics is the denominator: three calls")
print("  cost 3x, so self-consistency must be compared against simply spending")
print("  the same money on one call to a better model. Read the $/accepted")
print("  column against the large-1 row in schema_lab.py before assuming voting")
print("  is the cheap option; on this fixture it is not.")
print()

print("=== 3. Break it: retry the invalid ones at a higher temperature ===")
print("  A common recipe: sample greedily, and on a validation failure resample")
print("  with temperature to 'shake it loose'. Predict whether it works.")
print()
budget, fixed, attempts = 0.0, 0, 0
failures = 0
for doc_id, (_, gold) in DOCUMENTS.items():
    for a in range(DRAWS):
        obj, viol, r = sample(provider, doc_id, 0.0, False, a)
        budget += r.cost
        attempts += 1
        if not viol:
            continue
        failures += 1
        for t in (0.3, 0.7):
            obj2, viol2, r2 = sample(provider, doc_id, t, False, a + 1000)
            budget += r2.cost
            attempts += 1
            if not viol2:
                fixed += 1
                break
print(f"  {failures} invalid first attempts, {fixed} recovered by resampling")
print(f"  ({fixed / failures:.3f}), at {attempts / (len(DOCUMENTS) * DRAWS):.2f} "
      "calls per document")
repaired = 0
for doc_id in DOCUMENTS:
    for a in range(DRAWS):
        obj, viol, r = sample(provider, doc_id, 0.0, False, a)
        if not viol:
            continue
        try:
            repaired += not validate(json.loads(repair(r.text)))
        except json.JSONDecodeError:
            pass
print(f"  For comparison, repair() alone recovers {repaired} of those "
      f"{failures} at zero additional calls.")
print()
print("  Resampling works, and it is the expensive way to solve a formatting")
print("  problem: it pays a full call to re-roll a die that was mostly going to")
print("  land the same way. Escalate on the failure CLASS, not on the fact of")
print("  failure -- packaging goes to repair(), shape goes to constrained")
print("  decoding, semantics goes to a better model or a different prompt, and")
print("  only genuine nondeterminism goes to a resample.")
print()

print("=== 4. Temperature 0 is not determinism ===")
print("  This lab is deterministic because the fixture is. A real provider at")
print("  temperature 0 is not: floating-point non-associativity under batching,")
print("  mixture-of-experts routing that depends on who else is in the batch,")
print("  and silent model updates all move the output. Greedy decoding removes")
print("  the sampling noise and nothing else.")
print("  Two consequences worth writing down:")
print("   - do not build a cache key, an idempotency key, or a test assertion on")
print("     the assumption that the same prompt returns the same string;")
print("   - when an eval score moves and nothing changed, the null hypothesis is")
print("     provider drift, and the instrument for it is a pinned model plus a")
print("     stored prompt hash (../prompt-versioning.md).")
