"""Evals 2-4: score answers from the baseline (no retrieval), plain RAG and the agent on all the questions.

    python eval/run_answers.py baseline rag agent

Each answer is saved to eval/results/answers_<mode>.jsonl as it finishes, so an interrupted run carries on.
The summaries are written to eval/results_answers.csv and eval/results_behaviour.csv. The agent also runs on
eval/controls.jsonl: questions that give every detail, or hold a right belief, which it should not ask about or correct.
"""

import csv
import json
import sys
import time
import traceback
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
sys.stdout.reconfigure(encoding="utf-8")

from src.answer import FORMAT, mentions_number, parse_draft
from src.llm import load_complete
from src.retrieval.corpus import ROOT

QUESTIONS = ROOT / "eval" / "questions.jsonl"
OUT = ROOT / "eval" / "results"
SUMMARY = ROOT / "eval" / "results_answers.csv"
BEHAVIOUR = ROOT / "eval" / "results_behaviour.csv"
CONTROLS = ROOT / "eval" / "controls.jsonl"
BASELINE_SYSTEM = f"คุณเป็นผู้ช่วยด้านสิทธิแรงงานไทย ตอบจากความรู้ของคุณ อ้างมาตราโดยใช้รหัสกฎหมาย เช่น LPA2541 สำหรับ พ.ร.บ.คุ้มครองแรงงาน\n{FORMAT}"
JUDGE_SYSTEM = """คุณเป็นผู้ตรวจคำตอบ เทียบคำตอบกับเฉลยเท่านั้น ไม่ให้คะแนนความยาวหรือสำนวน
คำตอบถูกเมื่อข้อเท็จจริงหลักและตัวเลขตรงกับเฉลย และไม่มีข้อมูลที่ขัดกับเฉลย
ตอบ JSON เท่านั้น: {"correct": true} หรือ {"correct": false}"""
METRICS = ["behaviour_ok", "number_ok", "citation_hit", "judge_correct"]


def behaviour_ok(q, a):
    expected = q["expected_behavior"]
    if expected == "refuse":
        return a["not_found"]
    if expected == "ask_clarification":
        return bool(a["clarifying_question"])
    if expected == "correct_premise":
        return bool(a["correction"]) and not a["not_found"]
    return not a["not_found"] and not a["clarifying_question"]


def number_ok(q, a):
    """Every labelled figure must be stated, and no outdated one. A correction may name the figure it corrects."""
    if q["expected_number"] is None:
        return None
    text = a["answer"] + " " + (a["correction"] or "")
    if a.get("calculation") and a["calculation"]["value"] != q["expected_number"]:
        return False
    if q["expected_behavior"] == "answer" and any(mentions_number(n, text) for n in q.get("wrong_numbers", [])):
        return False
    return all(mentions_number(n, text) for n in q["expected_numbers"])


def citation_hit(q, a):
    if not q["gold_sections"] or q["expected_behavior"] == "ask_clarification":
        return None
    gold = {(g["law"], g["section"]) for g in q["gold_sections"]}
    return bool(gold & {(c["law"], c["section"]) for c in a["citations"]})


def judge(q, a, complete):
    if q["expected_behavior"] not in ("answer", "correct_premise"):
        return None
    text = a["answer"] + (f"\nแก้ไขความเข้าใจ: {a['correction']}" if a["correction"] else "")
    reply = complete([{"role": "system", "content": JUDGE_SYSTEM},
                      {"role": "user", "content": f"คำถาม: {q['question']}\nเฉลย: {q['reference_answer']}\nคำตอบ: {text}"}]).content
    try:
        return bool(json.loads((reply or "").strip().removeprefix("```json").removesuffix("```"))["correct"])
    except (ValueError, KeyError, TypeError):
        return None


