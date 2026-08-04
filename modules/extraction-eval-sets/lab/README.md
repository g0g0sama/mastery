# Lab -- scoring an extraction set

**Goal:** after this lab you can write a matching policy, compute per-field
precision and recall over set-valued and scalar fields, choose between micro and
macro averaging with a reason, separate omission from invention, and say which
number a decision should rest on.

**Time:** ~90 min. **Files you edit:** `policy.py` and `scoring.py` only.

## Setup

No third-party packages. CPython 3.14 on Windows, stdlib only -- `unicodedata`
and `re` do all the work. Nothing here calls a model or the network: this lab is
about the measuring instrument, and an instrument you cannot run twice with the
same result is not one.

```powershell
cd modules\extraction-eval-sets\lab
python verify.py        # expect 0/10 until you implement the five tasks
```

The data is Chinese text. No script prints a raw field value -- record ids are
the currency of every report -- because a redirected stdout on Windows falls back
to the ANSI codepage and raises `UnicodeEncodeError` on the first CJK character.
The `sys.stdout.reconfigure(...)` line at the top of each script is boilerplate
guarding the same thing; ignore it.

## What is here

| File | Role |
|---|---|
| `gold.py` | 12 hand-labelled records. A scorer fixture, **not** an eval set |
| `predictions.py` | three systems' output over the same 12 documents |
| `policy.py` | the matching policy. **You implement two normalizers** |
| `scoring.py` | the scorer. **You implement five functions** |
| `predict.py` | five questions to answer in writing first |
| `verify.py` | checks each task, then the full report |
| `break_it.py` | three seeded failures |
| `kappa.py` | extension -- inter-annotator agreement. Standalone |
| `interval.py` | extension -- bootstrap interval. Needs all five tasks |
| `errors.py` | extension -- per-error dump for classification. Needs task 1 |
| `graders.py` | extension -- gold-free graders and their precision. Needs tasks 1-2 |
| `adversarial.py` | extension -- four hypothesis-driven records. Needs all five |
| `gate.py` | extension -- a CI gate that blocks a change. Needs all five |
| `rubric.py` | extension -- judge-vs-human agreement. Standalone |
| `ranking.py` | extension -- recall@k, MRR, nDCG. Standalone |
| `version.py` | extension -- set and policy fingerprints. Needs all five |

The nine extension scripts belong to micro modules that build on this lab. Run
them after step 5, in this order:

| Script | Module |
|---|---|
| `kappa.py` | [../../inter-annotator-agreement.md](../../inter-annotator-agreement.md) |
| `errors.py` | [../../error-taxonomy.md](../../error-taxonomy.md) |
| `graders.py` | [../../deterministic-graders.md](../../deterministic-graders.md) |
| `rubric.py` | [../../rubric-graders.md](../../rubric-graders.md) |
| `adversarial.py` | [../../adversarial-examples.md](../../adversarial-examples.md) |
| `interval.py` | [../../eval-set-sample-size.md](../../eval-set-sample-size.md) |
| `gate.py` | [../../eval-gates.md](../../eval-gates.md) |
| `version.py` | [../../eval-set-versioning.md](../../eval-set-versioning.md) |
| `ranking.py` | [../../retrieval-metrics.md](../../retrieval-metrics.md) |

`adversarial.py`, `gate.py` and `version.py` mutate the shared gold and
prediction data in place and restore it in a `finally` block, exactly as
`break_it.py` does; the rest only read. Running any of them leaves the baseline
numbers unchanged -- confirm with `python scoring.py` if a run was interrupted.

`kappa.py`, `rubric.py` and `ranking.py` carry their own constructed fixtures and
do not touch the 12-record set at all.

Twelve records has no statistical power and was built to exercise specific metric
behaviours. The 50 in the cycle's evidence contract come from your own documents.
What this gives you is something to point a scorer at while you are still writing
the scorer -- which is the right order, because the policy decisions you make
here are the ones you would otherwise make silently on record 37.

## Step 1 -- Read and predict

Read `policy.py` top to bottom first. Its header is five numbered decisions with
their costs, and it is the artifact this lab is really teaching you to write.
Then read `gold.py` and `predictions.py`.

Answer `predict.py`'s five questions in writing, then run it:

```powershell
python predict.py
```

Verify: you have five written answers, including arithmetic for question 4.

## Step 2 -- The normalizers (`policy.py`)

Implement `normalize_actor` and `normalize_location`.

The ordering constraint in `normalize_actor` is the part that bites: NFKC first,
because it folds `（ＣＡＴＬ）` to `(CATL)` and lets an ASCII-only pattern strip
it. Do it the other way round and the full-width parenthetical survives.

