"""Drift and quality degradation: the scheduled eval run that catches it.

Map row (Layer 9): "A scheduled eval run detecting a real regression."

Sixty days of one service. Three things happen and only one of them is a model
problem: on day 20 the input distribution shifts with no effect on quality, on
day 33 the traffic mix moves toward a slice the prompt is bad at, and on day 45
the provider reskills the alias. The eval set is frozen on day 0 and never
resampled, which is what makes section 4 possible.

Section 1 runs the same eval two ways -- a fixed set with fixed seeds, and a
fresh sample each day -- and measures what determinism is worth. Section 2 asks
what can be watched without labels. Section 3 measures the precision of an
input-drift alarm. Section 4 is the one that ends the module: the frozen holdout
stops representing the traffic, and its flat line means nothing.

Correctness, token counts and failure modes are real consequences of the fake
provider. Volumes, the mix schedule and the reskill day are declared.

Commit to the predictions before running.
"""
from __future__ import annotations

import random
import statistics

import ops

PREDICTIONS = {
    "A": "A daily eval on 50 records detects a 10-point regression within a "
         "day or two either way -- the harness details do not matter much.",
    "B": "Without labels there is nothing useful to watch, so quality "
         "monitoring has to wait for the labelled set.",
    "C": "Input drift monitoring catches quality regressions early.",
    "D": "If the score on the frozen holdout is flat, quality is fine.",
}

REL = ops.Release("d1", 0, "e3f0a12", prompt_version="v2")

# The eval harness retries transient provider errors instead of scoring them:
# a 429 is a fact about the provider's queue, not about the model's quality,
# and counting it makes the eval measure two things at once. Turning them off
# is what makes section 1's first row possible.
NO_FAILURES = ops.Failures(0.0, 0.0, 0.0, 0.0, 0.0)
DAYS = 60
EVAL_N = 50

# Declared mix schedule. Weights over the eight documents.
MIX_BASE = {"N01": 2, "N02": 2, "N03": 2, "N04": 2,
            "N05": 2, "N06": 2, "N07": 2, "N08": 2}
MIX_LONG = {"N01": 1, "N02": 4, "N03": 2, "N04": 1,
            "N05": 1, "N06": 1, "N07": 4, "N08": 4}      # longer documents
MIX_REG = {"N01": 1, "N02": 1, "N03": 9, "N04": 1,
           "N05": 1, "N06": 1, "N07": 1, "N08": 1}       # regulation-heavy
LONG_DAY, REG_DAY = 20, 33


def mix_on(day):
    if day >= REG_DAY:
        return MIX_REG
    if day >= LONG_DAY:
        return MIX_LONG
    return MIX_BASE


def sample_docs(mix, n, rng):
    pool = [d for d, w in mix.items() for _ in range(w)]
    return [pool[rng.randrange(len(pool))] for _ in range(n)]


def live_traffic(day, n=300):
    rng = random.Random(f"live|{day}")
    docs = sample_docs(mix_on(day), n, rng)
    return [ops.process(d, REL, seq=day * 100_000 + i, day=day)
            for i, d in enumerate(docs)]


# The set, frozen on day 0 from the day-0 mix, with its seeds.
FROZEN = [(d, 7_000_000 + i)
          for i, d in enumerate(sample_docs(MIX_BASE, EVAL_N, random.Random(1)))]


def run_frozen(day):
    return [ops.process(d, REL, seq=s, day=day, failures=NO_FAILURES)
            for d, s in FROZEN]


def run_fresh(day, rng):
    """The other harness: today's 50 records, sampled from today's traffic."""
    docs = sample_docs(mix_on(day), EVAL_N, rng)
    return [ops.process(d, REL, seq=day * 200_000 + i, day=day,
                        failures=NO_FAILURES)
            for i, d in enumerate(docs)]


def acc(evs):
    return sum(e["correct"] for e in evs) / len(evs)


