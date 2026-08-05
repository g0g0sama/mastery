"""Failure queues and replay: what has to be in the dead letter for the replay
to mean anything.

Map row (Layer 9): "Failed extractions replayable after a fix."

Section 1 measures three properties of a dead-letter entry that are usually
treated as one: can it be replayed, is it replayed on the same input, and can
the original failure be reproduced. Section 2 is the queue mechanics -- poison
items, head-of-line blocking and the retry policy that amplifies an outage.
Section 3 is the duplicate rows that a replay writes. Section 4 asks which
configuration a replayed record belongs to, which is where this module meets
../model-prompt-registry.md.

Outcomes, costs and failure classes are real consequences of the fake provider.
Queue timings, worker counts and the share of sources that changed are declared.

Commit to the predictions before running.
"""
from __future__ import annotations

import heapq
import json
import random
import statistics

import ops

PREDICTIONS = {
    "A": "Logging the exception with the document id is enough to replay a "
         "failed extraction after the fix.",
    "B": "Retrying a failed item costs a little latency and nothing else.",
    "C": "Replaying the dead-letter queue after the fix is safe: the items "
         "failed, so there is nothing to duplicate.",
    "D": "A replayed record is just the record that should have been written "
         "the first time.",
}

REL = ops.RELEASES[1]
DAY = 20
CHANGED_SOURCES = 0.18        # declared: share of URLs whose content moved


def failed_items(n=4000):
    evs = ops.traffic(DAY, n)
    return evs, [e for e in evs if e["outcome"] in ("error", "invalid")]


# --------------------------------------------------------------------------- #
# 1. Three properties of a dead-letter entry.
# --------------------------------------------------------------------------- #

ENTRIES = {
    "exception message only": lambda e: {"error": e["error_class"]},
    "+ document id": lambda e: {"error": e["error_class"], "doc_id": e["doc_id"]},
    "+ input snapshot + stamp": lambda e: {
        "error": e["error_class"], "doc_id": e["doc_id"],
        "input": e["input_snapshot"], "stamp": e["stamp"], "seq": e["seq"],
        "release": e["release"]},
}


def section_1_entry(failures):
    ops.rule("1. Can it be replayed, on what input, and can it be reproduced")
    rng = random.Random(8)
    moved = {d for d in ops.DOC_IDS if rng.random() < CHANGED_SOURCES}
    print(f"dead-letter items: {len(failures)}")
    print(f"documents whose source changed before the replay ran: "
          f"{len(moved)} of {len(ops.DOC_IDS)} (declared {CHANGED_SOURCES:.0%})\n")

    w = [28, 14, 18, 22, 16]
    ops.row("entry shape", "bytes", "replayable", "same input as before",
            "failure reproduced", widths=w)
    results = {}
    for name, build in ENTRIES.items():
        entries = [build(e) for e in failures]
        size = statistics.mean(len(json.dumps(x, ensure_ascii=False))
                               for x in entries)
        replayable = sum(1 for x in entries if x.get("doc_id"))
        same_input = sum(1 for x in entries
                         if x.get("input") is not None
                         or (x.get("doc_id") and x["doc_id"] not in moved))
        # Reproducing the failure needs the draw as well as the input: without
        # the seq, the replay is a different sample from the same distribution.
        reproduced = 0
        for x, e in zip(entries, failures):
            if not x.get("doc_id"):
                continue
            seq = x.get("seq", e["seq"] + 999_331)
            rel = REL if "release" in x else REL
            r = ops.process(x["doc_id"], rel, seq=seq, day=DAY)
            reproduced += (r["outcome"] == e["outcome"]
                           and r["error_class"] == e["error_class"])
        results[name] = (replayable, same_input, reproduced)
        ops.row(name, f"{size:.0f}", f"{replayable / len(failures):.0%}",
                f"{same_input / len(failures):.0%}",
                f"{reproduced / len(failures):.0%}", widths=w)

    print("\nThree different questions, and only the third one is what an")
    print("engineer means by 'we can replay it'. The middle column is the one")
    print("that gets discovered late: replaying by document id re-fetches the")
    print("source, and a source that moved makes the replay a different")
    print("experiment with the same name. The identical failure shape is in")
    print("../provenance-and-lineage.md, where a re-fetch silently shifted")
    print("the spans of a stored record.")
    print("\nThe third column is the one nobody stores for. Reproducing a")
    print("failure needs the DRAW as well as the input -- the sampling seed,")
    print("the attempt number, whatever identifies which of the model's")
    print("possible answers you got. Without it a replay is a fresh sample")
    print("from the same distribution, and it 'passes' at the base rate,")
    print("which is how a bug gets closed as not-reproducible and reopened a")
    print("week later.")
    print("\nCost of the difference: a few hundred bytes per failed item.")
    return results


