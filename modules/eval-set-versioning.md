# Eval set and label versioning

**Micro module.** One mechanism, one experiment, three cards. Makes the
Measurement section of [../decisions/TEMPLATE.md](../decisions/TEMPLATE.md)
verifiable rather than asserted.

**Capability:** dataset and label versioning (Layer 1c, - -> Independent). Map
evidence to graduate: "An eval set with a version, a changelog, and a frozen
holdout."

---

## The problem

Six months from now, someone reads your ADR. It says record accuracy went from
0.50 to 0.62 and the change was shipped on that number. They re-run the scorer
today and get 0.41.

Did the system regress? Did somebody fix labels? Did the matching policy change?
The ADR cannot say, the score cannot say, and the person now has to choose
between re-deriving six months of history and ignoring the number. They will
ignore the number.

## The wrong model

**"The eval set is the data, so versioning the data is enough."**

It leaves out half the instrument. A score is a function of *three* things --
the labels, the matching policy, and the system -- and only the third one is what
you meant to measure. Version the labels alone and a policy edit still silently
rewrites every historical number.

The related error is **hashing the policy's source file.** It feels rigorous and
it misses everything that changes behaviour without changing that file: a config
value, a dependency upgrade, an environment variable, a normalizer swapped at
runtime. Hash what the instrument *does*, not what its source looks like.

## The mechanism

Stamp every recorded score with three fingerprints:

```text
gold             canonical JSON of the scored fields, hashed
policy_behavior  the normalizers run over a FIXED PROBE SET, hashed,
                 plus the closed vocabulary
policy_src       the policy file, hashed -- useful for a diff, not sufficient
```

Then make comparison refuse rather than mislead. Given two stamped scores:

- **gold differs** -> the target moved. Not a regression; re-baseline.
- **policy_behavior differs** -> the ruler moved. Re-score the old system under
  the new policy before drawing any conclusion.
- **neither differs** -> the delta is your system. This is the only case where
  the number means what the ADR says it means.

The probe set is the trick worth keeping. It is a fixed list of inputs pushed
through every normalizer, with the outputs hashed -- a behavioural fingerprint
that catches a change however it was introduced, including ones that never touch
a tracked file.

## The experiment

`extraction-eval-sets/lab/version.py`. Requires all five lab tasks.

Three snapshots: the baseline, one where the normalizers are swapped at runtime
with the file untouched, and one where a single gold label is corrected.

**Predict before running: which of the three hashes moves in each scenario, and
whether the two changes are distinguishable from the score alone.**

```powershell
cd modules\extraction-eval-sets\lab
python version.py
```

Actual:

```text
scenario                                  gold  policy_src  policy_beh  rec acc
baseline                            0413553f59  27ce4abc32  0ef99881dc   0.5000
policy changed at runtime           0413553f59  27ce4abc32  84aa21b9a7   0.4167
gold label corrected (R09)          3ebfbfe44e  27ce4abc32  0ef99881dc   0.4167
```

Two completely different causes -- the ruler moved, the target moved -- and
**they produce the identical score, 0.4167.** From the number alone the two are
indistinguishable, and both look exactly like "the system got worse". That is the
failure this module exists to prevent, and it is a coincidence only in the sense
that any two changes can land on the same number; the point is that nothing in
the score tells you which happened.

The stamps do:

```text
compare(baseline, policy changed at runtime) -> INCOMPARABLE: the POLICY changed
compare(baseline, gold label corrected)      -> INCOMPARABLE: the LABELS changed
compare(baseline, nothing changed)           -> comparable: +0.0000 -- this is the system
```

And read the middle column. `policy_src` is **identical in all three rows** -- the
runtime swap never touched the file. A pipeline that versioned the source hash
would have declared the first scenario comparable and reported a 0.083 regression
that no system change produced.

## Boundary

- A fingerprint proves two runs used the same instrument. It does not prove the
  instrument is *good*, and a stable hash on a wrong policy is stability of the
  wrong thing.
- The probe set only covers what it probes. A normalizer change affecting only
  inputs absent from the probes is invisible; grow the probe set whenever a
  policy decision is added, and treat that growth as a version bump itself.
- Hashes tell you *that* something changed, not what. Pair them with a changelog
  entry per version -- one line, what changed and why -- because a hash diff is
  not a reason.
- The holdout needs its own stamp and its own spend date. See
  [extraction-eval-sets/README.md](extraction-eval-sets/README.md); a holdout
  re-labelled after being scored is a new holdout.
- Set versions are cheap; skipping them is only cheap until the first argument
  about a historical number, at which point the cost is the whole record.

## Cards

### 1. [mechanism] A recorded eval score is a function of three things. Name them, and say which one you actually intended to measure.

**Answer:** The labels, the matching policy, and the system. Only the system is
the intended measurement.

**Why:** Two scores are comparable only when the first two are held fixed, so
each recorded number needs a stamp for the labels and for the policy -- otherwise
a label fix or a normalizer edit is indistinguishable from a regression.

**Boundary:** In this module's data a policy change and a label correction
produce the identical score, from opposite causes. The number alone cannot
separate them; only the stamps can.

**Tags:** `eval-sets` `mechanism` `general-principle`

---

### 2. [failure] Your pipeline versions the matching policy by hashing `policy.py`. Which changes slip through?

**Answer:** Every behavioural change that does not edit that file -- a config
value, a dependency upgrade, an environment variable, a normalizer monkeypatched
at runtime.

**Why:** The source hash answers "was this file edited", not "does the instrument
behave the same". A run that silently changed behaviour is then declared
comparable and its delta is attributed to the system.

**Boundary:** Fix by hashing behaviour: push a fixed probe set through every
normalizer and hash the outputs. Keep the source hash too -- it is useful for
producing a diff once the behavioural hash tells you something moved.

**Tags:** `eval-sets` `failure` `general-principle`

---

### 3. [best-practice] What should a scorer do when it is asked to compare two runs carrying different set versions?

**Answer:** Refuse, and name which fingerprint differs -- labels or policy --
because the diagnosis and the remedy differ.

**Why:** Labels differing means the target moved and you re-baseline. Policy
differing means the ruler moved and you must re-score the old system under the
new policy before concluding anything. Silently reporting a delta invites the
change to be attributed to the system.

**Boundary:** Refusing is only useful if re-scoring under the new policy is
cheap. Keep predictions cached per system so a policy change can be replayed
against stored output rather than re-run.

**Tags:** `eval-sets` `best-practice` `general-principle`
