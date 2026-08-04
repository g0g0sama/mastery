"""Structured outputs: what a schema guarantees, and what it quietly moves.

    python schema_lab.py

200 samples per cell (8 documents x 25 draws), deterministic. The provider's
failure distribution is declared in provider.py rather than discovered here --
this lab measures the CONSEQUENCES of that distribution, which is the part that
is not obvious even when you wrote the generator.
"""
import json
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provider import Provider, repair
from task import DOCUMENTS, SCORED_FIELDS, field_match, record_correct, validate

DRAWS = 25


def run(model, constrained, temperature=0.0, use_repair=False, draws=DRAWS):
    provider = Provider(model)
    rows = []
    for doc_id, (_, gold) in DOCUMENTS.items():
        for attempt in range(draws):
            r = provider.complete(doc_id, temperature=temperature,
                                  constrained=constrained, attempt=attempt)
            text = repair(r.text) if use_repair else r.text
            try:
                obj = json.loads(text)
                parse_error = None
            except json.JSONDecodeError:
                obj, parse_error = None, "parse"
            violations = validate(obj) if obj is not None else ["root/unparseable"]
            rows.append({"doc": doc_id, "gold": gold, "obj": obj, "mode": r.mode,
                         "parse_error": parse_error, "violations": violations,
                         "cost": r.cost})
    return rows


def summarize(rows):
    n = len(rows)
    valid = [r for r in rows if not r["violations"]]
    correct = [r for r in valid if record_correct(r["obj"], r["gold"])]
    return {
        "n": n,
        "parses": sum(1 for r in rows if r["parse_error"] is None) / n,
        "validity": len(valid) / n,
        "accuracy": len(correct) / n,
        "cost_per_accepted": (sum(r["cost"] for r in rows) / len(correct)
                              if correct else float("inf")),
    }


print("=== 1. The headline number, and the one underneath it ===")
print(f"  {'system':<34}{'parses':>9}{'valid':>8}{'correct':>9}{'$/accepted':>12}")
print("  " + "-" * 72)
cells = {}
for model in ("tiny-1", "mid-1", "large-1"):
    for constrained in (False, True):
        rows = run(model, constrained)
        s = summarize(rows)
        cells[(model, constrained)] = (rows, s)
        label = f"{model} {'constrained' if constrained else 'free-form'}"
        print(f"  {label:<34}{s['parses']:>9.3f}{s['validity']:>8.3f}"
              f"{s['accuracy']:>9.3f}{s['cost_per_accepted']:>12.6f}")
print()
m_free, m_con = cells[("mid-1", False)][1], cells[("mid-1", True)][1]
print(f"  mid-1: validity +{m_con['validity'] - m_free['validity']:.3f}, "
      f"accuracy +{m_con['accuracy'] - m_free['accuracy']:.3f} -- the headline")
print("  moves about three times as far as the thing the headline stands for.")
print("  A schema constrains the SHAPE of the output and says nothing about its")
print("  CONTENT, so a dashboard showing schema-validity climbing to 100% is")
print("  entirely compatible with the extraction getting worse. Section 3 shows")
print("  the direction the remaining errors moved, which is the part that")
print("  decides whether this trade was good.")
print()

print("=== 2. Where the failures went ===")
for model in ("mid-1",):
    for constrained in (False, True):
        rows, _ = cells[(model, constrained)]
        modes = Counter(r["mode"] for r in rows)
        label = "constrained" if constrained else "free-form"
        print(f"  {model} {label}:")
        for mode, k in modes.most_common():
            print(f"    {mode:<24}{k:>5}  {k / len(rows):>7.3f}")
        print()
print("  Constrained decoding did not make the model better. It deleted three")
print("  syntax modes and three shape modes -- and every one of those was")
print("  DETECTABLE. What remains is the semantic failures, which are valid,")
print("  well-formed, and wrong. You have traded loud errors for silent ones,")
print("  which is usually the right trade and never a free one.")
print()

