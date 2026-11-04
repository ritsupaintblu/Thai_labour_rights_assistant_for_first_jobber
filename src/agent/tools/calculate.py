"""calculate: statutory money amounts in exact arithmetic. Each rule follows the section named in legal_basis.

The result is a dict with a "status":
    ok          - value, unit, formula, legal_basis, and an explanation of each step in Thai
    needs_input - "missing" lists what to ask the user for
    invalid     - the arguments were rejected; nothing was calculated
Monthly wages use a daily rate of monthly / 30. The Labour Protection Act only states this for hourly rates (s.68).
A figure the user has not given is left out, and comes back in "missing", so the agent asks for it instead of guessing.
The explanation is written here, not by the model, so the tenure band, rate, multiple and ceiling it shows are the
ones the amount was worked out from.
"""

from fractions import Fraction

from src.agent.tools.get_rate import get_rate, thai_date

SEVERANCE_DAYS = [(20, 400), (10, 300), (6, 240), (3, 180), (1, 90)]  # (full years, days of pay), s.118
SEVERANCE_BANDS = {400: "ครบ 20 ปีขึ้นไป", 300: "ครบ 10 ปีแต่ไม่ครบ 20 ปี", 240: "ครบ 6 ปีแต่ไม่ครบ 10 ปี",
                   180: "ครบ 3 ปีแต่ไม่ครบ 6 ปี", 90: "ครบ 1 ปีแต่ไม่ครบ 3 ปี", 30: "ครบ 120 วันแต่ไม่ครบ 1 ปี"}
OVERTIME = {"overtime": (Fraction(3, 2), "LPA2541 s.61"), "holiday_overtime": (Fraction(3), "LPA2541 s.63"),
            "maritime_overtime": (Fraction(5, 4), "MARITIME2558 s.55")}
OVERTIME_RULES = {"overtime": "ทำงานล่วงเวลาในวันทำงาน", "holiday_overtime": "ทำงานล่วงเวลาในวันหยุด",
                  "maritime_overtime": "คนประจำเรือทำงานล่วงเวลา"}
SPECIAL_SEVERANCE_CAP = 360
TENURE_KINDS = {"severance", "special_severance"}
HOUR_KINDS = {*OVERTIME, "holiday_work"}
KINDS = {*TENURE_KINDS, *HOUR_KINDS, "sso_contribution", "ewf_contribution", "compensation", "wage_share"}
# the section each kind follows, so the agent can check that rule against the question before asking for its figures.
# wage_share follows the section named in its own basis
KIND_BASIS = {"severance": "LPA2541 s.118", "special_severance": "LPA2541 s.122", "overtime": "LPA2541 s.61",
              "holiday_work": "LPA2541 s.62", "holiday_overtime": "LPA2541 s.63", "maritime_overtime": "MARITIME2558 s.55",
              "sso_contribution": "SSA2533 s.46", "ewf_contribution": "LPA2541 s.131", "compensation": "WCA2537 s.18"}


def ok(kind, value, unit, formula, legal_basis, explanation, note=None):
    result = {"status": "ok", "kind": kind, "value": float(round(value, 2)), "unit": unit, "formula": formula,
              "legal_basis": legal_basis, "explanation": explanation}
    return {**result, "note": note} if note else result


def invalid(reason):
    return {"status": "invalid", "reason": reason}


def missing(*names):
    return {"status": "needs_input", "missing": list(names)}


def exact(number):
    return Fraction(str(number))


def round_half_up(value):
    return int(value + Fraction(1, 2))


def money(value):
    """12,000 or 82.50: whole amounts without decimals, others to the satang."""
    value = Fraction(value)
    return f"{int(value):,}" if value.denominator == 1 else f"{float(value):,.2f}"


def number(value):
    """A multiple, percentage or count as written in the law: 1.5, 0.25, 70."""
    return f"{float(value):g}"


def is_whole_satang(value):
    return (Fraction(value) * 100).denominator == 1


def daily_rate(wage, wage_type):
    return wage / 30 if wage_type == "monthly" else wage


def hourly_rate(wage, wage_type, hours_per_day):
    if wage_type == "hourly":
        return wage
    return wage / (30 * hours_per_day) if wage_type == "monthly" else wage / hours_per_day


