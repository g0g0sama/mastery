"""Routing, fallback, and model versioning: three things that look like config.

    python routing_lab.py
"""
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provider import MODELS, OverloadedError, Provider, repair
from task import DOCUMENTS, record_correct, validate

DRAWS = 25


def attempt(model, doc_id, gold, attempt_no, constrained=True):
    r = Provider(model).complete(doc_id, constrained=constrained,
                                 attempt=attempt_no)
    try:
        obj = json.loads(repair(r.text))
    except json.JSONDecodeError:
        obj = None
    ok = obj is not None and not validate(obj) and record_correct(obj, gold)
    return ok, r.cost, r.model.name


print("=== 1. One model per task is a cost decision, not a taste one ===")
print(f"  {'strategy':<32}{'correct':>10}{'$/doc':>12}{'$/accepted':>13}")
print("  " + "-" * 67)
results = {}
for model in MODELS:
    ok = cost = n = 0
    for doc_id, (_, gold) in DOCUMENTS.items():
        for a in range(DRAWS):
            good, c, _ = attempt(model, doc_id, gold, a)
            ok += good
            cost += c
            n += 1
    results[model] = (ok / n, cost / n)
    print(f"  {'always ' + model:<32}{ok / n:>10.3f}{cost / n:>12.6f}"
          f"{cost / max(ok, 1):>13.6f}")

# Escalation: run the cheap model, and only if its output fails validation
# does the expensive one see the document. Note what this can and cannot fix.
ok = cost = n = escalated = 0
for doc_id, (_, gold) in DOCUMENTS.items():
    for a in range(DRAWS):
        r = Provider("tiny-1").complete(doc_id, constrained=False, attempt=a)
        cost += r.cost
        n += 1
        try:
            obj = json.loads(repair(r.text))
            invalid = bool(validate(obj))
        except json.JSONDecodeError:
            obj, invalid = None, True
        if invalid:
            escalated += 1
            good, c, _ = attempt("large-1", doc_id, gold, a)
            cost += c
            ok += good
        else:
            ok += record_correct(obj, gold)
print(f"  {'tiny-1, escalate on invalid':<32}{ok / n:>10.3f}{cost / n:>12.6f}"
      f"{cost / max(ok, 1):>13.6f}")
print(f"  ({escalated}/{n} documents escalated)")
print()
print("  Escalation only routes on what the CHEAP model told you about itself,")
print("  and a schema violation is the one signal it gives away for free. It")
print("  cannot escalate a confident wrong answer, which is most of tiny-1's")
print("  error budget (../structured-outputs.md, section 2). Cascades work when")
print("  the cheap model's failures are LOUD; measure that ratio before")
print("  building one, because the architecture is worthless without it.")
print()

print("=== 2. Fallback: what a degraded run looks like from the outside ===")


def with_fallback(doc_id, gold, a, primary="large-1", secondary="mid-1",
                  outage=True):
    if outage:
        try:
            raise OverloadedError("primary unavailable")
        except OverloadedError:
            return attempt(secondary, doc_id, gold, a)
    return attempt(primary, doc_id, gold, a)


for outage in (False, True):
    ok = cost = n = 0
    used = Counter()
    for doc_id, (_, gold) in DOCUMENTS.items():
        for a in range(DRAWS):
            good, c, name = with_fallback(doc_id, gold, a, outage=outage)
            ok += good
            cost += c
            n += 1
            used[name] += 1
    label = "during a primary outage" if outage else "normal operation"
    print(f"  {label:<28}correct {ok / n:.3f}   $/doc {cost / n:.6f}   {dict(used)}")
print()
print("  The failure is invisible: no error reaches the caller, latency improves")
print("  because the fallback is faster, cost drops, and quality falls. Every")
print("  signal points the wrong way. This is why the model name belongs IN THE")
print("  STORED RECORD -- without it, the next eval run shows a regression with")
print("  no cause attached, and you will look for it in your prompt.")
print()

print("=== 3. A record that can answer 'what produced you' ===")
doc_id = "N01"
r = Provider("mid-1").complete(doc_id, constrained=True, prompt_version="v2")
record = json.loads(repair(r.text))
stamped = record | {
    "_model": r.model.name,
    "_model_pinned": "mid-1@2026-02-14",      # a version, not a family name
    "_prompt_version": "v2",
    "_constrained": True,
    "_temperature": 0.0,
    "_usage": r.usage,
    "_cost": round(r.cost, 8),
}
print(json.dumps(stamped, ensure_ascii=False, indent=2)[:520])
print()
print("  Five fields, none of them interesting until the day they are the only")
print("  thing that explains a number. The pinned version is the one people")
print("  omit: 'mid-1' is a moving alias and a provider may repoint it without")
print("  telling you, which produces a quality change with no diff, no deploy,")
print("  and no cause. Pin the dated version, record it, and let a scheduled")
print("  eval run detect the drift (../eval-gates.md).")
print()

print("=== 4. What routing must never do ===")
print("  Route on the DOCUMENT and the TASK -- length, language, whether the")
print("  schema is nested, whether the answer will be stored or shown. Never")
print("  route on the user, the tenant, or the time of day without recording it,")
print("  because a routing key that is not in the record is a hidden variable")
print("  in every measurement you take afterwards.")
print("  And keep the routing table declarative. A router written as branching")
print("  code inside the call site cannot be enumerated, which means it cannot")
print("  be tested, and the first symptom is a document class that has been")
print("  silently going to the wrong model for a month.")
