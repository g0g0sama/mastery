# Failure log

Wrong predictions, in the order they happened. This is the highest-value file in
the repository: a generic flashcard tests a fact somebody else thought was
important, while an entry here tests the exact model that has already failed you
once.

Write the entry **at the moment of surprise**, before looking up the answer.
Retrospective entries lose the wrong model, which is the only part that matters.

## Format

```markdown
### YYYY-MM-DD -- one-line title

**Expected:** what I predicted would happen.

**Happened:** what actually happened, with the output or error.

**Wrong model:** the belief that produced the prediction. Not "I forgot X" --
name the thing I believed instead.

**Diagnosis:** how I found the real cause, including the dead ends.

**Rule:** what I will check first next time this shape appears.

**Propagate:** which card, lab, or module should change, or `none`.
```

The `Wrong model` line is the entry. An entry that says "I did not know about
this parameter" records a gap; an entry that says "I believed the lock was held
for the duration of the critical section, not the duration of the await" records
a model, and models are what fail again.

## Review

Read this file at the start of each cycle. Any entry that repeats a wrong model
already listed is a signal that the fix went into a card instead of into practice
-- promote it to a lab step or a project assertion.

---

<!-- newest entries at the top, below this line -->

### 2026-08-05 -- the classifier baseline scored 0.9965 and taught nothing

**Expected:** building a naive Bayes and a logistic regression against a
simulated extractor on generated documents would give the interesting case the
map row is about -- a cheap baseline somewhere near a model, where the decision
is real.

**Happened:** keyword rule 0.9965, naive Bayes 0.9965, logistic regression
0.9965, extractor 0.8267. Every classifier was near-perfect and agreed with the
extractor on everything the extractor got right (only 1 record of 286 went the
other way).

**Wrong model:** I believed the difficulty of a generated classification task
came from the noise I had put in the *label* -- per-type accuracy, confusion
between neighbours, confidence bias. All of that was in the generator. But I
had drawn each document's tokens from its own type's keyword list and nothing
else, so the classes were linearly separable and no amount of label noise could
make the *features* ambiguous. Difficulty lives in the overlap between classes
in feature space, not in the error rate attached to the answer.

**Diagnosis:** three systems reporting the identical 0.9965 was the tell -- it
was the same single misclassified record in all three, which meant they were
not making independent decisions but reading the same disjoint vocabulary. I
nearly wrote it up as "the bag-of-words baseline beats the LLM", which would
have been a statement about my own `KEYWORDS` dict.

**Rule:** when a generated fixture produces a result near a ceiling, find the
parameter that sets the ceiling before writing anything about it, and put that
parameter's name in the README. For a classification fixture the parameter is
always class overlap in feature space.

**Propagate:** `population.CONTAMINATION` now controls it and is documented as
one of the two parameters that decide everything in
`modules/stats-lab/README.md`; `modules/classical-baselines.md` states in its
boundary that setting it to zero returns 0.99 for every system. The general
form belongs beside the `predict.py` habit: a fixture needs a prediction about
its own difficulty, not only about the result.

### 2026-08-05 -- the shape checker padded the wrong end and hid the bug it was written to find

**Expected:** `broadcast((12,64), (12,))` would raise, demonstrating that the
non-square case catches a missing `keepdims` while the square case does not.
That contrast was the entire point of the section.

**Happened:** it returned `(12, 64)` with no error. Both cases passed, so the
section demonstrated nothing.

**Wrong model:** I believed "right-align the shapes" described the *operation*,
so I implemented it by padding the shorter shape on the right and then zipping
from the end. Right-alignment is the comparison order; the padding goes on the
**left**. Padded right, `(12,)` becomes `(12,1)` -- which is exactly the shape
the correct code should have had, so my checker silently repaired the bug it
existed to detect.

**Diagnosis:** the output table showed "no error" on all three rows including
the one labelled `-- not square`, which I first read as a typo in my test data
rather than in the rule. Working the rule by hand on `(12,64)` vs `(1,12)`
against `(12,1)` took a minute and was unambiguous.

**Rule:** when implementing a rule in order to demonstrate a violation of it,
check that the violation case actually fails before writing the prose. A
checker that never rejects anything is indistinguishable from a checker that is
correct, on the cases you chose.

**Propagate:** `modules/stats-lab/shapes_lab.py` carries the fix and a docstring
recording it, and `modules/matmul-and-shapes.md` opens with it, because the
module's subject is precisely bugs that do not raise and the lab produced one.

### 2026-08-05 -- "cache the expensive ones" lost on cost as well as on hit rate

**Expected:** an eviction policy that drops the cheapest-to-recompute entry
instead of the least recently used would trade hit rate for money -- fewer
hits, more dollars saved. I built the arm specifically to show that trade, and
wrote the paragraph describing it before running it.

**Happened:** at capacity 8 it lost 12.0 points of hit rate *and* 4.6 points of
cost saved against plain LRU. At capacity 16, 7.8 and 0.5. There was no trade;
it was worse at both.

**Wrong model:** I believed cost was a usable proxy for cache value once
requests differ in price. It is half of the value: an entry is worth
(frequency x cost to recompute), and I had thrown away the frequency term.
Keeping a 6x item asked for three times, by evicting a 1x item asked for fifty,
loses on money too -- fifty cheap recomputations cost more than three expensive
ones. Half of a product is not an approximation of the product.

