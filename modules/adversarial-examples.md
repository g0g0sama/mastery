# Adversarial and negative examples

**Micro module.** One mechanism, one experiment, three cards. Serves steps 3-4
of [../current-cycle.md](../current-cycle.md) -- the records you choose *before*
labelling 50.

**Capability:** adversarial and negative examples (Layer 5, - -> Independent).
Map evidence to graduate: "Cases that break your current system, in the set,
failing."

---

## The problem

You sampled 50 documents at random from your corpus and labelled them. The set is
representative, which is what you wanted, and it has a property you did not
intend: **it cannot fail your system in any way that surprises you.** A random
sample of typical documents measures typical performance, and typical performance
is the thing you already knew.

## The wrong model

**"Adversarial examples are the hard ones."**

Hard-but-randomly-chosen is just more of the same distribution, sampled from its
tail. An adversarial example is one you chose because you have a **hypothesis
about a specific failure** -- "this system cannot decline", "this system confuses
one-character-different company names", "this system takes the first date it
sees". The hypothesis is the work. Without one, you are collecting difficulty,
not information.

The costlier omission is quieter. **Negative examples** -- documents where the
correct output is *nothing* -- are almost never in a set built by sampling
documents that have events in them. If every record in your set contains an
event, a system that always emits an event scores perfectly on abstention you
never tested, and you learn that it cannot abstain in production, from an
analyst.

## The mechanism

Four kinds, each written from a hypothesis:

| Kind | Hypothesis it tests | The failure it exposes |
|---|---|---|
| **Negative** | can the system emit nothing? | fabrication on empty input |
| **Near-miss** | does the match rule hold under confusable inputs? | precision collapse on similar entities |
| **Distractor** | does the system pick the right one of several candidates? | first-match heuristics |
| **Out-of-vocabulary** | what happens past the closed set's edge? | forcing a wrong label to satisfy a schema |

Note what the negative case does to your metrics. Both sides empty scores
`0/0/0` -- invisible to precision, recall, and F1, and visible **only** in
complete-record accuracy. If you have negatives in the set and are watching F1,
you have paid for them and are not reading them.

## The experiment

`extraction-eval-sets/lab/adversarial.py`. Requires all five lab tasks.

Four records added to the 12: N1 negative (market commentary, no event), N2
near-miss (中国石油 against 中国石化, one character apart), N3 distractor (a 2019
precedent cited before the 2026 event), N4 out-of-vocabulary (a product recall,
absent from `EVENT_TYPES`).

On the base set, `model_a` and `model_b` have identical record accuracy of
0.5000.

**Predict before running: their record accuracy after adding these four, and how
many of the four each accepts.**

```powershell
cd modules\extraction-eval-sets\lab
python adversarial.py
```

Actual:

```text
system   metric            12 typical  +4 adversarial    delta
model_a  record accuracy       0.5000          0.3750  -0.1250
model_b  record accuracy       0.5000          0.6250  +0.1250

            N1 negative   N2 confusable  N3 distractor  N4 out-of-vocab
rules          REJECTED        REJECTED       REJECTED         accepted
model_a        REJECTED        REJECTED       REJECTED         REJECTED
model_b        accepted        accepted       accepted         accepted
```

Four records open a 25-point gap between two systems the base set called
identical, and they reverse which one you would ship. `model_a` fails all four;
`model_b` passes all four.

Three things in that output are worth more than the headline.

**`model_b`'s scores went up.** These records are adversarial *for the
confabulator* and confirmatory for the abstainer -- N1 is the first record in the
set where declining to answer was the correct answer, so it is the first time
`model_b`'s defining behaviour earned anything. Adversarial is relative to a
system and a hypothesis, never a property of a document.

**The rules baseline accepts N4**, the out-of-vocabulary event, because it never
predicts `event_type` at all and the gold label for an out-of-vocabulary event is
`None`. A stopped clock. Read it as a warning about single-record evidence, not
as a point for the baseline.

**Four records moved record accuracy by 12.5 points**, which is larger than the
gap the whole 12-record set could resolve. Deliberately chosen records buy more
discriminating power per label than random ones -- and they buy it by making the
set unrepresentative, which is the trade in the next section.

## Boundary

- **An adversarial set is not a representative set.** Once you add these, your
  headline number no longer estimates production performance. Keep them as a
  separate scored slice with its own name, or your F1 becomes a number about your
  imagination.
- Adversarial cases go **stale**. Each one exists because a system failed it;
  once fixed, it becomes a regression test rather than a discovery tool, and you
  need new hypotheses.
- Do not let them dominate. A handful of hypothesis-driven records against a
  representative base is the shape; a set that is mostly adversarial optimizes a
  system for a distribution nobody sends you.
- Write the hypothesis **next to each record**, in the set. A year later, an
  adversarial record with no recorded hypothesis is indistinguishable from a
  labelling mistake, and someone will delete it.

## Cards

### 1. [misconception] What makes an eval record adversarial?

**Answer:** That it was chosen to test a specific hypothesis about how the system
fails -- not that it is difficult.

**Why:** Hard-but-randomly-sampled records are just the tail of the same
distribution and tell you what you already knew. The hypothesis is what converts
a record into information.

**Boundary:** Adversarial is relative to a system. The same four records that
broke a fabricating extractor confirmed an abstaining one and *raised* its
scores.

**Tags:** `eval-sets` `misconception` `general-principle`

---

### 2. [failure] Your eval set is built by sampling documents that contain events. Which system behaviour is structurally unmeasurable, and how does it surface?

**Answer:** Abstention. With no negative examples -- documents where the correct
output is nothing -- a system that always emits an event is never penalized for
being unable to stay silent.

**Why:** Every record rewards producing output, so fabrication and correct
extraction are indistinguishable in the aggregate. It surfaces in production as
events that no document supports.

**Boundary:** Adding negatives is necessary but not sufficient to see the fix:
both sides empty scores `0/0/0`, invisible to precision, recall and F1, and
visible only in complete-record accuracy.

**Tags:** `eval-sets` `failure` `general-principle`

---

### 3. [decision] You add 12 hypothesis-driven adversarial records to a 50-record representative set. How should they be scored and reported?

**Answer:** As a separate named slice, with its own numbers, not merged into the
headline metric.

**Why:** Adversarial records are deliberately unrepresentative, so merging them
makes the headline stop estimating production performance -- it becomes a number
about which failures you happened to imagine.

**Boundary:** Record the hypothesis beside each one. An adversarial record whose
rationale was not written down is indistinguishable from a labelling error later,
and will be deleted by someone tidying up.

**Tags:** `eval-sets` `decision` `general-principle`
