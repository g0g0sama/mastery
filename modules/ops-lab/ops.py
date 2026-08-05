"""ops-lab -- the shared fixture for the seven Layer 9 modules.

What is real here and what is not, stated once so no table below has to carry
the caveat:

  real       the filesystem, zip containers, hashing, subprocess environments,
             JSON serialization and its byte counts, exception frames, and
             every arithmetic result computed from those.
  real       the records: every one came out of ../model-interface-lab's fake
             provider, whose own failure distribution is declared rather than
             discovered. Token counts and prices come from that provider.
  declared   request volumes, wall-clock latencies, injected failure rates, the
             release timeline, and the day the provider silently reskills.
  derived    costs, detection delays, series counts, replay fractions, and
             every delta the labs print.

No network, no container runtime, no key, no provider. The one failure this
fixture can cause is a reader mistaking a declared volume for a measured one.
"""
from __future__ import annotations

import hashlib
import json
import math
import random
import statistics
import sys
from dataclasses import dataclass, replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "model-interface-lab"))

from provider import (MODELS, Model, Provider, ProviderError,  # noqa: E402
                      PROMPT_VARIANTS, RateLimitError, BadRequestError,
                      ContentFilterError, OverloadedError, APITimeoutError,
                      repair)
from task import DOCUMENTS, record_correct, validate            # noqa: E402

DOC_IDS = list(DOCUMENTS)
GOLD = {d: DOCUMENTS[d][1] for d in DOC_IDS}
SLICE = {d: GOLD[d]["event_type"] for d in DOC_IDS}


# --------------------------------------------------------------------------- #
# Printing. Same helpers as ../serving-lab/hardware.py, kept local so the two
# fixtures do not import each other for four lines of formatting.
# --------------------------------------------------------------------------- #

def rule(title: str) -> None:
    print(f"=== {title} ===")


def row(*cells, widths=None) -> None:
    widths = widths or [22] + [12] * (len(cells) - 1)
    print("".join(str(c).ljust(w) for c, w in zip(cells, widths)))


def usd(x: float) -> str:
    return f"${x:,.2f}"


def bootstrap_ci(samples, statistic=statistics.mean, resamples: int = 2000,
                 seed: int = 11, level: float = 0.95):
    """Percentile bootstrap. Same helper as extraction-eval-sets/lab/interval.py
    and serving-lab/hardware.py -- a monitoring threshold is an estimate like
    any other, and the third fixture to need it is not a coincidence."""
    rng = random.Random(seed)
    n = len(samples)
    stats = []
    for _ in range(resamples):
        stats.append(statistic([samples[rng.randrange(n)] for _ in range(n)]))
    stats.sort()
    return (stats[int((1 - level) / 2 * resamples)],
            stats[int((1 + level) / 2 * resamples) - 1])


# --------------------------------------------------------------------------- #
# What a release is. Every field here is something that can change the output
# of the service without any other field changing -- which is the whole reason
# the registry module exists.
# --------------------------------------------------------------------------- #

@dataclass(frozen=True)
class Release:
    tag: str
    day: int                      # first day it sees any traffic
    code_version: str
    model: str = "mid-1"
    prompt_version: str = "v1"
    temperature: float = 0.0
    constrained: bool = False
    max_tokens: int = 256
    schema_version: str = "1.0"
    index_version: str = "idx-2026-02-01"
    canary_days: int = 0          # days of partial rollout before full traffic
    canary_share: float = 0.10

    def share_on(self, day: int) -> float:
        if day < self.day:
            return 0.0
        if day < self.day + self.canary_days:
            return self.canary_share
        return 1.0

    # The two stamps the registry module compares.
    def name_stamp(self) -> dict:
        """What almost every service stores: names, not versions."""
        return {"model": self.model, "prompt": self.prompt_version}

    def full_stamp(self) -> dict:
        return {"model": self.model, "prompt": self.prompt_version,
                "prompt_sha": self.prompt_sha(), "params_sha": self.params_sha(),
                "code": self.code_version, "schema": self.schema_version,
                "index": self.index_version}

    def prompt_text(self) -> str:
        return PROMPT_VARIANTS[self.prompt_version]["text"]

    def prompt_sha(self) -> str:
        return sha(self.prompt_text())[:8]

    def params_sha(self) -> str:
        return sha(json.dumps({"temperature": self.temperature,
                               "constrained": self.constrained,
                               "max_tokens": self.max_tokens},
                              sort_keys=True))[:8]


def sha(text: str | bytes) -> str:
    data = text.encode() if isinstance(text, str) else text
    return hashlib.sha256(data).hexdigest()


# The 60-day timeline every lab downstream of the build shares.
#
# Three things happen on it and only two of them are deploys. r2 rolls out as a
# canary, which is what makes "find the affected records by date" imprecise;
# r3 turns on constrained decoding; and on day 45 nothing is deployed at all --
# the provider reskills the `mid-1` alias underneath a service that pinned a
# name. That day is the drift module's whole subject and the registry module's
# argument for a behavioural hash.
RELEASES = [
    Release("r1", day=0,  code_version="a11f3c9"),
    Release("r2", day=12, code_version="b27e004", prompt_version="v2",
            canary_days=4),
    Release("r3", day=30, code_version="c8d1a55", prompt_version="v2",
            constrained=True, schema_version="1.1"),
    Release("r4", day=52, code_version="d90bb12", prompt_version="v2",
            schema_version="1.1"),          # rollback of r3's constrained flag
]

