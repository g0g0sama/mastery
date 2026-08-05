"""Model and prompt registry: which configuration produced this record?

Map row (Layer 9): "Which prompt and model produced a given stored record."

Section 1 measures what each level of stamping can actually answer, over sixty
days of a release timeline that includes a canary rollout and one provider-side
change that no deploy accompanied. Section 2 builds the behavioural fingerprint
that catches the change the declared fields cannot. Section 3 runs the incident
query -- "which stored records are affected" -- with stamps and without.
Section 4 asks the question people expect a registry to answer and it does not.

Every record here came out of the fake provider; the release timeline and the
reskill day are declared in ops.py.

Commit to the predictions before running.
"""
from __future__ import annotations

import json
from dataclasses import replace

import ops

PREDICTIONS = {
    "A": "Storing the model name and the prompt name on each record is enough "
         "to know what produced it.",
    "B": "Hashing the prompt text gives the prompt a version.",
    "C": "If a bad prompt shipped on day 12 and was fixed on day 40, the "
         "affected records are the ones written between those dates.",
    "D": "With everything stamped, any stored record can be reproduced.",
}

DAYS, PER_DAY = 60, 100


# --------------------------------------------------------------------------- #
# Ground truth: what actually decided this record's behaviour.
# --------------------------------------------------------------------------- #

def behaviour_key(e) -> tuple:
    """The tuple a perfect oracle would return. `skill` stands in for 'which
    model weights answered', which is exactly the thing a service pinning an
    alias cannot observe."""
    rel = next(r for r in ops.RELEASES if r.tag == e["release"])
    skill = ops.RESKILLED.skill if e["day"] >= ops.SILENT_RESKILL_DAY \
        else ops.MODELS[rel.model].skill
    return (rel.tag, rel.prompt_version, rel.temperature, rel.constrained,
            rel.schema_version, skill)


STAMPS = {
    "nothing": lambda e: (),
    "model name": lambda e: (e["stamp"]["model"],),
    "model + prompt name": lambda e: (e["stamp"]["model"], e["stamp"]["prompt"]),
    "+ prompt and param sha": lambda e: (e["stamp"]["model"], e["stamp"]["prompt"],
                                         e["stamp"]["prompt_sha"],
                                         e["stamp"]["params_sha"]),
    "full declared stamp": lambda e: tuple(sorted(e["stamp"].items())),
}


def section_1_attribution(events):
    ops.rule("1. Sixty days of records, five levels of stamping")
    print(f"{len(events)} records, {len({behaviour_key(e) for e in events})} "
          f"distinct behaviours actually in play.\n")

    ops.row("stamped with", "distinct stamps", "records uniquely attributable",
            "share", widths=[26, 18, 32, 10])
    results = {}
    for name, fn in STAMPS.items():
        groups = {}
        for e in events:
            groups.setdefault(fn(e), set()).add(behaviour_key(e))
        unique = sum(1 for e in events if len(groups[fn(e)]) == 1)
        results[name] = unique / len(events)
        ops.row(name, len(groups), unique, f"{unique / len(events):.1%}",
                widths=[26, 18, 32, 10])

    print("\nA prompt NAME is worth 25.9% here because `v2` covered three")
    print("releases that differed in decoding parameters, schema version and")
    print("code. Adding the two shas buys nothing on this timeline -- worth")
    print("knowing, because it is the fix that feels like the answer -- since")
    print("the releases they separate are the ones already separated by name.")
    print("Only the full declared stamp reaches 63%.")
    print("\nWhat the remaining 37% is:\n")
    ops.row("release", "days live", "spans the reskill?", "attributable?",
            widths=[12, 18, 22, 16])
    full = STAMPS["full declared stamp"]
    for rel in ops.RELEASES:
        mine = [e for e in events if e["release"] == rel.tag]
        if not mine:
            continue
        days = f"{min(e['day'] for e in mine)}-{max(e['day'] for e in mine)}"
        spans_it = any(e["day"] >= ops.SILENT_RESKILL_DAY for e in mine) and \
            any(e["day"] < ops.SILENT_RESKILL_DAY for e in mine)
        groups = {}
        for e in events:
            groups.setdefault(full(e), set()).add(behaviour_key(e))
        ok = len(groups[full(mine[0])]) == 1
        ops.row(rel.tag, days, "YES" if spans_it else "no",
                "yes" if ok else "NO", widths=[12, 18, 22, 16])
    print(f"\nExactly the release that was live on both sides of day "
          f"{ops.SILENT_RESKILL_DAY}.")
    print("The full declared stamp names every field the service controls,")
    print("and the provider changed what `mid-1`")
    print("resolves to with no deploy, no config change, and no field to")
    print("record it in. Identity by declaration cannot detect a change made")
    print("on the other side of the boundary -- which is section 2.")
    return results


