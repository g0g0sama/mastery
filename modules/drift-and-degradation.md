# Drift and quality degradation

**Micro module.** One mechanism, one experiment, three cards. Runs against
[ops-lab/](ops-lab/).

**Capability:** Drift and quality degradation (Layer 9, - -> Independent). Map
evidence: "A scheduled eval run detecting a real regression."

---

## The problem

Sixty days of one service. Three things happen and only one of them is a model
problem: on day 20 the input distribution shifts with no effect on quality, on
day 33 the traffic mix moves toward a slice the prompt is bad at, and on day 45
the provider reskills the model behind the alias. A monitoring setup that cannot
tell those three apart will do the wrong thing twice.

## The mechanism

**The harness decides whether you are doing statistics at all.** The same eval,
run two ways for sixty days:

```text
harness                           mean |day-to-day change|  worst quiet day   baseline acc
frozen set, frozen seeds          0.0000                    0.0000            0.880
fresh sample each day             0.0411                    0.1600            0.906

harness                       baseline  sd        threshold   FA      CUSUM
frozen set, frozen seeds      0.880     0.0000    day 45      0       day 45
fresh sample each day         0.906     0.0358    day 45      17      day 23
```

A frozen set with frozen seeds against a temperature-0 model is a *function*.
Two runs that differ mean the system differed — there is no noise floor to clear
and no interval to compute. Resampling "today's 50 records" instead costs a
3.6-point standard deviation and a 16-point worst quiet day, and buys nothing.

