"""Field-level provenance on the twelve gold records, and the three ways it lies.

    python provenance_lab.py

The cycle's evidence contract asks for "every extracted claim traceable to source
span and fetch time". This lab builds that, measures how much of it can actually
exist, and then breaks it the way it breaks in production -- by re-fetching a
document that changed.

The uncomfortable result is in section 2: the field this project's failures are
built around is the field that has no span to point at.
"""
from __future__ import annotations

import store

conn = store.build()
conn.executescript("""
    CREATE TABLE provenance (
        event_id     INTEGER NOT NULL,
        field        TEXT NOT NULL,
        value        TEXT,
        source_id    INTEGER NOT NULL,
        span_start   INTEGER,          -- NULL: the value is not in the text
        span_end     INTEGER,
        body_sha     TEXT NOT NULL,    -- what the document said when we read it
        extractor    TEXT NOT NULL,
        PRIMARY KEY (event_id, field, value)
    );
""")

EXTRACTOR = "extract-v3"      # records 8-12; 1-7 were done by v2
rows = conn.execute(
    "SELECT e.event_id, e.record_id, e.event_type, e.event_date, e.location,"
    " s.source_id, s.body, s.body_sha FROM events e JOIN sources s"
    " USING (source_id) ORDER BY e.event_id").fetchall()

for eid, rid, etype, date, loc, sid, body, bsha in rows:
    fields = [("event_type", etype), ("event_date", date), ("location", loc)]
    fields += [("actor", r[0]) for r in conn.execute(
        "SELECT name FROM actors WHERE event_id=? ORDER BY ordinal", (eid,))]
    fields += [("claim", r[0]) for r in conn.execute(
        "SELECT text FROM claims WHERE event_id=?", (eid,))]
    for field, value in fields:
        start = body.find(value) if value else -1
        conn.execute(
            "INSERT OR IGNORE INTO provenance VALUES (?,?,?,?,?,?,?,?)",
            (eid, field, value, sid,
             start if start >= 0 else None,
             start + len(value) if start >= 0 else None,
             bsha, EXTRACTOR if eid >= 8 else "extract-v2"))
conn.commit()

# --------------------------------------------------------------------------- #
store.rule("1. What fraction of the record can be traced at all")
# --------------------------------------------------------------------------- #
print(f"  {'field':<12} {'values':>7} {'with a span':>12} {'coverage':>9}")
for field, n, k in conn.execute(
        "SELECT field, count(*), count(span_start) FROM provenance"
        " GROUP BY field ORDER BY 2 DESC"):
    print(f"  {field:<12} {n:>7} {k:>12} {k / n:>8.0%}")
tot, span = conn.execute(
    "SELECT count(*), count(span_start) FROM provenance").fetchone()
print(f"  {'TOTAL':<12} {tot:>7} {span:>12} {span / tot:>8.0%}")
print()
print("  Just over a third of the extracted values can be pointed at a location")
print("  in the document they came from -- and this is the *optimistic* number,")
print("  measured against gold records on documents that genuinely contain them.")
print("  'Every claim traceable to a source span' is not a switch to turn on. It")
print("  is a per-field question with a different answer for each field.")
print()

# --------------------------------------------------------------------------- #
store.rule("2. The fields with no span, and why each one has none")
# --------------------------------------------------------------------------- #
for field in ("event_type", "event_date", "location", "actor", "claim"):
    miss = conn.execute(
        "SELECT count(*) FROM provenance WHERE field=? AND span_start IS NULL",
        (field,)).fetchone()[0]
    n = conn.execute("SELECT count(*) FROM provenance WHERE field=?",
                     (field,)).fetchone()[0]
    print(f"  {field:<12} {miss} of {n} untraceable")
