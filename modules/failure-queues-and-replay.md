# Failure queues and replay

**Micro module.** One mechanism, one experiment, three cards. Runs against
[ops-lab/](ops-lab/).

**Capability:** Failure queues and replay (Layer 9, - -> Working). Map evidence:
"Failed extractions replayable after a fix."

---

## The problem

"Replayable" is treated as one property and it is three: whether the item can be
re-run at all, whether it is re-run on the same input, and whether the original
failure can be reproduced. A dead-letter queue that satisfies only the first is
the normal case, and it is the one that turns a fix into a guess.

## The mechanism

**Three entry shapes, three properties, measured on 88 dead-lettered items:**

```text
entry shape                 bytes    replayable   same input as before   failure reproduced
exception message only      31       0%           0%                     0%
+ document id               48       100%         58%                    2%
+ input snapshot + stamp    272      100%         100%                   100%
```

The middle column gets discovered late: replaying by document id re-fetches the
source, and a source that moved makes the replay a different experiment with the
same name. Same failure shape as
[provenance-and-lineage.md](provenance-and-lineage.md), where a re-fetch
silently shifted the spans of a stored record.

The third column is the one nobody stores for. Reproducing a failure needs the
**draw** as well as the input — the sampling seed, the attempt number, whatever
identifies which of the model's possible answers you got. Without it a replay is
a fresh sample from the same distribution and "passes" at the base rate: 2% here.
That is how a bug is closed as not-reproducible and reopened a week later. The
whole difference costs a few hundred bytes per failed item.

**A poison item is not a slow item.** Six items that can never succeed, in a
queue of 600, four workers:

```text
policy                  completed   parked    makespan    worker-seconds  retry attempts
park immediately        594         6         165.4s      660.2           6
retry 3x then park      594         6         170.0s      678.8           24
retry forever           594         6         323.0s      922.0           246
```

1% of the queue added 40% to total worker time and doubled the time to drain it,
while completing exactly the same amount of real work. Parking is not giving up;
it is refusing to spend a shared resource on a private problem.

The same policy meeting an outage:

```text
provider state        retry policy    requests sent     amplification
healthy               retry 3x        1,020             1.02x
degraded              retry 3x        1,750             1.75x
outage                retry 3x        3,000             3.00x
```

A retry policy that costs 2% on a healthy day costs 3x during a total outage,
arriving at a provider that is already failing — and every client does it at the
same moment. The controls are the ones
[provider-errors-retries.md](provider-errors-retries.md) measured: a retry
*budget* as a fraction of traffic rather than a per-request count, a circuit
breaker, and jitter so recovery is not a thundering herd.

**What a replay writes twice.** The queue holds 88 genuine failures and 117
items whose work succeeded and whose acknowledgement was lost — which is what
at-least-once delivery means:

```text
write path                        rows before   rows written  of which duplicates
insert, no key                    3912          117           117
upsert on (source, content)       3912          0             0
```

Replayed under the *same* configuration the genuine failures failed again
exactly — as section 1's third column promises — so this replay added nothing
legitimate and every row it wrote was a duplicate. Draining a queue before the
fix is deployed is a pure duplication event.

The key is **(source instance, extracted content)** and both halves are
load-bearing. Content alone collapses two different articles reporting the same
event. A request id alone collapses nothing when the replay tool enqueues a new
request. And if a source is legitimately re-extracted after its content is
updated, the key has to include the source's **body hash**, or the new
observation is silently swallowed — the redundancy
[provenance-and-lineage.md](provenance-and-lineage.md) found you cannot
normalize away, arriving from the queue side.

**Which configuration does a replayed record belong to?** The dead letters were
produced by r2 (prompt v2, schema 1.0); the replay ran under r4 (prompt v2,
schema 1.1), and 23 of them now store:

