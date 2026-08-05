# Entropy and perplexity

**Micro module.** One mechanism, one experiment, three cards. Runs against
[stats-lab/](stats-lab/), over the corpus in [zh-retrieval-lab/](zh-retrieval-lab/).

**Capability:** Entropy, cross-entropy, KL, perplexity (Layer 2, Aware ->
Working). Map evidence: "Explain what perplexity does and does not tell you
about quality."

---

## The problem

This row carries no project pull on the map, and it acquired one from the far
end of the stack. [drift-and-degradation.md](drift-and-degradation.md) found
that no gold-free signal saw a 12-point collapse in record accuracy, and the
signals people reach for next are exactly these four. So the question is not
what perplexity is. It is which of the four measures something a production
panel could act on, and the answer differs sharply between them.

## The mechanism

**Perplexity is not comparable across tokenizations, and the difference is not
small.** One unigram language model, trained on thirteen documents and
evaluated on the same four held-out documents -- 75 characters of Chinese in
every row:

```text
analyzer      train tokens   vocab  held-out tokens  bits/token  perplexity  ppl per char
unigram                203     156               75      7.8129      224.86        224.86
bigram                 190     186               71      8.3166      318.82        234.43
dictmatch               77      73               49      7.0139      129.24         23.96
```

The perplexity column moves by a factor of 2.5 and almost none of that movement
is about how well the text was predicted. It is about how many pieces the text
was cut into: perplexity is per *token*, so a tokenizer that emits fewer,
longer tokens reports a smaller number for the same predictions. Only the last
column -- total bits divided by the character count, which is constant across
rows -- compares. Two perplexities from two models with two tokenizers are two
different quantities, and this is why published perplexities are only ever
comparable within a fixed vocabulary.

**And the number is mostly a report on vocabulary coverage:**

```text
held-out tokens: 75   total surprisal: 586.0 bits
tokens never seen in training: 31 (41.3% of the held-out text), carrying
                               44.9% of the bits
```

Nearly half the score is the model paying for characters it had never seen.
That is a fact about the training corpus size, not about modelling.

**Unsmoothed, the same model on the same text has no perplexity at all** -- 31
tokens at probability zero, so cross-entropy is infinite. Which means the
number you do report is a function of the smoothing constant:

```text
   alpha   bits/token   perplexity
    0.01      10.2708      1235.45
     0.1       8.9290       487.42
     1.0       7.8129       224.86
    10.0       7.3660       164.96
```

A 7.5x range from a hyperparameter that is not part of the model. Between the
tokenizer and the smoothing, a bare perplexity is close to uninterpretable
without both stated.

**Predictive entropy is a measurement; a stated confidence is a token.** Naive
Bayes has a real posterior over the six event types; the extractor emits a
number it wrote:

```text
signal                          system           AUC  accuracy
stated confidence               extractor     0.7054    0.8007
top posterior probability       naive_bayes   0.7533    0.7774
negative posterior entropy      naive_bayes   0.7333    0.7774
```

**The free classifier's self-assessment separates its own errors better than
the model's stated confidence separates the model's** (0.7533 against 0.7054),
on records where the classifier is 2.3 points *less* accurate. That is a
directly usable result for a review queue: if the job is routing, the signal
does not have to come from the system whose errors you are routing.

Top-probability and entropy are not the same signal once there are more than
two outcomes -- they order 5.5% of record pairs differently, and the difference
is whether the leftover mass sits on one rival or is spread over five. Entropy
does track correctness monotonically:

```text
entropy band               n  accuracy  mean top p
[0.00, 0.25)              78    0.9487      0.9839
[0.25, 0.75)             104    0.8462      0.8998
[0.75, 1.50)             100    0.6100      0.6688
[1.50, 2.59)              19    0.5789      0.4871
```

**KL detects change and says nothing about quality.** The input token
distribution, early period against late:

```text
KL(late || early)          0.0614 bits
KL(early || late)          0.0600 bits   (not symmetric -- it is not a distance)
Jensen-Shannon             0.0150 bits

null JS over 30 random halves of the same data: median 0.0082, max 0.0110
observed early/late JS: 0.0150  -> above the null range
```

Two things. First, **the alarm needs a null or its threshold is invented**:
0.0150 means nothing until you know that splitting the same period at random
gives 0.0082 to 0.0110. The observed value clears the null band, but not by
much, for a mix change that is large and declared.

