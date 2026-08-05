"""service-lab -- the shared fixture for the eight Layer 1b modules.

    import service
    with service.serve(MyHandler) as base:      # real socket, ephemeral port
        service.get(base + "/events")           # real HTTP over loopback

Like ../store-lab/, **the machinery here is real**. There is a real TCP
listener, real HTTP framing, real kernel socket buffers, real SQLite locks,
real OS threads and a real filesystem. Every race in these labs is a race the
interpreter and the kernel actually ran; nothing schedules a duplicate on
purpose.

What is real / declared / derived, stated once so no table has to carry it:

  real       sockets, HTTP framing and chunked transfer, connection resets,
             the kernel's send buffer, SQLite transactions and lock contention,
             thread interleaving, file writes, renames, hashing, and every
             count computed from those.
  real, with a declared failure distribution
             the extraction records: they come from ../model-interface-lab's
             fake provider, whose failure weights are asserted rather than
             discovered. Any quality number inherits that caveat.
  declared   the request/arrival volumes, the tenant layout, provider latency
             (a sleep), the outage windows, and the 8-document corpus.
  derived    hit rates, amplification factors, duplicate counts as fractions,
             and every delta the labs print.

The one thing this fixture cannot show is scale. Loopback has no RTT, no
packet loss, no proxy, no load balancer and no second machine; SQLite is not
Postgres and has one writer. Directions transfer, magnitudes do not.

The centre of gravity is one event, and it is not a failure: **a client whose
request timed out and who therefore sends it again.** The server did not fail.
Six of the eight modules are about what some layer does with that second
delivery, and two are about the layer that cannot see it happened.
"""
from __future__ import annotations

import contextlib
import hashlib
import http.client
import json
import os
import pathlib
import shutil
import socket
import sqlite3
import sys
import tempfile
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

_LAB = pathlib.Path(__file__).resolve().parent
_MI = _LAB.parent / "model-interface-lab"
if str(_MI) not in sys.path:
    sys.path.insert(0, str(_MI))

from provider import MODELS, Provider, ProviderError, RateLimitError  # noqa: E402
from task import DOCUMENTS, record_correct, validate                  # noqa: E402

DOC_IDS = list(DOCUMENTS)
GOLD = {d: DOCUMENTS[d][1] for d in DOC_IDS}

# Two tenants, because every authorization bug in this repository needs a
# second principal to be visible at all. The split is uneven on purpose: a
# 6/2 split makes a post-filtered count leak loudly.
TENANTS = {"acme": DOC_IDS[:6], "globex": DOC_IDS[6:]}
OWNER = {d: t for t, ds in TENANTS.items() for d in ds}


# --------------------------------------------------------------------------- #
# Printing. Same three helpers as ../ops-lab/ops.py, kept local so two fixtures
# do not import each other for formatting.
# --------------------------------------------------------------------------- #

def rule(title: str) -> None:
    print(f"=== {title} ===")


def row(*cells, widths=None) -> None:
    widths = widths or [30] + [13] * (len(cells) - 1)
    print("".join(str(c).ljust(w) for c, w in zip(cells, widths)))


def pct(x: float) -> str:
    return f"{x * 100:.1f}%"


def sha(data) -> str:
    if isinstance(data, str):
        data = data.encode("utf-8")
    return hashlib.sha256(data).hexdigest()


# --------------------------------------------------------------------------- #
# The store. Real SQLite, WAL on, shared across threads on purpose -- the
# contention in tx_lab.py is the subject, not an accident.
# --------------------------------------------------------------------------- #

