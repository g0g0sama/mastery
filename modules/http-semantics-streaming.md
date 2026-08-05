# HTTP semantics and streaming responses

**Micro module.** One mechanism, one experiment, three cards. Runs against
[service-lab/](service-lab/).

**Capability:** HTTP semantics and streaming responses (Layer 1b, Working ->
Independent). Map evidence: "Stream a model response with correct cancellation
on client disconnect."

---

## The problem

That evidence line contains two assumptions and both are false. It assumes a
streamed response can still report a failure, and it assumes the server finds
out when the client disconnects. What a real socket does instead decides how a
streaming endpoint has to be written.

## The mechanism

**A 200 is a promise made before the work is done.** Eight records streamed as
ndjson; the upstream fails after three:

```text
client framing            status   records   client saw a failure?
bare ndjson               200      3         no -- looks like 3 results
ndjson + done sentinel    200      3         YES
control, no failure       200      8+1       sentinel present = True
```

The status line is written before the first record is produced, so nothing
after it can lower the status. This is worse than a truncated body, because the
body is not truncated -- it is complete and short. Three well-formed objects, a
clean end of stream, no exception at any layer. A partial failure and a query
that genuinely matched three documents are byte-identical.

After that commitment point the only available signal is one the client agrees
in advance to check: a terminal event, or an HTTP trailer, plus a client that
treats its absence as an error. Neither exists by default, and the sentinel is
worth nothing if the client does not check for it. Same shape as
[eval-set-versioning.md](eval-set-versioning.md) -- the stamp only helps if the
comparison refuses without it.

**The server does not find out when the client leaves.** Client sends the
request, waits 150 ms, goes; server writes 64-byte chunks at full speed:

```text
how the client left       server got                bytes written   writes
FIN (graceful close)      ConnectionResetError      149,504         2,336
RST (killed)              ConnectionResetError      149,504         2,336
```

2,336 successful writes after the peer was gone. The write lands in the
kernel's send buffer and returns; the peer's receive buffer absorbs more; only
when both fill does the next write block, and only once the RST has been
received and processed does it raise. On loopback, with no RTT and no proxy in
between -- the most favourable case that exists.

The two rows agreeing is the second half of it. A graceful close is graceful
only for a peer that has finished; a client that closes mid-response has an OS
that RSTs the next byte to arrive, so **a deliberate cancellation and a crashed
client are indistinguishable to the server**. There is no "client cancelled"
signal to log, alert on, or bill differently.

**What cancellation is worth, and who takes it away.** Twenty units of 40 ms
provider work; the client leaves after 150 ms, by which point about 4 units are
legitimately owed:

```text
response shape                    units done   wasted work    cancelled?
buffered (Content-Length)         20/20        0.64 s         no
streamed, flush every unit         4/20        0.00 s         yes
streamed, flush every 8 units      8/20        0.16 s         yes
```

Streaming is not only a latency choice. It is the only thing that puts a write
between two units of work, and a write is the only place a dead peer becomes an
exception. The buffered handler ran the entire job -- and billed the entire
provider cost -- for a client that left in the first 8% of it.

The third row is the one that gets built by accident. Any buffer between the
handler and the socket -- a reverse proxy, a gzip encoder, a framework's
response buffering -- multiplies cancellation granularity by its own flush
size. The handler is written correctly and the cancellation still does not
arrive.

**What streaming costs**, same total work:

```text
framing                       first byte of body    complete
chunked, streamed                  51 ms            0.40 s
Content-Length, buffered          404 ms            0.40 s
```

Three things are spent for that 8x, and only the first is usually counted: the
status code (spent at byte zero), `Content-Length` (which is what a client, a
proxy and a progress bar use), and retryability -- a request that failed after
3 of 8 records cannot be repeated without either duplicating three or designing
a resume token, and a resume token is a protocol, not a header.

**Which of these may a client repeat?**

