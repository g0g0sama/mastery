# Streaming and cancellation

**Micro module.** One mechanism, one experiment, three cards. Runs against
[model-interface-lab/](model-interface-lab/).

**Capability:** streaming and cancellation (Layer 4, Aware -> Independent). Map
evidence to graduate: "Cancel a stream and prove no partial write persisted."
The proof is an assertion in the lab, and it is the deliverable.

**Gate:** async. Partly met by `../patterns/09-concurrency`.

---

## The problem

Streaming exists so a user sees the first token in 200ms instead of the last one
in 6 seconds. It arrives with a cost that nobody bills for: your code now
processes a response that is **not finished**, and the decision of what to do
with a fragment gets made implicitly, in a `for` loop, by whoever writes it.

## The wrong model

**"Handle the chunks as they arrive."**

It is what the API shape suggests, and for rendering text into a UI it is
correct. For anything that produces a *record* it is a trap, because the loop can
end three ways -- completion, client cancellation, provider failure -- and only
one of them leaves you with something valid.

```text
store holds 4 rows
reassembled: '{"event_type": "supply_agreement", "actors": ["宁'
parses -> no (Unterminated string starting at)
```

Four rows of debris are already in the store and **no exception was raised
anywhere**. The loop simply stopped. The parse failure is not the bug; it is the
only thing that stopped the bug from being worse.

## The mechanism

A stream is a sequence of deltas followed by a terminal event carrying usage.
Two consequences decide every design below:

- **The first delta is bytes, not a record.** Nothing downstream can validate
  anything until the last one arrives. So validation is a whole-response
  operation, and therefore so is any write derived from it.
- **Usage arrives last.** A budget enforced from the usage field is enforced
  after the money is spent ([budgets-and-timeouts.md](budgets-and-timeouts.md)).

The correct shape is therefore: **buffer, validate, commit once.**

```python
def extract_streaming(provider, doc_id, store, cancel_after=None):
    buffer = []
    stream = provider.stream(doc_id, constrained=True)
    try:
        for i, (kind, payload) in enumerate(stream):
            if kind == "delta":
                buffer.append(payload)
    finally:
        stream.close()          # runs the generator's own cleanup
    record = json.loads("".join(buffer))
    if violations := validate(record):
        raise ValueError(f"invalid record: {violations}")
    store.commit(doc_id, record)   # the ONLY write, and it is last
```

## The experiment

```powershell
cd modules\model-interface-lab
python stream_lab.py
```

```text
cancelled: client disconnected
rows persisted after cancellation: 0
assert safe.rows == []  -- passes.
```

That assertion is the map's evidence line, and it belongs in the test suite
rather than in a comment -- it is what fails when someone later adds a
"progressive save" for good reasons.

**Mid-stream failure is not cancellation.** The provider drops after 24
characters: you are billed for the tokens generated and have no usable output.
Retrying re-pays for all of them, which is why streaming a long structured output
is a cost decision as well as a latency one, and why
[provider-errors-retries.md](provider-errors-retries.md) caps attempts by budget
rather than by count.

## Boundary

- **Never run a repair pass over a stream you did not see end.** In the lab
  `repair()` correctly refuses the fragment because there is no closing brace --
  which is luck, not a guarantee. A truncation landing after a nested object
  closes *does* parse, and yields a record with silently missing fields that no
  schema can distinguish from a short answer.
- **Cancelling your loop may not cancel the generation.** Whether it does depends
  on the transport actually being torn down, and behind a proxy, a queue, or a
  retry wrapper it often is not. Assume you pay for the whole response unless
  you have measured otherwise.
- **Three things must hold on the cancellation path**, in order: no partial
  write; no partial side effect (no tool call, no email, no downstream job); and
  a record that the run was cancelled with tokens consumed, so cost per accepted
  record stays honest ([tokenization.md](tokenization.md)).
- **Streaming and structured output pull in opposite directions.** The user-facing
  argument for streaming is perceived latency on prose. A JSON record is not read
  as it arrives by anyone. If the output is a record, ask what streaming is
  buying before paying for the failure modes above.

## Cards

### 1. [failure] A user cancels a streamed extraction. No exception is raised and the request looks clean in the logs. What do you check in the database?

**Answer:** Whether partial rows were written. A consumer that persists deltas as
they arrive leaves fragments behind, and cancellation raises nothing -- the loop
just ends.

**Why:** In the lab, cancelling after four deltas left four rows in the store and
a reassembled fragment that does not parse. Nothing in the logs distinguished it
from a completed request.

**Boundary:** The fix is structural, not defensive: buffer, validate, commit
once, and assert in a test that a cancelled run leaves the store empty. That
assertion is what fails when someone later adds progressive saving.

**Tags:** `streaming` `failure` `general-principle`

---

### 2. [misconception] Why is running a JSON repair pass over a truncated stream more dangerous than letting it fail to parse?

**Answer:** Repair takes the first brace to the last one. A truncation that lands
after a nested object closes produces valid JSON with silently missing fields.

**Why:** A parse failure is loud and stops the pipeline. A repaired truncation is
a well-formed record that the schema cannot distinguish from a short but complete
answer, so it is stored and never looked at again.

**Boundary:** Repair is a legitimate tool on a *complete* response -- it recovers
most free-form invalidity. The precondition is having seen the terminal event.

**Tags:** `streaming` `misconception` `general-principle`

---

### 3. [mechanism] In a streaming response, when do you learn the token usage, and what does that rule out?

**Answer:** At the end, with the terminal event. It rules out enforcing a token
budget from the usage field, because by the time you read it the tokens are
generated and billed.

**Why:** A budget must be enforced *before* the request -- an estimated
`max_tokens`, a per-run cap, a wall-clock timeout -- rather than by inspecting
what came back.

**Boundary:** Cancelling mid-stream does not reliably stop generation either, so
even an aggressive client-side cutoff is not a spend control. Treat the whole
response as paid for unless measured otherwise.

**Tags:** `streaming` `cost` `mechanism` `general-principle`