# --------------------------------------------------------------------------- #
# 1. Two harnesses.
# --------------------------------------------------------------------------- #

def section_1_harness():
    ops.rule("1. The same eval, run two ways, for sixty days")
    rng = random.Random(4)
    frozen = [acc(run_frozen(d)) for d in range(DAYS)]
    fresh = [acc(run_fresh(d, rng)) for d in range(DAYS)]

    def noise(series, lo, hi):
        diffs = [abs(series[d] - series[d - 1]) for d in range(lo + 1, hi)]
        return statistics.mean(diffs), max(diffs)

    ops.row("harness", "mean |day-to-day change|", "worst quiet day",
            "baseline acc", widths=[34, 26, 18, 14])
    for name, series in (("frozen set, frozen seeds", frozen),
                         ("fresh sample each day", fresh)):
        m, w = noise(series, 0, LONG_DAY)
        ops.row(name, f"{m:.4f}", f"{w:.4f}",
                f"{statistics.mean(series[:LONG_DAY]):.3f}",
                widths=[34, 26, 18, 14])

    print("\nThe first row is exactly zero. A frozen set with frozen seeds")
    print("against a temperature-0 model is a FUNCTION, so two runs that")
    print("differ mean the system differed -- there is no noise floor to")
    print("clear and no statistics to do. The second row is what it costs to")
    print("resample: a day-to-day movement of several points, none of which")
    print("is a change in anything.\n")

    def detect(series, label):
        base = statistics.mean(series[:LONG_DAY])
        sd = statistics.pstdev(series[:LONG_DAY]) or 1e-9
        thresh = {d for d, x in enumerate(series) if x < base - 0.05}
        alarm, _ = ops.cusum(series, base, k=0.02, h=0.10)
        first_t = min((d for d in thresh if d >= ops.SILENT_RESKILL_DAY),
                      default=None)
        fa_t = len([d for d in thresh if d < ops.SILENT_RESKILL_DAY])
        ops.row(label, f"{base:.3f}", f"{sd:.4f}",
                "never" if first_t is None else f"day {first_t}",
                fa_t, "never" if alarm is None else f"day {alarm}",
                widths=[30, 10, 10, 12, 8, 12])
        return first_t, fa_t, alarm

    print()
    ops.row("harness", "baseline", "sd", "threshold", "FA", "CUSUM",
            widths=[30, 10, 10, 12, 8, 12])
    res_frozen = detect(frozen, "frozen set, frozen seeds")
    res_fresh = detect(fresh, "fresh sample each day")
    print(f"\n(the reskill is on day {ops.SILENT_RESKILL_DAY}; FA counts alarms "
          f"before it)")
    print(f"\nThe resampling harness alarms {res_fresh[1]} times before day "
          f"{ops.SILENT_RESKILL_DAY} and the frozen one never does. Most of")
    print(f"those are not false: the traffic mix moved toward a slice this")
    print(f"prompt is bad at on day {REG_DAY}, and the frozen set -- which by")
    print("definition does not resample -- cannot see it at all. Which is")
    print("section 4, and the reason the answer is not 'freeze everything'.")
    print("\nWhat determinism buys is not detection. It is that a difference")
    print("is exact: the frozen harness can name WHICH records changed and")
    print("diff their outputs, which turns a number into a fix. The resampled")
    print("harness has a score with an interval around it and nothing to")
    print("open. Same argument as ../eval-set-versioning.md: hold the set and")
    print("the seeds still, so that what moves is the system.")
    return frozen, fresh, res_frozen, res_fresh


# --------------------------------------------------------------------------- #
# 2. Proxies that need no labels.
# --------------------------------------------------------------------------- #

ZH_DIGITS = {"一": 1, "二": 2, "三": 3, "四": 4, "五": 5,
             "六": 6, "七": 7, "八": 8, "九": 9, "十": 10}


