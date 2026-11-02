"""Write read/Update.pdf: which stage of the daily plan the project is in.

Runs after every commit through .githooks/post-commit. Enable it once per clone with:
    git config core.hooksPath .githooks

Status comes from what is in the repo. A file existing does not prove the work is finished,
so a task only reaches Done when it can be measured or is listed in CONFIRMED.
"""

import csv
import hashlib
import html
import io
import json
import subprocess
from collections import Counter
from pathlib import Path

import pymupdf

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "read" / "Update.pdf"
FONT_DIR = Path("C:/Windows/Fonts")
EVAL_QUESTIONS = 100

# Tasks the repo cannot prove. Add a task's key here once it has really been checked
CONFIRMED = {"figures"}

DONE, ACTIVE, TODO = "Done", "In progress", "Not started"


def git(*args):
    result = subprocess.run(["git", *args], cwd=ROOT, capture_output=True, encoding="utf-8")
    return result.stdout.strip()


def found(*patterns):
    return sorted(p for pattern in patterns for p in ROOT.glob(pattern) if p.is_file() and p.name != "__init__.py")


def from_files(key, note_done, note_todo, *patterns):
    """Status for a task whose only evidence is its output files."""
    files = found(*patterns)
    if key in CONFIRMED:
        return DONE, note_done
    if files:
        return ACTIVE, f"{len(files)} file(s) so far; not confirmed finished"
    return TODO, note_todo


def manual(key, note_done, note_todo):
    return (DONE, note_done) if key in CONFIRMED else (TODO, note_todo)


