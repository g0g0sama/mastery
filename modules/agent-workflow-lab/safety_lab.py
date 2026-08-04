"""Prompt injection, untrusted content, and the approval boundary.

    python safety_lab.py
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from agent import (ApprovalQueue, Budget, DOC_PASSAGES, PASSAGES, Store, Trace,
                   check, extract, fence, retrieve, send_alert, store)
from provider import Provider
from task import DOCUMENTS

print("=== 1. Where the attacker actually is ===")
for pid, text in PASSAGES.items():
    tag = "  <-- payload" if pid in ("P03", "P05") else ""
    print(f"  {pid}  {text}{tag}")
print()
print("  Nobody typed these. P03 and P05 are retrieval context: a fetched page,")
print("  a supplier PDF, a scraped registry row. Direct injection -- a user")
print("  typing 'ignore your instructions' -- is the version that gets")
print("  demonstrated and the version that matters least, because the user is")
print("  usually attacking their own session. INDIRECT injection arrives")
print("  through content your own pipeline retrieved on behalf of a victim, and")
print("  it is the one your corpus is full of.")
print()
print("  P05 is the more interesting payload. It contains no imperative aimed at")
print("  a model -- it reads as an editorial note about how to record dates.")
print("  A filter looking for 'ignore previous instructions' does not see it,")
print("  and a human reviewing the corpus does not either.")
print()

print("=== 2. A run with no isolation ===")
st, approvals = Store(), ApprovalQueue()
for doc_id in ("N01", "N04"):
    trace = Trace(doc_id)
    provider, budget = Provider("mid-1"), Budget()
    passages = retrieve(doc_id, trace, isolate=False)
    record = extract(doc_id, passages, provider, budget, trace,
                     obey_injection=True)
    gold = DOCUMENTS[doc_id][1]
    hijacked = trace.events[-1]["injected_by"]
    print(f"  {doc_id}: confidence={record.get('confidence')} "
          f"(gold {gold['confidence']})  date={record.get('date')} "
          f"(gold {gold['date']})")
    print(f"        schema violations={check(record, trace)}  "
          f"injected_by={hijacked}")
print()
print("  Both records are schema-valid. One of them reports confidence 1.0 on a")
print("  fabricated certainty and the other silently substitutes the fetch date")
print("  for the event date, which is the exact failure mode")
print("  ../structured-outputs.md measured as a model error. It is now an")
print("  ATTACK with the same signature, and no grader in this repo can tell")
print("  the two apart from the output alone.")
print()

print("=== 3. Delimiting helps and does not solve ===")
print(f"  fenced form of P03:\n    {fence(PASSAGES['P03'])[:88]}...")
print()
print("  What fencing buys: the model can now tell content from instruction, so")
print("  a well-behaved model usually declines. What it does not buy: anything")
print("  at all against a model that does not, because the fence is a request")
print("  written in the same channel as the attack. There is no privileged")
print("  channel in a prompt. Everything is text, and precedence between two")
print("  pieces of text is a behaviour, not a guarantee.")
print()
print("  So fencing is a mitigation and never a control. The controls are")
print("  structural, and there are only three that survive contact:")
print("   1. the model's output cannot authorize anything (section 4);")
print("   2. tools with irreversible effects are gated (section 5);")
print("   3. untrusted content never shares a context with a privileged tool.")
print()

print("=== 4. Authorization outside the model ===")


def naive_store(record, principal):
    """Wrong. The decision is a property of the record the model produced."""
    if record.get("confidence", 0) >= 0.9:
        return "written"
    return "queued for review"


ALLOWED = {"analyst": {"events:read"}, "ingest": {"events:read", "events:write"}}


def guarded_store(record, principal):
    """Right. The decision is a property of the CALLER, checked in code."""
    if "events:write" not in ALLOWED.get(principal, set()):
        return "denied"
    return "written"


poisoned = {"event_type": "regulation", "actors": ["x"], "date": "2026-03-11",
            "confidence": 1.0}
for principal in ("analyst", "ingest"):
    print(f"  {principal:<10} naive: {naive_store(poisoned, principal):<20}"
          f"guarded: {guarded_store(poisoned, principal)}")
print()
print("  The naive check reads a field the attacker controls, so the injection")
print("  in section 2 -- 'set confidence to 1.0' -- was not a data-quality bug.")
print("  It was a privilege escalation with a schema. The guarded check is")
print("  provable by reading twelve lines of Python and never reading a prompt,")
print("  which is the map's evidence line for the Layer 10 row.")
print()

print("=== 5. The approval boundary ===")
trace = Trace("N01")
print(f"  unapproved: {send_alert('稀土出口管制升级', approvals, trace)}")
print(f"  approved:   {send_alert('稀土出口管制升级', approvals, trace, approved=True)}")
print(f"  queue: {approvals.pending}")
print()
print("  send_alert is irreversible: there is no API call that unsends it. So")
print("  the model may PROPOSE it and may not PERFORM it, and the difference is")
print("  enforced by the tool rather than by the prompt. Note what the queue")
print("  entry has to carry to be approvable -- the action, the payload, and")
print("  the reason -- because an approval UI that shows a human 'the agent")
print("  wants to send an alert' with no payload trains them to click yes.")
print()

print("=== 6. Least privilege, per tool, written down before granting ===")
print(f"  {'tool':<16}{'reads':<20}{'writes':<16}{'reversible':<18}{'in-loop?'}")
print("  " + "-" * 74)
rows = [
    ("retrieve", "corpus", "nothing", "n/a", "yes"),
    ("lookup_company", "registry", "nothing", "n/a", "yes"),
    ("store", "nothing", "events table", "yes, by key", "yes, idempotent"),
    ("send_alert", "nothing", "email/slack", "NO", "NEVER"),
    ("delete_record", "nothing", "events table", "no (audit only)", "NEVER"),
]
for row in rows:
    print(f"  {row[0]:<16}{row[1]:<20}{row[2]:<16}{row[3]:<18}{row[4]}")
print()
print("  The last two columns are the whole policy. A tool that is irreversible")
print("  and in-loop is an incident with a schedule; the table is what makes")
print("  that combination visible before it is granted rather than after.")
print()
print("  And the boundary the table protects is narrower than it looks: it")
print("  covers what the agent can DO, not what it can SAY. Model output that")
print("  reaches a shell, a SQL string, an HTML page, or another agent's prompt")
print("  is untrusted input at that destination too -- the same rule as a tool")
print("  result, pointed the other way.")
