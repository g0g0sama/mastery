"""Streaming and cancellation: prove that no partial write persisted.

    python stream_lab.py
"""
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provider import OverloadedError, Provider, repair
from task import validate

DOC = "N02"


class Store:
    """Stands in for the events table. `rows` is the evidence."""

    def __init__(self):
        self.rows = []

    def append(self, doc_id, fragment):
        self.rows.append((doc_id, fragment))

    def commit(self, doc_id, record):
        self.rows.append((doc_id, record))


provider = Provider("mid-1")

print("=== 1. What a stream actually is ===")
deltas = []
for kind, payload in provider.stream(DOC, constrained=True):
    if kind == "delta":
        deltas.append(payload)
    else:
        usage = payload
print(f"  {len(deltas)} deltas, first = {deltas[0]!r}")
print(f"  usage arrives LAST: {usage}")
print("  Two consequences that decide the design of everything below:")
print("   - the first delta is bytes, not a record. Nothing downstream of the")
print("     stream can validate anything until the last one arrives.")
print("   - token usage is only known at the end, so a budget enforced from the")
print("     usage field is enforced after the money is spent")
print("     (../budgets-and-timeouts.md).")
print()

print("=== 2. Break it: cancel a naive consumer ===")
naive = Store()
stream = provider.stream(DOC, constrained=True)
try:
    for i, (kind, payload) in enumerate(stream):
        if kind == "delta":
            naive.append(DOC, payload)      # write as it arrives
        if i == 3:
            break                            # the user closed the tab
finally:
    stream.close()
partial = "".join(frag for _, frag in naive.rows)
print(f"  store holds {len(naive.rows)} rows")
print(f"  reassembled: {partial!r}")
try:
    json.loads(partial)
    print("  parses -> yes")
except json.JSONDecodeError as exc:
    print(f"  parses -> no ({exc.msg})")
print(f"  repair() makes it: {repair(partial)!r}")
print("  Four rows of debris are already in the store, and no exception was")
print("  raised anywhere -- the loop simply stopped. The parse failure is not")
print("  the bug; it is the only thing that stopped the bug from being worse.")
print("  repair() correctly refuses this fragment because there is no closing")
print("  brace. That is luck rather than a guarantee: a truncation that lands")
print("  after a nested object closes DOES parse, and yields a record with")
print("  silently missing fields that no schema can distinguish from a short")
print("  answer. Never run a repair pass over a stream you did not see end.")
print()

print("=== 3. The fix: buffer, validate, commit once ===")


def extract_streaming(provider, doc_id, store, cancel_after=None):
    """Cancellation-safe by construction: nothing is written before the end."""
    buffer = []
    stream = provider.stream(doc_id, constrained=True)
    try:
        for i, (kind, payload) in enumerate(stream):
            if kind == "delta":
                buffer.append(payload)
                if cancel_after is not None and i >= cancel_after:
                    raise KeyboardInterrupt("client disconnected")
    finally:
        stream.close()                       # runs the generator's own cleanup
    record = json.loads("".join(buffer))
    if violations := validate(record):
        raise ValueError(f"invalid record: {violations}")
    store.commit(doc_id, record)             # the ONLY write, and it is last
    return record


safe = Store()
try:
    extract_streaming(provider, DOC, safe, cancel_after=3)
except KeyboardInterrupt as exc:
    print(f"  cancelled: {exc}")
print(f"  rows persisted after cancellation: {len(safe.rows)}")
assert safe.rows == [], "cancellation must leave no trace"
print("  assert safe.rows == []  -- passes. That assertion is the map's")
print("  evidence line for this row, and it belongs in the test suite rather")
print("  than in a comment.")
extract_streaming(provider, DOC, safe)
print(f"  rows after a completed run: {len(safe.rows)}")
print()

print("=== 4. Mid-stream failure is not the same as cancellation ===")
failed = Store()
stream = provider.stream(DOC, constrained=True, fail_at=20)
got = []
try:
    for kind, payload in stream:
        if kind == "delta":
            got.append(payload)
except OverloadedError as exc:
    print(f"  provider failed after {len(''.join(got))} characters: {exc}")
print("  You are billed for the tokens generated before the failure and you")
print("  have no usable output. Retrying re-pays for all of them -- which is why")
print("  streaming a long structured output is a cost decision as well as a")
print("  latency one, and why ../provider-errors-retries.md caps attempts by")
print("  budget rather than by count.")
print()

print("=== 5. What cancellation does NOT cancel ===")
print("  Closing the generator stops YOUR loop. Whether it stops the provider's")
print("  generation depends on the transport actually being torn down -- and if")
print("  the request is behind a proxy, a queue, or a retry wrapper, it very")
print("  often is not. Assume you pay for the whole response unless you have")
print("  measured otherwise.")
print("  Three things to hold on the cancellation path, in order:")
print("   1. no partial write     -- asserted in section 3")
print("   2. no partial side effect -- no tool call, no email, no downstream job")
print("   3. a record that the run was cancelled, with the tokens consumed, so")
print("      cost per accepted record stays honest (../tokenization.md)")
