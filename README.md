# Thai Labour-Rights Assistant for First Jobbers

Answers questions about Thai employee rights from the laws **in force**, citing the section and its effective date. Money (severance, overtime, social security) is calculated in Python, not by the model.

> **Not legal advice.** Course capstone. Corpus frozen at **1 November 2026**. Check the official text or call the Department of Labour Protection and Welfare (1546) before acting.

## Example

`POST /ask` with `{"question": "ลาคลอดได้กี่วัน ได้รับค่าจ้างกี่วัน"}` returns:

```json
{
  "answer": "ลาคลอดได้ไม่เกิน 120 วันต่อการตั้งครรภ์ นายจ้างจ่ายค่าจ้างไม่เกิน 60 วัน",
  "citations": [{"law": "LPA2541", "section": "41", "amendment_no": 9, "effective_date": "2025-12-07"}],
  "as_of": "2026-11-01",
  "confidence": "high",
  "not_found": false,
  "clarifying_question": null,
  "correction": null
}
```

## How it works

```
question → FastAPI POST /ask → agent (gemma-4-E4B-it)
  ├── search_law  reranked hybrid search over section-level chunks
  ├── calculate   severance / overtime / SSO contribution in Python
  └── get_rate    official rates from data/rates.csv by date
→ Pydantic-validated JSON with citations
```

- **One chunk per section**, tagged with law, section, amendment and effective date. Only `in_force` text is searched.
- **Thai-aware retrieval:** BM25 + PyThaiNLP and `BAAI/bge-m3` embeddings, fused, then reranked by `BAAI/bge-reranker-v2-m3`. The question is also rewritten in statute wording.
- **Refuses from the content, not a score:** if the model can't quote a sentence from the results that answers the question, it says it doesn't know.
- **Asks back or corrects** when details are missing or the question rests on a wrong belief.
- **Every number must have a source:** the retrieved text, a tool result or the question.

## Corpus

37 official files in `data/raw/`, listed in `data/manifest.csv` with URL, dates, status and SHA-256: the Labour Protection Act and Amendments 2–9, the Social Security Act, the Workmen's Compensation Act, minimum wage, the Employee Welfare Fund, and related laws. `python scripts/fetch_corpus.py` verifies the hashes and downloads missing files (several government sites block scripts, so use the archived files).

## Results

Retrieval, 82 questions with gold sections:

| Variant | recall@5 | MRR |
|---|---:|---:|
| BM25, raw text | 0.018 | 0.015 |
| BM25 + PyThaiNLP | 0.504 | 0.357 |
| Embeddings | 0.764 | 0.683 |
| Reranked, both wordings (used by the agent) | **0.900** | **0.797** |

Answers, 100 labelled questions (`eval/questions.jsonl`):

| Measure | No retrieval | RAG | Agent |
|---|---:|---:|---:|
| Expected behaviour | 59/100 | 72/100 | **92/100** |
| Right figures, none outdated | 7/58 | 30/58 | **52/58** |
| Calculations correct | 2/18 | 2/18 | **18/18** |
| Cites a gold section | 17/74 | 48/74 | **61/74** |

The system was tuned on these 100 questions, so it was also checked on five locked held-out sets written later. On the latest (44 questions, 3 runs) the agent gave the expected behaviour on 41–42/44 and cited a gold section on 29–30/32. Details are in `eval/results/` and the commit history.

## Getting started

Developed on Python 3.13.2; `requirements.txt` was installed with that version.

```bash
python -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -r requirements.txt

python scripts/fetch_corpus.py     # verify the corpus
python scripts/build_chunks.py     # → data/processed/chunks.jsonl
python scripts/build_index.py      # → data/index/ (downloads a 4.3 GB model)
```

The model is `gemma-4-E4B-it`, called through any OpenAI-compatible server. Copy `.env.example` to `.env` and fill in `OPENAI_API_KEY` and `OPENAI_BASE_URL` (or set them in the environment), then:

```bash
uvicorn src.api.main:app
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question": "ลาป่วยได้กี่วันโดยได้รับค่าจ้าง"}'
```

On Windows PowerShell, use this instead of `curl`, or open http://localhost:8000/docs and try `/ask` from the browser:

```powershell
Invoke-RestMethod -Method Post -Uri http://localhost:8000/ask -ContentType "application/json; charset=utf-8" `
  -Body '{"question": "ลาป่วยได้กี่วันโดยได้รับค่าจ้าง"}'
```

A new question takes about 20–40 seconds on CPU, mostly reranking.

Tests: `python -m unittest discover -s tests -t .`
Evaluation: `python eval/run_retrieval.py`, `python eval/run_answers.py baseline rag agent`, `python eval/run_heldout.py --set=heldout5 --label=fixed`

## Project structure

```
data/      manifest.csv, raw/ sources, processed/ chunks, rates.csv
scripts/   fetch_corpus, build_chunks, build_index
src/       retrieval/, agent/ (loop and tools), api/, schemas.py, rag.py, llm.py
eval/      questions, held-out sets, runners, results/
tests/
read/      write-up of each stage: corpus, build_chunks, rates, retrieval, agent, evaluation, heldout
```

## Limitations

- Law changes after 1 November 2026 are not included.
- A small model can still pick the wrong formula or miss a condition.
- One person wrote and labelled the evaluation questions.
- Statute text only: no court rulings, contracts or company policies.