print()
print("  Four different reasons, and they are not interchangeable:")
print()
print("  **event_type is inferred.** 'investment' is a label from a closed")
print("  vocabulary; it is nowhere in the text and never will be. A span for it")
print("  would have to be a *rationale span* -- the phrase that justified the")
print("  label -- which is a different thing needing a different policy.")
print()
print("  **event_date is computed.** The source says 一月十二日 or nothing at all;")
print("  the record says 2026-01-12. The normalizer is where the value came from,")
print("  so the honest provenance is a pointer to the *normalizer*, plus the raw")
print("  string it consumed. Neither is stored above, which is why the coverage")
print("  is what it is.")
print()
print("  **location is normalized.** '深圳市' is in the record and '深圳' is in")
print("  the text. The span exists; the exact-match lookup that built this table")
print("  cannot find it. This is a tooling gap, not a conceptual one, and it is")
print("  the only one of the four that is fixable by writing better code.")
print()
print("  **claims are paraphrases and some actors are absent.** Half the claims")
print("  were written by the labeller as summaries, not quoted, so no span")
print("  exists -- the same problem as event_type wearing a longer sentence. The")
print("  six untraceable *actors* are the interesting ones: a name in the record")
print("  that is nowhere in its source document is either a normalization")
print("  artifact or a value the extractor invented. **An untraceable actor is a")
print("  hallucination candidate**, and that is a cheap detector worth running on")
print("  the whole corpus -- no labels required, which puts it in the gold-free")
print("  grader family from ../deterministic-graders.md.")
print()
print("  Note which field is worst. `event_date` is the field whose failure this")
print("  entire cycle is organized around -- the model substituting the fetch")
print("  date, measured in ../structured-outputs.md and reproduced by a poisoned")
print("  passage in ../prompt-injection.md -- and it is the field with the least")
print("  provenance. **The fields that need auditing most are the ones hardest to")
print("  attribute**, because both properties come from the same cause: the value")
print("  was produced rather than copied.")
print()

# --------------------------------------------------------------------------- #
store.rule("3. Break it: the document changes under the citation")
# --------------------------------------------------------------------------- #
victim = 10          # R10: 隆基绿能与通威股份协调光伏减产
before = conn.execute("SELECT body, body_sha FROM sources WHERE source_id=?",
                      (victim,)).fetchone()
new_body = "通威股份取消"                # re-fetched: rewritten and cut down
conn.execute("UPDATE sources SET body=?, body_sha=?, fetched_at=?"
             " WHERE source_id=?",
             (new_body, store.sha(new_body), "2026-04-19T08:00:00Z", victim))
conn.commit()
print(f"  source {victim} was re-fetched. The article was rewritten and cut")
print(f"  down: the actor order swapped, 协调 (coordinate) became 取消 (cancel),")
print(f"  and the text is now shorter than it was.")
print()
print(f"  {'field':<10} {'stored span':<13} {'stored value':<10} "
      f"{'text at that span now':<12} verdict")
drift = intact = broken = 0
for field, value, s0, s1, bsha in conn.execute(
        "SELECT field, value, span_start, span_end, body_sha FROM provenance"
        " WHERE event_id=? AND span_start IS NOT NULL", (victim,)):
    now = new_body[s0:s1] if s1 <= len(new_body) else "(out of bounds)"
    if now == value:
        verdict, intact = "intact", intact + 1
    elif now == "(out of bounds)":
        verdict, broken = "out of bounds", broken + 1
    else:
        verdict, drift = "SILENT DRIFT", drift + 1
    print(f"  {field:<10} [{s0}:{s1}]{'':<7} {value:<10} {now:<12}   {verdict}")
print()
print(f"  intact {intact}, out of bounds {broken}, silently drifted {drift}")
print()
print("  Both failure modes, from one edit. The out-of-bounds span is harmless:")
print("  it raises, someone notices, the citation is visibly broken.")
print()
print("  The drifted span is the dangerous one. It still resolves, still")
print("  returns Chinese text of the right length, and still renders in a UI as")
print("  'here is where we got this'. It is now pointing at a different company.")
print()
print("  A citation that cannot fail loudly is not a citation. It is a decoration")
print("  that survives exactly as long as nobody edits the source.")
print()

