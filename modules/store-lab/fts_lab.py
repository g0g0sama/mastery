"""Full-text search over Chinese, in a real FTS engine, with the default settings.

    python fts_lab.py

../chinese-segmentation.md measured what segmentation does to recall in a BM25
implementation written by hand. This lab asks the question the project actually
faces: what does the *database* do, out of the box, on the same corpus and the
same six queries -- and it is a different and worse answer.

SQLite FTS5, not Postgres `tsvector`. The failure demonstrated in section 1 is
present in both and for the same reason, because both tokenize on character
class and Han script has no spaces to tokenize on. The remedies differ: FTS5 has
a built-in `trigram` tokenizer, Postgres needs an extension (`zhparser`,
`pg_jieba`). Section 5 states what does and does not transfer.
"""
from __future__ import annotations

import sqlite3

import store
from analyzers import bigram, dictmatch, unigram
from corpus import DOCS, QUERIES
from metrics import evaluate

conn = sqlite3.connect(":memory:")
conn.create_function("bigram_txt", 1, lambda t: " ".join(bigram(t)))
IDS = list(DOCS)

TABLES = {
    # name           tokenizer           how the text is stored
    "default": ("unicode61", lambda t: t),
    "trigram": ("trigram", lambda t: t),
    "unigram-split": ("unicode61", lambda t: " ".join(unigram(t))),
    "bigram-split": ("unicode61", lambda t: " ".join(bigram(t))),
    "dict-split": ("unicode61", lambda t: " ".join(dictmatch(t))),
}

for name, (tok, prep) in TABLES.items():
    tbl = "t_" + name.replace("-", "_")
    conn.execute(f"CREATE VIRTUAL TABLE {tbl} USING fts5(body, tokenize='{tok}')")
    conn.executemany(f"INSERT INTO {tbl}(rowid, body) VALUES (?,?)",
                     [(i + 1, prep(DOCS[d])) for i, d in enumerate(IDS)])
conn.commit()

print(f"{len(DOCS)} documents, {len(QUERIES)} queries, five FTS5 tables over the "
      f"same text.\n")


def search(tbl: str, query: str, prep, join: str = " OR ") -> list[str]:
    """Rank by FTS5's own bm25(). Lower is better, so ORDER BY is ascending."""
    terms = prep(query).split() if prep(query) != query else [query]
    expr = join.join(f'"{t}"' for t in terms)
    try:
        rows = conn.execute(
            f"SELECT rowid FROM {tbl} WHERE {tbl} MATCH ?"
            f" ORDER BY bm25({tbl}) LIMIT 10", (expr,)).fetchall()
    except sqlite3.OperationalError as exc:
        return [f"!{exc}"]
    return [IDS[r[0] - 1] for r in rows]


def score(name: str, join: str = " OR ") -> dict:
    tok, prep = TABLES[name]
    tbl = "t_" + name.replace("-", "_")
    rankings = {q: search(tbl, q.split(" ", 1)[1], prep, join) for q in QUERIES}
    return evaluate(rankings, QUERIES, k=5), rankings


# --------------------------------------------------------------------------- #
store.rule("1. The default tokenizer on Chinese")
# --------------------------------------------------------------------------- #
doc = DOCS["D03"]
conn.execute("CREATE VIRTUAL TABLE v_probe USING fts5vocab('t_default', 'row')")
vocab = [r[0] for r in conn.execute("SELECT term FROM v_probe ORDER BY term")]
print(f"  D03 is {len(doc)} characters long.")
print(f"  The whole `default` index contains {len(vocab)} distinct terms for "
      f"{len(DOCS)} documents.")
print(f"  Longest term in the index: {max(len(t) for t in vocab)} characters.")
print()
print("  `unicode61` splits on character *class*: it breaks at punctuation and")
print("  at the boundary between scripts, and Han characters are all one class.")
print("  A sentence with no spaces and no punctuation is therefore **one token**.")
print("  The index is not a word index; it is a list of whole sentences.")
print()
for q, expected in list(QUERIES.items())[:3]:
    got = search("t_default", q.split(" ", 1)[1], lambda t: t)
    print(f"    {q[:2]} -> {got or '(nothing)'}   (relevant: "
          f"{sorted(expected)})")
print()
print("  Nothing matches unless the query happens to be the entire document.")
print("  This is not a tuning problem or a ranking problem. The search feature")
print("  ships, passes its tests on English fixtures, and returns zero results")
print("  for every Chinese query -- which reads to a user as 'no news today'.")
print()

# --------------------------------------------------------------------------- #
store.rule("2. Five tokenization strategies, scored")
# --------------------------------------------------------------------------- #
print(f"  {'strategy':<16} {'recall@5':>9} {'MRR':>7} {'nDCG@5':>8}   note")
NOTES = {
    "default": "one token per sentence",
    "trigram": "built-in, substring matching",
    "unigram-split": "every character a term",
    "bigram-split": "the standard CJK baseline",
    "dict-split": "forward maximum matching, OOV falls back to chars",
}
results = {}
for name in TABLES:
    m, rankings = score(name)
    results[name] = (m, rankings)
    print(f"  {name:<16} {m['recall@k']:9.3f} {m['MRR']:7.3f} "
          f"{m['nDCG@k']:8.3f}   {NOTES[name]}")
