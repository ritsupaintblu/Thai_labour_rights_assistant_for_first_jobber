"""Turn the model's JSON into a checked Answer, retrying with the error when it is invalid.

The model only names the sections it relies on. Dates, amendments and sources are copied from what the tools
returned, so a citation can never point at something that was not retrieved.
"""

import json
import re

from pydantic import ValidationError
from pythainlp.util import num_to_thaiword

from src.agent.tools.search_law import AS_OF, search_results, section_rows
from src.schemas import Answer, Calculation, Citation, Draft

RETRIES = 2
THAI_DIGITS = ["ศูนย์", "หนึ่ง", "สอง", "สาม", "สี่", "ห้า", "หก", "เจ็ด", "แปด", "เก้า"]
NUMBER_WORDS = [*THAI_DIGITS[1:], "ยี่", "เอ็ด", "สิบ", "ร้อย", "พัน", "หมื่น", "แสน", "ล้าน"]
FORMAT = """ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่น:
{"answer": str, "citations": [{"law": str, "section": str}], "confidence": "high"|"medium"|"low",
 "not_found": bool, "clarifying_question": str|null, "correction": str|null}
เขียนตัวเลขเป็นเลขอารบิก เช่น 120 วัน และอ้างเฉพาะมาตราที่อยู่ในผลค้น
ถ้าผลค้นไม่มีคำตอบ: not_found=true, citations=[], answer="ไม่ทราบ เนื่องจากข้อมูลนี้เกินขอบเขตของเนื้อหาที่มีอยู่"
ถ้าคำถามขาดข้อมูลที่คำตอบขึ้นอยู่กับข้อมูลนั้น เช่น อายุงาน ค่าจ้าง หรือเหตุที่เลิกจ้าง: ใส่คำถามกลับใน clarifying_question ห้ามเดา
ถ้าคำถามตั้งอยู่บนความเชื่อที่ผิด: ใส่สิ่งที่ถูกต้องใน correction และอธิบายใน answer
ตัวอย่าง:
{"answer":"ลาป่วยได้เท่าที่ป่วยจริง","citations":[{"law":"LPA2541","section":"32"}],"confidence":"high","not_found":false,"clarifying_question":null,"correction":null}
{"answer":"ขอข้อมูลเพิ่มก่อนตอบ","citations":[],"confidence":"medium","not_found":false,"clarifying_question":"ทำงานมานานเท่าไร และได้ค่าจ้างเท่าไร","correction":null}
{"answer":"ไม่จริง ลาป่วยไม่ได้จำกัดที่ 30 วัน","citations":[{"law":"LPA2541","section":"32"}],"confidence":"high","not_found":false,"clarifying_question":null,"correction":"ลาป่วยได้เท่าที่ป่วยจริง ส่วน 30 วันทำงานคือจำนวนวันที่นายจ้างต้องจ่ายค่าจ้าง"}"""
# the agent decides refusing, asking back and correcting before this, so its answer step only writes the answer
ANSWER_FORMAT = """ตอบเป็น JSON เท่านั้น ห้ามมีข้อความอื่น: {"answer": str, "citations": [{"law": str, "section": str}], "confidence": "high"|"medium"|"low"}
เขียนตัวเลขเป็นเลขอารบิก เช่น 120 วัน อ้างเฉพาะมาตราที่อยู่ในข้อมูล
ถ้ามีผลคำนวณ ให้บอกจำนวนเงินนั้นในคำตอบ ผลคำนวณถูกต้องแล้ว ห้ามบอกว่าคำนวณไม่ได้ ถ้ามีอัตราทางการ ให้บอกอัตรานั้นในคำตอบ
อัตราและผลคำนวณระบบอ้างแหล่งที่มาให้เอง ถ้าตอบจากสองอย่างนี้อย่างเดียวให้ citations เป็น []"""
TOOL_LABELS = {"อัตราทางการ", "ผลคำนวณ"}
SECTION = re.compile(r"\d+(?:/\d+)?(?:\s*(?:ทวิ|ตรี|จัตวา|เบญจ|ฉ|สัตต|อัฏฐ|นว)(?![ก-๙]))?")
UNITS = {"baht": "บาท", "baht_per_month": "บาทต่อเดือน", "baht_per_day": "บาทต่อวัน", "percent": "เปอร์เซ็นต์"}
GAVE_UP = "ขออภัย ระบบสร้างคำตอบที่ตรวจสอบแหล่งอ้างอิงได้ไม่สำเร็จ กรุณาถามใหม่ หรือสอบถามสายด่วน 1546"


class Evidence:
    """What the tools returned for one question: the only things an answer may rely on."""

    def __init__(self):
        self.sections = {}
        self.rates = []
        self.calculation = None
        self.calculation_section = None

    def add_search(self, result):
        for row in search_results(result):
            self.sections.setdefault((row["law"], row["section"]), row)

    def add_rate(self, result):
        if result.get("status") == "found" and result not in self.rates:
            self.rates.append(result)

    def add_calculation(self, result):
        if result.get("status") == "ok":
            self.calculation = result
            # the rule the amount came from can be cited even when the search did not return that section
            law, section = result["legal_basis"].split(" s.")
            self.calculation_section = section_rows()[(law, section)]
            self.sections.setdefault((law, section), self.calculation_section)


