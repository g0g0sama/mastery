# AuthN and AuthZ

**Micro module.** One mechanism, one experiment, three cards. Runs against
[service-lab/](service-lab/).

**Capability:** AuthN / AuthZ (Layer 1b, Aware -> Independent). Map evidence:
"Authorization enforced outside the model, tested with a denied case." The
Layer 10 row it shares a border with asks for the same property from the other
side: "deterministic checks, provable without reading a prompt."

---

## The problem

Authentication is a solved, single, testable thing: one signature check, one
expiry check, done once at the edge. Authorization is none of those. It is a
decision about an *object*, made once per endpoint, by whoever wrote that
endpoint, and it is only ever tested from the side that is allowed to pass.

## The mechanism

Two tenants: `acme` owns six documents, `globex` two. Every request below
carries a **valid** acme token and asks for a globex document. Authentication
succeeds every time.

```text
request (valid acme token)          status  result
GET /documents/N07                  403     denied
GET /documents?ids=N01,N07          200     LEAKS
GET /search?q=                      200     LEAKS   (total: 8)
GET /export                         200     LEAKS
GET /events/8                       200     LEAKS
POST /extractions {doc_id: N07}     201     LEAKS
```

Five of six. Each fails differently: the batch endpoint checks the first id and
trusts the rest; search filters the rows but not the count; the export endpoint
was written for an internal dashboard and never had a check; the derived event
was never joined to its source's owner; and the write path reads a document id
straight out of the request body.

That is the property being measured. The check is not a rule the system
enforces -- it is a line of code repeated six times, so **coverage is per
endpoint and the newest endpoint has the least**.

The last row is the expensive one, and it is the one that belongs to this
project specifically. It does not read another tenant's data, it **copies** it:
an event row extracted from globex's document, stamped with acme's tenant,
indistinguishable from acme's own data forever afterwards. A read leak is an
incident; a write leak is a provenance problem that outlives the fix, and
[provenance-and-lineage.md](provenance-and-lineage.md) is what you would need
to unpick it.

**Post-filtering leaks three things that are not rows.**

```text
filter placement          total shown   items returned
after the query           8             3
inside the query          6             3
```

The count is the leak everyone forgets and it needs no row: a competitor
learning the exact size of your corpus, or an agent learning that a record
exists for someone they may not read. Pagination is the second -- a filtered
page of a shared result set is short, and *how* short is a per-page oracle for
the number of hidden rows. The third is the status pair: `N07` -> 403, a
nonexistent id -> 404, which is an existence oracle. Returning 404 for both
costs nothing technically; what it costs is that your own users get 404 for
documents they merely lack permission on. Pick one and write down which.

**The denied case is the only test that measures anything.**

```text
suite                         endpoints covered   passing   leaks it catches
happy path, per endpoint      6 / 6               6/6       0 of 5
denied case, per endpoint     6 / 6               1/6       5 of 5
```

100% endpoint coverage, 100% pass rate, zero leaks detected. "Tested" is a
property of the endpoint; "authorized" is a property of the pair (endpoint,
principal), and only the second axis carries the bug. The cheap fix is a
table-driven test over `endpoint x principal x object owner` -- 6 x 2 x 2 here
-- because that grid already has a row for the endpoint someone adds next
month.

**Authentication, separately.** Four tokens, two verifiers:

```text
token                             signature verified    signature decoded only
valid acme token                  acme ok               acme ok
expired acme token                401                   401
signed with another key           401                   globex ok
claims edited, signature kept     401                   globex ok
```

The last row is not an exotic attack. The claims are a base64 blob the client
sent, so "decode the token and read `tenant` from it" is a complete
authentication bypass that passes every happy-path test, passes the expiry
test, and looks correct in review. The signature check is the single line that
turns a claim into a fact.

Note also what a correct token cannot do: it carries a tenant, not a permission
to read document N07. Every leak in the first table happened *after* the who
question was answered correctly.

**Where the check belongs.**

```text
placement                    leaks (of 6)
inline in each handler       5
in the query                 0
in a route middleware        -- authorizes nothing
```

