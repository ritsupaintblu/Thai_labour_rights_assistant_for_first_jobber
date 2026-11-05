# Thai Labour-Rights Assistant: Project Overview

Nov 5, 2026 · @riri

## Summary

The assistant answers Thai employee-rights questions from the laws in force on 1 November 2026, citing each section and its effective date. Money is calculated in Python. On the 100 labelled questions the agent gave the expected behaviour on 92, against 59 for Gemma alone and 72 for plain RAG. On the latest unseen set it scored 41–42 of 44.

> **Not legal advice.** Course capstone. Check the official text or call the Department of Labour Protection and Welfare (1546) before acting.

## The problem

- **The law is long and changes.** The Labour Protection Act has been amended nine times. Amendment No. 9 (7 Dec 2025) raised maternity leave from 98 to 120 days.
- **Online copies are outdated.** Many "full texts" stop before No. 9.
- **General LLMs answer wrongly with confidence.** They repeat old figures and treat draft bills, such as 10 days' annual leave, as law.

## The stages

| Stage | What was built | Key result | Write-up |
| --- | --- | --- | --- |
| Corpus | 37 official files with a SHA-256 manifest | 37 of 37 verified; 21 can only come from the archive | [corpus.md](corpus.md) |
| Chunks | One chunk per section, tagged with amendment and effective date | 1,101 chunks from 10 Acts, 1,039 in force | [build_chunks.md](build_chunks.md) |
| Rates | `rates.csv` and `get_rate`, typed from scans and unreadable PDFs | 99 rows: minimum wage, SSO and EWF rates and ceilings | [rates.md](rates.md) |
| Retrieval | BM25 + PyThaiNLP, `bge-m3`, fusion, cross-encoder reranking | recall@5 from 0.018 (raw BM25) to 0.900 | [retrieval.md](retrieval.md) |
| Agent and API | Agent with `search_law`, `calculate`, `get_rate`; FastAPI `POST /ask` | Every calculation right; 155 tests pass | [agent.md](agent.md) |
| Evaluation | 100 labelled questions, three systems, a manual review | 92/100 expected behaviour; the judge misses incomplete answers | [evaluation.md](evaluation.md) |
| Held-out checks | Five locked sets, 242 questions, one per fix round | Tuned scores were optimistic; fixes gained a little, within the noise | [heldout.md](heldout.md) |

## What mattered most

- **In-force text only.** Consolidated texts give the current wording, and footnotes give each section's amendment and date.
- **Thai word segmentation.** Without it, BM25 found almost nothing.
- **Statute wording.** Searching the question and its legal rewrite, keeping the best score, raised recall@5 from 0.841 to 0.900 while reranking 20 sections instead of 50.
- **Code decides, the model reads.** Refusing, asking back and correcting are decided from quotes the model must find in the results, not from scores or the model's own judgement.
- **No number without a source.** Amounts come from `calculate`, and every number in an answer must appear in the results, a tool result or the question.
- **Locked held-out sets.** Each fix was measured on questions written and locked before the fix.

## Results at a glance

| Measure | No retrieval | RAG | Agent |
| --- | ---: | ---: | ---: |
| Expected behaviour | 59/100 | 72/100 | **92/100** |
| Right figures, none outdated | 7/58 | 30/58 | **55/58** |
| Calculations correct | 2/18 | 2/18 | **18/18** |
| Out of scope refused | 10/18 | **18/18** | 16/18 |

## Limitations

- Law changes after 1 November 2026 are not included.
- The small model still picks a wrong formula at times, and asks for figures a rate question does not need.
- One person wrote and labelled every question, and each held-out set was written knowing the planned fix.
- Statute text only: no court rulings, contracts or company policies.
- A new question takes 20–40 seconds on CPU, mostly reranking.
