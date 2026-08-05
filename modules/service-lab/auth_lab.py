"""Six endpoints, one authorization rule, and how many places it has to be right.

    python auth_lab.py        # ~3 s, binds an ephemeral port on 127.0.0.1

Map evidence lines, one from each layer that owns half of this:

  Layer 1b   "authorization enforced outside the model, tested with a denied case"
  Layer 10   "deterministic checks, provable without reading a prompt"

Two tenants. `acme` owns six documents, `globex` two. Every request below
carries a *valid* token for acme and asks for something belonging to globex.
Authentication is never the failing part.
"""
from __future__ import annotations

import base64
import hmac
import json
import time

import service as s

SECRET = b"service-lab-signing-key"
FOREIGN = s.TENANTS["globex"][0]            # the document acme must not see
OWN = s.TENANTS["acme"][0]


# --------------------------------------------------------------------------- #
# Authentication: a signed bearer token. Real HMAC, real constant-time compare.
# --------------------------------------------------------------------------- #

def mint(tenant: str, ttl: float = 300.0, secret: bytes = SECRET) -> str:
    payload = json.dumps({"tenant": tenant, "exp": time.time() + ttl}).encode()
    body = base64.urlsafe_b64encode(payload).decode()
    sig = hmac.new(secret, body.encode(), "sha256").hexdigest()[:32]
    return f"{body}.{sig}"


def verify(token: str, *, check_sig: bool = True) -> dict | None:
    try:
        body, sig = token.split(".")
        claims = json.loads(base64.urlsafe_b64decode(body))
    except (ValueError, TypeError, json.JSONDecodeError):
        return None
    if check_sig:
        want = hmac.new(SECRET, body.encode(), "sha256").hexdigest()[:32]
        if not hmac.compare_digest(sig, want):
            return None
    if claims.get("exp", 0) < time.time():
        return None
    return claims


