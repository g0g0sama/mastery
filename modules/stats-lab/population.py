"""Six hundred extraction records with a declared generative process.

Every other fixture in this repository either measures something real
(`store-lab`, `service-lab`) or drives a fake provider whose failure
distribution is asserted (`model-interface-lab` and its dependants). This one
is a third thing and the label matters more here than anywhere else: the
population below is **generated from parameters written at the top of this
file**. Nothing in it was observed.

That is not a defect for the Layer 2 rows, and it is worth being precise about
why. The results the labs report divide into two kinds:

- **Mathematical facts**, true of any dataset with these shapes: a monotone
  recalibration cannot change AUC, a group-correlated split inflates a holdout,
  accuracy and macro-F1 disagree under class imbalance, an equal-width binning
  of a calibration curve is a different estimator from an equal-count one.
  These would reproduce on your data. The generator only makes them visible.
- **Magnitudes** -- how many points a random split inflates by, how large the
  expected calibration error is. These are properties of the parameters below
  and transfer to nothing. Every module states which of its numbers is which.

What is declared here:

- base rates per event type, deliberately imbalanced (0.34 down to 0.06)
- the confusion structure: which types the extractor mistakes for which
- per-type extractor accuracy, and per-type confidence bias -- the extractor is
  overconfident everywhere and *most* overconfident on the class it is worst at,
  which is the usual direction and the one that hurts
- story clustering: one news story is covered by several outlets, so documents
  arrive in near-duplicate groups. This is the leakage mechanism and it is the
  most under-modelled property of real corpora
- a labeller who corrects extractor output rather than labelling blind, and
  notices only some of its errors

Vocabulary is borrowed from `../zh-retrieval-lab/` and the event types from
`../extraction-eval-sets/lab/policy.py`, so a record here is the same shape as
a record there. No script prints a raw field value -- Windows stdout falls back
to the ANSI codepage under redirection and raises on the first CJK character.
"""
from __future__ import annotations

import random

SEED = 20260805
N_DOCS = 600
N_DAYS = 120

EVENT_TYPES = (
    "investment",
    "trade_dispute",
    "plant_opening",
    "leadership_change",
    "sanction",
    "production_halt",
)

# Declared. Imbalanced on purpose: `sanction` is 6% of traffic and is the class
# every aggregate metric is free to ignore.
BASE_RATES = {
    "investment": 0.34,
    "trade_dispute": 0.22,
    "plant_opening": 0.16,
    "production_halt": 0.13,
    "leadership_change": 0.09,
    "sanction": 0.06,
}

# Declared. The mix is not stationary. From MIX_SHIFT_DAY the wire moves toward
# trade and sanctions coverage -- an ordinary editorial change, no model or code
# change anywhere. A split that ignores time cannot see it.
MIX_SHIFT_DAY = 60
BASE_RATES_LATE = {
    "investment": 0.20,
    "trade_dispute": 0.30,
    "plant_opening": 0.11,
    "production_halt": 0.12,
    "leadership_change": 0.09,
    "sanction": 0.18,
}

# Declared. When the extractor is wrong, it is not wrong uniformly -- it lands
# on the neighbour, which is what makes a confusion matrix worth printing and a
# single accuracy number worth distrusting.
CONFUSABLE = {
    "investment": "plant_opening",
    "plant_opening": "investment",
    "trade_dispute": "sanction",
    "sanction": "trade_dispute",
    "production_halt": "plant_opening",
    "leadership_change": "investment",
}

# Declared. Accuracy at median difficulty, per type.
ACCURACY = {
    "investment": 0.90,
    "trade_dispute": 0.76,
    "plant_opening": 0.82,
    "production_halt": 0.80,
    "leadership_change": 0.86,
    "sanction": 0.54,
}

