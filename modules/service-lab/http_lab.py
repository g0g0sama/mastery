"""What a real socket does to the four HTTP beliefs a service is built on.

    python http_lab.py        # ~12 s, binds an ephemeral port on 127.0.0.1

Map evidence line: "stream a model response with correct cancellation on client
disconnect". Both halves are measured here, and neither behaves the way the
sentence implies.

Four predictions, written before the file ran:

  P1  a mid-stream failure after a 200 is visible to the client       -> ?
  P2  the server notices a vanished client on its next write          -> ?
  P3  a streaming handler stops within a chunk of the disconnect      -> ?
  P4  streaming trades total time for first-byte time                 -> ?

Section 6 scores them.
"""
from __future__ import annotations

import json
import socket
import struct
import threading
import time

import service as s

PROBE = {}          # server-side observations, read after each experiment


# --------------------------------------------------------------------------- #
class Streamer(s.Handler):
    """One handler, four endpoints, all writing the same eight records."""

    fail_after = None          # emit this many records, then raise
    sentinel = False           # terminate the stream with an explicit event
    chunk_bytes = 64
    budget = 8 * 1024 * 1024   # bytes, so no loop here can run away
    work = 0.0                 # seconds of real work before each chunk
    units = 8
    flush_every = 1            # write every Nth unit -- a proxy's buffer

    def _chunk(self, data: bytes) -> None:
        self.wfile.write(b"%x\r\n%s\r\n" % (len(data), data))

    def _start_chunked(self, ctype="application/x-ndjson"):
        self.send_response(200)
        self.send_header("Content-Type", ctype)
        self.send_header("Transfer-Encoding", "chunked")
        self.end_headers()

    def do_GET(self):                                   # noqa: N802
        route = self.path.split("?")[0]
        return {"/records": self.records, "/firehose": self.firehose,
                "/work": self.work_stream, "/buffered": self.buffered
                }.get(route, lambda: self.send_json(404, {}))()

    # -- 1. eight records, streamed, with an error partway through ----------
    def records(self):
        self._start_chunked()
        sent = 0
        try:
            for i, doc_id in enumerate(s.DOC_IDS):
                if self.fail_after is not None and i >= self.fail_after:
                    raise RuntimeError("upstream provider failed mid-stream")
                self._chunk((json.dumps({"doc_id": doc_id, "n": i},
                                        ensure_ascii=False) + "\n").encode())
                sent += 1
            if self.sentinel:
                self._chunk((json.dumps({"done": True, "count": len(s.DOC_IDS)})
                             + "\n").encode())
        except RuntimeError:
            # There is no third option. The status line left the building eight
            # records ago; all that remains is to stop writing.
            PROBE["records_sent"] = sent
        self.wfile.write(b"0\r\n\r\n")

    # -- 2. write as fast as possible until the peer objects ----------------
    def firehose(self):
        self._start_chunked("application/octet-stream")
        payload = b"x" * self.chunk_bytes
        written = 0
        try:
            while written < self.budget:
                self._chunk(payload)
                written += len(payload)
        except OSError as exc:
            PROBE["errno"] = type(exc).__name__
        else:
            PROBE["errno"] = f"none -- hit the {self.budget // 1024} KB budget"
        PROBE["bytes_written"] = written

    # -- 3. slow producer: real work between writes -------------------------
    def work_stream(self):
        self._start_chunked()
        done = 0
        pending = []
        try:
            for i in range(self.units):
                time.sleep(self.work)          # stands for a provider call
                done += 1
                pending.append(json.dumps({"n": i}).encode() + b"\n")
                if len(pending) >= self.flush_every:
                    self._chunk(b"".join(pending))
                    pending.clear()
            if pending:
                self._chunk(b"".join(pending))
            self.wfile.write(b"0\r\n\r\n")
        except OSError as exc:
            PROBE["errno"] = type(exc).__name__
        PROBE["units_done"] = done

    # -- 4. the same work, buffered until it is all finished ----------------
    def buffered(self):
        done = 0
        out = []
        for i in range(self.units):
            time.sleep(self.work)
            done += 1
            out.append({"n": i})
        PROBE["units_done"] = done
        self.send_json(200, out)


def read_ndjson(base: str, path: str):
    """A client that trusts end-of-body to mean end-of-results."""
    status, raw = s.get(base, path)
    if isinstance(raw, (dict, list)):
        raw = json.dumps(raw).encode()
    return status, [json.loads(x) for x in raw.decode().splitlines() if x.strip()]


