"""Containerization and CI/CD: is the thing you deploy the thing you built?

Map row (Layer 9): "Reproducible build and deploy of a model-backed service."

Sections 1 and 2 are about the artifact and are measured on this machine with
real files, real zip containers and real hashing. Section 3 is the part the map
row actually asks about and the part a container tutorial never reaches: a
byte-identical artifact that behaves differently, because most of what decides
a model-backed service's output is not inside the artifact. Section 4 asks what
a rollback rolls back.

Commit to the predictions before running.
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from pathlib import Path

import ops

PREDICTIONS = {
    "A": "The same source tree and the same build command produce the same "
         "artifact bytes. If they do not, something in my build is obviously "
         "wrong and I will see it.",
    "B": "Pinning every dependency in requirements.txt to an exact version "
         "pins the build.",
    "C": "Two runs of a byte-identical artifact, on the same input, produce "
         "the same output.",
    "D": "Rolling the deployment back to the previous artifact undoes the "
         "release.",
}

SOURCE = {
    "app/__init__.py": "",
    "app/extract.py": (
        "PROMPT_NAME = 'extract_v2'\n"
        "MODEL = 'mid-1'\n\n"
        "def run(doc):\n"
        "    return {'doc': doc}\n"
    ),
    "app/schema.py": "SCHEMA_VERSION = '1.1'\n",
    "requirements.txt": "httpx==0.27.2\npydantic==2.9.1\n",
    "Dockerfile": "FROM python:3.14-slim\nCOPY . /srv\nRUN pip install -r requirements.txt\n",
}


def write_tree(root: Path) -> Path:
    """A fresh checkout. Note what this does to mtimes -- that is section 1."""
    for name, body in SOURCE.items():
        p = root / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(body, encoding="utf-8")
    return root


EPOCH = (1980, 1, 1, 0, 0, 0)


def build(root: Path, out: Path, *, fixed_mtime=False, sorted_order=False,
          stamp=True, fixed_generated=False) -> str:
    """Package the tree. Each keyword switches off one source of variation, so
    the sections below can turn them off one at a time and watch the hash.

    `fixed_generated` is separate from `fixed_mtime` on purpose: normalizing
    the files you enumerate and forgetting the ones you generate is the near
    miss, and it is worth having its own column.
    """
    paths = [p for p in root.rglob("*") if p.is_file()]
    paths = sorted(paths) if sorted_order else paths
    with zipfile.ZipFile(out, "w", zipfile.ZIP_STORED) as zf:
        for p in paths:
            arc = str(p.relative_to(root)).replace("\\", "/")
            if fixed_mtime:
                info = zipfile.ZipInfo(arc, date_time=EPOCH)
                info.external_attr = 0o644 << 16
                zf.writestr(info, p.read_bytes())
            else:
                zf.write(p, arc)
        # The file every build system generates and nobody thinks of as input.
        body = (f"BUILT_AT = '{time.strftime('%Y-%m-%dT%H:%M:%S')}'\n"
                f"BUILD_ID = '{os.getpid()}'\n") if stamp else \
               "BUILT_AT = 'source-date-epoch'\n"
        if fixed_generated:
            info = zipfile.ZipInfo("app/build_info.py", date_time=EPOCH)
            info.external_attr = 0o644 << 16
            zf.writestr(info, body)
        else:
            zf.writestr("app/build_info.py", body)     # ZipInfo.now(), silently
    return hashlib.sha256(out.read_bytes()).hexdigest()


def section_1_bytes(tmp: Path):
    ops.rule("1. Measured: two builds of the same source, on this machine")

    def fresh(n):
        root = tmp / f"checkout{n}"
        shutil.rmtree(root, ignore_errors=True)
        root.mkdir(parents=True)
        return write_tree(root)

    h1 = build(fresh(1), tmp / "a.zip")
    time.sleep(2.2)                 # a CI queue is longer than this. Zip
                                    # timestamps have 2-second resolution,
                                    # which is itself a thing to know.
    h2 = build(fresh(2), tmp / "b.zip")     # a second checkout, a minute later
    print(f"build 1: {h1[:16]}   build 2: {h2[:16]}   "
          f"{'IDENTICAL' if h1 == h2 else 'DIFFERENT'}")
    print("Same source text, same command, same machine, same interpreter.\n")

    # Which bytes moved. This is the part worth doing once by hand: the answer
    # is never in the code and always in the container format.
    za, zb = zipfile.ZipFile(tmp / "a.zip"), zipfile.ZipFile(tmp / "b.zip")
    same_content = all(za.read(n) == zb.read(n) for n in za.namelist()
                       if n != "app/build_info.py")
    print(f"every file's CONTENT identical (excluding build_info): {same_content}")
    ops.row("entry", "mtime in A", "mtime in B", "equal?", widths=[26, 24, 24, 10])
    for name in list(za.namelist())[:4]:
        ia, ib = za.getinfo(name), zb.getinfo(name)
        ops.row(name, str(ia.date_time), str(ib.date_time),
                "yes" if ia.date_time == ib.date_time else "NO",
                widths=[26, 24, 24, 10])
    za.close()
    zb.close()

    print("\nA fresh checkout does not restore mtimes -- git records content,")
    print("not timestamps -- so every CI run stamps every file with the time")
    print("the checkout happened, and the archive stores it. The source is")
    print("identical and the artifact is not.\n")

    # Turn the contributors off one at a time, each build from its own fresh
    # checkout with time between them -- the CI situation, not the laptop one.
    ops.row("build variant", "hash A", "hash B", "reproducible?",
            widths=[34, 20, 20, 16])
    variants = [
        ("naive", dict()),
        ("+ fixed mtime on source files", dict(fixed_mtime=True)),
        ("+ no build timestamp inside", dict(fixed_mtime=True, stamp=False)),
        ("+ fixed mtime on generated file",
         dict(fixed_mtime=True, stamp=False, fixed_generated=True)),
    ]
    reproducible_at = None
    for label, kw in variants:
        ha = build(fresh(3), tmp / "va.zip", **kw)
        time.sleep(2.2)
        hb = build(fresh(4), tmp / "vb.zip", **kw)
        ok = ha == hb
        if ok and reproducible_at is None:
            reproducible_at = label
        ops.row(label, ha[:16], hb[:16], "yes" if ok else "no",
                widths=[34, 20, 20, 16])

    # Entry order is the contributor this machine cannot demonstrate, which is
    # worth reporting rather than dramatizing.
    o3 = [str(p.relative_to(tmp / "checkout3")) for p in (tmp / "checkout3").rglob("*")]
    o4 = [str(p.relative_to(tmp / "checkout4")) for p in (tmp / "checkout4").rglob("*")]
    print(f"\nfirst reproducible variant: {reproducible_at}")
    print("The third row is the near miss and it is the one worth keeping: the")
    print("build stamp's CONTENT was removed and the artifact still did not")
    print("reproduce, because `zipfile.writestr` with a string name takes the")
    print("current time for that entry's own metadata. Normalizing the files")
    print("you enumerate and forgetting the file you generate leaves a build")
    print("that is reproducible within a two-second window and not outside it,")
    print("which reads as flaky rather than as broken.\n")
    print(f"rglob order identical across two checkouts here: {o3 == o4}")
    print(f"rglob order equals sorted() here: {o3 == sorted(o3)}")
    print("Entry order is the contributor that costs nothing on this machine")
    print("and breaks on another: it is a property of the filesystem and of")
    print("the order files were created in, not of the build. It reproduces on")
    print("your laptop and stops reproducing in the runner, which is the worst")
    print("available failure mode -- so sort explicitly even when the measured")
    print("answer above is 'stable'.")
    return reproducible_at


def section_1b_hashseed(tmp: Path):
    ops.rule("1b. Measured: the same code, two processes, two different outputs")
    print("A generated config file, built from a set of feature flags -- the")
    print("shape half of all codegen has. Two subprocesses, two hash seeds:\n")
    prog = ("import json,sys;"
            "flags={'zh_segmenter','rerank','strict_schema','trace','canary'};"
            "sys.stdout.write(json.dumps(list(flags)))")
    outs = []
    for seed in ("0", "1", "2", "3"):
        env = dict(os.environ, PYTHONHASHSEED=seed)
        r = subprocess.run([sys.executable, "-c", prog], capture_output=True,
                           text=True, env=env)
        outs.append(r.stdout)
        print(f"  PYTHONHASHSEED={seed}: {r.stdout}")
    distinct = len(set(outs))
    print(f"\ndistinct outputs from identical source: {distinct} of {len(outs)}")
    print("Set iteration order depends on the per-process hash seed for str")
    print("keys. Nothing in the source changed, nothing in the environment a")
    print("reviewer would look at changed, and the artifact's bytes moved.")
    print("This is why reproducible-build tooling sets PYTHONHASHSEED,")
    print("SOURCE_DATE_EPOCH, TZ and LC_ALL before it does anything else: the")
    print("build's inputs include the environment, and the environment is the")
    print("input nobody declares.")
    return distinct


# --------------------------------------------------------------------------- #
# 2. Pinning. Declared index, real resolution arithmetic.
# --------------------------------------------------------------------------- #

INDEX_T0 = {
    "httpx":       ["0.27.0", "0.27.2"],
    "pydantic":    ["2.9.1"],
    "httpcore":    ["1.0.5", "1.0.6"],
    "certifi":     ["2024.7.4"],
    "anyio":       ["4.4.0"],
    "idna":        ["3.7"],
    "pydantic-core": ["2.23.3"],
    "typing-extensions": ["4.12.2"],
    "sniffio":     ["1.3.1"],
    "h11":         ["0.14.0"],
}
INDEX_T1 = {k: list(v) for k, v in INDEX_T0.items()}
INDEX_T1["httpcore"].append("1.0.7")          # a new release, three weeks later
INDEX_T1["anyio"].append("4.6.0")
INDEX_T1["certifi"] = ["2024.7.4", "2024.8.30"]

DEPS = {
    "httpx": ["httpcore", "certifi", "anyio", "idna"],
    "pydantic": ["pydantic-core", "typing-extensions"],
    "httpcore": ["h11", "certifi"],
    "anyio": ["sniffio", "idna"],
    "pydantic-core": ["typing-extensions"],
}
PINNED = {"httpx": "0.27.2", "pydantic": "2.9.1"}     # what requirements.txt says


def resolve(index, pinned):
    """Newest-satisfying resolution, the default of every tool that has one."""
    out, queue = {}, list(pinned)
    while queue:
        name = queue.pop()
        if name in out:
            continue
        out[name] = pinned.get(name) or index[name][-1]
        queue.extend(DEPS.get(name, []))
    return out


def section_2_pinning():
    ops.rule("2. The lockfile that is not one")
    t0, t1 = resolve(INDEX_T0, PINNED), resolve(INDEX_T1, PINNED)
    moved = {k for k in t0 if t0[k] != t1[k]}
    ops.row("package", "declared", "resolved t0", "resolved t1", "moved?",
            widths=[22, 12, 14, 14, 10])
    for name in sorted(t0):
        ops.row(name, PINNED.get(name, "--"), t0[name], t1[name],
                "MOVED" if name in moved else "", widths=[22, 12, 14, 14, 10])
    print(f"\ndirect dependencies declared: {len(PINNED)}")
    print(f"packages actually installed:  {len(t0)}")
    print(f"pinned fraction of the closure: {len(PINNED) / len(t0):.0%}")
    print(f"packages that moved between the two builds: {len(moved)} "
          f"({', '.join(sorted(moved))})")
    print("\nBoth builds satisfy requirements.txt. Both pass review. The line")
    print("'we pin our dependencies' is true about 20% of what gets installed.")
    print("A lockfile is the file that names the other 80%, and a lockfile")
    print("without hashes still trusts that a version number identifies bytes.")
    return len(PINNED) / len(t0), len(moved)


# --------------------------------------------------------------------------- #
# 3. The section the container tutorials do not have.
# --------------------------------------------------------------------------- #

BEHAVIOUR_INPUTS = [
    ("application code", "in artifact", True),
    ("dependency versions", "in artifact, if locked with hashes", True),
    ("JSON schema version", "in artifact", True),
    ("prompt text", "runtime config store", False),
    ("model behind the alias", "provider side", False),
    ("decoding parameters", "runtime config store", False),
    ("retrieval index contents", "external, mutable", False),
    ("tokenizer / analyzer version", "provider or index side", False),
]


def section_3_same_bytes(tmp: Path):
    ops.rule("3. A byte-identical artifact, two different services")
    root = write_tree(tmp / "release")
    h = build(root, tmp / "rel.zip", fixed_mtime=True, sorted_order=True,
              stamp=False)
    print(f"artifact sha256: {h[:32]}  (reproducible, per section 1)\n")

    rel = ops.RELEASES[2]           # r3: pinned code, pinned prompt NAME
    n = 400
    before = [ops.process(ops.DOC_IDS[i % len(ops.DOC_IDS)], rel, seq=i, day=44)
              for i in range(n)]
    after = [ops.process(ops.DOC_IDS[i % len(ops.DOC_IDS)], rel, seq=i, day=46)
             for i in range(n)]

    def q(evs):
        stored = [e for e in evs if e["outcome"] == "stored"]
        return (sum(e["correct"] for e in evs) / len(evs),
                len(stored) / len(evs),
                sum(e["cost"] for e in evs))

    ops.row("run", "artifact sha", "record accuracy", "stored rate", "cost/400",
            widths=[16, 18, 18, 14, 12])
    for label, evs in (("day 44", before), ("day 46", after)):
        acc, stored, cost = q(evs)
        ops.row(label, h[:12], f"{acc:.3f}", f"{stored:.3f}", ops.usd(cost),
                widths=[16, 18, 18, 14, 12])
    d_acc = q(before)[0] - q(after)[0]
    lo, hi = ops.bootstrap_ci([int(e["correct"]) for e in before])
    lo2, hi2 = ops.bootstrap_ci([int(e["correct"]) for e in after])
    print(f"\naccuracy 95% CI day 44: [{lo:.3f}, {hi:.3f}]   "
          f"day 46: [{lo2:.3f}, {hi2:.3f}]")
    print(f"drop: {d_acc:.3f} with no deploy, no config change, no code change.")
    print("The provider reskilled what `mid-1` points at. The artifact hash is")
    print("evidence about the code and about nothing else.\n")

    ops.row("input that decides output", "lives", "pinned by artifact?",
            widths=[32, 38, 22])
    for name, where, inside in BEHAVIOUR_INPUTS:
        ops.row(name, where, "yes" if inside else "NO", widths=[32, 38, 22])
    inside = sum(1 for _, _, i in BEHAVIOUR_INPUTS if i)
    print(f"\n{inside} of {len(BEHAVIOUR_INPUTS)} inputs are inside the artifact.")
    print("Reproducible build is necessary and it is the smaller half of the")
    print("problem. The deployable unit of a model-backed service is the")
    print("artifact PLUS a resolved configuration -- prompt hash, model")
    print("version rather than alias, decoding parameters, index version --")
    print("and that tuple is what has to be stamped on every record it writes.")
    print("Which is ../model-prompt-registry.md, arriving from the build side.")
    return d_acc, inside


# --------------------------------------------------------------------------- #
# 4. Rollback.
# --------------------------------------------------------------------------- #

def section_4_rollback():
    ops.rule("4. What a rollback rolls back")
    print("One events table, filled by 25 days of traffic. r3 ships on day 30")
    print("and writes records under schema 1.1, which adds a required")
    print("`provenance` object. On day 34 it is rolled back to r2's reader,")
    print("which validates against 1.0 and refuses unknown properties.\n")

    from task import SCHEMA
    table = []
    for day in range(25, 41):
        for i in range(60):
            rel = ops.release_for(day, i)
            e = ops.process(ops.DOC_IDS[i % len(ops.DOC_IDS)], rel, seq=i, day=day)
            if e["outcome"] == "stored":
                if rel.schema_version == "1.1":     # what the new code writes
                    e["record"]["provenance"] = {"span": [0, 8],
                                                 "fetched": "2026-03-11"}
                table.append((day, e))

    ops.row("rolled back on", "rows in table", "unreadable by r2", "share",
            widths=[18, 18, 20, 10])
    for cutoff in (31, 32, 34, 37, 41):
        rows = [(d, e) for d, e in table if d < cutoff]
        bad = sum(1 for _d, e in rows
                  if any(v.startswith("provenance/")
                         for v in ops.validate(e["record"], SCHEMA)))
        ops.row(f"day {cutoff}", len(rows), bad, f"{bad / len(rows):.1%}",
                widths=[18, 18, 20, 10])
    rows = [(d, e) for d, e in table if d < 41]
    rejected = sum(1 for _d, e in rows
                   if any(v.startswith("provenance/")
                          for v in ops.validate(e["record"], SCHEMA))) / len(rows)
    print("\nThe damage is a function of how long the release stayed up, and")
    print("nothing in the rollback tooling knows that number.")
    print("\nThe artifact rolled back in seconds. The rows did not. Every")
    print("stateful thing a release touches has its own rollback story and")
    print("most of them do not have one:\n")
    for line in [
        "schema migration -- additive is reversible, destructive is not",
        "records already written in the new shape -- readable by old code?",
        "the prompt store -- rolled back, or still on the new prompt?",
        "the eval set version the gate ran against -- see eval-set-versioning",
        "the retrieval index, if the release reindexed it",
        "the DLQ, now holding items the old code cannot parse",
        "anything the release sent to a third party",
    ]:
        print(f"  - {line}")
    print("\nThe rule that survives: deploy is not atomic with data, so a")
    print("release must be readable by the version before it (expand, migrate,")
    print("contract) or it is a one-way door with a rollback button on it.")
    return rejected


def score(reproducible_at, distinct, pinned_frac, moved, drop, inside, rejected):
    ops.rule("5. The predictions")
    verdicts = {
        "A": (f"WRONG and invisibly so -- the naive build differed on the "
              f"first try, and needed '{reproducible_at}' before two builds of "
              f"identical source matched. Nothing in the build log says "
              f"anything is wrong; the artifact is simply not the same one"),
        "B": (f"WRONG -- exact pins on both direct dependencies cover "
              f"{pinned_frac:.0%} of the installed closure, and {moved} "
              f"packages moved between two builds that both satisfy the file"),
        "C": (f"WRONG, and this is the one that matters here -- the same "
              f"artifact hash produced record accuracy {drop:.3f} lower after "
              f"the provider changed what an alias points at. Only {inside} of "
              f"{len(BEHAVIOUR_INPUTS)} behaviour-deciding inputs are inside "
              f"the artifact at all"),
        "D": (f"WRONG for anything stateful -- after eleven days on the new "
              f"release, {rejected:.0%} of the rows in the events table cannot "
              f"be read by the code it rolled back to, and the share is a "
              f"function of how long the release stayed up. The artifact is "
              f"reversible; what it wrote is not"),
    }
    for key, text in PREDICTIONS.items():
        print(f"{key}. {verdicts[key]}\n   claim: {text}\n")


if __name__ == "__main__":
    tmp = Path(tempfile.mkdtemp(prefix="ops-build-"))
    try:
        repro = section_1_bytes(tmp)
        print()
        distinct = section_1b_hashseed(tmp)
        print()
        pinned_frac, moved = section_2_pinning()
        print()
        drop, inside = section_3_same_bytes(tmp)
        print()
        rejected = section_4_rollback()
        print()
        score(repro, distinct, pinned_frac, moved, drop, inside, rejected)
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
