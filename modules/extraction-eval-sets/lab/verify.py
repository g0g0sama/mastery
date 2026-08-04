"""Verification for the eval-set lab. Run: python verify.py

Checks run in the order the tasks are meant to be done. A later check failing
with NotImplementedError just means you have not got there yet.

The expected numbers were computed from a reference implementation of the same
policy. If your scorer disagrees, the useful question is not "which is right"
but "which convention did I choose differently" -- and then whether you wrote it
down.
"""

from __future__ import annotations

import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")  # boilerplate

import policy  # noqa: E402
import scoring  # noqa: E402

results: list[tuple[str, bool, str]] = []


def check(name: str):
    def run(fn):
        try:
            fn()
        except NotImplementedError as exc:
            results.append((name, False, f"not implemented ({exc})"))
        except AssertionError as exc:
            results.append((name, False, str(exc) or "assertion failed"))
        except Exception as exc:  # noqa: BLE001 -- report, do not crash the run
            results.append((name, False, f"{type(exc).__name__}: {exc}"))
        else:
            results.append((name, True, ""))
        return fn

    return run


# --------------------------------------------------------------------------


@check("1a normalize_actor")
def _actor():
    n = policy.normalize_actor
    assert n(None) == "", "None must normalize to the empty string"
    assert n("中国石化 ") == "中国石化", "trailing whitespace must be stripped"
    assert n("宁德时代（ＣＡＴＬ）") == "宁德时代", (
        "NFKC folds the full-width parentheses to ASCII, then the parenthetical "
        "is dropped -- check you do NFKC before the regex"
    )
    assert n("BMW  Group") == "bmw group", "collapse whitespace, then casefold"
    assert n("华为技术有限公司") == "华为技术有限公司", (
        "legal-form suffixes must NOT be stripped -- policy decision 2"
    )
    assert n("华为") != n("华为技术有限公司"), "these are deliberately not a match"


@check("1b normalize_location")
def _location():
    n = policy.normalize_location
    assert n(None) == ""
    assert n("深圳") == "深圳"
    assert n("深圳市") == "深圳", "drop the administrative suffix"
    assert n("福建省宁德市") == "宁德", "keep the most specific component"
    assert n("北京市") == "北京"
    assert n("广州市天河区") == "天河", "most specific means the last component"
    assert n("华盛顿") == "华盛顿", "a name with no suffix is already specific"
    assert n("安徽省") == "安徽"
    assert n("安徽省") != n("合肥"), "a province is not its capital"


@check("2 counts_for_field")
def _counts():
    c = scoring.counts_for_field
    assert c("actors", ["A", "B"], ["A", "C"]) == (1, 1, 1)
    assert c("actors", ["A"], []) == (0, 0, 1), "an omission is fn only"
    assert c("actors", [], ["A"]) == (0, 1, 0), "an invention is fp only"
    assert c("actors", [], []) == (0, 0, 0), "correct silence scores nothing"
    assert c("event_type", "sanction", "sanction") == (1, 0, 0)
    assert c("event_type", "sanction", "investment") == (0, 1, 1), (
        "a substitution is both a false positive and a false negative"
    )
    assert c("event_type", "sanction", None) == (0, 0, 1)
    assert c("time", None, "2026-04-05") == (0, 1, 0), (
        "gold recorded no date; a predicted date is an invention"
    )
    assert c("time", "2026-03-14", "2026-03-14T00:00:00") == (0, 1, 1), (
        "policy decision 4: a datetime is not a date"
    )
    assert c("location", "深圳市", "深圳") == (1, 0, 0), (
        "normalization must be applied to both sides"
    )


@check("3a micro_average")
def _micro():
    m = scoring.micro_average
    assert m([(1, 1, 1), (3, 0, 0)]) == (0.8, 0.8, 0.8)
    assert m([(0, 0, 2)]) == (0.0, 0.0, 0.0), (
        "no predictions at all: micro precision is 0.0, not 1.0"
    )
    assert m([]) == (0.0, 0.0, 0.0)


@check("3b macro_average")
def _macro():
    m = scoring.macro_average
    # Two records: one perfect, one that predicted nothing.
    assert m([(2, 0, 0), (0, 0, 2)]) == (1.0, 0.5, 0.5), (
        "the silent record contributes precision 1.0 -- that is the convention "
        "that flatters abstention"
    )
    # A record with an empty gold field is excluded, not averaged in as zero.
    assert m([(2, 0, 0), (0, 1, 0)]) == (1.0, 1.0, 1.0), (
        "the second record has no gold items, so it is not part of the average"
    )
    assert m([]) == (0.0, 0.0, 0.0)
    assert m([(0, 0, 0)]) == (0.0, 0.0, 0.0)


@check("4 outcome")
def _outcome():
    o = scoring.outcome
    assert o("event_type", "sanction", "sanction") == "correct"
    assert o("time", None, None) == "correct", "both empty is agreement"
    assert o("event_type", "sanction", None) == "empty"
    assert o("event_type", "sanction", "investment") == "wrong"
    assert o("actors", ["A", "B"], ["A"]) == "wrong", (
        "a partial set is not 'empty' -- this coarseness is on purpose, and it "
        "is why you still need the tp/fp/fn counts"
    )
    assert o("time", None, "2026-04-05") == "wrong"


