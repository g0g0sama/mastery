# Tokenization and the token budget

**Micro module.** One mechanism, one experiment, three cards. Runs against
[model-interface-lab/](model-interface-lab/).

**Capabilities:** tokenization (Layer 3, Aware -> Independent) and token
accounting / context budgeting (Layer 4, Aware -> Independent). One module,
because the second is arithmetic over the first and separating them produces two
modules that each say half of a thing.

Map evidence: "Explain why Chinese text costs the tokens it does, measured" and
"Predict cost per document before running a batch."

---

## The problem

You are about to run extraction over 10,000 Chinese news documents and you need
a number before you start, not after. The price list is in tokens. Your corpus
is in characters. The conversion is not a constant, and the factor it varies by
is not a property of your text.

## The wrong model

**"A token is roughly four characters."**

That heuristic comes from English and it is roughly right there. For Chinese it
is wrong by a factor of four to five in the other direction:

```text
       chars  tokens  tok/char   text
zh        21      23      1.10   中国石化宣布将于三月十日在深圳新建研发中心
en        67      19      0.28   Sinopec announced on March 10 a new research...

zh        22      29      1.32   宁德时代与宝马集团于三月九日签署长期供货协议
en        53      15      0.28   CATL and BMW Group signed a long term supply...
```

Same information, both directions. Chinese is dense per character and expensive
per character; English is the reverse. The character count is the intuition
people carry and it is simply the wrong unit.

## The mechanism

A subword vocabulary is **learned from a training corpus**. A string that appears
often enough during vocabulary construction becomes one token; a string that does
not is split, and in the limit falls back to its UTF-8 bytes -- three bytes for a
CJK character, which typically resolves to two or three tokens.

So the cost of your corpus is a function of **how well the model's vocabulary
covers your domain's characters**, which is a property of the model, not of your
text. Two Chinese sentences of the same length can differ by 50%:

```text
稀土永磁材料出口价格上涨
  19 tokens for 12 characters; 7 characters fell back to bytes
中国石油天然气产能扩大
  13 tokens for 11 characters; 2 characters fell back to bytes
```

Domain vocabulary that the tokenizer does not hold is a permanent tax on every
request: invisible in the prompt, visible only on the bill.

## The experiment

```powershell
cd modules\model-interface-lab
python token_lab.py
```

```text
prompt template: 61 tokens, paid on every request
mean input 87.2 tokens, mean output 60.4 tokens

model        in $/1k  out $/1k       $/doc   $/10k docs
tiny-1       0.00025   0.00125    0.000097         0.97
mid-1        0.00300   0.01500    0.001167        11.67
large-1      0.01500   0.07500    0.005837        58.37
```

Two things this settles that a per-call price cannot:

- **The instruction is 61 tokens and the document is 26.** On short documents
  most of what you are paying for is the template, identical on every request --
  so it is the first thing to shorten, and the first thing to put behind prompt
  caching.
- **Output tokens cost 5x input tokens at every tier.** A schema that makes the
  model echo the source span back for provenance is not a rounding error on the
  bill. (It may still be worth it -- see
  [structured-outputs.md](structured-outputs.md).)

The context budget is a **different question** with the same units. A 128,000
token window holds about 4,873 of these documents, and that is a ceiling rather
than a target: attention cost per generated token rises with context, the KV
cache grows linearly with it (Layer 8), and retrieval quality inside a long
context degrades well before the window ends.

## Boundary

- **The lab's tokenizer is a stand-in and says so.** It reproduces the rule --
  vocabulary hit costs one, byte fallback costs two or three -- and none of the
  data. Never budget a real batch with it. Use the provider's own counting
  endpoint, because the only tokenizer whose count decides your bill is theirs.
- **Budget three quantities and never conflate them:** tokens per *request*
  (latency and context limits), tokens per *document* (unit cost), and tokens per
  **accepted** document (the only one that decides anything, since a failed
  extraction was paid for too). The third is the metric in
  [eval-gates.md](eval-gates.md) and the one that makes a cheap model look
  expensive.
- **Tokenization is upstream of retrieval too.** The analyzer choice in
  [chinese-segmentation.md](chinese-segmentation.md) is the same question asked
  of an index rather than a model, and the answers do not have to agree -- a
  segmenter optimized for recall and a vocabulary optimized for compression are
  solving different problems on the same text.
- **Model changes reprice your corpus.** A new model version with a different
  vocabulary changes tokens per document with no change to your code, which is
  one reason model version belongs in the record ([prompt-versioning.md](prompt-versioning.md)).

## Cards

### 1. [mechanism] Why does Chinese text cost roughly four times as many tokens per character as English, and what determines the exact ratio?

**Answer:** Subword vocabularies are learned from a training corpus. A character
in the vocabulary costs one token; one that is not falls back to UTF-8 bytes --
three bytes for a CJK character, typically two or three tokens.

**Why:** The ratio therefore depends on how well the model's vocabulary covers
your domain's characters, which is a property of the model rather than of your
text. Two Chinese sentences of equal length in the lab differed by 50% in tokens.

**Boundary:** Per *character* Chinese is expensive; per unit of *information* it
is often cheaper, since a 21-character Chinese sentence carried the same content
as a 67-character English one. Which comparison matters depends on whether you
are paying for the source or writing the prompt.

**Tags:** `tokenization` `mechanism` `general-principle`

---

### 2. [decision] You need a cost estimate for extracting from 10,000 short documents. Which three token quantities do you compute, and which one decides?

**Answer:** Tokens per request, tokens per document, and tokens per **accepted**
document. The third decides.

**Why:** Failed extractions are billed. A cheaper model that needs two attempts
and still fails 20% of the time can cost more per usable record than an expensive
one that succeeds first time -- and only the third quantity shows it.

**Boundary:** Cost per accepted record requires an acceptance criterion, which
means an eval set. Without one you can only compute the first two, and neither
is a decision.

**Tags:** `cost` `decision` `general-principle`

---

### 3. [failure] Your per-document cost rises 20% after a model version upgrade, with no change to your prompt or your corpus. What is the first explanation?

**Answer:** A different tokenizer vocabulary. The same text tokenizes to a
different count under a different merge table.

**Why:** Vocabulary coverage of your domain's characters -- in particular rare
CJK characters that fall back to bytes -- changes between model families and
sometimes between versions of one family.

**Boundary:** Check output tokens separately from input. A model that has become
more verbose raises cost through the 5x-priced side of the ledger, which is a
prompt problem rather than a tokenizer one.

**Tags:** `cost` `tokenization` `failure` `general-principle`
