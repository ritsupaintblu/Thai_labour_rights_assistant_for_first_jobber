"""
build_chunks.py — PDF -> text -> section-level chunks (มาตรา) + metadata

Usage:
    pip install pymupdf
    python scripts/build_chunks.py --manifest data/manifest.csv --raw data/raw --out data/processed/chunks.jsonl

Required manifest.csv columns (read with utf-8-sig, so files saved from Excel work):
    id, title, url, effective, status, sha256, law, kind, amendment_no
      kind          = "consolidated" (full text of an Act), "amendment" (an amending Act),
                      "rate" or "secondary" (skipped: rates go to rates.csv, not the index)
      amendment_no  = consolidated: the LAST amendment already included in that text (e.g. 9)
                      amendment:    that Act's own number (e.g. 9)

Files are found by sha256 anywhere under --raw, the same way as fetch_corpus.py.
Amendments already included in their consolidated text are skipped: the consolidated text
is the in-force wording, and its footnotes say which amendment last changed each section.
"""

import argparse
import csv
import hashlib
import json
import re
import sys
import unicodedata
from collections import Counter
from pathlib import Path

THAI_DIGITS = str.maketrans("๐๑๒๓๔๕๖๗๘๙", "0123456789")

# Old-style section suffixes order after the plain number: 47 < 47 ทวิ < 47 ตรี ...
SUFFIXES = ["ทวิ", "ตรี", "จัตวา", "เบญจ", "ฉ", "สัตต", "อัฏฐ", "นว", "ทศ"]
SECTION_NO = r"\d+(?:/\d+|\s(?:" + "|".join(SUFFIXES) + r")(?![ก-๙]))?"

# Line-start section header: "มาตรา 41", "มาตรา 23/1", "มาตรา 47 ทวิ", optionally followed by a marker like [12] or *
SECTION_RE = re.compile(r"^\s*มาตรา\s*(" + SECTION_NO + r")(?:\s*\[\d+\])?\*?(?:\s+(.*))?$")
# A heading is a short line of its own; "หมวด ๘ ความปลอดภัย..." wrapped inside a sentence must not match
HEADING_RE = re.compile(r"^\s*(หมวด|ลักษณะ|ส่วนที่)\s*\d+(?:/\d+)?\s*$")
BARE_HEADING_RE = re.compile(r"^\s*บทเฉพาะกาล\s*$")
# The Act ends here. After it come the schedule, reasons and the amendments' own transitional clauses
END_OF_ACT_RE = re.compile(r"^\s*ผู้รับสนองพระบรมราชโองการ")

# Page furniture in Royal Gazette / consolidated PDFs
NOISE_RES = [
    re.compile(r"^\s*หน้?า\s*\d+[่-๋]?\s*$"),            # some headers lose their tone mark: "หนา 192่"
    re.compile(r"^\s*เล่?ม\s*\d+\s*ตอน(ที่|พิเศษ)\s*\d+.*$"),
    re.compile(r"^\s*ราชกิจจานุเบกษา\s*$"),
    re.compile(r"^\s*-\s*\d+\s*-\s*(สำนักงานคณะกรรมการกฤษฎีกา\s*)?$"),  # "- 12 -" page numbers
    re.compile(r"^\s*\d+\s*$"),                  # bare page numbers
    re.compile(r"^\s*สำนักงานคณะกรรมการกฤษฎีกา\s*(-\s*\d+\s*-\s*)?$"),  # per-page header of Council of State PDFs
    re.compile(r"^\s*\[\d+\]\s*$"),              # footnote numbers collected at the page end
    re.compile(r"^\s*\d+/\d+/\d+\s+\d+:\d+\s*$"),  # browser print header "11/12/68 13:54"
    re.compile(r"^\s*about:blank\s*$"),
    re.compile(r"^\s*\d+/\d+\s*$"),              # "11/52" page counter
    re.compile(r"^\s*\*\[รก\..*\]\s*$"),          # "*[รก.2543/31ก/1/7 เมษายน 2543]"
]

