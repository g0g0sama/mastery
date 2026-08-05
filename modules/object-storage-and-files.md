# Object storage and file handling

**Micro module.** One mechanism, one experiment, three cards. Runs against
[service-lab/](service-lab/).

**Capability:** Object storage and file handling (Layer 1b, Aware -> Working).
Map evidence: "Ingest documents with content-addressed storage and dedup."

---

## The problem

Content addressing is usually sold as a dedup trick. The dedup is the part that
works least well; what it actually buys is that a filename cannot be an
instruction, and that verification cannot drift out of sync with the data.

## The mechanism

**What the hash considers "the same document".** One document, seven fetches:

```text
variant                       raw hash    normalized hash
original fetch                7c6f597e    7c6f597e
re-fetched, byte identical    7c6f597e    7c6f597e
re-fetched with a BOM         ae805de7    7c6f597e
trailing newline added        0c3832f4    7c6f597e
full-width space inserted     7dd17c4d    76f153c0
NFD instead of NFC            7c6f597e    7c6f597e
one character changed         738672f5    738672f5

distinct blobs: raw = 5, normalized = 3, out of 7 fetches
```

A content hash answers "are these the same bytes"; dedup needs "are these the
same document". The gap is every invisible difference a fetch introduces -- a
byte-order mark, a trailing newline, a full-width space, a Unicode
normalization form. The last is the nastiest: NFC and NFD render identically,
compare unequal, and are chosen by whatever produced the text rather than by
you. (Note the fourth row: Python's `.encode()` did not change form, so the raw
hashes matched here anyway -- which is exactly the kind of platform-dependent
luck you cannot rely on.)

Store **both** hashes. The raw hash is the provenance record -- it is what you
fetched, and [provenance-and-lineage.md](provenance-and-lineage.md) needs it to
detect a source changing under a stored span. The normalized hash is the dedup
key. Different questions; one column cannot answer both. And write the
normalizer down as a versioned artifact, because changing it silently
re-partitions the store: documents that were the same become different, nothing
errors, and the dedup ratio moves for no visible reason -- the same behavioural-
hash problem [eval-set-versioning.md](eval-set-versioning.md) measured on a
policy file.

**A partial write, and who notices.** The process dies halfway through storing
a document:

```text
write path             files on disk   read succeeds   corruption found
open, write, close     3               3/4             1 (by hash)
temp file + rename     3               3/4             0 -- nothing to find
```

Both are survivable and they fail differently. Writing in place leaves a
truncated file **under the name of the full one**: nothing is missing, so
nothing looks wrong, and every later reader gets half a document. Only the hash
check catches it, and only because the name *is* the hash. Temp-plus-rename
leaves a `.part` no reader looks for, and the real name never existed -- the
document is simply absent, which the metadata row notices.

The second costs one line: write to a temporary name **in the same directory**,
then `os.replace`, which is atomic on POSIX and Windows. Same directory matters
-- a rename across filesystems is a copy.

What neither buys is durability. `os.replace` orders the rename against the
data only if the data has reached the disk; surviving a *machine* crash needs
an `fsync` of the file and of the directory, which is a real per-document cost
rather than a free correctness win. Decide which failure you are defending
against.

**Filenames from a source that does not like you.** A document's own title or
URL used as a filename, on Windows:

```text
'../../etc/passwd'         ESCAPES the directory
'..\\..\\Windows\\...'     ESCAPES the directory
'C:\\Windows\\Temp\\x'     ESCAPES the directory
'report.txt'               written
'report.txt.'              written
'report.txt '              written
'Report.TXT'               written
'CON'                      written
'aaaa...300 chars.txt'     OSError 22
'näive.txt' (NFD)          written
'naïve.txt' (NFC)          written
```

Of 11 names: 3 escaped the directory before anything was written, 1 raised, and
**7 writes reported success -- but only 4 files exist.** Three successful
writes silently overwrote another document, and just 4 of the original names
can be read back with their own contents.

The collisions are the Windows-specific part and the dangerous part. A trailing
dot and a trailing space are stripped by the filesystem and comparison is
case-insensitive, so `report.txt.`, `report.txt ` and `Report.TXT` are one file
here and three on Linux. That is how a sanitizer written and tested on Linux
passes CI and destroys data in production, with every write returning success.

The list also cannot be completed. Every sanitizer is a blocklist against an OS
whose filename rules were never designed as a security boundary, and the rules
differ per platform, per filesystem, and per mount option. Content addressing
removes the category: a hex digest cannot traverse, cannot collide by case,
cannot be a device name, has fixed length, and is in one Unicode form by
construction. The original name is *data* -- store it in a column, where it is
a string rather than an instruction.

**The bytes and the row are two systems.** Process dies between them on 5 of
20:

