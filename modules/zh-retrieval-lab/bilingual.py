"""An English corpus, the same Chinese queries, and a hand-built concept space.

The Layer 6 map row is "zh query -> en document retrieval, scored". This fixture
is the smallest thing that makes that sentence measurable without a model.

Three honest warnings, because this fixture is easier to over-read than the
monolingual one:

1. CONCEPTS is a bilingual dictionary wearing a costume. A real multilingual
   encoder learns the alignment from parallel data; this one was typed by hand.
   What transfers is the GEOMETRY and the FAILURE SHAPES -- out-of-vocabulary
   entities, sense collisions, and the length effect on cosine. What does not
   transfer is coverage: a real encoder has an opinion about every string, and
   its gaps are invisible rather than listed in a dict literal.
2. GLOSSARY commits to one translation per term, which is what a cheap query
   translator does. A better translator produces alternatives; that is a
   different system, and the module says which failures it would fix.
3. Sixteen documents and six queries resolve a large effect, not a small one.
"""
from analyzers import ANALYZERS

# English documents. Deliberately NOT literal translations of DOCS in corpus.py
# -- a comparable corpus, not a parallel one, which is the case you actually
# have. E04 says "cell supply" where the query says 动力电池: the paraphrase gap
# survives the language gap, and only one of the three systems below crosses it.
DOCS_EN = {
    "E01": "Sinopec announces a new research and development center in Shenzhen",
    "E02": "PetroChina expands natural gas capacity in Xinjiang",
    "E03": "The Ministry of Industry and Information Technology convenes firms "
           "on rare earth export controls",
    "E04": "CATL and BMW Group sign a long term cell supply agreement",
    "E05": "BYD begins mass production at its new Zhengzhou plant",
    "E06": "Huawei rotates its chairman for the coming term",
    "E07": "The US Commerce Department adds SMIC to the entity list",
    "E08": "Yangtze Memory halts part of its Wuhan production line for maintenance",
    "E09": "NIO receives a new round of investment from the Hefei municipal government",
    "E10": "The National Development and Reform Commission comments on tariff measures",
    "E11": "LONGi and Tongwei coordinate a cut in solar output",
    "E12": "Xiaomi completes its second phase plant in Beijing",
    "E13": "COSCO and Maersk enter arbitration over freight rates",
    "E14": "Rare earth permanent magnet material export prices rise",
    # The cross-sense false match, carried across languages: "control" and
    # "export" both appear, in unrelated senses.
    "E15": "Air traffic control changes at Shenzhen airport affect export freight",
    "E16": "China Rare Earth Group consolidates northern rare earth assets",
}

# Same queries as corpus.py, judged against the English corpus.
QUERIES_ZH = {
    # 中石化 is the everyday abbreviation. It is absent from both the concept
    # lexicon and the maximum-matching dictionary -- the entity case.
    "Q1 中石化深圳投资": {"E01": 2},
    "Q2 出口管制": {"E03": 2, "E14": 1},
    # 动力电池 has no English cognate in the corpus; E04 says "cell".
    "Q3 动力电池供应": {"E04": 2},
    "Q4 光伏减产": {"E11": 2},
    "Q5 稀土永磁": {"E14": 2, "E16": 1, "E03": 1},
    "Q6 芯片制裁": {"E07": 2},
}

# --- system B: one translation per term, chosen greedily -------------------
# What a cheap query-translation layer does. Note 动力电池 -> "battery": correct,
# and still wrong for this corpus, because the document says "cell".
GLOSSARY = {
    "中石化": "sinopec", "中国石化": "sinopec", "深圳": "shenzhen",
    "投资": "investment", "出口": "export", "管制": "control",
    "动力电池": "battery", "电池": "battery", "供应": "supply",
    "光伏": "solar", "减产": "output cut", "稀土": "rare earth",
    "永磁": "permanent magnet", "芯片": "chip", "制裁": "sanction",
}

