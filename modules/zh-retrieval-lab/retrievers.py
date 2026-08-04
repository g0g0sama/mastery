"""An inverted index, a TF-IDF cosine retriever, and BM25 -- all over any analyzer."""
import math
from collections import Counter, defaultdict

from analyzers import ANALYZERS
from corpus import DOCS


class Index:
    def __init__(self, analyzer="bigram", docs=None):
        self.analyze = ANALYZERS[analyzer]
        self.docs = docs or DOCS
        self.terms = {d: Counter(self.analyze(t)) for d, t in self.docs.items()}
        self.length = {d: sum(c.values()) for d, c in self.terms.items()}
        self.avgdl = sum(self.length.values()) / len(self.length)
        self.postings = defaultdict(set)          # the inverted index itself
        for doc, counts in self.terms.items():
            for term in counts:
                self.postings[term].add(doc)
        self.N = len(self.docs)

    def df(self, term):
        return len(self.postings.get(term, ()))

    def candidates(self, query_terms):
        """The point of an inverted index: score only documents that can match."""
        out = set()
        for term in query_terms:
            out |= self.postings.get(term, set())
        return out

    def tfidf_cosine(self, query):
        q_terms = Counter(self.analyze(query))
        q_vec = {t: c * math.log(self.N / self.df(t)) for t, c in q_terms.items()
                 if self.df(t)}
        q_norm = math.sqrt(sum(v * v for v in q_vec.values())) or 1.0
        scores = {}
        for doc in self.candidates(q_vec):
            d_vec = {t: c * math.log(self.N / self.df(t))
                     for t, c in self.terms[doc].items() if self.df(t)}
            d_norm = math.sqrt(sum(v * v for v in d_vec.values())) or 1.0
            dot = sum(v * d_vec.get(t, 0.0) for t, v in q_vec.items())
            scores[doc] = dot / (q_norm * d_norm)
        return scores

    def bm25(self, query, k1=1.2, b=0.75):
        q_terms = self.analyze(query)
        scores = defaultdict(float)
        for term in q_terms:
            df = self.df(term)
            if not df:
                continue
            idf = math.log(1 + (self.N - df + 0.5) / (df + 0.5))
            for doc in self.postings[term]:
                tf = self.terms[doc][term]
                denom = tf + k1 * (1 - b + b * self.length[doc] / self.avgdl)
                scores[doc] += idf * (tf * (k1 + 1)) / denom
        return dict(scores)


def rank(scores, k=None):
    ordered = sorted(scores.items(), key=lambda kv: (-kv[1], kv[0]))
    return [d for d, _ in ordered][:k] if k else [d for d, _ in ordered]