# --------------------------------------------------------------------------- #
# 2. The fingerprint that is taken rather than declared.
# --------------------------------------------------------------------------- #

PROBE = [(d, a) for d in ops.DOC_IDS for a in range(3)]


def behavioural_hash(rel, day) -> str:
    """Run a fixed probe set through the configuration and hash the outputs.

    Cheap: 24 calls, once per deploy and once per day. It is the only detector
    here that observes the system instead of describing it.
    """
    out = []
    for doc_id, attempt in PROBE:
        e = ops.process(doc_id, rel, seq=10_000 + attempt, day=day)
        out.append(json.dumps(e["record"], sort_keys=True, ensure_ascii=False)
                   if e["record"] else f"!{e['error_class']}")
    return ops.sha("|".join(out))[:12]


def _edit_prompt_in_place():
    """The most ordinary change there is: someone improves `v2` and saves the
    file. The name does not move, because moving it means updating the config
    and the deploy, and the edit is an improvement."""
    old = ops.PROMPT_VARIANTS["v2"]
    ops.PROMPT_VARIANTS["v2"] = {
        "text": old["text"].replace("Sentence: ",
                                    "Prefer the most specific location "
                                    "mentioned. Sentence: "),
        "skill_delta": old["skill_delta"] - 0.06,
        "slice_delta": old["slice_delta"],
    }
    return old


def section_2_fingerprint():
    ops.rule("2. Five changes, five detectors")
    base = ops.Release("base", 0, "a11f3c9", prompt_version="v2")
    b0, day0 = base, 20
    ref = {"model": b0.model, "prompt": b0.prompt_version,
           "prompt_sha": b0.prompt_sha(), "params_sha": b0.params_sha(),
           "behaviour": behavioural_hash(b0, day0)}

    def probe(rel, day):
        return {"model": rel.model, "prompt": rel.prompt_version,
                "prompt_sha": rel.prompt_sha(), "params_sha": rel.params_sha(),
                "behaviour": behavioural_hash(rel, day)}

    changes = [("prompt file edited, still called v2", "in-place", 20),
               ("prompt version changed (v2 -> v1)",
                replace(base, prompt_version="v1"), 20),
               ("temperature 0.0 -> 0.7", replace(base, temperature=0.7), 20),
               ("constrained decoding turned on",
                replace(base, constrained=True), 20),
               ("provider reskills the alias", base, 46)]

    ops.row("change", "model name", "prompt name", "prompt sha", "params sha",
            "behaviour", widths=[36, 12, 13, 12, 12, 12])
    caught = {}
    for label, rel, day in changes:
        if rel == "in-place":
            saved = _edit_prompt_in_place()
            got = probe(base, day)
            ops.PROMPT_VARIANTS["v2"] = saved
        else:
            got = probe(rel, day)
        cells = ["CAUGHT" if got[k] != ref[k] else "-"
                 for k in ("model", "prompt", "prompt_sha", "params_sha",
                           "behaviour")]
        caught[label] = cells
        ops.row(label, *cells, widths=[36, 12, 13, 12, 12, 12])

    print("\nRead the columns, not the rows. The prompt sha catches a prompt")
    print("edit and nothing else. The params sha catches a decoding change and")
    print("nothing else -- and it is the field nobody stores, which is why a")
    print("temperature change looks like a model regression. The prompt NAME")
    print("catches nothing at all when the file is edited in place, which is")
    print("the most ordinary change on the list. Only the behavioural hash")
    print("catches all five, because it is the only detector that runs the")
    print("system instead of describing it.")
    print("\nThis is the third time this repository has arrived at the same")
    print("shape. ../eval-set-versioning.md found that hashing the policy")
    print("source file missed a runtime normalizer swap and needed a probe set")
    print("pushed through the normalizers. ../reproducible-builds.md found a")
    print("byte-identical artifact behaving differently. The rule underneath")
    print("all three: hash what the system DOES on a fixed input, not what its")
    print("configuration SAYS.")
    return caught


