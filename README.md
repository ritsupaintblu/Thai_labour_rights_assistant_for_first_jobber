# Thai Labour-Rights Assistant for First Jobbers

An LLM-powered assistant that answers questions about Thai employee rights, using the laws that are **actually in force**, with section citations and effective dates. Money questions such as severance, overtime and social-security contributions are calculated in Python, not by the model.

> **Not legal advice.** This is an information tool built as a course capstone. Corpus is frozen **as of 1 November 2026 (B.E. 2569)**. Check the official text or the Department of Labour Protection and Welfare (hotline 1546) before acting.

## Project status

The assistant runs end to end: retrieval, the agent, its tools and the API are built and evaluated. The report and demo video are still to come.

| Part | Status |
|---|---|
| Corpus files and `data/manifest.csv` | Done |
| `scripts/fetch_corpus.py` | Done |
| Section-level chunks (`scripts/build_chunks.py`) | Done |
| Index (`scripts/build_index.py`) | Done |
| Retrievers: BM25, BM25 + PyThaiNLP, embeddings, hybrid, reranked (`src/retrieval/`) | Done |
| Retrieval evaluation (`eval/run_retrieval.py`) | Done |
| Agent loop and `search_law`, `calculate` tools (`src/agent/`) | Done |
| FastAPI service (`src/api/`) | Done |
| Evaluation questions (`eval/questions.jsonl`) | Done |
| Official rates (`data/rates.csv`) and `get_rate` | Done |
| Evaluation results (`eval/results_*.csv`) | Done |

---

## The problem

New employees often don't know their basic rights: probation, sick leave, maternity leave, overtime pay, severance, and social-security deductions. Three things make this harder than it should be:

1. **The law is long and formal.** The Labour Protection Act B.E. 2541 has been amended nine times.
2. **Much online information is outdated.** Many "full text" copies online stop before Amendment No. 9 (in force 7 Dec 2025), which raised maternity leave from 98 to 120 days.
3. **General LLMs answer confidently and wrongly.** They repeat old figures, and they treat draft bills as law, such as "10 days' annual leave," which is still only a proposal.

This assistant is designed to answer only from in-force legal text, citing the section and the date it took effect. When the law doesn't cover a question, it says so instead of guessing.

## What it will do

Ask a question in Thai or English, for example:

- "ลาคลอดได้กี่วัน ได้รับค่าจ้างกี่วัน" (How many days of maternity leave, and how many are paid?)
- "ทำงานมา 3 ปี 2 เดือน เงินเดือน 25,000 ถูกเลิกจ้าง ได้ค่าชดเชยเท่าไร" (Worked 3 years 2 months on 25,000 baht/month and got laid off. How much severance?)
- "เงินเดือน 20,000 ถูกหักประกันสังคมเดือนละเท่าไร" (How much social security is deducted from a 20,000 baht salary?)

You get back a validated JSON answer. The target format is:

```json
{
  "answer": "ลาคลอดได้ไม่เกิน 120 วันต่อการตั้งครรภ์ นายจ้างจ่ายค่าจ้างไม่เกิน 60 วัน",
  "citations": [
    {"law": "LPA2541", "section": "41", "amendment_no": 9, "effective_date": "2025-12-07", "source": "พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541 (ฉบับรวมถึงฉบับที่ 9)"}
  ],
  "calculation": null,
  "as_of": "2026-11-01",
  "confidence": "high",
  "not_found": false,
  "clarifying_question": null,
  "correction": null
}
```

## How it will work

```
User question
   │
   ▼
FastAPI  POST /ask
   │
   ▼
Agent (gemma-4-E4B-it)
   ├── In parallel: rewrite the question in statute wording; does it need more details?
   ├── Tool choice, before seeing any law (max 5 steps)
   │     ├── search_law(query, k)       → reranked hybrid retrieval
   │     ├── calculate(kind, ...)       → severance / overtime / SSO contribution in Python
   │     └── get_rate(name, as_of, ...) → official rates from a versioned CSV
   ├── Search with both wordings, reranking 10 sections for each
   ├── In parallel: do the results cover this and quote an answer? Is a stated belief wrong?
   └── Refuse or ask back straight away, or write the answer
   │
   ▼
Pydantic-validated JSON answer with citations + as_of date
```

### Key design choices

- **Section-level chunks with legal metadata.** Each chunk is one section (มาตรา) tagged with `law`, `section`, `amendment_no`, `effective_date` and `status`. Retrieval returns only `in_force` text.
- **Thai-aware retrieval.** Thai has no spaces between words, so naive BM25 performs poorly. We compare raw BM25, BM25 with PyThaiNLP word segmentation, embeddings, and hybrid search.
- **Refusing from the content, not a score.** If the search results do not cover the question, the assistant says it doesn't know instead of guessing. Everyday wording scored low against the statutes: the same section scored 0.035 for one wording and 0.999 for another. Statute wording raised the scores of out-of-scope questions too, so no score floor could separate them. If the model cannot quote a sentence that is really in the results and shares a key word with the question, the answer is marked low confidence. A rule for all employees counts as covering a question about one job or shift.
- **Searching in statute wording.** The model rewrites the question in legal terms, and the search keeps each section's best score across both wordings.
- **Asking back is its own step.** It runs before the model sees any law, because shown the sections the model listed every case instead of asking. It only applies if the results cover the topic, since it otherwise asked about out-of-scope questions.
- **Correcting a belief is its own step.** It only runs if the wording states a belief, such as "ใช่ไหม" or "ได้ยินว่า". The model compares the belief with the results, and code fills in `correction`. This misses a belief stated without those words.
- **The model chooses tools before it sees the law.** With section text in front of it, or the JSON format in its prompt, it often answered without calling a tool. Few-shot examples did not help.
- **The answer sees only the section it quoted.** Given all five sections, the model often answered from a neighbouring one.
- **A calculation cites its own rule.** The section behind each amount comes from `calculate`, so it is cited even if the search did not return it. If the model will not state a result from `calculate` or `get_rate`, code writes that answer itself.
- **Calculations in code.** Small models are unreliable at arithmetic, so all money is computed by deterministic, input-checked Python functions.
- **Safe tool use.** Tools are allow-listed. Arguments are validated before running. Retrieved text and tool results are treated as data, never as instructions.

