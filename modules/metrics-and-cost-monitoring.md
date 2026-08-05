# Metrics and cost monitoring

**Micro module.** One mechanism, one experiment, three cards. Runs against
[ops-lab/](ops-lab/).

**Capability:** Metrics and cost monitoring (Layer 9, - -> Independent). Map
evidence: "Cost per task on a dashboard, alerting on drift."

---

## The problem

The map row has two halves and the second one is the hard one. Computing cost
per task is arithmetic. Putting an *alarm* on it means choosing a series, a
detector and a threshold, and each choice has a failure mode that only shows up
against a year of data with a real regression in it.

## The mechanism

**Three denominators, three different answers.** Same spend, four releases:

```text
release              requests    $ / call    $ / stored record   $ / correct record
r1 (free)            1500        $0.00118    $0.00121            $0.00140
r2 (free)            1500        $0.00124    $0.00126            $0.00140
r3 (constrained)     1500        $0.00123    $0.00124            $0.00144
r4 (free)            1500        $0.00124    $0.00128            $0.00160
```

Constrained decoding stores nearly everything, which improves the middle column
by construction and makes the right-hand column *worse* — the finding
[structured-outputs.md](structured-outputs.md) measured as quality, arriving
here as money. A stored record that is wrong is not output; it is work someone
redoes plus a row that has to be found again.

**The aggregate moves on its own.** Two slices behind a routing rule, identical
releases before and after:

```text
slice                   share before    share after     $ / correct
routine -> mid-1        70%             38%             $0.00140
complex -> large-1      30%             62%             $0.00631
ALL TRAFFIC             100%            100%            $0.00288 -> $0.00445

aggregate cost per correct record: +54.7%
```

Neither slice moved by a cent. Same models, same prompts, same code — a customer
segment grew. It runs the other way just as easily, and that one is worse: a
real improvement inside every slice, invisible because the mix moved against it.
An aggregate unit cost is a weighted average whose weights nobody is watching.
Alert on the slices, report the aggregate, and put volume-by-slice on the same
dashboard.

**What failures cost, which is not zero:**

```text
what the money bought             spend         share
stored and correct                $3.26         87.8%
stored but wrong                  $0.39         10.5%
schema-invalid output             $0.06          1.6%
provider errors (all attempts)    $0.01          0.1%

requests that needed more than one attempt: 141 (4.7%)
share of spend that produced no usable record: 12.2%
```

A failed call is billed for its input tokens; a retried call is billed twice for
them; and a response that fails validation is billed in full in both directions
while *looking* like success. The interesting ratio is the gap between the first
row and the total — the fraction of the bill attributable to output a human
would accept. That is the number that makes a cheaper model with a lower accept
rate lose an argument it wins on the price sheet.

**Four detectors, 120 days, one real regression on day 90:**

```text
detector on TOTAL SPEND               false alarms  detection     false alarm days
static threshold (+25% of baseline)   1             15 d          44
day-over-day > 25%                    12            1 d           7, 14, 21, 28, 35, 42
EWMA z > 3, raw series                0             never         -
EWMA z > 3, seasonally adjusted       0             15 d          -
```

The day-over-day detector is the one everybody builds first and it fires every
Monday — twelve false alarms, all on one weekday, because a 2x jump from Sunday
is the week starting. Its false alarms are not noise, they are seasonality, and
they arrive on a schedule that trains people to ignore the alert.

Its apparent 1-day detection is the part worth keeping: day 91 is a Monday. **A
detector that alarms every Monday will always appear to catch a Monday
regression.** A detection delay measured against a detector with a 17% base rate
is not evidence of anything, and that arithmetic is behind every "our alert
caught it" story where nobody checked the false-alarm rate.

**And the incident none of them could see.** The 35% unit-cost regression landed
in the same week as a 28% volume drop:

```text
factor                before        after         change
volume                7,196         5,557         -22.8%
cost per record       $0.00140      $0.00189      +35.1%
total (product)       $10.04        $10.48         +4.3%
```

