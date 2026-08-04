# Inter-annotator agreement

**Micro module.** One mechanism, one experiment, three cards. Serves steps 2-3
of [../current-cycle.md](../current-cycle.md) and its second open question
("is there a second labeller available for even 10 records?").

**Capability:** building a labelled eval set (Layer 5). Not a separate cycle.

---

## The problem

You wrote a labelling policy, labelled 50 records, and want to know whether the
policy is written clearly enough that the set means anything. So you get a second
person to label 20 of them and compare. They agree on 17. Eighty-five percent --
good enough, ship it.

It is not good enough, and 85% is not the number you think it is.

## The wrong model

**"Agreement is the fraction of items two labellers assign the same label."**

Tempting because it is literally true and trivially computable. It fails because
two labellers who both say "yes" to almost everything will agree at a high rate
*by construction*, whether or not they understand the policy or each other. On a
decision where 85% of items are genuinely "yes", two people flipping weighted
coins independently agree about 74% of the time. Your 85% is buying you eleven
points over noise, and the raw number never shows you that.

The failure mode is specific: a skewed label distribution inflates raw agreement.
Extraction scope decisions are almost always skewed -- most candidate mentions
really are in scope -- so this is the normal case, not the edge case.

## The mechanism

Cohen's kappa removes the agreement you would expect from chance alone:

```text
kappa = (po - pe) / (1 - pe)

po = observed agreement
pe = agreement expected if both labellers assigned labels independently,
     each at their own observed base rate
```

For a binary decision with cells `a` (both yes), `b` (A only), `c` (B only),
`d` (both no), over `n` items:

```text
po = (a + d) / n
pe = ((a+b)(a+c) + (c+d)(b+d)) / n^2
```

The denominator `1 - pe` is the headroom -- the agreement that was actually
available to earn. Kappa is the fraction of that headroom you captured. It is
1.0 for perfect agreement, 0.0 for chance, and negative for systematic
disagreement.

Rough reading, and it is a convention rather than a law: below 0.4 the policy is
not written clearly enough to label against; 0.4-0.6 means the disagreements are
concentrated in cases the policy does not cover; above 0.8 the policy is doing
its job.

## The experiment

`extraction-eval-sets/lab/kappa.py`. Standalone -- it needs nothing from the lab
stubs.

Twenty candidate actor mentions, two labellers, one binary in-scope decision
each. Raw agreement is 17/20.

**Predict before running: what is kappa?** Write the number down.

```powershell
cd modules\extraction-eval-sets\lab
python kappa.py
```

Actual:

```text
n = 20   both-yes 15  A-only 2  B-only 1  both-no 2
A said in-scope 17/20, B said in-scope 16/20

raw agreement      po = 0.8500
chance agreement   pe = 0.7100
Cohen's kappa         = 0.4828
```

Eighty-five percent agreement is kappa 0.48. Of the 29 points of headroom above
chance, the two labellers captured 14.

Now read the three disagreements the script prints, because they are the actual
product of this exercise:

```text
R01 parent group in the byline    A=yes B=no
R05 rotating chairman by name     A=no  B=yes
R07 plant, not the operator       A=yes B=no
```

Those are not careless errors. They are three questions the policy never answered
-- does a parent company count, does a named person count, does a facility count
-- and each one gets a sentence in the policy. That is the deliverable. Kappa
told you to look; the disagreements told you what to write.

## Boundary

- Kappa is for **categorical** decisions by **two** labellers. Three or more
  wants Fleiss' kappa; ordered ratings want a weighted kappa, because "off by
  one grade" should not cost the same as "opposite".
- Kappa is depressed by skew as well as inflated by it -- with 98% of items in
  one class, kappa can be low even when both labellers are excellent. Report the
  marginals (`A said in-scope 17/20`) beside it so the reader can see the skew.
- It measures **agreement, not correctness**. Two labellers sharing the same
  misreading of the policy score 1.0.
- Twenty items gives a very wide interval on kappa itself. Treat it as a smoke
  test of the policy, not as a measurement.

## Cards

### 1. [misconception] Two labellers agree on 17 of 20 in-scope decisions. Is 85% agreement good evidence that the labelling policy is clear?

**Answer:** No. On a skewed decision -- and scope decisions usually are -- most
of that 85% is chance. In this module's data it works out to kappa 0.48.

**Why:** Raw agreement does not subtract the agreement two independent labellers
would reach anyway from their base rates. Here `pe` was 0.71, so only 29 points
of agreement were available to earn and they captured 14.

**Boundary:** Report the marginals alongside kappa. Kappa is depressed by extreme
skew as well as inflated by moderate skew, so neither number is readable alone.

**Tags:** `eval-sets` `misconception` `general-principle`

---

### 2. [mechanism] What do the numerator and denominator of Cohen's kappa each represent?

**Answer:** `kappa = (po - pe) / (1 - pe)`. The numerator is agreement earned
above chance; the denominator is the agreement that was available to earn.

**Why:** Expressing it as a fraction of available headroom makes kappa comparable
across decisions with different base rates, which raw agreement is not.

**Boundary:** Two labellers who share the same misreading of the policy score
1.0. Kappa measures agreement, never correctness.

**Tags:** `eval-sets` `mechanism` `general-principle`

---

### 3. [best-practice] After a two-labeller agreement check, what is the actual deliverable?

**Answer:** The list of disagreements, converted into new sentences in the
labelling policy -- not the kappa value.

**Why:** Each disagreement is a case the policy failed to cover. Kappa tells you
whether to look; the disagreements tell you what to write, and the policy is the
artifact that outlives the numbers.

**Boundary:** Do this before labelling the bulk of the set. A policy clarified
after 50 records means the first 50 were labelled under a different instrument
and have to be re-checked.

**Tags:** `eval-sets` `best-practice` `general-principle`
