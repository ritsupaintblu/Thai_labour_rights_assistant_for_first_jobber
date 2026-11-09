# Building Section-Level Chunks: What Was Done

Nov 1, 2026 · @riri

## Summary

The first `build_chunks.py` did not work on the real PDFs, so it was rewritten. It now builds 1,101 section-level chunks from 10 laws.

| Status | Chunks | Meaning |
| --- | --- | --- |
| `in_force` | 1,039 | Current text, usable for answers |
| `repealed` | 11 | Section text reads "(ยกเลิก)" |
| `superseded` | 51 | Disability Act and Foreign Workers Royal Ordinance sections fully replaced by Amendment No. 2 |

| File | Change |
| --- | --- |
| `scripts/build_chunks.py` | New location, rewritten |
| `data/processed/chunks.jsonl` | New output, about 1.6 MB |
| `data/manifest.csv` | Added `law`, `kind` and `amendment_no`; retitled `emp_consolidated` as including No. 3 |
| `README.md` | Added the build step and updated the status table |
| `chunks/build_chunks.py` | Old copy, removed |

## Problems found and fixes

The original script had only been tested on simulated text, and most failures appeared only on the real files.

| Area | Problem on the real files | Fix |
| --- | --- | --- |
| Manifest | No `law`, `kind` or `amendment_no` columns; files are not named `<id>.pdf` | Added the columns; files are found by SHA-256, like `fetch_corpus.py` |
| Extraction | `pdfplumber` lost tone marks and mixed watermark text into sentences | Switched to PyMuPDF; dropped text in the watermark's grey color |
| Extraction | Footnote markers fused with section numbers: `มาตรา ๔๑๒๗` is section 41, footnote 27 | Dropped superscripts and footnotes by font size |
| Extraction | One printed line was split into pieces, separating `มาตรา` from its number | Rejoined pieces that share a baseline |
| Encoding | WCA drew every `า` as `ำ`, giving `มำตรำ` | Swapped them back; a real `ำ` appears there as space + `ำ` |
| Encoding | EMP drew marks as Latin letters and digits: `ฝUาฝVน` is `ฝ่าฝืน` | Character map for that file, read from context |
| Encoding | Fishing stored `ำ` as space + `า`: `ก าหนด` | Repaired everywhere, because no Thai word starts with `า` |
| Encoding | Several Acts used Private Use Area tone marks | Mapped to standard Thai characters |
| Sections | "Last occurrence wins" could delete a real section when a later reference to it wrapped to a line start | Pick the best increasing run of section numbers, favoring indented lines |
| Sections | `มาตรา 47 ทวิ` numbering was not recognized | Added suffix support and correct ordering |
| Sections | Chapter titles leaked into the previous section | Headings are consumed with their title line |
| Sections | Schedules, reasons and sign-offs followed the last section | Cut the text at `ผู้รับสนองพระบรมราชโองการ` |
| Metadata | Consolidated texts and amendments would both be `in_force`, creating duplicates | Skip amendments already included in the consolidated text |
| Metadata | Every consolidated section would cite the Act's own date (1998 for LPA) | Read `amendment_no` per section from footnotes, so section 41 cites No. 9 and 2025-12-07 |
| Metadata | The repealed Foreign Workers Act was hard-coded as `in_force` | Status now comes from the manifest |
| Amendments | The parser missed the last clause, multi-section additions and paragraph-level changes | Handled all three; changed paragraphs become `change: "partial"` chunks |
| Amendments | The 2561 Foreign Workers amendment replaces several sections in one clause, which stayed in force with outdated wording | Split these clauses by section; a clause that can't be split cleanly goes to review by hand |
| Corpus | The Foreign Workers Act 2551 was repealed by the 2560 Royal Ordinance, section 3 | Replaced it with the 2560 Royal Ordinance and added its 2561 amendment |
| Console | Printing Thai crashed on a default Windows console | Set stdout to UTF-8 |

