"""Structured logging and tracing: one request, end to end, including the
model call.

Map row (Layer 9): "One request traced end to end, including model calls."

Section 1 turns "traceable" into a countable thing: eight questions an incident
actually asks, answered mechanically against three logging styles. Section 2 is
about sampling, which is where traces are lost. Section 3 prices the telemetry
against the model spend it describes. Section 4 is the one that costs people a
week: a tail-sampled trace store is a biased sample, and every rate computed
from it is wrong.

Requests, spans and byte counts are real -- they come from ops.process and from
json.dumps. Traffic volume and the price per GB are declared.

Commit to the predictions before running.
"""
from __future__ import annotations

import json
import random
import re

import ops

PREDICTIONS = {
    "A": "A request id on every log line is what makes a request traceable.",
    "B": "Sampling 1% of traces is fine: errors are rare but there are enough "
         "of them that some will be sampled.",
    "C": "Structured logs cost about what text logs cost -- it is the same "
         "information with punctuation.",
    "D": "The trace store is where I look up the current error rate.",
}

DAY, N = 7, 3000


# --------------------------------------------------------------------------- #
# Three ways to emit the same request.
# --------------------------------------------------------------------------- #

def text_log(e) -> list[str]:
    """What a service emits before anyone asks it to emit anything."""
    out = [f"INFO  processing {e['doc_id']}",
           f"INFO  calling model {e['stamp']['model']}"]
    for s in e["spans"]:
        if s["name"] == "extract" and "error" in s["attrs"]:
            out.append(f"WARN  provider error: {s['attrs']['error']}")
    if e["outcome"] == "invalid":
        out.append("ERROR validation failed")
    elif e["outcome"] == "error":
        out.append(f"ERROR extraction failed: {e['error_class']}")
    else:
        out.append(f"INFO  stored record for {e['doc_id']} "
                   f"in {e['latency_ms']:.0f}ms")
    return out


def flat_events(e) -> list[dict]:
    """Structured, one event per step, with a request id on each -- the state
    most services reach and stop at."""
    out = []
    for s in e["spans"]:
        out.append({"ts": s["start"], "request_id": e["request_id"],
                    "step": s["name"], "duration_ms": s["ms"],
                    "level": "info"})
    out.append({"ts": e["latency_ms"], "request_id": e["request_id"],
                "step": "done", "outcome": e["outcome"],
                "error_class": e["error_class"], "level":
                "info" if e["outcome"] == "stored" else "error"})
    return out


def spans(e) -> list[dict]:
    """Spans: parented, attributed, and carrying the identity of what ran."""
    trace_id = e["request_id"]
    root = {"trace_id": trace_id, "span_id": "0", "parent": None,
            "name": "extract_request", "duration_ms": e["latency_ms"],
            "attrs": {"doc_id": e["doc_id"], "slice": e["slice"],
                      "outcome": e["outcome"], "error_class": e["error_class"],
                      "attempts": e["attempts"],
                      "usage_in": e["usage"]["input"],
                      "usage_out": e["usage"]["output"],
                      "cost_usd": e["cost"], **e["stamp"]}}
    out = [root]
    for i, s in enumerate(e["spans"], start=1):
        out.append({"trace_id": trace_id, "span_id": str(i), "parent": "0",
                    "name": s["name"], "duration_ms": s["ms"],
                    "attrs": s["attrs"]})
    return out


# --------------------------------------------------------------------------- #
# 1. Eight questions, answered mechanically.
# --------------------------------------------------------------------------- #

QUESTIONS = [
    "which prompt version produced this record",
    "which model, and was it an alias or a version",
    "what did this request cost",
    "was the model call retried, and with what error",
    "how much of the latency was the model",
    "which retrieval index served the context",
    "which field failed validation",
    "which other requests today hit the same fault",
]


def answer_text(log, e, population):
    joined = "\n".join(log)
    return [
        None,
        (re.search(r"calling model (\S+)", joined).group(1)
         if "calling model" in joined else None),
        None,
        ("retried" if joined.count("provider error") else None),
        None,
        None,
        None,
        # A free-text message is greppable, and grep over a day is not a
        # query: it finds lines, not requests, and it cannot group.
        None,
    ]


def answer_flat(evs, e, population):
    by_step = {ev["step"]: ev for ev in evs}
    extract = [ev for ev in evs if ev["step"] == "extract"]
    klass = by_step["done"]["error_class"]
    return [
        None,
        None,
        None,
        (f"{len(extract)} attempts" if len(extract) > 1 else None),
        (f"{sum(ev['duration_ms'] for ev in extract):.0f} ms of "
         f"{by_step['done']['ts']:.0f}" if extract else None),
        None,
        None,
        # An error_class FIELD is queryable, which is the one thing this style
        # buys over text -- as long as the class is a code and not a message.
        (f"{sum(1 for x in population if x['error_class'] == klass)} today"
         if klass else "no fault"),
    ]


