# Thai Labour-Rights Assistant for First Jobbers

An LLM-powered assistant that answers questions about Thai employee rights, using the laws that are **actually in force**, with section citations and effective dates. Money questions such as severance, overtime and social-security contributions are calculated in Python, not by the model.

> **Not legal advice.** This is an information tool built as a course capstone. Corpus is frozen **as of 1 November 2026 (B.E. 2569)**. Check the official text or the Department of Labour Protection and Welfare (hotline 1546) before acting.

## Project status

This project is in progress. Only the corpus is built so far. The sections below describe the intended design unless they say otherwise.

| Part | Status |
|---|---|
| Corpus files and `data/manifest.csv` | Done |
| `scripts/fetch_corpus.py` | Done |
| Section-level chunks and index | Planned |
| Retrieval, agent loop and tools | Planned |
| FastAPI service | Planned |
| Evaluation set and results | Planned |

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
    {"law": "LPA2541", "section": "41", "amendment_no": 9, "effective_date": "2025-12-07"}
  ],
  "calculation": null,
  "as_of": "2026-11-01",
  "confidence": "high",
  "not_found": false
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
   └── get_rate(name, as_of)   → official rates from a versioned CSV
   │
   ▼
Pydantic-validated JSON answer with citations + as_of date
```

### Key design choices

- **Section-level chunks with legal metadata.** Each chunk is one section (มาตรา) tagged with `law`, `section`, `amendment_no`, `effective_date` and `status`. Retrieval returns only `in_force` text.
- **Thai-aware retrieval.** Thai has no spaces between words, so naive BM25 performs poorly. We compare raw BM25, BM25 with PyThaiNLP word segmentation, embeddings, and hybrid search.
- **A `min_score` floor.** If nothing relevant is retrieved, the assistant answers "not found in the law" instead of guessing. The threshold is chosen from a sweep on the eval set, not by hand.
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
| Workmen's Compensation Act B.E. 2537: consolidated text and Amendment No. 2 | 2 | Compensation for work-related injury |
| Wage Committee Announcement on minimum wage (No. 14) | 1 | Minimum wage by province |
| Employee Welfare Fund: Ministerial Regulation on rates, B.E. 2568, and Royal Decree on collection, B.E. 2569 | 2 | Collection starts 1 Jan 2027 |
| Employee Welfare Fund: Q&A documents and web articles | 6 | Explanatory material, not law |
| Employment and Job-Seekers Protection Act B.E. 2528: consolidated text and Amendments No. 2–3 | 3 | Job seekers and recruitment |
| Other laws: fishing labour, state enterprise labour relations, home workers, foreign workers, maritime labour, and persons with disabilities (Act and Amendment No. 2) | 7 | Groups covered by separate laws |

### Manifest

Every file is listed in `data/manifest.csv` with its URL, publication date, effective date, status and SHA-256 hash. When a law changes, add a row for the new version and mark the old row `superseded`.

| `status` | Rows |
|---|---:|
| `in_force` | 28 |
| `superseded` | 3 |
| `secondary` | 3 |
| `repealed_check` | 1 |

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

Use the files in `data/raw/` as the corpus. A check on 2026-11-01, with the local files present and then with an empty folder, gave these results:

- **With the archived files:** 35 of 35 verified.
- **Downloading from the URLs:** 16 of 35 verified.

The 19 rows that did not verify from their URLs:

| Rows | Result | Reason |
|---|---|---|
| `fishing_labour`, `soe_labour`, `home_work`, `ssa_consolidated`, `ssa_no2`, `ssa_no3`, `ssa_no4`, `wca_consolidated`, `min_wage_no14`, `emp_no2`, `emp_no3`, `foreign_workers`, `maritime_labour`, `disability`, `disability_no2` | `NOT A DOCUMENT` | `mol.go.th` serves a bot-protection page to scripts instead of the PDF. |
| `ewf_info1`, `ewf_info2`, `ewf_info3` | `NOT A DOCUMENT` | The sources are web articles, archived as PNG screenshots. The manifest holds the screenshot's hash, so a download can never match. The URL only records where the content came from. |
| `wca_no2` | `DOWNLOAD FAILED` | `www.ratchakitcha.soc.go.th` returns HTTP 403. |

**TLS.** The script uses `curl` because Python rejected the certificates from several `.go.th` servers. Certificate checks stay on. This was tested on Windows; `curl` on other systems may still report `DOWNLOAD FAILED` for those servers.

## Evaluation

*Planned.* The evaluation set will live in `eval/questions.jsonl`. It will have about 30 hand-labelled questions plus 5 out-of-scope questions, each labelled with the correct section(s), reference answer and expected number.

| Question type | Count | Purpose |
|---|---|---|
| General rights | 14 | Everyday questions |
| **Trap questions** | 10 | Outdated or draft answers are wrong (e.g. maternity leave 120 vs 98 days, annual leave 6 vs 10 days, SSO maximum 875 vs 750 baht) |
| Calculations | 6 | Severance, overtime, contributions |
| Out of scope | 5 | The law doesn't say, so the assistant must answer "not found" |

| Eval | Metric | Baseline | Compared against |
|---|---|---|---|
| Retrieval | recall@5, MRR | BM25 on raw text | BM25 + PyThaiNLP, embeddings, hybrid |
| Answers | Correctness (LLM-as-judge, checked against our labels), citation accuracy | Gemma with no retrieval | RAG + agent; trap questions reported separately |
| Calculations | Exact match on amounts | LLM does the arithmetic | `calculate` tool |
| Refusals | Correct "not found" vs false refusals | No `min_score` | `min_score` sweep |

### Results

*To be filled in from `python eval/run.py`. Every number will be reproducible from this repo.*

| Eval | Baseline | This system |
|---|---|---|
| Retrieval recall@5 | – | – |
| Trap questions correct (/10) | – | – |
| Calculation exact match (/6) | – | – |
| Out-of-scope handled (/5) | – | – |

## Project structure

Only `data/manifest.csv`, `data/raw/`, `scripts/fetch_corpus.py` and this README exist so far. Everything else is planned.

```
.
├── data/
│   ├── manifest.csv          # source list: url, dates, status, sha256
│   ├── raw/                  # archived source files (PDF and PNG)
│   ├── processed/            # section-level chunks with metadata (JSONL)
│   └── rates.csv             # versioned official rates for get_rate
├── scripts/
│   ├── fetch_corpus.py       # verify sha256, download missing sources
│   └── build_index.py        # PDF → text → sections → index
├── src/
│   ├── retrieval/            # BM25, embeddings, hybrid, min_score
│   ├── agent/                # agent loop and tools
│   ├── schemas.py            # Pydantic models
│   └── api/                  # FastAPI app
├── eval/
│   ├── questions.jsonl       # labelled test set
│   ├── run.py                # runs all evals and baselines
│   └── results/              # CSV outputs
└── README.md
```

## Getting started

Only cloning and verifying the corpus work today. The remaining steps show how the finished project will run.

### 1. Get the code and verify the corpus

```bash
git clone https://github.com/ritsupaintblu/Thai_labour_rights_assistant_for_first_jobber.git
cd Thai_labour_rights_assistant_for_first_jobber
python scripts/fetch_corpus.py
```

### 2. Install (planned)

```bash
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

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
- **Small, single-labeller eval set.** About 30 questions labelled by one person, so results will indicate direction rather than precise accuracy.
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