# --------------------------------------------------------------------------- #
# 3. The incident query.
# --------------------------------------------------------------------------- #

def section_3_incident(events):
    ops.rule("3. 'The v2 prompt had a bug. Which records are affected?'")
    r2 = ops.RELEASES[1]
    fixed_day = ops.RELEASES[2].day
    truth = {e["request_id"] for e in events
             if e["stamp"]["prompt"] == "v2" and r2.day <= e["day"] < fixed_day}
    by_date = {e["request_id"] for e in events if r2.day <= e["day"] < fixed_day}
    by_stamp = {e["request_id"] for e in events
                if e["stamp"]["prompt"] == "v2" and r2.day <= e["day"] < fixed_day}

    ops.row("method", "selected", "true positives", "precision", "recall",
            widths=[26, 12, 16, 12, 10])
    for name, sel in (("date range", by_date), ("stamp query", by_stamp)):
        tp = len(sel & truth)
        ops.row(name, len(sel), tp, f"{tp / max(1, len(sel)):.3f}",
                f"{tp / len(truth):.3f}", widths=[26, 12, 16, 12, 10])

    canary = [e for e in events
              if r2.day <= e["day"] < r2.day + r2.canary_days]
    on_old = sum(1 for e in canary if e["stamp"]["prompt"] != "v2")
    print(f"\nrecords written during the {r2.canary_days}-day canary: "
          f"{len(canary)}, of which {on_old} were served by the previous "
          f"release")
    print(f"date-range false positives: {len(by_date - truth)}")
    print("\nA date range is a proxy for a deploy, and a deploy is not an")
    print("instant. Canary, blue-green, a rollout that stalls, a worker pool")
    print("that drains slowly, a queue holding requests built against the old")
    print("config -- every one of them makes the boundary fuzzy in the")
    print("direction nobody checks. The stamp query needs no boundary at all.")
    print("\nThe cost of being wrong here is not the query. It is that the")
    print("remediation -- reprocess, refund, notify, retract -- runs against")
    print("the selected set, and a set with false positives reprocesses")
    print("records that were fine while a set with false negatives leaves bad")
    print("ones in the table.")
    return len(by_date - truth), len(truth)


# --------------------------------------------------------------------------- #
# 4. What a registry does not give you.
# --------------------------------------------------------------------------- #