SILENT_RESKILL_DAY = 45
RESKILLED = Model("mid-1", MODELS["mid-1"].price_in, MODELS["mid-1"].price_out,
                  MODELS["mid-1"].latency_ms, skill=0.66)   # was 0.80


def releases_on(day: int):
    """Which releases are serving traffic on this day, and in what proportion.

    Returns [(release, share)] normalized. Newest release wins its share; the
    previous one keeps the remainder. This is a rollout, not a load balancer.
    """
    live = [r for r in RELEASES if r.day <= day]
    if not live:
        return []
    newest = live[-1]
    share = newest.share_on(day)
    if share >= 1.0 or len(live) == 1:
        return [(newest, 1.0)]
    return [(newest, share), (live[-2], 1.0 - share)]


def release_for(day: int, seq: int):
    """Pick the release serving one particular request. Deterministic in `seq`
    so that any lab can reconstruct the routing without storing it -- which is
    exactly the assumption the registry module takes apart."""
    mix = releases_on(day)
    x = ((seq * 2654435761) % 1000) / 1000.0
    acc = 0.0
    for rel, share in mix:
        acc += share
        if x < acc:
            return rel
    return mix[-1][0]


# --------------------------------------------------------------------------- #
# The service. One request: retrieve -> extract -> validate -> store.
# --------------------------------------------------------------------------- #

@dataclass
class Failures:
    """Declared. Retryable and terminal rates per model call, plus one code bug
    that only fires on a slice -- the shape a real incident has."""
    rate_limit: float = 0.030
    overloaded: float = 0.010
    timeout: float = 0.006
    bad_request: float = 0.004
    content_filter: float = 0.003
    bug_slice: str | None = None       # event_type whose handler raises
    bug_from_day: int = 10**9


DEFAULT_FAILURES = Failures()


class CodeBug(Exception):
    """Not a provider error. Counting it as one is the mistake the DLQ module
    measures: it is not transient, and no amount of retrying fixes it."""


def _provider_for(rel: Release, day: int) -> Provider:
    p = Provider(rel.model)
    if day >= SILENT_RESKILL_DAY:
        p.model = RESKILLED           # same name, same price, different model
    return p