def answer_spans(sp, e, population):
    root = sp[0]
    extract = [s for s in sp if s["name"] == "extract"]
    codes = next((s["attrs"].get("codes") for s in sp
                  if s["name"] == "validate"), None)
    klass, stamp = root["attrs"]["error_class"], e["stamp"]
    same = [x for x in population
            if x["error_class"] == klass and x["stamp"] == stamp]
    return [
        root["attrs"]["prompt"] + "/" + root["attrs"]["prompt_sha"],
        f"{root['attrs']['model']} alias @{root['attrs']['params_sha']}",
        f"${root['attrs']['cost_usd']:.5f}",
        (", ".join(s["attrs"].get("error", "ok") for s in extract)
         if len(extract) > 1 else None),
        f"{sum(s['duration_ms'] for s in extract):.0f} of "
        f"{root['duration_ms']:.0f} ms",
        next(s["attrs"]["index"] for s in sp if s["name"] == "retrieve"),
        (codes[0] if codes else ("none" if codes == [] else None)),
        (f"{len(same)} today, same stamp" if klass else "no fault"),
    ]


def section_1_questions(events):
    ops.rule("1. Eight questions an incident asks, three logging styles")
    # A request that both retried and failed validation -- the interesting
    # kind, and the reason to pick the example rather than take the first.
    e = next((x for x in events if x["attempts"] > 1 and x["outcome"] == "invalid"),
             next((x for x in events if x["outcome"] == "invalid"), events[0]))
    print(f"example request: {e['request_id']}  doc={e['doc_id']}  "
          f"outcome={e['outcome']}  attempts={e['attempts']}\n")

    w = [48, 14, 24, 26]
    styles = [("text log", answer_text(text_log(e), e, events)),
              ("flat structured events", answer_flat(flat_events(e), e, events)),
              ("spans with attributes", answer_spans(spans(e), e, events))]
    ops.row("question", *[s for s, _ in styles], widths=w)
    counts = [0, 0, 0]
    for i, q in enumerate(QUESTIONS):
        cells = []
        for j, (_name, answers) in enumerate(styles):
            a = answers[i]
            counts[j] += a is not None
            cells.append("--" if a is None else str(a)[:24])
        ops.row(q, *cells, widths=w)
    ops.row("ANSWERED", *[f"{c} of {len(QUESTIONS)}" for c in counts], widths=w)

    print("\nThe middle column is the trap. It is structured, it has a request")
    print("id on every line, it satisfies 'we have structured logging' -- and")
    print("it answers three questions, all of them about timing, because the")
    print("only things it recorded are the names of steps and their durations.")
    print("A request id makes lines JOINABLE. It does not make them")
    print("INFORMATIVE, and those are different problems with the same fix")
    print("applied to different fields.")
    print("\nWhat the third column added is not a format. It is a decision")
    print("about WHICH ATTRIBUTES ARE FACTS about a request: the resolved")
    print("model and prompt hash, the token counts and cost, the index")
    print("version, the violation count, the error CLASS rather than message.")
    print("Every one of those is a column some other module in this repository")
    print("needed -- cost per successful task, the error taxonomy, the")
    print("registry, the drift proxy. Tracing is where they are captured.")
    return counts


# --------------------------------------------------------------------------- #
# 2. Sampling.
# --------------------------------------------------------------------------- #