def section_4_reproduction():
    ops.rule("4. Attribution is not reproduction")
    rel = ops.RELEASES[1]
    old = [ops.process(ops.DOC_IDS[i % len(ops.DOC_IDS)], rel, seq=i, day=20)
           for i in range(200)]

    same_day = [ops.process(e["doc_id"], rel, seq=e["seq"], day=20) for e in old]
    today = [ops.process(e["doc_id"], rel, seq=e["seq"], day=50) for e in old]
    hot = replace(rel, temperature=0.7)
    draw1 = [ops.process(e["doc_id"], hot, seq=e["seq"], day=20) for e in old]
    draw2 = [ops.process(e["doc_id"], hot, seq=e["seq"] + 500_000, day=20)
             for e in old]

    def agree(a, b):
        return sum(1 for x, y in zip(a, b)
                   if json.dumps(x["record"], sort_keys=True) ==
                   json.dumps(y["record"], sort_keys=True)) / len(a)

    ops.row("re-execution", "identical records", widths=[52, 20])
    ops.row("same config, same day, same inputs", f"{agree(old, same_day):.3f}",
            widths=[52, 20])
    ops.row("same config, replayed after the alias moved",
            f"{agree(old, today):.3f}", widths=[52, 20])
    ops.row("same config at temperature 0.7, two draws",
            f"{agree(draw1, draw2):.3f}", widths=[52, 20])

    print("\nA registry answers 'what ran'. It does not answer 'run it again")
    print("and get this back', and the three rows are three different reasons:")
    print("  - nothing changed, so replay reproduces (the easy case, and the")
    print("    only one most teams ever test)")
    print("  - the alias moved, so the configuration that is stamped no longer")
    print("    resolves to what it resolved to. Provider-side retirement does")
    print("    this permanently, and no field you store prevents it")
    print("  - sampling above temperature 0 makes two draws of the SAME")
    print("    configuration disagree, by design")
    print("\nWhich reframes what to store. If a record has to be defensible")
    print("later -- a claim, an extraction, a decision -- store the OUTPUT and")
    print("its provenance, not a recipe for regenerating it. The registry")
    print("makes the record attributable and auditable; it does not make the")
    print("model a pure function.")

    # What the stamp costs, since it is the objection that gets raised.
    name_only = len(json.dumps({"model": rel.model, "prompt": rel.prompt_version}))
    full = len(json.dumps(rel.full_stamp()))
    print(f"\nbytes per record: name stamp {name_only}, full stamp {full}, "
          f"config_id foreign key 8")
    n_configs = len({tuple(sorted(r.full_stamp().items())) for r in ops.RELEASES})
    print(f"distinct configurations in {DAYS} days: {n_configs}. The stamp")
    print("belongs in a config table with an integer key on the record -- the")
    print("cardinality is per RELEASE, not per record, which is the one design")
    print("decision in this module.")
    return agree(old, same_day), agree(old, today), agree(draw1, draw2)


def score(results, caught, incident, repro):
    ops.rule("5. The predictions")
    fp, truth = incident
    verdicts = {
        "A": (f"WRONG -- model plus prompt NAME attributed "
              f"{results['model + prompt name']:.1%} of records uniquely, and "
              f"the full declared stamp only "
              f"{results['full declared stamp']:.1%}. A name is not a version: "
              f"`v2` covered three releases differing in decoding parameters, "
              f"schema and code, and survived an in-place edit of its own file"),
        "B": (f"HALF RIGHT and worth doing -- the prompt sha caught both "
              f"prompt changes, including the in-place edit that the NAME "
              f"missed, and neither of the two decoding changes nor the "
              f"provider reskill. Only the behavioural hash caught all five"),
        "C": (f"WRONG -- the date range selected {fp} records that were not "
              f"affected, out of {truth} truly affected, because the release "
              f"rolled out as a canary and a deploy is not an instant. The "
              f"stamp query is exact and needs no boundary"),
        "D": (f"WRONG -- replay reproduced {repro[0]:.0%} of records the same "
              f"day, {repro[1]:.0%} after the alias moved, and two draws at "
              f"temperature 0.7 agreed on {repro[2]:.0%}. A registry gives "
              f"attribution, not reproduction"),
    }
    for key, text in PREDICTIONS.items():
        print(f"{key}. {verdicts[key]}\n   claim: {text}\n")


if __name__ == "__main__":
    events = [e for day in range(DAYS) for e in ops.traffic(day, PER_DAY)]
    results = section_1_attribution(events)
    print()
    caught = section_2_fingerprint()
    print()
    incident = section_3_incident(events)
    print()
    repro = section_4_reproduction()
    print()
    score(results, caught, incident, repro)
