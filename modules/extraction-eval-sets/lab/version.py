"""Version the set AND the instrument, so a number stays meaningful later.

    python version.py

A score is comparable to another score only if the labels and the matching
policy were the same. Three things can move a number, and only one of them is
your system. Requires all five lab tasks.
"""
import copy
import hashlib
import json
import pathlib
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

import policy
import scoring
from gold import GOLD
from policy import SCORED_FIELDS

PROBES = ["中国石化 ", "宁德时代（ＣＡＴＬ）", "华为技术有限公司", "华为",
          "福建省宁德市", "深圳市", "深圳", "安徽省", "2026-03-14",
          "2026-03-14T00:00:00", "sanction", "SANCTION "]


def digest(payload):
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()[:10]


def gold_hash():
    """The labels, canonically. Changes when a label is added, removed or fixed."""
    payload = json.dumps(
        [{f: g.get(f) for f in ("id",) + SCORED_FIELDS} for g in GOLD],
        sort_keys=True, ensure_ascii=False,
    )
    return digest(payload)


def source_hash():
    """The policy FILE. Catches edits to the file -- and nothing else."""
    return digest(pathlib.Path(policy.__file__).read_text(encoding="utf-8"))


def behavior_hash():
    """The policy's BEHAVIOUR on fixed probes. Catches any change, however made."""
    lines = [f"{field}|{p}|{policy.NORMALIZERS[field](p)}"
             for field in sorted(policy.NORMALIZERS) for p in PROBES]
    lines.append("vocab|" + ",".join(sorted(policy.EVENT_TYPES)))
    return digest("\n".join(lines))


def stamp():
    return {"gold": gold_hash(), "policy_src": source_hash(),
            "policy_behavior": behavior_hash()}


def compare(baseline, candidate):
    """Refuse to compare two numbers produced under different instruments."""
    reasons = []
    if baseline["stamp"]["gold"] != candidate["stamp"]["gold"]:
        reasons.append("the LABELS changed -- the target moved, not the system")
    if baseline["stamp"]["policy_behavior"] != candidate["stamp"]["policy_behavior"]:
        reasons.append("the POLICY changed -- the ruler moved, not the system")
    if reasons:
        return "INCOMPARABLE: " + "; ".join(reasons)
    delta = candidate["score"] - baseline["score"]
    return f"comparable: record accuracy {delta:+.4f} -- this is the system"


def snapshot():
    return {"stamp": stamp(), "score": scoring.score("model_b")["record_accuracy"]}


baseline = snapshot()
print(f"{'scenario':<34}{'gold':>12}{'policy_src':>12}{'policy_beh':>12}{'rec acc':>9}")
print("-" * 79)


def show(label, snap):
    s = snap["stamp"]
    print(f"{label:<34}{s['gold']:>12}{s['policy_src']:>12}"
          f"{s['policy_behavior']:>12}{snap['score']:>9.4f}")


show("baseline", baseline)

# 1. The ruler moves: normalizers swapped at runtime, file untouched.
saved = dict(policy.NORMALIZERS)
policy.NORMALIZERS.update({f: (lambda r: "" if r is None else str(r).strip())
                           for f in policy.NORMALIZERS})
try:
    ruler = snapshot()
finally:
    policy.NORMALIZERS.update(saved)
show("policy changed at runtime", ruler)

# 2. The target moves: one gold label corrected.
saved_gold = copy.deepcopy(GOLD)
try:
    for g in GOLD:
        if g["id"] == "R09":
            g["time"] = "2026-04-05"      # decided the month-only case gets a day
    target = snapshot()
finally:
    GOLD[:] = saved_gold
show("gold label corrected (R09)", target)

print()
for label, snap in (("policy changed at runtime", ruler),
                    ("gold label corrected", target),
                    ("nothing changed", baseline)):
    print(f"  compare(baseline, {label + ')':<28} -> {compare(baseline, snap)}")
print()
print("Note the second column. The policy FILE hash is identical in every row --")
print("the runtime swap never touched it. Hash what the instrument DOES, not")
print("what its source looks like, or config and monkeypatching slip through.")
