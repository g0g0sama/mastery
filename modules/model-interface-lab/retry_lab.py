"""Provider errors: which ones to retry, how, and what a retry costs you.

    python retry_lab.py

Time is simulated. Real sleeps would make the lab slow and would measure nothing
that the accumulated delay does not already show.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provider import (APITimeoutError, BadRequestError, ContentFilterError,
                      OverloadedError, Provider, ProviderError, RateLimitError,
                      ServerError)

# One script per document, so both policies face exactly the same failures.
# A shared script would let whichever policy burns calls faster consume the
# errors and look better -- a comparison artifact, not a result.
SCRIPTS = {
    "N01": [RateLimitError(retry_after=2.0),
            OverloadedError("upstream overloaded"),
            None],
    # Repeated, because that is what terminal means: the same request produces
    # the same rejection however many times you send it.
    "N02": [BadRequestError("max_tokens exceeds model limit")] * 4,
    "N03": [ServerError("internal error"), None],
}


def run_policy(name, policy):
    stats = {"calls": 0, "slept": 0.0, "ok": 0, "gave_up": 0}
    for doc, script in SCRIPTS.items():
        policy(Provider("mid-1", script=list(script)), doc, stats)
    print(f"  {name:<34}{stats['calls']:>7}{stats['slept']:>9.1f}s"
          f"{stats['ok']:>6}{stats['gave_up']:>9}")
    return stats


def naive(provider, doc, stats, attempts=4):
    """Retry everything, fixed delay. The policy everyone writes first."""
    for _ in range(attempts):
        try:
            stats["calls"] += 1
            provider.complete(doc)
            stats["ok"] += 1
            return
        except ProviderError:
            stats["slept"] += 1.0
    stats["gave_up"] += 1


def classified(provider, doc, stats, attempts=4, base=0.5, cap=8.0):
    """Retry transient errors only, with capped exponential backoff, and honour
    a server-supplied retry_after over your own arithmetic."""
    delay = base
    for attempt in range(attempts):
        try:
            stats["calls"] += 1
            provider.complete(doc)
            stats["ok"] += 1
            return
        except ProviderError as exc:
            if not exc.transient:
                stats["gave_up"] += 1
                return                     # retrying cannot change the outcome
            wait = exc.retry_after if exc.retry_after else min(delay, cap)
            stats["slept"] += wait
            delay *= 2
    stats["gave_up"] += 1


print("=== 1. Two policies against exactly the same failures ===")
print(f"  {'policy':<34}{'calls':>7}{'slept':>10}{'ok':>6}{'gave up':>9}")
print("  " + "-" * 66)
run_policy("retry everything, fixed delay", naive)
run_policy("classify + backoff + retry_after", classified)
print()
print("  Same outcomes -- two succeeded, one is unrecoverable under any policy --")
print("  for nine calls against six. The three wasted calls all went to the")
print("  BadRequestError: a malformed request retried four times is the same")
print("  malformed request, four times, at full price. A retry policy that")
print("  cannot distinguish transient from terminal is a cost multiplier bolted")
print("  onto your worst bugs, and it is silent because the end state is right.")
print()

print("=== 2. The error taxonomy, in the only two columns that matter ===")
print(f"  {'error':<22}{'status':>8}{'transient':>11}   {'what it means'}")
print("  " + "-" * 74)
rows = [
    (RateLimitError(), "you are sending too fast; retry_after is authoritative"),
    (OverloadedError(), "they are busy; back off and jitter"),
    (ServerError(), "their bug or yours; retry a bounded number of times"),
    (APITimeoutError(), "UNKNOWN outcome -- see section 3"),
    (BadRequestError(), "your bug; retrying reproduces it exactly"),
    (ContentFilterError(), "a RESULT about the input, not a failure"),
]
for err, meaning in rows:
    print(f"  {type(err).__name__:<22}{str(err.status or '-'):>8}"
          f"{str(err.transient):>11}   {meaning}")
print()
print("  ContentFilterError is the one that is always miscategorised. Counting")
print("  it as a failure buries a data problem inside a reliability metric, and")
print("  the alert that fires is the wrong alert. It belongs in the error")
print("  taxonomy of the extraction (../error-taxonomy.md), not in the retry")
print("  budget.")
print()

print("=== 3. The timeout, and why it needs an idempotency key ===")


class EventTable:
    def __init__(self):
        self.rows = []
        self.keys = set()

    def insert(self, doc, record, key=None):
        if key is not None:
            if key in self.keys:
                return "deduplicated"
            self.keys.add(key)
        self.rows.append((doc, record))
        return "inserted"


for use_key in (False, True):
    table = EventTable()
    provider = Provider("mid-1")
    doc = "N04"
    # First attempt: the response was produced and the connection dropped.
    # Your code saw a timeout. The provider saw a success -- and so did the
    # write it triggered, if the write happens provider-side or in a worker.
    table.insert(doc, provider.complete(doc).text,
                 key=f"{doc}:v1" if use_key else None)
    try:
        raise APITimeoutError("no response within 30s")
    except APITimeoutError:
        outcome = table.insert(doc, provider.complete(doc).text,
                               key=f"{doc}:v1" if use_key else None)
    print(f"  idempotency key {'on ' if use_key else 'off'}: "
          f"retry -> {outcome}, rows in table = {len(table.rows)}")
print("  A timeout is the one transient error whose outcome is unknown: the")
print("  request may have completed. Retrying it is only safe if the effect is")
print("  idempotent, which for 'append a row' it is not. The key has to be")
print("  derived from the WORK -- document id plus prompt version -- and not")
print("  from the attempt, or every retry mints a new key and dedupes nothing.")
print("  Same mechanism as ../patterns/08-database-patterns; the LLM-specific")
print("  part is only that timeouts here are common rather than rare.")
print()

print("=== 4. What retries do to an outage ===")
print("  Every client retrying a 529 three times turns a degraded provider into")
print("  a provider receiving 3x its normal load, at exactly the moment it can")
print("  least absorb it. Three rules, in order of how often they are missed:")
print("   - jitter. Synchronised retries re-converge into the same spike; a")
print("     random factor on the delay is what breaks the convoy.")
print("   - a circuit breaker. After N consecutive failures, stop calling and")
print("     fail fast for a cool-down. A retry policy without a breaker cannot")
print("     stop; it can only slow down.")
print("   - a budget, not a count. 'Three attempts' on a request that costs")
print("     $0.05 and takes 30 seconds is a different decision from three")
print("     attempts on a $0.0001 request. Cap total spend and total latency")
print("     per unit of WORK, and let the attempt count fall out of that.")
