"""Shared fixture for the Layer 1c modules: events, sources, claims in SQLite.

    import store
    conn = store.build()          # schema + the 12 gold records
    store.seed_bulk(conn, 40_000) # synthetic rows, for anything timed

Unlike the other three fixtures in this repository, **the engine here is real**.
SQLite plans the queries, chooses the indexes, runs the FTS tokenizer, and
rewrites the tables. Every plan string and every timing below came out of the
database rather than out of a generator.

What is still fake: the data. Twelve labelled records and seventeen sentences,
padded to tens of thousands of synthetic rows with a fixed seed. Cardinalities
and value distributions are therefore authored, and those are exactly what a
query planner keys on -- so treat the *direction* of every result as evidence
and the *magnitude* as fixture-specific.

What is different from Postgres, stated once because three modules depend on it:

- SQLite has no `JSONB` column type. `json_extract` over a `TEXT` column is the
  closest analogue and it is *slower* than Postgres jsonb, which stores a parsed
  binary form. The structural argument (an unindexed JSON path is a full scan;
  indexing one means naming it) transfers; the constant factor does not.
- SQLite's planner is simpler and has no statistics unless `ANALYZE` is run.
  Where a module depends on statistics, it runs `ANALYZE` and says so.
- Full-text search is FTS5, not `tsvector`. The tokenizer lesson transfers
  exactly; the operator syntax does not. See ../fulltext-search-zh.md.
"""
from __future__ import annotations

import hashlib
import pathlib
import random
import sqlite3
import statistics
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_LAB = pathlib.Path(__file__).resolve().parent
for _p in (_LAB.parent / "extraction-eval-sets" / "lab", _LAB.parent / "zh-retrieval-lab"):
    if str(_p) not in sys.path:
        sys.path.insert(0, str(_p))

from gold import GOLD          # noqa: E402  12 hand-labelled records
from corpus import DOCS        # noqa: E402  17 Chinese sentences

# Which document each gold record was extracted from. The pairing is by content:
# R01 is the 中国石化 record and D01 is the 中国石化 sentence.
SOURCE_OF = {
    "R01": "D01", "R02": "D04", "R03": "D03", "R04": "D05", "R05": "D06",
    "R06": "D07", "R07": "D08", "R08": "D09", "R09": "D10", "R10": "D11",
    "R11": "D12", "R12": "D13",
}

EVENT_TYPES = ["investment", "trade_dispute", "plant_opening",
               "leadership_change", "sanction", "production_halt"]

BASE_SCHEMA = """
CREATE TABLE sources (
    source_id  INTEGER PRIMARY KEY,
    url        TEXT NOT NULL UNIQUE,
    fetched_at TEXT NOT NULL,
    body       TEXT NOT NULL,
    body_sha   TEXT NOT NULL
);

-- event_date is nullable on purpose, and null means "not stated in the source"
-- rather than "unknown". ../structured-outputs.md measured what happens when
-- it is not: a required field cannot be omitted, so abstention becomes
-- confabulation.
CREATE TABLE events (
    event_id   INTEGER PRIMARY KEY,
    record_id  TEXT UNIQUE,
    event_type TEXT NOT NULL,
    event_date TEXT,
    location   TEXT,
    source_id  INTEGER NOT NULL REFERENCES sources(source_id),
    confidence REAL,
    extra      TEXT DEFAULT '{}'      -- the JSON escape hatch. See ../jsonb-vs-relational.md
);

-- One row per actor, not a delimited string. The cardinality argument for this
-- is the whole of ../sql-schema-design.md section 3.
CREATE TABLE actors (
    event_id INTEGER NOT NULL REFERENCES events(event_id),
    ordinal  INTEGER NOT NULL,
    name     TEXT NOT NULL,
    PRIMARY KEY (event_id, ordinal)
);

CREATE TABLE claims (
    claim_id   INTEGER PRIMARY KEY,
    event_id   INTEGER NOT NULL REFERENCES events(event_id),
    text       TEXT NOT NULL,
    span_start INTEGER,
    span_end   INTEGER
);
"""


def sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()[:12]