def abandon(base: str, path: str, mode: str, after: float = 0.15) -> None:
    """Start a request, then leave. Two ways of leaving, both real."""
    sock = s.raw_socket(base)
    sock.sendall(f"GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
                 .encode())
    time.sleep(after)
    if mode == "reset":
        # SO_LINGER with a zero timeout makes close() emit RST instead of FIN.
        # The killed browser tab, the evicted pod, the load balancer giving up.
        sock.setsockopt(socket.SOL_SOCKET, socket.SO_LINGER,
                        struct.pack("ii", 1, 0))
    sock.close()


print("A real listener on 127.0.0.1, real HTTP/1.1 framing, real socket buffers.\n"
      "Every number below came out of the kernel, not out of a generator.\n")

# --------------------------------------------------------------------------- #
s.rule("1. A 200 is a promise made before the work is done")
# --------------------------------------------------------------------------- #
print("Eight records, streamed as ndjson. The upstream fails after three.\n")
s.row("client framing", "status", "records", "client saw a failure?",
      widths=[26, 9, 10, 24])
for label, sentinel in (("bare ndjson", False), ("ndjson + done sentinel", True)):
    with s.serve(Streamer, fail_after=3, sentinel=sentinel) as base:
        status, lines = read_ndjson(base, "/records")
    complete = any(x.get("done") for x in lines)
    s.row(label, status, len(lines),
          "YES" if (sentinel and not complete) else "no -- looks like 3 results",
          widths=[26, 9, 10, 24])
with s.serve(Streamer, fail_after=None, sentinel=True) as base:
    status, lines = read_ndjson(base, "/records")
s.row("  control, no failure", status, f"{len(lines) - 1}+1",
      f"sentinel present = {any(x.get('done') for x in lines)}",
      widths=[26, 9, 10, 24])
print("""
  The status line is written before the first record is produced, so a failure
  after it cannot lower the status. Worse than a truncated body: the body is
  not truncated, it is *complete and short*. Three well-formed objects, a clean
  end of stream, no exception at any layer. The client cannot distinguish that
  from a document set that only had three matches.

  After the commitment point the only signal left is one the client agrees in
  advance to check -- a terminal event or an HTTP trailer -- plus a client that
  treats its absence as an error. Neither exists by default.
""")

# --------------------------------------------------------------------------- #
s.rule("2. The server does not find out when the client leaves")
# --------------------------------------------------------------------------- #
print("Client sends the request, waits 150 ms, then goes. The server writes\n"
      "64-byte chunks at full speed. How much does it write before the OS says no?\n")
s.row("how the client left", "server got", "bytes written", "writes",
      widths=[26, 26, 16, 10])
for label, mode in (("FIN (graceful close)", "fin"), ("RST (killed)", "reset")):
    PROBE.clear()
    with s.serve(Streamer, chunk_bytes=64, budget=8 * 1024 * 1024) as base:
        t = threading.Thread(target=abandon, args=(base, "/firehose", mode))
        t.start(); t.join()
        time.sleep(1.2)
        written, err = PROBE.get("bytes_written", 0), PROBE.get("errno", "-")
    s.row(label, err, f"{written:,}", f"{written // 64:,}", widths=[26, 26, 16, 10])
print("""
  Nothing in that path is instantaneous. The write goes into the kernel's send
  buffer and returns; the peer's receive buffer absorbs more; only when both
  fill does the next write block, and only once the RST has been received and
  processed does it raise. Loopback with a 64-byte payload turns "the client is
  gone" into thousands of successful writes.

  Note that the two rows agree. A "graceful" FIN is graceful only for a peer
  that has finished; a client that closes mid-response has an OS that will RST
  the next byte that arrives, so the server sees the identical error either
  way and cannot tell a cancelled request from a crashed client.

  Two consequences. A `try/except OSError` around the write is a real
  cancellation signal but a *late* one. And an idle connection tells you
  nothing at all -- if the handler is not writing it will never learn, which is
  what a keepalive or heartbeat frame is actually for.
""")

# --------------------------------------------------------------------------- #
s.rule("3. What cancellation is worth, and who takes it away")
# --------------------------------------------------------------------------- #
print("Twenty units of 40 ms work = 0.8 s of provider time. The client leaves\n"
      "after 150 ms, by which point ~4 units are legitimately owed.\n")
s.row("response shape", "units done", "wasted work", "cancelled?",
      widths=[34, 13, 15, 12])
cases = [("buffered (Content-Length)", "/buffered", 1),
         ("streamed, flush every unit", "/work", 1),
         ("streamed, flush every 8 units", "/work", 8)]
