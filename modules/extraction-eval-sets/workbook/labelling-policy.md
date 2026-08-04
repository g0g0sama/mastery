# Sinoscope labelling policy

**Policy version:** [fill in, for example v0.1.0]  
**Effective date:** [YYYY-MM-DD]  
**Policy owner:** [fill in]  
**Authoritative labels:** [fill in Sinoscope repository path or dataset ID]

Complete before bulk labelling. A policy change requires a new version, change-log entry, and an explicit decision before cross-version score comparison.

## Scope

**In-scope source documents:** [fill in]  
**Out of scope:** [fill in]  
**Unit of evaluation:** [one source document / one event / other]  
**Abstention rule:** [when an empty record is correct, versus a missing field]

## Field rules

| Field | Expected shape | Correctness / match rule | Normalization or linking | Evidence rule | Empty is correct when | Boundary / cost |
|---|---|---|---|---|---|---|
| actors | list of normalized entity names | [exact / normalized / linked] | [aliases, suffixes, linking] | [source span] | [fill in] | [recall ceiling or false-merge cost] |
| event_type | closed vocabulary or governed open text | [fill in] | [vocabulary version or open policy] | [fill in] | [fill in] | [edge-case cost] |
| time | event time at available granularity | [fill in] | [format, timezone, locale, partial-date rule] | [fill in] | [fill in] | [publication-time confusion cost] |
| location | normalized available granularity | [fill in] | [normalizer, geocoding, or no inference] | [fill in] | [fill in] | [ambiguity cost] |
| claims | source assertions, not implications | [unscored initially / rubric rule] | [atom and support rule] | [supporting span] | [fill in] | [rubric-agreement limitation] |
| source | URL, fetch time, field-level spans | [fill in] | [canonical URL and timestamp] | [fill in] | [normally never] | [provenance-loss cost] |
| confidence | separate model and labeller values | [fill in] | [scale, calibration, missing-value rule] | [fill in] | [fill in] | [calibration cost] |

## Required decisions

### Event vocabulary

**Choice:** [closed / open]  
**Vocabulary or governance rule:** [fill in]  
**Why scoreable:** [fill in]  
**Boundary cost:** [fill in]

### Actor matching

**Choice:** [exact surface string / normalized form / linked entity]  
**Procedure:** [fill in]  
**Recall ceiling or false-merge risk accepted:** [fill in]

| Ambiguity | Rule | Example reference | Cost |
|---|---|---|---|
| Multiple plausible actors | [fill in] | [fill in] | [fill in] |
| Relative or partial time | [fill in] | [fill in] | [fill in] |
| Conflicting statements | [fill in] | [fill in] | [fill in] |
| Unsupported implication | [fill in] | [fill in] | [fill in] |

## Change log

| Version | Date | Change | Why | Dataset impact | Re-labelling required? |
|---|---|---|---|---|---|
| [fill in] | [YYYY-MM-DD] | Initial policy | [fill in] | [fill in] | [yes / no] |

- [ ] Vocabulary and actor-matching choices are explicit.
- [ ] Every field has correctness, evidence, and empty-value rules.
- [ ] Two ambiguous cases were resolved before bulk labelling.
- [ ] A second labeller can apply this policy to a calibration sample.