## Course capability coverage

| Capability family | Where it will appear |
|---|---|
| Structured output with validation | Pydantic answer schema, retry on invalid JSON |
| Retrieval / RAG | Section-level index, cited answers |
| Retrieval evaluation | recall@k and MRR on a labelled question set |
| Agent loop with tools *(agentic)* | `search_law`, `calculate`, `get_rate`, stop condition |
| Served interface | FastAPI `POST /ask` (SSE streaming optional) |

## Corpus

The corpus is 35 official Thai government documents. Thai statutes and official announcements are not protected by copyright, so the raw files are committed in `data/raw/`.

| Source | Files | Why it's needed |
|---|---|---|
| Labour Protection Act B.E. 2541: consolidated text and Amendments No. 2–9 | 9 | Core employee rights, including work-from-home (No. 8, Section 23/1) and 120-day maternity leave, infant-care leave and spouse-support leave (No. 9, in force 7 Dec 2025) |
| Social Security Act B.E. 2533: consolidated text and Amendments No. 2–4 | 4 | Contributions and benefits |
| Ministerial Regulation on the Section 33 wage base, B.E. 2568 | 1 | Contribution ceiling of 17,500 baht from 1 Jan 2026 |
| Ministerial Regulation on Social Security contribution rates, B.E. 2565 | 1 | Employee rate of 5% from 1 Jan 2023 |
| Workmen's Compensation Act B.E. 2537: consolidated text and Amendment No. 2 | 2 | Compensation for work-related injury |
| Wage Committee Announcement on minimum wage (No. 14) | 1 | Minimum wage by province |
| Employee Welfare Fund: Ministerial Regulation on rates, B.E. 2568, and Royal Decree on collection, B.E. 2569 | 2 | Collection starts 1 Jan 2027 |
| Employee Welfare Fund: Q&A documents and web articles | 6 | Explanatory material, not law |
| Employment and Job-Seekers Protection Act B.E. 2528: consolidated text and Amendments No. 2–3 | 3 | Job seekers and recruitment |
| Other laws: fishing labour, state enterprise labour relations, home workers, foreign workers, maritime labour, and persons with disabilities (Act and Amendment No. 2) | 7 | Groups covered by separate laws |

### Manifest

Every file is listed in `data/manifest.csv` with its URL, publication date, effective date, status, SHA-256 hash, `law` code, `kind` (`consolidated`, `amendment`, `rate` or `secondary`) and `amendment_no`. When a law changes, add a row for the new version and mark the old row `superseded`.

| `status` | Rows |
|---|---:|
| `in_force` | 31 |
| `superseded` | 3 |
| `secondary` | 3 |

`manifest.csv` is read with `encoding="utf-8-sig"`, so it works even when saved from Excel (which adds a BOM).

Draft bills will be stored separately and used **only** as trap questions, never as answers. None have been added yet.

### Verifying the corpus

Requires Python 3 and `curl`; there are no Python packages to install.

```bash
python scripts/fetch_corpus.py
```

For each manifest row, the script looks for a file with the same SHA-256 anywhere under `data/raw/`, so filenames and folders don't need to match the `id`. If there is none, it downloads the row's `url` and checks the hash. The script exits with status 1 if any row is not verified.

| Output | Meaning |
|---|---|
| `OK` | A file with the expected hash is already in `data/raw/` |
| `DOWNLOADED` | The download matched and was saved as `data/raw/<id>.<ext>` |
| `HASH MISMATCH` | The server returned a different document, saved to `data/raw_unverified/` for comparison |
| `NOT A DOCUMENT` | The server returned a web page, so the hash could not be compared. Nothing is saved |
| `DOWNLOAD FAILED` | The request failed, for example with an HTTP 403 |

### Sources that can't be re-downloaded

Use the files in `data/raw/` as the corpus. With the archived files, 37 of 37 rows verify (checked 2026-11-02).

A full download test on 2026-11-01, with an empty folder, covered the 35 rows at that time. These rows do not verify from their URLs, including `foreign_workers` after its URL changed and the later `foreign_workers_no2` and `ssa_rate_2565`:

| Rows | Result | Reason |
|---|---|---|
| `fishing_labour`, `soe_labour`, `home_work`, `ssa_consolidated`, `ssa_no2`, `ssa_no3`, `ssa_no4`, `wca_consolidated`, `min_wage_no14`, `emp_no2`, `emp_no3`, `maritime_labour`, `disability`, `disability_no2` | `NOT A DOCUMENT` | `mol.go.th` serves a bot-protection page to scripts instead of the PDF. |
| `ewf_info1`, `ewf_info2`, `ewf_info3` | `NOT A DOCUMENT` | The sources are web articles, archived as PNG screenshots. The manifest holds the screenshot's hash, so a download can never match. The URL only records where the content came from. |
| `wca_no2`, `foreign_workers`, `foreign_workers_no2`, `ssa_rate_2565` | `DOWNLOAD FAILED` | `www.ratchakitcha.soc.go.th` returns HTTP 403. |

**TLS.** The script uses `curl` because Python rejected the certificates from several `.go.th` servers. Certificate checks stay on. This was tested on Windows; `curl` on other systems may still report `DOWNLOAD FAILED` for those servers.

### Building the chunks

Requires `pip install -r requirements.txt`, which pins PyMuPDF. After upgrading it, rebuild and run `git diff --stat data/processed/chunks.jsonl`: a difference means the upgrade changed the extraction, so review it before committing.

```bash
python scripts/build_chunks.py
```

This writes `data/processed/chunks.jsonl`, with one chunk per section (long sections are split into parts).