# Footnote: "มาตรา 41 วรรคหนึ่ง แก้ไขเพิ่มเติมโดยพระราชบัญญัติคุ้มครองแรงงาน (ฉบับที่ 9) พ.ศ. 2568"
FOOTNOTE_RE = re.compile(
    r"มาตรา\s*(" + SECTION_NO + r")(?![\d/])(?:(?!มาตรา).){0,80}?(?:แก้ไขเพิ่มเติม|เพิ่ม|ยกเลิก)โดย"
    r"พระราชบัญญัติ((?:(?!มาตรา).){1,60}?)\(ฉบับที่\s*(\d+)\)",
    re.S)

MAX_CHARS = 1500  # a section longer than this is split into parts
WATERMARK_COLOR = 0xe6e6e6  # the grey "สำนักงานคณะกรรมการกฤษฎีกา" text drawn across each page
SMALL_TEXT_RATIO = 0.9      # below this share of the body font size: a footnote or superscript marker
INDENT_POINTS = 15          # further right than the page's left margin by this: a new paragraph

# Fonts that draw shifted Thai marks from the Private Use Area; these are the standard code points
PUA_MAP = str.maketrans({
    "": "ฐ", "": "ญ", "": "ั", "": "ํ", "": "็",
    "": "ิ", "": "ี", "": "ึ", "": "ื",
    "": "่", "": "้", "": "๊", "": "๋", "": "์",
    "": "่", "": "้", "": "๊", "": "๋", "": "์",
    "": "่", "": "้", "": "๊", "": "๋", "": "์",
    "": "ุ", "": "ู", "": "ฺ",
})

# Broken font encoding in the employment Act's PDF: marks came out as Latin letters and digits.
# Each one was read from its context, e.g. ฝUาฝVน = ฝ่าฝืน, เปTด = เปิด, ปXอง = ป้อง, ปุ]ย = ปุ๋ย
BROKEN_MARKS = {
    "emp_consolidated": {"\x1e": "้", "9": "่", "1": "็", "2": "ี", "5": "ั", "D": "์",
                         "O": "ึ", "U": "่", "V": "ื", "T": "ิ", "X": "้", "]": "๋"},
}


# ---------------------------------------------------------------- 1. PDF -> text
def pdf_to_text(path: Path):
    """Return (body, notes). The body drops the watermark and superscript footnote markers,
    which otherwise fuse onto section numbers ('มาตรา ๔๑๒๗' = section 41, footnote 27).
    Footnotes go to notes. Indented lines start with a tab, which split_sections uses."""
    import pymupdf
    pymupdf.TOOLS.mupdf_display_errors(False)
    with pymupdf.open(path) as pdf:
        pages = [page.get_text("dict", sort=True)["blocks"] for page in pdf]

    sizes = Counter()
    for blocks in pages:
        for line in lines_of(blocks):
            for span in line["spans"]:
                sizes[round(span["size"], 1)] += len(span["text"])
    if not sizes:
        return "", ""
    small = sizes.most_common(1)[0][0] * SMALL_TEXT_RATIO

    body, notes = [], []
    for blocks in pages:
        lines = merge_baselines(lines_of(blocks))
        left = min((line["bbox"][0] for line in lines), default=0)
        for line in lines:
            text = "".join(s["text"] for s in line["spans"] if s["size"] >= small or not s["text"].strip())
            if text.strip():
                indent = "\t" if line["bbox"][0] - left > INDENT_POINTS else ""
                body.append(indent + text)
            else:
                notes.append("".join(s["text"] for s in line["spans"]))
    return "\n".join(body), "\n".join(notes)


def lines_of(blocks):
    for block in blocks:
        for line in block.get("lines", []):
            spans = [s for s in line["spans"] if s["color"] != WATERMARK_COLOR]
            if "".join(s["text"] for s in spans).strip():
                yield {"bbox": line["bbox"], "spans": spans}