def numbers_in(text):
    return {float(n.replace(",", "")) for n in re.findall(r"\d[\d,]*(?:\.\d+)?", text)}


def thai_number_word(number):
    whole, _, fraction = f"{number:g}".partition(".")
    word = num_to_thaiword(int(whole))
    return f"{word}จุด{''.join(THAI_DIGITS[int(d)] for d in fraction)}" if fraction else word


def mentions_number(number, text):
    """The number in digits, or in Thai words as the statutes write it, not as part of a longer number."""
    if float(number) in numbers_in(text):
        return True
    before = "".join(f"(?<!{w})" for w in NUMBER_WORDS)
    after = "|".join(NUMBER_WORDS)
    return re.search(f"{before}{thai_number_word(number)}(?!{after}|จุด)", text) is not None


def section_id(text):
    """The section number alone: "มาตรา 119 (5)" and "s.119 วรรคสอง" are both section 119, and "47 ทวิ" stays whole."""
    text = text.strip().removeprefix("มาตรา").removeprefix("s.").strip()
    match = SECTION.match(text)
    return " ".join(match.group(0).split()) if match else text


def parse_draft(raw):
    try:
        text = re.sub(r"^```(?:json)?|```$", "", (raw or "").strip()).strip()
        return Draft.model_validate(json.loads(text))
    except (ValueError, ValidationError) as e:
        raise ValueError(f"not valid JSON in the required format: {e}") from e


def build_answer(raw, evidence):
    """The checked Answer, or ValueError saying what the model must fix."""
    draft = parse_draft(raw)
    citations = []
    if draft.clarifying_question:
        draft.not_found = False  # asking is not refusing, though the model often sets both
    if draft.not_found and (evidence.rates or evidence.calculation):
        raise ValueError("a tool returned a result, so answer from it instead of setting not_found=true")
    if draft.not_found or draft.clarifying_question:
        draft.citations = []
    else:
        rows = []
        rate_sources = {r["source"] for r in evidence.rates} | {r["clause"] for r in evidence.rates} | TOOL_LABELS
        for ref in draft.citations:
            if ref.law in rate_sources or ref.section in rate_sources:
                continue  # rates are cited below, with their real clause and date
            section = section_id(ref.section)
            row = evidence.sections.get((ref.law, section))
            if row is None:
                raise ValueError(f"{ref.law} section {section} is not in the search results, so it cannot be cited. "
                                 "Remove it. Rates and calculations are cited automatically, so citations may be []")
            rows.append(row)
        if evidence.calculation_section:
            rows.append(evidence.calculation_section)
        citations = list({(r["law"], r["section"]): Citation(
            law=r["law"], section=r["section"], amendment_no=r["amendment_no"],
            effective_date=r["effective_date"], source=r["source"]) for r in rows}.values())
        citations += [Citation(law=None, section=r["clause"], effective_date=r["effective_from"], source=r["source"])
                      for r in evidence.rates]
        if not citations:
            raise ValueError("an answer needs a citation. If the results do not answer the question, set not_found=true")

    calculation = None
    if evidence.calculation and not draft.not_found and not draft.clarifying_question:
        calculation = Calculation(**{k: evidence.calculation[k] for k in Calculation.model_fields})
        if calculation.value not in numbers_in(draft.answer):
            raise ValueError(f"the answer must state the calculated amount: {calculation.value:g} ({calculation.unit})")
    rates = [r["value"] for r in evidence.rates if r["unit"] != "date"]
    if rates and not calculation and not draft.not_found and not draft.clarifying_question \
            and not numbers_in(draft.answer) & {float(v) for v in rates}:
        raise ValueError(f"the answer must state the rate from get_rate: {rates}")
    return Answer(answer=draft.answer, citations=citations, calculation=calculation, as_of=AS_OF,
                  confidence=draft.confidence, not_found=draft.not_found,
                  clarifying_question=draft.clarifying_question, correction=draft.correction)


def answer_from_tools(evidence):
    """Written by code, for when the model will not state a result the tools found. None if they found nothing."""
    parts = []
    if evidence.calculation:
        c = evidence.calculation
        parts.append(f"จำนวนเงินตามกฎหมายคือ {c['value']:,g} {UNITS.get(c['unit'], c['unit'])} ({c['formula']})")
    elif evidence.rates:
        parts += [f"{r['source']} {r['clause']}: {r['value']} {UNITS.get(r['unit'], r['unit'])} มีผลตั้งแต่ {r['effective_from']}"
                  for r in evidence.rates]
    if not parts:
        return None
    text = json.dumps({"answer": " ".join(parts), "citations": [], "confidence": "medium"}, ensure_ascii=False)
    return build_answer(text, evidence)


def finalize(messages, evidence, complete, answer_format=FORMAT):
    """Ask for the answer and validate it, asking again with the error up to RETRIES times."""
    for attempt in range(RETRIES + 1):
        reply = complete(messages).content
        try:
            return build_answer(reply, evidence)
        except ValueError as e:
            messages = [*messages, {"role": "assistant", "content": reply or ""},
                        {"role": "user", "content": f"คำตอบไม่ผ่านการตรวจ: {e}\n{answer_format}"}]
    return answer_from_tools(evidence) or Answer(answer=GAVE_UP, as_of=AS_OF, confidence="low")