- **In-force wording comes from the consolidated texts.** An amendment already included in its consolidated text is skipped. The consolidated footnotes set each section's `amendment_no` and `effective_date`, so Section 41 cites Amendment No. 9 and 2025-12-07.
- **Amendments newer than the consolidated text are merged.** Only the Disability Act and the Foreign Workers Royal Ordinance need this. A replaced section becomes `superseded`. A changed paragraph becomes its own chunk with `change: "partial"`, and the older section gets `partly_amended_by`, because it still contains the outdated paragraph.
- **Not indexed:** rate announcements and secondary material, schedules, statements of reasons, and the transitional clauses of amending Acts.

### Retrieval

```bash
python scripts/build_index.py
```

This embeds the in-force chunks into `data/index/embeddings.npz`, which is not committed. The first run downloads the embedding model (4.3 GB). Rerun it after rebuilding the chunks: the retrievers refuse an index that does not match the chunks or the model.

| Variant | Method |
|---|---|
| `bm25_raw` | BM25, splitting on whitespace only. This is the baseline |
| `bm25_pythainlp` | BM25 with PyThaiNLP `newmm` word segmentation, after removing PDF line breaks inside Thai text |
| `embedding` | Cosine similarity with `BAAI/bge-m3` at a pinned revision, which runs on CPU and supports Thai |
| `hybrid` | Reciprocal rank fusion (k = 60) of `bm25_pythainlp` and `embedding` |
| `reranked` | The top 50 from `hybrid`, reordered by the cross-encoder `BAAI/bge-reranker-v2-m3` at a pinned revision |
| `reranked_live` | The same with the top 20. Plain RAG uses this one, because reranking 50 is too slow on CPU to use live |
| `reranked_10` | The same with the top 10 |
| `statute_both` | `reranked_10` on the question and on its statute wording, keeping each section's best score. The agent uses this one, and it needs the API key |

```python
from src.retrieval.hybrid import build_retrievers

retrievers = build_retrievers()
hits = retrievers["reranked"].search("ลาคลอดได้กี่วัน", k=5)
hits[0].chunk["section"], hits[0].score, hits[0].parts
```

Each variant returns chunks, so two parts of a long section can both appear. Only `in_force` chunks are searched. A hybrid score only reflects rank, so `parts` also keeps each method's own score for the `min_score` floor. A `reranked` score is the cross-encoder's relevance, from 0 to 1.

`python eval/run_retrieval.py` scores every variant on the 82 questions with gold sections and writes `eval/results_retrieval.csv`, overall and by question type:

| Variant | recall@1 | recall@3 | recall@5 | MRR | nDCG@5 | Seconds per query (CPU) |
|---|---|---|---|---|---|---|
| `bm25_raw` | 0.000 | 0.018 | 0.018 | 0.015 | 0.010 | 0.00 |
| `bm25_pythainlp` | 0.183 | 0.407 | 0.504 | 0.357 | 0.363 | 0.01 |
| `embedding` | 0.514 | 0.695 | 0.764 | 0.683 | 0.674 | 0.29 |
| `hybrid` | 0.382 | 0.628 | 0.713 | 0.579 | 0.581 | 0.27 |
| `reranked` | 0.667 | 0.801 | 0.841 | 0.812 | 0.791 | 35.58 |
| `reranked_live` | 0.626 | 0.772 | 0.795 | 0.755 | 0.745 | about 21 |
| `reranked_10` | 0.626 | 0.730 | 0.740 | 0.740 | 0.714 | not measured |
| **`statute_both`** | **0.628** | **0.854** | **0.900** | 0.797 | **0.809** | about 21 |

The reranked settings were chosen on these same questions, so its scores may be optimistic. The 35.58 and 21 second figures were measured with no scores saved. Rerunning reuses saved scores, so the reranked times in `eval/results_retrieval.csv` are not real search times.

`python eval/sweep_min_score.py` chooses the `min_score` floor for plain RAG: 0.10 has the best balanced accuracy, refusing 16 of 18 out-of-scope questions but also 12 of 82 answerable ones on score alone. Five of the nine questions with no gold section in the `reranked` top 5 (`T09`, `T16`, `T17`, `T20`, `C20`) take their figures from rate announcements, which are looked up with `get_rate` rather than searched.

### Official rates

Rate files are not indexed. Their figures are in `data/rates.csv`, one row per rate and period, with the source `id` and clause. `src/agent/tools/get_rate.py` looks them up for a date:

```python
from src.agent.tools.get_rate import get_rate

get_rate("sso_employee_rate_percent", "2026-11-01")                  # found: 5
get_rate("min_wage_daily", "2026-11-01", province="นนทบุรี")          # found: 372
get_rate("min_wage_daily", "2026-11-01", province="เชียงใหม่")         # needs_input: district
get_rate("sso_wage_base_max", "2020-01-01")                          # not_found
```

The result's `status` is `found`, `needs_input` (ask the user for the items in `missing`), `not_found` (the table has no rate for that date, so don't guess) or `invalid`. A `found` result includes the source's manifest title and clause.

The figures were typed by hand: the minimum wage from a scan, checked against the announcement's own summary table, and the others from the PDFs. To add a rate, add a row, end the previous period with `effective_to`, and run the tests:

```bash
python -m unittest discover -s tests -t .
```

The minimum wage announcement does not apply to government bodies, state enterprises, non-profit employers, employers of home workers, seagoing freight work, or agricultural work that is not year-round. `get_rate` does not check for these.

## Evaluation

The evaluation set is in `eval/questions.jsonl`: 100 questions, each with the correct section(s), reference answer, expected number, `expected_behavior` (`answer`, `refuse`, `ask_clarification` or `correct_premise`) and `reference_source`, which names the source files by their `manifest.csv` title. The evals are described below.

`python eval/check_questions.py` checks the labels against the chunks: each section must be in force and contain the quoted evidence, each formula must give the expected number, each expected number must be in the reference answer, each outdated number must be in `wrong_answer`, out-of-scope terms must not appear in the corpus, out-of-scope answers must refuse, and each `reference_source` must match the manifest. Rerun it after rebuilding the chunks.

