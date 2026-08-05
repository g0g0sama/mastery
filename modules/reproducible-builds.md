# Reproducible builds and deploys

**Micro module.** One mechanism, one experiment, three cards. Runs against
[ops-lab/](ops-lab/).

**Capability:** Containerization and CI/CD (Layer 9, Working -> Independent).
Map evidence: "Reproducible build and deploy of a model-backed service."

---

## The problem

The map row says *reproducible build and deploy of a model-backed service*, and
the two halves of that phrase are different problems. The first is about bytes
and is solved by known techniques. The second is about a service most of whose
behaviour is decided outside the artifact, and no amount of build hygiene
touches it.

## The mechanism

**Two builds of identical source do not produce identical bytes, and nothing
warns you.** Same machine, same interpreter, same command, two fresh checkouts
a few seconds apart:

```text
build 1: 36f35ea80220b066   build 2: 2e1ec288765ddbe5   DIFFERENT
every file's CONTENT identical (excluding build_info): True

entry                     mtime in A              mtime in B              equal?
Dockerfile                (2026, 8, 5, 8, 56, 0)  (2026, 8, 5, 8, 56, 2)  NO
requirements.txt          (2026, 8, 5, 8, 56, 0)  (2026, 8, 5, 8, 56, 2)  NO
app/extract.py            (2026, 8, 5, 8, 56, 0)  (2026, 8, 5, 8, 56, 2)  NO
```

Git records content, not timestamps, so a checkout stamps every file with the
time of the checkout and the archive stores that. The content is identical and
the artifact is not.

Turning the contributors off one at a time gives the useful result, which is the
**third** row rather than the last one:

```text
build variant                     hash A              hash B              reproducible?
naive                             36f35ea80220b066    2e1ec288765ddbe5    no
+ fixed mtime on source files     91fd2f6edcb768b4    0a39bb8cdc3b445b    no
+ no build timestamp inside       4f4d66a3f542bb5b    0a68ed601a6c4af6    no
+ fixed mtime on generated file   0f52b56f0d753d63    0f52b56f0d753d63    yes
```

Row three normalized every enumerated file's mtime *and* removed the build
timestamp from the generated `build_info.py` — and the artifact still moved,
because `zipfile.writestr` with a string name takes the current clock for that
entry's own metadata. The build was reproducible inside a two-second window and
not outside it. That does not read as broken; it reads as flaky, which is worse.

A fourth contributor this machine cannot demonstrate but that has to be handled
anyway: **entry order**. Two checkouts here iterate identically (`rglob` order
identical across two checkouts: True) and that order is not `sorted()`. It
reproduces on the laptop and stops reproducing in the runner. Sort explicitly.

**And the environment is an input nobody declares.** The same four-line program,
four subprocesses, four hash seeds:

```text
  PYTHONHASHSEED=0: ["canary", "trace", "rerank", "zh_segmenter", "strict_schema"]
  PYTHONHASHSEED=1: ["strict_schema", "zh_segmenter", "canary", "trace", "rerank"]
  PYTHONHASHSEED=2: ["zh_segmenter", "strict_schema", "rerank", "trace", "canary"]
  PYTHONHASHSEED=3: ["trace", "rerank", "strict_schema", "canary", "zh_segmenter"]

distinct outputs from identical source: 4 of 4
```

Set iteration over string keys depends on the per-process hash seed. Any
codegen step that serializes a set — feature flags, a schema's property list, a
vocabulary — emits different bytes per process. This is why reproducible-build
tooling sets `SOURCE_DATE_EPOCH`, `PYTHONHASHSEED`, `TZ` and `LC_ALL` before it
does anything else.

**"We pin our dependencies" is a claim about a fifth of what gets installed.**

```text
package               declared    resolved t0   resolved t1   moved?
anyio                 --          4.4.0         4.6.0         MOVED
certifi               --          2024.7.4      2024.8.30     MOVED
httpcore              --          1.0.6         1.0.7         MOVED
httpx                 0.27.2      0.27.2        0.27.2
pydantic              2.9.1       2.9.1         2.9.1
...
direct dependencies declared: 2      packages actually installed: 10
pinned fraction of the closure: 20%
```

Both resolutions satisfy `requirements.txt`; both pass review. A lockfile is the
file that names the other 80%, and a lockfile without hashes still assumes a
version number identifies bytes — which is exactly the assumption a re-uploaded
release breaks.

**The part that is specific to a model-backed service.** Take the artifact from
above — reproducible, hash pinned — and run it on two days:

```text
run             artifact sha      record accuracy   stored rate   cost/400
day 44          3ff9d8678874      0.805             0.995         $0.49
day 46          3ff9d8678874      0.703             0.998         $0.50

accuracy 95% CI day 44: [0.765, 0.843]   day 46: [0.655, 0.748]
```

A 10-point drop with no deploy, no config change and no code change: the
provider changed what the `mid-1` alias points at. The artifact hash is evidence
about the code and about nothing else.

