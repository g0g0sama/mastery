"""Content-addressed storage: what the hash buys, and the four things it does not.

    python storage_lab.py     # ~5 s, real files on a real filesystem

Map evidence line: "ingest documents with content-addressed storage and dedup".
Every byte below is written to and read from disk; the crashes are real partial
writes and the hostile filenames are really resolved by this OS.

Windows matters here and is called out where it does. Three of the collisions
in section 3 do not exist on Linux and two of them are the interesting ones.
"""
from __future__ import annotations

import hashlib
import os
import pathlib
import unicodedata

import service as s

BOM = "\ufeff"


# --------------------------------------------------------------------------- #
class Blobs:
    """A content-addressed store. The filename IS the hash of the contents."""

    def __init__(self, root: pathlib.Path, atomic=True, verify=True):
        self.root, self.atomic, self.verify = root, atomic, verify
        root.mkdir(parents=True, exist_ok=True)
        self.writes = self.deduped = 0

    def path_for(self, digest: str) -> pathlib.Path:
        # two-level fanout: 65,536 directories rather than one with a million
        # entries in it, which is a real limit on some filesystems and a real
        # slowdown on the rest
        return self.root / digest[:2] / digest[2:4] / digest

    def put(self, data: bytes, crash_after: int | None = None) -> str:
        digest = hashlib.sha256(data).hexdigest()
        dest = self.path_for(digest)
        if dest.exists():
            self.deduped += 1
            return digest
        dest.parent.mkdir(parents=True, exist_ok=True)
        self.writes += 1
        if self.atomic:
            tmp = dest.with_suffix(".part")
            with open(tmp, "wb") as f:
                f.write(data if crash_after is None else data[:crash_after])
            if crash_after is not None:
                return digest          # the process died before the rename
            os.replace(tmp, dest)      # atomic on both Windows and POSIX
        else:
            with open(dest, "wb") as f:
                f.write(data if crash_after is None else data[:crash_after])
        return digest

    def get(self, digest: str) -> bytes | None:
        p = self.path_for(digest)
        if not p.exists():
            return None
        data = p.read_bytes()
        if self.verify and hashlib.sha256(data).hexdigest() != digest:
            raise ValueError(f"blob {digest[:8]} does not match its name")
        return data


def normalize(text: str) -> str:
    """What has to happen before a hash means 'the same document'.

    Every line here is a decision that must be written down, because changing
    one silently re-partitions the whole store -- the same behavioural-hash
    problem ../eval-set-versioning.md measured on a policy file.
    """
    text = text.lstrip(BOM)
    text = unicodedata.normalize("NFC", text)
    return " ".join(text.split())


print("Real files, real hashing, a real temp directory.\n")

# --------------------------------------------------------------------------- #
s.rule("1. What the hash considers 'the same document'")
# --------------------------------------------------------------------------- #
base = s.DOCUMENTS["N01"][0]
variants = [
    ("original fetch", base),
    ("re-fetched, byte identical", base),
    ("re-fetched with a BOM", BOM + base),
    ("trailing newline added", base + "\n"),
    ("full-width space inserted", base[:6] + "\u3000" + base[6:]),
    ("NFD instead of NFC", unicodedata.normalize("NFD", base)),
    ("one character changed", base.replace("三月十日", "三月十一日")),
]
with s.workdir() as d:
    raw = Blobs(d / "raw")
    norm = Blobs(d / "norm")
    s.row("variant", "raw hash", "normalized hash", "same doc?",
          widths=[30, 12, 18, 12])
    for label, text in variants:
        h1 = raw.put(text.encode("utf-8"))
        h2 = norm.put(normalize(text).encode("utf-8"))
        s.row(label, h1[:8], h2[:8],
              "no" if label.startswith("one character") else "yes",
              widths=[30, 12, 18, 12])
    print(f"\n  distinct blobs: raw = {raw.writes}, normalized = {norm.writes}, "
          f"out of {len(variants)} fetches")