def hourly_steps(wage, wage_type, hours_per_day):
    """How the hourly rate is found, and the term that stands for it in the product. A rate with no exact value in
    satang, such as 25,000 / 30 / 8, stays as the division so the shown result is the exact one."""
    rate = hourly_rate(wage, wage_type, hours_per_day)
    if wage_type == "hourly":
        return [], money(rate)
    division = f"{money(wage)} / 30 / {number(hours_per_day)}" if wage_type == "monthly" else f"{money(wage)} / {number(hours_per_day)}"
    if not is_whole_satang(rate):
        return [], division
    return [f"ค่าจ้างต่อชั่วโมง {division} = {money(rate)} บาท"], money(rate)


def daily_term(wage, wage_type):
    return f"{money(wage)} / 30" if wage_type == "monthly" else money(wage)


def tenure(years, months, days):
    """Full years, and the days left over, counting a month as 30 days."""
    return years + months // 12, (months % 12) * 30 + days


def tenure_text(years, months, days):
    parts = [f"{n} {unit}" for n, unit in ((years, "ปี"), (months, "เดือน"), (days, "วัน")) if n]
    return " ".join(parts) or "0 วัน"


def joined(steps):
    return "; ".join(steps)


def severance(wage, wage_type, years, months, days):
    full_years, rest = tenure(years, months, days)
    pay_days = next((d for y, d in SEVERANCE_DAYS if full_years >= y), 30 if rest >= 120 else 0)
    daily = daily_rate(wage, wage_type)
    value = daily * pay_days
    if not pay_days:
        explanation = f"ทำงาน {tenure_text(years, months, days)} ยังไม่ครบ 120 วัน จึงยังไม่มีสิทธิค่าชดเชยตามมาตรา 118"
        note = "ทำงานไม่ครบ 120 วัน จึงไม่มีสิทธิค่าชดเชยตามมาตรา 118"
    else:
        explanation = joined([f"ทำงาน {tenure_text(years, months, days)} อยู่ในช่วง{SEVERANCE_BANDS[pay_days]} "
                              f"ได้ค่าชดเชยไม่น้อยกว่าค่าจ้างอัตราสุดท้าย {pay_days} วัน",
                              f"{daily_term(wage, wage_type)} x {pay_days} = {money(value)} บาท"])
        note = None
    return ok("severance", value, "baht", f"ค่าจ้างวันละ {float(daily):g} x {pay_days} วัน", "LPA2541 s.118",
              explanation, note)


def special_severance(wage, wage_type, years, months, days):
    full_years, rest = tenure(years, months, days)
    worked = tenure_text(years, months, days)
    if full_years < 6 or (full_years == 6 and rest == 0):
        return ok("special_severance", 0, "baht", "ไม่เข้าเงื่อนไข", "LPA2541 s.122",
                  f"ทำงาน {worked} ยังไม่เกิน 6 ปี จึงไม่มีสิทธิค่าชดเชยพิเศษเพิ่มตามมาตรา 122", "ต้องทำงานเกิน 6 ปี")
    counted = full_years + (1 if rest > 180 else 0)
    pay_days = min(15 * counted, SPECIAL_SEVERANCE_CAP)
    daily = daily_rate(wage, wage_type)
    value = daily * pay_days
    steps = [f"ทำงาน {worked} เกิน 6 ปี ได้ค่าชดเชยพิเศษเพิ่มจากค่าชดเชยตามมาตรา 118 อีกไม่น้อยกว่า 15 วันต่อการทำงานครบ 1 ปี"]
    if rest > 180:
        steps.append(f"เศษที่เกิน 180 วันนับเป็น 1 ปี จึงนับ {counted} ปี")
    days_step = f"15 x {counted} = {15 * counted} วัน"
    if 15 * counted > SPECIAL_SEVERANCE_CAP:
        days_step += f" แต่รวมไม่เกิน {SPECIAL_SEVERANCE_CAP} วัน จึงได้ {SPECIAL_SEVERANCE_CAP} วัน"
    steps += [days_step, f"{daily_term(wage, wage_type)} x {pay_days} = {money(value)} บาท"]
    return ok("special_severance", value, "baht",
              f"ค่าจ้างวันละ {float(daily):g} x min(15 x {counted} ปี, {SPECIAL_SEVERANCE_CAP}) = {pay_days} วัน", "LPA2541 s.122",
              joined(steps))


