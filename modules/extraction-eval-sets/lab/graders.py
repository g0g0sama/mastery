"""Deterministic graders, and the precision of each one.

    python graders.py

Every check below runs on the output alone -- no gold label is consulted to
produce a finding. That is the property that matters: these can run over
production records where no labelled answer exists, which is where the volume
is and where your eval set is not.

The labels are used for one thing only, at the end: to measure how often each
grader was right. A grader is itself a classifier and has its own precision.
Requires the lab's tasks 1 and 2.
"""
import sys
from collections import defaultdict

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gold import GOLD_BY_ID
from policy import NORMALIZERS, validate
from predictions import SYSTEMS
from scoring import counts_for_field

# Each check returns (label, field_it_implicates) or None.


def schema_checks(record, meta):
    for violation in validate(record):
        yield f"schema: {violation}", "event_type"


def invariant_checks(record, meta):
    """Facts about a storable record. Violating one is definitionally an error."""
    actors = record.get("actors") or []
    normalized = [NORMALIZERS["actors"](a) for a in actors]
    if len(set(normalized)) != len(normalized):
        yield "invariant: duplicate actors after normalization", "actors"
    if not actors:
        yield "invariant: event with no actor", "actors"
    time = record.get("time")
    if time and time[:10] > meta["fetched_at"][:10]:
        yield "invariant: event dated after the article was fetched", "time"


def suspicion_checks(record, meta):
    """Heuristics. Correlated with error, but not definitionally wrong."""
    time = record.get("time")
    if time and time[:10] == meta["fetched_at"][:10]:
        yield "suspicion: event date equals fetch date", "time"
    conf = record.get("confidence")
    if conf is not None and conf >= 0.9 and not (record.get("actors") or []):
        yield "suspicion: high confidence, no actors", "actors"


CHECKS = (schema_checks, invariant_checks, suspicion_checks)
ALL_LABELS = [
    "schema: actors must be a list of strings",
    "schema: event_type outside the closed vocabulary",
    "schema: time must be ISO-8601",
    "invariant: duplicate actors after normalization",
    "invariant: event with no actor",
    "invariant: event dated after the article was fetched",
    "suspicion: event date equals fetch date",
    "suspicion: high confidence, no actors",
]

fired = defaultdict(int)
real = defaultdict(int)
detail = []

for system, preds in SYSTEMS.items():
    for rid, record in preds.items():
        meta = GOLD_BY_ID[rid]["source"]
        for check in CHECKS:
            for label, field in check(record, meta):
                fired[label] += 1
                # NOW consult the labels, only to judge the grader.
                if label.startswith("schema"):
                    was_real = True
                else:
                    _tp, fp, fn = counts_for_field(
                        field, GOLD_BY_ID[rid].get(field), record.get(field)
                    )
                    was_real = bool(fp or fn)
                real[label] += was_real
                detail.append((system, rid, label, was_real))

print(f"{'check':<52}{'fired':>7}{'real':>6}{'precision':>11}")
print("-" * 76)
for label in ALL_LABELS:
    f, r = fired[label], real[label]
    p = f"{r / f:.3f}" if f else "--"
    print(f"{label:<52}{f:>7}{r if f else '--':>6}{p:>11}")
print()
print("36 predictions scored (3 systems x 12 records), no gold used to fire a check.")
print()
print("False alarms, by system:")
for system in SYSTEMS:
    misses = [d for d in detail if d[0] == system and not d[3]]
    print(f"  {system:<9}{len(misses):>3}  " + ", ".join(sorted({d[1] for d in misses})))