```text
order                    blobs   rows   orphan blobs   dangling rows
row first, then blob     15      20     0              5
blob first, then row     20      15     5              0
```

Blob first. An orphan blob is disk space -- findable by a sweep, deletable at
leisure. A dangling row is a 404 or a 500 every time somebody opens that
document, and no sweep can invent the bytes. Same "prefer the loud failure,
then remove the choice" argument as
[background-jobs-queues.md](background-jobs-queues.md) section 1, with the same
escape: an outbox row rather than a direct second write.

Which brings the property of CAS that bites. Dedup means one blob can be
referenced by many documents, so **deleting a document must not delete its
bytes** -- another document may still point at them, possibly another tenant's.
The delete path needs a reference count or a mark-and-sweep against the
metadata table, and until it has one, "delete this document" is either a leak
or a corruption of someone else's data.
[retrieval-freshness-deletion.md](retrieval-freshness-deletion.md) found a
deleted document still reachable through two of four entry points; the blob
store is a fifth, and it is the one holding the actual text.

## The experiment

```powershell
cd modules\service-lab
python storage_lab.py     # ~5 s, real files on a real filesystem
```

## Boundary

- **Section 3 is measured on Windows and three of its results do not exist on
  Linux.** The trailing-dot, trailing-space and case collisions are the
  platform-specific ones, and they are the ones that matter, because they are
  invisible to a test suite that runs on the other platform. Re-run it on your
  deployment target rather than trusting the table.
- **A local directory is not object storage.** S3 and its equivalents have no
  rename, so "temp + rename" becomes "write to a key and then copy", eventual
  consistency on some operations, and per-request costs that make the two-level
  fanout irrelevant. The CAS and ordering arguments transfer; the atomicity
  mechanism does not.
- **No `fsync` anywhere in this lab**, so none of it survives a machine crash,
  only a process one. That is stated in section 2 rather than fixed, because
  the fix has a real cost per document.
- **Dedup ratios here are fixture-sized.** Seven fetches of one document is not
  evidence about a corpus; what the numbers show is which *classes* of
  near-duplicate a raw hash misses.

## Cards

### 1. [decision] Should a document's blob be named by its content hash or by its source-derived filename?

**Answer:** By the content hash, and not primarily for dedup. A hex digest
cannot traverse directories, cannot collide by case, cannot be a Windows device
name, has fixed length, and is in one Unicode form. In the lab, 11
source-derived names produced 3 directory escapes and 3 silent overwrites, with
every overwrite reporting success.

**Why:** A filename is interpreted by the OS, so an attacker-controlled
filename is attacker-controlled behaviour. Sanitizing is a blocklist against
rules that differ per platform, filesystem and mount option.

**Boundary:** Keep the original name as a column -- it is data users need. And
note the cost CAS introduces: one blob may be referenced by many documents, so
deletion needs a reference count or a mark-and-sweep, or "delete" either leaks
bytes or destroys another tenant's document.

**Tags:** `storage` `security` `decision` `general-principle`

---

### 2. [failure] A stored document reads back as half a document. What happened, and what would have prevented it?

**Answer:** The process died mid-write with the file opened under its final
name, so a truncated file exists where a complete one is expected -- nothing
is missing, so nothing looks wrong. Writing to a temp name in the same
directory and calling `os.replace` (atomic on POSIX and Windows) means the
final name either never appears or appears complete.

**Why:** Rename is atomic; write is not. Failure during a rename-based write
leaves an unreferenced partial file instead of a corrupt referenced one.

**Boundary:** This survives a process crash, not a machine crash -- durability
needs `fsync` on the file and the directory, at a real per-document cost. And
the corruption was only *detectable* because the filename was the content hash;
with an arbitrary name you need a separate checksum column that somebody has to
remember to write.

**Tags:** `storage` `atomicity` `failure` `general-principle`

---

### 3. [mechanism] Why does a content-addressed store need two hashes per document?

**Answer:** A raw hash of the fetched bytes and a hash of the normalized text.
The raw hash is the provenance record -- it proves what was fetched and detects
a source changing under a stored span. The normalized hash is the dedup key,
because a BOM, a trailing newline or an NFD/NFC difference makes bytes differ
while the document is the same.

**Why:** "Same bytes" and "same document" are different questions, and one
column cannot answer both.

**Boundary:** The normalizer is then a versioned artifact: changing it silently
re-partitions the whole store -- previously-identical documents become
distinct, nothing errors, and the dedup ratio moves for no visible reason.
Normalization also cannot catch semantic near-duplicates (a re-worded headline,
a syndicated copy); that needs similarity, not hashing.

**Tags:** `storage` `dedup` `mechanism` `general-principle`