def rate_percent(name, as_of):
    rate = get_rate(name, as_of)
    return exact(rate["value"]) / 100 if rate["status"] == "found" else None


def sso_contribution(wage, as_of):
    percent = rate_percent("sso_employee_rate_percent", as_of)
    low, high = get_rate("sso_wage_base_min", as_of), get_rate("sso_wage_base_max", as_of)
    if percent is None or low["status"] != "found" or high["status"] != "found":
        return invalid(f"no contribution rate in the table for {as_of}")
    low_value, high_value = exact(low["value"]), exact(high["value"])
    base = max(low_value, min(wage, high_value))
    raw = base * percent
    value = round_half_up(raw)
    if wage > high_value:
        base_step = f"ค่าจ้าง {money(wage)} บาทเกินเพดาน {money(high_value)} บาท จึงใช้ฐาน {money(high_value)} บาท"
    elif wage == high_value:
        base_step = f"ค่าจ้างที่ถึงเพดาน {money(high_value)} บาทขึ้นไปใช้ฐาน {money(high_value)} บาท"
    elif wage < low_value:
        base_step = f"ค่าจ้าง {money(wage)} บาทต่ำกว่าฐานขั้นต่ำ {money(low_value)} บาท จึงใช้ฐาน {money(low_value)} บาท"
    else:
        base_step = f"ใช้ค่าจ้าง {money(wage)} บาทเป็นฐาน เพราะอยู่ระหว่างฐานขั้นต่ำ {money(low_value)} บาทและเพดาน {money(high_value)} บาท"
    product = f"{money(base)} x ร้อยละ {number(percent * 100)} = {money(raw)} บาท"
    if raw != value:
        product += f" ปัดเศษตั้งแต่ 50 สตางค์ขึ้นเป็น {money(value)} บาท"
    return ok("sso_contribution", value, "baht_per_month",
              f"ฐาน {float(base):g} บาท x ร้อยละ {float(percent * 100):g} ปัดเศษตั้งแต่ 50 สตางค์ขึ้น", "SSA2533 s.46",
              joined([base_step, product]))


def ewf_contribution(wage, as_of):
    percent = rate_percent("ewf_employee_rate_percent", as_of)
    if percent is None:
        return invalid(f"no fund rate in the table for {as_of}")
    start = get_rate("ewf_collection_start", as_of)["value"]
    note = None if as_of >= start else f"เริ่มเก็บจริงวันที่ {thai_date(start)}"
    value = wage * percent
    return ok("ewf_contribution", value, "baht_per_month", f"ค่าจ้าง x ร้อยละ {float(percent * 100):g}", "LPA2541 s.131",
              f"เงินสะสมร้อยละ {number(percent * 100)} ของค่าจ้าง: {money(wage)} x ร้อยละ {number(percent * 100)} = {money(value)} บาทต่อเดือน",
              note)


def wage_share(wage, wage_type, percent, days, basis):
    """A share of the daily wage for a number of days, for rules with no kind of their own, such as pay while
    suspended (s.116) or during a temporary closure (s.75). The percentage must be written in the section named,
    so the model cannot pair a rule with a figure from somewhere else."""
    from src.agent.tools.search_law import section_texts
    from src.answer import mentions_number  # imported here: src.answer imports the tools
    if wage_type == "hourly":
        return invalid("wage_share needs a monthly or daily wage")
    law, _, section = (basis or "").partition(" s.")
    text = section_texts().get((law, section))
    if text is None:
        return invalid(f"basis must be an in-force section written like 'LPA2541 s.116', not {basis!r}")
    percent = exact(percent)
    if percent != 100 and not mentions_number(percent, text):
        return invalid(f"{law} s.{section} does not state ร้อยละ {float(percent):g}")
    daily = daily_rate(wage, wage_type)
    value = daily * percent / 100 * exact(days)
    share = "เท่ากับค่าจ้าง" if percent == 100 else f"ร้อยละ {number(percent)} ของค่าจ้าง"
    product = f"{daily_term(wage, wage_type)}" + ("" if percent == 100 else f" x ร้อยละ {number(percent)}")
    return ok("wage_share", value, "baht",
              f"ค่าจ้างวันละ {float(daily):g} x ร้อยละ {float(percent):g} x {days} วัน", f"{law} s.{section}",
              f"มาตรา {section} ให้ได้{share}: {product} x {number(days)} วัน = {money(value)} บาท")


