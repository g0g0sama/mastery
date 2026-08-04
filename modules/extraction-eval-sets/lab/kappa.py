"""Two labellers, 20 candidate actor mentions, one in-scope decision each."""
import sys
sys.stdout.reconfigure(encoding="utf-8", errors="replace")

# (item, labeller_A, labeller_B) -- True means "in scope as an actor"
JUDGEMENTS = [
    ("R01 subsidiary named in passing",      True,  True),
    ("R01 parent group in the byline",       True,  False),
    ("R02 joint-venture vehicle",            True,  True),
    ("R02 named executive, not the firm",    False, False),
    ("R03 industry association",             True,  True),
    ("R03 ministry department vs ministry",  True,  True),
    ("R03 company listed in a table only",   True,  True),
    ("R04 local government bureau",          True,  True),
    ("R05 rotating chairman by name",        False, True),
    ("R05 the firm itself",                  True,  True),
    ("R06 foreign regulator",                True,  True),
    ("R06 entity-list target",               True,  True),
    ("R07 plant, not the operator",          True,  False),
    ("R08 municipal investment arm",         True,  True),
    ("R09 commission spokesperson",          True,  True),
    ("R10 trade body coordinating",          True,  True),
    ("R11 company in the page footer",       False, False),
    ("R11 the announcing firm",              True,  True),
    ("R12 shipping line",                    True,  True),
    ("R12 arbitration venue",                True,  True),
]

n = len(JUDGEMENTS)
a = sum(1 for _, x, y in JUDGEMENTS if x and y)
b = sum(1 for _, x, y in JUDGEMENTS if x and not y)
c = sum(1 for _, x, y in JUDGEMENTS if not x and y)
d = sum(1 for _, x, y in JUDGEMENTS if not x and not y)

po = (a + d) / n
pe = ((a + b) * (a + c) + (c + d) * (b + d)) / (n * n)
kappa = (po - pe) / (1 - pe)

print(f"n = {n}   both-yes {a}  A-only {b}  B-only {c}  both-no {d}")
print(f"A said in-scope {a+b}/{n}, B said in-scope {a+c}/{n}")
print()
print(f"raw agreement      po = {po:.4f}")
print(f"chance agreement   pe = {pe:.4f}")
print(f"Cohen's kappa         = {kappa:.4f}")
print()
print("Disagreements:")
for item, x, y in JUDGEMENTS:
    if x != y:
        print(f"  {item:<38} A={'yes' if x else 'no ':<3} B={'yes' if y else 'no'}")