**Label limits.** Severance for monthly wages assumes a daily rate of monthly wage / 30, which the Labour Protection Act does not define. `C19` assumes the ministry's compensation limits, which are not in the corpus, do not apply. `T09`, `T20`, the wage base in `T04`, `T05`, `T12`, `T18`, `C05`, `C06` and `C12`, and the Employee Welfare Fund figures in `T16`, `T17` and `C20` were read by eye from PDFs without usable text.

| Question type | Count | Purpose |
|---|---|---|
| General rights | 30 | Everyday questions |
| **Trap questions** | 20 | Outdated or draft answers are wrong (e.g. maternity leave 120 vs 98 days, annual leave 6 vs 10 days, SSO maximum 875 vs 750 baht) |
| Calculations | 18 | Severance, overtime, contributions |
| Out of scope | 18 | The corpus doesn't say, so the assistant must refuse: it doesn't know because the question is outside the scope of its content |
| Clarification | 8 | Key details are missing, so the assistant must ask for them instead of assuming |
| Correction | 6 | The question rests on a wrong belief, so the assistant must correct it |

| Eval | Metric | Baseline | Compared against |
|---|---|---|---|
| Retrieval | recall@k, MRR, nDCG | BM25 on raw text | BM25 + PyThaiNLP, embeddings, hybrid, reranked |
| Answers | Correctness (LLM-as-judge, checked against our labels), citation accuracy | Gemma with no retrieval | RAG + agent; trap questions reported separately |
| Calculations | Exact match on amounts | LLM does the arithmetic | `calculate` tool |
| Refusals | Correct refusals vs false refusals | No retrieval | RAG with a `min_score` floor; agent checking the content |
| Behaviour | Asking back: recall, over-asking, precision. Correcting: filled in, right content, false corrections | Gemma with no retrieval | RAG + agent, plus controls for the agent |

### Results

`python eval/run_answers.py baseline rag agent` writes each answer to `eval/results/`, and the summaries to `eval/results_answers.csv` and `eval/results_behaviour.csv`. It uses `gemma-4-E4B-it` at `temperature=0`. An interrupted run carries on from the saved answers, so delete those files to start again. The class proxy allows 200,000 tokens and 150 requests a minute per key. The client retries a 429 error up to 8 times. A question that still fails is logged to `eval/results/errors_<mode>.log` and skipped, and rerunning retries it.

| Measure, over all 100 questions | No retrieval | RAG | Agent |
|---|---:|---:|---:|
| Expected behaviour | 59/100 | 72/100 | **92/100** |
| Figures the question asks for, no outdated one | 7/58 | 30/58 | **52/58** |
| Supporting figures from the reference | 2/10 | **8/10** | **8/10** |
| Cites a gold section | 17/74 | 48/74 | **61/74** |
| LLM judge says correct (see below) | 13/74 | 41/74 | 65/74 |

| By question type | No retrieval | RAG | Agent |
|---|---:|---:|---:|
| Calculation: expected numbers | 2/18 | 2/18 | **18/18** |
| Trap: expected numbers | 1/18 | 7/18 | **15/18** |
| General: expected numbers | 3/20 | **19/20** | 17/20 |
| Out of scope: refused | 10/18 | **18/18** | 17/18 |

Asking back and correcting are measured in both directions, because recall alone rewards a system that always asks:

| Behaviour | No retrieval | RAG | Agent |
|---|---:|---:|---:|
| Asked back when details were missing (recall) | **7/8** | 2/8 | 5/8 |
| Asked back when not needed (over-asking) | 28/92 | **1/92** | 4/92 |
| Of the questions it asked back, how many needed it (precision) | 7/35 | 2/3 | 5/9 |
| Correction with the right content | 0/10 | 2/10 | **9/10** |
| Corrected when there was nothing to correct | 2/90 | 1/90 | **0/90** |

`eval/controls.jsonl` holds questions we added as checks for the agent, which do not count in the 100. It asked back on 0 of the 8 questions that give every detail, and corrected 0 of the 6 beliefs that are right.

**How to read these numbers**

- **Tuning used the same questions.** The prompts, the search set-up and the refusal rule were all adjusted on this set, so these scores may be optimistic. They need confirming on questions the system has not seen.
- **General questions still trail RAG on figures.** `G12` asks back for details it does not need, `G20` leaves out a figure, and `G30` is refused because the search misses its section. Shown only the section it quoted, the agent stopped answering from a neighbouring section: before that, a question about breaks on a night shift was answered with the night-work rule for children. Figures the question did not ask for, such as notice periods, are counted apart as supporting figures.
- **Asking back is still weak.** `A04` and `A07` answer instead of asking, and `A05` is refused because the check says the results do not cover it. `G12`, `O03`, `T11` and `T16` ask about details the answer does not need, and `O03`, an out-of-scope question, is answered after asking.
- **Some corrections fail.** `T15` does not state the right penalty, because its section is not found. The correction check reads the expected figures and key terms only.
- **The number check needs every figure the question asks for.** `expected_numbers` lists the figures that answer the question, and `supporting_numbers` the reference's other figures, such as notice periods. Both leave out dates, section numbers and the steps of a calculation. `wrong_numbers` lists outdated figures, which fail an answer unless it is correcting that belief. A calculated amount must also equal the expected one. One person labelled these from the reference answers, so where to draw the line is a judgement. The answer may still state other figures that are not labelled.
- **The LLM judge misses some missing figures.** It passes `T14` and `T15` for the agent, which leave out a required figure. The judge is the same model that wrote the answers, and it has not been checked against human labels.
- **Runs can vary despite `temperature=0`.** Two runs of an earlier version differed in 46 of 100 answer texts. A question near the edge of a check can change between runs: `O03` was answered in one recent run and refused in the next.
- **Time.** Six new questions through `POST /ask`, one at a time, took 20 to 41 seconds on CPU, of which about 21 seconds is reranking. In the full evaluation, a few questions took over 60 seconds, the longest 122. That may be the client waiting out the rate limit, which we did not confirm. Times in the CSV files are lower than real ones, because they reuse saved scores.
- **Earlier results.** `eval/results/min_score_*` holds answers from an earlier version of the agent, which relied on a `min_score` floor. Refusing from the content did better: 17/18 out-of-scope questions and 2/82 answerable ones refused, against 18/18 and 7/82 at the best floor. The option that produced them has been removed.