**Diagnosis:** the hit-rate loss was expected, so I only noticed the cost loss
because I had printed both deltas next to each other. Printing only the metric
the arm was designed to improve would have hidden it completely.

**Rule:** when adding an arm to demonstrate a trade-off, print both sides of the
trade for every arm. An arm that is supposed to lose on metric A and win on
metric B has to be checked on B, not assumed.

**Propagate:** `modules/caching.md` section 1 and card 1 now carry the negative
result, and the eviction advice is "rank by frequency x cost", never "cache the
expensive ones". More generally: this is the second entry in this log about a
one-factor rule replacing a two-factor one -- see the natural-key entry below --
which suggests the check belongs in the lab template, not in a card.

### 2026-08-05 -- the thundering herd did not queue, it was refused

**Expected:** 60 clients retrying on a synchronised 200 ms backoff would all
arrive in one 50 ms bucket, wait in the accept queue, and be served -- slower
than jittered clients but all served. I built the measurement around peak
arrivals per bucket for exactly that reason.

**Happened:** 23 of the 60 connections were reset by the OS before the
application ever saw them, and the run took 1016 ms to drain against 197 ms
with jitter. The peak-per-bucket columns were nearly identical (25 vs 20),
because the arrivals that would have made the spike tall were dropped instead.

**Wrong model:** I believed the accept queue was effectively unbounded on
loopback and that a burst degraded into latency. It degrades into *loss*, at a
layer with no application-level logging, and the loss shows up at the client as
a transport error -- which every retry policy classifies as transient. So the
herd's own overflow feeds the next round of the herd.

**Diagnosis:** the tracebacks were `ConnectionResetError` in the *client*
threads, which I first read as my own test harness misbehaving and nearly
suppressed the way I had suppressed the server-side ones in `service.serve`.
Counting them instead of hiding them was the whole finding.

**Rule:** when measuring a burst, always count what never arrived. An arrival
histogram cannot show you the requests the kernel refused, and the refused ones
are the mechanism by which a burst sustains itself.

**Propagate:** `modules/backoff-circuit-breaking.md` section 3 and card 2 both
lead with the connections-lost column rather than the peak. And a general one
for this fixture: suppressing an exception class in the harness is a decision
about what can be measured, so `service.serve` suppresses server-side resets
only, never client-side ones.

### 2026-08-05 -- a natural-key constraint removed more rows than it was asked to

**Expected:** adding `UNIQUE(doc_id, content_sha)` to the events table would
turn the 32 rows written by 24 requests plus 8 retries into 24 -- the retries
suppressed, everything else untouched.

**Happened:** 8 rows. The 24 requests cover 8 documents, so the constraint also
collapsed the 16 requests that were genuinely distinct calls about the same
document that happened to produce the same answer.

**Wrong model:** I believed a natural key was a strictly weaker version of an
idempotency key -- same job, no client cooperation needed. It is not weaker, it
is a different question. The key asks "is this the same request?" and the
constraint asks "is this the same observation?", and the second one has no
access to intent at all.

**Diagnosis:** the row count was too low rather than too high, which is the
opposite of the failure I was watching for, so I nearly wrote it up as a clean
result. Dividing 24 by the 8 documents in the fixture made it obvious.

**Rule:** when a deduplication rule is proposed, ask what it is keyed on and
then ask whether two legitimately separate intents can produce that key. If they
can, the rule is a data-identity rule and needs an UPSERT or a decision about
append-only semantics, not a constraint bolted on for safety.

**Propagate:** `modules/idempotency-keys.md` section 6 and card 3, both of which
now state the over-collapse rather than presenting the constraint as a free win.

---

### 2026-08-05 -- a failed INSERT held a write lock through a polling loop

**Expected:** the wait-and-replay idempotency policy would work like the 409
policy but slower: loser of the key race polls until the winner marks the key
done, then replays the stored response.

**Happened:** deadlock. 26 `sqlite3.OperationalError: database is locked` and
a wave of client timeouts, with 10 rows written out of 24.

**Wrong model:** I believed that an `INSERT` raising `IntegrityError` had left
no transaction behind -- that a statement which failed was a statement that had
not happened. It had happened: Python's sqlite3 had already opened the
transaction implicitly, the failed statement rolled back only itself, and the
connection sat in that open write transaction for the entire five-second
polling loop, blocking every other writer.

**Diagnosis:** the error pointed at the writers, not at the waiters, so I first
suspected connection-per-request overhead and the `CREATE TABLE IF NOT EXISTS`
in the shared `store()` helper -- which was a real second problem and fixing it
did not fix this one. Adding `conn.rollback()` in the `IntegrityError` branch
did.

**Rule:** after any caught database exception, ask what the connection is still
holding before doing anything else on it -- especially before anything that
waits. An `except` block that does not end the transaction is a lock held for
the duration of whatever comes next.

**Propagate:** `modules/service-lab/idempotency_lab.py` carries the fix and the
comment; the shape belongs in
`modules/transactions-and-consistency.md`, which is where lock duration is the
subject rather than an accident.

