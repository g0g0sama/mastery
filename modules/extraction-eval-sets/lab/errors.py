"""Dump every individual error, one line each, for hand classification.

    python errors.py model_a

Unlike the rest of the lab this prints raw field values, because you cannot
classify an error you cannot read. The stdout reconfigure line is what keeps
that from raising UnicodeEncodeError when output is redirected.
"""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gold import GOLD
from policy import SCORED_FIELDS, validate
from predictions import SYSTEMS
from scoring import as_set

system = sys.argv[1] if len(sys.argv) > 1 else "model_a"
preds = SYSTEMS[system]
rows = []
for g in GOLD:
    p = preds[g["id"]]
    bad = validate(p)
    if bad:
        rows.append((g["id"], "-", "INVALID", "; ".join(bad)))
        continue
    for field in SCORED_FIELDS:
        gs, ps = as_set(field, g.get(field)), as_set(field, p.get(field))
        for item in sorted(ps - gs):
            rows.append((g["id"], field, "INVENTED", item))
        for item in sorted(gs - ps):
            rows.append((g["id"], field, "MISSED", item))

print(f"{system}: {len(rows)} errors\n")
print(f"{'rec':<5}{'field':<12}{'kind':<10}value")
print("-" * 70)
for r in rows:
    print(f"{r[0]:<5}{r[1]:<12}{r[2]:<10}{r[3]}")
print()
print("Now assign a CLASS to each line by hand -- a cause, not a restatement.")
print("'actors MISSED' is not a class. 'gold holds the short form, model emits")
print("the registered legal name' is a class, and it names its own fix.")
