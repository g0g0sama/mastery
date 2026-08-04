"""Why Chinese text costs the tokens it does, and what a batch will cost.

    python token_lab.py

The tokenizer is a stand-in and says so at the top of tokenizer.py. The RULE it
reproduces -- vocabulary hit costs one token, byte fallback costs two or three --
is the mechanism. The exact ratio for your text is a measurement you must take
with the provider's own counter.
"""
import sys

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from provider import MODELS, PROMPT, Provider
from task import DOCUMENTS
from tokenizer import count, profile, tokens

# The same six facts, written twice. Not a translation exercise -- the point is
# that identical information costs different amounts depending on the script it
# is written in, which is a budgeting fact and not a linguistic one.
PAIRS = [
    ("中国石化宣布将于三月十日在深圳新建研发中心",
     "Sinopec announced on March 10 a new research and development center in Shenzhen"),
    ("宁德时代与宝马集团于三月九日签署长期供货协议",
     "CATL and BMW Group signed a long term supply agreement on March 9"),
    ("美国商务部三月五日将中芯国际列入实体清单",
     "The US Commerce Department added SMIC to the entity list on March 5"),
]

print("=== 1. The same information, two scripts ===")
print(f"  {'':<4}{'chars':>7}{'tokens':>8}{'tok/char':>10}   text")
for i, (zh, en) in enumerate(PAIRS, start=1):
    for label, text in (("zh", zh), ("en", en)):
        p = profile(text)
        print(f"  {label:<4}{p['chars']:>7}{p['tokens']:>8}"
              f"{p['tokens_per_char']:>10.2f}   {text[:46]}")
    print()
print("  Chinese is dense per character and expensive per character; English is")
print("  the reverse. The character count is the intuition people carry and it")
print("  is the wrong unit. What matters is that a Chinese character is one")
print("  token when the vocabulary holds it and two or three when it falls back")
print("  to UTF-8 bytes -- so the cost of your corpus depends on how well the")
print("  vocabulary covers your domain's characters, which is a property of the")
print("  MODEL and not of your text.")
print()

print("=== 2. Where the fallback bites ===")
rare = "稀土永磁材料出口价格上涨"
common = "中国石油天然气产能扩大"
for text in (rare, common):
    t = tokens(text)
    fallback = [x for x in t if x.endswith("#1")]
    print(f"  {text}")
    print(f"    {len(t)} tokens for {len(text)} characters; "
          f"{len(fallback)} characters fell back to bytes")
print("  Two sentences of the same length, different prices. A domain vocabulary")
print("  full of characters the tokenizer does not hold is a permanent tax on")
print("  every request, invisible in the prompt and visible only on the bill.")
print()

print("=== 3. Cost per document, before running the batch ===")
provider = Provider("mid-1")
usages = []
for doc_id, (text, _) in DOCUMENTS.items():
    r = provider.complete(doc_id)
    usages.append(r.usage)
mean_in = sum(u["input"] for u in usages) / len(usages)
mean_out = sum(u["output"] for u in usages) / len(usages)
print(f"  prompt template: {count(PROMPT)} tokens, paid on every request")
print(f"  mean input {mean_in:.1f} tokens, mean output {mean_out:.1f} tokens")
print()
print(f"  {'model':<10}{'in $/1k':>10}{'out $/1k':>10}{'$/doc':>12}{'$/10k docs':>13}")
print("  " + "-" * 55)
for name, m in MODELS.items():
    per_doc = m.cost({"input": mean_in, "output": mean_out})
    print(f"  {name:<10}{m.price_in:>10.5f}{m.price_out:>10.5f}"
          f"{per_doc:>12.6f}{per_doc * 10_000:>13.2f}")
print()
print("  Two things this table settles that a per-call price cannot:")
print(f"   - The template is {count(PROMPT)} tokens and the document is about")
print(f"     {mean_in - count(PROMPT):.0f}. Most of what you are paying for on a short")
print("     document is the instruction, which is the same on every request and")
print("     therefore the first thing to shorten or cache.")
print("   - Output tokens cost 5x input tokens at every tier here. A schema that")
print("     asks the model to echo the source span back is not a small change to")
print("     the bill; see ../structured-outputs.md for why you may want it anyway.")
print()

print("=== 4. The context budget, which is a different question ===")
WINDOW = 128_000
doc_tokens = mean_in - count(PROMPT)
print(f"  a {WINDOW:,}-token window holds about "
      f"{int((WINDOW - count(PROMPT)) / doc_tokens):,} of these documents")
print("  -- and that number is the ceiling, not the target. Three costs rise")
print("  with context length and none of them are on the price list:")
print("   - attention over a longer context is slower per token generated")
print("   - the KV cache grows linearly with context and is what exhausts")
print("     memory on a local model (Layer 8)")
print("   - retrieval quality falls off inside a long context long before the")
print("     window ends, which is a measurement, not a rumour -- make it on")
print("     your own eval set rather than accepting either the vendor's number")
print("     or the folklore.")
print()
print("  Budget in three separate quantities and never conflate them:")
print("    tokens per request  -> latency and context limits")
print("    tokens per document -> unit cost")
print("    tokens per ACCEPTED document -> the only one that decides anything,")
print("    because a failed extraction was paid for too (../eval-gates.md).")
