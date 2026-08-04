"""Prompt versioning: a prompt change gated by an eval run, not by reading it.

    python prompt_lab.py
"""
import hashlib
import json
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provider import PROMPT_VARIANTS, Provider, repair
from task import DOCUMENTS, record_correct, validate

DRAWS = 60
MODEL = "mid-1"


def score(version, docs=None):
    docs = docs or DOCUMENTS
    provider = Provider(MODEL)
    ok = n = 0
    per_slice = {}
    for doc_id, (_, gold) in docs.items():
        s = gold["event_type"]
        per_slice.setdefault(s, [0, 0])
        for a in range(DRAWS):
            r = provider.complete(doc_id, constrained=True, attempt=a,
                                  prompt_version=version)
            try:
                obj = json.loads(repair(r.text))
            except json.JSONDecodeError:
                obj = None
            good = obj is not None and not validate(obj) and record_correct(obj, gold)
            ok += good
            n += 1
            per_slice[s][0] += good
            per_slice[s][1] += 1
    return ok / n, {k: v[0] / v[1] for k, v in per_slice.items()}


print("=== 1. The diff, which is the part everyone reviews ===")
for version, variant in PROMPT_VARIANTS.items():
    print(f"  {version}: {variant['text'][-90:]!r}")
print()
print("  Reading that diff, v2 is obviously better. It fixes the single most")
print("  common extraction bug in this corpus -- the fetch date substituted for")
print("  the event date -- and it says so in one clear sentence. Predict the")
print("  aggregate change and the per-slice change before running section 2.")
print()

print("=== 2. The eval run ===")
agg = {}
slices = {}
for version in ("v1", "v2"):
    agg[version], slices[version] = score(version)
    print(f"  {version}  record accuracy {agg[version]:.4f}")
print(f"  delta {agg['v2'] - agg['v1']:+.4f}")
print()
print("=== 3. The same run, sliced by event type ===")
names = sorted(slices["v1"])
print(f"  {'slice':<20}{'v1':>8}{'v2':>8}{'delta':>9}")
print("  " + "-" * 45)
for s in names:
    d = slices["v2"][s] - slices["v1"][s]
    flag = "  <-- regression" if d < -0.05 else ""
    print(f"  {s:<20}{slices['v1'][s]:>8.3f}{slices['v2'][s]:>8.3f}{d:>+9.3f}{flag}")
print()
print("  The aggregate went up and one slice went down hard. That is what an")
print("  added instruction usually does: it moves probability mass toward the")
print("  case it names and away from the cases it does not. `regulation` events")
print("  are the ones where the event date genuinely IS the publication date --")
print("  a ministry announces a rule on the day the article runs -- so the new")
print("  sentence tells the model to distrust the right answer.")
print("  An aggregate-only gate ships this. A sliced gate asks a question first.")
print()
print("  SIZE WARNING: eight documents across six slices means each slice is one")
print("  or two documents sampled 60 times. That measures the model's variance")
print("  on those documents and says nothing about the slice as a population --")
print("  a second regulation document could behave completely differently. The")
print("  mechanism is the lesson here; the number is not transferable. A real")
print("  slice gate needs enough documents per slice to survive")
print("  ../eval-set-sample-size.md, which is the expensive part of doing this")
print("  properly and the reason most teams gate on the aggregate.")
print()

print("=== 4. The gate ===")
THRESHOLD = -0.05


def gate(before, after, slices_before, slices_after):
    failures = []
    if after < before:
        failures.append(f"aggregate {after - before:+.4f}")
    for s in slices_before:
        d = slices_after[s] - slices_before[s]
        if d < THRESHOLD:
            failures.append(f"slice {s} {d:+.4f}")
    return failures


failures = gate(agg["v1"], agg["v2"], slices["v1"], slices["v2"])
print(f"  aggregate rule:      {'PASS' if agg['v2'] >= agg['v1'] else 'FAIL'}")
print(f"  aggregate + slices:  {'PASS' if not failures else 'FAIL'}  {failures}")
print()
print("  Two gates, same data, opposite decisions. Which one is right depends on")
print("  a policy decision you have to make in advance and write down: is a")
print("  large loss on one document class acceptable in exchange for a small")
print("  gain everywhere? Sometimes yes. But that has to be a decision, made by")
print("  someone, recorded -- not the accidental output of averaging.")
print()

print("=== 5. The stamp that makes any of this recoverable ===")


def prompt_hash(version):
    return hashlib.sha256(
        PROMPT_VARIANTS[version]["text"].encode()).hexdigest()[:12]


for version in ("v1", "v2"):
    print(f"  {version}  sha256[:12] = {prompt_hash(version)}  "
          f"{len(PROMPT_VARIANTS[version]['text'])} chars")
print()
print("  Store that hash on every produced record, beside the pinned model")
print("  version from ../routing-and-fallback.md and the eval set version from")
print("  ../eval-set-versioning.md. Three hashes, and a score becomes")
print("  attributable; two of the three, and it is an anecdote.")
print()
print("  Note what the hash does NOT catch, which is the same blind spot")
print("  ../eval-set-versioning.md found: the prompt text can be byte-identical")
print("  while a variable interpolated into it, a retrieved passage, or a tool")
print("  description has changed. Hash the RENDERED prompt for one fixed probe")
print("  input, not the template, if you want the hash to mean what you think.")
print()
print("  And the ADR is the deliverable, not the number:")
print("    context   -- v2 adds a date instruction")
print("    measured  -- aggregate +, `regulation` slice -, on a frozen set,")
print("                 with the set hash and both prompt hashes")
print("    decision  -- ship / do not ship / ship with a routing exception")
print("    revisit   -- the condition that would reopen it")
print("  ../decisions/TEMPLATE.md is the shape. A prompt change that improved")
print("  the aggregate and was never written down is a change you cannot")
print("  attribute in six months, when it is the thing that broke.")
