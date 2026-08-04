# Scoring an extraction set

> **Source status.** This is synthesis, not a summary of a source. The three
> primary sources named in `current-cycle.md` -- your provider's structured-output
> reference, your provider's evaluation guidance, and one primary treatment of
> annotation quality -- are unread here and are yours to read. Where this document
> and a provider reference disagree about what the API does, the reference wins;
> where they disagree about what a metric means, check whether you are using the
> same denominator. Everything below is general principle and holds across
> providers. The concrete numbers are computed by `lab/`, and you can reproduce
> every one of them.

## The problem

You have two extraction systems and a weekend to choose one.

System A scores 0.870 F1 on `actors`. System B scores 0.878. Both are 100%
schema-valid. Both get exactly half of the records completely right. On every
number you have, they are the same system, and B is fractionally ahead.

They are not the same system. A invents three actors that appear in no document.
B silently drops five that do. Ship A and your database fills with people who
were never there, at a rate no query will reveal, because a fabricated actor
looks exactly like a real one. Ship B and your coverage is quietly 22% lower than
your dashboard claims, which you will discover when an analyst asks why a company
they read about this morning is not in the system.

Those are opposite failures with opposite fixes, and F1 rated them equivalent.
This is not a flaw in F1. It is what happens when a single number is asked to
carry a decision it does not contain.

## The obvious fix, and why it fails

The obvious fix is more labels. Get to 500 records, the reasoning goes, and the
noise averages out.

Follow it. At 500 records A scores 0.871 and B scores 0.877. The gap is now
statistically solid and still means nothing, because the problem was never
sample size. F1 pools false positives and false negatives into one number by
construction. A larger sample estimates that number more precisely. It does not
make it a different number.

The second obvious fix is to look at the errors. Also right, also insufficient
on its own: with no policy written down, two people reading the same 30 errors
will disagree about a third of them, and neither disagreement gets recorded.

What actually separates A from B is already in the arithmetic, one level below
the headline. A: `tp=20, fp=3, fn=3`. B: `tp=18, fp=0, fn=5`. Same F1, different
systems, visible the moment you stop collapsing the counts. Everything in this
document is a way of not collapsing them.

## The mechanism

### 1. The policy is the instrument, and it is a person's opinion

Before any score exists, someone decided what counts as a match. Does `华为`
match `华为技术有限公司`? Does `福建省宁德市` match `宁德`? Does an ISO datetime
match an ISO date?

Each answer moves the score without moving the system. In `lab/break_it.py`,
replacing the normalizers with `str.strip()` -- no label changes, no prediction
changes, no extractor code changes -- moves `model_a`'s location F1 from 1.0000
to 0.5000 and `model_b`'s from 0.9565 to 0.7826, **inverting which system is
better on that field**. The instrument alone decided the winner.

So the policy is written down, versioned next to the labels, and states its
costs. This lab's policy refuses to strip legal-form suffixes, because merging
`华为` and `华为技术有限公司` merges legally distinct entities; the price is a
systematically pessimistic `actors` recall, and that measured ceiling is the
argument for building entity linking later.

A corollary that costs people whole sets: **store gold raw and normalize at
scoring time, on both sides.** Normalize on the way in and you cannot re-score
when the policy changes, and the policy always changes.

### 2. Schema validity is a gate, not a quality metric

Validity answers "can this be stored", nothing more. It rises to 100% under any
constrained-decoding feature while content quality does whatever it likes.

Worse, the schema and the policy are different contracts and the schema is
usually looser. The lab's schema accepts an ISO datetime; the policy requires a
date, because the gold records only the granularity the source supplied. When
`model_b` starts emitting `2026-03-14T00:00:00`, its time F1 goes to **0.0000
while validity holds at 1.0000**. A field at exactly zero with validity intact is
almost never a model that got everything wrong -- it is a producer and a match
rule that stopped agreeing on a representation.

The other half of the gate is the denominator. Invalid records are excluded from
per-field scoring, so a system that fails structurally on its hardest documents
scores better on what remains. The lab's rules baseline reports location F1 of
**1.0000** -- on `n_scored = 10`, having dropped the only two records on which
its location was wrong. A field score without its `n_scored` beside it is not a
result.

### 3. Set-valued precision and recall, and the one trick

`actors` is a list; `event_type` is a single value. Rather than two code paths,
treat a scalar as a set of size 0 or 1. Precision and recall are then defined
identically for both, and "predicted nothing" stops being a division by zero:

```text
tp = |gold & pred|    fp = |pred - gold|    fn = |gold - pred|
```

Read the four corners, because they are the whole vocabulary of extraction error:

| gold | pred | counts | what happened |
|---|---|---|---|
| {A,B} | {A,C} | 1/1/1 | one found, one invented, one missed |
| {A} | {} | 0/0/1 | omission |
| {} | {A} | 0/1/0 | invention |
| {} | {} | 0/0/0 | correct silence, and invisible to every metric |