`normalize_location` reduces a place name to its most specific administrative
component, so `福建省宁德市`, `宁德市` and `宁德` all compare equal.

```powershell
python verify.py
```

Verify: checks `1a` and `1b` pass. Note what `1a`'s last assertion demands --
`华为` and `华为技术有限公司` must **not** match. That is policy decision 2, and
it costs you real recall on purpose.

## Step 3 -- Counts and averages (`scoring.py`)

Implement `counts_for_field`, then `micro_average` and `macro_average`.

The trick that removes every special case: treat a scalar field as a set of size
0 or 1. Precision and recall are then defined identically for `actors` and for
`event_type`, and "predicted nothing" stops being a division by zero.

```powershell
python verify.py
```

Verify: `2`, `3a`, `3b` pass. Check `3b`'s two assertions carefully -- they pin
down the two conventions macro averaging makes on your behalf.

## Step 4 -- Outcomes and acceptance (`scoring.py`)

Implement `outcome` and `record_accepted`, then:

```powershell
python verify.py     # expect 10/10
python scoring.py
```

Verify: 10/10, and three reports printed. Read them side by side before going on.
Compare your five written predictions against these five facts:

1. The rules baseline's `event_type` micro precision is `0.0000` and its **macro
   precision is `1.0000`**, on a system that never once predicted the field.
2. `model_a` and `model_b` differ by 0.008 in actors micro F1 and have the
   **identical** record accuracy of 0.5000. The numbers that separate them are
   `tp/fp/fn` -- `20/3/3` against `18/0/5` -- and the outcome split.
3. The rules baseline's location micro F1 is `1.0000`, computed on `n_scored`
   = 10 -- and the two dropped records are the only two on which its location
   was wrong.
4. Four fields at roughly 0.9 F1 give record accuracy 0.5, not 0.9.
5. The free baseline's cost per accepted record is `n/a`, because it accepted
   nothing. Cost per call would have ranked it first.

Any of those five that you did not predict goes in `../../failure-log.md` now,
with the model that produced the wrong prediction -- not the corrected fact.

## Step 5 -- Break it

```powershell
python break_it.py          # read all three prompts, predict in writing
python break_it.py 1
```

Break 1 replaces every normalizer with `str.strip()`. No prediction changes, no
label changes, no extractor code changes. Predict the symptom before running.

Expected: `model_a`'s location micro F1 falls from `1.0000` to `0.5000` and
`model_b`'s from `0.9565` to `0.7826` -- so the ranking on that field **inverts**,
because `model_a` was the system emitting `福建省宁德市` and relying on the
normalizer to earn the match. The rules baseline does not move at all: its output
already matched the gold surface form, so it never exercised the normalizer. The
system you sanity-check against is the one system this class of change cannot
break, which is why it ships.

Then run breaks 2 and 3, predicting each first. Break 2 is a `%d/%m` locale
transposition in the extractor; break 3 is a producer that starts emitting
datetimes where it used to emit dates. In both, watch `[validity]`.

Verify: after break 3 you can state, in one sentence, why a field at exactly
`0.0000` with validity at `1.0000` points at the policy rather than the model.

## Stretch

No solutions given.

1. **Fix the denominator.** Per-field scores currently exclude invalid records.
   Add a second scoring mode that counts an invalid record as a total miss (all
   gold items `fn`) and report both. Does the ranking of the three systems
   change? Which mode would you put in a weekly report, and which in a bug
   report?
2. **Split "wrong".** `model_b`'s actors outcome split shows `9/1/2` -- two
   "wrong" records that contain zero false positives, because a partial set
   match lands in the same bucket as an invention. Add a fourth outcome that
   distinguishes them, and say which of the two you would rather have.
3. **Bootstrap the interval.** Resample the 12 records with replacement 1000
   times and report a 95% interval on `model_a`'s actors micro F1. Then answer
   the question the cycle's evidence contract will ask you: with 50 records, is
   a 3-point gain real?
4. **Calibration.** `predictions.py` carries each system's `confidence`. Compute
   accuracy per confidence decile for `model_a` and `model_b`. One of them is
   confidently wrong; find the threshold at which its output would be safe to
   store unreviewed, and the recall you would pay for it.

## Cleanup

Nothing to undo. No processes, no ports, no files written outside this
directory. `break_it.py` restores every mutation in a `finally` block, so a
scorer run after a break gives the baseline numbers again -- confirm that with
`python scoring.py` if you interrupted one mid-run.