```text
detector on $ / RECORD                false alarms  detection
static threshold (+25% of baseline)   0             0 d
day-over-day > 25%                    0             0 d
EWMA z > 3, raw series                0             0 d
EWMA z > 3, seasonally adjusted       0             never
```

Same four detectors, same code, different series. The unit metric has no
seasonality to fight — cost per record does not care that it is Sunday — so the
detector that was drowning in Mondays becomes usable and the step is visible the
day it lands. The last row is the mirror-image lesson: seasonal adjustment
applied to a series that has no seasonality inflates the baseline variance and
blinds the detector.

**Alert on rates and ratios; report totals.** A total is the product of a
business quantity and an engineering quantity, and an alarm on a product cannot
say which factor moved — or notice when they move in opposite directions.

## The experiment

```powershell
cd modules\ops-lab
python cost_lab.py      # ~2 s
```

## Boundary

- **Volumes, seasonality, the regression and the outage are declared.** The
  token counts, costs and accept rates are real consequences of the fixture's
  provider. The transferable content is the shape of each detector's failure,
  not the detection delays.
- **Four detectors is not a survey.** No changepoint detection, no STL
  decomposition, no forecast-residual monitoring. What the four demonstrate is
  that the *series* choice dominates the detector choice, which stays true with
  better detectors.
- **Cost per correct record needs labels**, which production does not have. In
  practice the deployed proxy is cost per *accepted* record — schema-valid,
  passing gold-free graders, not retried — and the gap between that proxy and
  the labelled number is itself a thing to measure. See
  [deterministic-graders.md](deterministic-graders.md).
- **Prices here are per-token list prices.** Cached input, batch discounts,
  committed-use contracts and rate-limit tiers all change the arithmetic and
  none of them changes the denominator argument.

## Cards

### 1. [decision] Which cost number goes on the dashboard?

**Answer:** Cost per *successful* task, sliced, with the volume of each slice
beside it. In the lab, cost per call, cost per stored record and cost per
correct record named different winners, and constrained decoding improved the
middle one by construction while making the right one worse. Then the aggregate
moved +54.7% with no slice moving at all, because the mix shifted.

**Why:** Cost is spend divided by work delivered, a wrong record is not work
delivered, and any aggregate over heterogeneous slices is a weighted average.

**Boundary:** "Successful" needs a definition you can compute without labels in
production — schema-valid, ungraded-failure-free, not retried — and the drift
between that proxy and the labelled accept rate is its own metric. Cost per 1M
successful queries is the same argument from Layer 8; see
[benchmark-methodology.md](benchmark-methodology.md).

**Tags:** `monitoring` `decision` `general-principle`

---

### 2. [failure] The cost alert never fired, and the monthly bill was 35% higher per record.

**Answer:** Check whether the denominator moved. In the lab a 35% unit-cost
regression coincided with a 28% volume drop and total spend rose 4.3% — under
every threshold. The same four detectors on cost *per record* caught it the day
it landed with zero false alarms.

**Why:** Total spend is the product of a business quantity and an engineering
quantity. An alarm on the product cannot separate them, and they can cancel.

**Boundary:** Unit metrics are not automatically better: seasonal adjustment
applied to the unit series (which has no seasonality) blinded that detector
entirely. Match the transform to the series, and check the false-alarm rate on
a year of history before trusting a detection delay.

**Tags:** `monitoring` `failure` `general-principle`

---

### 3. [misconception] A day-over-day change alert is a reasonable first cost monitor.

**Answer:** On a seasonal series it is an alarm clock. In the lab it fired 12
times in 90 quiet days, every one of them a Monday, because weekend traffic is
half of weekday traffic. Worse, its "1-day detection" of the real regression was
also a Monday — the same alarm it fires every week.

**Why:** Day-over-day differencing removes trend and amplifies weekly
seasonality, so its false alarms are periodic and predictable, which is exactly
what makes people mute it.

**Boundary:** Day-over-day is fine on a series without weekly structure — cost
per record, accept rate, tokens per record. The fix on a seasonal series is
week-over-week or an explicit seasonal adjustment, and either way the number to
report alongside detection delay is the false-alarm count on quiet history.

**Tags:** `monitoring` `misconception` `general-principle`
