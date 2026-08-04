# Reranking and multi-stage retrieval

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** reranking and multi-stage (Layer 6, `-` -> Independent). Map
evidence to graduate: "nDCG gain per added millisecond, tabulated." Tabulated
below, on six queries -- which is enough to show the shape of the curve and not
enough to pick a depth for production.

**Gate:** hybrid retrieval. Met by
[hybrid-retrieval-fusion.md](hybrid-retrieval-fusion.md), whose conclusion this
module needs twice.

---

## The problem

The good scorer is too slow to run on the corpus. A cross-encoder reads the
query and the document together and costs a forward pass per pair; at a hundred
thousand documents that is not a latency problem, it is an impossibility. So you
run a cheap ranker over everything and an expensive one over a few. The only
decisions left are how few, and what "expensive one" means.

Both of those look like tuning. They are not.

## The wrong model

**"The reranker is the good ranker, so send it more candidates."**

Depth reads like a quality dial with a cost attached: pay more milliseconds, get
more accuracy, stop where the budget stops. Under that model the only mistake
possible is spending too much.

The lab says otherwise. nDCG@5 peaks at depth 3 and is **worse than no
reranking at all** from depth 5 onward. Every additional candidate is another
chance for the second stage to promote something the first stage had correctly
buried, and quality does not move monotonically with the money.

## The mechanism

Two stages with different jobs, and this is the part that decides everything
downstream:

- **Stage 1 optimizes recall.** It is allowed to be sloppy, because stage 2 will
  clean up. The lab uses the **unigram** index for this, not the more precise
  bigram one -- chosen deliberately, since the precise analyzer would leave the
  reranker nothing to do while capping what the pipeline can ever reach.
- **Stage 2 optimizes precision** over a window it can afford to read properly.
  The lab's reranker computes the smallest character span containing all matched
  terms: a feature stage 1 **structurally cannot** produce, because an inverted
  index stores which documents contain a term, not where.

Two consequences follow, and they are the module:

1. **Stage 1's recall@depth is a hard ceiling.** A reranker cannot retrieve. Its
   best possible score is whatever a perfect reordering of the candidate window
   would give.
2. **The stages have different feature bases**, so stage 2 can be blind exactly
   where stage 1 was right.

## The experiment

```powershell
cd modules\zh-retrieval-lab
python rerank_lab.py
```

**Predict before running.** The reranker is strictly better informed than BM25 --
it sees positions. Reranking the top 3, top 5, top 10, and all 17 documents: is
nDCG@5 monotonic in depth? Write down the direction before you look.

Actual:

```text
system                   nDCG@5     MRR   ms/query   gain/ms
BM25 only                0.9432  0.9167      0.008        --
+ rerank top-3           0.9940  1.0000      0.044    1.4362
+ rerank top-5           0.9325  0.9167      0.057   -0.2219
+ rerank top-10          0.9325  0.9167      0.069   -0.1776
+ rerank top-17          0.9325  0.9167      0.068   -0.1795
```

Up, then down through the baseline. The per-query table shows both halves:

```text
query                   BM25   top-3   top-5
Q2 出口管制                0.659   0.964   0.964     <- the fix
Q6 芯片制裁                1.000   1.000   0.631     <- the damage
```

**Q2 is what reranking is for.** `D15` -- *air traffic control ... affects export
freight* -- carries both query terms in unrelated senses, in different clauses.
BM25 scores it 6.781 against the correct document's 6.159 and ranks it first. The
proximity scorer gives 5.041 against 14.613 and the order flips. A bag-of-terms
score cannot distinguish "says both terms together" from "says both terms in
unrelated sentences", and the second stage exists to see that difference.

**Q6 is the failure nobody predicts.** `芯片` never occurs in the relevant
document; `芯` does, inside the company name `中芯国际`. Stage 1 matched on that
single character and was **right**. The reranker's features are bigrams, it finds
nothing, and it scores the document **exactly 0.000** -- so a correct rank-1
result falls below noise and nDCG@5 drops from 1.000 to 0.631.