def zh_number(text):
    """十一 -> 11, 十 -> 10, 三 -> 3. Enough for a day of the month."""
    if "十" in text:
        left, _, right = text.partition("十")
        return (ZH_DIGITS.get(left, 1) if left else 1) * 10 + \
            (ZH_DIGITS.get(right, 0) if right else 0)
    return ZH_DIGITS.get(text, 0)


def rules_date(text):
    """The regex-and-rules baseline from the cycle's step 5, reused as a
    MONITOR. It needs no labels: it reads the same source the model read."""
    import re
    m = re.search(r"([一二三四五六七八九十\d]+)月([一二三四五六七八九十\d]+)日", text)
    if not m:
        return None
    month, day = (zh_number(g) if not g.isdigit() else int(g) for g in m.groups())
    return f"2026-{month:02d}-{day:02d}"


def proxies(evs):
    stored = [e for e in evs if e["outcome"] == "stored"]
    filled = [e for e in stored if e["record"].get("location") is not None]
    conf = [e["record"].get("confidence", 0) for e in stored
            if isinstance(e["record"].get("confidence"), (int, float))]
    agree = [e for e in stored
             if e["record"].get("date") == rules_date(e["input_snapshot"] or "")]
    return {
        "schema-valid rate": len(stored) / len(evs),
        "retry rate": sum(1 for e in evs if e["attempts"] > 1) / len(evs),
        "location fill rate": len(filled) / max(1, len(stored)),
        "mean confidence": statistics.mean(conf) if conf else 0.0,
        "mean output tokens": statistics.mean(e["usage"]["output"] for e in evs),
        "rules-baseline agreement": len(agree) / max(1, len(stored)),
    }


def type_distribution(evs):
    stored = [e for e in evs if e["outcome"] == "stored"]
    counts = {}
    for e in stored:
        t = e["record"].get("event_type")
        counts[t] = counts.get(t, 0) + 1
    return {k: v / max(1, len(stored)) for k, v in counts.items()}


def tv_distance(p, q):
    keys = set(p) | set(q)
    return 0.5 * sum(abs(p.get(k, 0) - q.get(k, 0)) for k in keys)


