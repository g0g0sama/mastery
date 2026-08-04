# NNNN -- Short title in the imperative

**Date:** YYYY-MM-DD
**Status:** proposed | accepted | superseded by [NNNN](NNNN-title.md)
**Project:** which system this changes
**Capability:** which row of [../capability-map.md](../capability-map.md) this
exercised

## Context

The situation that forced a decision. What was in place before, what stopped
working or was about to, and the constraint that rules out the obvious answer.
No solution vocabulary here.

## Options considered

1. **<option>** -- what it is, what it costs.
2. **<option>** -- what it is, what it costs.
3. **<option>** -- including the cheap baseline. If no baseline was measured, say
   so and treat the decision as provisional.

## Measurement

The eval set, its size, how it was labelled, and what was held out. Then the
numbers, before and after, on the same set:

| Metric | Baseline | Option A | Option B |
|---|---|---|---|
| ... | | | |

Include cost and latency. A quality gain bought with a 4x latency increase is a
different decision from the same gain at equal latency, and the table is where
that becomes visible.

## Decision

What was chosen, and the specific number that decided it.

## Consequences

What is now harder. What must be monitored. What would make this decision wrong
later -- name the observation that should trigger revisiting it, not "we will
review periodically".

## Failures observed

Where the chosen option still loses, from the error taxonomy. This section is why
the ADR is worth writing: it is the record of what the winning approach cannot
do, which is invisible in the summary metric.