# --------------------------------------------------------------------------- #
class API(s.Handler):
    """Six endpoints written the way six endpoints get written: one at a time,
    by different people, with the authorization decision inlined in each."""

    conn = None
    check_sig = True
    fixed = False          # True = the version where the filter is in the query

    def principal(self):
        auth = self.headers.get("Authorization", "")
        return verify(auth.removeprefix("Bearer "), check_sig=self.check_sig)

    def do_GET(self):                                   # noqa: N802
        who = self.principal()
        if not who:
            return self.send_json(401, {"error": "unauthenticated"})
        route, _, query = self.path.partition("?")
        args = dict(p.split("=", 1) for p in query.split("&") if "=" in p)
        parts = route.strip("/").split("/")

        # 1. the endpoint everyone writes the denied-case test for
        if parts[0] == "documents" and len(parts) == 2:
            r = self.conn.execute(
                "SELECT doc_id, tenant, body FROM documents WHERE doc_id=?",
                (parts[1],)).fetchone()
            if not r:
                return self.send_json(404, {"error": "not found"})
            if r[1] != who["tenant"]:
                # 403 or 404? The choice is an information-disclosure decision,
                # measured in section 3.
                return self.send_json(403, {"error": "forbidden"})
            return self.send_json(200, {"doc_id": r[0], "body": r[2]})

        # 2. the batch variant, added later, checking the first id only
        if parts[0] == "documents" and args.get("ids"):
            ids = args["ids"].split(",")
            first = self.conn.execute(
                "SELECT tenant FROM documents WHERE doc_id=?", (ids[0],)).fetchone()
            if not first or first[0] != who["tenant"]:
                return self.send_json(403, {"error": "forbidden"})
            q = ("SELECT doc_id, tenant FROM documents WHERE doc_id IN (%s)"
                 % ",".join("?" * len(ids)))
            if self.fixed:
                q += " AND tenant=?"
                rows = self.conn.execute(q, (*ids, who["tenant"])).fetchall()
            else:
                rows = self.conn.execute(q, ids).fetchall()
            return self.send_json(200, [{"doc_id": a, "tenant": b} for a, b in rows])

        # 3. search: filtered in the handler, counted in the database
        if parts[0] == "search":
            rows = self.conn.execute(
                "SELECT doc_id, tenant FROM documents WHERE body LIKE ?"
                + (" AND tenant=?" if self.fixed else ""),
                (f"%{args.get('q', '')}%",) + ((who["tenant"],) if self.fixed else ()),
            ).fetchall()
            total = len(rows)
            visible = [r for r in rows if r[1] == who["tenant"]]
            page = visible[: int(args.get("limit", 3))]
            return self.send_json(200, {"total": total, "returned": len(page),
                                        "items": [r[0] for r in page]})

        # 4. the export endpoint, written for an internal dashboard
        if parts[0] == "export":
            q = "SELECT doc_id, tenant FROM documents"
            params = ()
            if self.fixed:
                q += " WHERE tenant=?"
                params = (who["tenant"],)
            rows = self.conn.execute(q, params).fetchall()
            return self.send_json(200, [{"doc_id": a, "tenant": b} for a, b in rows])

        # 5. the derived object: the source is protected, the extraction is not
        if parts[0] == "events" and len(parts) == 2:
            r = self.conn.execute(
                "SELECT event_id, doc_id, tenant, actors FROM events WHERE event_id=?"
                + (" AND tenant=?" if self.fixed else ""),
                (parts[1],) + ((who["tenant"],) if self.fixed else ())).fetchone()
            if not r:
                return self.send_json(404, {"error": "not found"})
            return self.send_json(200, {"event_id": r[0], "doc_id": r[1],
                                        "tenant": r[2], "actors": r[3]})

        return self.send_json(404, {})

    # 6. the write path: extract from a document id supplied by the client
    def do_POST(self):                                  # noqa: N802
        who = self.principal()
        if not who:
            return self.send_json(401, {"error": "unauthenticated"})
        body = self.read_json()
        doc = self.conn.execute(
            "SELECT doc_id, tenant, body FROM documents WHERE doc_id=?"
            + (" AND tenant=?" if self.fixed else ""),
            (body["doc_id"],) + ((who["tenant"],) if self.fixed else ())).fetchone()
        if not doc:
            return self.send_json(404, {"error": "not found"})
        record, status = s.extract(doc[0])
        if status != "ok":
            return self.send_json(502, {"error": status})
        # Note what gets stored: the row is stamped with the *caller's* tenant.
        cur = self.conn.execute(
            "INSERT INTO events (doc_id, tenant, event_type, event_date, actors,"
            " content_sha, request_id, created_at) VALUES (?,?,?,?,?,?,?,?)",
            (doc[0], who["tenant"], record["event_type"], record.get("date"),
             json.dumps(record["actors"], ensure_ascii=False),
             s.content_sha(record), None, time.time()))
        self.conn.commit()
        return self.send_json(201, {"event_id": cur.lastrowid,
                                    "doc_id": doc[0],
                                    "actors": record["actors"]})


def setup():
    conn = s.store()
    s.seed_documents(conn)
    # one event per document, so the derived-object endpoint has something
    for i, doc_id in enumerate(s.DOC_IDS, start=1):
        conn.execute(
            "INSERT INTO events (event_id, doc_id, tenant, event_type, actors,"
            " content_sha, created_at) VALUES (?,?,?,?,?,?,?)",
            (i, doc_id, s.OWNER[doc_id], s.GOLD[doc_id]["event_type"],
             json.dumps(s.GOLD[doc_id]["actors"], ensure_ascii=False),
             f"seed{i}", time.time()))
    conn.commit()
    return conn


print(f"Two tenants. acme owns {len(s.TENANTS['acme'])} documents, globex owns "
      f"{len(s.TENANTS['globex'])}.\nEvery request below carries a valid acme "
      f"token and asks for {FOREIGN}, which belongs to globex.\n")

TOKEN = mint("acme")
conn = setup()

# --------------------------------------------------------------------------- #
s.rule("1. Authentication passed. Now, six times, does authorization?")
# --------------------------------------------------------------------------- #