def merge_baselines(lines):
    """Some PDFs break one printed line into pieces ('มาตรา' and its number apart): rejoin the
    pieces whose vertical extents mostly overlap, left to right."""
    merged = []
    for line in sorted(lines, key=lambda l: l["bbox"][1]):
        x0, y0, x1, y1 = line["bbox"]
        last = merged[-1] if merged else None
        if last:
            overlap = min(y1, last["bbox"][3]) - max(y0, last["bbox"][1])
            if overlap > 0.5 * min(y1 - y0, last["bbox"][3] - last["bbox"][1]):
                last["pieces"].append(line)
                b = last["bbox"]
                last["bbox"] = (min(x0, b[0]), min(y0, b[1]), max(x1, b[2]), max(y1, b[3]))
                continue
        merged.append({"bbox": line["bbox"], "pieces": [line]})
    for m in merged:
        pieces = sorted(m.pop("pieces"), key=lambda l: l["bbox"][0])
        m["spans"] = [s for p in pieces for s in p["spans"]]
    return merged


# ---------------------------------------------------------------- 2. clean the text
def repair_encoding(text: str, source_id: str) -> str:
    # One PDF draws every า as ำ, and a real ำ as " ำ", so "มาตรา" comes out as "มำตรำ"
    if text.count("มำตรำ") > text.count("มาตรา"):
        text = re.sub(r" ?ำ", lambda m: "ำ" if m.group(0) == " ำ" else "า", text)
    # Another stores ำ as a space + า ("ก าหนด"). No Thai word starts with า, so this is always safe
    text = re.sub(r"(?<=[ก-ฮ่-๋]) า", "ำ", text)
    for wrong, right in BROKEN_MARKS.get(source_id, {}).items():
        text = re.sub(r"(?<=[ก-๎])" + re.escape(wrong), right, text)
    return text


def normalize(text: str, source_id: str = "") -> str:
    text = text.translate(PUA_MAP)
    text = repair_encoding(text, source_id)
    text = unicodedata.normalize("NFC", text)
    # Thai PDFs often split sara am (ำ) into nikhahit + sara aa, sometimes with a tone mark in between
    text = re.sub("ํ([่-๋]?)า", lambda m: m.group(1) + "ำ", text)
    text = text.translate(THAI_DIGITS)
    text = text.replace("​", "")             # zero-width spaces
    text = re.sub(r"[ ]+([ั-ฺ็-๎])", r"\1", text)   # a mark never starts a word: "วนั" / "ท ี่"
    text = re.sub("ั +(?=[ก-ฮ])", "ั", text)        # sara a-short always has a following consonant
    text = re.sub(r"([ั-ฺ็-๎])\1+", r"\1", text)     # a mark drawn twice: "นาฬิิกา"
    lines = []
    for line in text.splitlines():
        if any(r.match(line) for r in NOISE_RES):
            continue
        indent = "\t" if line.startswith("\t") else ""
        cleaned = re.sub(r"[ \t]+", " ", line).strip()
        if cleaned:
            lines.append(indent + cleaned)
    return "\n".join(lines)


def section_key(sec: str) -> tuple:
    m = re.fullmatch(r"(\d+)(?:/(\d+)|\s(\S+))?", sec)
    sub = int(m.group(2)) if m.group(2) else SUFFIXES.index(m.group(3)) + 2 if m.group(3) else 0
    return (int(m.group(1)), sub)


# ---------------------------------------------------------------- 3a. consolidated text -> sections
def pick_headers(cand):
    """Choose which line-start 'มาตรา N' are real headers: the increasing run of section numbers
    with the highest score. A wrapped cross-reference ('...ตาม\\nมาตรา 118' inside section 41) cannot
    join it without losing every section in between. A reference to the very next section could,
    so indented lines score higher: real headers are indented, wrapped text is not."""
    best = []  # best[j] = (score, previous index) of the best run ending at candidate j
    for j, (_, key, indented) in enumerate(cand):
        score = 3 if indented else 1
        prev = max((i for i in range(j) if cand[i][1] < key), key=lambda i: best[i][0], default=None)
        best.append((score + (best[prev][0] if prev is not None else 0), prev))
    if not best:
        return set()
    j = max(range(len(best)), key=lambda i: best[i][0])
    picked = set()
    while j is not None:
        picked.add(cand[j][0])
        j = best[j][1]
    return picked


