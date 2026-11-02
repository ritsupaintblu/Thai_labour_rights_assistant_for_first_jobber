"""BM25 over the chunks, with a choice of tokenizer.

tokenize_raw is the baseline. Thai has no spaces between words, so it treats whole phrases as tokens.
tokenize_thai segments words with PyThaiNLP.
"""

import re

from pythainlp.tokenize import word_tokenize
from rank_bm25 import BM25Okapi

from src.retrieval.corpus import Hit

THAI = "฀-๿"
# a PDF line break can fall inside a Thai word, and the segmenter still finds words without it
THAI_LINE_BREAK = re.compile(rf"(?<=[{THAI}])\s*\n\s*(?=[{THAI}])")


def tokenize_raw(text):
    return text.split()


def tokenize_thai(text):
    words = word_tokenize(THAI_LINE_BREAK.sub("", text).lower(), engine="newmm", keep_whitespace=False)
    return [w for w in words if any(ch.isalnum() for ch in w)]


class BM25Retriever:
    def __init__(self, chunks, tokenizer):
        self.chunks = chunks
        self.tokenizer = tokenizer
        self.index = BM25Okapi([tokenizer(c["text"]) for c in chunks])

    def search(self, query, k=5):
        """The best k chunks. A chunk sharing no term with the query is not a match, so it is left out."""
        scores = self.index.get_scores(self.tokenizer(query))
        ranked = sorted(range(len(self.chunks)), key=lambda i: scores[i], reverse=True)
        return [Hit(self.chunks[i], float(scores[i])) for i in ranked[:k] if scores[i] > 0]
