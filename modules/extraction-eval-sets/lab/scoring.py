"""The scorer. Five stubs; everything else is given.

Conventions this file commits to, all of them arguable and all of them the sort
of thing that silently moves a headline number:

- A scalar field is a set of size 0 or 1. That single decision removes every
  special case: precision and recall are then defined identically for `actors`
  and for `event_type`, and "predicted nothing" stops being a crash.

- Records that FAIL VALIDATION are excluded from per-field scoring and reported
  separately. Consequence, and it is a trap: per-field scores are computed on
  the valid subset, so a system that emits invalid output on exactly its hardest
  documents scores better on the remainder. Always read n_scored next to the
  field scores. `record_accuracy` uses the full denominator on purpose.

- Micro precision with no predictions at all is 0.0. Macro precision with no
  predictions on a record is 1.0. Both conventions are standard and they
  disagree; see prf(). The consequence is that macro precision rewards
  abstention, which is exactly the behaviour you are trying to measure, so never
  report macro precision alone for a system that can decline to answer.
"""

from __future__ import annotations

from collections import Counter

from gold import GOLD
from policy import NORMALIZERS, SCORED_FIELDS, SET_FIELDS, validate
from predictions import COST_PER_RECORD, SYSTEMS

Counts = tuple[int, int, int]  # (tp, fp, fn)


def as_set(field: str, value) -> frozenset[str]:
    """Normalize a field value into a set of comparison forms.

    Given. Note that it drops values that normalize to "", so a whitespace-only
    actor name is an absent actor rather than an empty-string actor.
    """
    if value is None:
        return frozenset()
    items = value if field in SET_FIELDS else [value]
    return frozenset(n for n in (NORMALIZERS[field](i) for i in items) if n)


def prf(tp: int, fp: int, fn: int, empty_precision: float = 0.0) -> tuple:
    """Precision, recall, F1, each rounded to 4 places. Given.

    `empty_precision` is the value returned when nothing was predicted, which is
    undefined (0/0). Micro passes 0.0, macro passes 1.0. Read the module
    docstring before deciding that is a bug.
    """
    p = tp / (tp + fp) if (tp + fp) else empty_precision
    r = tp / (tp + fn) if (tp + fn) else 0.0
    f = 2 * p * r / (p + r) if (p + r) else 0.0
    return (round(p, 4), round(r, 4), round(f, 4))


# --------------------------------------------------------------------------
# TASK 2 -- counts for one field of one record.
# --------------------------------------------------------------------------


def counts_for_field(field: str, gold_value, pred_value) -> Counts:
    """Return (tp, fp, fn) for a single record's single field.

    Build both sides with as_set(), then:
      tp = items in both, fp = predicted but not gold, fn = gold but not
      predicted.

    Check your result against these four cases before moving on:
      gold {A,B}, pred {A,C}  -> (1, 1, 1)
      gold {A},   pred {}     -> (0, 0, 1)   an omission
      gold {},    pred {A}    -> (0, 1, 0)   an invention
      gold {},    pred {}     -> (0, 0, 0)   correctly silent, and invisible
    """
    raise NotImplementedError("TASK 2")


# --------------------------------------------------------------------------
# TASK 3 -- the two averages.
# --------------------------------------------------------------------------


def micro_average(counts: list[Counts]) -> tuple:
    """Pool the counts across records, then compute prf once.

    Use empty_precision=0.0. This weights every EXTRACTED ITEM equally, so a
    document containing seven actors contributes seven times as much as one
    containing a single actor.
    """
    raise NotImplementedError("TASK 3a")


def macro_average(counts: list[Counts]) -> tuple:
    """Compute prf per record, then average each of the three numbers.

    Use empty_precision=1.0. Include only records where the gold field is
    non-empty (tp + fn > 0); a record with nothing to find has undefined recall
    and averaging it in would be inventing data. Return (0.0, 0.0, 0.0) if no
    record qualifies.

    This weights every DOCUMENT equally. Compare it to micro on the `actors`
    field of the rules baseline and account for the gap before you continue --
    the gap has a single cause and you can name the record.
    """
    raise NotImplementedError("TASK 3b")


# --------------------------------------------------------------------------
# TASK 4 -- the outcome split. Where did the error come from?
# --------------------------------------------------------------------------