print("""
  A content hash answers "are these the same bytes", and dedup needs "are these
  the same document". The gap is every invisible difference a fetch introduces:
  a byte-order mark, a trailing newline, a full-width space, and a Unicode
  normalization form -- the last of which is the nastiest, because NFC and NFD
  render identically, compare unequal, and are chosen by whatever produced the
  text rather than by you.

  Store both. The raw hash is the provenance record -- it is what you fetched,
  and ../provenance-and-lineage.md needs it to detect that a source changed
  under a stored span. The normalized hash is the dedup key. They are different
  questions and a single column cannot answer both.

  And write the normalizer down as a versioned artifact, because changing it
  silently re-partitions the entire store: documents that were the same become
  different, nothing errors, and the dedup ratio moves for no visible reason.
""")

# --------------------------------------------------------------------------- #
s.rule("2. A partial write, and who notices")
# --------------------------------------------------------------------------- #
print("The process dies halfway through storing a document. Two write paths,\n"
      "then a read of every blob with the hash verified.\n")
s.row("write path", "files on disk", "read succeeds", "corruption found",
      widths=[26, 16, 16, 20])
for label, atomic in (("open, write, close", False),
                      ("temp file + rename", True)):
    with s.workdir() as d:
        store = Blobs(d / "b", atomic=atomic)
        digests = []
        for i, (_, text) in enumerate(variants[:4]):
            data = text.encode("utf-8")
            crash = len(data) // 2 if i == 2 else None
            digests.append(store.put(data, crash_after=crash))
        found, ok = 0, 0
        for h in digests:
            try:
                if store.get(h) is not None:
                    ok += 1
            except ValueError:
                found += 1
        files = s.file_count(d / "b")
    s.row(label, files, f"{ok}/{len(digests)}",
          f"{found} (by hash)" if found else "0 -- nothing to find",
          widths=[26, 16, 16, 20])
print("""
  The two rows fail differently and both are survivable, which is the point:

    write in place    a truncated file exists under the name of the full one.
                      Nothing is missing, so nothing looks wrong, and every
                      later reader gets half a document. Only the hash check
                      catches it -- and only because the name is the hash.
    temp + rename     the partial file is a `.part` that no reader looks for,
                      and the real name never existed. The document is simply
                      absent, which the metadata row will notice.

  The second is the one you want and it costs one line: write to a temporary
  name in the same directory, then `os.replace`, which is atomic on POSIX and
  on Windows. Same directory matters -- a rename across filesystems is a copy.

  What neither buys is durability. `os.replace` orders the rename against the
  data only if the data has actually reached the disk; a crash of the *machine*
  rather than the process needs an `fsync` of the file and of the directory,
  and that is a real cost per document rather than a free correctness win.
  Decide which failure you are defending against, because they have different
  prices.

  The unnamed third option is the one CAS makes unnecessary: verifying content
  after a read is normally an extra checksum column somebody has to remember to
  write. Here the filename is the checksum, so verification is free and cannot
  drift out of sync with the data.
""")

# --------------------------------------------------------------------------- #
s.rule("3. Filenames from a source that does not like you")
# --------------------------------------------------------------------------- #
print("A document's own title or URL, used as a filename. Naive join versus\n"
      "content addressing, on this OS:\n")
HOSTILE = [
    ("../../etc/passwd", "parent traversal"),
    ("..\\..\\Windows\\System32\\x", "backslash traversal"),
    ("C:\\Windows\\Temp\\x", "absolute path"),
    ("report.txt", "the honest baseline"),
    ("report.txt.", "trailing dot"),
    ("report.txt ", "trailing space"),
    ("Report.TXT", "different case"),
    ("CON", "Windows device name"),
    ("a" * 300 + ".txt", "over the path length limit"),
    ("na\u0308ive.txt", "NFD form of naive.txt"),
    ("na\u00efve.txt", "NFC form of naive.txt"),
]
with s.workdir() as d:
    target = d / "docs"
    target.mkdir()
    escaped = failed = written = 0
    for i, (name, why) in enumerate(HOSTILE):
        joined = os.path.normpath(os.path.join(str(target), name))
        inside = os.path.abspath(joined).startswith(os.path.abspath(str(target)))
        if not inside:
            escaped += 1
            verdict = "ESCAPES the directory"
        else:
            try:
                # distinct contents per name, so a collision is detectable by
                # reading back rather than by reasoning about the string
                pathlib.Path(joined).write_bytes(str(i).encode())
                written += 1
                verdict = "written"
            except OSError as exc:
                failed += 1
                verdict = f"OSError {exc.errno}"
        s.row(repr(name)[:32] + ("..." if len(repr(name)) > 32 else ""),
              why, verdict, widths=[36, 30, 26])
    landed = [p for p in target.rglob("*") if p.is_file()]
    survived = sum(1 for i, (name, _) in enumerate(HOSTILE)
                   for p in landed
                   if p.read_bytes() == str(i).encode())
    collided = written - len(landed)
