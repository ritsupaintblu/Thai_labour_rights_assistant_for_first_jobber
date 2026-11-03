"""Choose MIN_SCORE: how many out-of-scope questions each floor refuses, and how many others it wrongly refuses."""

import csv
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from src.retrieval.corpus import ROOT
from src.retrieval.hybrid import SEARCH_VARIANT, build_retrievers

RESULTS = ROOT / "eval" / "results_min_score.csv"


def main():
    retriever = build_retrievers()[SEARCH_VARIANT]
    with open(ROOT / "eval" / "questions.jsonl", encoding="utf-8") as f:
        questions = list(map(json.loads, f))
    top = [(retriever.search(q["question"], k=1)[0].score, bool(q["gold_sections"])) for q in questions]
    answerable = sum(a for _, a in top)
    rows = []
    for floor in [i / 100 for i in range(0, 100, 1)]:
        refused = sum(s < floor and not a for s, a in top)
        wrongly = sum(s < floor and a for s, a in top)
        rows.append({"min_score": floor, "out_of_scope_refused": refused, "out_of_scope": len(top) - answerable,
                     "answerable_refused": wrongly, "answerable": answerable,
                     "balanced_accuracy": round((refused / (len(top) - answerable) + 1 - wrongly / answerable) / 2, 3)})
    with open(RESULTS, "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0])
        writer.writeheader()
        writer.writerows(rows)
    best = max(rows, key=lambda r: r["balanced_accuracy"])
    for row in rows[::10] + [best]:
        print(row)
    print("best", best)


if __name__ == "__main__":
    main()
