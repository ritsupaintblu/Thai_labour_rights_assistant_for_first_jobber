# Thai Labour-Rights Assistant for First Jobbers

An LLM-powered assistant that answers questions about Thai employee rights, using the laws that are **actually in force**, with section citations and effective dates. Money questions such as severance, overtime and social-security contributions are calculated in Python, not by the model.

> **Not legal advice.** This is an information tool built as a course capstone. Corpus is frozen **as of 1 November 2026 (B.E. 2569)**. Check the official text or the Department of Labour Protection and Welfare (hotline 1546) before acting.

---

## The problem

New employees often don't know their basic rights: probation, sick leave, maternity leave, overtime pay, severance, and social-security deductions. Three things make this harder than it should be:

1. **The law is long and formal.** The Labour Protection Act B.E. 2541 has been amended nine times.
2. **Much online information is outdated.** Many "full text" copies online stop before Amendment No. 9 (in force 7 Dec 2025), which raised maternity leave from 98 to 120 days.
3. **General LLMs answer confidently and wrongly.** They repeat old figures, and they treat draft bills as law, such as "10 days' annual leave," which is still only a proposal.

This assistant answers only from in-force legal text. It cites the section and the date it took effect. When the law doesn't cover a question, it says so instead of guessing.

## What it does

Ask a question in Thai or English, for example:

- "ลาคลอดได้กี่วัน ได้รับค่าจ้างกี่วัน" (How many days of maternity leave, and how many are paid?)
- "ทำงานมา 3 ปี 2 เดือน เงินเดือน 25,000 ถูกเลิกจ้าง ได้ค่าชดเชยเท่าไร" (Worked 3 years 2 months on 25,000 baht/month and got laid off. How much severance?)
- "เงินเดือน 20,000 ถูกหักประกันสังคมเดือนละเท่าไร" (How much social security is deducted from a 20,000 baht salary?)

You get back a validated JSON answer:

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

## How it works

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

- **Section-level chunks with legal metadata.** Each chunk is one section (มาตรา) tagged with `law`, `section`, `amendment_no`, `effective_date` and `status` (`in_force`, `superseded`, `draft`). Retrieval returns only `in_force` text.
- **Thai-aware retrieval.** Thai has no spaces between words, so naive BM25 performs poorly. We compare raw BM25, BM25 with PyThaiNLP word segmentation, embeddings, and hybrid search.
- **A `min_score` floor.** If nothing relevant is retrieved, the assistant answers "not found in the law" instead of guessing. The threshold is chosen from a sweep on the eval set, not by hand.
- **Calculations in code.** Small models are unreliable at arithmetic, so all money is computed by deterministic, input-checked Python functions.
- **Safe tool use.** Tools are allow-listed. Arguments are validated before running. Retrieved text and tool results are treated as data, never as instructions.

## Course capability coverage

| Capability family | Where it appears |
|---|---|
| Structured output with validation | Pydantic answer schema, retry on invalid JSON |
| Retrieval / RAG | Section-level index, cited answers |
| Retrieval evaluation | recall@k and MRR on a labelled question set |
| Agent loop with tools *(agentic)* | `search_law`, `calculate`, `get_rate`, stop condition |
| Advanced capability *(agentic)* | Sandboxed code execution for calculations |
| Served interface | FastAPI `POST /ask` (SSE streaming optional) |

## Corpus

All sources are official Thai government publications, mainly from the Royal Gazette (ราชกิจจานุเบกษา). Thai statutes and official announcements are not protected by copyright, so raw files can be committed.

| Source | Why it's needed |
|---|---|
| Labour Protection Act B.E. 2541 (latest consolidated text) | Core employee rights |
| Labour Protection Act (No. 8) B.E. 2566 | Work-from-home / off-site work (Section 23/1) |
| Labour Protection Act (No. 9) B.E. 2568 | 120-day maternity leave, infant-care leave, spouse-support leave (in force 7 Dec 2025) |
| Social Security Act B.E. 2533 (latest consolidated text) | Contributions and benefits |
| Ministerial Regulation on the Section 33 wage base, B.E. 2568 | Contribution ceiling of 17,500 baht from 1 Jan 2026 |
| Wage Committee Announcements on minimum wage (No. 13, No. 14) | 337–400 baht/day by province |
| Royal Decree on Employee Welfare Fund collection, B.E. 2569 | Collection starts 1 Jan 2027 |

Every file is listed in `data/manifest.csv` with its URL, publication date, effective date, status and SHA-256 hash. Draft bills are stored separately and used **only** as trap questions, never as answers.

## Evaluation

The evaluation set lives in `eval/questions.jsonl`. It has about 30 hand-labelled questions plus 5 out-of-scope questions, each labelled with the correct section(s), reference answer and expected number.

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

*To be filled in from `python eval/run.py`. Every number is reproducible from this repo.*

| Eval | Baseline | This system |
|---|---|---|
| Retrieval recall@5 | – | – |
| Trap questions correct (/10) | – | – |
| Calculation exact match (/6) | – | – |
| Out-of-scope handled (/5) | – | – |

## Project structure

```
.
├── data/
│   ├── manifest.csv          # source list: url, dates, status, sha256
│   ├── raw/                  # original Royal Gazette PDFs
│   ├── processed/            # section-level chunks with metadata (JSONL)
│   └── rates.csv             # versioned official rates for get_rate
├── scripts/
│   ├── fetch_corpus.py       # download sources and verify sha256
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

### 1. Install

```bash
git clone <repo-url>
cd thai-labour-rights-assistant
python -m venv .venv
source .venv/bin/activate        # Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

### 2. Configure

The API key and base URL are read from the environment, never committed:

```bash
export OPENAI_API_KEY=...        # Windows PowerShell: $env:OPENAI_API_KEY="..."
export OPENAI_BASE_URL=...
```

### 3. Get the corpus and build the index

```bash
python scripts/fetch_corpus.py   # downloads files listed in data/manifest.csv, checks sha256
python scripts/build_index.py
```

`manifest.csv` is read with `encoding="utf-8-sig"`, so it works even when saved from Excel (which adds a BOM).

### 4. Run the API

```bash
uvicorn src.api.main:app --reload
```

```bash
curl -X POST http://localhost:8000/ask \
  -H "Content-Type: application/json" \
  -d '{"question": "ลาป่วยได้กี่วันโดยได้รับค่าจ้าง"}'
```

### 5. Reproduce the evaluation

```bash
python eval/run.py
```

## Limitations

- **Frozen corpus.** Answers reflect the law as of 1 November 2026. Changes after that date are not included. For example, the 2027 minimum wage was still undecided at that date.
- **Small model.** `gemma-4-E4B-it` sometimes picks the wrong tool or misreads multi-section questions. Tool calls are logged for failure analysis.
- **Small, single-labeller eval set.** About 30 questions labelled by one person, so results indicate direction rather than precise accuracy.
- **No interpretation.** The assistant reports what the statute says. It does not cover court rulings, company policies or employment contracts that give more than the legal minimum.

## Future work

- Add Supreme Court labour rulings for interpretation questions
- Watch the Royal Gazette for amendments and update `manifest.csv` automatically
- Cover the Labour Relations Act and Workmen's Compensation Act
- Expand the eval set with a second labeller and report agreement

## Sources

- Royal Gazette (ราชกิจจานุเบกษา): https://ratchakitcha.soc.go.th
- Department of Labour Protection and Welfare, legal division: https://legal.labour.go.th
- Office of the Council of State, law search: https://www.ocs.go.th
- Social Security Office: https://www.sso.go.th