def build(path: str = ":memory:") -> sqlite3.Connection:
    """Schema plus the twelve gold records, each joined to its source document."""
    conn = sqlite3.connect(path)
    conn.executescript(BASE_SCHEMA)
    for n, record in enumerate(GOLD, start=1):
        body = DOCS[SOURCE_OF[record["id"]]]
        src = record["source"]
        conn.execute(
            "INSERT INTO sources (source_id, url, fetched_at, body, body_sha)"
            " VALUES (?,?,?,?,?)",
            (n, src["url"], src["fetched_at"], body, sha(body)),
        )
        conn.execute(
            "INSERT INTO events (event_id, record_id, event_type, event_date,"
            " location, source_id, confidence) VALUES (?,?,?,?,?,?,?)",
            (n, record["id"], record["event_type"], record["time"],
             record["location"], n, record["confidence"]),
        )
        for i, name in enumerate(record["actors"]):
            conn.execute(
                "INSERT INTO actors (event_id, ordinal, name) VALUES (?,?,?)",
                (n, i, name),
            )
        for text in record["claims"]:
            conn.execute(
                "INSERT INTO claims (event_id, text, span_start, span_end)"
                " VALUES (?,?,?,?)",
                (n, text, None, None),
            )
    conn.commit()
    return conn


def seed_bulk(conn: sqlite3.Connection, n: int = 40_000, seed: int = 7) -> None:
    """n synthetic events, drawn from the gold rows with varied dates and types.

    The distribution is authored: event_type is skewed (investment is ~40% of
    rows), event_date spans four years, and one actor name is deliberately rare.
    Selectivity is the input to every planner decision, so it is stated here
    rather than discovered in a lab.
    """
    rng = random.Random(seed)
    weights = [40, 20, 15, 10, 10, 5]
    start_id = conn.execute("SELECT max(event_id) FROM events").fetchone()[0] + 1
    bodies = list(DOCS.values())
    rows_e, rows_s, rows_a = [], [], []
    for i in range(n):
        eid = start_id + i
        body = bodies[i % len(bodies)]
        rows_s.append((eid, f"https://example.test/bulk/{eid}",
                       f"2026-0{1 + i % 5}-0{1 + i % 9}T00:00:00Z", body, sha(body)))
        etype = rng.choices(EVENT_TYPES, weights=weights, k=1)[0]
        year = rng.choice([2023, 2024, 2025, 2026])
        date = f"{year}-{rng.randint(1, 12):02d}-{rng.randint(1, 28):02d}"
        rows_e.append((eid, f"B{eid}", etype, date, rng.choice(
            ["深圳市", "北京", "上海市", "武汉市", "合肥"]), eid,
            rng.choice([0.4, 0.7, 1.0]), '{}'))
        for j in range(rng.randint(1, 3)):
            # 稀土永磁研究院 appears in ~0.02% of rows: the selective needle that
            # ../indexes-and-query-plans.md section 2 is built around.
            name = ("稀土永磁研究院" if rng.random() < 0.0002
                    else rng.choice(["中国石化", "比亚迪", "华为技术有限公司",
                                     "宁德时代", "小米集团", "长江存储"]))
            rows_a.append((eid, j, name))
    conn.executemany("INSERT INTO sources VALUES (?,?,?,?,?)", rows_s)
    conn.executemany("INSERT INTO events VALUES (?,?,?,?,?,?,?,?)", rows_e)
    conn.executemany("INSERT INTO actors VALUES (?,?,?)", rows_a)
    conn.commit()


# --------------------------------------------------------------------------- #
# Measurement helpers. Every number printed by this lab comes through one of
# these two, so the methodology is in one place and can be argued with.
# --------------------------------------------------------------------------- #

def plan(conn: sqlite3.Connection, sql: str, params=()) -> list[str]:
    """The planner's own words. Read this before timing anything."""
    rows = conn.execute("EXPLAIN QUERY PLAN " + sql, params).fetchall()
    return [r[3] for r in rows]


def timed(conn: sqlite3.Connection, sql: str, params=(), repeat: int = 7) -> float:
    """Median wall-clock milliseconds over `repeat` runs, results fully consumed.

    Median rather than mean because one run in seven is routinely a page-cache
    miss, and a mean lets that single run decide the comparison. Consuming the
    cursor matters: SQLite is lazy, and timing `execute()` alone times parsing.
    """
    samples = []
    for _ in range(repeat):
        t0 = time.perf_counter()
        conn.execute(sql, params).fetchall()
        samples.append((time.perf_counter() - t0) * 1000)
    return statistics.median(samples)


def rule(title: str) -> None:
    print(f"=== {title} ===")