def process(doc_id: str, rel: Release, *, seq: int = 0, day: int = 0,
            failures: Failures = DEFAULT_FAILURES, retries: int = 2,
            capture_input: bool = True) -> dict:
    """One request, start to finish. Returns the event a real service would
    emit, with the spans it would emit them under.

    Wall-clock numbers are declared (derived from the provider's declared
    latency plus seeded jitter); token counts, costs, parse outcomes and
    correctness are real consequences of the fake provider's output.
    """
    rng = random.Random(f"{rel.tag}|{doc_id}|{seq}|{day}")
    request_id = f"req-{day:03d}-{seq:05d}"
    provider = _provider_for(rel, day)
    spans, attempts, cost, usage = [], 0, 0.0, {"input": 0, "output": 0}

    t = 0.0
    ms = 6.0 + rng.random() * 4
    spans.append({"name": "retrieve", "ms": round(ms, 2), "start": round(t, 2),
                  "attrs": {"index": rel.index_version, "k": 3}})
    t += ms

    text, _gold = DOCUMENTS[doc_id]
    outcome, error_class, response = None, None, None
    for attempt in range(retries + 1):
        attempts += 1
        roll = rng.random()
        thrown = None
        acc = failures.rate_limit
        if roll < acc:
            thrown = RateLimitError()
        elif roll < (acc := acc + failures.overloaded):
            thrown = OverloadedError("overloaded")
        elif roll < (acc := acc + failures.timeout):
            thrown = APITimeoutError("request timed out")
        elif roll < (acc := acc + failures.bad_request):
            thrown = BadRequestError("context length exceeded")
        elif roll < acc + failures.content_filter:
            thrown = ContentFilterError("input flagged")

        lat = provider.model.latency_ms * (0.6 + rng.random() * 0.9)
        if thrown is not None:
            # A failed call still consumed input tokens. That is the cost
            # module's second section and it is not a modelling choice.
            in_tokens = len(rel.prompt_text()) // 4 + len(text)
            usage["input"] += in_tokens
            cost += in_tokens * provider.model.price_in / 1000
            spans.append({"name": "extract", "ms": round(lat, 2),
                          "start": round(t, 2),
                          "attrs": {"model": rel.model, "attempt": attempt,
                                    "error": type(thrown).__name__,
                                    "transient": thrown.transient}})
            t += lat
            if not thrown.transient or attempt == retries:
                outcome, error_class = "error", type(thrown).__name__
                break
            backoff = (2 ** attempt) * 120 * (0.5 + rng.random())
            spans.append({"name": "backoff", "ms": round(backoff, 2),
                          "start": round(t, 2), "attrs": {"attempt": attempt}})
            t += backoff
            continue

        response = provider.complete(doc_id, temperature=rel.temperature,
                                     constrained=rel.constrained,
                                     max_tokens=rel.max_tokens, attempt=seq,
                                     prompt_version=rel.prompt_version)
        usage["input"] += response.usage["input"]
        usage["output"] += response.usage["output"]
        cost += response.cost
        spans.append({"name": "extract", "ms": round(lat, 2),
                      "start": round(t, 2),
                      "attrs": {"model": rel.model, "attempt": attempt,
                                "in": response.usage["input"],
                                "out": response.usage["output"],
                                "stop": response.stop_reason}})
        t += lat
        outcome = "extracted"
        break

    record, violations = None, []
    if outcome == "extracted":
        parsed, _perr = response.parse()
        if parsed is None:
            parsed = _repaired(response.text)
        if parsed is None:
            outcome, error_class = "invalid", "parse"
        else:
            violations = validate(parsed)
            if violations:
                outcome, error_class = "invalid", violations[0]
            else:
                record, outcome = parsed, "stored"
        spans.append({"name": "validate", "ms": 0.4,
                      "start": round(t, 2),
                      "attrs": {"violations": len(violations),
                                # codes, not messages: a code is countable and
                                # a message is only readable. Same argument as
                                # ../error-taxonomy.md, one layer down.
                                "codes": violations[:3],
                                "schema": rel.schema_version}})
        t += 0.4

    if (outcome == "stored" and failures.bug_slice
            and SLICE[doc_id] == failures.bug_slice and day >= failures.bug_from_day):
        outcome, error_class, record = "error", "CodeBug", None

    if outcome == "stored":
        ms = 3.0 + rng.random() * 3
        spans.append({"name": "store", "ms": round(ms, 2), "start": round(t, 2),
                      "attrs": {"table": "events"}})
        t += ms

    return {
        "request_id": request_id, "day": day, "seq": seq, "doc_id": doc_id,
        "slice": SLICE[doc_id], "release": rel.tag, "outcome": outcome,
        "error_class": error_class, "attempts": attempts,
        "usage": usage, "cost": round(cost, 8), "latency_ms": round(t, 2),
        "spans": spans, "record": record,
        "correct": bool(record) and record_correct(record, GOLD[doc_id]),
        # What replay needs, and what a service that logs exceptions does not
        # keep. The DLQ module removes this line and measures the difference.
        "input_snapshot": (text if capture_input else None),
        "stamp": rel.full_stamp(),
    }


def _repaired(text: str):
    """The packaging-only repair from ../model-interface-lab. Returns the
    parsed object or None -- it never edits a value, so a record that survives
    it is the model's record and not the repair pass's."""
    try:
        obj = json.loads(repair(text))
        return obj if isinstance(obj, dict) else None
    except Exception:
        return None


def traffic(day: int, n: int, *, failures: Failures = DEFAULT_FAILURES,
            seed: int = 0, retries: int = 2):
    """One day of requests. Volume is declared; everything the requests do is
    a consequence of the provider."""
    rng = random.Random(f"traffic|{day}|{seed}")
    out = []
    for seq in range(n):
        doc_id = DOC_IDS[rng.randrange(len(DOC_IDS))]
        rel = release_for(day, seq)
        out.append(process(doc_id, rel, seq=seq, day=day, failures=failures,
                           retries=retries))
    return out


# --------------------------------------------------------------------------- #
# Small shared statistics the monitoring labs both need.
# --------------------------------------------------------------------------- #

def ewma(series, alpha: float = 0.3):
    out, s = [], series[0]
    for x in series:
        s = alpha * x + (1 - alpha) * s
        out.append(s)
    return out


def cusum(series, target: float, k: float, h: float):
    """One-sided downward CUSUM. Returns (index of alarm or None, statistic).

    The point of a CUSUM in a monitoring module: a threshold looks at today,
    a CUSUM accumulates evidence, and the difference between them is the whole
    detection-delay table.
    """
    s, stats = 0.0, []
    alarm = None
    for i, x in enumerate(series):
        s = max(0.0, s + (target - x - k))
        stats.append(s)
        if alarm is None and s > h:
            alarm = i
    return alarm, stats


def psi(expected, actual, bins=10):
    """Population stability index over a numeric feature. The industry's
    default input-drift detector; the drift module measures its precision."""
    lo, hi = min(expected + actual), max(expected + actual)
    if hi == lo:
        return 0.0
    edges = [lo + (hi - lo) * i / bins for i in range(bins + 1)]

    def hist(xs):
        counts = [0] * bins
        for x in xs:
            idx = min(bins - 1, int((x - lo) / (hi - lo) * bins))
            counts[idx] += 1
        return [max(c / len(xs), 1e-4) for c in counts]

    e, a = hist(expected), hist(actual)
    return sum((a[i] - e[i]) * math.log(a[i] / e[i]) for i in range(bins))
