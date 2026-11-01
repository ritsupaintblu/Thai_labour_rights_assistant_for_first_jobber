# Thai_labour_rights_assistant_for_first_jobber

## Data corpus

The corpus is 35 Thai legal and government documents covering labour protection, social security, workmen's compensation, the Employee Welfare Fund, minimum wage and employment.

| Path | Contents |
|---|---|
| `data/raw/` | Archived source files (PDF and PNG). These are the copies the project relies on. |
| `data/manifest.csv` | One row per document: `id`, `title`, `url`, `published`, `effective`, `status`, `sha256` |
| `scripts/fetch_corpus.py` | Verifies the archived files and downloads any that are missing |

`status` is one of `in_force` (28 rows), `superseded` (3), `secondary` (3) or `repealed_check` (1). When a law changes, add a row for the new version and mark the old row `superseded`.

### Verifying the corpus

Requires Python 3 and `curl`; there are no Python packages to install.

```
python scripts/fetch_corpus.py
```

For each manifest row, the script looks for a file with the same SHA-256 anywhere under `data/raw/`, so filenames and folders don't need to match the `id`. If there is none, it downloads the row's `url` and checks the hash. The script exits with status 1 if any row is not verified.

| Output | Meaning |
|---|---|
| `OK` | A file with the expected hash is already in `data/raw/` |
| `DOWNLOADED` | The download matched and was saved as `data/raw/<id>.<ext>` |
| `HASH MISMATCH` | The server returned a different document, saved to `data/raw_unverified/` for comparison |
| `NOT A DOCUMENT` | The server returned a web page, so the hash could not be compared. Nothing is saved |
| `DOWNLOAD FAILED` | The request failed, for example with an HTTP 403 |

### Sources that can't be re-downloaded

Use the files in `data/raw/` as the corpus. A check on 2026-11-01, with the local files present and then with an empty folder, gave these results:

- **With the archived files:** 35 of 35 verified.
- **Downloading from the URLs:** 16 of 35 verified.

The 19 rows that did not verify from their URLs:

| Rows | Result | Reason |
|---|---|---|
| `fishing_labour`, `soe_labour`, `home_work`, `ssa_consolidated`, `ssa_no2`, `ssa_no3`, `ssa_no4`, `wca_consolidated`, `min_wage_no14`, `emp_no2`, `emp_no3`, `foreign_workers`, `maritime_labour`, `disability`, `disability_no2` | `NOT A DOCUMENT` | `mol.go.th` serves a bot-protection page to scripts instead of the PDF. |
| `ewf_info1`, `ewf_info2`, `ewf_info3` | `NOT A DOCUMENT` | The sources are web articles, archived as PNG screenshots. The manifest holds the screenshot's hash, so a download can never match. The URL only records where the content came from. |
| `wca_no2` | `DOWNLOAD FAILED` | `www.ratchakitcha.soc.go.th` returns HTTP 403. |

**TLS.** The script uses `curl` because Python rejected the certificates from several `.go.th` servers. Certificate checks stay on. This was tested on Windows; `curl` on other systems may still report `DOWNLOAD FAILED` for those servers.