def section_2_sampling(events):
    ops.rule("2. Sampling: three policies at the same storage budget")
    rng = random.Random(5)
    errors = [e for e in events if e["outcome"] != "stored"]
    true_rate = len(errors) / len(events)
    print(f"requests: {len(events)}   true failure rate: {true_rate:.1%}\n")

    head = [e for e in events if rng.random() < 0.01]
    tail = [e for e in events
            if e["outcome"] != "stored" or rng.random() < 0.01]
    ops.row("policy", "traces kept", "errors kept", "errors kept %",
            widths=[34, 14, 14, 16])
    for name, kept in (("head sampling 1%", head),
                       ("tail sampling: all errors + 1%", tail),
                       ("keep everything", events)):
        errs = [e for e in kept if e["outcome"] != "stored"]
        ops.row(name, len(kept), len(errs),
                f"{len(errs) / max(1, len(errors)):.0%}", widths=[34, 14, 14, 16])

    print("\nHead sampling decides before the request has an outcome, so it")
    print("keeps errors at the same rate as everything else -- which for a")
    print("rare failure means it keeps almost none of the only traces anyone")
    print("was going to look at. Tail sampling decides after, at a storage")
    print("cost of a few percent, and is the default worth arguing for.")

    # Per-span sampling, which is the version that looks equivalent.
    print("\nThe same 10% budget, spent two ways:\n")
    ops.row("granularity", "spans kept", "complete traces", "share",
            widths=[26, 14, 18, 10])
    n_traces = 400
    per_trace = [e for e in events[:n_traces] if rng.random() < 0.10]
    span_counts = [len(spans(e)) for e in events[:n_traces]]
    kept_spans_trace = sum(len(spans(e)) for e in per_trace)
    complete_span = 0
    kept_spans = 0
    for e in events[:n_traces]:
        sp = spans(e)
        k = [s for s in sp if rng.random() < 0.10]
        kept_spans += len(k)
        if len(k) == len(sp):
            complete_span += 1
    ops.row("per trace", kept_spans_trace, len(per_trace),
            f"{len(per_trace) / n_traces:.1%}", widths=[26, 14, 18, 10])
    ops.row("per span (independent)", kept_spans, complete_span,
            f"{complete_span / n_traces:.1%}", widths=[26, 14, 18, 10])
    mean_spans = sum(span_counts) / len(span_counts)
    print(f"\nmean spans per trace: {mean_spans:.1f}   "
          f"P(complete trace) at p=0.10 per span: {0.10 ** mean_spans:.2e}")
    print("Both rows stored the same number of spans and one of them stored")
    print("no usable traces at all. The sampling decision has to be made once,")
    print("at the root, and propagated -- which is what a trace context header")
    print("is for and the only reason it has to be forwarded through every")
    print("service, queue and model call in the path.")
    return true_rate, len(head), len([e for e in head if e["outcome"] != "stored"])


# --------------------------------------------------------------------------- #
# 3. What the telemetry costs.
# --------------------------------------------------------------------------- #

PRICE_PER_GB = 0.50           # declared: log ingest, USD
DAILY_REQUESTS = 250_000      # declared


def section_3_volume(events):
    ops.rule("3. Measured bytes, declared volume, derived bill")
    e = events[0]
    variants = {
        "text log": sum(len(line) + 1 for line in text_log(e)),
        "flat structured events": len(json.dumps(flat_events(e))),
        "spans with attributes": len(json.dumps(spans(e))),
        "spans + prompt and response bodies": len(json.dumps(
            spans(e) + [{"trace_id": e["request_id"], "name": "payload",
                         "attrs": {"prompt": ops.RELEASES[0].prompt_text(),
                                   "document": e["input_snapshot"],
                                   "response": json.dumps(e["record"],
                                                          ensure_ascii=False)}}])),
    }
    model_spend = sum(x["cost"] for x in events) / len(events) * DAILY_REQUESTS * 30
    ops.row("what is emitted", "bytes/request", "GB/month", "$/month",
            "vs model spend", widths=[38, 15, 12, 12, 16])
    for name, nbytes in variants.items():
        gb = nbytes * DAILY_REQUESTS * 30 / 1e9
        cost = gb * PRICE_PER_GB
        ops.row(name, nbytes, f"{gb:8.1f}", ops.usd(cost),
                f"{cost / model_spend:8.3%}", widths=[38, 15, 12, 12, 16])
    print(f"\nmodel spend on the same traffic: {ops.usd(model_spend)}/month "
          f"(measured token usage x declared volume)")
    print("\nThe first three rows are noise against the model bill, which is")
    print("the answer to 'can we afford structured logging' and the reason the")
    print("question is asked backwards. The fourth row is the one to think")
    print("about, and it is the row everybody wants: logging the prompt and")
    print("the response makes every trace a copy of the corpus, with the")
    print("licence terms, retention policy and PII exposure of the corpus,")
    print("plus the leak surface from ../config-and-secrets.md. Sample")
    print("payloads, do not log them by default, and give them their own")
    print("retention.")

    # Cardinality, which is the metric-side version of the same mistake.
    print()
    label_sets = {
        "release, slice, outcome": lambda x: (x["release"], x["slice"],
                                              x["outcome"]),
        "+ error_class": lambda x: (x["release"], x["slice"], x["outcome"],
                                    x["error_class"]),
        "+ doc_id": lambda x: (x["release"], x["slice"], x["outcome"],
                               x["error_class"], x["doc_id"]),
        "+ request_id": lambda x: (x["release"], x["slice"], x["outcome"],
                                   x["error_class"], x["request_id"]),
    }
    ops.row("metric labels", f"series in {len(events)} req",
            f"series at {DAILY_REQUESTS:,}/day", widths=[28, 24, 26])
    for name, key in label_sets.items():
        seen = len({key(x) for x in events})
        projected = ("bounded" if seen < len(events) / 10
                     else f"~{DAILY_REQUESTS:,}+")
        ops.row(name, seen, projected, widths=[28, 24, 26])
    print("\nA label whose value space grows with traffic is not a label, it")
    print("is a log line in the wrong system. The rule is worth stating as a")
    print("test rather than as taste: if the number of distinct values grows")
    print("with request count, it belongs in a trace attribute, where it is")
    print("cheap, and not in a metric dimension, where it is a series.")
    return variants, model_spend