### Held-out check

The scores above come from the questions the system was tuned on. To check them, `eval/heldout.jsonl` holds 30 new questions, written from the statutes after tuning finished: 7 general, 5 trap, 5 calculation, 4 correction, 4 clarification and 5 out of scope. Each targets a known weak spot, such as a neighbouring section, a belief stated without "ใช่ไหม", or a broad question that needs asking back. The labels pass `python eval/check_questions.py eval/heldout.jsonl`.

The file was committed with its SHA-256 in `eval/heldout.lock` before any run, and `python eval/run_heldout.py` refuses to start if the file has changed. Nothing in the system was changed after seeing the results. The agent ran 3 times. Ranges are the lowest and highest of the 3 runs, and the interval is a 95% Wilson interval for the lower count:

| Measure | Held-out, 3 runs | 95% interval | Tuned set, agent |
|---|---:|---:|---:|
| Expected behaviour | 22-23/30 | 56-86% | 92/100 |
| Figures the question asks for, no outdated one | 11/18 | 39-80% | 52/58 |
| Cites a gold section | 12-14/21 | 37-76% | 61/74 |
| LLM judge says correct | 12-13/21 | 41-79% | 65/74 |

| By type, expected behaviour | Held-out, 3 runs |
|---|---:|
| General | 6/7 |
| Trap | 3-4/5 |
| Calculation | 5/5, but only 3/5 with the right amount |
| Correction | 2/4 |
| Clarification | 1/4 |
| Out of scope | 5/5 |

- **The tuned-set scores were optimistic.** Every measure is lower on unseen questions. The tuned set's own intervals are 85-96% for expected behaviour and 79-95% for figures, so the intervals only just touch. With 30 questions, each held-out interval is about 30 points wide, so the size of the drop is uncertain.
- **Runs barely varied.** 21 of 30 answer texts were identical in all 3 runs, and only 3 questions changed an outcome: `H01`, `H08` and `H17`. The variation between runs is much smaller than the gap to the tuned set. Retrieval is deterministic, so only the model varies between runs.
- **Refusals held up.** All 5 out-of-scope questions were refused in every run, and no answerable question was refused for being out of scope except `H08`.
- **Calculations fail when no tool kind fits.** `H17` asks for suspension pay, which `calculate` has no kind for. The model used the compensation kind instead and answered 420 baht, citing the Workmen's Compensation Act. `H15` asks for 2029 contributions, but `as_of` was not passed, so the 2026 ceiling gave 875 instead of 1,000 baht.
- **Answers from a neighbouring section persist.** In 2 of 3 runs, `H01` about women on night shifts was answered with the rule for pregnant employees.
- **Weak spots seen in tuning are confirmed.** Corrections were missed when the belief had no trigger word (`H18`, `H19`). `H21` was corrected from the wrong section. Asking back worked only where `get_rate` needed a district (`H22`), and `H05` and `H09` asked when it was not needed. `H08`, on pay for spouse-support leave, was refused in 2 runs and failed to produce an answer in the third. `H12` never found the 90-day maternity benefit.
- **Citations of rates do not count as gold.** `H10` and `H11` cite the rate announcement's clause, which has no law code, so they miss the labelled section even though the rate is right.

### Fixes, and a second held-out check

Commit `2ffbd32` made 7 changes aimed at the weak spots above:

- **A year in the question sets the date.** "ปี 2572" or "ตุลาคม 2574" is passed to `calculate` and `get_rate` as `as_of`, so a future contribution uses that year's ceiling.
- **Pay that is a share of the daily wage.** `calculate` has a `wage_share` kind for rules such as pay while suspended (s.116) or during a temporary closure (s.75). The percentage must be written in the section it cites, so the model cannot pair a rule with a figure from somewhere else.
- **Figures the user did not give are asked for.** A wage of 0 means not given. The agent then asks for it instead of guessing, but only when the question asks for an amount.
- **Beliefs without a trigger word.** A question that reports what someone said ("เพื่อนบอกว่า", "นายจ้างบอกว่า") is also checked for a wrong belief. The check must quote, word for word, the text that contradicts the belief.
- **Rules for a group the question does not mention are dropped.** A section written for pregnant employees, children, seafarers or a similar group is removed from the results unless the question mentions that group. An age under 18 counts as mentioning children.
- **Results that do not cover the question are dropped.** When a section answers the question, the answer no longer states a rate or calculation whose own check does not cover the question.
- **Rate citations count when labelled.** A citation of a rate announcement counts as gold when the question lists that announcement in `gold_sources`. This changes the scoring, not the system.

These changes were tuned on the 100 questions, the controls and the first held-out set, which is now development data. Before any fix was written, `eval/heldout2.jsonl` was committed with its lock in `dc4a859`. It holds 60 new questions:

- 14 general
- 10 trap
- 10 calculation
- 8 correction: 4 with a trigger word and 4 without
- 8 clarification
- 10 out of scope

The agent from before the fixes ran on it 3 times, from a separate checkout of that commit. Its scores were not read until the fixed agent had also run 3 times. Both are scored by the same code with `python eval/run_heldout.py --set=heldout2 --label=before`, or `--label=fixed`.

| Measure, 60 new questions | Before, 3 runs | 95% interval | After, 3 runs | 95% interval |
|---|---:|---:|---:|---:|
| Expected behaviour | 46/60 | 65-86% | 48-50/60 | 68-88% |
| Figures the question asks for, no outdated one | 22/31 | 53-84% | 25/31 | 64-91% |
| Cites a gold section | 34-35/42 | 67-90% | 35/42 | 69-92% |
| LLM judge says correct | 27-28/42 | 49-77% | 30-31/42 | 56-83% |

