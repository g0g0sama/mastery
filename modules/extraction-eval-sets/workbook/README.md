# Sinoscope extraction-evaluation workbook

**Purpose:** Record real evaluation evidence for Sinoscope. This workbook contains no source documents, labels, model outputs, or scores.

**Status:** Not started. Templates do not close the cycle; only the five conditions in [current-cycle.md](../../../current-cycle.md#evidence-contract) do.

## Ordered work

1. Read the three named primary sources and complete [source-reading.md](source-reading.md).
2. Complete [labelling-policy.md](labelling-policy.md) before looking at or labelling the corpus.
3. Create labels in Sinoscope; record only the authoritative location and version in [dataset-holdout-register.md](dataset-holdout-register.md). Never add .jsonl files or results here.
4. Complete the seven tasks in the parent [lab](../lab/README.md), predict first, then run `python verify.py` until it reports `10/10 checks passed`.
5. Score the Sinoscope rules baseline and structured-output candidate. Run a seeded failure and record its prediction before seeing the result.
6. Freeze the holdout before tuning; spend it once and record its date and version.
7. Complete [results-and-handoff.md](results-and-handoff.md). Only after real measurements, copy [the ADR template](../../../decisions/TEMPLATE.md) to a numbered decision record.
8. One week later, answer the cold-recall prompt without notes; log wrong predictions in [failure-log.md](../../../failure-log.md).

## Evidence map

| Cycle condition | Workbook record | Required real-world proof |
|---|---|---|
| Implemented | Policy and handoff links | Validated Sinoscope record with surfaced schema failures |
| Verified | Dataset register and result stamps | 50+ labels, frozen holdout, repeatable scoring |
| Diagnosed | Seeded-failure section | Predicted and observed metric movement |
| Explained cold | Cold-recall section | Written answer a week later without notes |
| Used in a decision | ADR path | Measured Sinoscope change accepted or rejected |

## Boundary

The parent [explainer](../explainer.md), [lab](../lab/README.md), and [cards](../cards.md) teach the mechanism. This workbook is the project-transfer trail. Keep unknown paths, provider behavior, labels, results, and decisions as [fill in] until verified.
