"""A rubric grader, and the measurement that decides whether to trust it.

    python rubric.py

The judge's verdicts are a RECORDED TRANSCRIPT, checked in so this lab is
deterministic and offline. In your project that file is written by an actual
model call; everything downstream of it -- the agreement arithmetic, which is
the part this module teaches -- is identical either way.

Constructed fixture: these 16 rows were authored to make a specific point, not
sampled from a run. The arithmetic is real; the data is illustrative.
"""
import sys
from collections import Counter

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (id, difficulty, human_label, judge_label) -- "S" supported by the source,
# "U" unsupported. Difficulty was assigned by the human BEFORE seeing the judge.
JUDGMENTS = [
    ("c01", "clear", "S", "S"), ("c02", "clear", "S", "S"),
    ("c03", "clear", "S", "S"), ("c04", "clear", "S", "S"),
    ("c05", "clear", "S", "S"), ("c06", "clear", "S", "S"),
    ("c07", "clear", "S", "S"), ("c08", "clear", "S", "S"),
    ("c09", "clear", "U", "U"), ("c10", "clear", "U", "U"),
    # Borderline: the claim paraphrases, generalizes, or adds a qualifier the
    # source does not contain. These are the cases the grader exists to decide.
    ("b01", "borderline", "U", "S"), ("b02", "borderline", "U", "S"),
    ("b03", "borderline", "U", "S"), ("b04", "borderline", "U", "U"),
    ("b05", "borderline", "S", "S"), ("b06", "borderline", "S", "S"),
]


def kappa(rows):
    n = len(rows)
    a = sum(1 for *_, h, j in rows if h == "S" and j == "S")
    b = sum(1 for *_, h, j in rows if h == "S" and j == "U")
    c = sum(1 for *_, h, j in rows if h == "U" and j == "S")
    d = sum(1 for *_, h, j in rows if h == "U" and j == "U")
    po = (a + d) / n
    pe = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
    return po, pe, (po - pe) / (1 - pe) if pe != 1 else float("nan"), (a, b, c, d)


po, pe, k, cells = kappa(JUDGMENTS)
human = Counter(h for *_, h, _ in JUDGMENTS)
judge = Counter(j for *_, _, j in JUDGMENTS)

print(f"n = {len(JUDGMENTS)}   both-supported {cells[0]}  human-only {cells[1]}  "
      f"judge-only {cells[2]}  both-unsupported {cells[3]}")
print(f"human called it supported {human['S']}/{len(JUDGMENTS)}, "
      f"judge called it supported {judge['S']}/{len(JUDGMENTS)}")
print()
print(f"raw agreement   po = {po:.4f}")
print(f"chance          pe = {pe:.4f}")
print(f"Cohen's kappa      = {k:.4f}")
print()
print(f"{'subset':<14}{'n':>4}{'agreement':>12}{'kappa':>9}")
print("-" * 39)
for subset in ("clear", "borderline"):
    rows = [r for r in JUDGMENTS if r[1] == subset]
    p, _e, kk, _c = kappa(rows)
    kk_s = f"{kk:.4f}" if kk == kk else "undefined"
    print(f"{subset:<14}{len(rows):>4}{p:>12.4f}{kk_s:>9}")
print()
print("Disagreements (every one is borderline, and every one is the judge")
print("calling an unsupported claim supported):")
for rid, diff, h, j in JUDGMENTS:
    if h != j:
        print(f"  {rid}  {diff:<11} human={h}  judge={j}")
