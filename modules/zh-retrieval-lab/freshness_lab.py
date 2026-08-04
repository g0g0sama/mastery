"""Deletion, access control, and staleness -- the three ways a correct ranking
returns a wrong answer.

    python freshness_lab.py

Every other module in this lab asks whether the right documents came back. This
one asks whether documents that should not exist came back, which is a different
question with a different failure mode: nobody files a bug when retrieval is too
permissive.
"""
import sys
import time

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

from corpus import DOCS
from retrievers import Index, rank

# Access control and mutation state, kept beside the corpus rather than inside
# it -- which is already a design decision with consequences. See section 5.
T0 = 1_700_000_000
META = {d: {"acl": "public", "updated": T0, "deleted": False} for d in DOCS}
for d in ("D01", "D02", "D06", "D12"):
    META[d]["acl"] = "team-energy"
for d in ("D07", "D08"):
    META[d]["acl"] = "team-semis"


def visible(doc, principal):
    m = META[doc]
    return not m["deleted"] and (m["acl"] == "public" or m["acl"] in principal)


class Store:
    """One index and two entry points -- which is where the bug lives."""

    def __init__(self):
        # Unigram, so the candidate set is broad enough for filtering to be
        # visible. Which analyzer is used does not affect anything below.
        self.index = Index("unigram")
        self.built_at = T0
        self.snippets = {d: t[:12] for d, t in DOCS.items()}

    def search(self, query, principal, k=5, mode="post"):
        scores = self.index.bm25(query)
        if mode == "pre":
            scores = {d: s for d, s in scores.items() if visible(d, principal)}
            return rank(scores, k=k)
        ordered = rank(scores, k=k)                      # top-k first ...
        return [d for d in ordered if visible(d, principal)]   # ... then filter

    def similar_to(self, doc, k=3):
        """'More like this'. Written six months later, by someone else."""
        return [d for d in rank(self.index.bm25(DOCS[doc]), k=k + 1) if d != doc]

    def preview(self, doc):
        return self.snippets.get(doc)


store = Store()
ENERGY = {"team-energy"}
NOBODY = set()

print("=== 1. Post-filtering silently shortens the page ===")
query = "中国工厂投资"
print(f"  query {query!r}, k=5")
for label, principal in (("full access", {"team-energy", "team-semis"}),
                         ("public only", NOBODY)):
    post = store.search(query, principal, k=5, mode="post")
    pre = store.search(query, principal, k=5, mode="pre")
    print(f"  {label:<14} post-filter -> {post}  ({len(post)} results)")
    print(f"  {'':<14} pre-filter  -> {pre}  ({len(pre)} results)")
print("  Same k, same ranking, different number of rows. Post-filtering asks for")
print("  five and then removes some, so a restricted user gets a short page and")
print("  no way to ask for the rest -- page 2 starts at rank 6 and the missing")
print("  rows are gone. The bug reads as 'search is worse for some users' and")
print("  gets triaged as relevance.")
print()

print("=== 2. Over-fetching is not a fix, it is a moving target ===")
needed = 5
for factor in (1, 2, 3, 4):
    got = store.search(query, NOBODY, k=needed * factor, mode="post")
    print(f"  over-fetch x{factor:<2} (k={needed * factor:>2}) -> {len(got)} "
          f"visible of {needed} wanted")
print("  The multiplier you need is a function of how much of the corpus the")
print("  principal can see, which changes per tenant, per query, and over time.")
print("  Pre-filtering answers the question once; over-fetching re-answers it")
print("  wrongly on every request. In a vector index this is the harder version")
print("  of the same problem -- see ../ann-indexes-hnsw.md: a filter applied")
print("  before the graph search changes which nodes are reachable.")
print()

print("=== 3. A count is a disclosure ===")
q = "长江存储武汉"
matching = [d for d in store.index.bm25(q)]
allowed = [d for d in matching if visible(d, NOBODY)]
print(f"  query {q!r}: {len(matching)} matching documents, "
      f"{len(allowed)} visible to an unprivileged principal.")
print(f"  the restricted matches are {sorted(set(matching) - set(allowed))}")
print(f"  Returning zero rows is correct. Returning '{len(matching)} results, "
      f"{len(allowed)} shown',")
print("  a total, a facet count, or a page-2 link confirms the existence of a")
print("  document matching a term this principal may not search. So does a")
print("  latency difference. The authorization boundary covers metadata about")
print("  results, not only results -- and none of the graders in")
print("  ../deterministic-graders.md would catch this, because every one of them")
print("  scores what came back rather than what leaked.")
print()

