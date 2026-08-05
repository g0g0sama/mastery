# ops-lab

A shared fixture for seven micro modules covering Layer 9 (production AI and
LLMOps). Not a module itself.

```powershell
cd modules\ops-lab
python build_lab.py       # ../reproducible-builds.md          (~13 s, sleeps and spawns)
python secrets_lab.py     # ../config-and-secrets.md
python logging_lab.py     # ../structured-logging-tracing.md
python registry_lab.py    # ../model-prompt-registry.md
python cost_lab.py        # ../metrics-and-cost-monitoring.md
python drift_lab.py       # ../drift-and-degradation.md
python dlq_lab.py         # ../failure-queues-and-replay.md
```

CPython 3.14, stdlib only. `ops.py` reuses the fake provider and the extraction
task from [../model-interface-lab/](../model-interface-lab/) via a `sys.path`
insert, so a record produced here is the same kind of record the Layer 4 and
Layer 7 modules produce, and its token counts and costs come from the same
price table.

| File | Role |
|---|---|
| `ops.py` | the release timeline, one request end to end, and the shared statistics |
| `build_lab.py` | two builds of one source tree, then one artifact behaving two ways |
| `secrets_lab.py` | eight egress channels for one key, four defence levels, and configuration |
| `logging_lab.py` | eight incident questions against three logging styles; sampling, volume, bias |
| `registry_lab.py` | five levels of stamping against sixty days of records |
| `cost_lab.py` | three denominators, four detectors, and the incident a spend alert misses |
| `drift_lab.py` | a scheduled eval two ways, gold-free proxies, input drift, a stale holdout |
| `dlq_lab.py` | what a dead letter has to contain, and what a replay writes |

## What is real here

Different from the other fixtures, and worth stating per kind:

- **real** -- the filesystem, zip containers, hashing, subprocess environments,
  exception frames, JSON serialization and its byte counts, and every
  arithmetic result computed from those. Section 1 of `build_lab.py` and
  section 1 of `secrets_lab.py` are measurements of this machine.
- **real, with a declared failure distribution** -- every record: outcomes,
  token counts, costs, parse and validation failures, and correctness against
  gold all come from `../model-interface-lab/provider.py`, whose own failure
  weights are asserted rather than discovered. That caveat propagates into
  every quality number here.
- **declared** -- request volumes, wall-clock latencies, injected provider
  failure rates, prices per GB of logs, the weekly seasonality, the release
  timeline, and the day the provider reskills the `mid-1` alias.
- **derived** -- costs, detection delays, series counts, replay fractions,
  amplification factors, and every delta the labs print.

No network, no container runtime, no broker, no key, no provider. The one
failure this fixture can cause is a reader mistaking a declared volume for a
measured one.

## The timeline every lab shares

Sixty days, in `ops.RELEASES`. Three things happen on it and only two are
deploys:

```text
day 0   r1   code a11f3c9, prompt v1
day 12  r2   code b27e004, prompt v2, rolled out as a 4-day canary
day 30  r3   code c8d1a55, constrained decoding, schema 1.1
day 45  --   the provider reskills what `mid-1` points at. No deploy.
day 52  r4   code d90bb12, r3's constrained flag rolled back
```

Day 45 is the fixture's centre of gravity. It is the change with no artifact,
no config diff, no log line and no field to record it in, and four of the seven
modules are about some system's inability to see it: the build hash cannot, the
declared stamp cannot, the spend alert cannot, and no gold-free proxy can. The
scheduled eval run can, and that is the argument the layer exists to make.

## Read in this order

1. `reproducible-builds` -- can you ship the same thing twice, and is "the same
   thing" even the unit that decides behaviour
2. `config-and-secrets` -- what must not be inside what you shipped, and the
   other 95% of configuration, which is where the outages are
3. `structured-logging-tracing` -- what the running system emits, and what has
   to be in it before an incident can be answered
4. `model-prompt-registry` -- the identity stamp on each output row, without
   which no later number can be attributed to anything
5. `metrics-and-cost-monitoring` -- aggregation over those events, the
   denominator that decides, and what to put an alarm on
6. `drift-and-degradation` -- whether the quality is still there, and which
   instrument can tell
7. `failure-queues-and-replay` -- what happens to what failed, and whether a fix
   can be applied to it afterwards

The order is a dependency chain, not a preference: 4 before 5 because an
aggregate you cannot attribute is not evidence; 5 before 6 because drift
detection is alerting with a quality metric in it; 7 last because a replay's
hardest question -- which configuration the replayed record belongs to -- is
the registry's question.

## What this fixture cannot show

- Anything about a real container runtime, orchestrator, log platform, message
  broker or secret manager. Every one of those is simulated to the depth needed
  for one measurement and no further.
- Real latency, real throughput, real cost at scale. Volumes are declared; see
  [../serving-lab/](../serving-lab/) for the layer where timing is measured.
- Whether a real provider silently changes a model behind an alias, how often,
  and with what notice. The fixture asserts that it does, because the
  interesting question is what your system could detect if it did.
- Anything about organizations: who owns the alert, who drains the queue, who
  approves a prompt change. Half of Layer 9 in practice, and none of it here.

A module here is evidence of exposure, not of level. Levels move in
[../../capability-map.md](../../capability-map.md), and only on the five
conditions in the cycle's evidence contract.
