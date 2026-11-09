# Held-Out Checks and Fix Rounds: What Was Done

Nov 3–5, 2026 · @riri

## Summary

The 100 questions were also used for tuning, so each round of fixes was measured on a new set of questions locked before the fix was written. The first check showed the tuned scores were optimistic. The four fix rounds after it each gained a little, mostly within the noise.

| Set | Questions | Locked in | Change measured | Expected behaviour, before → after |
| --- | ---: | --- | --- | --- |
| `heldout` | 30 | `c3bff94` | None: first check of the tuned agent | 22–23/30 (tuned set: 92/100) |
| `heldout2` | 60 | `dc4a859` | Weak spots from the first check (`2ffbd32`) | 46 → 48–50/60 |
| `heldout3` | 60 | `dece746` | Asking back from the law, grounding every number (`12fd6f3`) | 48–51 → 50/60 |
| `heldout4` | 48 | `30fa333` | Asking for the figures a formula needs (`36d5e65`) | 45 → 44–45/48 |
| `heldout5` | 44 | `9380248` | Fixes from the manual review (`47a2a38`) | 40–41 → 41–42/44 |

Ranges are the lowest and highest of 3 runs.

## Problems found and fixes

| Problem | Fix |
| --- | --- |
| Tuned-set scores can be optimistic | Each set is written after tuning and locked before any run |
| A set changed after a run would hide the change | Its SHA-256 is committed in a `.lock` file; `run_heldout.py` refuses to run if the file changed |
| A set seen once is no longer blind | It becomes development data, and the next round gets a new set |
| One run hides variation between runs | Old and new code each run 3 times; 95% Wilson intervals are reported |
| "Before" could be run on different code | The old code runs from a separate checkout of its commit |
| Two runners once wrote to the same files (`heldout2`) | Scoring keeps the last answer for each question |
| A few scores appeared in logs before the new code ran (`heldout3`, `heldout4`, `heldout5`) | Recorded; no held-out answer was read before the code was frozen |
| Round 5's first frozen code gave one-word answers, found on the 100 questions | That held-out run was set aside unread, a length check was added, and the code was frozen again |

## What each round found

1. **First check.** Every measure was lower than on the tuned set. Weak spots:
   - Calculations with no fitting kind (`H17`) or the wrong year (`H15`).
   - Answers from a neighbouring section (`H01`).
   - Corrections without a trigger word (`H18`, `H19`).
   - Over-asking (`H05`, `H09`).
2. **Second round.** Year in the question, `wage_share`, asking for missing figures, reported-speech beliefs, dropping group-specific sections.
   - Gains of 1–3 questions per measure.
   - A minimum-wage question with no province was now refused instead of asked back (`N47`).
3. **Third round.** Asking back decided by the law, code looking up the rates the question names, every number needing a source.
   - Over-asking fell from 3–4/52 to 1–2/52, but so did needed asking.
   - `P43` and `P45` asked for an amount with no figures and got only the rule.
4. **Fourth round.** Asking for the figures a formula needs.
   - Asked back when needed: 11/14 → 13–14/14.
   - Over-asking rose: 0/34 → 3/34 (`Q16`, `Q17`, `Q20`), so the figure and citation scores fell.
5. **Fifth round.** Working shown for calculations, four content errors, the rule stated while asking, conditions in answers, refusals worded by kind.
   - Supporting figures: 4–5/23 → 15–16/23, mostly the added working.
   - Refusal worded for its kind: 4/8 → 8/8.
   - `S26` now refuses with a false claim.

## Verification

| Set | Measure | Before | After |
| --- | --- | ---: | ---: |
| `heldout2` | Figures asked for, none outdated | 22/31 | 25/31 |
| `heldout3` | Cites a gold section | 35–36/42 | 37–38/42 |
| `heldout4` | Asked back when not needed | 0/34 | 3/34 |
| `heldout5` | LLM judge says correct | 23–25/32 | 29/32 |

Full tables for every round are in the README as of commit `47a2a38` (`git show 47a2a38:README.md`), and every answer is in `eval/results/heldout*/`.

## Open issues

| Issue | Effect |
| --- | --- |
| Each set was written knowing the planned fix | Not fully blind; some gains need the exact wording the fix looks for |
| 30–60 questions per set | Intervals about 20–30 points wide, so most before/after differences are within the noise |
| One person wrote and labelled every set | The labels are one person's judgement |
| Each fix round also moved the tuned set slightly, sometimes down | Fixes trade one failure for another |

To rerun a set (3 runs, then scoring):

```bash
python eval/run_heldout.py --set=heldout5 --label=fixed
```
