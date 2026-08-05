"""Metrics and cost monitoring: the number that decides, and the alarm on it.

Map row (Layer 9): "Cost per task on a dashboard, alerting on drift."

Section 1 computes the three denominators and shows them disagreeing. Section 2
prices the failures, which are billed. Section 3 puts four detectors on a
120-day spend series and counts false alarms and detection delay. Section 4 is
the one worth carrying: the incident that a total-spend alert cannot see at all,
because the denominator moved with the numerator.

Token counts and costs are real consequences of the fake provider's output.
Daily volumes, the seasonality, and the day the prompt change ships are
declared.

Commit to the predictions before running.
"""
from __future__ import annotations

import random
import statistics

import ops

PREDICTIONS = {
    "A": "Cost per record went down after the change, so the change was an "
         "improvement.",
    "B": "Failed requests are close to free -- you do not pay for output you "
         "did not get.",
    "C": "A day-over-day alert at 30% catches a cost regression without "
         "drowning anyone in false alarms.",
    "D": "Total spend is the thing to alert on. Everything else is a "
         "breakdown of it.",
}


def unit_costs(events):
    stored = [e for e in events if e["outcome"] == "stored"]
    correct = [e for e in events if e["correct"]]
    total = sum(e["cost"] for e in events)
    return {"requests": len(events), "stored": len(stored),
            "correct": len(correct), "total": total,
            "per_call": total / len(events),
            "per_stored": total / max(1, len(stored)),
            "per_correct": total / max(1, len(correct))}


# --------------------------------------------------------------------------- #
# 1. Three denominators.
# --------------------------------------------------------------------------- #

def section_1_denominators():
    ops.rule("1. The same spend, three denominators")
    ops.row("release", "requests", "$ / call", "$ / stored record",
            "$ / correct record", widths=[10, 12, 12, 20, 20])
    per_release = {}
    for rel in ops.RELEASES:
        day = rel.day + 6                    # past any canary
        evs = [ops.process(ops.DOC_IDS[i % len(ops.DOC_IDS)], rel, seq=i, day=day)
               for i in range(1500)]
        u = unit_costs(evs)
        per_release[rel.tag] = u
        ops.row(f"{rel.tag} ({'constrained' if rel.constrained else 'free'})",
                u["requests"], f"${u['per_call']:.5f}",
                f"${u['per_stored']:.5f}", f"${u['per_correct']:.5f}",
                widths=[22, 12, 12, 20, 20])

    best = {k: min(per_release, key=lambda t: per_release[t][k])
            for k in ("per_call", "per_stored", "per_correct")}
    print(f"\ncheapest per call:            {best['per_call']}")
    print(f"cheapest per stored record:   {best['per_stored']}")
    print(f"cheapest per correct record:  {best['per_correct']}")
    print("\nThe third denominator is the only one that answers a question")
    print("anyone asked. A stored record that is wrong is not output; it is")
    print("work someone will redo, plus a row that has to be found again.")
    print("Constrained decoding stores nearly everything, which improves the")
    print("second denominator by construction and does not improve the third")
    print("-- the same result ../structured-outputs.md measured on quality,")
    print("arriving here as money.")
    return per_release