# --------------------------------------------------------------------------- #
# 2. Queue mechanics.
# --------------------------------------------------------------------------- #

def simulate(policy, n_items=600, workers=4, poison=6, seed=3):
    """One queue, four workers, `poison` items that can never succeed.

    Declared timings; the point is the ordering, not the milliseconds.
    """
    rng = random.Random(seed)
    poison_ids = set(rng.sample(range(n_items), poison))
    ready = [(0.0, i, 0) for i in range(n_items)]      # (time, item, attempt)
    heapq.heapify(ready)
    free = [0.0] * workers
    done, parked, work_ms, retries = 0, 0, 0.0, 0
    clock = 0.0
    while ready:
        t, item, attempt = heapq.heappop(ready)
        w = min(range(workers), key=lambda k: free[k])
        start = max(t, free[w])
        service = 0.9 + rng.random() * 0.4
        free[w] = start + service
        clock = max(clock, free[w])
        work_ms += service
        if item not in poison_ids:
            done += 1
            continue
        retries += 1
        if policy == "retry forever":
            if attempt >= 40:                # the lab has to stop somewhere;
                parked += 1                  # production does not, which is
                continue                     # the point of the row
            heapq.heappush(ready, (free[w] + 0.05 * (2 ** min(attempt, 6)),
                                   item, attempt + 1))
        elif policy == "retry 3x then park":
            if attempt < 3:
                heapq.heappush(ready, (free[w] + 0.05 * (2 ** attempt),
                                       item, attempt + 1))
            else:
                parked += 1
        else:                                 # park immediately
            parked += 1
    return {"completed": done, "parked": parked, "makespan": clock,
            "worker_seconds": work_ms, "retry_attempts": retries}


def section_2_queue():
    ops.rule("2. Six poison items in a queue of 600")
    ops.row("policy", "completed", "parked", "makespan", "worker-seconds",
            "retry attempts", widths=[24, 12, 10, 12, 16, 16])
    rows = {}
    for policy in ("park immediately", "retry 3x then park", "retry forever"):
        r = simulate(policy)
        rows[policy] = r
        ops.row(policy, r["completed"], r["parked"], f"{r['makespan']:.1f}s",
                f"{r['worker_seconds']:.1f}", r["retry_attempts"],
                widths=[24, 12, 10, 12, 16, 16])
    waste = (rows["retry forever"]["worker_seconds"]
             / rows["park immediately"]["worker_seconds"])
    span = (rows["retry forever"]["makespan"]
            / rows["park immediately"]["makespan"])
    print(f"\nSix items -- 1% of the queue -- added {waste - 1:.0%} to total "
          f"worker time and")
    print(f"multiplied the time to drain the queue by {span:.1f}x, while "
          f"completing exactly")
    print("the same 594 units of real work.")
    print("\nA poison item is not a slow item. It is an item that will consume")
    print("every resource you give it and never produce anything, and an")
    print("unbounded retry gives it all of them. The parked column is the one")
    print("to read: parking is not giving up, it is refusing to spend the")
    print("shared resource on a private problem.")

    # The same policy, meeting an outage.
    print()
    ops.row("provider state", "retry policy", "requests sent", "amplification",
            widths=[22, 24, 18, 16])
    base = 1000
    for state, fail in (("healthy", 0.02), ("degraded", 0.5), ("outage", 1.0)):
        for policy, tries in (("no retry", 1), ("retry 3x", 3)):
            sent = base * sum(fail ** k for k in range(tries))
            ops.row(state, policy, f"{sent:,.0f}", f"{sent / base:.2f}x",
                    widths=[22, 24, 18, 16])
    print("\nThe retry policy that costs 2% extra traffic on a healthy day")
    print("costs 3x during a total outage, arriving at a provider that is")
    print("already failing. Every client does this at the same time, which is")
    print("how a partial outage becomes a total one. The controls are the ones")
    print("../provider-errors-retries.md measured -- a retry BUDGET as a")
    print("fraction of traffic rather than a per-request count, a circuit")
    print("breaker, and jitter so the recovery is not a thundering herd.")
    return rows, waste