def probe(base, fixed_label):
    checks = [
        ("GET /documents/{foreign}", lambda: s.get(
            base, f"/documents/{FOREIGN}", headers={"Authorization": f"Bearer {TOKEN}"})),
        ("GET /documents?ids=own,foreign", lambda: s.get(
            base, f"/documents?ids={OWN},{FOREIGN}",
            headers={"Authorization": f"Bearer {TOKEN}"})),
        ("GET /search?q=", lambda: s.get(
            base, "/search?q=", headers={"Authorization": f"Bearer {TOKEN}"})),
        ("GET /export", lambda: s.get(
            base, "/export", headers={"Authorization": f"Bearer {TOKEN}"})),
        ("GET /events/8  (from foreign doc)", lambda: s.get(
            base, "/events/8", headers={"Authorization": f"Bearer {TOKEN}"})),
        ("POST /extractions {foreign}", lambda: s.post(
            base, "/extractions", {"doc_id": FOREIGN},
            headers={"Authorization": f"Bearer {TOKEN}"})),
    ]
    leaks = 0
    for label, call in checks:
        status, body = call()
        text = json.dumps(body, ensure_ascii=False)
        # A leak is any globex-owned identifier or count reaching an acme caller.
        leaked = (FOREIGN in text or '"globex"' in text
                  or ('"total": 8' in text and "search" in label))
        leaks += leaked
        s.row(label, status, "LEAKS" if leaked else "denied",
              text[:44] + ("..." if len(text) > 44 else ""),
              widths=[36, 8, 9, 48])
    print(f"\n  {fixed_label}: {leaks} of 6 endpoints leak another tenant's data.\n")
    return leaks


s.row("request (valid acme token)", "status", "result", "response",
      widths=[36, 8, 9, 48])
with s.serve(API, conn=conn, fixed=False) as base:
    before = probe(base, "authorization inlined per endpoint")

print("""  Every one of those endpoints has an authorization decision in it and five of
  them get it wrong, each in a different way: the batch endpoint checks the
  first id and trusts the rest, search filters the rows but not the count, the
  export endpoint was written against an internal dashboard and never had one,
  the derived object was never joined to its source's owner, and the write path
  reads a document id straight out of the request body. That is the actual
  property being measured: the check is not a rule the system enforces, it is a
  line of code repeated six times, so coverage is per endpoint and the newest
  endpoint has the least.

  The last row is the expensive one. It does not read another tenant's data, it
  *copies* it -- an event row extracted from globex's document, stamped with
  acme's tenant, indistinguishable from acme's own data forever afterwards. A
  read leak is an incident; a write leak is a data-provenance problem that
  outlives the fix.
""")

s.row("request (valid acme token)", "status", "result", "response",
      widths=[36, 8, 9, 48])
conn2 = setup()
with s.serve(API, conn=conn2, fixed=True) as base:
    after = probe(base, "the same rule pushed into every query")

# --------------------------------------------------------------------------- #
s.rule("2. Post-filtering leaks three things that are not rows")
# --------------------------------------------------------------------------- #
print("`/search` filters in the handler after the database has answered.\n")
with s.serve(API, conn=conn, fixed=False) as base:
    _, loose = s.get(base, "/search?q=&limit=3",
                     headers={"Authorization": f"Bearer {TOKEN}"})
with s.serve(API, conn=conn2, fixed=True) as base:
    _, tight = s.get(base, "/search?q=&limit=3",
                     headers={"Authorization": f"Bearer {TOKEN}"})
s.row("filter placement", "total shown", "items returned", "page is full?",
      widths=[26, 14, 17, 15])
s.row("after the query", loose["total"], loose["returned"],
      "yes" if loose["returned"] == 3 else "no", widths=[26, 14, 17, 15])
s.row("inside the query", tight["total"], tight["returned"],
      "yes" if tight["returned"] == 3 else "no", widths=[26, 14, 17, 15])
print("""
  The count is the leak everyone forgets, and it is a real one: a competitor
  learning the exact size of your corpus, or a support agent learning that a
  record exists for a patient they may not read, needs no row to do it.
  Pagination is the second: a filtered page of a shared result set is short,
  and "how short" is a per-page oracle for how many hidden rows there were.
""")

with s.serve(API, conn=conn, fixed=False) as base:
    exists, _ = s.get(base, f"/documents/{FOREIGN}",
                      headers={"Authorization": f"Bearer {TOKEN}"})
    missing, _ = s.get(base, "/documents/N99",
                       headers={"Authorization": f"Bearer {TOKEN}"})