def section_1b_mix():
    ops.rule("1b. Unit cost up 55%, with nothing about the system changed")
    # Two slices with a routing rule between them: routine documents go to the
    # mid model, complex ones to the large model under a schema. The releases
    # are IDENTICAL before and after. The only thing that moves is who called.
    from dataclasses import replace as _replace
    base = ops.Release("mix", 0, "code", prompt_version="v2")
    routine = _replace(base, model="mid-1")
    complex_ = _replace(base, model="large-1", constrained=True)
    arms = {"routine -> mid-1": (routine, routine),
            "complex -> large-1": (complex_, complex_)}
    share_after = {"routine -> mid-1": 0.38, "complex -> large-1": 0.62}
    share_before = {"routine -> mid-1": 0.70, "complex -> large-1": 0.30}

    def run(rel, n=1200):
        return [ops.process(ops.DOC_IDS[i % len(ops.DOC_IDS)], rel, seq=i,
                            day=10) for i in range(n)]

    ops.row("slice", "share before", "share after", "$ / correct",
            widths=[24, 16, 16, 16])
    agg_b = agg_a = 0.0
    for name, (rb, ra) in arms.items():
        b, a = unit_costs(run(rb)), unit_costs(run(ra))
        agg_b += share_before[name] * b["per_correct"]
        agg_a += share_after[name] * a["per_correct"]
        ops.row(name, f"{share_before[name]:.0%}", f"{share_after[name]:.0%}",
                f"${b['per_correct']:.5f}", widths=[24, 16, 16, 16])
    ops.row("ALL TRAFFIC", "100%", "100%",
            f"${agg_b:.5f} -> ${agg_a:.5f}", widths=[24, 16, 16, 26])
    b_all = {"per_correct": agg_b}
    a_all = {"per_correct": agg_a}
    print(f"\naggregate cost per correct record: {(agg_a / agg_b - 1):+.1%}")
    print("\nNeither slice moved by a cent. The releases are identical, the")
    print("models are identical, the prompts are identical -- the mix moved")
    print("toward the expensive route, because a customer segment grew. This")
    print("is the ordinary case, not a pathology: an aggregate unit cost is a")
    print("weighted average whose weights nobody is watching.")
    print("\nIt runs in the other direction just as easily, and that one is")
    print("worse: a real improvement inside every slice, invisible in the")
    print("aggregate because the mix moved against it. Either way the")
    print("aggregate is unreadable without the weights beside it.")
    print("\nThe operational form of the rule: alert on the slices, report the")
    print("aggregate, and put the mix on the same dashboard. A cost dashboard")
    print("without a volume-by-slice panel cannot be read.")
    return b_all, a_all


# --------------------------------------------------------------------------- #
# 2. What the failures cost.
# --------------------------------------------------------------------------- #

def section_2_waste():
    ops.rule("2. Spend that bought nothing")
    evs = ops.traffic(day=20, n=3000)
    total = sum(e["cost"] for e in evs)
    buckets = {
        "stored and correct": sum(e["cost"] for e in evs if e["correct"]),
        "stored but wrong": sum(e["cost"] for e in evs
                                if e["outcome"] == "stored" and not e["correct"]),
        "schema-invalid output": sum(e["cost"] for e in evs
                                     if e["outcome"] == "invalid"),
        "provider errors (all attempts)": sum(e["cost"] for e in evs
                                              if e["outcome"] == "error"),
    }
    retried = [e for e in evs if e["attempts"] > 1]
    ops.row("what the money bought", "spend", "share", widths=[34, 14, 10])
    for name, amount in buckets.items():
        ops.row(name, ops.usd(amount), f"{amount / total:.1%}",
                widths=[34, 14, 10])
    ops.row("TOTAL", ops.usd(total), "100.0%", widths=[34, 14, 10])
    wasted = 1 - buckets["stored and correct"] / total
    print(f"\nrequests that needed more than one attempt: {len(retried)} "
          f"({len(retried) / len(evs):.1%})")
    print(f"share of spend that produced no usable record: {wasted:.1%}")
    print("\nA failed call is billed for its input tokens. A retried call is")
    print("billed twice for them. And a call whose output failed validation is")
    print("billed in full, for both directions -- the most expensive failure")
    print("mode in the table, because it looks like success until something")
    print("reads the record.")
    print("\nWhich makes the interesting ratio not 'cost per call' but the gap")
    print("between the first and last rows: what fraction of the bill is")
    print("attributable to output a human would accept. That is the number")
    print("that makes a cheaper model with a lower accept rate lose an")
    print("argument it usually wins on the price sheet.")
    return buckets, total, wasted


# --------------------------------------------------------------------------- #
# 3. Alerting on a spend series.
# --------------------------------------------------------------------------- #

DOW = [1.0, 1.0, 1.0, 1.0, 0.95, 0.55, 0.50]      # declared weekly shape
BASE_VOLUME = 9000
STEP_DAY = 90            # a prompt change lands: longer outputs
STEP = 1.35
DIP_START, DIP_END, DIP = 88, 103, 0.72           # a partner outage, same week


def build_series(unit_cost):
    """Declared volumes and seasonality; the per-record cost is the measured
    one from the fixture, scaled by the declared step."""
    rng = random.Random(11)
    spend, volume, per_record = [], [], []
    for d in range(120):
        vol = BASE_VOLUME * DOW[d % 7] * (1 + rng.gauss(0, 0.04))
        if DIP_START <= d < DIP_END:
            vol *= DIP
        unit = unit_cost * (STEP if d >= STEP_DAY else 1.0) * (1 + rng.gauss(0, 0.02))
        volume.append(vol)
        per_record.append(unit)
        spend.append(vol * unit)
    return spend, volume, per_record


