"""An eval gate: a scored comparison against a recorded baseline that can block.

    python gate.py                  candidate == baseline, expect PASS
    python gate.py --break datetime candidate emits datetimes, expect FAIL
    python gate.py --break subtle   candidate drops one actor, expect PASS

Exit code is 0 on pass and 1 on fail, so this runs in CI. Requires all five
lab tasks.
"""
import copy
import random
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import scoring
from gold import GOLD
from predictions import SYSTEMS
from scoring import counts_for_field, prf

SHIPPED = "model_b"
TOLERANCE = 0.10          # policy: the most any single field may regress
N_BOOT, SEED = 2000, 20260803

# In a real repository this is a committed JSON file with a git sha and a date,
# not a literal -- the point is that it was recorded, not recomputed.
BASELINE = {
    "recorded": "2026-08-03", "system": SHIPPED, "n_records": 12,
    "schema_validity_rate": 1.0, "record_accuracy": 0.5,
    "fields": {"actors": 0.878, "event_type": 0.9565, "time": 0.9524,
               "location": 0.9565},
}


def mutate(kind):
    if kind == "datetime":
        for record in SYSTEMS[SHIPPED].values():
            if record["time"]:
                record["time"] = record["time"] + "T00:00:00"
    elif kind == "subtle":
        SYSTEMS[SHIPPED]["R10"]["actors"] = ["隆基绿能"]


def noise_floor(field):
    """Bootstrap SE of this field's micro F1, to compare against TOLERANCE."""
    per_record = [
        counts_for_field(field, g.get(field), SYSTEMS[SHIPPED][g["id"]].get(field))
        for g in GOLD
    ]
    rng, n, scores = random.Random(SEED), len(GOLD), []
    for _ in range(N_BOOT):
        sample = [per_record[rng.randrange(n)] for _ in range(n)]
        tp = sum(c[0] for c in sample)
        fp = sum(c[1] for c in sample)
        fn = sum(c[2] for c in sample)
        scores.append(prf(tp, fp, fn)[2])
    scores.sort()
    return (scores[int(0.975 * N_BOOT)] - scores[int(0.025 * N_BOOT)]) / 2


kind = sys.argv[2] if len(sys.argv) > 2 and sys.argv[1] == "--break" else None
original = copy.deepcopy(SYSTEMS[SHIPPED])
try:
    if kind:
        mutate(kind)
    candidate = scoring.score(SHIPPED)
    floors = {f: noise_floor(f) for f in BASELINE["fields"]}
finally:
    SYSTEMS[SHIPPED].clear()
    SYSTEMS[SHIPPED].update(original)

print(f"gate: candidate '{SHIPPED}{'+' + kind if kind else ''}' vs baseline "
      f"recorded {BASELINE['recorded']}   tolerance {TOLERANCE:.2f}\n")

failures = []
print(f"{'check':<26}{'baseline':>10}{'candidate':>11}{'delta':>9}{'noise':>8}  result")
print("-" * 72)

if candidate["schema_validity_rate"] < BASELINE["schema_validity_rate"]:
    failures.append("schema validity regressed")
print(f"{'schema validity':<26}{BASELINE['schema_validity_rate']:>10.4f}"
      f"{candidate['schema_validity_rate']:>11.4f}"
      f"{candidate['schema_validity_rate'] - BASELINE['schema_validity_rate']:>+9.4f}"
      f"{'--':>8}  {'FAIL' if failures else 'ok'}")

for field, base in BASELINE["fields"].items():
    got = candidate["fields"][field]["micro"][2]
    delta = got - base
    bad = delta < -TOLERANCE
    if bad:
        failures.append(f"{field} F1 regressed {delta:+.4f}")
    blind = (not bad) and delta < 0 and abs(delta) < floors[field]
    print(f"{'field F1: ' + field:<26}{base:>10.4f}{got:>11.4f}{delta:>+9.4f}"
          f"{floors[field]:>8.3f}  {'FAIL' if bad else ('ok (under noise)' if blind else 'ok')}")

delta = candidate["record_accuracy"] - BASELINE["record_accuracy"]
if delta < -TOLERANCE:
    failures.append(f"record accuracy regressed {delta:+.4f}")
print(f"{'record accuracy':<26}{BASELINE['record_accuracy']:>10.4f}"
      f"{candidate['record_accuracy']:>11.4f}{delta:>+9.4f}{'--':>8}"
      f"  {'FAIL' if delta < -TOLERANCE else 'ok'}")

print()
if failures:
    print("GATE FAILED -- not shipped:")
    for f in failures:
        print(f"  - {f}")
else:
    print("GATE PASSED.")
    worst = min(floors, key=lambda f: candidate["fields"][f]["micro"][2] - BASELINE["fields"][f])
    d = candidate["fields"][worst]["micro"][2] - BASELINE["fields"][worst]
    if d < 0:
        print(f"  Note: {worst} moved {d:+.4f}, inside this set's noise floor of "
              f"+/-{floors[worst]:.3f}.")
        print("  A regression smaller than the noise floor cannot be caught here,")
        print("  whatever tolerance you set. That is a set-size problem, not a gate one.")
sys.exit(1 if failures else 0)