print(f"""  And the third: {FOREIGN} -> {exists}, a document id that does not exist ->
  {missing}. The pair is an existence oracle. Returning 404 for both costs
  nothing and answers nothing; the cost is that your own users get 404 for
  documents they merely lack permission on, which is a support burden traded
  for an enumeration defence. State which one you chose and why.
""")

# --------------------------------------------------------------------------- #
s.rule("3. The denied case is the only test that measures anything")
# --------------------------------------------------------------------------- #
print("A suite that exercises every endpoint with its *own* tenant's data:\n")
own_pass = 0
with s.serve(API, conn=conn, fixed=False) as base:
    for path in (f"/documents/{OWN}", f"/documents?ids={OWN}", "/search?q=",
                 "/export", "/events/1"):
        status, _ = s.get(base, path, headers={"Authorization": f"Bearer {TOKEN}"})
        own_pass += status == 200
    status, _ = s.post(base, "/extractions", {"doc_id": OWN},
                       headers={"Authorization": f"Bearer {TOKEN}"})
    own_pass += status == 201
s.row("suite", "endpoints covered", "passing", "leaks it would catch",
      widths=[30, 20, 10, 24])
s.row("happy path, per endpoint", "6 / 6", f"{own_pass}/6", f"0 of {before}",
      widths=[30, 20, 10, 24])
s.row("denied case, per endpoint", "6 / 6", f"{6 - before}/6", f"{before} of {before}",
      widths=[30, 20, 10, 24])
print("""
  100% endpoint coverage, 100% pass rate, and it detects none of the leaks.
  "Tested" is a property of the endpoint; "authorized" is a property of the
  pair (endpoint, principal), and only the second axis has the bug on it. The
  cheap version of the fix is a table-driven test over
  (endpoint x principal x object owner) -- 6 x 2 x 2 here -- because that grid
  has an entry for the endpoint someone adds next month.
""")

# --------------------------------------------------------------------------- #
s.rule("4. Authentication, separately, and the failure that is not a bug")
# --------------------------------------------------------------------------- #
forged = mint("globex", secret=b"not-the-signing-key")
swapped = base64.urlsafe_b64encode(
    json.dumps({"tenant": "globex", "exp": time.time() + 300}).encode()
).decode() + "." + mint("acme").split(".")[1]
cases = [("valid acme token", TOKEN),
         ("expired acme token", mint("acme", ttl=-1)),
         ("signed with another key", forged),
         ("claims edited, signature kept", swapped)]
s.row("token", "signature verified", "signature decoded only",
      widths=[34, 22, 24])
for label, tok in cases:
    strict = verify(tok, check_sig=True)
    loose_ = verify(tok, check_sig=False)
    s.row(label,
          f"{strict['tenant']} ok" if strict else "401",
          f"{loose_['tenant']} ok" if loose_ else "401",
          widths=[34, 22, 24])
print("""
  The last row is the one that matters and it is not an exotic attack: the
  claims are a base64 blob the client sent, so "decode the token and read
  `tenant` from it" is a complete authentication bypass that passes every happy
  path test, every expiry test, and looks correct in review. The signature check
  is the only line that turns a claim into a fact.

  Note also what the token cannot do. It carries a tenant, not a permission to
  read document N08. Authentication answers who; every leak in section 1
  happened after that question was answered correctly.
""")

# --------------------------------------------------------------------------- #
s.rule("5. Where the check belongs")
# --------------------------------------------------------------------------- #
print(f"""  placement                        leaks (of 6)   why
  inline in each handler           {before}              six chances to differ,
                                                  and the newest one is worst
  in the query                     {after}              the database cannot
                                                  return what it cannot select
  in a route middleware            -- see below

  A middleware that authorizes the *route* (`/documents/*` needs a tenant
  token) authorizes nothing, because every leak above was an authenticated
  caller on an allowed route asking for the wrong object. Object-level
  authorization needs the object, which means it happens where the object is
  fetched -- which is why the fixed column above is a `WHERE tenant=?` and not
  a decorator.

  Two properties that fall out of putting it in the query and are worth naming
  because they are the argument for it:

    - it is provable by reading the query, not by reasoning about control flow
    - it cannot be bypassed by a code path that forgot to call the checker,
      because there is no checker to forget -- see
      ../untrusted-content-isolation.md for the same argument on the tool side
""")
