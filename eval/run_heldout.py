"""The held-out check: the agent on 30 questions it was never tuned on, run several times to see how much it varies.

    python eval/run_heldout.py                               # eval/heldout.jsonl, 3 runs
    python eval/run_heldout.py --set=heldout2 --label=fixed  # another locked set, saved under a label

Each set eval/<set>.jsonl was written from the statutes and locked by eval/<set>.lock before any run. The script
refuses to start if the file no longer matches its hash, so the questions cannot be edited to fit the results.
Each run is saved to eval/results/<set>/[<label>/]run<n>/, so an interrupted run carries on. The summaries are
eval/results_<set>[_<label>].csv (each run, then the range) and eval/results_<set>[_<label>]_questions.csv.
"""

import csv
import hashlib
import json
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import run_answers  # noqa: E402
from run_answers import METRICS, agent_answerer, behaviour_row, correction_ok, run_mode, summarize  # noqa: E402

from src.llm import load_complete  # noqa: E402
from src.retrieval.corpus import ROOT  # noqa: E402

BEHAVIOUR = ["ask_recall", "over_ask", "ask_precision", "correction_filled", "correction_right", "false_corrections"]


def load_locked(name):
    path, lock = ROOT / "eval" / f"{name}.jsonl", ROOT / "eval" / f"{name}.lock"
    data = path.read_bytes().replace(b"\r\n", b"\n")  # so a Windows checkout gives the same hash
    expected = json.loads(lock.read_text(encoding="utf-8"))["sha256"]
    if hashlib.sha256(data).hexdigest() != expected:
        raise SystemExit(f"{path.name} does not match {lock.name}. The held-out questions must not change after locking")
    return [json.loads(line) for line in data.decode("utf-8").splitlines() if line.strip()]


def fraction(text):
    done, total = text.split("/")
    return int(done), int(total)


def spread(values):
    """min-max of "a/b" counts with the same b, as "lo-hi/b", or "a/b" if every run agrees."""
    counts = [fraction(v) for v in values if v]
    if not counts:
        return ""
    if len({c[1] for c in counts}) > 1:  # the judge can fail to reply, which changes the total
        return " to ".join(f"{a}/{b}" for a, b in sorted(set(counts)))
    lo, hi, total = min(c[0] for c in counts), max(c[0] for c in counts), counts[0][1]
    return f"{lo}/{total}" if lo == hi else f"{lo}-{hi}/{total}"


def outcomes(q, record):
    answer = record["answer"]
    return {**{m: record.get(m) for m in METRICS}, "correction_ok": correction_ok(q, answer),
            "asked": bool(answer["clarifying_question"]), "refused": answer["not_found"]}


def main():
    args = dict(a[2:].split("=", 1) for a in sys.argv[1:] if a.startswith("--") and "=" in a)
    runs, name, label = int(args.get("runs", 3)), args.get("set", "heldout"), args.get("label", "")
    out = ROOT / "eval" / "results" / name / label
    stem = ROOT / "eval" / f"results_{name}{'_' + label if label else ''}"
    questions = load_locked(name)
    complete = load_complete()
    answerer = agent_answerer(complete)
    rows, per_run = [], []
    for n in range(1, runs + 1):
        run_answers.OUT = out / f"run{n}"  # run_mode saves and resumes from here
        run_answers.OUT.mkdir(parents=True, exist_ok=True)
        records = run_mode("agent", answerer, questions, complete)
        if len(records) < len(questions):
            raise SystemExit(f"run {n} is missing questions. Rerun to retry them before the summary is written")
        rows += [{"run": n, **r} for r in summarize("agent", records)]
        rows.append({"run": n, "group": "behaviour", **behaviour_row("agent", records, questions)})
        per_run.append({r["id"]: r for r in records})

    # the range over runs, for each group and measure
    by_group = defaultdict(list)
    for r in rows:
        by_group[r["group"]].append(r)
    for group, rs in by_group.items():
        fields = BEHAVIOUR if group == "behaviour" else METRICS
        rows.append({"run": "range", "group": group, "questions": rs[0].get("questions", ""),
                     **{m: spread([r.get(m, "") for r in rs]) for m in fields}})
    fields = ["run", "mode", "group", "questions", *METRICS, "seconds_per_question", *BEHAVIOUR, "over_asked"]
    with open(f"{stem}.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)

    # each question across runs, so a flip shows which question moved and on what
    names = [*METRICS, "correction_ok", "asked", "refused"]
    with open(f"{stem}_questions.csv", "w", encoding="utf-8", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["id", "type", "expected_behavior", *names, "flips"])
        for q in questions:
            seen = [outcomes(q, run[q["id"]]) for run in per_run]
            cells = [" ".join("-" if s[m] is None else str(int(s[m])) for s in seen) for m in names]
            flips = [m for m in names if len({s[m] for s in seen}) > 1]
            writer.writerow([q["id"], q["type"], q["expected_behavior"], *cells, " ".join(flips)])
    for r in rows:
        if r["run"] == "range":
            print(r)


if __name__ == "__main__":
    main()
