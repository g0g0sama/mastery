# Groundedness: the gate, the denominator, and the unit

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** groundedness and citation accuracy (Layer 5, `-` -> Independent).
Map evidence to graduate: "Every generated claim traced to a retrieved span,
scored." Gate was `retrieval`, met by the six modules that precede this one.

> **Scope, stated up front.** Gate 2 below -- does the span actually support the
> claim -- is an entailment judgment. This lab does not make it; it stipulates a
> gold answer per atom and studies the arithmetic on top. That arithmetic holds
> whoever makes the judgment. It is not evidence that a judge *can* make it:
> [rubric-graders.md](rubric-graders.md) measured one at kappa 0.182 on borderline
> cases, and nothing here improves on that. Twelve claims, one author -- a worked
> example, not a benchmark.

---

## The problem

The cycle's `claims` field is unscored, on purpose. `policy.py` decision 5 leaves
it out because "is this claim true" needs a judge, and the judge this repo
measured was near chance on exactly the cases a judge exists to decide.

Groundedness looks like the escape. Stop asking whether the claim is true; ask
whether the retrieved document says it. That question has a document in it, so it
should be cheap. Ask for a citation with every claim, check the citations, report
the rate.

Then you have a number, and you have to decide whether it is good. And the number
turns out to have three free parameters nobody set.

## The wrong model

**"Groundedness is the fraction of claims whose citation checks out."**

Three things are unstated in that sentence, and each one moves the number enough
to change which system ships:

- **Which check.** "Checks out" collapses three independent gates: the citation
  resolves, the span supports the claim, and the span covers *all* of the claim.
  A system can pass the first two on almost everything and fail the third
  constantly.
- **Over what denominator.** Claims that were cited? Claims whose citation
  resolved? All claims emitted? A rate computed over cited claims is a rate that
  improves when the system cites less.
- **In what unit.** A claim asserting two things is "supported" the moment its
  citation covers either one. Scored whole, groundedness only ever reads high.

The tempting part is that all three defaults are the convenient ones. Resolve is
the cheapest gate, cited-claims is the smallest denominator, and the whole claim
is the unit the model emitted -- so the pipeline you build without thinking is the
one that reports the most flattering number available.

## The mechanism

Three gates, in the order a pipeline can afford them:

```text
  1. resolves   quote occurs in the cited document      string containment, free
  2. supports   the span entails the claim              needs a judge
  3. covers     every atom of the claim has a span      needs 2, plus a decomposition
```

Gate 1 is definitional, not heuristic -- the same distinction
[deterministic-graders.md](deterministic-graders.md) drew when the schema graders
scored 1.000 by construction and the plausible heuristic scored 0.074. A quote
that is not in the document is a fabricated citation by definition, with no
labelling cost and no judgment involved. It can run over all of Sinoscope today.

Gate 3 is where the unit enters. An **atom** is the smallest assertion that can
independently be true or false. "A signed with B, and the new line is 60 GWh" is
two atoms; a single citation to the first sentence supports one of them and the
whole claim scores as supported. Nothing is fabricated, nobody lied, and the
number is wrong. This is the same argument as per-field precision against
complete-record accuracy in the cycle's own metric table -- one level further
down, on the claim instead of the record.

## The experiment

`zh-retrieval-lab/grounding_lab.py`. Two systems emit the **same twelve claims**
over the same three documents and differ only in what they cite -- A cites
everything with the first span it finds, B cites only where it located the
evidence and quotes every span the claim needs. Holding the claims fixed makes
every difference in the numbers attributable to citation behaviour alone.

**Predict before running. (1) A cites all 12 claims and B cites 6. Which one
reports the higher groundedness? (2) You want to skip the judge and grade support
by lexical overlap between claim and cited span. Where do you put the threshold?
(3) The evidence for a claim exists in the document. You retrieve top-3 chunks
and it is not there. Does k=5 fix it?**

```powershell
cd modules\zh-retrieval-lab
python grounding_lab.py
```

### Gate 1 is free and it catches something

```text
system                    cited  quotes  resolve    rate   fabricated
A cite-everything            12      12       11  0.9167   K03
B cite-conservatively         6       8        8  1.0000   -
```

