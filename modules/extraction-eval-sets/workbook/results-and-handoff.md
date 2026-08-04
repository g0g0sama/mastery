# Results and decision handoff

Complete only after the Sinoscope run has real, repeatable measurements. Leave placeholders empty until then. Do not create a numbered ADR before these results support a decision.

## Run identity

| Item | Value |
|---|---|
| Run date | [YYYY-MM-DD] |
| Dataset ID and version | [fill in] |
| Gold hash | [fill in] |
| Behavioural policy hash | [fill in] |
| Schema version | [fill in] |
| Sinoscope implementation revision | [fill in] |
| Provider and model version | [fill in] |
| Prompt or extraction configuration revision | [fill in] |
| Development or frozen holdout | [fill in] |

## Systems compared

| System | Purpose | Configuration / revision | Cost basis | Latency basis |
|---|---|---|---|---|
| Rules baseline | Establish what needs no model | [fill in] | [fill in] | [fill in] |
| Structured-output extraction | Candidate system | [fill in] | [fill in] | [fill in] |
| Additional candidate, if any | [fill in] | [fill in] | [fill in] | [fill in] |

## Results

Record n_scored beside every field. Do not average incomparable dataset or policy versions.

| Metric | Rules baseline | Candidate | Additional candidate | Interpretation |
|---|---|---|---|---|
| Schema-validity rate | [fill in] | [fill in] | [fill in] | Gate only, not content quality |
| actors precision / recall / F1 | [fill in] | [fill in] | [fill in] | [fill in] |
| event_type precision / recall / F1 | [fill in] | [fill in] | [fill in] | [fill in] |
| time precision / recall / F1 | [fill in] | [fill in] | [fill in] | [fill in] |
| location precision / recall / F1 | [fill in] | [fill in] | [fill in] | [fill in] |
| claims score or explicitly unscored | [fill in] | [fill in] | [fill in] | [fill in] |
| Micro and macro averages | [fill in] | [fill in] | [fill in] | [fill in] |
| Complete-record accuracy | [fill in] | [fill in] | [fill in] | [fill in] |
| Empty-vs-wrong split | [fill in] | [fill in] | [fill in] | [fill in] |
| Cost and latency per accepted record | [fill in] | [fill in] | [fill in] | [fill in] |

## Seeded failure and error taxonomy

**Prediction made before the run:** [fill in]  
**Seeded failure:** [field coercion / flattened nested list / locale date / other]  
**Observed metric movement:** [fill in]  
**Wrong model or unexpected mechanism:** [fill in]

Add the wrong model to [failure-log.md](../../../failure-log.md) before looking up an explanation.

| Error class | Count | Example IDs in Sinoscope | First suspected cause | Next experiment |
|---|---|---|---|---|
| [fill in] | [fill in] | [fill in] | [fill in] | [fill in] |
| [fill in] | [fill in] | [fill in] | [fill in] | [fill in] |
| [fill in] | [fill in] | [fill in] | [fill in] | [fill in] |

## Decision handoff

**Decision question:** [fill in]  
**Chosen option or rejection:** [fill in]  
**Specific metric and set version that decided it:** [fill in]  
**What the winning option still loses on:** [fill in]  
**Monitoring condition that would reopen the decision:** [fill in]  
**ADR path:** [fill in ../../../decisions/0001-short-title.md after copying the template]

Create the ADR only after this section names a real decision and supporting number. Include failure taxonomy and version stamps in its measurement section.

## Cold recall -- one week after the run

Without notes, explain why per-field precision and recall diagnose a problem that complete-record accuracy hides, and when complete-record accuracy is more decision-relevant.

**Date attempted:** [YYYY-MM-DD]  
**Answer:** [fill in]  
**Could I explain the difference without the module?** [yes / no]
