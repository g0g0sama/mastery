# Freshness, deletion, and access-control filtering

**Micro module.** One mechanism, one experiment, three cards. Runs against
[zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** freshness, deletion, and access-control filtering (Layer 6, `-`
-> Independent). Map evidence to graduate: "A deleted document provably
unreachable through retrieval." The experiment builds that proof and it is the
deliverable -- the fix it forces takes four lines.

**Gate:** pipelines. Partly met. This module is also Layer 10 work in disguise
(authorization outside the model) and the Layer 10 row it feeds is
`Authorization outside the model`, whose evidence line -- "deterministic checks,
provable without reading a prompt" -- is what section 5 does.

---

## The problem

Every other retrieval module in this lab asks whether the right documents came
back. This one asks whether documents that should not exist came back.

The asymmetry is the whole point: **nobody files a bug when retrieval is too
permissive.** A missing result is a complaint. An extra result is a disclosure
that reaches you through legal, months later, if at all.

## The wrong model

**"Filter the results by permission before returning them."**

It is the obvious implementation, it is one line, and it is wrong twice over.

```text
query '中国工厂投资', k=5
full access    post-filter -> ['D16', 'D09', 'D05', 'D12', 'D01']  (5 results)
public only    post-filter -> ['D16', 'D09', 'D05']                (3 results)
               pre-filter  -> ['D16', 'D09', 'D05', 'D03', 'D13']  (5 results)
```

Same k, same ranking, different number of rows. Post-filtering asks the index
for five and then throws some away, so the restricted user gets a short page and
**no way to ask for the rest** -- page 2 starts at rank 6 and the removed rows
are simply gone. It reads as "search is worse for some users" and gets triaged
as a relevance problem, which it is not.

The reflex fix, over-fetching, is not a fix:

```text
over-fetch x1  (k= 5) -> 3 visible of 5 wanted
over-fetch x2  (k=10) -> 6 visible of 5 wanted
over-fetch x4  (k=20) -> 6 visible of 5 wanted
```

The multiplier you need is a function of how much of the corpus the principal can
see, which differs per tenant, per query, and over time. Pre-filtering answers
that question once, at the index; over-fetching re-answers it wrongly on every
request. In a vector index it is worse still -- see
[ann-indexes-hnsw.md](ann-indexes-hnsw.md): a filter applied *before* a graph
search changes which nodes are reachable, so filtered ANN recall is not the
recall you measured unfiltered.

## The mechanism

Three separate properties, three separate enforcement points:

| Property | Enforced at | Failure |
|---|---|---|
| **Visibility** | candidate generation, before ranking | short pages, count leaks |
| **Deletion** | the store boundary, every entry point | a removed document returned |
| **Freshness** | the pipeline, against a watermark | a correct answer about a past state |

The second row is where the module earns its place, because deletion looks done
long before it is.

## The experiment

```powershell
cd modules\zh-retrieval-lab
python freshness_lab.py
```

**Predict before running.** The store has one index and a `search()` that honours
a `deleted` flag. A document is deleted. How many ways out of the store still
return it?

```text
D02 (中国石油在新疆扩大天然气产能) deleted.
    search() pre-filter    clean  ['D01', 'D16', 'D13', 'D10']
    search() post-filter   clean  ['D01', 'D16', 'D13']
    similar_to(D01)        LEAKS  ['D02', 'D07', 'D15']
    preview(D02)           LEAKS  ['中国石油在新疆扩大天然气']
```

`search()` is correct on both filter modes. `similar_to()` and `preview()` never
learned about deletion, because deletion was implemented **where the requirement
was noticed** -- in the search path -- rather than at the boundary of the store.
The distance between those two is measured in months and one engineer.

So the evidence line cannot be satisfied by a test that calls `search()`. It
needs a sweep:

```text
before the fix: 10 reachable paths, e.g. [('similar_to', 'D01'), ...]
after the fix:  0 reachable paths
```

`unreachable(doc, principals)` enumerates every entry point, every query, and
every principal, and returns the paths that still resolve. **That function is
worth more than the fix**: it fails again the next time someone adds a fourth
entry point, which is the only guarantee that survives staff turnover.

Section 3 adds the leak that no grader in this repo would catch:

```text
query '长江存储武汉': 4 matching documents, 2 visible to an unprivileged principal.
```

Returning zero rows is correct. Returning *"4 results, 2 shown"*, a total, a
facet count, or a page-2 link confirms the existence of a document matching a
term this principal may not search. So does a measurable latency difference. The
authorization boundary covers **metadata about results**, not only results, and
every grader in [deterministic-graders.md](deterministic-graders.md) scores what
came back rather than what leaked.

And freshness, which fails in two directions of which only one is visible:

```text
D11 before: ...协调光伏减产          index watermark = 1700000000
D11 after:  ...取消光伏减产计划       document updated  = 1700003600
query '协调' (removed from the document) still returns: ['D11', ...]
query '取消' (added to the document)     returns: (nothing)
```

A stale hit looks like a relevance bug and gets investigated. A stale miss looks
like nothing at all. Neither is detectable from inside retrieval, because the
index is not wrong about anything -- it is a correct claim about a past state.
The instrument is a watermark stored **next to the index**, with the checkable
invariant `max(updated) <= watermark` over indexed documents. Keep it in the job
scheduler instead and a redeploy silently reindexes everything, or nothing.

## Boundary

- **Pre-filtering has its own cost**, and it is why post-filtering is tempting:
  the filter must be pushed into the index, which for a graph-based ANN index
  means either filtered traversal (recall changes) or per-tenant indexes (cost
  changes). Choosing post-filtering deliberately, with an over-fetch bound and a
  documented failure mode, is defensible. Arriving at it by accident is not.
- **Soft delete is a retention decision, not an implementation detail.** A
  tombstone that keeps the text satisfies "not returned" and fails "not
  retained". Decide which one the requirement actually was before choosing.
- **The sweep is only as complete as the entry-point list**, which is why it
  belongs beside the store rather than in the test suite of one caller. Adding
  an endpoint that reads the store without updating the sweep is the failure
  this module cannot prevent -- only make visible.
- **Access control belongs outside the model entirely.** If a retrieved document
  reaches a prompt, the check has already happened or it has already failed; a
  model instructed not to reveal something is not an authorization mechanism.
  That is Layer 10's row, and this lab is its retrieval half.

## Cards

### 1. [failure] A user reports that search returns three results on page one instead of ten, but only for their account. What is the first implementation to suspect?

**Answer:** Post-filtering -- the index returns the top k and permission
filtering removes rows afterwards, so restricted principals get short pages.

**Why:** The removed rows are not replaced from deeper in the ranking, and page 2
still starts at rank k+1, so the missing results are unreachable rather than
delayed. It presents as a relevance complaint from one class of user.

**Boundary:** Over-fetching does not fix it: the multiplier depends on what
fraction of the corpus that principal can see, which varies per tenant and query.
The fix is filtering during candidate generation -- which in a graph-based ANN
index changes reachability and therefore recall, so it must be re-measured.

**Tags:** `retrieval` `authorization` `failure` `general-principle`

---

### 2. [scenario] You must show that a deleted document is unreachable through retrieval. Your test deletes it and asserts the search endpoint returns nothing. What has that test proved?

**Answer:** That the search path honours deletion. Nothing about deletion.

**Why:** Stores accumulate entry points -- similarity/"more like this", snippet
and preview caches, export jobs, reindex sources. In the lab, deletion was
implemented in `search()` and two other paths still returned the document,
including its cached text.

**Boundary:** The deliverable is a sweep over every entry point, every query, and
every principal, living beside the store. It is worth more than the fix because
it fails again when someone adds the next entry point.

**Tags:** `retrieval` `deletion` `scenario` `general-principle`

---

### 3. [mechanism] A search returns zero rows to an unauthorized user but reports "4 results, 2 shown". Why is that a disclosure, and what class of bug does it belong to?

**Answer:** The count confirms that documents matching the query exist, which the
user is not authorized to learn. It is an authorization bug, not a UI one.

**Why:** The boundary covers metadata about results as well as results: totals,
facet counts, page-2 links, and measurable latency differences all answer a
question the filter was meant to refuse.

**Boundary:** No relevance grader detects this, because graders score what came
back rather than what leaked. It needs a test written against the authorization
requirement directly.

**Tags:** `retrieval` `authorization` `mechanism` `general-principle`