```text
input that decides output       lives                                 pinned by artifact?
application code                in artifact                           yes
dependency versions             in artifact, if locked with hashes    yes
JSON schema version             in artifact                           yes
prompt text                     runtime config store                  NO
model behind the alias          provider side                         NO
decoding parameters             runtime config store                  NO
retrieval index contents        external, mutable                     NO
tokenizer / analyzer version    provider or index side                NO
```

Three of eight. The deployable unit of this kind of service is the artifact
**plus a resolved configuration** — prompt hash, model version rather than
alias, decoding parameters, index version — and that tuple is what has to be
stamped on every record it writes. See
[model-prompt-registry.md](model-prompt-registry.md), which is the same argument
arriving from the storage side.

**A rollback rolls back the artifact.** r3 ships on day 30 writing records under
schema 1.1, which adds a required `provenance` object; the rolled-back r2 reader
validates against 1.0 and refuses unknown properties:

```text
rolled back on    rows in table     unreadable by r2    share
day 31            351               58                  16.5%
day 32            411               118                 28.7%
day 34            528               235                 44.5%
day 37            708               415                 58.6%
day 41            947               654                 69.1%
```

The damage is a function of how long the release stayed up, and nothing in the
rollback tooling knows that number. Everything stateful a release touches has
its own rollback story and most have none: the migration, the rows already
written, the prompt store, the eval-set version the gate ran against, the
retrieval index, the DLQ now holding items the old code cannot parse, and
anything sent to a third party. Hence expand-migrate-contract: a release must be
readable by the version before it, or the rollback button is decorative.

## The experiment

```powershell
cd modules\ops-lab
python build_lab.py      # ~15 s; writes and deletes a temp tree, spawns 4 subprocesses
```

## Boundary

- **This is a zip, not an OCI image.** Layer digests, base-image drift and
  `RUN` cache invalidation are additional sources of the same class of problem;
  the container format changes the surface area, not the argument.
- **The dependency index is declared.** The resolution arithmetic is real, the
  package versions are invented. The 20% is a property of this closure — the
  transferable claim is "measure your own closure", not the number.
- **The provider reskill is declared** by the fixture. What is real is that a
  service pinning a model *alias* has no way to detect it, which is the same
  gap `../drift-and-degradation.md` measures from the monitoring side.
- **Nothing here proves an artifact is trustworthy.** Reproducibility says two
  builds agree; supply-chain integrity — signing, provenance attestation,
  verifying the base image — is a separate row this module does not touch.

## Cards

### 1. [failure] CI is green, the source is unchanged, and today's image digest differs from yesterday's.

**Answer:** Look for a clock and an iteration order, not for a bug. In the lab
the contributors were, in order of discovery: file mtimes set by the checkout,
a generated `build_info.py` containing a timestamp, the *metadata* of that
generated file even after its content was fixed, and per-process hash seeding
that reordered a serialized set in four out of four runs.

**Why:** A build's inputs include the filesystem's metadata and the process
environment, neither of which appears in the diff a reviewer reads.

**Boundary:** Normalizing the files you enumerate and forgetting the ones you
generate produces a build that reproduces within a two-second window — flaky
rather than broken, and much harder to find.

**Tags:** `ci-cd` `failure` `general-principle`

---

### 2. [decision] The model-backed service must be reproducible. What goes in the artifact?

**Answer:** The artifact can pin the code, the locked dependency closure and the
schema — three of the eight inputs that decide output in the lab's inventory.
The other five (prompt text, the model behind the alias, decoding parameters,
index contents, tokenizer version) live outside it. So the deployable unit is
the artifact plus a resolved configuration, and the record of what ran is a
stamp on each output row, not a tag on the image.

**Why:** In this class of system, most of the behaviour is late-bound by design
— that is what makes prompts and models changeable without a deploy.

**Boundary:** The lab measured a 0.103 accuracy drop across a provider-side
alias change with a byte-identical artifact. Pinning a model *version* removes
that particular gap and costs you the provider's improvements; that is a
decision to make in writing, per task.

**Tags:** `ci-cd` `decision` `ai-specific`

---

### 3. [misconception] We can always roll back the deploy.

**Answer:** You can roll back the artifact. In the lab, the share of the events
table unreadable by the previous release grew 16.5% -> 69.1% over eleven days,
purely as a function of how long the new schema had been writing. Rollback
safety is a property of the data the release produced, not of the deployment
system.

**Why:** Deploy is not atomic with state. Code moves in one step; rows,
prompts, indexes and queues do not move back.

**Boundary:** Expand-migrate-contract makes rollback real for schema changes —
every release must be readable by the one before it. It does nothing for
anything already sent to a third party, and nothing for a destructive
migration, which is why "additive only until the old version is retired" is the
operating rule rather than the polite one.

**Tags:** `ci-cd` `misconception` `general-principle`