# --- system C: a shared concept space -------------------------------------
# Both sides map into the same concept ids. This is what a multilingual encoder
# gives you, minus the coverage and plus an audit trail.
ZH_CONCEPTS = {
    "中国石化": "SINOPEC", "石化": "PETROCHEM", "深圳": "SHENZHEN",
    "投资": "INVEST", "出口": "EXPORT", "管制": "CONTROL",
    "动力电池": "BATTERY", "电池": "BATTERY", "供应": "SUPPLY",
    "光伏": "SOLAR", "减产": "OUTPUT_CUT", "稀土": "RARE_EARTH",
    "永磁": "MAGNET", "芯片": "CHIP", "制裁": "SANCTION",
    # 中石化 is missing on purpose. So is 永磁 on the English side.
}
EN_CONCEPTS = {
    "sinopec": "SINOPEC", "petrochina": "PETROCHEM", "natural gas": "PETROCHEM",
    "shenzhen": "SHENZHEN", "investment": "INVEST", "invests": "INVEST",
    "export": "EXPORT", "exports": "EXPORT", "control": "CONTROL",
    "controls": "CONTROL", "air traffic": "AVIATION", "airport": "AVIATION",
    "battery": "BATTERY", "cell": "BATTERY", "supply": "SUPPLY",
    "solar": "SOLAR", "photovoltaic": "SOLAR", "cut": "OUTPUT_CUT",
    "rare earth": "RARE_EARTH", "permanent magnet": "MAGNET",
    "chip": "CHIP", "semiconductor": "CHIP", "memory": "CHIP",
    "entity list": "SANCTION", "sanction": "SANCTION", "tariff": "TARIFF",
    "freight": "SHIPPING", "arbitration": "DISPUTE", "plant": "FACTORY",
    "production": "FACTORY", "research and development": "RND",
    "government": "GOVERNMENT", "ministry": "GOVERNMENT",
    "commission": "GOVERNMENT", "commerce department": "GOVERNMENT",
    "price": "PRICE", "prices": "PRICE", "rates": "PRICE",
}

_EN_MAX = max(len(p.split()) for p in EN_CONCEPTS)
_ZH_MAX = max(len(w) for w in set(ZH_CONCEPTS) | set(GLOSSARY))


def english(text):
    """Whitespace tokens, lowercased, punctuation stripped."""
    return [t.strip(",.()").lower() for t in text.split() if t.strip(",.()")]


ANALYZERS["english"] = english        # so retrievers.Index can index DOCS_EN


def _zh_terms(text, table):
    """Forward maximum matching against one Chinese table."""
    chars = [c for c in text if c.strip()]
    out, i = [], 0
    while i < len(chars):
        for size in range(min(_ZH_MAX, len(chars) - i), 0, -1):
            span = "".join(chars[i:i + size])
            if span in table:
                out.append(span)
                i += size
                break
        else:
            i += 1
    return out


def translate(query):
    """System B: one English string per recognized Chinese term, concatenated.

    Unrecognized spans are dropped rather than transliterated -- which is what
    makes a missing entity a silent failure instead of a noisy one.
    """
    return " ".join(GLOSSARY[t] for t in _zh_terms(query, GLOSSARY))


def zh_vector(query):
    """System C, query side: concept counts from the Chinese lexicon."""
    v = {}
    for term in _zh_terms(query, ZH_CONCEPTS):
        c = ZH_CONCEPTS[term]
        v[c] = v.get(c, 0) + 1
    return v


def en_vector(text):
    """System C, document side: concept counts from the English lexicon.

    Longest phrase wins, so "air traffic control" contributes AVIATION for the
    first two tokens and CONTROL for the third -- the sense collision is built
    in, not simulated.
    """
    tokens = english(text)
    v, i = {}, 0
    while i < len(tokens):
        for size in range(min(_EN_MAX, len(tokens) - i), 0, -1):
            phrase = " ".join(tokens[i:i + size])
            if phrase in EN_CONCEPTS:
                c = EN_CONCEPTS[phrase]
                v[c] = v.get(c, 0) + 1
                i += size
                break
        else:
            i += 1
    return v


DOC_VECTORS = {d: en_vector(t) for d, t in DOCS_EN.items()}
