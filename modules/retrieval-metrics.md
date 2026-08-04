# Retrieval metrics: recall@k, MRR, nDCG

**Micro module.** One mechanism, one experiment, three cards.

**Capability:** retrieval metrics (Layer 5, Aware -> Independent). Map evidence
to graduate: "Ranked judgments on Chinese queries, scores reproducible."

Deliberately **before** any retrieval work. The map's own sequencing note says
evaluation before retrieval: building HNSW intuition before you can measure
recall means you will not know whether the index helped.

---

## The problem

You have two retrievers and the same five Chinese queries. Both find every
relevant document within the top 10. Recall says they are identical.

They are not remotely identical. One puts a merely-related document at rank 1 and
the document that actually answers the query at rank 8. The other leads with the
document that answers the query. For anything a person reads, or anything you
feed into a context window with a budget, that is the whole difference -- and
recall@10 cannot see it, because recall does not know what order is.

## The wrong model

**"Retrieval quality is recall: did we find the relevant documents."**

True and insufficient the moment anything downstream consumes a *prefix* of the
list -- a reader who checks three results, a reranker over the top 20, a prompt
that fits eight chunks. Then position is quality, and a set-based metric is
blind to it.

The correction people reach for next is MRR, and it introduces its own blind
spot: MRR looks only at the **first** relevant result and does not care how
relevant it was, or what follows. A system that surfaces something marginally
related at rank 1 scores a perfect 1.0.

## The mechanism

Four metrics, and what each is structurally unable to see:

| Metric | Question | Blind to |
|---|---|---|
| **recall@k** | did we retrieve them at all | order, and grade |
| **precision@k** | how much of the top-k is worth reading | what we missed |
| **MRR** | how fast to the first useful result | grade, and everything after the first hit |
| **nDCG@k** | is the ranking well-ordered by usefulness | absolute cost; harder to explain to a stakeholder |

nDCG is the only one that uses **graded** relevance. Gain per document is
`2^grade - 1`, discounted by `log2(rank + 1)`, normalized by the best possible
ordering -- so a grade-2 document at rank 2 beats a grade-1 at rank 1, and moving
a good result from rank 8 to rank 2 shows up.

Graded judgments are the prerequisite. Binary relevance throws away the
distinction between "answers the query" and "related and useful", and once
thrown away, nDCG has nothing to work with.

## The experiment

`extraction-eval-sets/lab/ranking.py`. Standalone -- pure arithmetic over ranked
lists and graded judgments, no retriever and no index. Six Chinese queries,
graded 2 / 1 / absent. Constructed fixture.

`system_a` surfaces *a* relevant document at rank 1 and the best one late.
`system_b` has nothing at rank 1 and the best document at rank 2.

**Predict before running: which system wins on recall@10, on MRR, and on
nDCG@10.**

```powershell
cd modules\extraction-eval-sets\lab
python ranking.py
```

Actual:

```text
AGGREGATE             system         R@3   R@10    P@3    MRR  nDCG@10
(Q6 excluded)         system_a     0.400  1.000  0.278  1.000    0.527
(Q6 excluded)         system_b     0.400  1.000  0.278  0.500    0.634
```

Same rankings, three different winners. Recall and precision call it a **tie**.
MRR says `system_a` by a factor of two. nDCG says `system_b` by 10 points. Every
one of those numbers is correctly computed.

Which is right depends entirely on what consumes the list. If a human reads until
they find anything useful, `system_a` genuinely is better. If a reranker takes
the top 5, or a prompt takes the top 3 and you need the *best* document in there,
`system_b` is better and MRR actively misled you.

Q6 is the edge case worth having in the set: a query with no relevant document in
the corpus. Reciprocal rank is undefined -- there is no rank to take the
reciprocal of -- and the convention you pick moves the headline:

```text
(Q6 excluded)   system_a MRR 1.000    (Q6 scored 0)   system_a MRR 0.833
(Q6 excluded)   system_b MRR 0.500    (Q6 scored 0)   system_b MRR 0.417
```

Same shape as the macro-precision convention in the main module: a `0/0` that
somebody has to decide, silently changing a headline. Write which convention you
chose next to the number.

## Boundary

- All of this assumes **judged** documents. Anything unjudged is scored as
  irrelevant, so a retriever that finds good documents your pooling never showed
  a judge is punished for it. Report judgment coverage beside recall.
- `@k` must match a real downstream constraint -- the reranker's input size, the
  context budget, the number of results a person actually reads. A `k` chosen
  because it is round measures nothing in particular.
- Graded judgments cost more than binary ones and are less consistent between
  labellers. Run the agreement check on grades before trusting nDCG --
  [inter-annotator-agreement.md](inter-annotator-agreement.md).
- Five queries resolve nothing small. Query-level variance is large, and query
  count is the sample size here -- [eval-set-sample-size.md](eval-set-sample-size.md)
  applies with queries as the resampling unit.
- For Chinese specifically, the judgments are entangled with segmentation and
  analyzer choices. That is Layer 6 and a later cycle; do not let it block
  building the judgments now.

## Cards

### 1. [comparison] Two retrievers return every relevant document in the top 10 for every query. Which metrics can still distinguish them, and which cannot?

**Answer:** recall@10 and precision@10 cannot -- they are set metrics and both
sets are identical. MRR and nDCG@k can, because both are functions of position.

**Why:** Order only becomes quality when something downstream consumes a prefix:
a reader who stops at three results, a reranker over the top 20, a context budget
that fits eight chunks.

**Boundary:** MRR and nDCG can disagree about the winner. In this module's data
MRR favours one system 1.000 to 0.500 while nDCG favours the other 0.634 to
0.527, on the same rankings.

**Tags:** `retrieval` `comparison` `general-principle`

---

### 2. [mechanism] What does MRR structurally ignore, and which system does that flatter?

**Answer:** Everything except the position of the first relevant result -- its
grade, and every document after it.

**Why:** A retriever that puts a marginally-related document at rank 1 scores a
perfect 1.0, identical to one that leads with the document that fully answers the
query.

**Boundary:** MRR is the right metric when the user genuinely stops at the first
useful hit -- a known-item lookup or a navigational query. It is the wrong one
when a fixed-size prefix is consumed downstream.

**Tags:** `retrieval` `mechanism` `general-principle`

---

### 3. [decision] Your relevance judgments are binary. What does that cost you, and when does it matter?

**Answer:** nDCG, effectively -- with no grades there is nothing to discount by
usefulness, and "answers the query" collapses into "related".

**Why:** nDCG's gain term is `2^grade - 1`; with every grade equal to 1 it
degenerates into a rank-discounted recall and stops rewarding putting the *best*
document first.

**Boundary:** Binary is the right trade when a fixed prefix is passed wholesale
to a model that reads all of it, since order inside the prefix barely matters.
Grade when a human reads top-down or the budget is tight.

**Tags:** `retrieval` `decision` `general-principle`