# Declared. Added to the true probability of being correct to produce the
# stated confidence. Positive everywhere: the extractor is overconfident. The
# `sanction` row is the interesting one -- worst accuracy, largest bias.
CONFIDENCE_BIAS = {
    "investment": 0.06,
    "trade_dispute": 0.10,
    "plant_opening": 0.08,
    "production_halt": 0.09,
    "leadership_change": 0.07,
    "sanction": 0.30,
}

# Chinese tokens, per type, borrowed from the retrieval fixture's vocabulary.
KEYWORDS = {
    "investment": ["投资", "融资", "新一轮", "资金", "入股", "签署", "研发中心"],
    "trade_dispute": ["关税", "争议", "仲裁", "反倾销", "磋商", "运价", "措施"],
    "plant_opening": ["新工厂", "量产", "落成", "二期", "投产", "产能", "开工"],
    "leadership_change": ["董事长", "换届", "轮值", "辞任", "任命", "总裁", "接任"],
    "sanction": ["实体清单", "制裁", "管制", "出口", "禁令", "列入", "限制"],
    "production_halt": ["停产", "检修", "减产", "产线", "停工", "协调", "维护"],
}
GENERIC = ["公司", "集团", "宣布", "表示", "市场", "行业", "本周", "报道", "消息",
           "相关", "方面", "计划", "预计", "目前", "已经"]
OUTLETS = ["outlet_a", "outlet_b", "outlet_c", "outlet_d",
           "outlet_e", "outlet_f", "outlet_g", "outlet_h"]

# Declared. Story sizes: most stories are covered once, a few are covered by
# most of the wire. Sampled with replacement until N_DOCS is reached.
STORY_SIZES = (1, 1, 1, 1, 2, 2, 2, 3, 3, 4, 5, 6)

# Declared. How many of the confusable type's keywords a document also carries.
# Two of these values exceed the number of own-type keywords a document is
# likely to have, which is what puts irreducible error into the task.
CONTAMINATION = (0, 0, 1, 1, 1, 2, 2, 3)

# Declared. A labeller who reviews extractor output instead of labelling from
# scratch notices this fraction of its errors -- and fewer of them when the
# error is onto the confusable neighbour, because that is the error that reads
# as plausible.
NOTICE_RATE = 0.75
NOTICE_RATE_CONFUSABLE = 0.45


def _weighted(rng: random.Random, weights: dict[str, float]) -> str:
    r = rng.random() * sum(weights.values())
    for key, w in weights.items():
        r -= w
        if r <= 0:
            return key
    return next(reversed(weights))