# --------------------------------------------------------------------------- #
# 3. What a replay writes twice.
# --------------------------------------------------------------------------- #

def section_3_duplicates(events, failures):
    ops.rule("3. The replay writes rows that already exist")
    rng = random.Random(12)
    # At-least-once delivery: some items were processed and stored, and the
    # acknowledgement was lost. They are in the queue AND in the table.
    stored = [e for e in events if e["outcome"] == "stored"]
    lost_ack = rng.sample(stored, k=int(0.03 * len(stored)))
    queue = failures + lost_ack
    print(f"items to replay: {len(queue)}  "
          f"({len(failures)} genuine failures + {len(lost_ack)} whose "
          f"acknowledgement was lost)\n")

    # One fetched document instance per request -- two articles can carry the
    # same sentence and still be two events, so identity is the SOURCE plus
    # the extracted content, never the content alone.
    def fingerprint(e, rec):
        return ops.sha(f"{e['request_id']}|{json.dumps(rec, sort_keys=True)}")[:16]

    n_before = len(stored)
    naive_new, keyed = 0, {fingerprint(e, e["record"]) for e in stored}
    keyed_new = 0
    for item in queue:
        # A faithful replay: same input, same draw, per section 1.
        r = ops.process(item["doc_id"], REL, seq=item["seq"], day=DAY)
        if r["outcome"] != "stored":
            continue
        naive_new += 1
        fp = fingerprint(item, r["record"])
        if fp not in keyed:
            keyed.add(fp)
            keyed_new += 1

    ops.row("write path", "rows before", "rows written", "of which duplicates",
            widths=[34, 14, 14, 20])
    ops.row("insert, no key", n_before, naive_new, naive_new - keyed_new,
            widths=[34, 14, 14, 20])
    ops.row("upsert on (source, content)", n_before, keyed_new, 0,
            widths=[34, 14, 14, 20])
    print(f"\nThe {len(failures)} genuine failures replayed under the SAME")
    print("configuration failed again, exactly, which is what section 1's")
    print("third column promised -- so this replay adds nothing legitimate at")
    print(f"all, and every row it wrote is one of the {len(lost_ack)} items")
    print("whose work had already succeeded and whose acknowledgement was")
    print("lost. That is the shape of most real replays: draining a queue")
    print("before the fix is deployed is a pure duplication event.")
    print("\nThe key is (source instance, extracted content), and both halves")
    print("are load-bearing. Content alone collapses two different articles")
    print("that report the same event -- in this fixture, catastrophically:")
    print("eight documents behind thousands of requests. A request id alone")
    print("collapses nothing when the replay arrives as a new request, which")
    print("is how a replay tool usually enqueues it.")
    print("\nThe corollary that costs a schema change later: if the same")
    print("source is legitimately re-extracted after its content is updated,")
    print("the key has to include the source's BODY HASH, or the new")
    print("observation is silently swallowed as a duplicate. That is the")
    print("redundancy ../provenance-and-lineage.md found you cannot normalize")
    print("away, arriving from the queue side.")
    return n_before, naive_new, keyed_new, len(lost_ack)


# --------------------------------------------------------------------------- #
# 4. Which configuration does a replayed record belong to?
# --------------------------------------------------------------------------- #

