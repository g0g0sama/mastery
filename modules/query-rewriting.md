# Query rewriting

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** query rewriting (Layer 6, - -> Independent). Map evidence to
graduate: "Rewrites that help, with the cases where they hurt named." The gate
is a retrieval eval, which now exists.

---

## The problem

[chinese-segmentation.md](chinese-segmentation.md) left two queries retrieving
nothing under a bigram analyzer. `动力电池供应` finds no document because the
phrase appears nowhere; `芯片制裁` finds none because the corpus writes 中芯国际
and 实体清单. Both documents exist and both are unreachable.

Nothing is wrong with the index or the scorer. The query and the corpus use
different words for the same thing, and lexical retrieval cannot cross that gap
by scoring harder.

## The wrong model

**"A rewrite that adds relevant terms can only help -- more terms means more
chances to match."**

Every added term also adds a way to match the wrong document. A rewrite is not a
free improvement in recall; it is a trade of precision for recall, made blind,
on every query it fires on -- including the ones that were already working.

The corollary that does the damage: **"the aggregate went up, so the rewrite
works."** In this module's experiment recall rises from 0.667 to 1.000 and MRR
from 0.667 to 0.917, and underneath that a query which was previously perfect is
now broken. The aggregate is the sum of two large effects in opposite directions
and it reports only the net.

## The mechanism

Rewrites come in kinds, and they carry different risk:

| Kind | Example | Risk |
|---|---|---|
| Abbreviation expansion | 中石化 -> 中国石化 | low; near-deterministic |
| Paraphrase to corpus vocabulary | 动力电池 -> 电池供货 | medium; depends on the corpus |
| Synonym / related-term expansion | 出口 -> 出口货运贸易 | **high**; pulls in adjacent senses |

Two rules that follow:

- **Append, never replace.** Keeping the original terms means the rewrite can
  only add candidates, and the original signal still ranks. Replacing bets the
  whole query on the rewrite being right.
- **Evaluate per query, never in aggregate.** A rewrite is a rule that fires on
  a subset. Its effect on the subset it fires on is the measurement; the corpus
  average dilutes it with queries it never touched.

## The experiment

`zh-retrieval-lab/rewrite_lab.py`. Index, analyzer and scorer are all held
constant -- only the query text changes.

**Predict before running: the aggregate will improve. Predict whether any
individual query gets worse, and which.**

```powershell
cd modules\zh-retrieval-lab
python rewrite_lab.py
```

Aggregate:

```text
system                recall@5     MRR   nDCG@5
bigram raw              0.6667  0.6667   0.6607
bigram + rewrite        1.0000  0.9167   0.9432
```

A large, real win. Per query:

```text
query                  raw RR   rewritten RR     verdict
Q1 中石化深圳投资          1.00           1.00          --
Q2 出口管制               1.00           0.50        HURT
Q3 动力电池供应            0.00           1.00      helped
Q4 光伏减产               1.00           1.00          --
Q5 稀土永磁               1.00           1.00          --
Q6 芯片制裁               0.00           1.00      helped
```

Two queries went from unretrievable to rank 1. **One query went from perfect to
half**, and the script names the cause:

```text
  Q2 出口管制: 出口管制 -> 出口管制出口货运贸易
    now ranks D15 first: 深圳机场空域管制调整影响出口货运
    the added terms matched a document the original query could not reach
```

The `出口 -> 出口货运贸易` expansion is the plausible one -- domain-adjacent trade
vocabulary, the sort of entry a person adds without thinking twice. It is also
the one that reaches the cross-sense false match, because 出口货运 appears in D15
verbatim.

The lesson is not that rewriting is dangerous. It is that **a rewrite table is a
set of independent hypotheses and must be evaluated as one**: three of the four
entries here are unambiguously good and the fourth should be deleted. Shipping
the table as a unit ships the fourth with the rest, and the aggregate will never
tell you it is there.

Note what this implies for [eval-gates.md](eval-gates.md): a gate watching only
the headline would have passed this change with a commendation.

## Boundary

- Six queries. Each verdict above rests on one query, which is evidence about a
  mechanism and not an effect size --
  [eval-set-sample-size.md](eval-set-sample-size.md).
- Rewrites are corpus-specific by construction. `动力电池 -> 电池供货` is right
  only because this corpus says 供货协议; on a corpus that says 动力电池 it is
  noise.
- Every rewrite must be versioned with the eval numbers it produced. A rewrite
  table is part of the retrieval instrument in exactly the sense
  [eval-set-versioning.md](eval-set-versioning.md) means -- change it and
  historical numbers stop comparing.
- Model-generated rewrites (HyDE, query expansion by generation) are the same
  trade with a larger and less inspectable rule set. The per-query evaluation
  matters more there, not less, because you cannot read the table.
- Rewriting is one of two answers to vocabulary mismatch. The other is a dense
  retriever, which handles the general case instead of the enumerated one -- and
  costs an index. Measure the proportion of queries affected before choosing.

## Cards

### 1. [failure] A query-rewrite rule set raises recall@5 from 0.67 to 1.00 and MRR from 0.67 to 0.92. What must you check before shipping it?

**Answer:** The per-query table. In this module's data those aggregate gains hide
one query going from reciprocal rank 1.00 to 0.50.

**Why:** A rewrite is a rule firing on a subset of queries, and the aggregate
sums large opposite effects into a net. Two queries went from unretrievable to
rank 1; one previously perfect query broke.

**Boundary:** The remedy is per-rule attribution, not a stricter threshold --
three of the four rules here were good and one should be deleted.

**Tags:** `retrieval` `failure` `general-principle`

---

### 2. [best-practice] Why should a query rewrite append terms rather than replace the original query?

**Answer:** So the rewrite can only add candidates while the original terms still
contribute ranking signal.

**Why:** Replacement bets the entire query on the rewrite being correct. If the
expansion is wrong the original -- which may have been working -- is gone, and
the failure is total rather than a dilution.

**Boundary:** Appending is not free either: added terms shift IDF weighting and
can pull an adjacent-sense document above a correct one, which is exactly how
the harmful rule in this module's data works.

**Tags:** `retrieval` `best-practice` `general-principle`

---

### 3. [decision] Two of your queries retrieve nothing because the corpus words the concept differently. Rewrite rules, or a dense retriever?

**Answer:** Rules first, when the affected queries are few and enumerable; a
dense retriever when vocabulary mismatch is broad, since it handles the general
case rather than the listed one.

**Why:** Rules are cheap, inspectable and per-query debuggable, but each is a
corpus-specific hypothesis that can misfire. A dense index costs infrastructure
and is the honest answer to systematic paraphrase.

**Boundary:** Decide on the measured proportion of queries affected, not on
principle -- and note that dense retrieval does not remove the need for the
per-query evaluation, it enlarges what needs evaluating.

**Tags:** `retrieval` `decision` `general-principle`