| By type | Before | After |
|---|---:|---:|
| General: expected behaviour | 12/14 | 12/14 |
| Trap: expected behaviour | 8/10 | 8/10 |
| Calculation: right amount | 5/10 | 7/10 |
| Correction: expected behaviour | 3/8 | 4-5/8 |
| Clarification: asked back | 5/8 | 5-6/8 |
| Out of scope: refused | 8/10 | 9/10 |
| Asked back when not needed | 2-3/52 | 3/52 |
| Corrected when there was nothing to correct | 0/52 | 0/52 |

The tuned set was run once with the fixed agent: `python eval/run_answers.py agent --out=eval/results/after_fixes`. The "before" column rescores the saved answers from the Results section with the current scoring. That is why its citations read 67/74 there, not 61/74.

| Measure, tuned set, 1 run each | Before | After |
|---|---:|---:|
| Expected behaviour | 92/100 | 90/100 |
| Figures the question asks for, no outdated one | 52/58 | 50/58 |
| Cites a gold section | 67/74 | 64/74 |
| LLM judge says correct | 65/74 | 62/74 |
| Asked back when not needed | 4/92 | 6/92 |
| Correction with the right content | 9/10 | 8/10 |

- **New questions gained a little, within the noise.** Each measure rose by 1 to 3 questions out of 60, but the intervals overlap almost entirely.
  - 6 questions improved in all 3 runs. `N17`, `N30` and `N31` give a year. `N35` reports a belief with "บอกว่า". `N50` now asks back, and `N56`, a freelance tax question, is now refused.
  - `N47` got worse. Before the fixes it asked for the province in all 3 runs. Now it is refused in 2 of them.
- **The new set was not fully blind.** I wrote the 60 questions knowing which fixes were planned. Three of the 6 gains need a year in the question, and the correction questions use the reported-speech words the fix looks for. The labels are one person's judgement.
- **The tuned set dropped slightly.** Each measure fell by 2 or 3 questions, from one run each. Some of the changes are the same in both sets:
  - A minimum-wage question with no province is refused instead of asked back (`A03`, `N47`).
  - `G16` and `G31` now ask how long the user has worked, which their answers do not need.
- **`wage_share` is not used yet.**
  - `N32` asks for pay during a temporary closure. The model did the arithmetic itself and answered 3,500 instead of 3,000 baht.
  - `N34` used the compensation kind for maternity pay, and the check that drops an unrelated calculation missed it.
- **Corrections without a trigger word still miss.** `N36` was refused. `N37` states the right rule without correcting the belief. `N38` answered from the wrong paragraph.
- **Asking back is still uneven.**
  - `N16` asks for the district, although it names Koh Samui.
  - `N09` and `N21` ask back when the law already answers them.
  - `N45` answers instead of asking.
  - `N49` refuses instead of asking for the wage.
- **Some answers were generated twice.** For part of the fixed runs, two copies of the runner wrote to the same files at once. Both ran the same code. The scoring keeps the last answer for each question.
- **These results were not used to change the system.** The next fixes, for the province refusal, the tenure questions and `wage_share`, need a new locked set to be measured.

### Asking back and calculations, and a third held-out check

The next round changed when the agent asks back and how it calculates. Each rule is meant to hold for any question, not for one set:

- **The law decides when a fact is missing, not the model.** The model's own ask step was removed, because it asked about things the answer did not need. Now the agent asks for a fact only when it finds all of these:
  - At least two sections in the results each answer the question alone.
  - Those sections give different answers.
  - Both sections are in the same Act.
  - The case each section covers is quoted word for word from the results.
- **Figures are asked for only when the rule that needs them covers the question.** A tool's missing input, such as the wage or the province, is asked for only when the check finds that the section or rate it belongs to covers the question. A question about another country's minimum wage no longer asks for a Thai province.
- **Code looks up what the question names.** For a minimum-wage question, code looks up the rate even if the model does not call `get_rate`. A place named in the question overrides the one the model passes. A province the table does not know is asked for instead of rejected. A question about the user's own social-security or provident-fund deduction that gives no wage asks for the wage.
- **Calculations follow the section that answers.** Suppose that section has a formula and the question gives figures, but the model did not calculate. Then one more call is made, with `calculate` as the only tool. Its result is kept only if its legal basis is that section. Formulas now show the daily rate.
- **Every number in an answer must have a source.** Each number must appear in the retrieved text, a tool result or the question. It may also be a single product, quotient or percentage of those numbers. Otherwise the answer is written again. If the retries fail, the answer is built from the tool results.

These changes were tuned on the 100 questions, the controls and both earlier held-out sets. Before any fix was written, `eval/heldout3.jsonl` and its lock were written. They hold 60 new questions, `P01` to `P60`, mostly on sections that no earlier set used:

- 14 general
- 10 trap
- 10 calculation
- 8 correction: 4 with a trigger word and 4 without
- 8 clarification
- 10 out of scope

The agent from `f0f10c3` ran on it 3 times, from a separate checkout. The changed agent then also ran 3 times. Both are scored by the same code with `python eval/run_heldout.py --set=heldout3 --label=before`, or `--label=fixed`.

| Measure, 60 new questions | Before, 3 runs | 95% interval | After, 3 runs | 95% interval |
|---|---:|---:|---:|---:|
| Expected behaviour | 48-51/60 | 68-92% | 50/60 | 72-91% |
| Figures the question asks for, no outdated one | 21/29 | 54-85% | 23-24/29 | 62-92% |
| Cites a gold section | 35-36/42 | 69-93% | 37-38/42 | 75-96% |
| LLM judge says correct | 33-34/42 | 64-90% | 37-38/42 | 75-96% |

