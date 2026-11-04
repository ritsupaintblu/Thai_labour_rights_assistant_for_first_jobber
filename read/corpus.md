# Collecting and Verifying the Corpus: What Was Done

Nov 1, 2026 · @riri

## Summary

The corpus is 37 official files, archived in `data/raw/` and listed in `data/manifest.csv`. `scripts/fetch_corpus.py` checks every row against its SHA-256 hash, and all 37 match.

| `status` | Rows | Meaning |
| --- | ---: | --- |
| `in_force` | 31 | Law or rate in force on 1 Nov 2026 |
| `superseded` | 3 | Out-of-date Employee Welfare Fund explainers, kept for the record |
| `secondary` | 3 | Explanatory material, not law |

| `kind` | Rows |
| --- | ---: |
| `consolidated` | 10 |
| `amendment` | 16 |
| `rate` | 5 |
| `secondary` | 6 |

| File | Change |
| --- | --- |
| `data/manifest.csv` | One row per file: URL, published and effective dates, status, SHA-256, `law`, `kind`, `amendment_no` |
| `data/raw/` | Archived PDFs, plus PNG screenshots of three web articles |
| `scripts/fetch_corpus.py` | New: verifies hashes and downloads missing files |

## Problems found and fixes

| Area | Problem | Fix |
| --- | --- | --- |
| File names | Archived files have Thai titles, not `<id>.pdf` | Files are found by SHA-256 anywhere under `data/raw/` |
| TLS | Python rejected the certificates of several `.go.th` servers | Download with `curl`, keeping certificate checks on |
| Bot protection | `mol.go.th` serves a web page to scripts instead of the PDF | Reported as `NOT A DOCUMENT` and nothing is saved |
| Blocked server | `ratchakitcha.soc.go.th` returns HTTP 403 | Reported as `DOWNLOAD FAILED`; the archived copy is used |
| Web articles | Three EWF sources are web pages, so a download can never match | Archived as PNG screenshots; the URL only records where they came from |
| Wrong URL | The `emp_consolidated` URL served a different PDF | Replaced with a URL that matches the hash |
| Mismatches | A changed download could replace a verified file | Saved to `data/raw_unverified/` for comparison, never used |
| Repealed law | The Foreign Workers Act 2551 was repealed by the 2560 Royal Ordinance, section 3 | Replaced with the 2560 Royal Ordinance and its 2561 amendment |
| Missing source | The 5% employee contribution rate had no source file | Added the Ministerial Regulation on contribution rates, B.E. 2565 |
| Chunking needs | The chunker needs to know what each file is | Added `law`, `kind` and `amendment_no` columns |
| Excel | Saving the manifest from Excel adds a BOM | Read with `encoding="utf-8-sig"` |

## How it works now

For each manifest row, the script looks for a file with the expected hash. Only if there is none does it download the row's URL.

| Output | Meaning |
| --- | --- |
| `OK` | A file with the expected hash is already in `data/raw/` |
| `DOWNLOADED` | The download matched and was saved as `data/raw/<id>.<ext>` |
| `HASH MISMATCH` | A different document came back; saved to `data/raw_unverified/` |
| `NOT A DOCUMENT` | A web page came back, so nothing could be compared |
| `DOWNLOAD FAILED` | The request failed, for example with HTTP 403 |

The script exits with status 1 if any row is not verified. When a law changes, add a row for the new version and mark the old row `superseded`.

## Verification

| Check | Result |
| --- | --- |
| Archived files against the manifest | 37 of 37 verified (2026-11-02) |
| Full download into an empty folder (2026-11-01) | 21 rows cannot be re-downloaded: 14 bot-protected, 3 screenshots, 4 blocked |

## Open issues

| Issue | Effect | Next step |
| --- | --- | --- |
| 21 rows cannot be re-downloaded by script | The archive in `data/raw/` is the only copy that verifies | Keep the archive committed |
| `curl` was tested only on Windows | Other systems may report `DOWNLOAD FAILED` for the same servers | Test on Linux or macOS |
| No draft bills are stored | Trap questions about drafts rely on the labels only | Add them, marked so they are never used as answers |
| Changes after 1 Nov 2026 are not tracked | New amendments must be added by hand | Watch the Royal Gazette |

To verify the corpus (Python 3 and `curl`, no packages):

```bash
python scripts/fetch_corpus.py
```