print("=== 4. Break it: delete a document and watch it come back ===")
victim = "D02"
META[victim]["deleted"] = True
print(f"  {victim} ({DOCS[victim]}) deleted.")
print("  Checking every path out of the store:")
paths = {
    "search() pre-filter": store.search("中国石油天然气", ENERGY, k=5, mode="pre"),
    "search() post-filter": store.search("中国石油天然气", ENERGY, k=5, mode="post"),
    "similar_to(D01)": store.similar_to("D01"),
    "preview(D02)": [store.preview(victim)],
}
for name, result in paths.items():
    leaked = victim in result or (name.startswith("preview") and result != [None])
    print(f"    {name:<22} {'LEAKS' if leaked else 'clean':<6} {result}")
print()
print("  search() is correct on both filter modes. similar_to() and preview()")
print("  never learned about deletion, because deletion was implemented where")
print("  the requirement was noticed -- in the search path -- rather than at the")
print("  boundary of the store. The distance between those two is measured in")
print("  months and one engineer.")
print()

print("=== 5. What 'provably unreachable' has to mean ===")


def unreachable(doc, principals):
    """Sweep every entry point, with every query, for every principal.

    This function is the deliverable. The fix it forces is the cheap part.
    """
    failures = []
    for principal in principals:
        for q in list(DOCS.values()) + ["中芯", "深圳", "稀土", "出口管制"]:
            if doc in store.search(q, principal, k=17, mode="pre"):
                failures.append(("search/pre", q))
            if doc in store.search(q, principal, k=17, mode="post"):
                failures.append(("search/post", q))
    for other in DOCS:
        if other != doc and doc in store.similar_to(other, k=17):
            failures.append(("similar_to", other))
    if store.preview(doc) is not None:
        failures.append(("preview", doc))
    return failures


fails = unreachable(victim, [NOBODY, ENERGY, {"team-semis"}])
print(f"  before the fix: {len(fails)} reachable paths, e.g. {fails[:3]}")


def hard_delete(doc):
    """Deletion at the boundary: every store that holds the id forgets it."""
    META[doc]["deleted"] = True
    store.snippets.pop(doc, None)
    store.index.docs.pop(doc, None)
    store.index.terms.pop(doc, None)
    store.index.length.pop(doc, None)
    for postings in store.index.postings.values():
        postings.discard(doc)


hard_delete(victim)
fails = unreachable(victim, [NOBODY, ENERGY, {"team-semis"}])
print(f"  after the fix:  {len(fails)} reachable paths")
print("  That assertion is the map's evidence line for this row, and it is worth")
print("  more than the fix: it fails again the next time someone adds a fourth")
print("  entry point. A deletion test that only calls search() proves nothing")
print("  about deletion -- it proves search() was the path you thought of.")
print()

print("=== 6. Freshness: the index is a claim about the past ===")
edited = "D11"
print(f"  {edited} before: {DOCS[edited]}")
DOCS[edited] = "隆基绿能与通威股份取消光伏减产计划"      # meaning reversed
META[edited]["updated"] = T0 + 3600
print(f"  {edited} after:  {DOCS[edited]}")
print(f"  index built at {store.built_at}, document updated at "
      f"{META[edited]['updated']}")
stale = rank(store.index.bm25("协调"), k=3)
print(f"  query '协调' (removed from the document) still returns: {stale}")
fresh = rank(store.index.bm25("取消"), k=3)
print(f"  query '取消' (added to the document) returns: {fresh or '(nothing)'}")
print()
print("  Both directions are wrong and only one of them is visible: a stale hit")
print("  looks like a relevance bug, a stale miss looks like nothing at all.")
print("  Neither is detectable from inside retrieval -- freshness is a property")
print("  of the pipeline, and the instrument is a watermark:")
changed = [d for d, m in META.items() if m["updated"] > store.built_at]
t = time.strftime("%H:%M:%S", time.gmtime(store.built_at))
print(f"    index watermark = {store.built_at} ({t} UTC)")
print(f"    documents updated after the watermark = {changed}")
print("  Reindex those, advance the watermark, and the invariant becomes")
print("  checkable rather than hoped for: max(updated) <= watermark for every")
print("  indexed document. Store the watermark next to the index, not in a job")
print("  scheduler, or a redeploy silently reindexes everything or nothing.")
