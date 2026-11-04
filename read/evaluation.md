# The Evaluation Set and Answer Evaluation: What Was Done

Nov 2–5, 2026 · @riri

## Summary

100 labelled questions compare three systems: Gemma with no retrieval, plain RAG, and the agent. The agent gave the expected behaviour on 92 of 100 and every calculation right.

| Question type | Count | What the system must do |
| --- | ---: | --- |
| General rights | 30 | Answer everyday questions |
| Trap | 20 | Avoid outdated or draft figures, such as 98 instead of 120 days' maternity leave |
| Calculation | 18 | Get severance, overtime and contributions right |
| Out of scope | 18 | Refuse, because the corpus does not say |
| Clarification | 8 | Ask for missing details instead of assuming |
| Correction | 6 | Correct a wrong belief in the question |

| File | Change |
| --- | --- |
| `eval/questions.jsonl` | New: 100 questions with gold sections, reference answer, figures, expected behaviour and source |
| `eval/check_questions.py` | New: checks every label against the chunks and the manifest |
| `eval/controls.jsonl` | New: 14 control questions that should not be asked about or corrected |
| `eval/run_answers.py` | New: Evals 2–4, writes `eval/results/` and the summary CSVs |
| `eval/review.py`, `eval/review.html` | New: label saved answers by hand in the browser |

## Problems found and fixes

| Problem | Fix |
| --- | --- |
| The first 60 questions only tested answering and refusing | Expanded to 100, adding clarification and correction questions and each question's source file |
| Labels could drift from the law | `check_questions.py`: each gold section is in force and contains the quoted evidence, each formula gives the expected number, out-of-scope terms are absent from the corpus |
| Recall alone rewards a system that always asks | Over-asking, precision and false corrections are reported too |
| A question that gives every detail could still be asked about | Control questions: 8 with every detail, 6 with a right belief |
| Figures the question did not ask for counted as required | `expected_numbers` and `supporting_numbers` are scored apart; `wrong_numbers` lists outdated ones |
| The LLM judge is the same model that wrote the answers | Checked against one person's labels of all 100 answers |
| The class proxy rate-limits requests | Up to 8 retries on HTTP 429; failures are logged and rerun; runs resume from saved answers |

## Results

| Measure | No retrieval | RAG | Agent |
| --- | ---: | ---: | ---: |
| Expected behaviour | 59/100 | 72/100 | **92/100** |
| Figures asked for, none outdated | 7/58 | 30/58 | **52/58** |
| Cites a gold section | 17/74 | 48/74 | **61/74** |
| LLM judge says correct | 13/74 | 41/74 | **65/74** |
| Calculation: right amount | 2/18 | 2/18 | **18/18** |
| Trap: right figures | 1/18 | 7/18 | **15/18** |
| Out of scope: refused | 10/18 | **18/18** | 17/18 |
| Asked back when needed | **7/8** | 2/8 | 5/8 |
| Asked back when not needed | 28/92 | **1/92** | 4/92 |
| Correction with the right content | 0/10 | 2/10 | **9/10** |
| Corrected with nothing to correct | 2/90 | 1/90 | **0/90** |

After four rounds of fixes, the final agent (`eval/results/after_fixes4`) scored:

- Expected behaviour 92/100
- Figures 55/58, supporting figures 9/10
- Gold citations 70/74
- Judge 64/74

### Manual review

One person labelled all 100 answers of `after_fixes3`:

| Label | Count |
| --- | ---: |
| Correct | 51 |
| Partly correct | 31 |
| Wrong | 6 |
| Unsure | 12, all out of scope |

- **The judge passes no wrong answers but most incomplete ones:** it passed 0 of 6 wrong and 20 of 23 partly correct.
- **The behaviour check passed 4 wrong answers:** `T04`, `T10`, `T15`, `T16`.

The fixes from this review are in `heldout.md`.

## Open issues

| Issue | Effect |
| --- | --- |
| The system was tuned on these 100 questions | Scores are optimistic; see `heldout.md` |
| One person wrote and labelled every question | Results show direction, not precise accuracy |
| Severance assumes a daily rate of monthly wage / 30 | The Act does not define it |
| Some figures were read by eye from PDFs without text | `T09`, `T20`, the EWF figures and some wage bases may contain typos |
| The judge does not measure completeness | Partly correct answers count as correct |

To check the labels and rerun:

```bash
python eval/check_questions.py
python eval/run_answers.py baseline rag agent
python eval/review.py --summary
```