def section_2_proxies():
    ops.rule("2. What moves at the reskill, without a single label")
    before = [e for d in range(40, 45) for e in live_traffic(d)]
    after = [e for d in range(46, 51) for e in live_traffic(d)]
    p_before, p_after = proxies(before), proxies(after)
    truth = acc(after) - acc(before)

    w = [28, 14, 14, 12, 10]
    ops.row("signal", "days 40-44", "days 46-50", "change", "moved?", widths=w)
    ops.row("record accuracy (LABELS)", f"{acc(before):.3f}", f"{acc(after):.3f}",
            f"{truth:+.3f}", "yes", widths=w)
    moved = []
    for k in p_before:
        rel_change = (p_after[k] - p_before[k]) / (abs(p_before[k]) or 1)
        ops.row(k, f"{p_before[k]:.3f}", f"{p_after[k]:.3f}",
                f"{p_after[k] - p_before[k]:+.3f}",
                "MOVED" if abs(rel_change) > 0.05 else "no", widths=w)
        if abs(rel_change) > 0.05:
            moved.append(k)
    tv = tv_distance(type_distribution(before), type_distribution(after))
    ops.row("event_type distribution", "-", "-", f"TV {tv:.3f}",
            "MOVED" if tv > 0.05 else "no", widths=w)
    if tv > 0.05:
        moved.append("event_type distribution")

    # The same gold-free monitor, restricted to the documents where it can
    # actually discriminate. On a regulation document the event date IS the
    # fetch date, so the rule and the failure mode agree and the monitor is
    # blind by construction.
    def sub(evs):
        return [e for e in evs
                if rules_date(e["input_snapshot"] or "") != "2026-03-11"]
    sb, sa = proxies(sub(before)), proxies(sub(after))
    subset_delta = sa["rules-baseline agreement"] - sb["rules-baseline agreement"]
    ops.row("  same, on documents the", "", "", "", "", widths=w)
    ops.row("  rule can discriminate", f"{sb['rules-baseline agreement']:.3f}",
            f"{sa['rules-baseline agreement']:.3f}",
            f"{sa['rules-baseline agreement'] - sb['rules-baseline agreement']:+.3f}",
            "", widths=w)

    print(f"\ngold-free signals that moved more than 5%: "
          f"{', '.join(moved) or 'NONE'}")
    print("\nThe flat rows are the important ones, and there are five of them.")
    print("Schema-valid rate, retry rate, field-fill rate, output length and")
    print("mean confidence all held steady across a 12-point collapse in")
    print("record accuracy. That is not a quirk of this fixture: the reskill")
    print("made the model SEMANTICALLY worse, and every one of those signals")
    print("measures the SHAPE of the output. A degradation that keeps the")
    print("shape is invisible to all of them.")
    print("\nMean confidence deserves its own sentence, because it is the")
    print("panel everyone builds. Confidence is a token the model emits, not")
    print("a measurement it takes; a worse model is confidently wrong at the")
    print("rate it used to be confidently right. A confidence panel is not a")
    print("quality panel and it never was.")
    print("\nThe closest thing to a working gold-free monitor is the one that")
    print("compares the output against something OUTSIDE it: agreement with")
    print("the regex-and-rules date extractor, which reads the same source")
    print("the model read and needs no label. It moved 1.8 points over all")
    print("traffic and 4.2 points on the documents where the rule can")
    print("discriminate at all -- on a regulation document the event date IS")
    print("the fetch date, so the rule and the failure mode agree and the")
    print("monitor is blind by construction. Which is the second lesson: a")
    print("gold-free monitor's sensitivity is a property of the traffic mix,")
    print("so compute it per slice or it will be diluted to nothing by the")
    print("slice it cannot see.")
    print("\nThe honest summary is uncomfortable and worth writing down: a")
    print("12-point collapse in record accuracy produced no gold-free signal")
    print("above a 5% threshold, and the best available proxy moved a third")
    print("as far as the truth did. Gold-free monitors are for catching")
    print("SHAPE failures fast and cheaply on 100% of traffic. Semantic")
    print("degradation needs labels, which is why the scheduled eval run in")
    print("section 1 exists and why the cycle's 50 records are the")
    print("prerequisite for every other row on this layer.")
    print("\nThe reuse worth remembering anyway: the rules baseline built as a")
    print("COMPARISON in the cycle's step 5 is also a MONITOR, running")
    print("forever on all traffic for the cost of a regex.")
    return p_before, p_after, moved, truth, subset_delta


# --------------------------------------------------------------------------- #
# 3. Input drift, and what an input-drift alarm is worth.
# --------------------------------------------------------------------------- #

def doc_lengths(evs):
    return [float(len(e["input_snapshot"] or "")) for e in evs]