SCHEMA = """
PRAGMA journal_mode=WAL;

-- The ingest side. `body_sha` is the content address; see storage_lab.py for
-- why the raw and the normalized hash are different columns.
CREATE TABLE IF NOT EXISTS documents (
    doc_id     TEXT PRIMARY KEY,
    tenant     TEXT NOT NULL,
    url        TEXT NOT NULL,
    body       TEXT NOT NULL,
    body_sha   TEXT NOT NULL,
    fetched_at REAL NOT NULL
);

-- The write the whole fixture is arguing about. (doc_id, content_sha) is the
-- natural key that makes a replayed or retried extraction a no-op; see
-- idempotency_lab.py section 4 and ../failure-queues-and-replay.md.
CREATE TABLE IF NOT EXISTS events (
    event_id    INTEGER PRIMARY KEY,
    doc_id      TEXT NOT NULL,
    tenant      TEXT NOT NULL,
    event_type  TEXT,
    event_date  TEXT,
    actors      TEXT,
    content_sha TEXT NOT NULL,
    request_id  TEXT,
    created_at  REAL NOT NULL
);

-- Durable idempotency. The response body lives here too: a key that records
-- only "seen" answers the retry with 200 and nothing in it.
CREATE TABLE IF NOT EXISTS idem (
    key         TEXT PRIMARY KEY,
    tenant      TEXT NOT NULL,
    fingerprint TEXT NOT NULL,
    state       TEXT NOT NULL,          -- in_progress | done
    response    TEXT,
    created_at  REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS jobs (
    job_id     INTEGER PRIMARY KEY,
    doc_id     TEXT NOT NULL,
    payload    TEXT,
    state      TEXT NOT NULL,           -- ready | leased | done | parked
    attempts   INTEGER NOT NULL DEFAULT 0,
    lease_until REAL,
    fence      INTEGER NOT NULL DEFAULT 0,
    enqueued_at REAL NOT NULL
);

CREATE TABLE IF NOT EXISTS outbox (
    out_id  INTEGER PRIMARY KEY,
    doc_id  TEXT NOT NULL,
    sent    INTEGER NOT NULL DEFAULT 0
);
"""


def connect(path: str, timeout: float = 10.0) -> sqlite3.Connection:
    """One connection to an existing database. What a request handler calls.

    `busy_timeout` rather than an immediate SQLITE_BUSY, because the labs are
    measuring application-level contention and a five-millisecond lock wait is
    not the subject. tx_lab.py turns it back down where it is.
    """
    conn = sqlite3.connect(path, check_same_thread=False, timeout=timeout)
    conn.execute(f"PRAGMA busy_timeout={int(timeout * 1000)}")
    return conn


def store(path: str = ":memory:") -> sqlite3.Connection:
    """Create the schema. Call once per database, not once per request --
    `CREATE TABLE IF NOT EXISTS` still takes a write lock to decide it has
    nothing to do, which is its own small lesson about idempotent DDL."""
    conn = sqlite3.connect(path, check_same_thread=False, timeout=10.0)
    conn.executescript(SCHEMA)
    conn.commit()
    return conn


def seed_documents(conn: sqlite3.Connection) -> None:
    now = time.time()
    for doc_id in DOC_IDS:
        body = DOCUMENTS[doc_id][0]
        conn.execute(
            "INSERT OR REPLACE INTO documents VALUES (?,?,?,?,?,?)",
            (doc_id, OWNER[doc_id], f"https://example.test/{doc_id}",
             body, sha(body), now))
    conn.commit()


def content_sha(record: dict) -> str:
    """Identity of an extracted record, independent of when it was produced.

    Sorted keys and no timestamp: two extractions of the same document that
    agree must hash the same, or the natural key in `events` cannot suppress a
    duplicate. Anything in here that varies per request -- a request id, a
    wall clock -- makes every retry a new row.
    """
    return sha(json.dumps(record, sort_keys=True, ensure_ascii=False))[:16]


# --------------------------------------------------------------------------- #
# The work. One extraction, so every lab is measuring the same unit.
# --------------------------------------------------------------------------- #

def extract(doc_id: str, *, provider: Provider | None = None,
            latency: float = 0.0, attempt: int = 0) -> tuple[dict | None, str]:
    """Returns (record, status). Status is one of ok | invalid | unparsed.

    `latency` is a real sleep. It stands for a provider round trip and is the
    reason a transaction that spans this call is a different animal from one
    that does not (tx_lab.py section 2).
    """
    provider = provider or Provider("mid-1")
    if latency:
        time.sleep(latency)
    response = provider.complete(doc_id, attempt=attempt)
    obj, err = response.parse()
    if obj is None:
        return None, "unparsed"
    if validate(obj):
        return None, "invalid"
    return obj, "ok"


