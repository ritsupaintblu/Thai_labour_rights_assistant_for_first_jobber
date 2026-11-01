"""Check eval/questions.jsonl against the chunks, so a wrong label fails instead of skewing the evals.

Every labelled section must be in force and contain its quoted evidence, every formula must give
the expected number, and terms marked absent must not appear in any in-force chunk.
Exits with status 1 if any check fails.
"""

import csv
import json
import re
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
EXPECTED_TYPES = {"general": 24, "trap": 14, "calculation": 12, "out_of_scope": 10}


def squeeze(text):
    # chunks keep the PDF's line breaks, which can fall in the middle of a phrase
    return re.sub(r"\s+", "", text)


def check(question, sections, in_force_text, source_ids):
    errors = []
    labelled = "".join(sections.get((g["law"], g["section"]), "") for g in question["gold_sections"])
    for g in question["gold_sections"]:
        if (g["law"], g["section"]) not in sections:
            errors.append(f"no in-force chunk for {g['law']} s{g['section']}")
    for phrase in question.get("evidence", []):
        if squeeze(phrase) not in labelled:
            errors.append(f"evidence not in the labelled sections: {phrase}")
    for source in question.get("gold_sources", []):
        if source not in source_ids:
            errors.append(f"unknown source: {source}")
    if "formula" in question:
        # the formulas are written in this repo's own test set, not taken from input
        if abs(eval(question["formula"]) - question["expected_number"]) > 0.01:
            errors.append(f"{question['formula']} does not give {question['expected_number']}")
    if question["type"] == "out_of_scope":
        if question["gold_sections"] or not question.get("not_found"):
            errors.append("out-of-scope questions need not_found and no gold sections")
        for term in question.get("absent_terms", []):
            if squeeze(term) in in_force_text:
                errors.append(f"term is in the corpus, so this may not be out of scope: {term}")
    elif not question["gold_sections"]:
        errors.append("no gold sections")
    if question["type"] == "trap" and not question.get("wrong_answer"):
        errors.append("trap question without wrong_answer")
    return errors


def main():
    sys.stdout.reconfigure(encoding="utf-8")  # the Windows console default cannot print Thai
    with open(ROOT / "data" / "processed" / "chunks.jsonl", encoding="utf-8") as f:
        chunks = [c for c in map(json.loads, f) if c["status"] == "in_force"]
    sections = {}
    for c in chunks:
        key = (c["law"], c["section"])
        sections[key] = sections.get(key, "") + squeeze(c["text"])
    in_force_text = "".join(sections.values())
    with open(ROOT / "data" / "manifest.csv", encoding="utf-8-sig", newline="") as f:
        source_ids = {r["id"] for r in csv.DictReader(f)}
    with open(ROOT / "eval" / "questions.jsonl", encoding="utf-8") as f:
        questions = [json.loads(line) for line in f if line.strip()]

    failed = 0
    for question in questions:
        for error in check(question, sections, in_force_text, source_ids):
            print(f"{question['id']}: {error}")
            failed += 1
    counts = Counter(q["type"] for q in questions)
    if dict(counts) != EXPECTED_TYPES:
        print(f"question types {dict(counts)}, expected {EXPECTED_TYPES}")
        failed += 1
    duplicates = [i for i, n in Counter(q["id"] for q in questions).items() if n > 1]
    if duplicates:
        print(f"duplicate ids: {duplicates}")
        failed += 1

    print(f"{len(questions)} questions, {failed} problem(s)")
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