```text
stamped as                answers 'what produced this row'      answers 'when was this event'
original release only     NO -- that config did not produce it  yes
replay release only       yes                                   NO -- looks like a day-55 event
both, plus replay_of      yes                                   yes
```

A replayed record is a new record about an old event, produced by a
configuration that did not exist when the event happened. Each single-column
option breaks a query someone runs during an incident: stamp it with the
original release and the registry query from
[model-prompt-registry.md](model-prompt-registry.md) returns rows that release
never wrote, so a remediation reprocesses the wrong set; stamp it with the
replay release and every time series shows a spike of events on the replay day.
Store the producing configuration, the time of the **event**, and a `replay_of`
pointer to what it supersedes.

## The experiment

```powershell
cd modules\ops-lab
python dlq_lab.py      # ~2 s
```

## Boundary

- **The queue simulation is a simulation.** Declared service times, no broker,
  no visibility timeout, no partition ordering, no consumer rebalancing. What
  it demonstrates is resource accounting under a retry policy, which survives;
  the seconds do not.
- **Eight documents behind thousands of requests** makes content-only
  fingerprinting look worse than it is in a real corpus. The direction is right
  and the magnitude is a fixture artifact.
- **"Failure reproduced" is easy here** because the fixture's provider is a
  deterministic function of its inputs. A real provider is not, even at
  temperature 0 — batching, kernel nondeterminism and model updates all leak in
  — so treat 100% as the ceiling a stored draw moves you toward, not the value
  you will measure.
- **Nothing here covers who drains the queue.** Ownership, alerting on queue
  age, and the review step before a bulk replay are the operational half, and
  the DLQ that nobody drains is the most common failure of all.

## Cards

### 1. [failure] The fix is deployed, the dead letters were replayed, and half of them failed differently.

**Answer:** Check what the entry stored. Replaying by document id re-fetches the
source: in the lab only 58% of items replayed on the same input, because 18% of
sources had changed. And without the original draw — seed or attempt id — only
2% reproduced the original failure at all, against 100% with the input snapshot
and the stamp stored.

**Why:** A replay is an experiment. Re-running it with a different input, a
different configuration or a different sample is a different experiment.

**Boundary:** Storing the snapshot costs a few hundred bytes per failed item and
raises its own retention question, since the snapshot is a copy of the source
document with the source's privacy and licence terms.

**Tags:** `dlq` `failure` `general-principle`

---

### 2. [decision] An item keeps failing. Retry it, or park it?

**Answer:** Park it after a small bounded number of attempts, and retry only
what is transient. In the lab six poison items — 1% of the queue — added 40% to
worker time and doubled the drain time under unbounded retry while completing
the same real work. The same policy sends 3x the requests at a provider in a
total outage.

**Why:** Retrying spends a shared resource on an item that cannot succeed, and
under load the retries arrive exactly when there is least capacity for them.

**Boundary:** The classification matters more than the count: a 429 is
transient, a schema violation and a code bug are not, and retrying a terminal
error is pure waste at full price. Bound the total retry *budget* as a fraction
of traffic rather than per request, so the policy degrades instead of
amplifying.

**Tags:** `dlq` `decision` `general-principle`

---

### 3. [misconception] Replaying a dead-letter queue is safe — those items failed, so there is nothing to duplicate.

**Answer:** At-least-once delivery means the queue also holds items whose work
succeeded and whose acknowledgement was lost. In the lab 117 of 205 queued items
were in that state, and the naive replay wrote 117 duplicate rows while adding
nothing legitimate — the genuine failures, replayed under the unchanged
configuration, failed again exactly.

**Why:** The queue records delivery, not outcome. Only the write path can
enforce identity.

**Boundary:** Key the write on (source instance, extracted content) — content
alone collapses distinct events, a request id alone collapses nothing once the
replay arrives as a new request. If sources can be re-fetched and change, the
key needs the body hash too, or the corrected extraction is swallowed as a
duplicate.

**Tags:** `dlq` `misconception` `general-principle`
