"""search_law: the in-force sections for a query, or not_found when nothing clears the min_score floor."""

import csv
import re
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


@lru_cache(maxsize=1)
def section_full_texts():
    """Every in-force section's text as the chunks print it, by (law, section)."""
    texts = {}
    for chunk in load_chunks():
        key = (chunk["law"], chunk["section"])
        texts[key] = f"{texts[key]}\n{chunk['text']}" if key in texts else chunk["text"]
    return texts


def section_result(key):
    """A section as a search result, for one that code adds rather than the search finding it."""
    row = section_rows().get(key)
    return {**row, "text": section_full_texts()[key], "score": 0.0} if row else None


SECTION_REF = re.compile(r"มาตรา(\d+(?:/\d+)?)(ทวิ|ตรี|จัตวา|เบญจ)?(?![\d/])")


@lru_cache(maxsize=1)
def penalties():
    """(law, section) -> the sections of the same Act that set the penalty for breaking it. A penalty section names
    the duty only by number, such as "ฝ่าฝืนมาตรา 8", so a search for the duty's words never finds it."""
    links = {}
    for (law, section), text in section_texts().items():
        if "ต้องระวางโทษ" not in text:
            continue
        # the offence comes before each "ต้องระวางโทษ"; sections named after the last one are exceptions, such as
        # "เว้นแต่เป็นคนต่างด้าวตามมาตรา 63", unless the duties are listed after it, as in "บทบัญญัติดังต่อไปนี้"
        *offences, rest = text.split("ต้องระวางโทษ")
        described = "".join(offences) + (rest if "ดังต่อไปนี้" in offences[-1] else "")
        for number, suffix in SECTION_REF.findall(described):
            duty = f"{number} {suffix}" if suffix else number
            if duty != section and (law, section) not in links.get((law, duty), []):
                links.setdefault((law, duty), []).append((law, section))
    return links


def repealed_by(act, year):
    """The sections that repeal the Act named, such as มาตรา 3 "ให้ยกเลิก (1) พระราชบัญญัติ...พ.ศ. 2551"."""
    target = f"{''.join(act.split())}พ.ศ.{year}"
    return [key for key, text in section_texts().items() if "ให้ยกเลิก" in text and target in text]


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
