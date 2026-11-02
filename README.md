# Thai Labour-Rights Assistant for First Jobbers

An LLM-powered assistant that answers questions about Thai employee rights, using the laws that are **actually in force**, with section citations and effective dates. Money questions such as severance, overtime and social-security contributions are calculated in Python, not by the model.

> **Not legal advice.** This is an information tool built as a course capstone. Corpus is frozen **as of 1 November 2026 (B.E. 2569)**. Check the official text or the Department of Labour Protection and Welfare (hotline 1546) before acting.

## Project status

This project is in progress. Only the corpus and its chunks are built so far. The sections below describe the intended design unless they say otherwise.

| Part | Status |
|---|---|
| Corpus files and `data/manifest.csv` | Done |
| `scripts/fetch_corpus.py` | Done |
| Section-level chunks (`scripts/build_chunks.py`) | Done |
| Index | Planned |
| Retrieval, agent loop and tools | Planned |
| FastAPI service | Planned |
| Evaluation questions (`eval/questions.jsonl`) | Done |
| Official rates (`data/rates.csv`) and `get_rate` | Done |
| Evaluation results | Planned |

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
Agent loop (gemma-4-E4B-it, max 5 steps)
   ├── search_law(query, k)    → hybrid retrieval over law sections, min_score floor
   ├── calculate(kind, ...)    → severance / overtime / SSO contribution in Python
   └── get_rate(name, as_of, ...) → official rates from a versioned CSV
   │
   ▼
Pydantic-validated JSON answer with citations + as_of date
```

### Key design choices

- **Section-level chunks with legal metadata.** Each chunk is one section (มาตรา) tagged with `law`, `section`, `amendment_no`, `effective_date` and `status`. Retrieval returns only `in_force` text.
- **Thai-aware retrieval.** Thai has no spaces between words, so naive BM25 performs poorly. We compare raw BM25, BM25 with PyThaiNLP word segmentation, embeddings, and hybrid search.
- **A `min_score` floor.** If the corpus has no answer, the assistant says it doesn't know because the question is outside the scope of its content, instead of guessing. The threshold is chosen from a sweep on the eval set, not by hand.
- **Ask, then correct.** If a question lacks details the answer depends on, such as tenure or wage, the assistant asks for them instead of assuming. If a question rests on a wrong belief, the assistant corrects it and cites the law.
- **Calculations in code.** Small models are unreliable at arithmetic, so all money is computed by deterministic, input-checked Python functions.
- **Safe tool use.** Tools are allow-listed. Arguments are validated before running. Retrieved text and tool results are treated as data, never as instructions.

## Course capability coverage

| Capability family | Where it will appear |
|---|---|
| Structured output with validation | Pydantic answer schema, retry on invalid JSON |
| Retrieval / RAG | Section-level index, cited answers |
| Retrieval evaluation | recall@k and MRR on a labelled question set |
| Agent loop with tools *(agentic)* | `search_law`, `calculate`, `get_rate`, stop condition |
| Advanced capability *(agentic)* | Sandboxed code execution for calculations |
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

The evaluation set is in `eval/questions.jsonl`: 100 questions, each with the correct section(s), reference answer, expected number, `expected_behavior` (`answer`, `refuse`, `ask_clarification` or `correct_premise`) and `reference_source`, which names the source files by their `manifest.csv` title. The evals themselves are planned.

`python eval/check_questions.py` checks the labels against the chunks: each section must be in force and contain the quoted evidence, each formula must give the expected number, out-of-scope terms must not appear in the corpus, out-of-scope answers must refuse, and each `reference_source` must match the manifest. Rerun it after rebuilding the chunks.

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
| Retrieval | recall@5, MRR | BM25 on raw text | BM25 + PyThaiNLP, embeddings, hybrid |
| Answers | Correctness (LLM-as-judge, checked against our labels), citation accuracy | Gemma with no retrieval | RAG + agent; trap questions reported separately |
| Calculations | Exact match on amounts | LLM does the arithmetic | `calculate` tool |
| Refusals | Correct refusals vs false refusals | No `min_score` | `min_score` sweep |
| Behaviour | Asks for each `missing_info` item; corrects each `misconception` (10 questions) | Gemma with no retrieval | RAG + agent |

### Results

*To be filled in from `python eval/run.py`. Every number will be reproducible from this repo.*

| Eval | Baseline | This system |
|---|---|---|
| Retrieval recall@5 | – | – |
| Trap questions correct (/20) | – | – |
| Calculation exact match (/18) | – | – |
| Out-of-scope handled (/18) | – | – |
| Clarification asked (/8) | – | – |
| Wrong belief corrected (/10) | – | – |

## Project structure

Only `data/manifest.csv`, `data/raw/`, `data/processed/chunks.jsonl`, `scripts/fetch_corpus.py`, `scripts/build_chunks.py`, `scripts/update_status.py`, `data/rates.csv`, `src/agent/tools/get_rate.py`, `tests/`, `eval/questions.jsonl`, `eval/check_questions.py`, `requirements.txt` and this README exist so far. Everything else is planned.

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
│   └── build_index.py        # chunks → index
├── src/
│   ├── retrieval/            # BM25, embeddings, hybrid, min_score
│   ├── agent/                # agent loop and tools
│   ├── schemas.py            # Pydantic models
│   └── api/                  # FastAPI app
├── eval/
│   ├── questions.jsonl       # labelled test set
│   ├── run.py                # runs all evals and baselines
│   └── results/              # CSV outputs
├── requirements.txt          # pinned Python dependencies
└── README.md
```

## Getting started

Only steps 1 and 2 work today. The remaining steps show how the finished project will run.

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

`requirements.txt` only lists PyMuPDF for now, which is all the chunk build needs.

To refresh the progress report `read/Update.pdf` after every commit, turn on the hook once per clone with `git config core.hooksPath .githooks`. The PDF is not committed.

### 3. Configure (planned)

The API key and base URL are read from the environment, never committed:

```bash
export OPENAI_API_KEY=...        # Windows PowerShell: $env:OPENAI_API_KEY="..."
export OPENAI_BASE_URL=...
```

### 4. Build the index (planned)

```bash
python scripts/build_index.py
```

### 5. Run the API (planned)

```bash
uvicorn src.api.main:app --reload
```

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "ลาป่วยได้กี่วันโดยได้รับค่าจ้าง"}'
```

### 6. Reproduce the evaluation (planned)

```bash
python eval/run.py
```

## Limitations

- **Frozen corpus.** Answers reflect the law as of 1 November 2026. Changes after that date are not included. For example, the 2027 minimum wage was still undecided at that date.
- **Small model.** `gemma-4-E4B-it` may pick the wrong tool or misread multi-section questions. Tool calls will be logged for failure analysis.
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