def split_sections(text: str):
    lines = text.splitlines()
    end = next((i for i, l in enumerate(lines) if END_OF_ACT_RE.match(l)), len(lines))
    lines = lines[:end]

    cand = []
    for i, l in enumerate(lines):
        if m := SECTION_RE.match(l):
            cand.append((i, section_key(m.group(1)), l.startswith("\t")))
    headers = pick_headers(cand)

    sections, chapter, current = [], None, None
    i = 0
    while i < len(lines):
        line = lines[i]
        if HEADING_RE.match(line):
            # the title is on the next line, and must not end up in the previous section's text
            has_title = i + 1 < len(lines) and i + 1 not in headers and not HEADING_RE.match(lines[i + 1])
            chapter = line.strip() + (" " + lines[i + 1].strip() if has_title else "")
            i += 2 if has_title else 1
            continue
        if BARE_HEADING_RE.match(line):
            chapter = line.strip()
        elif i in headers:
            m = SECTION_RE.match(line)
            if current:
                sections.append(current)
            current = {"section": m.group(1), "chapter": chapter, "lines": [m.group(2) or ""]}
        elif current:
            current["lines"].append(line)
        i += 1
    if current:
        sections.append(current)
    for s in sections:
        s["text"] = "\n".join(l.strip() for l in s.pop("lines") if l.strip()).strip()
    report_gaps(sections)
    return sections


def report_gaps(sections):
    """Print numbering gaps so you can check them by eye against the PDF."""
    nums = [section_key(s["section"])[0] for s in sections]
    gaps = [(a, b) for a, b in zip(nums, nums[1:]) if b - a > 1]
    if gaps:
        print(f"   [CHECK] numbering gaps (missing sections?): {gaps}")


def section_amendments(text: str, act_name: str):
    """Read the consolidated text's footnotes: section -> the last amendment that changed it.
    Only this Act's own amendments count, not other Acts that also have a 'ฉบับที่ N'."""
    latest = {}
    for m in FOOTNOTE_RE.finditer(text):
        if re.sub(r"\s", "", m.group(2)) == re.sub(r"\s", "", act_name):
            sec, no = re.sub(r"\s+", " ", m.group(1)), int(m.group(3))
            latest[sec] = max(latest.get(sec, 0), no)
    return latest


def act_name_of(title: str) -> str:
    return re.sub(r"^พ\.ร\.บ\.", "", title).split(" พ.ศ.")[0].strip()


# ---------------------------------------------------------------- 3b. amending Act -> replaced / added sections
CLAUSE_END = r"”\s*(?=\n\s*มาตรา\s*\d+\s|\n\s*ผู้รับสนอง|\Z)"
REPLACE_RE = re.compile(
    r"ให้ยกเลิกความในมาตรา\s*(" + SECTION_NO + r")\s*แห่ง.*?ให้ใช้ความต่อไปนี้แทน\s*“(.*?)" + CLAUSE_END,
    re.S)
ADD_RE = re.compile(
    r"ให้เพิ่มความต่อไปนี้เป็นมาตรา\s*(" + SECTION_NO + r")(?:\s*(?:และ\s*)?มาตรา\s*" + SECTION_NO + r")*\s*แห่ง.*?“(.*?)" + CLAUSE_END,
    re.S)
# Part of a section: "ให้ยกเลิกความในวรรคสามของมาตรา 19", "ให้เพิ่มความต่อไปนี้เป็นวรรคสี่ของมาตรา 19"
PARTIAL_RE = re.compile(
    r"ให้(?:ยกเลิกความใน|เพิ่มความต่อไปนี้เป็น)((?:(?!มาตรา).){1,80}?)\s*(?:ของ|ใน)\s*มาตรา\s*(" + SECTION_NO + r")\s*แห่ง.*?“(.*?)" + CLAUSE_END,
    re.S)