A middleware that authorizes the route (`/documents/*` requires a tenant token)
authorizes nothing here, because every leak was an authenticated caller on an
allowed route asking for the wrong object. Object-level authorization needs the
object, which means it happens where the object is fetched -- which is why the
fixed column is a `WHERE tenant=?` and not a decorator. Two properties fall out
of that placement and they are the whole argument for it: it is provable by
reading the query rather than by reasoning about control flow, and it cannot be
bypassed by a path that forgot to call the checker, because there is no checker
to forget. Same argument as
[untrusted-content-isolation.md](untrusted-content-isolation.md) makes on the
tool side.

## The experiment

```powershell
cd modules\service-lab
python auth_lab.py     # ~3 s
```

## Boundary

- **`WHERE tenant=?` is the right shape and the wrong mechanism at scale.** Two
  tenants and one predicate hide the real problem: rules that are hierarchical,
  delegated, or role-based do not compress into a single column, and hand-written
  predicates drift apart exactly the way the six handlers did. Row-level security
  in the database, or a policy engine that generates the predicate, is where this
  goes next; the transferable claim is only that the filter must reach the query.
- **The lab has no cross-tenant caching.** A cache key that omits the principal
  reproduces every leak in section 1 with all the checks correct -- measured
  separately in [caching.md](caching.md).
- **HMAC-in-a-blob is not JWT.** Real tokens bring algorithm confusion, key
  rotation, `kid` handling and clock skew, none of which are here. The one thing
  that transfers is that decoding is not verifying.
- **Nothing here covers authentication of the service to the provider**, key
  custody, or how a denied request is logged and alerted on. See
  [config-and-secrets.md](config-and-secrets.md) for the first.

## Cards

### 1. [failure] A tenant-scoped API passes every authorization test and a customer reports seeing another customer's data. Where do you look first?

**Answer:** The endpoints nobody wrote a denied-case test for -- batch/list
endpoints, exports, and any object *derived* from a protected one. In the lab
five of six endpoints leaked with a valid token: the batch endpoint checked
only the first id, search filtered rows but not the count, export had no check,
and the extraction endpoint read a document id straight from the request body.

**Why:** Authorization is a per-endpoint line of code, not a system-wide rule,
so its coverage is per endpoint and the newest endpoint has the least.

**Boundary:** The derived-object leak is the one that persists: an extraction
run against another tenant's document is stored stamped with the *caller's*
tenant, so fixing the endpoint does not unpick the rows it already wrote.

**Tags:** `authz` `failure` `general-principle`

---

### 2. [misconception] The handler filters the results by tenant before returning them, so nothing leaks.

**Answer:** Rows are not the only thing that leaks. Post-filtering still
exposed the unfiltered `total` (8 instead of 6), returned short pages whose
shortness counts the hidden rows, and distinguished 403 (exists, not yours)
from 404 (does not exist) -- an existence oracle needing no row at all.

**Why:** The database answered the unrestricted question; everything derived
from that answer before the filter -- counts, page boundaries, timings, status
codes -- carries information about rows the caller may not see.

**Boundary:** Putting the predicate in the query fixes all three at once and is
provable by reading the query. It does not scale to hierarchical or delegated
rules -- that is where row-level security or a policy engine starts.

**Tags:** `authz` `misconception` `general-principle`

---

### 3. [mechanism] What is the difference between decoding a bearer token and verifying it, and what does skipping the difference cost?

**Answer:** Decoding reads claims the client sent; verifying proves the server
issued them. In the lab a decode-only verifier accepted a token signed with the
wrong key and a token whose `tenant` claim had been edited to `globex` -- full
authentication bypass -- while correctly rejecting the expired one.

**Why:** The claims are a base64 blob under the client's control. Only the HMAC
(compared in constant time) binds them to the server's key.

**Boundary:** It passes every happy-path and expiry test and looks correct in
review, so tests do not catch it -- a forged-token case has to be written
deliberately. And verification only settles *who*: object-level authorization
is a separate decision the token cannot make.

**Tags:** `authn` `mechanism` `general-principle`