def hours_pay(kind, wage, wage_type, hours, hours_per_day, paid_holiday):
    rate, hours = hourly_rate(wage, wage_type, exact(hours_per_day)), exact(hours)
    steps, term = hourly_steps(wage, wage_type, exact(hours_per_day))
    if kind in OVERTIME:
        multiple, basis = OVERTIME[kind]
        rule = f"{OVERTIME_RULES[kind]} ได้ไม่น้อยกว่า {number(multiple)} เท่าของค่าจ้างต่อชั่วโมง"
        formula = f"ค่าจ้างชั่วโมงละ {float(rate):g} x {float(multiple):g} x {float(hours):g}"
    else:
        if paid_holiday is None and wage_type == "hourly":
            return missing("paid_holiday")
        paid = wage_type == "monthly" if paid_holiday is None else paid_holiday
        multiple, basis = (1 if paid else 2), "LPA2541 s.62"
        who = "ลูกจ้างรายเดือน" if paid_holiday is None and paid else "ลูกจ้าง"
        rule = (f"{who}มีสิทธิได้ค่าจ้างในวันหยุดอยู่แล้ว จึงได้ค่าทำงานในวันหยุดเพิ่มอีกไม่น้อยกว่า 1 เท่าของค่าจ้างต่อชั่วโมง" if paid
                else "ลูกจ้างไม่มีสิทธิได้ค่าจ้างในวันหยุดนั้น จึงได้ค่าทำงานในวันหยุดไม่น้อยกว่า 2 เท่าของค่าจ้างต่อชั่วโมง")
        formula = f"ค่าจ้างชั่วโมงละ {float(rate):g} x {multiple} x {float(hours):g}"
    value = rate * multiple * hours
    explanation = joined([rule, *steps, f"{term} x {number(multiple)} x {number(hours)} ชั่วโมง = {money(value)} บาท"])
    return ok(kind, value, "baht", formula, basis, explanation)


def missing_inputs(kind, wage, years, months, days, hours, percent, basis):
    names = [] if wage is not None else ["wage"]
    if kind in TENURE_KINDS and years is None and months is None and days is None:
        names.append("tenure")
    if kind in HOUR_KINDS and hours is None:
        names.append("hours")
    if kind == "wage_share":
        names += [n for n, v in (("days", days), ("percent", percent), ("basis", basis)) if v is None]
    return names


def calculate(kind, wage=None, wage_type="monthly", years=None, months=None, days=None, hours=None, hours_per_day=8,
              paid_holiday=None, as_of=None, percent=None, basis=None):
    """Inputs are checked by CalculateArgs in the agent loop; a wrong kind or value is rejected here as well."""
    if kind not in KINDS:
        return invalid(f"unknown kind: {kind}")
    if wage is not None and exact(wage) < 0:
        return invalid("wage must be positive")
    wage = None if wage is None or exact(wage) == 0 else wage  # 0 is how the model says it was not given
    names = missing_inputs(kind, wage, years, months, days, hours, percent, basis)
    if names:
        return missing(*names)
    wage = exact(wage)
    if kind == "wage_share":
        return wage_share(wage, wage_type, percent, days, basis)
    years, months, days = years or 0, months or 0, days or 0
    if kind == "severance":
        return severance(wage, wage_type, years, months, days)
    if kind == "special_severance":
        return special_severance(wage, wage_type, years, months, days)
    if kind in HOUR_KINDS:
        return hours_pay(kind, wage, wage_type, hours, hours_per_day, paid_holiday)
    if kind == "compensation":
        value = wage * Fraction(7, 10)
        return ok(kind, value, "baht_per_month", "ค่าจ้างรายเดือน x ร้อยละ 70", "WCA2537 s.18",
                  f"ค่าทดแทนรายเดือนร้อยละ 70 ของค่าจ้างรายเดือน: {money(wage)} x ร้อยละ 70 = {money(value)} บาทต่อเดือน",
                  "ไม่รวมเพดานขั้นต่ำและขั้นสูงที่กระทรวงแรงงานประกาศ")
    if kind in ("sso_contribution", "ewf_contribution"):
        if as_of is None:
            return missing("as_of")
        return (sso_contribution if kind == "sso_contribution" else ewf_contribution)(wage, as_of)
    return invalid(f"unknown kind: {kind}")
