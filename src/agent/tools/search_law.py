"""search_law: the in-force sections for a query, or not_found when nothing clears the min_score floor."""

import csv
from functools import lru_cache

from src.retrieval.corpus import ROOT, load_chunks

AS_OF = "2026-11-01"
MIN_SCORE = 0.1  # plain RAG only: the agent checks the content, because a score cannot tell it there is an answer


def source_titles():
    with open(ROOT / "data" / "manifest.csv", encoding="utf-8-sig", newline="") as f:
        return {r["id"]: r["title"].strip() for r in csv.DictReader(f)}


def section_row(chunk, titles):
    return {"law": chunk["law"], "section": chunk["section"], "amendment_no": chunk["amendment_no"],
            "effective_date": chunk["effective_date"], "source": titles.get(chunk["source_id"], chunk["source_id"])}


@lru_cache(maxsize=1)
def section_rows():
    """Citation details for every in-force section, by (law, section)."""
    titles = source_titles()
    rows = {}
    for chunk in load_chunks():
        rows.setdefault((chunk["law"], chunk["section"]), section_row(chunk, titles))
    return rows


@lru_cache(maxsize=1)
def section_texts():
    """Every in-force section's text with whitespace removed, by (law, section): PDF line breaks split words."""
    texts = {}
    for chunk in load_chunks():
        key = (chunk["law"], chunk["section"])
        texts[key] = texts.get(key, "") + "".join(chunk["text"].split())
    return texts


class SearchLaw:
    def __init__(self, retriever, min_score=MIN_SCORE, titles=None):
        self.retriever = retriever
        self.min_score = min_score
        self.titles = source_titles() if titles is None else titles

    def __call__(self, query, k=5):
        return self.format(self.retriever.search(query, k=k))

    def format(self, hits):
        hits = [h for h in hits if h.score >= self.min_score]
        if not hits:
            return {"status": "not_found", "reason": "ไม่มีมาตราที่เกี่ยวข้องพอในกฎหมายที่มีอยู่"}
        return {"status": "found", "results": [
            {**section_row(h.chunk, self.titles), "text": h.chunk["text"], "score": round(h.score, 3)} for h in hits]}


def search_results(result):
    return result.get("results", [])
