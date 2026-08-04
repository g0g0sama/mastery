# Dataset and holdout register

**Dataset ID:** [fill in]  
**Dataset version:** [fill in]  
**Authoritative Sinoscope location:** [fill in repository path or dataset URI]  
**Owner:** [fill in]

Do not copy labels, source documents, predictions, .jsonl files, or result directories into this repository. This register points to the authoritative Sinoscope artifacts.

## Sampling and composition

| Item | Value | Rationale / source |
|---|---|---|
| Target labelled-record count | 50 or more | Cycle minimum; not enough to resolve small effects |
| Actual labelled-record count | [fill in] | [fill in] |
| Candidate population | [fill in] | [fill in] |
| Sampling method | [random / stratified / time-window / other] | [fill in] |
| In-scope event records | [fill in] | [fill in] |
| Negative records | [fill in] | [hypothesis] |
| Near-miss / distractor records | [fill in] | [hypothesis] |
| Out-of-vocabulary records | [fill in] | [hypothesis] |
| Second-labeller calibration sample | [fill in, at least 10 where feasible] | [fill in] |

## Split and holdout protocol

**Development-set location:** [fill in]  
**Frozen-holdout location:** [fill in]  
**Split method and seed or deterministic selection rule:** [fill in]  
**Who may inspect the holdout before the final run:** Nobody.

| Event | Date | Person | Dataset version | What was accessed | Consequence |
|---|---|---|---|---|---|
| Holdout frozen | [YYYY-MM-DD] | [fill in] | [fill in] | [identifier only] | Holdout eligible |
| Holdout spent | [YYYY-MM-DD or not yet] | [fill in] | [fill in] | [final score run] | [eligible / now a development set] |

If a person inspects a frozen-holdout item while debugging or tuning, mark it spent. Create a fresh holdout; it cannot be partially valid.

## Version stamps

| Stamp | Value | How computed | Captured on |
|---|---|---|---|
| Gold hash | [fill in] | [exact command or procedure] | [YYYY-MM-DD] |
| Behavioural policy hash | [fill in] | Fixed probe set through active normalizers | [YYYY-MM-DD] |
| Policy version | [fill in] | See labelling-policy.md | [YYYY-MM-DD] |
| Schema version | [fill in] | [source] | [YYYY-MM-DD] |
| Extraction implementation revision | [fill in] | [commit or release] | [YYYY-MM-DD] |

Compare scores only when the gold and behavioural-policy stamps match, or after re-scoring under one shared version.

## Dataset change log

| Version | Date | Change | Why | Affected split | Re-labelling or re-scoring required? |
|---|---|---|---|---|---|
| [fill in] | [YYYY-MM-DD] | Initial dataset | [fill in] | [development / holdout] | [yes / no] |

- [ ] Policy version was fixed before bulk labelling.
- [ ] Dataset has 50+ labels or an explicit collection plan.
- [ ] Negative or adversarial records measure abstention.
- [ ] Holdout is separated from development.
- [ ] Gold and behavioural-policy stamps were captured before comparison.
