"""Is model_b's actors F1 lead over model_a real? Paired bootstrap over records."""
import random, statistics, sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from gold import GOLD
from predictions import SYSTEMS
from scoring import counts_for_field, prf

FIELD, N_BOOT, SEED = "actors", 10000, 20260803

def per_record(system):
    return [counts_for_field(FIELD, g.get(FIELD), SYSTEMS[system][g["id"]].get(FIELD))
            for g in GOLD]

def f1(counts):
    tp = sum(c[0] for c in counts); fp = sum(c[1] for c in counts); fn = sum(c[2] for c in counts)
    return prf(tp, fp, fn)[2]

A, B = per_record("model_a"), per_record("model_b")
observed = f1(B) - f1(A)

rng = random.Random(SEED)
n = len(GOLD)
deltas = []
for _ in range(N_BOOT):
    idx = [rng.randrange(n) for _ in range(n)]          # SAME indices for both
    deltas.append(f1([B[i] for i in idx]) - f1([A[i] for i in idx]))
deltas.sort()
lo, hi = deltas[int(0.025 * N_BOOT)], deltas[int(0.975 * N_BOOT)]
crosses = sum(1 for d in deltas if d <= 0) / N_BOOT

print(f"model_a actors F1 = {f1(A):.4f}")
print(f"model_b actors F1 = {f1(B):.4f}")
print(f"observed difference (B - A) = {observed:+.4f}")
print()
print(f"paired bootstrap, {N_BOOT} resamples of n={n} records, seed {SEED}")
print(f"  95% interval on the difference: [{lo:+.4f}, {hi:+.4f}]")
print(f"  fraction of resamples where A >= B: {crosses:.3f}")
print()
sd = statistics.stdev(deltas)
print(f"  bootstrap standard error at n={n}: {sd:.4f}")
for target in (50, 200, 1000):
    print(f"  projected SE at n={target:<5} (SE * sqrt({n}/{target})): "
          f"{sd * (n / target) ** 0.5:.4f}"
          f"   -> 95% half-width ~{1.96 * sd * (n / target) ** 0.5:.4f}")
