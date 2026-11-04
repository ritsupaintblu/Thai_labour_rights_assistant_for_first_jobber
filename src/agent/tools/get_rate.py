"""get_rate: look up an official rate in data/rates.csv for a given date.

Rates are exact and change over time, so they come from this versioned table instead of retrieval.
The result is always a dict with a "status":
    found      - value, unit, effective dates and the source's manifest title
    not_found  - the table has no rate for that date, so the assistant must not guess
    needs_input - "missing" lists what to ask the user for, including a province the table does not know
    invalid    - the arguments were rejected; nothing was looked up
"""

import csv
from datetime import date
from functools import lru_cache
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BUSINESSES = {"hotel_type_2_4", "service", "other"}
PROVINCE_ALIASES = {"กรุงเทพ": "กรุงเทพมหานคร", "กรุงเทพฯ": "กรุงเทพมหานคร", "กทม": "กรุงเทพมหานคร", "กทม.": "กรุงเทพมหานคร"}
MIN_WAGE = "min_wage_daily"
# what a rate whose value is a date stands for, in Thai
DATE_RATES = {"ewf_collection_start": "วันเริ่มจัดเก็บเงินสะสมและเงินสมทบกองทุนสงเคราะห์ลูกจ้าง"}
THAI_MONTHS = ["มกราคม", "กุมภาพันธ์", "มีนาคม", "เมษายน", "พฤษภาคม", "มิถุนายน", "กรกฎาคม", "สิงหาคม", "กันยายน",
               "ตุลาคม", "พฤศจิกายน", "ธันวาคม"]


def thai_date(iso):
    """2027-01-01 as 1 มกราคม 2570. The model copied ISO dates from the table and confused them with each other."""
    day = date.fromisoformat(iso)
    return f"{day.day} {THAI_MONTHS[day.month - 1]} {day.year + 543}"


@lru_cache(maxsize=1)
def load_rates():
    # utf-8-sig: like the manifest, the table is saved with a BOM so Excel shows the Thai correctly
    with open(ROOT / "data" / "rates.csv", encoding="utf-8-sig", newline="") as f:
        rows = [{k: v.strip() for k, v in row.items()} for row in csv.DictReader(f)]
    with open(ROOT / "data" / "manifest.csv", encoding="utf-8-sig", newline="") as f:
        titles = {r["id"]: r["title"].strip() for r in csv.DictReader(f)}
    return rows, titles


def rate_description(name):
    """What a rate is, from its source in the table, so the agent can check it fits the question before asking for
    the details it needs."""
    rows, titles = load_rates()
    sources = dict.fromkeys(titles[r["source_id"]] for r in rows if r["name"] == name)
    places = " แตกต่างตามจังหวัดและพื้นที่" if any(r["province"] for r in rows if r["name"] == name) else ""
    return f"{' และ '.join(sources)} ({name}) ของประเทศไทย{places}"


def place_in(question):
    """The (province, district) the question names, from the places in the rates table, or (None, None).
    A district with its own rate, such as เกาะสมุย, also gives its province. The model often guessed these."""
    rows, _ = load_rates()
    text = "".join((question or "").split())
    districts = {r["district"]: r["province"] for r in rows if r["district"]}
    district = max((d for d in districts if d in text), key=len, default=None)
    if district:
        return districts[district], district
    names = {r["province"]: r["province"] for r in rows if r["province"]} | PROVINCE_ALIASES
    found = max((n for n in names if n in text), key=len, default=None)
    return (names[found], None) if found else (None, None)


def clean_place(text, prefix):
    text = (text or "").strip()
    return text[len(prefix):].strip() if text.startswith(prefix) else text


def in_period(row, day):
    return row["effective_from"] <= day and (not row["effective_to"] or day <= row["effective_to"])


def parse_value(row):
    if row["unit"] == "date":
        return row["value"]
    return float(row["value"]) if "." in row["value"] else int(row["value"])


def invalid(reason):
    return {"status": "invalid", "reason": reason}


def found(row, titles):
    result = {"status": "found", "name": row["name"], "value": parse_value(row), "unit": row["unit"],
              "effective_from": row["effective_from"], "effective_to": row["effective_to"] or None,
              "source": titles[row["source_id"]], "clause": row["clause"]}
    if row["note"]:
        result["note"] = row["note"]
    return result


def find_min_wage(rows, province, district, business):
    if business in ("hotel_type_2_4", "service"):
        return [r for r in rows if r["business"] == business], None
    if not province:
        return [], ["province"]
    in_province = [r for r in rows if r["province"] == province]
    if not in_province:
        return None, None
    districts = {r["district"] for r in in_province if r["district"]}
    if districts and not district:
        return [], ["district"]
    matches = [r for r in in_province if r["district"] == district]
    return matches or [r for r in in_province if not r["district"]], None


def get_rate(name, as_of, province=None, district=None, business=None):
    rows, titles = load_rates()
    if name not in {r["name"] for r in rows}:
        return invalid(f"unknown rate name: {name}")
    try:
        day = date.fromisoformat(as_of).isoformat()
    except (TypeError, ValueError):
        return invalid("as_of must be a date in YYYY-MM-DD form")
    if name != MIN_WAGE and (province or district or business):
        return invalid(f"{name} does not depend on province, district or business")
    if business and business not in BUSINESSES:
        return invalid(f"business must be one of {sorted(BUSINESSES)}")

    current = [r for r in rows if r["name"] == name and in_period(r, day)]
    if not current:
        return {"status": "not_found", "reason": f"no {name} in the table for {day}"}
    if name != MIN_WAGE:
        return found(current[0], titles)

    province = clean_place(province, "จังหวัด")
    province = PROVINCE_ALIASES.get(province, province)
    matches, missing = find_min_wage(current, province, clean_place(district, "อำเภอ"), business)
    if missing:
        return {"status": "needs_input", "missing": missing}
    if matches is None:  # such as "ทุกจังหวัด": only the user can say where they work
        return {"status": "needs_input", "missing": ["province"], "reason": f"unknown province: {province}"}
    result = found(matches[0], titles)
    if not business:
        result["note"] = "โรงแรมประเภท 2 3 และ 4 และสถานบริการใช้อัตรา 400 บาททุกจังหวัด"
    return result