def outcome(field: str, gold_value, pred_value) -> str:
    """Classify one record-field as "correct", "empty", or "wrong".

      "correct" -- the two sets are equal, INCLUDING both being empty
      "empty"   -- the prediction set is empty and the gold set is not
      "wrong"   -- anything else: a substitution, an invention, or a partial
                   set match

    Note the coarseness you are accepting: a partially-recovered list of seven
    actors lands in "wrong" alongside a confidently invented one. The split
    tells you about whole fields; the (tp, fp, fn) counts are what separate
    invention from omission. You will need both in step 5.
    """
    raise NotImplementedError("TASK 4")


# --------------------------------------------------------------------------
# TASK 5 -- would a human accept the record?
# --------------------------------------------------------------------------


def record_accepted(gold_record: dict, pred_record: dict) -> bool:
    """True when every scored field is exactly right.

    Every field in SCORED_FIELDS must have fp == 0 and fn == 0. Validation is
    checked by the caller; assume the record is valid here.

    Predict before implementing: given four fields at roughly 0.9 F1 each, what
    fraction of records do you expect to pass?
    """
    raise NotImplementedError("TASK 5")


# --------------------------------------------------------------------------
# Given: assembly and reporting.
# --------------------------------------------------------------------------


def score(system: str) -> dict:
    predictions = SYSTEMS[system]
    per_field: dict[str, list[Counts]] = {f: [] for f in SCORED_FIELDS}
    outcomes: dict[str, Counter] = {f: Counter() for f in SCORED_FIELDS}
    invalid_ids: list[str] = []
    accepted = 0

    for gold_record in GOLD:
        pred_record = predictions[gold_record["id"]]
        if validate(pred_record):
            invalid_ids.append(gold_record["id"])
            continue
        for field in SCORED_FIELDS:
            per_field[field].append(
                counts_for_field(field, gold_record.get(field), pred_record.get(field))
            )
            outcomes[field][
                outcome(field, gold_record.get(field), pred_record.get(field))
            ] += 1
        if record_accepted(gold_record, pred_record):
            accepted += 1

    n = len(GOLD)
    total_cost = COST_PER_RECORD[system] * n
    return {
        "system": system,
        "n_records": n,
        "n_scored": n - len(invalid_ids),
        "invalid_ids": invalid_ids,
        "schema_validity_rate": round((n - len(invalid_ids)) / n, 4),
        "fields": {
            field: {
                "micro": micro_average(per_field[field]),
                "macro": macro_average(per_field[field]),
                "counts": tuple(sum(c[i] for c in per_field[field]) for i in range(3)),
                "outcomes": dict(outcomes[field]),
            }
            for field in SCORED_FIELDS
        },
        "record_accuracy": round(accepted / n, 4),
        "accepted": accepted,
        # The denominator is accepted records, not calls. A system that is cheap
        # per call and accepted by nobody has an undefined cost per unit of
        # value, which is the honest answer.
        "cost_per_accepted": round(total_cost / accepted, 6) if accepted else None,
    }


def report(system: str) -> str:
    r = score(system)
    lines = [
        f"{r['system']}: valid {r['n_scored']}/{r['n_records']} "
        f"({r['schema_validity_rate']:.0%})"
        + (f"  invalid: {', '.join(r['invalid_ids'])}" if r["invalid_ids"] else ""),
        f"{'field':<12}{'microP':>8}{'microR':>8}{'microF1':>9}"
        f"{'macroF1':>9}{'tp/fp/fn':>12}{'ok/empty/wrong':>16}",
    ]
    for field, v in r["fields"].items():
        o = v["outcomes"]
        counts = "/".join(str(x) for x in v["counts"])
        split = f"{o.get('correct', 0)}/{o.get('empty', 0)}/{o.get('wrong', 0)}"
        lines.append(
            f"{field:<12}{v['micro'][0]:>8.4f}{v['micro'][1]:>8.4f}"
            f"{v['micro'][2]:>9.4f}{v['macro'][2]:>9.4f}"
            f"{counts:>12}{split:>16}"
        )
    cost = r["cost_per_accepted"]
    lines.append(
        f"record accuracy {r['record_accuracy']:.4f} "
        f"({r['accepted']}/{r['n_records']})   cost per accepted record: "
        + (f"${cost:.4f}" if cost is not None else "n/a -- nothing was accepted")
    )
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # boilerplate
    for name in SYSTEMS:
        print(report(name))
        print()