| By type | Before | After |
|---|---:|---:|
| General: expected behaviour | 11-12/14 | 13-14/14 |
| Trap: expected behaviour | 9/10 | 9/10 |
| Calculation: right amount | 8-9/10 | 9/10 |
| Correction: expected behaviour | 3-5/8 | 4-5/8 |
| Clarification: asked back | 5/8 | 3/8 |
| Out of scope: refused | 10/10 | 10/10 |
| Asked back when not needed | 3-4/52 | 1-2/52 |
| Corrected when there was nothing to correct | 0/52 | 0/52 |

The tuned set was run once with the changed agent: `python eval/run_answers.py agent --out=eval/results/after_fixes2`. The comparison is the `after_fixes` run of `f0f10c3`.

| Measure, tuned set, 1 run each | Before | After |
|---|---:|---:|
| Expected behaviour | 90/100 | 94/100 |
| Figures the question asks for, no outdated one | 50/58 | 52/58 |
| Cites a gold section | 64/74 | 69/74 |
| LLM judge says correct | 62/74 | 62/74 |
| Asked back | 5/8 | 5/8 |
| Asked back when not needed | 6/92 | 1/92 |
| Correction with the right content | 8/10 | 7/10 |
| Control questions refused | 0/14 | 0/14 |

- **Over-asking fell, but so did needed asking.** On the new set, 3 questions stopped asking back when they should not: `P03`, `P11` and `P21`. They are now answered from the right section. `P47`, "ลางานได้ปีละกี่วัน", now asks which kind of leave. But 3 questions that should ask now answer instead:
  - `P43` asks for severance with no tenure or wage. `P45` asks for overtime pay with no wage. The model did not call `calculate`, so no tool reported a missing figure. The extra calculation runs only when the question has figures. These questions now get the rule without an amount. The tuned set has the same gap: `N44` and `A01`.
  - `P50` asks for the compensation rate for an injury, and the answer depends on whether the injury came from work. The two sections that differ are in two Acts, the Workmen's Compensation Act and the Social Security Act, and the agent does not ask across Acts.
- **One new over-ask.** `P22`, on travel time after work, now asks whether the travel was on a holiday. The three sections it found each answer the question, and the check reported a difference that the question did not need.
- **Minimum-wage figures improved.** `P16` names Chiang Mai's Mueang district. Code now looks up that district's rate and answers 380 baht, where the old agent answered 357. `P15` no longer adds the 400-baht rate for hotels and entertainment venues, which the label counts as the wrong figure for this question.
- **A wrong tool kind still gets through.** `P30` asks for holiday work pay. The model used the holiday-overtime kind, which gives 1,800 instead of 600 baht. The check found that section 63 also covers the question, so the result was kept. Before the change, the answer gave the rule without an amount.
- **The new set was not fully blind.**
  - I wrote the 60 questions knowing which fixes were planned.
  - While the old agent ran, its scores for `P11` and `P12` appeared in the log before the changed agent had run.
  - The labels are one person's judgement.
  - With 8 clarification questions, a 95% interval for 3/8 is 14-69%.
- **The measured code is commit `12fd6f3`.** All 6 runs on the new set used one version of the code. Its diff from `f0f10c3` has a SHA-256 starting `719e93d3c8515f30`, the same as that commit's.
- **These results were not used to change the system.** The next fix would ask for figures when the section that answers needs them and the question has none. It needs a new locked set to be measured.

### Asking for the figures a formula needs, and a fourth held-out check

One change followed. When a question asks for an amount and no calculation was made, the agent picks the section to calculate from:

- The section that answers, if it has a formula `calculate` knows or pays a share of the wage.
- Otherwise, the first section that covers the question with a formula `calculate` knows. Asked without figures, the check often found that no section answers, as in `P43` and `P45`.

Then:

- **The question gives figures.** The model calculates once more from that section alone, and the agent asks for what `calculate` reports missing.
- **The question gives none.** Code calls `calculate` for that section's formula with no figures, and asks for what it reports missing. The model cannot guess a figure.
- **No figures are asked for in these cases:**
  - The section only pays a share of the wage, such as sick-leave pay. It answers with its rule.
  - The question asks for a rate or a ceiling, with a word such as "อัตรา" or "สูงสุด".

The change was tuned on the 100 questions, the controls and the three earlier held-out sets. On the 100 questions it gave:

- **Expected behaviour:** 94/100 before, 95/100 after.
- **Asked back:** 5/8 before, 6/8 after.
- **Asked back when not needed:** 1/92 in both. It is now `G12`, a question about the monthly compensation rate.

Before the change was written, `eval/heldout4.jsonl` and its lock were written. They hold 48 money questions, `Q01` to `Q48`:

- 14 clarification: an amount without some or all of the figures its formula needs
- 12 general: an amount the law states without the user's figures, such as a ceiling or a share of the wage
- 10 calculation: every figure given
- 6 general questions that are not about an amount
- 6 out of scope, asking for an amount

The code from the previous section ran on it 3 times, from a separate checkout. The changed agent then also ran 3 times. Both are scored with `python eval/run_heldout.py --set=heldout4 --label=before`, or `--label=fixed`.

| Measure, 48 new questions | Before, 3 runs | 95% interval | After, 3 runs | 95% interval |
|---|---:|---:|---:|---:|
| Expected behaviour | 45/48 | 83-98% | 44-45/48 | 80-98% |
| Figures the question asks for, no outdated one | 25/26 | 81-99% | 22/26 | 66-94% |
| Cites a gold section | 27-28/28 | 82-100% | 25/28 | 73-96% |
| LLM judge says correct | 26-27/28 | 77-99% | 24/28 | 69-94% |
| Asked back when it should | 11/14 | 52-92% | 13-14/14 | 69-100% |
| Asked back when not needed | 0/34 | 0-10% | 3/34 | 3-23% |

- **Asking for missing figures works.**
  - `Q01` (severance) and `Q06` (overtime) gave no figures. They now ask in all 3 runs.
  - `Q08` gave the hours but not the wage. It now asks in 2 of 3 runs. In the third, the check found no section covering the question, so it was refused.