K03's citation is a fluent paraphrase of a sentence that exists -- 上述企业**须于**
三十日内完成**备案登记** against the document's 上述企业**需在**三十日内完成**合规备案**.
It reads correctly, it cites the right document, and it quotes text that was never
written. One `in` check, zero labels.

### Gate 2 cannot be a string metric

Bigram Jaccard between each claim and its cited span, system A, resolving
citations only:

```text
claim     jaccard   support   note
K08        0.8462        NO   one digit changed
K02        0.7826       yes
K07        0.7500       yes
K12        0.7000        NO   hedge dropped
K06        0.5161        NO   capacity atom not in the quote
K10        0.5000       yes
K09        0.5000       yes
K05        0.4062       yes
K11        0.3750        NO   second finding not in the quote
K01        0.2292        NO   second date not in the quote
K04        0.0312        NO   quote unrelated to the claim

lowest supported = 0.4062   highest unsupported = 0.8462   separable = False
```

**The most similar citation in the set is the false one.** K08's claim says the
threshold is 百分之十; the document says 百分之十五. One character, and the claim
is the highest-overlap row in the table -- above every correctly supported claim.
K12 drops 可能 and asserts what the document hedges, at 0.7000.

There is no threshold. Not a badly tuned one -- the supported and unsupported
ranges interleave, so the function does not exist. That is not an accident of this
fixture: extraction fabrications are usually a small edit to real text -- a digit,
a hedge, a negation, a swapped actor -- and a small edit is by construction
maximally similar and maximally wrong. Lexical overlap is a way to *find* the
candidate span. It is not a way to grade it.

### Gate 3, and the two numbers that flip

```text
                                    A cite-everything   B conservative
claims emitted                                     12               12
claims cited                                       12                6
claims whose citation resolves                     11                6

supported / claims that resolve                0.7273           1.0000
supported / cited claim                        0.6667           1.0000
supported / ALL claims                         0.6667           0.5000
FULLY supported / ALL claims                   0.4167           0.5000
atoms covered / ALL atoms                      0.5333           0.6000

partially supported claims: A=3  B=0
```

Read the middle three rows. On cited claims B scores a perfect 1.000 against A's
0.667. On all claims A leads, 0.667 to 0.500. **Same citations, same gold, the
winner decided by the denominator.** B did not get better at citing; it declined
to cite six claims, and two of those were claims it could have supported. A
denominator of cited claims pays a system for silence.

Now read the last row. Scored on atoms, B leads again -- 0.600 to 0.533 -- and the
entire gap between A's 0.667 and its 0.533 is three claims: K01, K06 and K11, each
asserting two things and citing a span that carries one. At claim level they are
wins. At atom level they are half-wins, which is what they are.

Two free parameters, two flips, in opposite directions. Neither number is wrong.
What is wrong is choosing one after seeing them.

### The retriever sets the ceiling

Twelve of the fifteen atoms are supportable from the documents at all. How many
sit in a chunk the retriever actually returned:

```text
  k   atoms in a retrieved chunk    rate   atoms lost
  1                            2  0.1667   K01a K01b K02a K03a K05a K06b K07a K09a K11a K11b
  3                            5  0.4167   K01a K01b K03a K06b K07a K11a K11b
  5                            5  0.4167   K01a K01b K03a K06b K07a K11a K11b
 10                            5  0.4167   K01a K01b K03a K06b K07a K11a K11b

query       candidate chunks  of  total
L1                         5  of     19
L2                         3  of     19
L3                         2  of     19
```

Raising k does nothing, and the reason is the inverted index rather than the
ranking: BM25 can only score chunks that share a term with the query, and the
【实施时间】 section shares none with 稀土出口管制. Nine of nineteen chunks are not
candidates at any k. That is [chinese-segmentation.md](chinese-segmentation.md)
and [chunking-and-metadata.md](chunking-and-metadata.md) arriving from the
grounding side: the fix for a missing span is a different analyzer, a rewritten
query, or fusion -- never a larger k.

The consequence is a ceiling. With 5 of 12 atoms retrievable, a generator that
cites perfectly still cannot ground the other 7. A groundedness score is the
product of what retrieval delivered and what the generator did with it, and only
the second is the generator's fault.