The consolidated LPA text already includes Amendment No. 9. That is why the unreadable font in `lpa_no9` does not block the corpus.

## How the pipeline works now

The consolidated text is the source of in-force wording, and amendments are parsed only when they are newer than it.

Each manifest row is read and its file is found by SHA-256. The row then takes one of four paths:

| Path | What happens | Reaches the output? |
| --- | --- | --- |
| Rate or secondary | Skipped; rates go to `rates.csv` | No |
| Already included | Amendment skipped; its text is in the consolidated Act | No |
| Consolidated | Clean the text, split into sections, read footnotes for amendment and date | Yes |
| Newer amendment | Clean the text, parse replaced, added and changed parts | Yes |

The last two paths are merged, with a newer section superseding the older one, and written to `data/processed/chunks.jsonl`.

Only the Disability Act and the Foreign Workers Royal Ordinance have a newer amendment. Their original texts have no consolidated version in the corpus, so they are treated as consolidated through No. 0.

## Verification

Automated checks passed, but nobody has read the output against the PDFs line by line.

| Check | Result |
| --- | --- |
| Section numbering in each of the 10 Acts | No missing whole numbers from section 1 to the last |
| 56 sections compared with the separately published amending Acts | 42 scored at least 0.97 similarity |
| The 14 lower scores, read by hand | All explained: lost `ำ` or page headers in the amendment PDFs, or later พินัย wording in the consolidated text |
| Leftovers in chunks: watermarks, page headers, broken characters | 0 |
| Duplicate chunk IDs | 0 |
| LPA sections 41 and 59, read directly | 120 days of leave, up to 60 paid, Amendment No. 9, effective 2025-12-07 |
| `fetch_corpus.py` after the manifest change | 36 of 36 verified |
| Adding the Foreign Workers Royal Ordinance | The other laws' 878 chunks stayed identical |

Four limits remain:

- The Foreign Workers amendment's sections were not compared with a consolidated text, because the corpus has none.

- The comparison covered only sections last changed by a readable amendment. No. 9, EMP No. 2 and EMP No. 3 are unreadable, so sections they changed could not be cross-checked.
- SSA No. 4 yielded no parsed sections, so sections it last changed were not compared either.
- The similarity check was run before the last repairs and not repeated on the final build. Those repairs touched page headers and the Fishing Act's `ำ`, and the Fishing Act has no amendments in the comparison.

## Open issues

The partly amended sections and the unreadable rate files need action before retrieval and `get_rate` can rely on this corpus.

| Issue | Effect | Next step |
| --- | --- | --- |
| Disability Act: 7 chunks across sections 4, 13, 16, 19, 21 and 26 contain outdated wording. Foreign Workers Royal Ordinance: sections 4, 5, 28, 38, 64, 67, 69, 76, 98, 100 and 133 do too | Old wording is still `in_force`, flagged with `partly_amended_by` | Handle the flag in retrieval, or merge by hand |
| Amendments to the Foreign Workers Royal Ordinance after No. 2 were not confirmed | Later changes could be missing | Check the Royal Gazette or the Department of Employment |
| `min_wage_no14` is a scan; `ssa_wage_base_2568`, `ewf_rate_2568` and `ewf_start_2569` have unreadable fonts | Their text cannot be extracted for `rates.csv` | Type the rates by hand or run OCR |
| Schedules and amending Acts' transitional clauses are not indexed | Questions on them, such as the LPA fee schedule, will not find text | Add them if the eval set needs them |
| Wrapped lines stay split inside chunks | May slightly hurt BM25 | Measure in the retrieval eval |
| `amendment_no` tracks only the Act's own amendments | Sections reworded by the พินัย Act, such as section 145, cite an older date | Add a note or a separate field for those sections |

To rebuild the chunks:

```bash
pip install pymupdf
python scripts/build_chunks.py
```