def correct(doc_id: str, record: dict | None) -> bool:
    return bool(record) and record_correct(record, GOLD[doc_id])


# --------------------------------------------------------------------------- #
# The HTTP layer. Real listener, real framing, ephemeral port.
# --------------------------------------------------------------------------- #

class Handler(BaseHTTPRequestHandler):
    """Base for the labs' handlers. Silences the access log; keeps the rest."""
    protocol_version = "HTTP/1.1"       # so keep-alive and chunked are on

    def log_message(self, *args) -> None:      # noqa: A003
        pass

    def send_json(self, status: int, obj) -> None:
        body = json.dumps(obj, ensure_ascii=False).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def read_json(self):
        n = int(self.headers.get("Content-Length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}


class _Server(ThreadingHTTPServer):
    """ThreadingHTTPServer that does not print a traceback for a dead peer.

    A client that vanished mid-response is the subject of http_lab.py, not an
    error, and socketserver's default handler dumps forty lines of stack for
    each one. Every other exception still prints.
    """
    daemon_threads = True

    def handle_error(self, request, client_address):
        exc = sys.exc_info()[1]
        if isinstance(exc, (ConnectionResetError, ConnectionAbortedError,
                            BrokenPipeError)):
            return
        super().handle_error(request, client_address)


@contextlib.contextmanager
def serve(handler_cls, **attrs):
    """A real server on 127.0.0.1 with an ephemeral port. Yields the base URL.

    `attrs` are set as class attributes on the handler, which is how a lab
    hands state (a connection, a policy flag) to a class the server
    instantiates per request.
    """
    for k, v in attrs.items():
        setattr(handler_cls, k, v)
    srv = _Server(("127.0.0.1", 0), handler_cls)
    srv.daemon_threads = True
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    try:
        yield f"http://127.0.0.1:{srv.server_address[1]}"
    finally:
        srv.shutdown()
        srv.server_close()


def request(base: str, method: str, path: str, body=None, headers=None,
            timeout: float = 10.0):
    """One request/response over a fresh connection. Returns (status, body)."""
    host = base.removeprefix("http://")
    conn = http.client.HTTPConnection(host, timeout=timeout)
    payload = json.dumps(body, ensure_ascii=False).encode() if body is not None else None
    hdrs = dict(headers or {})
    if payload is not None:
        hdrs.setdefault("Content-Type", "application/json")
    try:
        conn.request(method, path, payload, hdrs)
        resp = conn.getresponse()
        raw = resp.read()
        try:
            return resp.status, json.loads(raw)
        except (ValueError, UnicodeDecodeError):
            return resp.status, raw
    finally:
        conn.close()


def get(base, path, **kw):
    return request(base, "GET", path, **kw)


def post(base, path, body=None, **kw):
    return request(base, "POST", path, body, **kw)


def raw_socket(base: str) -> socket.socket:
    """A bare connection, for the cases where http.client is too helpful.

    Reading a chunked response one chunk at a time, and hanging up in the
    middle of one, both need the socket rather than the client.
    """
    host, port = base.removeprefix("http://").split(":")
    sock = socket.create_connection((host, int(port)), timeout=10.0)
    return sock


# --------------------------------------------------------------------------- #
# A temp directory that cleans itself up, for the blob store.
# --------------------------------------------------------------------------- #

@contextlib.contextmanager
def workdir(name: str = "service-lab"):
    path = pathlib.Path(tempfile.mkdtemp(prefix=name + "-"))
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)


def dir_bytes(path: pathlib.Path) -> int:
    return sum(f.stat().st_size for f in path.rglob("*") if f.is_file())


def file_count(path: pathlib.Path) -> int:
    return sum(1 for f in path.rglob("*") if f.is_file())


__all__ = [
    "rule", "row", "pct", "sha", "store", "connect", "seed_documents", "content_sha",
    "extract", "correct", "Handler", "serve", "request", "get", "post",
    "raw_socket", "workdir", "dir_bytes", "file_count",
    "DOC_IDS", "GOLD", "TENANTS", "OWNER", "DOCUMENTS", "Provider",
    "ProviderError", "RateLimitError", "MODELS", "os",
]