def baseline_answerer(complete):
    def answer(question):
        reply = complete([{"role": "system", "content": BASELINE_SYSTEM}, {"role": "user", "content": question}]).content
        try:
            draft = parse_draft(reply).model_dump()
        except ValueError:
            draft = {"answer": reply or "", "citations": [], "not_found": False, "clarifying_question": None, "correction": None}
        return draft, []
    return answer


def rag_answerer(complete, search_law):
    from src.rag import answer_with_rag
    return lambda question: (answer_with_rag(question, search_law, complete).model_dump(), [])


def agent_answerer(complete):
    from src.agent.loop import build_agent
    agent = build_agent(complete)

    def answer(question):
        result, trace = agent.run(question)
        return result.model_dump(), trace
    return answer


def load_search_law():
    from src.agent.tools.search_law import SearchLaw
    from src.retrieval.hybrid import SEARCH_VARIANT, build_retrievers
    return SearchLaw(build_retrievers()[SEARCH_VARIANT])


def correction_ok(q, a):
    """The field is filled in, without refusing, and says what the reference says. None if nothing needs correcting."""
    if q["expected_behavior"] != "correct_premise":
        return None
    text = a["correction"] or ""
    if not text or a["not_found"]:
        return False
    terms = q.get("correction_terms")
    return (not terms or any(t in text for t in terms)) and all(mentions_number(n, text) for n in q.get("expected_numbers", []))


def behaviour_row(mode, records, questions):
    """Asking and correcting, with the mistakes in both directions, since recall alone rewards always asking."""
    by_id = {r["id"]: r for r in records}
    needs = [q for q in questions if q["expected_behavior"] == "ask_clarification" and q["id"] in by_id]
    others = [q for q in questions if q["expected_behavior"] != "ask_clarification" and q["id"] in by_id]
    asked = sum(bool(by_id[q["id"]]["answer"]["clarifying_question"]) for q in needs)
    over = [q["id"] for q in others if by_id[q["id"]]["answer"]["clarifying_question"]]
    wrong = [q for q in questions if q["expected_behavior"] == "correct_premise" and q["id"] in by_id]
    rest = [q for q in questions if q["expected_behavior"] != "correct_premise" and q["id"] in by_id]
    return {"mode": mode, "ask_recall": f"{asked}/{len(needs)}", "over_ask": f"{len(over)}/{len(others)}",
            "ask_precision": f"{asked}/{asked + len(over)}", "over_asked": " ".join(over),
            "correction_filled": f"{sum(bool(by_id[q['id']]['answer']['correction']) for q in wrong)}/{len(wrong)}",
            "correction_right": f"{sum(bool(correction_ok(q, by_id[q['id']]['answer'])) for q in wrong)}/{len(wrong)}",
            "false_corrections": f"{sum(bool(by_id[q['id']]['answer']['correction']) for q in rest)}/{len(rest)}"}


def run_controls(answerer):
    """Saved like the answers. Returns how often the agent asked or corrected when it should not have."""
    with open(CONTROLS, encoding="utf-8") as f:
        controls = list(map(json.loads, f))
    path = OUT / "controls_agent.jsonl"
    done = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            done = {r["id"]: r for r in map(json.loads, f)}
    with open(path, "a", encoding="utf-8") as f:
        for c in controls:
            if c["id"] not in done:
                started = time.perf_counter()
                answer, trace = answerer(c["question"])
                done[c["id"]] = {**c, "answer": answer, "trace": trace, "seconds": round(time.perf_counter() - started, 1)}
                f.write(json.dumps(done[c["id"]], ensure_ascii=False) + "\n")
                f.flush()
    pairs = [done[c["id"]] for c in controls if c["kind"] == "details_given"]
    rights = [done[c["id"]] for c in controls if c["kind"] == "right_belief"]
    return {"pairs_over_asked": f"{sum(bool(r['answer']['clarifying_question']) for r in pairs)}/{len(pairs)}",
            "right_beliefs_corrected": f"{sum(bool(r['answer']['correction']) for r in rights)}/{len(rights)}",
            "controls_refused": f"{sum(r['answer']['not_found'] for r in pairs + rights)}/{len(pairs + rights)}"}


