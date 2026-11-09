# Official Rates and get_rate: What Was Done

Nov 2, 2026 · @riri

## Summary

Rate announcements are not indexed for search. Their figures were typed into `data/rates.csv`, one row per rate and period, and `get_rate` looks them up for a date.

| Rate | Rows | Values |
| --- | ---: | --- |
| `min_wage_daily` | 82 | 337–400 baht a day by province, from 1 Jul 2025; Chiang Mai, Songkhla and Surat Thani differ by district |
| `sso_employee_rate_percent`, `sso_employer_rate_percent` | 2 each | 3% to 31 Dec 2022, then 5% |
| `sso_government_rate_percent` | 2 | 2.75% |
| `sso_wage_base_min`, `sso_wage_base_max` | 3 each | 1,650 baht floor; ceiling 17,500 from 2026, 20,000 from 2029, 23,000 from 2032 |
| `ewf_employee_rate_percent`, `ewf_employer_rate_percent` | 2 each | 0.25%, then 0.5% from 1 Oct 2031 |
| `ewf_collection_start` | 1 | 1 Jan 2027 |

| File | Change |
| --- | --- |
| `data/rates.csv` | New: 99 rows, each with its source `id` and clause |
| `src/agent/tools/get_rate.py` | New |
| `tests/test_get_rate.py` | New: 14 tests |
| `data/manifest.csv` | Added `ssa_rate_2565` for the contribution rates |

## Problems found and fixes

| Problem | Fix |
| --- | --- |
| Rate files are tables, so section chunks do not fit them | Kept out of the index; looked up with `get_rate` instead |
| `min_wage_no14` is a scan with no text layer | Typed by hand and checked against the announcement's own summary table |
| `ssa_wage_base_2568`, `ewf_rate_2568` and `ewf_start_2569` have unreadable fonts | Typed by hand from the PDFs |
| The 5% employee rate had no source in the corpus | Added the Ministerial Regulation B.E. 2565 |
| Rates change over time | Each period has `effective_from` and `effective_to`, and the lookup takes a date |
| Some provinces set rates by district | Returns `needs_input` with `district` in `missing`, so the agent asks |
| A date before the first period could get the nearest rate | Returns `not_found` instead of guessing |
| The model copied codes such as `baht_per_month` into answers | Units are shown in Thai |
| Asked when the welfare fund starts, the model gave the announcement's effective date | A rate whose value is a date is shown without it |

## How it works now

```python
get_rate("sso_employee_rate_percent", "2026-11-01")              # found: 5
get_rate("min_wage_daily", "2026-11-01", province="นนทบุรี")      # found: 372
get_rate("min_wage_daily", "2026-11-01", province="เชียงใหม่")     # needs_input: district
get_rate("sso_wage_base_max", "2020-01-01")                      # not_found
```

| `status` | Meaning |
| --- | --- |
| `found` | The value, with the source's manifest title and clause for the citation |
| `needs_input` | Ask the user for the items in `missing` |
| `not_found` | No rate for that date, so do not guess |
| `invalid` | Unknown rate name or bad arguments |

A rate citation has the clause as its section and no law code.

## Verification

| Check | Result |
| --- | --- |
| `tests/test_get_rate.py` | 14 tests pass |
| Minimum wage against the summary table | Matched |

## Open issues

| Issue | Effect | Next step |
| --- | --- | --- |
| The minimum wage does not apply to government bodies, state enterprises, non-profits, home workers, seagoing freight or seasonal farm work | `get_rate` gives a rate for them anyway | Check the employer type before answering |
| All figures were typed by one person | A typo would go unnoticed | Have a second person check them |
| The 2027 minimum wage was undecided on 1 Nov 2026 | Later dates use the current rate | Add a row when it is announced |

To add a rate: add a row, end the previous period with `effective_to`, and run the tests.

```bash
python -m unittest discover -s tests -t .
```