- **It costs as many questions as it gains.** Three questions now ask for figures that their answer does not need:
  - `Q16` asks for the cap on special severance, "รวมแล้วได้ไม่เกินเท่าไร".
  - `Q17` asks for the holiday-overtime multiple, "เมื่อเทียบกับค่าจ้างต่อชั่วโมง".
  - `Q20` asks for the compensation rate as a share of the wage, "คิดเป็นเท่าไรของค่าจ้าง".

  All three ask "how much" without figures, and their section has a formula. The rule cannot tell them from "how much will I get". On the tuned set, `G12` failed the same way. That is why the figure, citation and judge scores fell: those questions now ask instead of answering.
- **A wrong formula still gets through.** `Q32` asks for holiday work pay. In every run, before and after, the model used the holiday-overtime kind and answered 1,620 instead of 540 baht. `P30` failed the same way. This change does not address it.
- **The new set was not fully blind.**
  - I wrote the 48 questions knowing the planned change. `Q15` to `Q26` were written to test for over-asking.
  - While the old agent ran, its scores for `Q26` and `Q27` appeared in a log. The changed code had already been frozen.
  - The labels are one person's judgement.
- **The measured code is commit `36d5e65`.** All 3 changed runs used one version. Its diff from `f0f10c3` has a SHA-256 starting `2ba927151803745a`, the same as that commit's.
- **These results were not used to change the system.**

## Project structure

```
.
├── data/
│   ├── manifest.csv          # source list: url, dates, status, sha256
│   ├── raw/                  # archived source files (PDF and PNG)
│   ├── processed/            # section-level chunks with metadata (JSONL)
│   └── rates.csv             # versioned official rates for get_rate
├── scripts/
│   ├── fetch_corpus.py       # verify sha256, download missing sources
│   ├── build_chunks.py       # PDF → text → sections → chunks
│   └── build_index.py        # chunks → embedding index
├── src/
│   ├── retrieval/            # BM25, embeddings, hybrid, reranking, metrics
│   ├── agent/                # agent, its decision steps and tools
│   ├── schemas.py            # Pydantic models
│   ├── answer.py             # validate the model's JSON, retry on errors
│   ├── rag.py                # plain RAG, the comparison for the agent
│   ├── llm.py                # the one place that calls the model
│   └── api/                  # FastAPI app
├── eval/
│   ├── questions.jsonl       # labelled test set
│   ├── run_retrieval.py      # Eval 1: every retrieval variant
│   ├── sweep_min_score.py    # chooses the refusal floor
│   ├── run_answers.py        # Evals 2-4: baseline, RAG, agent
│   ├── controls.jsonl        # questions the agent should not ask about or correct
│   ├── heldout.jsonl         # 30 locked questions written after tuning
│   ├── heldout2.jsonl        # 60 locked questions written before the fixes
│   ├── heldout3.jsonl        # 60 locked questions written before the asking-back changes
│   ├── heldout4.jsonl        # 48 locked money questions written before the figures change
│   ├── run_heldout.py        # runs them several times and reports ranges
│   └── results/              # every saved answer
├── requirements.txt          # pinned Python dependencies
└── README.md
```

## Getting started

### 1. Get the code and verify the corpus

```bash
git clone https://github.com/ritsupaintblu/Thai_labour_rights_assistant_for_first_jobber.git
cd Thai_labour_rights_assistant_for_first_jobber
python scripts/fetch_corpus.py
```

### 2. Install and build the chunks

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
python scripts/build_chunks.py
```

To refresh the progress report `read/Update.pdf` after every commit, turn on the hook once per clone with `git config core.hooksPath .githooks`. The PDF is not committed.

### 3. Configure

The API key and base URL are read from the environment, or from a local `.env` file, which git ignores:

```bash
export OPENAI_API_KEY=...        # Windows PowerShell: $env:OPENAI_API_KEY="..."
export OPENAI_BASE_URL=...
```

### 4. Build the index

```bash
python scripts/build_index.py
```

### 5. Run the API

```bash
uvicorn src.api.main:app
```

Startup loads both models, and the first run downloads the reranker. A new question took 20 to 41 seconds on CPU in our test, mostly reranking. Scores are saved in `data/index/`, so a repeated question is much faster.

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "ลาป่วยได้กี่วันโดยได้รับค่าจ้าง"}'
```

### 6. Reproduce the evaluation

```bash
python eval/run_retrieval.py
python eval/sweep_min_score.py
python eval/run_answers.py baseline rag agent
python eval/run_heldout.py                    # first held-out set, 3 runs
python eval/run_heldout.py --set=heldout2 --label=fixed
python eval/run_heldout.py --set=heldout3 --label=fixed
python eval/run_heldout.py --set=heldout4 --label=fixed
```

## Limitations

- **Frozen corpus.** Answers reflect the law as of 1 November 2026. Changes after that date are not included. For example, the 2027 minimum wage was still undecided at that date.
- **Small model.** `gemma-4-E4B-it` may pick the wrong tool or misread multi-section questions. Each decision is kept in the answer's trace in `eval/results/` for failure analysis.
- **Small, single-labeller eval set.** 100 questions labelled by one person, so results will indicate direction rather than precise accuracy.
- **No interpretation.** The assistant reports what the statute says. It does not cover court rulings, company policies or employment contracts that give more than the legal minimum.

## Future work

- Add Supreme Court labour rulings for interpretation questions
- Watch the Royal Gazette for amendments and update `manifest.csv` automatically
- Cover the Labour Relations Act
- Expand the eval set with a second labeller and report agreement

## Sources

- Royal Gazette (ราชกิจจานุเบกษา): https://ratchakitcha.soc.go.th
- Department of Labour Protection and Welfare, legal division: https://legal.labour.go.th
- Ministry of Labour: https://www.mol.go.th
- Office of the Council of State, law search: https://www.ocs.go.th
- Social Security Office: https://www.sso.go.th