def run_mode(mode, answerer, questions, complete):
    OUT.mkdir(exist_ok=True)
    path = OUT / f"answers_{mode}.jsonl"
    done = {}
    if path.exists():
        with open(path, encoding="utf-8") as f:
            done = {r["id"]: r for r in map(json.loads, f)}
    with open(path, "a", encoding="utf-8") as f, open(OUT / f"errors_{mode}.log", "a", encoding="utf-8") as errors:
        for q in questions:
            if q["id"] in done:
                # checks that need no model are scored again, so a fixed check applies to saved answers
                done[q["id"]]["number_ok"] = number_ok(q, done[q["id"]]["answer"])
                continue
            started = time.perf_counter()
            try:
                answer, trace = answerer(q["question"])
                seconds = round(time.perf_counter() - started, 1)
                correct = judge(q, answer, complete)
            except Exception:  # one failed question must not lose the run; rerun to retry it
                errors.write(f"{q['id']}\n{traceback.format_exc()}\n")
                errors.flush()
                print(mode, q["id"], "FAILED, see", errors.name, flush=True)
                continue
            record = {"id": q["id"], "type": q["type"], "question": q["question"], "answer": answer, "trace": trace,
                      "seconds": seconds, "behaviour_ok": behaviour_ok(q, answer), "number_ok": number_ok(q, answer),
                      "citation_hit": citation_hit(q, answer), "judge_correct": correct}
            done[q["id"]] = record
            f.write(json.dumps(record, ensure_ascii=False) + "\n")
            f.flush()
            print(mode, q["id"], seconds, {m: record[m] for m in METRICS}, flush=True)
    records = [done[q["id"]] for q in questions if q["id"] in done]
    if len(records) < len(questions):
        print(f"{mode}: only {len(records)} of {len(questions)} questions finished. Rerun to retry the rest", flush=True)
    return records


def summarize(mode, records):
    groups = defaultdict(list)
    for r in records:
        groups["all"].append(r)
        groups[r["type"]].append(r)
    rows = []
    for group, rs in groups.items():
        row = {"mode": mode, "group": group, "questions": len(rs), "seconds_per_question": round(sum(r["seconds"] for r in rs) / len(rs), 1)}
        for m in METRICS:
            known = [r[m] for r in rs if r[m] is not None]
            row[m] = f"{sum(known)}/{len(known)}" if known else ""
        rows.append(row)
    return rows


def main():
    modes = [a for a in sys.argv[1:] if not a.startswith("--")]
    ids = next((a[6:].split(",") for a in sys.argv[1:] if a.startswith("--ids=")), None)
    with open(QUESTIONS, encoding="utf-8") as f:
        questions = [q for q in map(json.loads, f) if not ids or q["id"] in ids]
    complete = load_complete()
    search_law = load_search_law() if "rag" in modes else None
    makers = {"baseline": lambda: baseline_answerer(complete), "rag": lambda: rag_answerer(complete, search_law),
              "agent": lambda: agent_answerer(complete)}
    rows, behaviour = [], []
    for mode in modes:
        answerer = makers[mode]()
        records = run_mode(mode, answerer, questions, complete)
        rows += summarize(mode, records)
        extra = run_controls(answerer) if mode == "agent" and not ids else {}
        behaviour.append({**behaviour_row(mode, records, questions), **extra})
    for row in rows + behaviour:
        print(row)
    if not ids:  # a partial run is a smoke test, not a result
        fields = ["mode", "group", "questions", *METRICS, "seconds_per_question"]
        with open(SUMMARY, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)
        fields = [*behaviour_row("", [], [])] + ["pairs_over_asked", "right_beliefs_corrected", "controls_refused"]
        with open(BEHAVIOUR, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(behaviour)


if __name__ == "__main__":
    main()