CHANGE_HINT_RE = re.compile(r"ให้ยกเลิกความใน|ให้เพิ่มความ")


def parse_amendment(text: str):
    """Return the changed sections, plus anything that needs a human.
    change = "replace" / "add": the quoted text is the whole section.
    change = "partial": only one paragraph or item changed, so the older text stays in force too."""
    found, spans = [], []
    for kind, rx in (("replace", REPLACE_RE), ("add", ADD_RE)):
        for m in rx.finditer(text):
            # one clause can add several sections: "ให้เพิ่มความ...เป็นมาตรา 20/1 มาตรา 20/2 ...".
            # Split only at those numbers, not at a cross-reference that wrapped to a line start
            named = re.findall(r"มาตรา\s*(" + SECTION_NO + r")", m.group(0)[:m.start(2) - m.start()])
            named = named[:1] if kind == "replace" else named
            header = "|".join(re.escape(n) for n in named)
            pieces = re.split(r"(?m)^\s*มาตรา\s*(" + header + r")(?:\s+|$)", m.group(2).strip())
            for sec, body in zip(pieces[1::2], pieces[2::2]):
                found.append({"section": sec, "change": kind, "text": clean_lines(body)})
            spans.append(m.span())
    for m in PARTIAL_RE.finditer(text):
        if not any(a <= m.start() < b for a, b in spans):
            what = re.sub(r"\s+", " ", m.group(1)).strip()
            found.append({"section": m.group(2), "change": "partial", "what": what, "text": clean_lines(m.group(3))})
            spans.append(m.span())
    review = []
    for m in CHANGE_HINT_RE.finditer(text):
        if not any(a <= m.start() < b for a, b in spans):
            review.append(text[m.start(): m.start() + 160].replace("\n", " "))
    return found, review


def clean_lines(text: str) -> str:
    return "\n".join(l.strip() for l in text.splitlines() if l.strip())


# ---------------------------------------------------------------- 4. sections -> chunks with metadata
def to_chunks(sections, row, as_of, per_section=None, effective=None):
    """per_section / effective: from a consolidated text's footnotes, so that section 41 cites
    Amendment No. 9 and its date instead of the 1998 date of the Act as a whole."""
    chunks, part_no = [], Counter()
    for s in sections:
        no = (per_section or {}).get(s["section"], 0 if per_section is not None else int(row["amendment_no"]))
        date = (effective or {}).get((row["law"], no), row["effective"].strip())
        repealed = re.fullmatch(r"\(?ยกเลิก\)?", s["text"].strip()) is not None
        parts = [s["text"]] if len(s["text"]) <= MAX_CHARS else split_long(s["text"])
        label = f"มาตรา {s['section']} ({s['what']})" if s.get("change") == "partial" else f"มาตรา {s['section']}"
        for part in parts:
            part_no[s["section"]] += 1  # keeps ids unique when one Act changes two paragraphs of a section
            i = part_no[s["section"]]
            chunks.append({
                "chunk_id": f"{row['law']}-s{s['section'].replace(' ', '_')}-a{no}-p{i}",
                "law": row["law"],
                "section": s["section"],
                "part": i,
                "chapter": s.get("chapter"),
                "change": s.get("change"),
                # put the section label inside the text so BM25 / embeddings can match "มาตรา 41"
                "text": f"{label} {part}",
                "amendment_no": no,
                "effective_date": date,
                "status": "repealed" if repealed else row["status"],
                "source_id": row["id"],
                "source_url": row["url"].strip(),
                "as_of": as_of,
            })
    return chunks


def split_long(text: str):
    parts, buf = [], ""
    for line in text.splitlines():
        if buf and len(buf) + len(line) > MAX_CHARS:
            parts.append(buf.strip())
            buf = ""
        buf += line + "\n"
    if buf.strip():
        parts.append(buf.strip())
    return parts


