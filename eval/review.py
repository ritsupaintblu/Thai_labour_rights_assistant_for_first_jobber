"""Label saved answers by hand in the browser, one question at a time.

    python eval/review.py                                   # eval/results/after_fixes3/answers_agent.jsonl
    python eval/review.py eval/results/heldout4/fixed/run1/answers_agent.jsonl
    python eval/review.py --summary                         # compare the saved labels with the automatic checks

Each click is saved at once next to the answers file (answers_agent.jsonl -> manual_labels_agent.csv), so you can stop and carry on later.
The automatic checks (LLM judge, number, citation) stay hidden until you label a question, so they don't sway you.
"""

import argparse
import csv
import json
import os
import sys
import webbrowser
from collections import Counter
from datetime import datetime
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8")

ROOT = Path(__file__).resolve().parent.parent
DEFAULT_RUN = ROOT / "eval" / "results" / "after_fixes3" / "answers_agent.jsonl"
CHUNKS = ROOT / "data" / "processed" / "chunks.jsonl"
QUESTION_FILES = ["questions.jsonl", "heldout.jsonl", "heldout2.jsonl", "heldout3.jsonl", "heldout4.jsonl", "heldout5.jsonl"]
VERDICTS = ["correct", "partly", "wrong", "unsure"]
FIELDS = ["id", "verdict", "note", "labelled_at"]
AUTO = ["behaviour_ok", "number_ok", "supporting_ok", "citation_hit", "judge_correct"]


def shown(path):
    try:
        return path.relative_to(ROOT).as_posix()
    except ValueError:
        return path.as_posix()


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def load_questions():
    questions = {}
    for name in QUESTION_FILES:
        path = ROOT / "eval" / name
        if path.exists():
            for q in read_jsonl(path):
                questions.setdefault(q["id"], q)
    return questions


def load_sections():
    """Full in-force text of each section, joining its parts in order."""
    parts = {}
    for c in read_jsonl(CHUNKS):
        if c["status"] == "in_force":
            parts.setdefault((c["law"], c["section"]), []).append((c["part"] or 0, c["text"]))
    return {key: "\n".join(t for _, t in sorted(p)) for key, p in parts.items()}


def load_labels(path):
    if not path.exists():
        return {}
    with open(path, encoding="utf-8-sig", newline="") as f:
        return {r["id"]: r for r in csv.DictReader(f)}


def save_labels(path, labels, order):
    rank = {qid: i for i, qid in enumerate(order)}
    tmp = path.with_suffix(".tmp")
    with open(tmp, "w", encoding="utf-8-sig", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=FIELDS)
        writer.writeheader()
        for qid in sorted(labels, key=lambda k: rank.get(k, len(rank))):
            writer.writerow({k: labels[qid].get(k, "") for k in FIELDS})
    os.replace(tmp, path)


def build_items(run):
    questions, sections = load_questions(), load_sections()
    items = []
    for row in read_jsonl(run):
        q = questions.get(row["id"], {})
        cited = {(c["law"], c["section"]) for c in row["answer"]["citations"] if c.get("law")}
        gold = [(g["law"], g["section"]) for g in q.get("gold_sections", [])]
        keys = gold + sorted(cited - set(gold))
        items.append({
            "id": row["id"], "type": row["type"], "question": row["question"], "answer": row["answer"],
            "expected_behavior": q.get("expected_behavior"), "reference_answer": q.get("reference_answer"),
            "expected_numbers": q.get("expected_numbers"), "wrong_numbers": q.get("wrong_numbers"),
            "evidence": q.get("evidence", []), "reference_source": q.get("reference_source"),
            "sections": [{"law": l, "section": s, "gold": (l, s) in gold, "cited": (l, s) in cited,
                          "text": sections.get((l, s))} for l, s in keys],
            "trace": row.get("trace", []), "seconds": row.get("seconds"),
            "auto": {k: row.get(k) for k in AUTO},
        })
    return items