def section_3_input_drift():
    ops.rule("3. Input drift: three events, one detector")
    print("PSI against a ROLLING reference -- the previous seven days -- so")
    print("the detector reports a change rather than a level. A fixed")
    print("reference window alarms forever after the first shift, which is")
    print("how input-drift dashboards get muted in week three.\n")
    quality_ref = acc([e for d in range(5, 10) for e in live_traffic(d, 200)])

    def window(lo, hi, n=150):
        return doc_lengths([e for d in range(lo, hi) for e in live_traffic(d, n)])

    ops.row("day", "PSI vs prior 7 days", "PSI alarm", "record accuracy",
            "quality alarm", widths=[8, 22, 12, 18, 14])
    events = []
    for day in (15, 21, 26, 34, 40, 46, 52):
        evs = list(live_traffic(day, 300))
        p = ops.psi(window(day - 8, day - 1), doc_lengths(evs))
        a = acc(evs)
        q_alarm = a < quality_ref - 0.05
        events.append((day, p, q_alarm))
        ops.row(day, f"{p:.3f}", "ALARM" if p > 0.25 else "-", f"{a:.3f}",
                "ALARM" if q_alarm else "-", widths=[8, 22, 12, 18, 14])

    def score_at(thr):
        t = sum(1 for _d, p, q in events if p > thr and q)
        f = sum(1 for _d, p, q in events if p > thr and not q)
        n = sum(1 for _d, p, q in events if q and p <= thr)
        return t, f, n

    tp, fp, fn = score_at(0.25)
    print(f"\nPSI alarms: {tp + fp}   of which quality actually moved: {tp}")
    print(f"PSI precision {tp / max(1, tp + fp):.2f}   "
          f"recall {tp / max(1, tp + fn):.2f}")

    # The threshold is doing more work than the detector, so show the sweep.
    print()
    ops.row("PSI threshold", "alarms", "precision", "recall",
            widths=[16, 12, 12, 12])
    for thr in (0.10, 0.15, 0.25, 0.50):
        t, f, n = score_at(thr)
        ops.row(thr, t + f, f"{t / max(1, t + f):.2f}",
                f"{t / max(1, t + n):.2f}", widths=[16, 12, 12, 12])
    print("\nThe harmless length shift scored 0.190 against the industry")
    print("default of 0.25 -- it did not alarm because of where the threshold")
    print("happens to sit, not because the detector understood anything. At")
    print("0.15 it becomes a false alarm and precision halves. Recall never")
    print("improves, because the failure the threshold cannot reach is the one")
    print("with no input signal at all.")
    print(f"\nDay {LONG_DAY} is a distribution shift with no quality cost: the")
    print("documents got longer and the model did not care. Day "
          f"{REG_DAY} is a")
    print("mix shift toward a slice this prompt is measurably worse at, and")
    print("the detector is right. Day "
          f"{ops.SILENT_RESKILL_DAY} is the provider changing the model")
    print("under a stable input distribution, and an input detector cannot")
    print("see it by construction -- there is nothing wrong with the input.")
    print("\nThe conclusion is not that input drift monitoring is useless. It")
    print("is that it is a monitor on the INPUT, and its alarms are")
    print("hypotheses about quality with a measured precision -- the same")
    print("finding as the heuristic grader in ../deterministic-graders.md,")
    print("which fired 27 times to catch 2 real errors. Route it to a review")
    print("queue, never to a page, and put the measured precision in the")
    print("alert text so the person reading it knows what it is worth.")
    return tp, fp, fn


# --------------------------------------------------------------------------- #
# 4. The set that stopped representing the traffic.
# --------------------------------------------------------------------------- #