@check("5 record_accepted")
def _accepted():
    from gold import GOLD_BY_ID
    from predictions import MODEL_A, MODEL_B

    assert scoring.record_accepted(GOLD_BY_ID["R04"], MODEL_A["R04"]) is True
    assert scoring.record_accepted(GOLD_BY_ID["R12"], MODEL_A["R12"]) is False, (
        "R12: event_type is wrong, so the record is not acceptable"
    )
    assert scoring.record_accepted(GOLD_BY_ID["R09"], MODEL_B["R09"]) is True, (
        "R09: both sides correctly hold no date -- agreement, not a gap"
    )
    assert scoring.record_accepted(GOLD_BY_ID["R06"], MODEL_B["R06"]) is False, (
        "R06: location is empty"
    )


# --------------------------------------------------------------------------
# 6 -- the full report. These are the numbers the rest of the lab discusses.
# --------------------------------------------------------------------------

EXPECTED = {
    "rules": {
        "n_scored": 10,
        "invalid_ids": ["R06", "R08"],
        "schema_validity_rate": 0.8333,
        "record_accuracy": 0.0,
        "accepted": 0,
        "cost_per_accepted": None,
        "fields": {
            "actors": {
                "micro": (0.9091, 0.5263, 0.6667),
                "macro": (0.95, 0.6786, 0.7111),
                "counts": (10, 1, 9),
                "outcomes": {"correct": 4, "wrong": 5, "empty": 1},
            },
            "event_type": {
                "micro": (0.0, 0.0, 0.0),
                "macro": (1.0, 0.0, 0.0),
                "counts": (0, 0, 10),
                "outcomes": {"empty": 10},
            },
            "time": {
                "micro": (0.9, 1.0, 0.9474),
                "macro": (1.0, 1.0, 1.0),
                "counts": (9, 1, 0),
                "outcomes": {"correct": 9, "wrong": 1},
            },
            "location": {
                "micro": (1.0, 1.0, 1.0),
                "macro": (1.0, 1.0, 1.0),
                "counts": (10, 0, 0),
                "outcomes": {"correct": 10},
            },
        },
    },
    "model_a": {
        "n_scored": 12,
        "invalid_ids": [],
        "schema_validity_rate": 1.0,
        "record_accuracy": 0.5,
        "accepted": 6,
        "cost_per_accepted": 0.0084,
        "fields": {
            "actors": {
                "micro": (0.8696, 0.8696, 0.8696),
                "macro": (0.8214, 0.8214, 0.8214),
                "counts": (20, 3, 3),
                "outcomes": {"wrong": 3, "correct": 9},
            },
            "event_type": {
                "micro": (0.9167, 0.9167, 0.9167),
                "macro": (0.9167, 0.9167, 0.9167),
                "counts": (11, 1, 1),
                "outcomes": {"correct": 11, "wrong": 1},
            },
            "time": {
                "micro": (0.8333, 0.9091, 0.8696),
                "macro": (0.9091, 0.9091, 0.9091),
                "counts": (10, 2, 1),
                "outcomes": {"correct": 10, "wrong": 2},
            },
            "location": {
                "micro": (1.0, 1.0, 1.0),
                "macro": (1.0, 1.0, 1.0),
                "counts": (12, 0, 0),
                "outcomes": {"correct": 12},
            },
        },
    },
    "model_b": {
        "n_scored": 12,
        "invalid_ids": [],
        "schema_validity_rate": 1.0,
        "record_accuracy": 0.5,
        "accepted": 6,
        "cost_per_accepted": 0.0076,
        "fields": {
            "actors": {
                "micro": (1.0, 0.7826, 0.878),
                "macro": (1.0, 0.8393, 0.8662),
                "counts": (18, 0, 5),
                "outcomes": {"correct": 9, "wrong": 2, "empty": 1},
            },
            "event_type": {
                "micro": (1.0, 0.9167, 0.9565),
                "macro": (1.0, 0.9167, 0.9167),
                "counts": (11, 0, 1),
                "outcomes": {"correct": 11, "empty": 1},
            },
            "time": {
                "micro": (1.0, 0.9091, 0.9524),
                "macro": (1.0, 0.9091, 0.9091),
                "counts": (10, 0, 1),
                "outcomes": {"correct": 11, "empty": 1},
            },
            "location": {
                "micro": (1.0, 0.9167, 0.9565),
                "macro": (1.0, 0.9167, 0.9167),
                "counts": (11, 0, 1),
                "outcomes": {"correct": 11, "empty": 1},
            },
        },
    },
}


def _compare(system: str):
    got = scoring.score(system)
    want = EXPECTED[system]
    for key in ("n_scored", "invalid_ids", "schema_validity_rate",
                "record_accuracy", "accepted", "cost_per_accepted"):
        assert got[key] == want[key], f"{system}.{key}: got {got[key]}, want {want[key]}"
    for field, expected_field in want["fields"].items():
        actual = got["fields"][field]
        for key, expected_value in expected_field.items():
            actual_value = actual[key]
            if isinstance(expected_value, tuple):
                actual_value = tuple(actual_value)
            assert actual_value == expected_value, (
                f"{system}.{field}.{key}: got {actual_value}, want {expected_value}"
            )


@check("6a full report -- rules baseline")
def _r():
    _compare("rules")


@check("6b full report -- model_a")
def _a():
    _compare("model_a")


@check("6c full report -- model_b")
def _b():
    _compare("model_b")


# --------------------------------------------------------------------------

if __name__ == "__main__":
    passed = sum(1 for _, ok, _ in results if ok)
    for name, ok, message in results:
        print(f"  {'PASS' if ok else 'FAIL'}  {name}" + (f"  --  {message}" if message else ""))
    print(f"\n{passed}/{len(results)} checks passed")
    if passed == len(results):
        print("\nAll green. Now run:  python scoring.py   and read the three reports")
        print("side by side before you touch break_it.py. Write down which system")
        print("you would ship, and on which number.")
    sys.exit(0 if passed == len(results) else 1)