# --------------------------------------------------------------------------- #
store.rule("4. The check that catches it, and where it has to live")
# --------------------------------------------------------------------------- #
stale = conn.execute("""
    SELECT count(*) FROM provenance p JOIN sources s USING (source_id)
     WHERE p.body_sha <> s.body_sha
""").fetchone()[0]
print(f"  SELECT count(*) FROM provenance p JOIN sources s USING (source_id)")
print(f"   WHERE p.body_sha <> s.body_sha        -> {stale}")
print()
print("  One join, one comparison, and it is exact: every span whose document")
print("  has changed since the span was recorded. It works because the hash was")
print("  written *beside the span*, at extraction time, by the same code that")
print("  wrote the span.")
print()
print("  Storing the hash only on `sources` would not work -- it moves with the")
print("  document, so there is nothing left to compare against. The whole")
print("  mechanism is the redundancy, and the instinct to normalize it away is")
print("  exactly wrong here. Provenance is a *snapshot of a belief*, so it is one")
print("  of the few places where duplicating a value is the correct design.")
print()

# --------------------------------------------------------------------------- #
store.rule("5. Lineage runs backwards, and that is the direction that matters")
# --------------------------------------------------------------------------- #
print("  Forwards -- 'where did this value come from' -- is what provenance is")
print("  usually sold as, and it is the easy direction:")
for field, value, url, fetched in conn.execute("""
        SELECT p.field, p.value, s.url, s.fetched_at
          FROM provenance p JOIN sources s USING (source_id)
         WHERE p.event_id = 3 AND p.field = 'actor' LIMIT 2"""):
    print(f"    {field:<6} {value:<10} <- {url}  fetched {fetched}")
print()
print("  Backwards -- 'this extractor was wrong, what did it touch' -- is the")
print("  query you write during an incident, and it needs the extractor version")
print("  stored per value rather than per run:")
affected = conn.execute("""
    SELECT count(DISTINCT event_id) FROM provenance
     WHERE extractor = ? AND field = 'event_date'""", (EXTRACTOR,)).fetchone()[0]
print(f"    SELECT DISTINCT event_id FROM provenance")
print(f"     WHERE extractor = '{EXTRACTOR}' AND field = 'event_date'")
print(f"    -> {affected} records to re-extract, and a precise list of which.")
print()
print("  Without that column the answer is 'everything since the deploy', which")
print("  means reprocessing the corpus and re-reviewing records that were fine.")
print("  The cost of the column is one TEXT per row. The cost of not having it")
print("  is paid once per incident, in review time, forever.")
print()

# --------------------------------------------------------------------------- #
store.rule("6. Four invariants worth asserting in CI")
# --------------------------------------------------------------------------- #
CHECKS = {
    "every event has a source":
        "SELECT count(*) FROM events WHERE source_id NOT IN"
        " (SELECT source_id FROM sources)",
    "every source has a fetch time":
        "SELECT count(*) FROM sources WHERE fetched_at IS NULL",
    "no span points outside its document":
        "SELECT count(*) FROM provenance p JOIN sources s USING (source_id)"
        " WHERE p.span_end > length(s.body)",
    "no span whose document has changed":
        "SELECT count(*) FROM provenance p JOIN sources s USING (source_id)"
        " WHERE p.body_sha <> s.body_sha",
}
for label, sql in CHECKS.items():
    n = conn.execute(sql).fetchone()[0]
    print(f"  {label:<38} {n:>4}   {'ok' if n == 0 else 'VIOLATED'}")
print()
print("  Two pass and two fail, which is the correct state for this database")
print("  right now -- a document was edited and nothing has re-extracted it yet.")
print("  A provenance schema with no failing check is a schema nobody has tested")
print("  against a changed source.")
print()
print("  What this contributes to the cycle: the error taxonomy in step 9 needs a")
print("  **provenance axis**. 'Wrong date' is not one failure class. It is at")
print("  least four -- the model invented it, the normalizer mis-parsed it, the")
print("  source said something different when we read it, or the source was")
print("  poisoned -- and only the columns above can tell them apart. Sorting them")
print("  by output alone is what makes an error taxonomy stop being actionable.")