def detectors(series):
    """Four ways to turn a series into an alarm. Each returns the set of days
    it fires on."""
    out = {}
    baseline = statistics.mean(series[:60])
    out["static threshold (+25% of baseline)"] = {
        d for d, x in enumerate(series) if x > baseline * 1.25}
    out["day-over-day > 25%"] = {
        d for d in range(1, len(series))
        if series[d] > series[d - 1] * 1.25}
    ew = ops.ewma(series, alpha=0.25)
    sd = statistics.pstdev(series[:60])
    out["EWMA z > 3, raw series"] = {
        d for d in range(len(series)) if ew[d] > baseline + 3 * sd}
    adj = [series[d] / DOW[d % 7] for d in range(len(series))]
    adj_base = statistics.mean(adj[:60])
    adj_sd = statistics.pstdev(adj[:60])
    ew_adj = ops.ewma(adj, alpha=0.25)
    out["EWMA z > 3, seasonally adjusted"] = {
        d for d in range(len(series)) if ew_adj[d] > adj_base + 3 * adj_sd}
    return out


def report(name, fired, step_day=STEP_DAY):
    false_alarms = sorted(d for d in fired if d < step_day)
    hits = sorted(d for d in fired if d >= step_day)
    delay = (hits[0] - step_day) if hits else None
    ops.row(name, len(false_alarms),
            "never" if delay is None else f"{delay} d",
            ", ".join(str(d) for d in false_alarms[:6]) or "-",
            widths=[38, 14, 14, 30])
    return len(false_alarms), delay


def section_3_alerting(unit_cost):
    ops.rule("3. Four detectors on 120 days of total spend")
    spend, volume, per_record = build_series(unit_cost)
    print(f"a prompt change on day {STEP_DAY} raises cost per record by "
          f"{STEP - 1:.0%}")
    print(f"a partner outage from day {DIP_START} to {DIP_END} cuts volume by "
          f"{1 - DIP:.0%}\n")
    ops.row("detector on TOTAL SPEND", "false alarms", "detection",
            "false alarm days", widths=[38, 14, 14, 30])
    results = {}
    for name, fired in detectors(spend).items():
        results[name] = report(name, fired)
    fired = detectors(spend)["day-over-day > 25%"]
    fa = sorted(d for d in fired if d < STEP_DAY)
    hit = min((d for d in fired if d >= STEP_DAY), default=None)
    print("\nThe day-over-day detector is the one everybody builds first and")
    print(f"it fires every Monday: false alarms on days {fa[:5]}, all "
          f"{len({d % 7 for d in fa})} distinct weekday(s). A 2x jump from")
    print("Sunday is the week starting, not a regression. Its false alarms")
    print("are not noise, they are SEASONALITY, arriving on a schedule that")
    print("trains people to ignore the alert.")
    if hit is not None:
        print(f"\nAnd its 'detection' on day {hit} is weekday {hit % 7} -- the "
              f"same weekday it fires on every week.")
        print("A detector that alarms every Monday will always appear to catch")
        print("a Monday regression. Detection delay measured against a")
        print("detector with a 17% base rate is not evidence of anything, and")
        print("this is the arithmetic behind every 'our alert caught it'")
        print("story that nobody checked the false-alarm rate for.")
    print("\nEvery detector in this table is also watching the wrong series --")
    print("see section 4.")
    return spend, volume, per_record, results