def corpus_task():
    with open(ROOT / "data" / "manifest.csv", encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    hashes = {hashlib.sha256(p.read_bytes()).hexdigest() for p in found("data/raw/**/*")}
    ok = sum(r["sha256"].strip() in hashes for r in rows)
    status = DONE if ok == len(rows) else ACTIVE
    return status, f"{ok} of {len(rows)} files match the manifest hash"


def manifest_task():
    tracked = git("ls-files", "data/manifest.csv", "scripts/fetch_corpus.py").splitlines()
    return (DONE, "Both are committed") if len(tracked) == 2 else (ACTIVE, "Not all committed yet")


def chunks_task():
    path = ROOT / "data" / "processed" / "chunks.jsonl"
    if not path.exists():
        return TODO, "data/processed/chunks.jsonl does not exist"
    with open(path, encoding="utf-8") as f:
        counts = Counter(json.loads(line)["status"] for line in f)
    detail = ", ".join(f"{n:,} {status}" for status, n in counts.most_common())
    return DONE, f"{sum(counts.values()):,} chunks: {detail}"


def questions_task():
    path = ROOT / "eval" / "questions.jsonl"
    if not path.exists():
        return TODO, "eval/questions.jsonl does not exist"
    with open(path, encoding="utf-8") as f:
        n = sum(1 for line in f if line.strip())
    return (DONE if n >= EVAL_QUESTIONS else ACTIVE), f"{n} of {EVAL_QUESTIONS} questions written"


def plan():
    """(day, [(task, (status, note))]), in the order of the project's daily plan."""
    return [
        ("Day 1: data + eval", [
            ("Download required files, check links, confirm section numbers", corpus_task()),
            ("Write manifest.csv + fetch_corpus.py", manifest_task()),
            ("Convert PDF to text, section-level chunks and metadata", chunks_task()),
            ("Write the labelled test set: 100 questions", questions_task()),
            ("Check severance and overtime figures against the Act text", manual(
                "figures", "Checked against the Act text", "Not recorded as checked yet")),
        ]),
        ("Day 2: RAG", [
            ("BM25 baseline, BM25 + PyThaiNLP, embeddings, hybrid", from_files(
                "retrieval", "All variants built", "src/retrieval/ does not exist", "src/retrieval/**/*.py")),
            ("Run Eval 1 on every variant and record the table", from_files(
                "eval1", "Results recorded", "No retrieval results yet", "eval/results_retrieval.csv", "eval/results/*retrieval*")),
            ("Generate cited answers + Pydantic schema + retry", from_files(
                "answers", "Answers and schema built", "src/schemas.py does not exist", "src/schemas.py")),
            ("Run the no-retrieval baseline for Eval 2", manual(
                "baseline", "Baseline recorded", "Not recorded as run yet")),
        ]),
        ("Day 3: agent + API", [
            ("Tools: search_law, calculate, get_rate, with allow-list and argument checks", from_files(
                "tools", "Tools built", "src/agent/ does not exist", "src/agent/*tool*.py", "src/agent/tools/**/*.py")),
            ("Agent loop + stop conditions (cited answer or 5 steps)", from_files(
                "agent", "Agent loop built", "No agent loop yet", "src/agent/*loop*.py", "src/agent/*agent*.py")),
            ("Sweep min_score, run Evals 2-4", from_files(
                "evals", "Results recorded", "No agent results yet", "eval/results_*.csv", "eval/results/*.csv")),
            ("FastAPI POST /ask (SSE if time), demo with new questions", from_files(
                "api", "API built", "src/api/ does not exist", "src/api/**/*.py")),
        ]),
        ("Day 4: reserve", [
            ("Report, 4-8 pages", from_files(
                "report", "Report finished", "report.pdf does not exist", "report.pdf")),
            ("Video, 3-6 minutes: one success + one failure", manual(
                "video", "Video link ready", "Not recorded as made yet")),
            ("Confirm the README runs on a new machine", manual(
                "fresh_machine", "Confirmed on a new machine", "Not recorded as checked yet")),
        ]),
    ]


def build_html(days):
    all_tasks = [t for _, tasks in days for t in tasks]
    done = sum(status == DONE for _, (status, _) in all_tasks)
    current = next((day for day, tasks in days if any(s != DONE for _, (s, _) in tasks)), "All days finished")
    upcoming = [(task, note) for task, (status, note) in all_tasks if status != DONE][:4]
    e = html.escape

    parts = ["<h1>Update</h1>",
             f"<p><b>Current stage: {e(current)}</b> ({done} of {len(all_tasks)} planned tasks done)</p>",
             f"<p>Last commit: {e(git('log', '-1', '--format=%h, %cs: %s'))}</p>",
             "<h2>What to do next</h2><ol>"]
    parts += [f"<li><b>{e(task)}</b>: {e(note)}</li>" for task, note in upcoming]
    parts.append("</ol>")
    for day, tasks in days:
        parts.append(f"<h2>{e(day)}</h2><table><tr><th width='45%'>Task</th><th width='13%'>Status</th><th>Notes</th></tr>")
        for task, (status, note) in tasks:
            parts.append(f"<tr><td>{e(task)}</td><td><b>{status.replace(' ', '&nbsp;')}</b></td><td>{e(note)}</td></tr>")
        parts.append("</table>")
    return "".join(parts)


def write_pdf(body):
    css = """
    * {font-family: thai; font-size: 9pt;}
    @font-face {font-family: thai; src: url(tahoma.ttf);}
    @font-face {font-family: thai; font-weight: bold; src: url(tahomabd.ttf);}
    h1 {font-size: 20pt; margin-bottom: 6pt;}
    h2 {font-size: 12pt; margin-top: 14pt; margin-bottom: 4pt;}
    table {border-collapse: collapse;}
    th, td {border: 0.5pt solid #888888; padding: 3pt; text-align: left;}
    """
    story = pymupdf.Story(html=body, user_css=css, archive=pymupdf.Archive(str(FONT_DIR)))
    buffer = io.BytesIO()
    writer = pymupdf.DocumentWriter(buffer)
    page = pymupdf.paper_rect("a4")
    area = page + (45, 45, -45, -45)
    more = True
    while more:
        device = writer.begin_page(page)
        more, _ = story.place(area)
        story.draw(device)
        writer.end_page()
    writer.close()
    with pymupdf.open(stream=buffer.getvalue(), filetype="pdf") as pdf:
        pdf.subset_fonts()  # embed only the characters used, not the whole font
        OUT.write_bytes(pdf.tobytes(garbage=4, deflate=True))


def main():
    write_pdf(build_html(plan()))
    print(f"Updated {OUT.relative_to(ROOT)}")


if __name__ == "__main__":
    main()