def section_4_attribution(failures):
    ops.rule("4. A replayed record has two versions and one column")
    old, new = ops.RELEASES[1], ops.RELEASES[3]
    replayed = [ops.process(e["doc_id"], new, seq=e["seq"], day=55)
                for e in failures]
    fixed = sum(1 for r in replayed if r["outcome"] == "stored")
    still = len(replayed) - fixed
    print(f"dead-letter items replayed under the fix: {len(replayed)}")
    print(f"now stored: {fixed} ({fixed / len(replayed):.0%})   "
          f"still failing: {still}\n")

    ops.row("stamped as", "answers 'what produced this row'",
            "answers 'when was this event'", widths=[26, 36, 32])
    ops.row("original release only", "NO -- that config did not produce it",
            "yes", widths=[26, 36, 32])
    ops.row("replay release only", "yes",
            "NO -- looks like a day-55 event", widths=[26, 36, 32])
    ops.row("both, plus replay_of", "yes", "yes", widths=[26, 36, 32])

    print(f"\nThe old release is {old.tag} ({old.prompt_version}, schema "
          f"{old.schema_version}); the replay ran under {new.tag} "
          f"({new.prompt_version}, schema {new.schema_version}).")
    print("A replayed record is a new record about an old event, produced by a")
    print("configuration that did not exist when the event happened. One")
    print("column cannot hold that, and the two single-column options each")
    print("break a query that someone runs during an incident:")
    print("  - stamp it with the original release and the registry query from")
    print("    ../model-prompt-registry.md returns rows that release never")
    print("    wrote, so a remediation reprocesses the wrong set")
    print("  - stamp it with the replay release and every time-series analysis")
    print("    sees a spike of events on the replay day")
    print("\nStore three things: the configuration that produced the row, the")
    print("time of the EVENT, and a replay_of pointer to what it supersedes.")
    print("Then a replay is auditable and the original is still there, which")
    print("is what makes the whole loop -- fail, park, fix, replay -- a")
    print("recoverable operation rather than a second write of unknown origin.")
    return fixed, still


def score(entry, queue, dupes, attribution):
    ops.rule("5. The predictions")
    rows, waste = queue
    n_before, naive_new, keyed_new, n_lost = dupes
    fixed, still = attribution
    by_id = entry["+ document id"]
    full = entry["+ input snapshot + stamp"]
    total = max(1, by_id[0])
    verdicts = {
        "A": (f"WRONG on two of the three properties -- storing the document "
              f"id makes {by_id[0] / total:.0%} of items replayable, but only "
              f"{by_id[1] / total:.0%} replay on the same input (the source "
              f"moved for the rest) and {by_id[2] / total:.0%} reproduce the "
              f"original failure, against {full[2] / total:.0%} when the "
              f"snapshot, the stamp and the draw are stored. A few hundred "
              f"bytes per item is the whole difference"),
        "B": (f"WRONG -- six poison items, 1% of a queue of 600, added "
              f"{waste - 1:.0%} to total worker time and doubled the time to "
              f"drain the queue under an unbounded retry, while completing "
              f"the same amount of real work. The same policy triples the "
              f"request rate against a provider that is already in a total "
              f"outage"),
        "C": (f"WRONG, and backwards -- replayed under the same "
              f"configuration the genuine failures failed again exactly, so "
              f"the replay added nothing legitimate and wrote {naive_new} "
              f"duplicate rows, one for each item whose work had already "
              f"succeeded and whose acknowledgement was lost. Keyed on "
              f"(source instance, content) it wrote {keyed_new}. At-least-once "
              f"delivery means the queue holds successes too"),
        "D": (f"WRONG -- {fixed} of the replayed items now store, under a "
              f"configuration that did not exist when the event happened. "
              f"Stamped with the original release, the registry query returns "
              f"rows that release never wrote; stamped with the replay "
              f"release, every time series shows a spike on the replay day. "
              f"Store both and a replay_of pointer"),
    }
    for key, text in PREDICTIONS.items():
        print(f"{key}. {verdicts[key]}\n   claim: {text}\n")


if __name__ == "__main__":
    events, failures = failed_items()
    entry = section_1_entry(failures)
    print()
    queue = section_2_queue()
    print()
    dupes = section_3_duplicates(events, failures)
    print()
    attribution = section_4_attribution(failures)
    print()
    score(entry, queue, dupes, attribution)