print("=== 3. Empty versus wrong: the split that constrained decoding hides ===")
print("  800 draws per row, because this difference is smaller than the one in")
print("  section 1 and 200 draws cannot resolve it (../eval-set-sample-size.md).")
print(f"  {'system':<30}{'omitted a field':>18}{'filled it wrongly':>20}")
print("  " + "-" * 68)
for temperature in (0.0, 0.6):
    for constrained in (False, True):
        rows = run("mid-1", constrained, temperature=temperature, draws=100)
        omitted = sum(1 for r in rows if r["mode"] == "missing_date")
        filled = sum(1 for r in rows if r["mode"] in ("location_filled",
                                                      "hallucinated_actor",
                                                      "date_is_fetch_date"))
        label = f"T={temperature} {'constrained' if constrained else 'free-form'}"
        print(f"  mid-1 {label:<24}{omitted / len(rows):>18.3f}"
              f"{filled / len(rows):>20.3f}")
print("  A required field cannot be omitted under a schema, so the model emits")
print("  something. Abstention becomes confabulation. For a pipeline that writes")
print("  to a database this is the most expensive line in this file: a missing")
print("  date is a row you can queue for review, and a wrong date is a row")
print("  nobody will ever look at again. Make `location` and `date` nullable and")
print("  the abstention comes back -- which is a schema DESIGN decision, not a")
print("  decoding one.")
print()

print("=== 4. How much of the validity gap was worth a schema at all ===")
rows_plain = run("mid-1", constrained=False)
rows_fixed = run("mid-1", constrained=False, use_repair=True)
print(f"  free-form, raw          validity {summarize(rows_plain)['validity']:.3f}")
print(f"  free-form, + repair()   validity {summarize(rows_fixed)['validity']:.3f}")
print(f"  constrained             validity {cells[('mid-1', True)][1]['validity']:.3f}")
print("  Thirty lines of fence-stripping and trailing-comma removal recover most")
print("  of the difference, because most free-form invalidity is packaging, not")
print("  confusion. Measure this before adopting constrained decoding: if repair")
print("  closes the gap, the schema is buying you the SEMANTIC change in")
print("  section 3, and you should decide whether you want it.")
print()

print("=== 5. Per-field, because the record-level number locates nothing ===")
print("  Conditioned on the record parsing, so this measures content quality")
print("  rather than re-counting the packaging failures from section 1.")
print(f"  {'field':<14}{'free-form':>12}{'constrained':>14}")
print("  " + "-" * 40)
for field in SCORED_FIELDS:
    row = [field]
    for constrained in (False, True):
        rows, _ = cells[("mid-1", constrained)]
        parsed = [r for r in rows if r["obj"] is not None]
        ok = sum(1 for r in parsed if field_match(r["obj"], r["gold"], field))
        row.append(ok / len(parsed))
    print(f"  {row[0]:<14}{row[1]:>12.3f}{row[2]:>14.3f}")
print("  Two fields go DOWN under the schema, and they are the two the record")
print("  level averaged away. `actors` loses the most: forced to emit a non-empty")
print("  array it appends a plausible extra organization. `date` loses because")
print("  the model returns the FETCH date rather than the event date -- valid,")
print("  well-formed, plausible, and the most common real extraction bug in news.")
print("  No schema can express 'this date must be the one in the sentence, not")
print("  the one in the metadata'. That is a grader's job")
print("  (../deterministic-graders.md), and this is why the two modules exist.")
print()

print("=== 6. Violation codes, for the taxonomy ===")
rows, _ = cells[("tiny-1", False)]
codes = Counter(v for r in rows for v in r["violations"])
for code, k in codes.most_common(8):
    print(f"  {code:<28}{k:>5}")
print("  Codes rather than messages, so they can be counted, and counted so they")
print("  can be ranked. The map's Deep target for this row is 'failure modes")
print("  taxonomized' -- this table is the input to that, and")
print("  ../error-taxonomy.md is the method for turning it into one.")
