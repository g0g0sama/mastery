"""A toy tokenizer, and an explicit statement of what it is not.

Real subword vocabularies are learned: tens of thousands of merges fitted to a
training corpus, where a frequent Chinese character is one token, a rare one
falls back to its UTF-8 bytes and costs two or three, and an English word of
four or five characters is usually one. This file reproduces that RULE and none
of that DATA.

Use it to understand why the ratio is what it is. Never use it to budget a real
batch -- for that, call the provider's own token counter, because the only
tokenizer whose count decides your bill is theirs.
"""

# A stand-in for "in the vocabulary as a single token". A real merge table holds
# tens of thousands of entries; this holds the characters common enough that any
# Chinese-capable vocabulary would certainly include them.
COMMON_ZH = set(
    "的一是不了在人有我他这个们中来上大为和国地到以说时要就出会可也你对生能而子那"
    "得于着下自之年过发后作里用道行所然家种事成方多经么去法学如都同现当没动面起看"
    "定天分还进好小部其些主样理心她本前开但因只从想实日军者意无力它与长把机十民第"
    "公此已工使情明性知全三又关点正业外将两高间由问很最重并物手应战向头文体政美相"
    "见被利什二等产或新己制身果加西斯月话合回特代内信表化老给世位次度门任常先海通"
    "教儿原东声提立及比员解水名真论处走义各入几口认条平系气题活尔更别打女变四神总"
    "何电数安少报才结反受目太量再感建务做接必场件计管期市直德资命山金指克许统区保"
    "至队形社便空决治展马科司五基眼书非则听白却界达光放强即像难且权思王象完设式色"
    "路记南品住告类求据程北边死张该交规万取拉格望觉术领共确传师观清今切院让识候带"
    "导争运笑飞风步改收根干造言联持组每济车亲极林服快办议往元英士证近失转夫令准布"
    "始怎呢存未远叫台单影具罗字爱击流备兵连调深商算质团集百需价花党华城石级整府离"
    "况亚请技际约示复病息究线似官火断精满支视消越器容照须九增研写称企八功吗包片史"
    "委乎查轻易早曼终章港湖登杂副挥密",
)

# Frequent English words that a learned vocabulary would hold whole.
COMMON_EN = {
    "the", "a", "an", "of", "in", "on", "at", "to", "for", "and", "or", "is",
    "was", "will", "new", "center", "group", "sign", "long", "term", "supply",
    "agreement", "export", "control", "controls", "rare", "earth", "list",
    "entity", "production", "line", "government", "investment", "round",
    "announce", "announces", "announced", "company", "plant", "date", "event",
    "json", "return", "only", "type", "actors", "location", "confidence",
}


def tokens(text):
    """Split into pseudo-tokens. The count is the point; the pieces are not."""
    out, buf = [], ""
    for ch in text:
        if ch.isascii() and (ch.isalnum() or ch == "'"):
            buf += ch
            continue
        if buf:
            out.extend(_ascii_word(buf))
            buf = ""
        if ch.isspace():
            continue
        if ch.isascii():
            out.append(ch)                       # punctuation: one token
        else:
            # In the vocabulary -> one token. Otherwise byte fallback, which for
            # a 3-byte UTF-8 character typically resolves to two tokens.
            out.extend([ch] if ch in COMMON_ZH else [ch + "#1", ch + "#2"])
    if buf:
        out.extend(_ascii_word(buf))
    return out


def _ascii_word(word):
    low = word.lower()
    if low in COMMON_EN or len(word) <= 4:
        return [word]
    return [word[i:i + 4] for i in range(0, len(word), 4)]


def count(text):
    return len(tokens(text))


def profile(text):
    """Characters, tokens, and the ratio that decides your context budget."""
    chars = len([c for c in text if not c.isspace()])
    n = count(text)
    return {"chars": chars, "tokens": n,
            "tokens_per_char": n / chars if chars else 0.0}
