"""Eval 1: score every retrieval variant on the questions with gold sections. Writes eval/results_retrieval.csv."""

import csv
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.retrieval.corpus import ROOT
from src.retrieval.hybrid import build_retrievers
from src.retrieval.metrics import ndcg_at_k, precision_at_k, recall_at_k, reciprocal_rank
from src.retrieval.rerank import CANDIDATES

QUESTIONS = ROOT / "eval" / "questions.jsonl"
RESULTS = ROOT / "eval" / "results_retrieval.csv"
METRICS = ["recall@1", "recall@3", "recall@5", "precision@5", "mrr", "ndcg@5"]


def score(ranked, relevant):
    return {
        "recall@1": recall_at_k(ranked, relevant, 1),
        "recall@3": recall_at_k(ranked, relevant, 3),
        "recall@5": recall_at_k(ranked, relevant, 5),
        "precision@5": precision_at_k(ranked, relevant, 5),
        "mrr": reciprocal_rank(ranked, relevant),
        "ndcg@5": ndcg_at_k(ranked, relevant, 5),
    }


def row(variant, group, scores, seconds=None):
    means = {m: round(sum(s[m] for s in scores) / len(scores), 3) for m in METRICS}
    return {"variant": variant, "group": group, "questions": len(scores), **means, "seconds_per_query": seconds}


def main():
    with open(QUESTIONS, encoding="utf-8") as f:
        questions = [q for q in map(json.loads, f) if q["gold_sections"]]

    rows = []
    for variant, retriever in build_retrievers().items():
        started = time.perf_counter()
        scores, misses = [], []
        for q in questions:
            relevant = {(g["law"], g["section"]) for g in q["gold_sections"]}
            # the same depth for every variant, so MRR compares like with like
            ranked = [(h.chunk["law"], h.chunk["section"]) for h in retriever.search(q["question"], k=CANDIDATES)]
            scores.append(score(ranked, relevant))
            if not relevant & set(ranked[:5]):
                misses.append(q["id"])
        seconds = round((time.perf_counter() - started) / len(questions), 2)
        rows.append(row(variant, "all", scores, seconds))
        for kind in dict.fromkeys(q["type"] for q in questions):
            rows.append(row(variant, kind, [s for s, q in zip(scores, questions) if q["type"] == kind]))
        print(rows[-1 - len(set(q["type"] for q in questions))])
        print(f"  no gold section in the top 5 ({len(misses)}): {' '.join(misses)}")

    with open(RESULTS, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    print(f"Wrote {RESULTS.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