## Boundary

- **Grounded is not true.** Groundedness measures faithfulness to the retrieved
  context. Retrieve the wrong document and a perfectly grounded answer scores
  1.000 while being false. It is a generator metric; correctness needs
  [retrieval-metrics.md](retrieval-metrics.md) upstream and a label downstream.
  Never report it alone.
- **The atom decomposition is a labelling policy, not a fact.** Two labellers who
  split a claim differently produce different denominators and non-comparable
  scores. Write the splitting rule into the policy and fingerprint it with the
  behavioural hash from [eval-set-versioning.md](eval-set-versioning.md) -- this is
  precisely the class of change that moves a score without touching the system.
- **Containment is a fragile resolve check.** It breaks on whitespace,
  full-width/half-width digits, and any model that "quotes" with tidied
  punctuation. Have extraction emit character offsets at the moment it cites, and
  verify the offsets; re-finding the string later is a check on the string
  normalizer as much as on the model.
- **A single citation field cannot express K06.** Its two atoms live in different
  sections. If the schema allows one span per claim, coverage is capped below 1.0
  by the schema and no prompt fixes it. Make it a list, one entry per atom.
- **Gate 1 can gate; gate 2 cannot.** Resolve is definitional and safe to enforce
  in the pipeline. Support is a judgment with a measured error rate, and
  [eval-gates.md](eval-gates.md)'s rule applies -- never route a review queue on an
  unmeasured grader.

## What this changes in Sinoscope

`claims` does not have to stay unscored. Split it: attributability -- a citation
exists, resolves, and carries offsets -- is deterministic and shippable now, over
the whole corpus, gold-free. Only entailment goes to a judge, on the residue, with
its own agreement sample. The field goes from unmeasurable to partly measured
without waiting for a judge anyone trusts.

## Cards

### 1. [decision] Two extraction systems emit the same 12 claims. A cites all 12 and 8 are supported; B cites 6 and all 6 are supported. Which is more grounded?

**Answer:** Unanswerable until you state whether an uncited claim counts as a
failure. Over cited claims B wins 1.000 to 0.667; over all claims emitted A wins
0.667 to 0.500. The denominator picks the winner, not the citations.

**Why:** A rate computed over cited claims has the system's own abstention in its
denominator, so declining to cite raises the score. B left two supportable claims
uncited and was rewarded for it.

**Boundary:** Choose the denominator from the decision the number will drive, and
write it down before running. If an uncited claim cannot enter the record, the
denominator is all claims and uncited is ungrounded.

**Tags:** `groundedness` `decision` `general-principle`

---

### 2. [mechanism] Groundedness scored on whole claims and on atomic assertions gives different numbers. Which is higher, and why is the direction always the same?

**Answer:** Whole-claim is always the higher of the two. A claim asserting several
things is marked supported as soon as its citation covers **any** one of them, so
partial coverage is rounded up to a full win.

**Why:** In the lab, three of twelve claims assert two things and cite a span
carrying one. That alone is the whole gap: 0.667 at claim level against 0.533 at
atom level, with nothing fabricated and no citation wrong.

**Boundary:** The decomposition into atoms is itself a labelling policy -- two
labellers splitting differently produce non-comparable denominators -- so version
the splitting rule alongside the gold.

**Tags:** `groundedness` `mechanism` `general-principle`

---

### 3. [failure] To avoid an LLM judge, you grade citation support by lexical overlap between the claim and its cited span. What class of error does this systematically miss?

**Answer:** The small edit -- a changed digit, a dropped hedge, an inserted
negation. Those produce the *highest* overlap scores in the set while being false,
so no threshold separates supported from unsupported.

**Why:** Measured on this lab's 11 resolving citations, the top-scoring row
(0.8462) is a claim that changed 百分之十五 to 百分之十, above every correctly
supported claim; the lowest correctly supported scored 0.4062. The ranges
interleave, so the separating function does not exist rather than being mistuned.

**Boundary:** Overlap is still the right tool for *locating* a candidate span, and
string containment is still a valid check that a quote is not fabricated. Neither
is a check that the span supports the claim.

**Tags:** `groundedness` `failure` `general-principle`