The rule underneath: **a reranker that replaces the first-stage score discards
the only evidence available whenever its own features miss.** Fusing the two
ranks instead fixes it and keeps Q2's win:

```text
system                       nDCG@5     MRR
BM25 only                    0.9432  0.9167
replace @5                   0.9325  0.9167
RRF(stage1,rerank) @5        0.9940  1.0000
RRF(stage1,rerank) @10       0.9940  1.0000
```

Fusion also removes the depth cliff -- at depth 10 the fused pipeline still
scores 0.9940, because a document now has to be bad under **both** scorers to
fall. Rank-level fusion rather than score-level, for the reason
[hybrid-retrieval-fusion.md](hybrid-retrieval-fusion.md) gives: a BM25 score and
a reranker score share no scale.

## Boundary

- **Measure stage 1's recall@depth first.** In the lab it saturates at 1.0000 by
  depth 5, so nothing above depth 5 can add anything, and every millisecond spent
  there is pure loss. If your recall@depth is still climbing at your budget's
  depth, the reranker is not your problem -- the retriever is.
- **Reranking cannot fix recall.** Q3 in the lab is retrieved only because the
  unigram analyzer matched incidental characters; the reranker scores the target
  at 0.000 and it holds rank 1 on an alphabetical tie-break. That is luck, not
  ranking. A genuine recall gap needs another retriever, never a better second
  stage.
- **These milliseconds are not yours.** The lab's reranker is a proximity scorer
  in Python over 17 short documents. A cross-encoder is three orders of magnitude
  slower per pair, which does not change the shape of the curve -- it moves the
  economic depth much closer to 3 than to 100.
- **Six queries.** The peak-then-fall shape is a large effect that survives; the
  0.9940 vs 0.9432 difference is not a shippable measurement. See
  [eval-set-sample-size.md](eval-set-sample-size.md).

## Cards

### 1. [misconception] You are reranking the top 10 with a cross-encoder and have latency budget left. Is reranking to depth 50 more accurate, less accurate, or unknowable without measuring?

**Answer:** Unknowable, and often less accurate. Quality is not monotonic in
depth.

**Why:** Every extra candidate is another chance for the second stage to promote
a document the first stage had correctly buried. In the lab, nDCG@5 rises from
0.9432 to 0.9940 at depth 3 and drops to 0.9325 -- below the no-rerank baseline
-- from depth 5 onward.

**Boundary:** The ceiling on the other side is stage 1's recall@depth. If it has
saturated by depth 5, no depth beyond 5 can add anything even in principle, so
measure that curve before tuning the reranker at all.

**Tags:** `retrieval` `reranking` `misconception` `general-principle`

---

### 2. [failure] After adding a reranker, one query that was previously perfect returns the right document far down the list. The reranker scores it exactly zero. What is the design error?

**Answer:** The reranker replaces the first-stage score instead of being fused
with it, so a document its features cannot see is demoted below noise.

**Why:** The two stages have different feature bases. In the lab, stage 1 matched
a relevant document on a single character inside a company name -- correctly --
and the bigram-based reranker found nothing and returned 0.000, dropping nDCG@5
on that query from 1.000 to 0.631.

**Boundary:** Fuse at the rank level, not the score level: a BM25 score and a
reranker score share no scale. Rank fusion also flattens the depth cliff, since a
document must be bad under both scorers to fall.

**Tags:** `retrieval` `reranking` `failure` `general-principle`

---

### 3. [decision] Why should the first stage of a two-stage retriever use a **less** precise analyzer than you would choose for single-stage retrieval?

**Answer:** Because the first stage's job is recall, and its recall@depth is a
hard ceiling on everything the second stage can achieve.

**Why:** A reranker reorders; it cannot retrieve. A precise first stage that
drops a relevant document has removed it from the pipeline permanently, and it
also leaves the reranker nothing to correct -- in the lab, the precise bigram
first stage produced identical output at every rerank depth.

**Boundary:** Sloppy has a limit: candidates the second stage cannot evaluate
become noise it must sort through, which is how the depth curve turns negative.
Recall@depth and rerank depth are tuned together, not separately.

**Tags:** `retrieval` `reranking` `decision` `general-principle`
