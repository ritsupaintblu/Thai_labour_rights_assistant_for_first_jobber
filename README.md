# Thai Labour-Rights Assistant for First Jobbers

Answers questions about Thai employee rights from the laws **in force**, citing the section and its effective date. Money (severance, overtime, social security) is calculated in Python, not by the model.

> **Not legal advice.** Course capstone. Corpus frozen at **1 November 2026**. Check the official text or call the Department of Labour Protection and Welfare (1546) before acting.

## Example

`POST /ask` with `{"question": "ทำงานมา 3 ปี 2 เดือน เงินเดือน 25,000 บาท ถูกเลิกจ้าง ได้ค่าชดเชยอย่างน้อยเท่าไร"}` returned (question `C01` in `eval/results/answers_agent.jsonl`, `answer` shortened):

```json
{
  "answer": "ลูกจ้างจะได้รับค่าชดเชยอย่างน้อยเท่ากับค่าจ้างอัตราสุดท้าย 180 วัน ... โดยค่าชดเชยอย่างน้อยคือ 150,000 บาท ...",
  "citations": [{"law": "LPA2541", "section": "118", "amendment_no": 7, "effective_date": "2019-05-05",
                 "source": "พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541 (ฉบับรวมถึงฉบับที่ 9)"}],
  "calculation": {
    "kind": "severance",
    "value": 150000.0,
    "unit": "baht",
    "formula": "ค่าจ้างวันละ 833.333 x 180 วัน",
    "legal_basis": "LPA2541 s.118",
    "explanation": "ทำงาน 3 ปี 2 เดือน อยู่ในช่วงครบ 3 ปีแต่ไม่ครบ 6 ปี ได้ค่าชดเชยไม่น้อยกว่าค่าจ้างอัตราสุดท้าย 180 วัน; 25,000 / 30 x 180 = 150,000 บาท"
  },
  "as_of": "2026-11-01",
  "confidence": "high",
  "not_found": false,
  "clarifying_question": null,
  "correction": null
}
```

The full write-up is in [`report.pdf`](report.pdf) (Thai).

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
- **Safe model and tool use:** the key and proxy URL come from the environment; every call uses `temperature=0`; the model can only call the three allow-listed tools, at most 5 steps and 2 searches a question; tool arguments are checked by Pydantic models that reject extra fields, and a bad call comes back to the model as an error instead of crashing; the final answer must pass the `Answer` schema, with up to 2 retries.

Course capabilities covered: structured output, RAG, retrieval evaluation, an agent loop with tools (the agentic capability), and a FastAPI service.

## Corpus

37 official files in `data/raw/`, listed in `data/manifest.csv` with URL, dates, status and SHA-256: the Labour Protection Act and Amendments 2–9, the Social Security Act, the Workmen's Compensation Act, minimum wage, the Employee Welfare Fund, and related laws. `python scripts/fetch_corpus.py` verifies the hashes and downloads missing files (several government sites block scripts, so use the archived files).

## Results

Retrieval, 82 questions with gold sections:

| Variant | recall@5 | MRR |
|---|---:|---:|
| BM25, raw text (baseline) | 0.018 | 0.015 |
| BM25 + PyThaiNLP | 0.504 | 0.357 |
| Embeddings | 0.764 | 0.683 |
| Hybrid, reranked top 50 | 0.841 | **0.812** |
| Reranked, both wordings (used by the agent) | **0.900** | 0.797 |

The measured improvement is the retrieval choice: recall@5 rose from 0.018 for raw BM25 to 0.900. Reranking each wording's top 10 instead of the hybrid top 50 also cut the time from 35.6 s to about 21 s a question. For plain RAG, `eval/sweep_min_score.py` sets the refusal floor at 0.10.

Answers, 100 labelled questions (`eval/questions.jsonl`):

| Measure | No retrieval | RAG | Agent |
|---|---:|---:|---:|
| Expected behaviour | 59/100 | 72/100 | **92/100** |
| Right figures, none outdated | 7/58 | 30/58 | **55/58** |
| Calculations correct | 2/18 | 2/18 | **18/18** |
| Cites a gold section or rate announcement | 17/74 | 48/74 | **70/74** |

The model's answers vary a little between runs, even at temperature 0. A fresh run of all three on a new machine (`eval/results/fresh_run/`) gave 58, 73 and 91/100 expected behaviour, and the agent 53/58 figures, 18/18 calculations and 70/74 citations. Retrieval without the model gave the same numbers to the last digit; with the model's rewording, 0.898 and 0.805.

The system was tuned on these 100 questions, so it was also checked on five locked held-out sets written later. On the latest (44 questions, 3 runs) the agent gave the expected behaviour on 41–42/44 and cited a gold section on 29–30/32; three fresh runs on a new machine gave 41/44 and 30/32 each time (`eval/results_heldout5_rerun.csv`). Details are in `eval/results/` and the commit history.

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

The model is `gemma-4-E4B-it`, called through any OpenAI-compatible server. Copy `.env.example` to `.env` and fill in `OPENAI_API_KEY` and `OPENAI_BASE_URL` (or set them in the environment).

On Windows, double-click `start_app.bat`: it starts the server and opens the web page at http://localhost:8000 once the models have loaded. The page asks `POST /ask` and opens each cited section through `GET /section?law=LPA2541&section=41`, which returns the in-force text, so an answer can be checked against the statute. Or start it yourself:

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

`run_answers.py` and `run_heldout.py` reuse the answers saved in `eval/results/`, so they reproduce the tables above in a few minutes. To ask the model again, pass a new folder (`--out=eval/results/rerun`) or label (`--label=rerun`). On a new machine `run_retrieval.py` and a fresh answer run each take a few hours on CPU, since reranker scores are cached in `data/index/` only after they are first computed.

## Project structure

```
data/      manifest.csv, raw/ sources, processed/ chunks, rates.csv
scripts/   fetch_corpus, build_chunks, build_index
src/       retrieval/, agent/ (loop and tools), api/ (endpoints and static/ web page), schemas.py, rag.py, llm.py
eval/      questions, held-out sets, runners, results/
tests/
abstract/  overview.md, then a write-up of each stage: corpus, build_chunks, rates, retrieval, agent, evaluation, heldout
```

## Limitations

- Law changes after 1 November 2026 are not included.
- A small model can still pick the wrong formula or miss a condition.
- One person wrote and labelled the evaluation questions.
- The LLM judge is the same model that wrote the answers and does not measure completeness.
- Statute text only: no court rulings, contracts or company policies.