```text
request / response       repeatable?   why
GET, HEAD                yes           no server state depends on it
PUT /documents/N01       yes           same body, same final state
DELETE /documents/N01    yes*          *the 404 on the second call is the
                                        success case; a client that treats it
                                        as an error retries forever
POST /extractions        NO            see idempotency-keys.md
408, 429, 502, 503, 504  yes           the server said so
400, 401, 403, 422       no            the same bad request will fail again
timeout / RST            UNKNOWN       the only interesting row
```

A client timeout is not a server failure; it is an absence of evidence. The
write may have been fully applied, applied with the response lost on the way
back, or never seen. No status code distinguishes them because there is no
status code. Only a key the client generated before sending can.

## The experiment

```powershell
cd modules\service-lab
python http_lab.py     # ~12 s, binds an ephemeral port on 127.0.0.1
```

Four predictions are written at the top of the file and scored in section 6.
Three of the four were wrong.

## Boundary

- **Loopback flatters every number here.** No RTT, no loss, no proxy, no load
  balancer, no TLS record layer. 149,504 bytes is this machine's buffer pair;
  the count on a real network with a proxy in front is different and larger.
  The direction -- discovery is late and buffer-sized, never immediate -- is
  the transferable part.
- **`http.server` is not a production server.** A real one (uvicorn, hypercorn,
  gunicorn) surfaces disconnects through its own API and may poll the socket
  for readability, which detects a FIN earlier than a failed write does. What
  it cannot fix is the buffered-response case: no signal exists where no write
  happens.
- **HTTP/2 and HTTP/3 do have an explicit cancel** (`RST_STREAM`,
  `STOP_SENDING`), which is a genuinely different situation from HTTP/1.1 and
  worth checking before assuming section 2 applies to your stack.
- **The 40 ms "unit" is a sleep**, not a provider call. What it stands for --
  work that costs money and cannot be un-spent -- is the point; the seconds are
  fixture-specific.

## Cards

### 1. [failure] A streaming JSON endpoint returns 200 and three valid records. The upstream failed after the third. What does the client see?

**Answer:** Nothing wrong. Status 200, three well-formed objects, a clean end
of stream, no exception. A partial failure is byte-identical to a query that
genuinely matched three documents.

**Why:** The status line is written before the first record is produced, so no
later failure can change it. There is no in-band error channel after the
commitment point.

**Boundary:** The fix is a terminal sentinel event or an HTTP trailer, *and* a
client that treats its absence as an error -- the sentinel alone buys nothing.
A resume token is a separate design problem: a retry after 3 of 8 either
duplicates three records or needs a protocol you have to invent.

**Tags:** `http` `streaming` `failure` `general-principle`

---

### 2. [misconception] The client disconnected, so the request handler stops.

**Answer:** It does not. In the lab the server completed 2,336 further writes
and 149,504 bytes after the peer was gone, on loopback with no proxy. The
disconnect surfaces when the send buffer fills and the RST has been processed,
not when the client leaves -- and a handler that is not writing at all never
finds out.

**Why:** A socket write lands in the kernel's send buffer and returns. Discovery
is bounded by buffer space divided by write size, which is a property of the
network stack, not of the request.

**Boundary:** Graceful FIN and killed-with-RST produce the identical error, so
a deliberate cancellation cannot be distinguished from a crashed client. If you
need that distinction, it has to be an application-level message. HTTP/2 and /3
do carry an explicit cancel and are a different case.

**Tags:** `http` `cancellation` `misconception` `general-principle`

---

### 3. [decision] A 20-step job behind an HTTP endpoint: buffer the response or stream it?

**Answer:** Stream it if the steps cost money, even when nobody needs early
output. In the lab a buffered handler ran all 20 units for a client that left
after 4, wasting 0.64 s of provider work; streaming per unit stopped at 4.

**Why:** A write is the only place a dead peer becomes an exception, so
streaming is what creates the cancellation signal in the first place. Buffering
removes it entirely.

**Boundary:** Streaming spends the status code, `Content-Length` and
retryability, and any buffer in front of the handler -- reverse proxy, gzip
encoder, framework response buffering -- sets the real granularity: flushing
every 8 units cancelled at 8, not at 4. Check what is between your handler and
the socket before claiming the endpoint is cancellable.

**Tags:** `http` `streaming` `decision` `general-principle`