# --------------------------------------------------------------------------- #
# 4. The bias nobody accounts for.
# --------------------------------------------------------------------------- #

def section_4_bias(events):
    ops.rule("4. Every rate computed from a tail-sampled store is wrong")
    rng = random.Random(19)
    keep_success = 0.01
    true_rate = sum(1 for e in events if e["outcome"] != "stored") / len(events)

    def sample():
        store = [e for e in events if e["outcome"] != "stored"
                 or rng.random() < keep_success]
        errs = [e for e in store if e["outcome"] != "stored"]
        weighted = len(errs) / (len(errs) + (len(store) - len(errs)) / keep_success)
        return len(errs) / len(store), weighted, len(store) - len(errs)

    naive, weighted, n_success = sample()
    reps = [sample() for _ in range(200)]
    ops.row("quantity", "value", widths=[50, 20])
    ops.row("true failure rate over all requests", f"{true_rate:.3f}",
            widths=[50, 20])
    ops.row("failure rate counted in the trace store", f"{naive:.3f}",
            widths=[50, 20])
    ops.row("same store, weighted by 1 / sampling rate", f"{weighted:.3f}",
            widths=[50, 20])
    ops.row("weighted estimate, mean of 200 resamples",
            f"{sum(r[1] for r in reps) / len(reps):.3f}", widths=[50, 20])
    lo, hi = ops.bootstrap_ci([r[1] for r in reps])
    ops.row("       and its 95% interval", f"[{lo:.3f}, {hi:.3f}]",
            widths=[50, 20])
    print(f"\noverstatement if read naively: {naive / true_rate:.0f}x")
    print(f"the weighted estimator is unbiased and imprecise: this store's")
    print(f"denominator rests on {n_success} sampled successes standing in for "
          f"{len(events) - int(true_rate * len(events))}.")
    print("\nThe trace store is a stratified sample with a sampling rate that")
    print("differs by outcome, which is exactly what makes it useful and")
    print("exactly what makes it unusable as a denominator. Rates come from")
    print("metrics, which count every request; traces explain the numerator.")
    print("\nThe same argument applies to any dataset built from the trace")
    print("store -- an error taxonomy sampled this way over-represents")
    print("failures by construction, which is fine, and a claim about how")
    print("OFTEN a failure class occurs is not recoverable from it without")
    print("the weights. Store the sampling rate on the trace; it costs four")
    print("bytes and it is the difference between a sample and an anecdote.")
    return true_rate, naive


def score(counts, sampling, variants, model_spend, bias):
    ops.rule("5. The predictions")
    true_rate, n_head, head_errors = sampling
    payload_key = "spans + prompt and response bodies"
    payload_cost = (variants[payload_key] * DAILY_REQUESTS * 30 / 1e9
                    * PRICE_PER_GB)
    spans_cost = (variants["spans with attributes"] * DAILY_REQUESTS * 30 / 1e9
                  * PRICE_PER_GB)
    verdicts = {
        "A": (f"WRONG -- structured events with a request id on every line "
              f"answered {counts[1]} of {len(QUESTIONS)} incident questions. "
              f"Spans carrying the resolved model, "
              f"prompt hash, token counts, index version and violation count "
              f"answered {counts[2]}. The id joins the lines; the attributes "
              f"are the content"),
        "B": (f"WRONG -- head sampling at 1% kept {n_head} traces and "
              f"{head_errors} of the failures, because the decision is made "
              f"before the outcome exists. Tail sampling keeps 100% of them "
              f"for a few percent more storage"),
        "C": (f"RIGHT, and it is the wrong comparison -- spans cost "
              f"{spans_cost / model_spend:.1%} of the model spend on the same "
              f"traffic. The row that matters is the one that logs prompt and "
              f"response bodies at {ops.usd(payload_cost)}/month, which is a "
              f"copy of the corpus with the corpus's retention and privacy "
              f"problems, not a logging decision"),
        "D": (f"WRONG -- the failure rate counted inside a tail-sampled store "
              f"was {bias[1]:.3f} against a true {bias[0]:.3f}, an "
              f"overstatement of {bias[1] / bias[0]:.0f}x. Rates come from "
              f"metrics; traces explain them"),
    }
    for key, text in PREDICTIONS.items():
        print(f"{key}. {verdicts[key]}\n   claim: {text}\n")


if __name__ == "__main__":
    events = ops.traffic(DAY, N)
    counts = section_1_questions(events)
    print()
    sampling = section_2_sampling(events)
    print()
    variants, model_spend = section_3_volume(events)
    print()
    bias = section_4_bias(events)
    print()
    score(counts, sampling, variants, model_spend, bias)