def section_4_stale_set():
    ops.rule("4. The frozen holdout goes quietly out of date")
    ops.row("day", "frozen set acc", "live traffic acc", "gap", "mix",
            widths=[8, 18, 20, 12, 22])
    rows = []
    for day in (10, 25, 35, 40, 44, 46, 52):
        f = acc(run_frozen(day))
        live = acc(live_traffic(day, 400))
        label = ("base" if day < LONG_DAY else
                 "longer docs" if day < REG_DAY else "regulation-heavy")
        rows.append((day, f, live))
        ops.row(day, f"{f:.3f}", f"{live:.3f}", f"{live - f:+.3f}", label,
                widths=[8, 18, 20, 12, 22])

    share_ref = sum(1 for d, _s in FROZEN if d == "N03") / EVAL_N
    share_live = MIX_REG["N03"] / sum(MIX_REG.values())
    print(f"\nshare of regulation documents -- frozen set {share_ref:.0%}, "
          f"live traffic after day {REG_DAY} {share_live:.0%}")
    gap35 = [r for r in rows if r[0] == 35][0]
    print(f"\nOn day 35 the frozen set reads {gap35[1]:.3f} and the traffic it")
    print(f"is supposed to represent reads {gap35[2]:.3f}. Nothing is wrong")
    print("with the set. It is measuring a distribution that stopped arriving.")
    print("\nBoth failures are in this table and they need opposite fixes:")
    print("  - a frozen set catches a MODEL change exactly (day 45, both")
    print("    columns drop) and is worth freezing for exactly that reason")
    print("  - a frozen set misses a MIX change entirely, and a resampled one")
    print("    catches it while losing the ability to say which record moved")
    print("\nSo run both. The frozen set is the regression gate; a monthly")
    print("resample of live traffic is the CHECK ON THE SET, and the number")
    print("to watch is the GAP between them. A widening gap is not a quality")
    print("problem, it is a representativeness problem, and it invalidates")
    print("every decision the gate made while it widened.")
    print("\nThe cheap version of this that needs no labels: compare the")
    print("feature distribution of the set with the feature distribution of")
    print("last week's traffic -- section 3's PSI, pointed at your own eval")
    print("set instead of at production.")
    return rows, share_ref, share_live


def score(h, proxies_out, drift, stale):
    ops.rule("5. The predictions")
    frozen, fresh, res_frozen, res_fresh = h
    _pb, _pa, moved, truth, subset_delta = proxies_out
    tp, fp, fn = drift
    rows, share_ref, share_live = stale
    d45 = [r for r in rows if r[0] == 46][0]
    d35 = [r for r in rows if r[0] == 35][0]
    verdicts = {
        "A": (f"WRONG in a way that is about the harness, not the size -- the "
              f"frozen set with frozen seeds has a day-to-day noise floor of "
              f"exactly 0.0000, so a difference is a difference. Resampling "
              f"the same 50 records each day gave a quiet-period standard "
              f"deviation of {statistics.pstdev(fresh[:LONG_DAY]):.4f} and "
              f"turns an exact comparison into a statistical one for nothing"),
        "B": (f"MOSTLY RIGHT, and it is the uncomfortable answer -- "
              f"{len(moved)} of six gold-free signals moved more than 5% "
              f"against a true accuracy change of {truth:+.3f}. Schema "
              f"validity, retry rate, fill rate, output length and mean "
              f"confidence were all flat. The best proxy -- agreement with "
              f"the regex baseline on documents where the rule can "
              f"discriminate -- moved {subset_delta:+.3f}, a third as far as "
              f"the truth. Gold-free monitors catch SHAPE failures; semantic "
              f"degradation needs the labelled set"),
        "C": (f"PARTLY, and its recall is the number to remember -- the PSI "
              f"detector alarmed once at the default 0.25 threshold, "
              f"correctly, for precision {tp / max(1, tp + fp):.2f} and recall "
              f"{tp / max(1, tp + fn):.2f}. It could not see the provider "
              f"reskill by construction, because nothing was wrong with the "
              f"input, and the harmless length shift scored 0.190 -- a false "
              f"alarm at any threshold below the default. An input alarm is a "
              f"hypothesis about quality with a measurable precision, not a "
              f"quality signal"),
        "D": (f"WRONG -- on day 35 the frozen holdout read {d35[1]:.3f} while "
              f"the traffic read {d35[2]:.3f}, because the set held "
              f"{share_ref:.0%} regulation documents and production had moved "
              f"to {share_live:.0%}. The set was fine and had stopped "
              f"describing the system. Watch the GAP, not the level"),
    }
    for key, text in PREDICTIONS.items():
        print(f"{key}. {verdicts[key]}\n   claim: {text}\n")


if __name__ == "__main__":
    h = section_1_harness()
    print()
    proxies_out = section_2_proxies()
    print()
    drift = section_3_input_drift()
    print()
    stale = section_4_stale_set()
    print()
    score(h, proxies_out, drift, stale)
