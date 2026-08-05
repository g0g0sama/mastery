# stats-lab

A shared fixture for six micro modules covering Layer 2 (mathematical and ML
literacy). Not a module itself.

```powershell
cd modules\stats-lab
python population.py       # the fixture's own summary
python calibration_lab.py  # ../calibration-and-thresholds.md
python classical_lab.py    # ../classical-baselines.md      (~30 s, trains 100+ models)
python leakage_lab.py      # ../leakage-and-shift.md        (~50 s, 30 seeds + bootstraps)
python pca_lab.py          # ../dimensionality-reduction.md
python shapes_lab.py       # ../matmul-and-shapes.md
python entropy_lab.py      # ../entropy-and-perplexity.md
```

CPython 3.14, stdlib only. No NumPy — the power iteration in `pca_lab.py`, the
broadcasting rule in `shapes_lab.py` and the logistic regression in `models.py`
are all written out, which is the point rather than a constraint. Implementing
the broadcasting rule is the fastest way to stop being surprised by it.

| File | Role |
|---|---|
| `population.py` | 600 extraction records from a declared generative process |
| `models.py` | four classifiers that need no model call, and the scorer |
| `calibration_lab.py` | reliability, ECE, temperature scaling, and where a threshold comes from |
| `classical_lab.py` | five systems, accuracy against macro-F1, and the learning curve |
| `leakage_lab.py` | three splits, correction-biased labels, a rare class, and a mix shift |
| `pca_lab.py` | truncated SVD over the retrieval corpus; what the axes lost |
| `shapes_lab.py` | every shape in a forward pass, and two bugs that do not raise |
| `entropy_lab.py` | perplexity, predictive entropy, and KL as a drift alarm |

## Why a Layer 2 fixture exists at all

The map is explicit that Layer 2 rows are learned **inside** the module that
uses them, and that a row here should never be the active cycle on its own.
That instruction is followed: every lab scores a real artifact from another
fixture rather than a toy of its own.

- `pca_lab.py`, `shapes_lab.py` and section 1 of `entropy_lab.py` run on the
  seventeen Chinese documents and six queries in
  [../zh-retrieval-lab/](../zh-retrieval-lab/), with that fixture's own
  analyzers and metrics, so a recall number here is directly comparable with
  one in the Layer 6 modules.
- `calibration_lab.py`, `classical_lab.py`, `leakage_lab.py` and section 3 of
  `entropy_lab.py` run on `population.py`, whose records have the field names,
  event-type vocabulary and Chinese entity tokens of
  [../extraction-eval-sets/](../extraction-eval-sets/).

The directory exists because three of the six rows need more records than any
existing fixture has. Twelve gold records cannot carry a learning curve, a
calibration curve or a group-split comparison.

## What is real here

Stated per kind, because this fixture is the easiest in the repository to
over-read:

- **real** — every document, query, character count, term count and relevance
  judgment used by `pca_lab.py`, `shapes_lab.py` and section 1 of
  `entropy_lab.py`. Those are the retrieval fixture's Chinese text, and the
  perplexities, principal components and recall numbers computed from them are
  real arithmetic over real strings.
- **real, and a theorem** — several results here would hold on any dataset and
  are labelled where they appear: a monotone recalibration cannot change AUC; a
  per-query constant cannot reorder that query's own results; accuracy and
  macro-F1 can rank two systems oppositely under class imbalance; an unsmoothed
  language model has infinite perplexity on any held-out token it has not seen.
  The fixture makes these visible; it does not establish them.
- **generated from declared parameters** — every record in `population.py`.
  Base rates, the mix shift on day 60, per-type accuracy, per-type confidence
  bias, story clustering, keyword contamination and the labeller's notice rate
  are all constants at the top of that file. Nothing in it was observed.
- **derived** — every delta, interval, learning curve and cost figure the labs
  print from the above.

The magnitudes from `population.py` transfer to nothing. Read them as "this is
the shape of the effect and here is how to measure it on your own data", never
as "leakage costs four points".

## The two parameters that decide everything

Both are in `population.py` and both are worth changing to see what happens.

`CONTAMINATION` sets how many of the confusable type's keywords a document also
carries. At zero the six classes are linearly separable, every classifier in
`models.py` scores 0.99, and `classical_lab.py` reports a fact about the
generator instead of about classifiers. The first version of this fixture had
it at zero; the numbers looked excellent and meant nothing.

`STORY_SIZES` sets how documents cluster into near-duplicate groups. It is the
entire mechanism behind `leakage_lab.py`, and it is the property of real
corpora that is most often left out of a synthetic one.

## One thing the fixture does not have

A second labeller. `population.py` models a labeller who corrects extractor
output and notices some fraction of its errors, which is enough to measure the
*direction* and rough size of correction bias. It cannot measure agreement,
which is
[../inter-annotator-agreement.md](../inter-annotator-agreement.md)'s subject
and needs two real people.