def section_4_denominator(spend, volume, per_record):
    ops.rule("4. The incident a spend alert cannot see")
    print("Total spend over the three weeks around the change:\n")
    ops.row("day", "volume", "$ / record", "total spend", widths=[10, 14, 14, 16])
    for d in (84, 87, 89, 90, 92, 95, 100, 105):
        ops.row(d, f"{volume[d]:,.0f}", f"${per_record[d]:.5f}",
                ops.usd(spend[d]), widths=[10, 14, 14, 16])

    before = statistics.mean(spend[80:90])
    after = statistics.mean(spend[90:100])
    print(f"\nmean daily spend, 10 days before: {ops.usd(before)}")
    print(f"mean daily spend, 10 days after:  {ops.usd(after)}  "
          f"({after / before - 1:+.1%})")
    print("\nA 35% regression in unit cost landed in the same week as a 28%")
    print("volume drop, and the bill barely moved. Every detector in section 3")
    print("is watching the product of two things, one of which is not under")
    print("engineering control at all.\n")

    ops.row("detector on $ / RECORD", "false alarms", "detection",
            "false alarm days", widths=[38, 14, 14, 30])
    unit_results = {}
    for name, fired in detectors(per_record).items():
        unit_results[name] = report(name, fired)

    print("\nThe same four detectors, the same code, a different series. The")
    print("unit metric has no seasonality to fight -- cost per record does not")
    print("care that it is Sunday -- so the detector that was drowning in")
    print("Mondays becomes usable, and the step is visible the day it lands.")
    print("\nThe rule this leaves: alert on RATES and RATIOS, report totals.")
    print("A total is the product of a business quantity and an engineering")
    print("quantity, and an alarm on a product cannot tell you which factor")
    print("moved -- or notice when they move in opposite directions, which is")
    print("this section.")

    # The decomposition, since 'which factor moved' is the next question.
    print()
    ops.row("factor", "before", "after", "contribution to spend change",
            widths=[22, 14, 14, 32])
    v0, v1 = statistics.mean(volume[80:90]), statistics.mean(volume[90:100])
    u0, u1 = statistics.mean(per_record[80:90]), statistics.mean(per_record[90:100])
    ops.row("volume", f"{v0:,.0f}", f"{v1:,.0f}", f"{v1 / v0 - 1:+.1%}",
            widths=[22, 14, 14, 32])
    ops.row("cost per record", f"${u0:.5f}", f"${u1:.5f}", f"{u1 / u0 - 1:+.1%}",
            widths=[22, 14, 14, 32])
    ops.row("total (product)", ops.usd(v0 * u0), ops.usd(v1 * u1),
            f"{(v1 * u1) / (v0 * u0) - 1:+.1%}", widths=[22, 14, 14, 32])
    print("\nThree lines, and the two that matter point in opposite")
    print("directions. Put the factors on the dashboard, not only the product:")
    print("volume, tokens per record, price per token, retries per record,")
    print("accept rate. Cost is the last row, and it is the one that moves")
    print("last.")
    return unit_results, (v1 / v0 - 1), (u1 / u0 - 1)


def score(per_release, mix, waste, results, unit_results, factors):
    ops.rule("5. The predictions")
    b_all, a_all = mix
    _buckets, _total, wasted = waste
    dod = "day-over-day > 25%"
    verdicts = {
        "A": (f"UNSUPPORTED without the weights -- in section 1b the "
              f"aggregate cost per correct record moved "
              f"{(a_all['per_correct'] / b_all['per_correct'] - 1):+.1%} with "
              f"neither slice moving at all, because the traffic mix shifted "
              f"toward the expensive route. An aggregate unit cost is a "
              f"weighted average whose weights nobody is watching, and it "
              f"moves in both directions for the same reason"),
        "B": (f"WRONG -- {wasted:.1%} of the day's spend produced no record a "
              f"human would accept. Failed calls are billed for input, "
              f"retries are billed twice for it, and a schema-invalid response "
              f"is billed in full for both directions while looking like "
              f"success"),
        "C": (f"WRONG on total spend -- the day-over-day detector fired "
              f"{results[dod][0]} times before the regression, every one of "
              f"them a Monday. On cost per record, the same detector fired "
              f"{unit_results[dod][0]} times and caught the step in "
              f"{unit_results[dod][1]} days"),
        "D": (f"WRONG -- a {factors[1]:+.0%} move in cost per record landed in "
              f"the same week as a {factors[0]:+.0%} move in volume, and total "
              f"spend barely moved. Alert on rates and ratios; report totals"),
    }
    for key, text in PREDICTIONS.items():
        print(f"{key}. {verdicts[key]}\n   claim: {text}\n")


if __name__ == "__main__":
    per_release = section_1_denominators()
    print()
    mix = section_1b_mix()
    print()
    waste = section_2_waste()
    print()
    unit_cost = per_release["r2"]["per_correct"]
    spend, volume, per_record, results = section_3_alerting(unit_cost)
    print()
    unit_results, dv, du = section_4_denominator(spend, volume, per_record)
    print()
    score(per_release, mix, waste, results, unit_results, (dv, du))
