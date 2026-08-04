"""The labelling and matching policy.

This file is the measuring instrument. Everything in it is a decision that was
made by a person, could have been made differently, and changes the score
without changing the system being scored. That is why it lives in its own file,
under version control, next to the labels -- not inline in a scoring script.

Decisions recorded here, with reasons:

1. `event_type` is a CLOSED vocabulary (EVENT_TYPES below). A value outside it
   is a schema violation, not a wrong answer. Rationale: a closed set is
   scoreable today. The cost is that genuinely novel event types are recorded as
   violations, so the violation log is also the backlog for vocabulary v2.

2. `actors` match on NORMALIZED SURFACE FORM, not on linked entity. Full-width
   characters are folded, a trailing parenthetical is dropped, latin case is
   folded. Legal-form suffixes are NOT stripped: "华为" and "华为技术有限公司"
   do not match. Rationale: stripping "有限公司" merges legally distinct
   entities, and the honest fix is entity linking, which this cycle does not
   have. The cost is a systematically pessimistic actors recall -- the ceiling
   this policy imposes, measured, is the argument for building entity linking.

3. `location` matches at the MOST SPECIFIC administrative component. So
   "福建省宁德市", "宁德市" and "宁德" are the same location. Rationale: sources
   vary in how much of the administrative hierarchy they print, and the
   difference carries no information about the event. The cost is that a
   prediction of the wrong district in the right city scores the same as a
   prediction of the wrong country.

4. `time` compares as an ISO DATE, exactly. A datetime is not a date. Rationale:
   the gold set records only the granularity the source supplied, so accepting a
   datetime would silently accept an invented midnight. Note that the SCHEMA
   accepts datetimes and the POLICY does not -- see the note on validate().

5. `claims` and `source` are NOT SCORED. Rationale: `claims` is free text and
   needs a rubric grader, which is a later cycle; `source` is provenance and is
   checked by an assertion, not a metric. A field that is present in the schema
   and absent from the score is a gap that must be written down, because silence
   reads as "this field is fine".

Normalization is applied to BOTH sides at scoring time. Gold is stored raw. If
you normalize gold on the way in, you cannot re-score the set when the policy
changes, and the policy will change.
"""

from __future__ import annotations

import re
import unicodedata

EVENT_TYPES = frozenset(
    {
        "investment",
        "trade_dispute",
        "plant_opening",
        "leadership_change",
        "sanction",
        "production_halt",
    }
)

SCORED_FIELDS = ("actors", "event_type", "time", "location")
SET_FIELDS = frozenset({"actors"})

# Administrative suffixes used to find the most specific component of a place
# name. Deliberately short: every entry is a policy commitment.
ADMIN_SUFFIXES = "省市区县"

PARENTHETICAL = re.compile(r"\([^)]*\)")
DATE_ONLY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
# The schema is LOOSER than the policy: it accepts an ISO datetime.
SCHEMA_DATE = re.compile(r"^\d{4}-\d{2}-\d{2}([T ].+)?$")


# --------------------------------------------------------------------------
# TASK 1 -- normalizers. Both of these are stubs.
# --------------------------------------------------------------------------


def normalize_actor(raw: str | None) -> str:
    """Fold an actor name to its comparison form, per decision 2 above.

    Must, in this order:
      1. return "" for None
      2. apply unicodedata.normalize("NFKC", ...) -- this folds full-width
         latin and full-width parentheses to their ASCII forms, which is why
         step 3 can use an ASCII-only pattern
      3. delete any parenthetical (PARENTHETICAL is already ASCII-only)
      4. collapse runs of whitespace to a single space and strip the ends
      5. casefold

    Must NOT strip legal-form suffixes.
    """
    raise NotImplementedError("TASK 1a")


def normalize_location(raw: str | None) -> str:
    """Reduce a place name to its most specific component, per decision 3.

    "福建省宁德市" -> "宁德",  "深圳市" -> "深圳",  "深圳" -> "深圳"

    Suggested approach: NFKC, drop parentheticals, remove all whitespace, then
    walk the string splitting on every character in ADMIN_SUFFIXES and keep the
    last non-empty segment. A name with no suffix character is already the most
    specific component. Finish with casefold.
    """
    raise NotImplementedError("TASK 1b")


# --------------------------------------------------------------------------
# Given. Read them -- they encode decisions 1 and 4.
# --------------------------------------------------------------------------


def normalize_event_type(raw: str | None) -> str:
    if raw is None:
        return ""
    return unicodedata.normalize("NFKC", str(raw)).strip().casefold()


def normalize_time(raw: str | None) -> str:
    """Return the value unchanged, whatever it is.

    There is nothing to fold: a date is already canonical and anything that is
    not a bare date is, by decision 4, a different value. This function exists
    so that every field has a normalizer and the scorer needs no special cases.
    """
    if raw is None:
        return ""
    return unicodedata.normalize("NFKC", str(raw)).strip()


NORMALIZERS = {
    "actors": normalize_actor,
    "location": normalize_location,
    "event_type": normalize_event_type,
    "time": normalize_time,
}


def validate(record: dict) -> list[str]:
    """Structural violations only. Returns [] for a storable record.

    Note what this cannot see. `time` here accepts an ISO datetime, because the
    storage schema does; the policy in normalize_time rejects it. A record can
    therefore be 100% schema-valid and 0% correct on the same field. Any system
    that reports validity as though it were quality is exploiting that gap,
    usually without meaning to.
    """
    violations: list[str] = []

    actors = record.get("actors")
    if not isinstance(actors, list) or any(not isinstance(a, str) for a in actors):
        violations.append("actors must be a list of strings")

    event_type = record.get("event_type")
    if event_type is not None and event_type not in EVENT_TYPES:
        violations.append("event_type outside the closed vocabulary")

    time = record.get("time")
    if time is not None and not (isinstance(time, str) and SCHEMA_DATE.match(time)):
        violations.append("time must be ISO-8601")

    location = record.get("location")
    if location is not None and not isinstance(location, str):
        violations.append("location must be a string or null")

    confidence = record.get("confidence")
    if confidence is not None and not (
        isinstance(confidence, float) and 0.0 <= confidence <= 1.0
    ):
        violations.append("confidence must be a float in [0,1] or null")

    return violations