Second, and this is the ceiling on the whole approach: accuracy went from
0.8576 to 0.7617 across the same boundary, and
[leakage-and-shift.md](leakage-and-shift.md) established that the generator
contains **no quality change at all** -- the drop is entirely the class mix. KL
correctly reported that the input moved. It cannot say whether quality moved,
in which direction, or whether anything needs doing. It is a change detector
attached to a question about change, which is its one honest use: route the
alarm to a labelled eval run, never to a decision.

## The experiment

```powershell
cd modules\stats-lab
python entropy_lab.py
```

## Boundary

- **Seventeen documents is a language-model fixture** in the sense that twelve
  records is an eval set -- enough to compute the quantity and see its shape,
  not a measurement of Chinese. The 41% unseen-token rate is a corpus-size
  artifact; the fact that it dominates the score is not.
- **The model is unigram**, so it has no notion of context and its perplexity
  is not comparable with anything from a real language model. The tokenization
  and smoothing results are properties of the definition of perplexity and hold
  regardless.
- **The AUC comparison is between a real posterior and a generated
  confidence.** `population.CONFIDENCE_BIAS` decides how informative the
  extractor's number is, so the *gap* is a fixture property. The mechanism --
  a distribution over outcomes is a measurement, a self-reported confidence is
  an output token -- is not, and
  [drift-and-degradation.md](drift-and-degradation.md) measured the same thing
  from the other side: mean confidence moved 0.002 across a 12-point collapse.
- **A real model's token-level entropy is not this quantity.** It is the
  entropy over the next token, not over the answer, and the relationship
  between the two is exactly what a groundedness or abstention study has to
  establish. See [groundedness-and-citations.md](groundedness-and-citations.md).
- **Nothing here covers KL as a training objective**, which is where most of
  the literature about it lives.

## Cards

### 1. [misconception] Model A has perplexity 129 and model B has 225 on the same held-out documents, so A is the better model.

**Answer:** Not comparable unless they share a tokenizer. In the lab those two
numbers came from the *same* model over the *same* 75 characters of Chinese,
differing only in whether the text was cut into characters or dictionary words.
Normalised to bits per character the ordering survives but the gap changes
completely -- 23.96 against 224.86.

**Why:** Perplexity is per token. Fewer, longer tokens means fewer opportunities
to be surprised, so the average is smaller for identical predictions.

**Boundary:** Convert to bits per character (or per byte) when the tokenizers
differ, which is what makes cross-tokenizer comparisons legitimate. And check
the smoothing: in the lab the same model on the same text ranged from 165 to
1235 perplexity across four smoothing constants, and was infinite with none.

**Tags:** `perplexity` `tokenization` `metrics` `misconception` `general-principle`

---

### 2. [mechanism] You need a gold-free signal for which extractions to send to human review. Where should it come from?

**Answer:** Not necessarily from the extractor. In the lab a free naive Bayes
classifier's own posterior separated *its* errors at AUC 0.7533 while the
extractor's stated confidence separated its errors at 0.7054 -- and the
classifier was 2.3 points less accurate overall.

**Why:** A posterior over outcomes is computed from the evidence; a stated
confidence is a token the model produced, subject to the same pressures as the
rest of its output. One is a measurement, the other is a claim.

**Boundary:** Any confidence-shaped signal is still gold-free and therefore
still blind to semantic degradation --
[drift-and-degradation.md](drift-and-degradation.md) found mean confidence
moved 0.002 across a 12-point collapse. Use these for routing volume, never as
the quality panel. And where there are more than two outcomes, decide between
top-probability and entropy deliberately: they ordered 5.5% of pairs
differently here.

**Tags:** `entropy` `confidence` `routing` `mechanism` `general-principle`

---

### 3. [failure] A KL divergence alarm on your input distribution fires. What have you learned?

**Answer:** That the input moved. Nothing else. In the lab KL fired correctly on
a declared mix shift (JS 0.0150 against a null band of 0.0082-0.0110) while the
underlying per-class quality was stationary by construction -- the 10-point
accuracy drop across the same boundary was entirely composition.

**Why:** KL measures the distance between two distributions. It has no access to
labels, so it cannot know whether the new distribution is one the system handles
better or worse.

**Boundary:** It also needs a null before it means anything: compute the
divergence between two random halves of the *same* period to find the noise
floor, or the threshold is invented. And note KL is asymmetric (0.0614 one way,
0.0600 the other) -- use Jensen-Shannon if you want a symmetric quantity, and
say which you used.

**Tags:** `kl-divergence` `drift` `monitoring` `failure` `general-principle`