def build(seed: int = SEED) -> list[dict]:
    """Return N_DOCS records. Deterministic in `seed`.

    Each record:
        id            "P0001"
        story         cluster id; siblings share ~80% of their tokens
        outlet        one of eight
        day           0..N_DAYS-1, increasing with story id
        event_type    the truth
        tokens        the document, as a bag of Chinese tokens
        pred          the extractor's event_type
        conf          the extractor's stated confidence in [0,1]
        correct       pred == event_type
        p_correct     the true probability of being correct. NOT observable in
                      any real system; present so the labs can show what a
                      calibration estimate is estimating
        corrected     the label a reviewing labeller would have written
    """
    rng = random.Random(seed)
    records: list[dict] = []
    story_id = 0

    while len(records) < N_DOCS:
        story_id += 1
        size = min(rng.choice(STORY_SIZES), N_DOCS - len(records))
        day = min(int(N_DAYS * len(records) / N_DOCS), N_DAYS - 1)
        truth = _weighted(rng, BASE_RATES if day < MIX_SHIFT_DAY else BASE_RATES_LATE)

        # The story's own tokens. Siblings resample a fifth of them, so
        # near-duplicates are near rather than identical.
        #
        # CONTAMINATION is the parameter that decides whether this fixture is
        # worth anything. Drawn only from the type's own keyword list, the six
        # classes are linearly separable and every classifier scores 0.99 --
        # a number about the generator and about nothing else. Each document
        # therefore also carries keywords belonging to the confusable
        # neighbour, and some documents carry more of those than of their own.
        core = rng.sample(KEYWORDS[truth], k=rng.randint(2, 4))
        core += rng.sample(GENERIC, k=rng.randint(2, 4))

        for _ in range(size):
            tokens = [t for t in core if rng.random() > 0.25]
            tokens += rng.sample(GENERIC, k=rng.randint(1, 2))
            n_conf = rng.choice(CONTAMINATION)
            tokens += rng.sample(KEYWORDS[CONFUSABLE[truth]], k=n_conf)
            if rng.random() < 0.10:  # a keyword from an unrelated type
                other = rng.choice([t for t in EVENT_TYPES
                                    if t not in (truth, CONFUSABLE[truth])])
                tokens.append(rng.choice(KEYWORDS[other]))

            # Difficulty is a property of the DOCUMENT, so a hard document is
            # hard for the classifier and for the model. The residual term is
            # the part that is idiosyncratic to the extractor.
            own = sum(1 for t in tokens if t in KEYWORDS[truth])
            ambiguity = n_conf / (own + n_conf) if (own + n_conf) else 1.0
            difficulty = min(1.0, max(0.0, 0.10 + 1.05 * ambiguity
                                      + rng.gauss(0.0, 0.18)))
            p_correct = min(0.99, max(0.05, ACCURACY[truth] * (1.25 - 0.50 * difficulty)))
            correct = rng.random() < p_correct
            pred = truth if correct else (
                CONFUSABLE[truth] if rng.random() < 0.70
                else rng.choice([t for t in EVENT_TYPES if t != truth])
            )

            conf = p_correct + CONFIDENCE_BIAS[truth] + rng.gauss(0.0, 0.06)
            conf = min(0.99, max(0.05, conf))

            notice = (NOTICE_RATE_CONFUSABLE if pred == CONFUSABLE[truth]
                      else NOTICE_RATE)
            corrected = truth if (correct or rng.random() < notice) else pred

            records.append({
                "id": f"P{len(records) + 1:04d}",
                "story": f"S{story_id:04d}",
                "outlet": rng.choice(OUTLETS),
                "day": day,
                "event_type": truth,
                "tokens": tokens,
                "pred": pred,
                "conf": round(conf, 4),
                "correct": pred == truth,
                "p_correct": round(p_correct, 4),
                "corrected": corrected,
            })

    return records


RECORDS = build()


def summary(records: list[dict] | None = None) -> str:
    records = records if records is not None else RECORDS
    n = len(records)
    stories = len({r["story"] for r in records})
    acc = sum(r["correct"] for r in records) / n
    lines = [
        f"{n} records, {stories} stories, {n / stories:.2f} documents per story",
        f"extractor accuracy overall: {acc:.4f}",
        "",
        f"{'event_type':<20}{'n':>6}{'share':>8}{'accuracy':>10}{'mean conf':>11}",
    ]
    for t in EVENT_TYPES:
        rows = [r for r in records if r["event_type"] == t]
        a = sum(r["correct"] for r in rows) / len(rows)
        c = sum(r["conf"] for r in rows) / len(rows)
        lines.append(f"{t:<20}{len(rows):>6}{len(rows) / n:>8.3f}{a:>10.4f}{c:>11.4f}")
    early = [r for r in records if r["day"] < MIX_SHIFT_DAY]
    late = [r for r in records if r["day"] >= MIX_SHIFT_DAY]
    lines += ["", f"mix before day {MIX_SHIFT_DAY} (n={len(early)}) against after "
                  f"(n={len(late)}):"]
    for t in EVENT_TYPES:
        a = sum(1 for r in early if r["event_type"] == t) / len(early)
        b = sum(1 for r in late if r["event_type"] == t) / len(late)
        lines.append(f"  {t:<20}{a:>8.3f}{b:>8.3f}{b - a:>+9.3f}")
    return "\n".join(lines)


if __name__ == "__main__":
    import sys

    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    print(summary())