def summary(run, labels_path):
    rows = {r["id"]: r for r in read_jsonl(run)}
    labels = load_labels(labels_path)
    print(f"{len(labels)}/{len(rows)} labelled in {shown(labels_path)}")
    print("verdicts:", dict(Counter(l["verdict"] for l in labels.values())))
    by_type = {}
    for qid, l in labels.items():
        by_type.setdefault(rows[qid]["type"], Counter())[l["verdict"]] += 1
    for t, c in sorted(by_type.items()):
        print(f"  {t:14} " + "  ".join(f"{v}={c[v]}" for v in VERDICTS if c[v]))
    for metric in ("judge_correct", "behaviour_ok"):
        table = Counter()
        for qid, l in labels.items():
            auto = rows[qid].get(metric)
            if auto is None or l["verdict"] not in ("correct", "wrong"):
                continue
            table[(auto, l["verdict"] == "correct")] += 1
        n = sum(table.values())
        if not n:
            continue
        agree = table[(True, True)] + table[(False, False)]
        print(f"\n{metric} vs human (correct/wrong only, {n} questions): agree {agree}/{n}")
        print(f"  auto pass, human correct {table[(True, True)]:3}   auto pass, human wrong   {table[(True, False)]:3}")
        print(f"  auto fail, human correct {table[(False, True)]:3}   auto fail, human wrong   {table[(False, False)]:3}")
        missed = sorted(qid for qid, l in labels.items() if rows[qid].get(metric) is True and l["verdict"] == "wrong")
        if missed:
            print("  passed by the check but wrong by hand:", ", ".join(missed))


def serve(run, labels_path, port, open_browser):
    items = build_items(run)
    order = [i["id"] for i in items]
    known = set(order)
    labels = load_labels(labels_path)
    page = (Path(__file__).with_name("review.html")).read_text(encoding="utf-8")
    meta = {"run": shown(run), "labels": shown(labels_path)}

    class Handler(BaseHTTPRequestHandler):
        def send(self, body, kind="application/json", status=200):
            data = body.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", f"{kind}; charset=utf-8")
            self.send_header("Content-Length", str(len(data)))
            self.send_header("Cache-Control", "no-store")
            self.end_headers()
            self.wfile.write(data)

        def do_GET(self):
            if self.path == "/":
                self.send(page, "text/html")
            elif self.path == "/api/items":
                self.send(json.dumps({"meta": meta, "items": items, "labels": labels}, ensure_ascii=False))
            else:
                self.send('{"error": "not found"}', status=404)

        def do_POST(self):
            if self.path != "/api/label":
                return self.send('{"error": "not found"}', status=404)
            body = json.loads(self.rfile.read(int(self.headers.get("Content-Length", 0))) or b"{}")
            qid, verdict = body.get("id"), body.get("verdict")
            if qid not in known or verdict not in VERDICTS + [""]:
                return self.send('{"error": "bad label"}', status=400)
            if verdict == "":
                labels.pop(qid, None)
            else:
                labels[qid] = {"id": qid, "verdict": verdict, "note": (body.get("note") or "").strip(),
                               "labelled_at": datetime.now().isoformat(timespec="seconds")}
            save_labels(labels_path, labels, order)
            self.send(json.dumps({"ok": True, "label": labels.get(qid)}, ensure_ascii=False))

        def log_message(self, *args):
            pass

    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    url = f"http://127.0.0.1:{server.server_address[1]}/"
    print(f"Reviewing {meta['run']} ({len(items)} questions, {len(labels)} labelled)")
    print(f"Labels save to {meta['labels']}")
    print(f"Open {url}  (Ctrl+C to stop)")
    if open_browser:
        webbrowser.open(url)
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nStopped. Run with --summary to compare your labels with the automatic checks.")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("run", nargs="?", type=Path, default=DEFAULT_RUN, help="an answers_*.jsonl file")
    parser.add_argument("--port", type=int, default=8765)
    parser.add_argument("--no-browser", action="store_true")
    parser.add_argument("--summary", action="store_true", help="print agreement with the automatic checks and exit")
    args = parser.parse_args()
    run = args.run.resolve()
    labels_path = run.with_name(run.stem.replace("answers", "manual_labels", 1) + ".csv")
    if args.summary:
        summary(run, labels_path)
    else:
        serve(run, labels_path, args.port, not args.no_browser)


if __name__ == "__main__":
    main()
