# Provider errors, retries, idempotency

**Micro module.** One mechanism, one experiment, three cards. Runs against
[model-interface-lab/](model-interface-lab/).

**Capability:** provider errors, retries, idempotency (Layer 4, Aware ->
Independent). Map evidence to graduate: "Retry policy that distinguishes
transient from terminal."

**Gate:** idempotency (Layer 1b). The database half is
`../patterns/08-database-patterns`; this is the model-facing half, and the only
new thing in it is that timeouts here are common rather than rare.

---

## The problem

Model APIs fail more often than the services you are used to, and they fail in
more distinguishable ways than the retry wrapper you reached for can express.

## The wrong model

**"Retry on exception, three times, with a short delay."**

Against exactly the same failures:

```text
policy                              calls     slept    ok  gave up
retry everything, fixed delay           9      7.0s     2        1
classify + backoff + retry_after        6      3.5s     2        1
```

Identical outcomes -- two succeeded, one was unrecoverable under any policy --
for nine calls against six. The three wasted calls all went to a
`BadRequestError`: a malformed request retried four times is the same malformed
request, four times, at full price. **A retry policy that cannot distinguish
transient from terminal is a cost multiplier bolted onto your worst bugs, and it
is silent, because the end state is right.**

## The mechanism

Two columns decide everything. Everything else is presentation:

```text
error                   status  transient   what it means
RateLimitError             429       True   too fast; retry_after is authoritative
OverloadedError            529       True   they are busy; back off and jitter
ServerError                500       True   their bug or yours; bounded retries
APITimeoutError              -       True   UNKNOWN outcome
BadRequestError            400      False   your bug; retrying reproduces it
ContentFilterError         400      False   a RESULT about the input
```

`ContentFilterError` is the one always miscategorised. Counting it as a failure
buries a data problem inside a reliability metric and fires the wrong alert. It
belongs in the extraction's error taxonomy
([error-taxonomy.md](error-taxonomy.md)), not in the retry budget.

## The experiment

```powershell
cd modules\model-interface-lab
python retry_lab.py
```

**The timeout is the one that needs a second mechanism.** It is transient in the
sense that retrying may work, and it is the only error whose *outcome is
unknown*: the request may have completed and you did not see the answer.

```text
idempotency key off: retry -> inserted,      rows in table = 2
idempotency key on : retry -> deduplicated,  rows in table = 1
```

The key must be derived from the **work** -- document id plus prompt version --
not from the attempt. A key minted per attempt dedupes nothing, which is the
single most common way this is implemented wrong.

## Boundary

- **Jitter, or the convoy re-forms.** Synchronised clients back off by the same
  amount and hit the recovering provider simultaneously. A random factor on the
  delay is what breaks it, and it is one line that is almost always missing.
- **A retry policy without a circuit breaker cannot stop, only slow down.** After
  N consecutive failures, fail fast for a cool-down. Otherwise every client
  retrying a 529 three times turns a degraded provider into one receiving 3x its
  normal load at the moment it can least absorb it.
- **Budget, not count.** "Three attempts" on a $0.05, 30-second request is a
  different decision from three attempts on a $0.0001 one. Cap total spend and
  total latency per unit of *work* and let the attempt count fall out.
- **Streaming complicates the timeout further.** A stream that fails at 80% has
  already billed you for 80% of the output ([streaming-cancellation.md](streaming-cancellation.md)),
  so retry cost is not the price of one call.
- **Honour `retry_after` over your own arithmetic.** The server knows its
  recovery window; your exponential backoff is a guess about it.

## Cards

### 1. [decision] Your retry wrapper catches every exception and retries three times. What does it cost you, given that the final outcomes are correct?

**Answer:** It spends full-price calls on terminal errors, which cannot succeed
however many times you send them.

**Why:** In the lab, retrying everything used nine calls where a classifying
policy used six for identical outcomes; all three wasted calls went to a
`BadRequestError`. The waste is invisible precisely because the end state is
right.

**Boundary:** The classification must be on `transient` versus `terminal`, not on
the status code -- two different 400s in the lab mean opposite things, and one of
them is not a failure at all.

**Tags:** `reliability` `decision` `general-principle`

---

### 2. [failure] A request times out. You retry it and it succeeds. Later you find duplicate rows. What happened, and what is the fix?

**Answer:** The first request completed on the provider's side; only the response
was lost. Both attempts produced a write. The fix is an idempotency key derived
from the work, not the attempt.

**Why:** A timeout is the one transient error whose outcome is unknown, so
retrying it is safe only if the effect is idempotent -- and "append a row" is not.

**Boundary:** A key minted per attempt dedupes nothing. Derive it from document
id plus prompt version, so the same work has the same key across retries and a
genuinely new run gets a new one.

**Tags:** `reliability` `idempotency` `failure` `general-principle`

---

### 3. [misconception] Why should a content-filter rejection be kept out of your retry and reliability metrics?

**Answer:** It is a result about the input, not a failure of the call. Counting
it as an error hides a data problem inside a reliability number.

**Why:** The alert that fires will be about provider health, and the actual
finding -- that a class of documents is being rejected -- lands nowhere. It
belongs in the extraction's error taxonomy with its own count.

**Boundary:** It is still terminal for that request: never retry it. Terminal and
"an error worth alerting on" are different properties, and the retry policy only
needs the first.

**Tags:** `reliability` `misconception` `general-principle`