That last row matters more than it looks. Correctly declining to answer earns
nothing, so a system rewarded only by recall learns to guess.

### 4. Micro and macro answer different questions

Micro pools the counts, then computes once: every **extracted item** weighs the
same, so a document with seven actors counts seven times a document with one.
Macro computes per record, then averages: every **document** weighs the same.

They diverge exactly where your data has a long tail. The lab's rules baseline
scores micro recall 0.5263 and macro recall 0.6786 on `actors` -- a 15-point gap
with a single cause, one document containing seven actors of which a
headline-built dictionary knows two. Micro says the system misses half of all
actors. Macro says it handles two thirds of documents well. Both are true and
they answer different product questions.

Macro also carries a convention worth knowing before someone else reports it at
you: precision on a record where nothing was predicted is conventionally 1.0
(it is 0/0). The lab's rules baseline therefore posts an `event_type` **macro
precision of 1.0000 on a system that never predicts `event_type` at all.** Macro
precision rewards abstention. Never report it alone for a system that can decline.

### 5. Empty versus wrong

Split every record-field three ways: `correct`, `empty` (predicted nothing, gold
had something), `wrong` (anything else). This is what separates the confabulator
from the abstainer -- in the lab, `model_a` posts `9/0/3` on actors and `model_b`
posts `9/1/2`, and the `fp` counts underneath say the rest.

Note the coarseness you are buying: a partially recovered list of seven lands in
`wrong` next to a confident fabrication. The split classifies fields; the counts
classify items. Keep both.

### 6. Complete-record accuracy is the brutal one

Four fields at ~0.9 F1 do not give a 0.9 acceptance rate. They give roughly
`0.9^4 ~ 0.66`, and in the lab, **0.5**. That is the number that answers "would a
human accept this record", and it is the one to compute over the *full*
denominator, invalid records included, because a record you cannot store is not
half-acceptable.

It is also nearly useless for diagnosis. Under the locale break, record accuracy
halves for all three systems and points at nothing; the per-field row that
collapsed says which file to open. Report both, and never only one.

### 7. Cost per accepted record

The denominator is accepted records, not calls. The lab's rules baseline costs
$0.00 per document and its cost per accepted record is undefined, because it
accepted nothing. Cost per call would have ranked it first.

### 8. The holdout is spent by looking

A holdout you have inspected is a dev set. There is no partial credit: you cannot
look at ten of its records and keep the other forty clean, because what you
learned from the ten changes what you build for all fifty. Freeze it, label it
blind, score against it once, and record the date you spent it.

## Boundaries and cost

- Everything here needs an **exact-match rule**. It does not extend to free text.
  `claims` is in the schema and absent from the score, deliberately, because it
  needs a rubric grader -- and a field present in the schema and missing from the
  score must be written down, since silence reads as "this field is fine".
- **Fifty records is not a benchmark.** It is enough to catch a broken field and
  far too few to resolve a 3-point difference. Bootstrap an interval before you
  believe a small gain.
- A **closed vocabulary** is scoreable today and wrong at the edges. The
  violation log is the backlog for vocabulary v2, not a list of model failures.
- All of this measures agreement with your labels, and **your labels are one
  person's opinion** until a second labeller has scored some of them. Agreement
  on ten records tells you whether the policy is written clearly enough to be
  worth fifty.

## Failure modes in production

**A metric moves and no code changed.** Suspect the policy first: a normalizer,
the vocabulary, a match rule. Diff the policy file before the extractor.

**A field reads exactly 0.0 with validity at 100%.** A representation change, not
a quality collapse. Dates gaining a time component; a list arriving as a
comma-joined string; identifiers gaining a prefix.

**Scores improve and complaints do not.** Check `n_scored`. Something began
failing validation and left the denominator.

**The dashboard is flat and analysts report missing entities.** Watch recall and
the empty-vs-wrong split, not F1. An abstaining regression is invisible to
precision and to record accuracy on the records it still answers.

**Every number improved after a prompt change.** Check whether the holdout was
used during iteration. Gains that only exist on the set you were watching are
the normal outcome, not the suspicious one.

## What to remember

1. The matching policy is a person's decision with a cost, and it moves the score
   without touching the system. Version it next to the labels; normalize at
   scoring time, on both sides.
2. Schema validity is a gate. It is blind to any error the storage type permits,
   and it silently edits the denominator of every field score.
3. Scalars are sets of size 0 or 1; `tp/fp/fn` is what separates invention from
   omission after F1 has hidden the difference.
4. Micro weighs items, macro weighs documents. They disagree wherever the data
   has a long tail, and macro precision rewards abstention.
5. Complete-record accuracy is the acceptance rate and is brutal by construction
   -- four fields at 0.9 give 0.5. It ranks systems; per-field scores locate the
   bug. Cost is per accepted record, never per call.