# ---------------------------------------------------------------- 5. merge: newer amendments win
def merge(consolidated, amendments):
    """A section in an amending Act newer than the consolidated text supersedes it.
    A partial change does not: the rest of the older section still applies, so it stays
    in force and "partly_amended_by" warns that one of its paragraphs is out of date."""
    latest, partly = {}, {}
    for c in amendments:
        k = (c["law"], c["section"])
        target = partly if c["change"] == "partial" else latest
        if k not in target or c["amendment_no"] > target[k]:
            target[k] = c["amendment_no"]
    for c in consolidated + amendments:
        k = (c["law"], c["section"])
        newer = latest.get(k)
        if newer is not None and c["amendment_no"] < newer and c["status"] == "in_force":
            c["status"] = "superseded"
        elif k in partly and c["amendment_no"] < partly[k] and c["status"] == "in_force":
            c["partly_amended_by"] = partly[k]
    return consolidated + amendments


# ---------------------------------------------------------------- main
def main():
    sys.stdout.reconfigure(encoding="utf-8")  # the Windows console default cannot print Thai

    ap = argparse.ArgumentParser()
    ap.add_argument("--manifest", default="data/manifest.csv")
    ap.add_argument("--raw", default="data/raw")
    ap.add_argument("--out", default="data/processed/chunks.jsonl")
    ap.add_argument("--as-of", default="2026-11-01")
    ap.add_argument("--dump-text", action="store_true", help="also save cleaned .txt for checking")
    args = ap.parse_args()

    with open(args.manifest, encoding="utf-8-sig", newline="") as f:
        rows = list(csv.DictReader(f))
    files = {hashlib.sha256(p.read_bytes()).hexdigest(): p for p in Path(args.raw).rglob("*") if p.is_file()}
    out_dir = Path(args.out).parent
    out_dir.mkdir(parents=True, exist_ok=True)

    included = {r["law"]: int(r["amendment_no"]) for r in rows if r["kind"] == "consolidated"}
    effective = {(r["law"], int(r["amendment_no"])): r["effective"].strip() for r in rows if r["kind"] == "amendment"}
    consolidated, amendments = [], []

    for row in rows:
        if row["kind"] not in ("consolidated", "amendment"):
            continue  # rate announcements etc. go to rates.csv, not the index
        if row["kind"] == "amendment" and int(row["amendment_no"]) <= included.get(row["law"], -1):
            print(f"[SKIP] {row['id']}: already included in the consolidated text")
            continue
        path = files.get(row["sha256"].strip())
        if path is None:
            print(f"[WARN] {row['id']}: no file with this sha256 under {args.raw}; run fetch_corpus.py")
            continue

        body, notes = pdf_to_text(path)
        text, notes = normalize(body, row["id"]), normalize(notes, row["id"])
        if args.dump_text:
            (out_dir / f"{row['id']}.txt").write_text(text, encoding="utf-8")

        if text.count("มาตรา") == 0:
            print(f"[WARN] {row['id']}: no 'มาตรา' found. The text layer may be scanned or garbled; try OCR.")
            continue

        if row["kind"] == "consolidated":
            secs = split_sections(text)
            per_section = section_amendments(notes + "\n" + text, act_name_of(row["title"]))
            unknown = sorted({n for n in per_section.values() if (row["law"], n) not in effective})
            if unknown:
                print(f"   [CHECK] footnotes cite amendments not in the manifest: {unknown}")
            consolidated += to_chunks(secs, row, args.as_of, per_section, effective)
            print(f"[OK] {row['id']}: {len(secs)} sections, {len(per_section)} changed by amendments")
        else:
            secs, review = parse_amendment(text)
            amendments += to_chunks(secs, row, args.as_of)
            print(f"[OK] {row['id']}: {len(secs)} changed sections -> {[s['section'] for s in secs]}")
            for r in review:
                print(f"   [REVIEW BY HAND] {r}…")

    chunks = merge(consolidated, amendments)
    with open(args.out, "w", encoding="utf-8") as f:
        for c in chunks:
            f.write(json.dumps(c, ensure_ascii=False) + "\n")
    counts = Counter(c["status"] for c in chunks)
    print(f"Wrote {len(chunks)} chunks to {args.out}: {dict(counts)}")


if __name__ == "__main__":
    main()
