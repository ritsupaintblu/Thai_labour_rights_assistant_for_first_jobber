"""Download the legal corpus listed in data/manifest.csv and verify each file's sha256.

A row is skipped when a file with its sha256 already exists anywhere under the raw
directory, so the original filenames and folders are kept. Otherwise the file is
downloaded to <raw-dir>/<id>.<ext>. A download whose hash differs from the manifest
is kept out of the corpus, in <raw-dir>/../raw_unverified/, for manual comparison.

Exits with status 1 if any row could not be verified.
"""

import argparse
import csv
import hashlib
import subprocess
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
USER_AGENT = "Mozilla/5.0 (compatible; thai-labour-corpus-fetcher)"
TIMEOUT_SECONDS = 60


def sha256_hex(data):
    return hashlib.sha256(data).hexdigest()


def index_existing(raw_dir):
    return {sha256_hex(p.read_bytes()) for p in raw_dir.rglob("*") if p.is_file()}


def download(url):
    # curl rather than urllib: several .go.th servers send an incomplete certificate
    # chain, which Python's ssl rejects but the OS TLS stack used by curl can complete
    command = ["curl", "-fsSL", "-A", USER_AGENT, "--max-time", str(TIMEOUT_SECONDS), url]
    return subprocess.run(command, capture_output=True, check=True).stdout


def extension_for(data):
    if data.startswith(b"%PDF-"):
        return ".pdf"
    if data.startswith(b"\x89PNG"):
        return ".png"
    return ".html"


def fetch_row(row, raw_dir, unverified_dir):
    """Download one manifest row and return whether its hash matched."""
    data = download(row["url"].strip())
    digest = sha256_hex(data)
    filename = row["id"] + extension_for(data)

    if digest == row["sha256"].strip():
        raw_dir.mkdir(parents=True, exist_ok=True)
        (raw_dir / filename).write_bytes(data)
        print(f"{row['id']}: DOWNLOADED")
        return True

    # A web page instead of a document says nothing about whether the source changed:
    # it is a bot-protection page, or the URL is an article captured as a screenshot
    if filename.endswith(".html"):
        print(f"{row['id']}: NOT A DOCUMENT server returned a web page, cannot compare")
        return False

    unverified_dir.mkdir(parents=True, exist_ok=True)
    (unverified_dir / filename).write_bytes(data)
    print(f"{row['id']}: HASH MISMATCH expected={row['sha256'].strip()} got={digest}")
    return False


def main():
    parser = argparse.ArgumentParser(description="Download and verify the legal corpus.")
    parser.add_argument("--manifest", type=Path, default=ROOT / "data" / "manifest.csv")
    parser.add_argument("--raw-dir", type=Path, default=ROOT / "data" / "raw")
    args = parser.parse_args()

    # utf-8-sig: the manifest is saved with a BOM, which would otherwise corrupt the first header
    with open(args.manifest, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))

    existing = index_existing(args.raw_dir)
    unverified_dir = args.raw_dir.parent / "raw_unverified"

    failed = []
    for row in rows:
        if row["sha256"].strip() in existing:
            print(f"{row['id']}: OK")
            continue
        try:
            if not fetch_row(row, args.raw_dir, unverified_dir):
                failed.append(row["id"])
        except subprocess.CalledProcessError as e:
            print(f"{row['id']}: DOWNLOAD FAILED {e.stderr.decode(errors='replace').strip()}")
            failed.append(row["id"])

    print(f"\n{len(rows) - len(failed)}/{len(rows)} verified")
    if failed:
        print("Not verified: " + ", ".join(failed))
    raise SystemExit(1 if failed else 0)


if __name__ == "__main__":
    main()