print(f"""
  Of {len(HOSTILE)} names: {escaped} escaped the target directory before
  anything was written, {failed} raised, and {written} writes reported success.
  Only {len(landed)} files exist afterwards, so {collided} of those successful
  writes silently overwrote another document, and just {survived} of the
  original names can be read back with their own contents.

  The collisions are the Windows-specific part and they are the dangerous part:
  a trailing dot and a trailing space are stripped by the filesystem, and the
  comparison is case-insensitive, so `report.txt.`, `report.txt ` and
  `Report.TXT` are all one file here and three files on Linux. That is how a
  sanitizer written and tested on Linux passes CI and destroys data in
  production, with every write returning success.

  The list is also not complete, and cannot be. Every sanitizer is a blocklist
  against an OS whose filename rules were not designed as a security boundary,
  and the rules differ per platform, per filesystem, and per mount option.

  Content addressing removes the entire category. A hex digest cannot traverse,
  cannot collide by case, cannot be a device name, has a fixed length, and is
  in one Unicode form by construction. The original name is data -- store it in
  a column, where it is a string rather than an instruction.
""")

# --------------------------------------------------------------------------- #
s.rule("4. The bytes and the row are two systems")
# --------------------------------------------------------------------------- #
print("Storing a document means writing a blob AND a metadata row. The process\n"
      "dies between them on 5 of 20.\n")
s.row("order", "blobs", "rows", "orphan blobs", "dangling rows",
      widths=[26, 9, 9, 15, 15])
for label, blob_first in (("row first, then blob", False),
                          ("blob first, then row", True)):
    with s.workdir() as d:
        store = Blobs(d / "b")
        conn = s.store(str(d / "m.db"))
        crash_on = {3, 7, 11, 15, 19}
        for i in range(20):
            text = s.DOCUMENTS[s.DOC_IDS[i % 8]][0] + f" #{i}"
            data = text.encode("utf-8")
            digest = hashlib.sha256(data).hexdigest()
            if blob_first:
                store.put(data)
                if i in crash_on:
                    continue
                conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                             (f"D{i}", "acme", f"u/{i}", "", digest, 0))
            else:
                conn.execute("INSERT INTO documents VALUES (?,?,?,?,?,?)",
                             (f"D{i}", "acme", f"u/{i}", "", digest, 0))
                conn.commit()
                if i in crash_on:
                    continue
                store.put(data)
            conn.commit()
        rows = conn.execute("SELECT body_sha FROM documents").fetchall()
        row_shas = {r[0] for r in rows}
        on_disk = {p.name for p in (d / "b").rglob("*") if p.is_file()}
        conn.close()
    s.row(label, len(on_disk), len(rows), len(on_disk - row_shas),
          len(row_shas - on_disk), widths=[26, 9, 9, 15, 15])
print("""
  Blob first. An orphan blob is disk space, findable by a sweep and deletable
  at leisure; a dangling row is a 404 or a 500 every time somebody opens that
  document, and no sweep can invent the bytes. Write the bytes, then commit the
  row that points at them -- the same "prefer the loud failure, then remove the
  choice" argument as ../background-jobs-queues.md section 1, and the same
  answer if you want to remove it: an outbox row for the delete, not a delete.

  Which brings the last property of CAS, and it is the one that bites. Dedup
  means one blob can be referenced by many documents, so deleting a document
  must not delete its bytes -- another document may still be pointing at them,
  possibly another *tenant's*. The delete path needs a reference count or a
  mark-and-sweep against the metadata table, and until it has one, "delete this
  document" is either a leak or a corruption of someone else's data.

  ../retrieval-freshness-deletion.md found a deleted document still reachable
  through two of four entry points. The blob store is a fifth, and it is the
  one that keeps the actual text.
""")