What determinism buys is not detection speed. It is that a difference is
**exact**: the frozen harness names *which* records changed and diffs their
outputs, which turns a number into a fix. Same argument as
[eval-set-versioning.md](eval-set-versioning.md) — hold the set and the seeds
still, so that what moves is the system. (The harness also has to retry
transient provider errors rather than score them; a 429 is a fact about the
provider's queue, and counting it makes the eval measure two things at once.)

**What can be watched without labels — which is less than advertised.** Across
the reskill, on live traffic:

```text
signal                      days 40-44    days 46-50    change      moved?
record accuracy (LABELS)    0.779         0.656         -0.123      yes
schema-valid rate           0.973         0.953         -0.020      no
retry rate                  0.043         0.045         +0.002      no
location fill rate          0.252         0.264         +0.012      no
mean confidence             0.855         0.853         -0.002      no
mean output tokens          58.747        59.004        +0.257      no
rules-baseline agreement    0.991         0.973         -0.018      no
event_type distribution     -             -             TV 0.023    no
  same, on documents the
  rule can discriminate     0.980         0.938         -0.042
```

Zero gold-free signals moved more than 5% across a 12-point collapse. The
reskill made the model *semantically* worse, and every one of those signals
measures the **shape** of the output. Mean confidence deserves its own sentence
because it is the panel everyone builds: confidence is a token the model emits,
not a measurement it takes, and a worse model is confidently wrong at the rate
it used to be confidently right.

The closest thing to a working gold-free monitor is the one that compares the
output against something *outside* it — agreement with the regex-and-rules date
extractor, which reads the same source the model read. It moved 1.8 points over
all traffic and 4.2 points on documents where the rule can discriminate at all;
on a regulation document the event date *is* the fetch date, so the rule and the
failure mode agree and the monitor is blind by construction. A gold-free
monitor's sensitivity is a property of the traffic mix — compute it per slice or
the slice it cannot see will dilute it to nothing.

The uncomfortable summary: gold-free monitors catch shape failures fast and
cheaply on 100% of traffic; semantic degradation needs labels. That is why the
scheduled eval run exists.

**What an input-drift alarm is worth.** PSI on document length, against a
rolling 7-day reference:

```text
day     PSI vs prior 7 days   PSI alarm   record accuracy   quality alarm
15      0.010                 -           0.873             -
21      0.190                 -           0.897             -
26      0.131                 -           0.890             -
34      1.137                 ALARM       0.797             ALARM
40      0.046                 -           0.790             ALARM
46      0.021                 -           0.673             ALARM
52      0.012                 -           0.677             ALARM

PSI threshold   alarms      precision   recall
0.10            3           0.33        0.25
0.15            2           0.50        0.25
0.25            1           1.00        0.25
0.50            1           1.00        0.25
```

Recall 0.25 at every threshold. The harmless length shift scored 0.190 — it did
not alarm because of where the industry-default threshold happens to sit, not
because the detector understood anything, and at 0.15 precision halves. The
reskill is invisible at any threshold: nothing was wrong with the input.

Not useless — but an input monitor's alarms are *hypotheses about quality with a
measurable precision*, the same finding as the heuristic grader in
[deterministic-graders.md](deterministic-graders.md), which fired 27 times to
catch 2 real errors. Route them to a review queue, never to a page, and put the
measured precision in the alert text.

**And the frozen holdout goes quietly out of date:**

```text
day     frozen set acc    live traffic acc    gap         mix
10      0.880             0.855               -0.025      base
25      0.880             0.882               +0.002      longer docs
35      0.880             0.770               -0.110      regulation-heavy
44      0.880             0.738               -0.142      regulation-heavy
46      0.720             0.670               -0.050      regulation-heavy

share of regulation documents -- frozen set 4%, live traffic after day 33: 56%
```

Nothing is wrong with the set. It is measuring a distribution that stopped
arriving. Both failure modes are in this one table and they need opposite fixes:
a frozen set catches a *model* change exactly (day 45, both columns drop) and
misses a *mix* change entirely; a resampled set does the reverse while losing
the ability to say which record moved.

So run both. The frozen set is the regression gate; a periodic resample of live
traffic is the **check on the set**; and the number to watch is the **gap**. A
widening gap is not a quality problem, it is a representativeness problem, and
it invalidates every decision the gate made while it widened. The label-free
version: point section 3's PSI at your own eval set instead of at production.

## The experiment

```powershell
cd modules\ops-lab
python drift_lab.py      # ~5 s
```

## Boundary

- **The mix schedule and the reskill are declared.** Correctness, failure modes
  and token counts are real consequences of the fixture's provider. The
  transferable results are the *relations* — determinism vs noise floor,
  shape-proxies vs semantic degradation, input-drift recall — not the numbers.
- **Eight documents.** A real corpus has far more distributional room, so real
  PSI on real text will be noisier and the per-slice dilution effect larger, not
  smaller.
- **Temperature 0 is doing work in section 1.** A system that samples above 0
  cannot have a zero noise floor, which is an argument for pinning the seed in
  the eval path even when production samples — and for measuring the noise floor
  when you cannot.
- **No alerting policy here.** How many consecutive days, what page vs ticket,
  who owns the response — all real and all out of scope. The measurable part is
  which series can carry a decision at all.

## Cards

### 1. [decision] The daily eval is noisy. Do we grow the set or change the harness?

**Answer:** Change the harness first — it is free. A frozen set with frozen
seeds against a temperature-0 model had a day-to-day noise floor of exactly
0.0000 in the lab; resampling "today's 50 records" gave a 3.6-point standard
deviation and a 16-point worst quiet day on the same 50-record budget. Growing
the set shrinks noise as √n; removing the resampling removes it.

**Why:** Most of the day-to-day variance in a small eval is sampling variance
you introduced, not variance in the system.

**Boundary:** Determinism gains exactness and loses coverage: a frozen set
cannot see a traffic-mix change, which was the *other* real regression on this
timeline. Run a frozen gate plus a periodic resample, and watch the gap between
them. And a set with 50 records still cannot resolve a 3-point difference — see
[eval-set-sample-size.md](eval-set-sample-size.md).

**Tags:** `drift` `decision` `ai-specific`

---

### 2. [misconception] We monitor quality in production: schema-validity rate, retry rate, and mean confidence.

**Answer:** Those measure the shape of the output. In the lab a 12-point
collapse in record accuracy moved none of them by 5% — mean confidence moved
0.002 — because the degradation was semantic and the records stayed well-formed.
The only signals that responded at all compared the output against something
outside it: agreement with a rules baseline (−4.2 points where the rule can
discriminate) and the predicted event-type distribution.

**Why:** Gold-free signals can only see properties computable without a label,
and "is this the right answer" is not one of them.

**Boundary:** Shape monitors are still worth having: they run on 100% of traffic,
they are cheap, and they catch a broken deploy in minutes. They are the fast
half of a two-speed system whose slow half is a labelled eval run. Do not let
one stand in for the other.

**Tags:** `drift` `misconception` `ai-specific`

---

### 3. [failure] The holdout score has been flat for a month and users are complaining.

**Answer:** Compare the holdout's composition to this week's traffic. In the lab
the frozen set read 0.880 while live traffic read 0.770, because the set held 4%
regulation documents and production had moved to 56%. The set was measuring a
distribution that stopped arriving.

**Why:** A frozen set is frozen against the system *and* against the world. Only
the first of those is the point.

**Boundary:** The fix is not to unfreeze it — the same freeze is what let the
set detect the provider-side model change exactly and name the affected records.
Keep the gate frozen, resample a fresh set periodically as a check, alert on the
gap, and re-version the gate when the gap opens, with the changelog entry
[eval-set-versioning.md](eval-set-versioning.md) demands.

**Tags:** `drift` `failure` `ai-specific`