for label, path, flush in cases:
    PROBE.clear()
    with s.serve(Streamer, units=20, work=0.04, flush_every=flush) as base:
        t = threading.Thread(target=abandon, args=(base, path, "reset"))
        t.start(); t.join()
        time.sleep(1.6)
        done = PROBE.get("units_done", 0)
    s.row(label, f"{done}/20", f"{max(0, done - 4) * 0.04:.2f} s",
          "no" if done >= 20 else "yes", widths=[34, 13, 15, 12])
print("""
  Streaming is not only a latency choice. It is the only thing that puts a
  write between two units of work, and a write is the only place a dead peer
  becomes an exception. A buffered handler runs the whole job for a client that
  left in the first 8% of it, and bills for all of it.

  The third row is the one that gets built by accident: a buffer in front of
  the handler -- a reverse proxy, a gzip encoder, a framework's response
  buffering -- multiplies the cancellation granularity by its own flush size.
  The handler is written correctly and the cancellation still does not arrive.
""")

# --------------------------------------------------------------------------- #
s.rule("4. What streaming costs")
# --------------------------------------------------------------------------- #


def ttfb(base: str, path: str) -> tuple[float, float]:
    """(first body byte, last byte) in seconds, measured on a raw socket."""
    sock = s.raw_socket(base)
    t0 = time.perf_counter()
    sock.sendall(f"GET {path} HTTP/1.1\r\nHost: x\r\nConnection: close\r\n\r\n"
                 .encode())
    buf, first, in_body = b"", None, False
    while True:
        data = sock.recv(65536)
        if not data:
            break
        buf += data
        if not in_body and b"\r\n\r\n" in buf:
            in_body = True
            if buf.partition(b"\r\n\r\n")[2]:
                first = time.perf_counter() - t0
        elif in_body and first is None:
            first = time.perf_counter() - t0
    last = time.perf_counter() - t0
    sock.close()
    return (first if first is not None else last), last


s.row("framing", "first byte of body", "complete", widths=[30, 22, 12])
with s.serve(Streamer, units=8, work=0.05, flush_every=1) as base:
    f, l = ttfb(base, "/work")
    s.row("chunked, streamed", f"{f * 1000:7.0f} ms", f"{l:.2f} s",
          widths=[30, 22, 12])
with s.serve(Streamer, units=8, work=0.05) as base:
    f, l = ttfb(base, "/buffered")
    s.row("Content-Length, buffered", f"{f * 1000:7.0f} ms", f"{l:.2f} s",
          widths=[30, 22, 12])
print("""
  Same total work, first byte moved to the front. The bill for it is three
  things, and only the first is usually counted:

    - the status code, spent at byte zero (section 1)
    - Content-Length, which is what a client, a proxy and a progress bar use
    - retryability. A request that failed after 3 of 8 records cannot be
      repeated without either duplicating three or designing a resume token,
      and a resume token is a protocol, not a header.
""")

# --------------------------------------------------------------------------- #
s.rule("5. Which of these may a client repeat?")
# --------------------------------------------------------------------------- #
print("""  request / response       repeatable?   why
  GET, HEAD                yes           no server state depends on it
  PUT /documents/N01       yes           same body, same final state
  DELETE /documents/N01    yes*          *the 404 on the second call is the
                                          success case, and a client that
                                          treats it as an error retries forever
  POST /extractions        NO            which is idempotency_lab.py entire
  408, 429, 502, 503, 504  yes           the server said so
  400, 401, 403, 422       no            the same bad request will fail again
  timeout / RST            UNKNOWN       and this is the only interesting row

  The last row is this fixture's centre of gravity. A client timeout is not a
  server failure; it is an absence of evidence. The write may have been fully
  applied, applied with the response lost on the way back, or never seen at
  all. No status code distinguishes them because there is no status code. The
  only thing that can is a key the client generated before it sent.
""")

# --------------------------------------------------------------------------- #
s.rule("6. Predictions, scored")
# --------------------------------------------------------------------------- #
print("""  P1  mid-stream failure is visible to the client
      WRONG. 200, three valid records, clean end of stream, no exception. A
      short success and a failure are byte-identical.

  P2  the server notices on its next write
      WRONG by four orders of magnitude of bytes. The send buffer absorbs the
      disconnect; a handler that is not writing never notices at all.

  P3  a streaming handler stops within a chunk of the disconnect
      HALF RIGHT, and it is not the handler's property. Any buffer between the
      handler and the socket -- proxy, encoder, framework -- sets the
      granularity, and a buffered response has none.

  P4  streaming trades total time for first-byte time
      RIGHT but incomplete: it also spends the status code, Content-Length,
      and the ability to retry the request as a unit.
""")
