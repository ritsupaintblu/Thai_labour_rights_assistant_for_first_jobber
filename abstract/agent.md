# The Agent, Its Tools and the API: What Was Done

Nov 3–5, 2026 · @riri

## Summary

The agent answers through FastAPI `POST /ask` with a Pydantic-validated JSON answer. It uses `gemma-4-E4B-it` and three tools. The model decides what to search and which tool to call, while code decides when to refuse, ask back or correct, and checks every number.

| Tool | What it does |
| --- | --- |
| `search_law` | `statute_both` retrieval: the question and its statute wording, 10 sections reranked for each |
| `calculate` | Severance, special severance, overtime, holiday work, SSO and EWF contributions, compensation, and pay that is a share of the wage, in exact arithmetic |
| `get_rate` | Official rates from `data/rates.csv` for a date |

| File | Change |
| --- | --- |
| `src/agent/loop.py` | The agent: tool calls, decisions and the answer |
| `src/agent/steps.py` | The model's checks: rewrite, coverage, differing rules, beliefs, refusal kind |
| `src/agent/tools/` | `search_law`, `calculate`, `get_rate` |
| `src/answer.py` | Builds the answer, checks every number, retries on invalid JSON |
| `src/schemas.py` | `Draft` (what the model may write) and `Answer` (adds what only code fills in) |
| `src/rag.py` | Plain RAG, the comparison for the agent |
| `src/llm.py` | The one place that calls the model |
| `src/api/main.py` | `POST /ask`, where a model failure returns 502; `GET /section` for the in-force text of a cited section; `GET /` for the web page |
| `src/api/static/index.html` | The web page: ask a question, then open each cited section |
| `tests/test_agent.py` | 124 tests with a fake model |

## Problems found and fixes

Each fix came from a failure on the evaluation questions. Most are in `evaluation.md` and `heldout.md`.

| Area | Problem | Fix |
| --- | --- | --- |
| Tools | Shown the law, or the JSON format, the model answered without calling a tool; few-shot examples did not help | Tools are chosen before the model sees any law |
| Arithmetic | The model got amounts wrong | All money is computed by `calculate`, never by the model |
| Arithmetic | Left optional, the wage argument was often left out | The wage is required, and 0 means not given |
| Refusing | No score floor could separate out-of-scope from everyday wording | Refuse unless the model quotes a sentence from the results that shares a key word with the question |
| Answering | Given five sections, the model answered from a neighbouring one | The answer sees the whole quoted section, plus the others that answer alone |
| Answering | Rules for pregnant employees or children answered general questions | Sections for a group the question does not mention are dropped |
| Answering | One-word answers such as "ใช่" or "ไม่ได้" | An answer under 40 characters without a calculation is sent back |
| Asking back | Asked first, the model asked about details the answer did not need | Ask only when two sections of the same Act each answer and differ, with each case quoted |
| Asking back | Amount questions with no figures got the rule but no amount | Code calls `calculate` for the section's formula and asks for what it reports missing, stating the rule too |
| Asking back | Minimum-wage questions never asked for the province | Code looks up the rate itself; a place named in the question overrides the model's |
| Correcting | The model said plain questions stated beliefs, correcting 7 of 90 | Checked only with a trigger word ("ใช่ไหม", "ได้ยินว่า") or reported speech ("เพื่อนบอกว่า"), with a quote against the belief |
| Dates | A 2029 contribution used the 2026 ceiling | A year in the question sets `as_of` |
| Formulas | No kind for suspension pay, so the model used compensation | `wage_share`, whose percentage must appear in the section it cites |
| Formulas | "The most deducted" was answered with the 17,500 baht ceiling | Calculated at the ceiling |
| Citations | The section behind an amount was cited only if the search found it | `calculate` returns its legal basis, which is always cited |
| Numbers | Answers stated numbers with no source | Every number must be in the results, a tool result or the question, or one step from them; otherwise rewrite, then build from tool results |
| Working | Calculations gave only the amount | `calculate` writes each step in Thai, added as "วิธีคิด" |
| Penalties | Penalty sections name the duty only by number | Add the duties that share the most words with the question, and their penalty sections |
| Refusals | Workplace questions got a bare refusal | "กฎหมายที่ระบบมีไม่ได้บังคับเรื่อง... จึงขึ้นกับสัญญาจ้างหรือข้อบังคับของบริษัท", only for what an employer must give |

## How it works now

1. Rewrite the question in statute wording. Choose tools before seeing any law, at most 5 steps.
2. Search with both wordings. Add penalty duties and repealing sections where asked; drop group-specific sections.
3. Check, in parallel: do the results cover the question, and which sections answer alone? Does a stated belief contradict them?
4. Decide in this order:
   - A figure is missing: ask for it, with the rule.
   - Two sections differ: ask which case applies.
   - Nothing covers the question: refuse, worded by kind.
   - Otherwise: answer from the quoted sections, and fill `correction` if a belief is wrong.
5. Check every number, add the calculation's working, and return the `Answer`.

Tools are allow-listed and their arguments validated before running. Retrieved text and tool results are treated as data, never as instructions.

## Verification

| Check | Result |
| --- | --- |
| All tests (`tests/`) | 158 pass |
| Six new questions through `POST /ask` | 20–41 s each on CPU, about 21 s of it reranking |
| Answers on 100 questions and five held-out sets | See `evaluation.md` and `heldout.md` |

## Open issues

| Issue | Seen in | Next step |
| --- | --- | --- |
| Holiday work pay uses the holiday-overtime kind (3× instead of 1×) | `P30`, `Q32` | Check the kind against the question, not only the section |
| "How much" questions about a rate or cap ask for the user's figures | `Q16`, `Q17`, `Q20`, `G12` | Tell rate questions from amount questions |
| A refusal can state something false | `S26`: said the law gives no leave to new employees | Keep the plain refusal when a section on the topic was found |
| Asking back across two Acts | `P50`: workmen's compensation vs social security | Allow it when both Acts apply to the case |
| Beliefs stated without a trigger word | `H18`, `H19`, `N36`–`N38` | A wider belief check, measured for false corrections |
| Runs vary at `temperature=0` | 46 of 100 texts differed between two runs of an earlier version | Report ranges over several runs |

To run the API (needs `OPENAI_API_KEY`, `OPENAI_BASE_URL` and the index), double-click `start_app.bat` on Windows to open the web page at http://localhost:8000, or:

```bash
uvicorn src.api.main:app
curl -X POST http://localhost:8000/ask -H "Content-Type: application/json" \
  -d '{"question": "ลาป่วยได้กี่วันโดยได้รับค่าจ้าง"}'
```