print()
print("  The gap between the first row and the rest is the finding. Every one of")
print("  the remedies is cheap; not applying one costs the entire feature.")
print()
print("  Two rows need a caveat before they are quoted anywhere.")
print()
print("  `unigram-split` scores a perfect recall@5 and that is a property of a")
print("  17-document corpus, not a recommendation. Every character matches")
print("  something, and with 17 candidates there is nothing for the noise to")
print("  bury. ../chinese-segmentation.md measures the other side of that trade")
print("  -- precision -- on the same corpus, and the two modules together are the")
print("  argument for bigrams as the default rather than either extreme.")
print()
print("  `trigram` looks weak for a reason worth understanding: it does literal")
print("  substring matching. It answers 'is 出口管制 inside this document' well")
print("  and answers 'is this document about 动力电池 supply' not at all, because")
print("  those characters appear nowhere. Four of these six queries are")
print("  paraphrases. Trigram is the right tool for identifier and code search,")
print("  and the wrong one for topical search in any language.")
print()

# --------------------------------------------------------------------------- #
store.rule("3. The conjunction nobody chose")
# --------------------------------------------------------------------------- #
print(f"  {'strategy':<16} {'recall@5 (OR)':>14} {'recall@5 (AND)':>15}")
for name in ("unigram-split", "bigram-split", "dict-split"):
    or_m, _ = score(name, " OR ")
    and_m, _ = score(name, " AND ")
    print(f"  {name:<16} {or_m['recall@k']:14.3f} {and_m['recall@k']:15.3f}")
print()
print("  FTS5's implicit operator between two bare terms is AND, and so is")
print("  Postgres's `plainto_tsquery`. Every term must be present. On segmented")
print("  Chinese that is a strong requirement -- a four-character query becomes")
print("  three or four mandatory terms -- and it is chosen by *not writing an")
print("  operator*, which means it is never reviewed.")
print()
print("  Neither answer is right in general. AND is precision-first and correct")
print("  for a filter; OR with a good ranker is recall-first and correct for")
print("  search. The failure is having it decided by a default.")
print()

# --------------------------------------------------------------------------- #
store.rule("4. The query must be tokenized the same way as the document")
# --------------------------------------------------------------------------- #
q = "稀土永磁"     # out of dictionary: dictmatch falls back to characters
print(f"  query {q!r}, against the dict-split index:")
print(f"    segmented as document would be: {dictmatch(q)}")
print(f"    dict-split, query segmented   : {search('t_dict_split', q, lambda t: ' '.join(dictmatch(t)))}")
print(f"    dict-split, query raw         : {search('t_dict_split', q, lambda t: t)}")
print()
print("  The last line is the bug, and it is a *silent* zero rather than an")
print("  error: the index holds terms the raw query can never produce. Any")
print("  pipeline that segments at write time and forgets at read time -- or")
print("  changes the dictionary and does not reindex -- gets exactly this, and")
print("  the symptom is 'search got worse', reported months later.")
print()
print("  Same shape as the versioning failure in ../eval-set-versioning.md: two")
print("  sides of a comparison that must be produced by the same code, with")
print("  nothing in the schema forcing it. The remedy is also the same -- stamp")
print("  the index with the analyzer version and refuse a query stamped")
print("  differently.")
print()

# --------------------------------------------------------------------------- #
store.rule("5. What each strategy costs, and what transfers to Postgres")
# --------------------------------------------------------------------------- #
print(f"  {'strategy':<16} {'index bytes':>12} {'distinct terms':>15}")
for name in TABLES:
    tbl = "t_" + name.replace("-", "_")
    size = conn.execute(f"SELECT sum(length(block)) FROM {tbl}_data").fetchone()[0]
    conn.execute(f"CREATE VIRTUAL TABLE IF NOT EXISTS v_{tbl}"
                 f" USING fts5vocab('{tbl}', 'row')")
    terms = conn.execute(f"SELECT count(*) FROM v_{tbl}").fetchone()[0]
    print(f"  {name:<16} {size:>12,} {terms:>15,}")
print()
print("  Trigram buys substring matching -- the only strategy here that answers")
print("  a query about the middle of a word -- and pays for it in index size and")
print("  in a term list that has no relationship to meaning.")
print()
print("  Transfers to Postgres:")
print("    - the failure. `to_tsvector('simple', '稀土出口管制')` yields one")
print("      lexeme, for the same reason, and `'zh'` is not a bundled")
print("      configuration.")
print("    - the analyzer/query symmetry requirement, exactly.")
print("    - the AND default, via `plainto_tsquery`.")
print("  Does not transfer:")
print("    - the `trigram` tokenizer (Postgres has `pg_trgm`, which is a")
print("      similarity operator with different semantics, not an FTS parser).")
print("    - ranking. `bm25()` here, `ts_rank_cd` there, different formulas.")
print()
print("  The decision this lab supports for Sinoscope: **do not accept the")
print("  default text-search configuration**. Choose a segmenter, version it,")
print("  store the segmented form in its own column, and measure recall on a")
print("  judged query set before believing any of it -- which is why this module")
print("  comes after ../retrieval-metrics.md rather than before.")
