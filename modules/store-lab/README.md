# store-lab

A shared fixture for seven micro modules covering Layer 1c (data systems). Not a
module itself.

```powershell
cd modules\store-lab
python schema_lab.py      # ../sql-schema-design.md
python json_lab.py        # ../jsonb-vs-relational.md
python plan_lab.py        # ../indexes-and-query-plans.md
python fts_lab.py         # ../fulltext-search-zh.md
python migrate_lab.py     # ../migrations-and-versioning.md
python pipeline_lab.py    # ../incremental-pipelines.md
python provenance_lab.py  # ../provenance-and-lineage.md
```

CPython 3.14, stdlib only. Reuses the twelve gold records from
[../extraction-eval-sets/lab/](../extraction-eval-sets/lab/) and the Chinese
corpus, analyzers and metrics from [../zh-retrieval-lab/](../zh-retrieval-lab/)
via a `sys.path` insert.

| File | Role |
|---|---|
| `store.py` | schema, seeding, and the two measurement helpers every lab reports through |
| `schema_lab.py` | the same records as normalized, wide and EAV, plus three fields arriving later |
| `json_lab.py` | one field as a column and as a JSON path, on 40,000 rows |
| `plan_lab.py` | six queries, six predictions written before running, scored |
| `fts_lab.py` | five FTS5 tokenization strategies over Chinese, recall measured |
| `migrate_lab.py` | a schema change with v1 and v2 code live at once |
| `pipeline_lab.py` | four watermark strategies over five incremental runs |
| `provenance_lab.py` | field-level spans, and what a re-fetched document does to them |

## This fixture is different from the other three

`zh-retrieval-lab/`, `model-interface-lab/` and `agent-workflow-lab/` all
simulate the system under study. **This one does not.** SQLite plans the
queries, picks the indexes, runs the FTS tokenizer, holds the locks and rewrites
the tables. Every plan string, every timing and every recall number below came
out of a database rather than out of a generator, and several of them
contradicted the prediction written in the file before it ran.

What is still authored is the **data**: twelve labelled records and seventeen
sentences, padded to tens of thousands of synthetic rows with a fixed seed. That
matters more here than it would elsewhere, because cardinality and value
distribution are precisely what a query planner keys on. Treat the direction of
every result as evidence and the magnitude as fixture-specific.

## SQLite is not Postgres

The project targets Postgres. Three modules depend on the difference, so it is
stated once here and repeated in each:

| | SQLite (this lab) | Postgres (the project) |
|---|---|---|
| JSON | `TEXT` + `json_extract`, reparsed per row | `jsonb`, stored pre-parsed |
| Statistics | `sqlite_stat1`: one average per index | `pg_stats`: per-value histograms |
| Prefix `LIKE` | needs `case_sensitive_like` or `GLOB` | needs C collation or `text_pattern_ops` |
| Full text | FTS5, built-in `trigram` tokenizer | `tsvector`; Chinese needs `zhparser` / `pg_jieba` |
| `ADD COLUMN` | metadata-only | metadata-only since 11 |
| `DROP COLUMN` | rewrites the table | metadata-only, space reclaimed by `VACUUM` |
| Skip-scan | yes, on low-cardinality leading columns | no |

Every one of those rows changes a *number* in these labs and none of them
changes a *conclusion*, with one exception worth naming: the skip-scan in
`plan_lab.py` section 6 rescues a badly ordered composite index here and would
not rescue it in Postgres. That is called out where it happens.

## Read in this order

Each module uses the previous one's result:

1. `sql-schema-design` -- the grain, and what a field arriving later costs
2. `jsonb-vs-relational` -- where the fields that have not earned a column live
3. `indexes-and-query-plans` -- what it costs to ask a question of either shape
4. `fulltext-search-zh` -- the one question the index above cannot answer
5. `migrations-and-versioning` -- changing all of it with the code still running
6. `incremental-pipelines` -- keeping it current without losing rows
7. `provenance-and-lineage` -- knowing where every value in it came from

A module here is evidence of exposure, not of level. Levels move in
[../../capability-map.md](../../capability-map.md), and only on the five
conditions in the cycle's evidence contract.
