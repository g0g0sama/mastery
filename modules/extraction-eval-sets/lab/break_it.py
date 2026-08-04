"""Three seeded failures. Predict the symptom, then run.

    python break_it.py        list the three, with the prediction to make
    python break_it.py 1      run break 1 and print before/after

Each break changes exactly one thing and leaves everything else alone. Two of
the three change no system code at all -- they change the instrument, or they
change a detail that the schema is structurally unable to see.

Requires verify.py to be green.
"""

from __future__ import annotations

import copy
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # boilerplate

import policy
import scoring
from predictions import SYSTEMS

WATCH = ("actors", "event_type", "time", "location")


def snapshot() -> dict:
    return {name: scoring.score(name) for name in SYSTEMS}


def diff(before: dict, after: dict, systems=tuple(SYSTEMS)) -> None:
    header = f"{'system':<9}{'field':<12}{'microF1 before':>16}{'after':>9}{'delta':>9}"
    print(header)
    print("-" * len(header))
    for name in systems:
        for field in WATCH:
            b = before[name]["fields"][field]["micro"][2]
            a = after[name]["fields"][field]["micro"][2]
            mark = "   <-- moved" if abs(a - b) > 1e-9 else ""
            print(f"{name:<9}{field:<12}{b:>16.4f}{a:>9.4f}{a - b:>+9.4f}{mark}")
        b, a = before[name], after[name]
        print(
            f"{name:<9}{'[validity]':<12}{b['schema_validity_rate']:>16.4f}"
            f"{a['schema_validity_rate']:>9.4f}"
            f"{a['schema_validity_rate'] - b['schema_validity_rate']:>+9.4f}"
        )
        print(
            f"{name:<9}{'[rec acc]':<12}{b['record_accuracy']:>16.4f}"
            f"{a['record_accuracy']:>9.4f}"
            f"{a['record_accuracy'] - b['record_accuracy']:>+9.4f}"
        )
        print()


PROMPTS = {
    "1": (
        "BREAK 1 -- the instrument moves, the system does not.\n"
        "  Every normalizer is replaced by str.strip(). No prediction changes,\n"
        "  no gold label changes, no extractor code changes.\n"
        "  Predict: which field moves most, for which systems, and -- the real\n"
        "  question -- does the RANKING between model_a and model_b on that\n"
        "  field survive?"
    ),
    "2": (
        "BREAK 2 -- a locale bug in the extractor.\n"
        "  Every predicted date has its day and month transposed whenever both\n"
        "  are <= 12, exactly as a %d/%m vs %m/%d confusion would produce.\n"
        "  Predict: does schema_validity_rate move? Which fields move? What\n"
        "  happens to record accuracy, and is the drop bigger or smaller than\n"
        "  the drop in the time field alone?"
    ),
    "3": (
        "BREAK 3 -- a granularity change nobody announced.\n"
        "  model_b starts emitting '2026-03-14T00:00:00' where it used to emit\n"
        "  '2026-03-14'. The storage schema accepts ISO datetimes.\n"
        "  Predict: model_b's time micro F1, and its schema_validity_rate."
    ),
}


def break_1() -> None:
    before = snapshot()
    identity = lambda raw: "" if raw is None else str(raw).strip()  # noqa: E731
    saved = dict(policy.NORMALIZERS)
    policy.NORMALIZERS.update({field: identity for field in policy.NORMALIZERS})
    try:
        after = snapshot()
    finally:
        policy.NORMALIZERS.update(saved)
    diff(before, after)
    print("The rules baseline did not move at all: its outputs already happen to")
    print("match the gold surface form, so it never exercised the normalizer.")
    print("That is what makes this class of change so easy to ship -- the")
    print("baseline you sanity-check against is the one system it cannot break.")


def break_2() -> None:
    before = snapshot()
    original = copy.deepcopy(SYSTEMS)

    def transpose(value):
        if not isinstance(value, str) or len(value) != 10:
            return value
        year, month, day = value.split("-")
        return f"{year}-{day}-{month}" if int(day) <= 12 else value

    try:
        for system in SYSTEMS.values():
            for record in system.values():
                record["time"] = transpose(record["time"])
        after = snapshot()
    finally:
        for name, system in original.items():
            SYSTEMS[name].update(copy.deepcopy(system))
    diff(before, after)
    print("Note which dates survived: only the ones where the day is above 12,")
    print("which here is about half of them. A bug that corrupts one field and")
    print("no others is exactly the shape that a whole-record accuracy number")
    print("reports as a general decline in quality -- record accuracy fell by")
    print("half for every system, and it cannot tell you which field to open.")


def break_3() -> None:
    before = snapshot()
    original = copy.deepcopy(SYSTEMS["model_b"])
    try:
        for record in SYSTEMS["model_b"].values():
            if record["time"]:
                record["time"] = record["time"] + "T00:00:00"
        after = snapshot()
    finally:
        SYSTEMS["model_b"].update(copy.deepcopy(original))
    diff(before, after, systems=("model_b",))
    print("A field at exactly 0.0000 while validity holds at 1.0000 is almost")
    print("never a system that got everything wrong. It is a match rule and a")
    print("producer that stopped agreeing on a representation. Check the policy")
    print("before you open the extractor.")
    print()
    print("Now decide, and write the decision down: should normalize_time accept")
    print("a datetime by truncating it? Whichever way you go, that is an edit to")
    print("policy.py's header, and every number computed before the edit was")
    print("computed under a different instrument.")


BREAKS = {"1": break_1, "2": break_2, "3": break_3}

if __name__ == "__main__":
    if len(sys.argv) < 2 or sys.argv[1] not in BREAKS:
        print(__doc__)
        for key in sorted(PROMPTS):
            print(PROMPTS[key])
            print()
        print("Write your predictions down, then run: python break_it.py 1")
        sys.exit(0)
    which = sys.argv[1]
    print(PROMPTS[which])
    print()
    BREAKS[which]()
