"""calculate: statutory money amounts in exact arithmetic. Each rule follows the section named in legal_basis.

The result is a dict with a "status":
    ok          - value, unit, formula and legal_basis
    needs_input - "missing" lists what to ask the user for
    invalid     - the arguments were rejected; nothing was calculated
Monthly wages use a daily rate of monthly / 30. The Labour Protection Act only states this for hourly rates (s.68).
"""

from fractions import Fraction

from src.agent.tools.get_rate import get_rate

SEVERANCE_DAYS = [(20, 400), (10, 300), (6, 240), (3, 180), (1, 90)]  # (full years, days of pay), s.118
OVERTIME = {"overtime": (Fraction(3, 2), "LPA2541 s.61"), "holiday_overtime": (Fraction(3), "LPA2541 s.63"),
            "maritime_overtime": (Fraction(5, 4), "MARITIME2558 s.55")}
SPECIAL_SEVERANCE_CAP = 360


def ok(kind, value, unit, formula, legal_basis, note=None):
    result = {"status": "ok", "kind": kind, "value": float(round(value, 2)), "unit": unit, "formula": formula,
              "legal_basis": legal_basis}
    return {**result, "note": note} if note else result


def invalid(reason):
    return {"status": "invalid", "reason": reason}


def missing(*names):
    return {"status": "needs_input", "missing": list(names)}


def exact(number):
    return Fraction(str(number))


def round_half_up(value):
    return int(value + Fraction(1, 2))


def daily_rate(wage, wage_type):
    return wage / 30 if wage_type == "monthly" else wage


def hourly_rate(wage, wage_type, hours_per_day):
    if wage_type == "hourly":
        return wage
    return wage / (30 * hours_per_day) if wage_type == "monthly" else wage / hours_per_day


def tenure(years, months, days):
    """Full years, and the days left over, counting a month as 30 days."""
    return years + months // 12, (months % 12) * 30 + days


def severance(wage, wage_type, years, months, days):
    full_years, rest = tenure(years, months, days)
    pay_days = next((d for y, d in SEVERANCE_DAYS if full_years >= y), 30 if rest >= 120 else 0)
    note = None if pay_days else "ทำงานไม่ครบ 120 วัน จึงไม่มีสิทธิค่าชดเชยตามมาตรา 118"
    return ok("severance", daily_rate(wage, wage_type) * pay_days, "baht", f"ค่าจ้างวันละ x {pay_days} วัน", "LPA2541 s.118", note)


def special_severance(wage, wage_type, years, months, days):
    full_years, rest = tenure(years, months, days)
    if full_years < 6 or (full_years == 6 and rest == 0):
        return ok("special_severance", 0, "baht", "ไม่เข้าเงื่อนไข", "LPA2541 s.122", "ต้องทำงานเกิน 6 ปี")
    counted = full_years + (1 if rest > 180 else 0)
    pay_days = min(15 * counted, SPECIAL_SEVERANCE_CAP)
    return ok("special_severance", daily_rate(wage, wage_type) * pay_days, "baht",
              f"ค่าจ้างวันละ x min(15 x {counted} ปี, {SPECIAL_SEVERANCE_CAP}) วัน", "LPA2541 s.122")


def rate_percent(name, as_of):
    rate = get_rate(name, as_of)
    return exact(rate["value"]) / 100 if rate["status"] == "found" else None


def sso_contribution(wage, as_of):
    percent = rate_percent("sso_employee_rate_percent", as_of)
    low, high = get_rate("sso_wage_base_min", as_of), get_rate("sso_wage_base_max", as_of)
    if percent is None or low["status"] != "found" or high["status"] != "found":
        return invalid(f"no contribution rate in the table for {as_of}")
    base = max(exact(low["value"]), min(wage, exact(high["value"])))
    return ok("sso_contribution", round_half_up(base * percent), "baht_per_month",
              f"ฐาน {float(base):g} บาท x ร้อยละ {float(percent * 100):g} ปัดเศษตั้งแต่ 50 สตางค์ขึ้น", "SSA2533 s.46")


def ewf_contribution(wage, as_of):
    percent = rate_percent("ewf_employee_rate_percent", as_of)
    if percent is None:
        return invalid(f"no fund rate in the table for {as_of}")
    start = get_rate("ewf_collection_start", as_of)["value"]
    note = None if as_of >= start else f"เริ่มเก็บจริงวันที่ {start}"
    return ok("ewf_contribution", wage * percent, "baht_per_month", f"ค่าจ้าง x ร้อยละ {float(percent * 100):g}",
              "LPA2541 s.131", note)


def calculate(kind, wage, wage_type="monthly", years=0, months=0, days=0, hours=None, hours_per_day=8,
              paid_holiday=None, as_of=None):
    """Inputs are checked by CalculateArgs in the agent loop; a wrong kind or value is rejected here as well."""
    wage = exact(wage)
    if wage <= 0:
        return invalid("wage must be positive")
    if kind == "severance":
        return severance(wage, wage_type, years, months, days)
    if kind == "special_severance":
        return special_severance(wage, wage_type, years, months, days)
    if kind in OVERTIME or kind == "holiday_work":
        if hours is None:
            return missing("hours")
        rate, hours = hourly_rate(wage, wage_type, exact(hours_per_day)), exact(hours)
    if kind in OVERTIME:
        multiple, basis = OVERTIME[kind]
        return ok(kind, rate * multiple * hours, "baht", f"ค่าจ้างชั่วโมงละ {float(rate):g} x {float(multiple):g} x {float(hours):g}", basis)
    if kind == "holiday_work":
        if paid_holiday is None and wage_type == "hourly":
            return missing("paid_holiday")
        paid = wage_type == "monthly" if paid_holiday is None else paid_holiday
        multiple = 1 if paid else 2
        return ok(kind, rate * multiple * hours, "baht", f"ค่าจ้างชั่วโมงละ {float(rate):g} x {multiple} x {float(hours):g}", "LPA2541 s.62")
    if kind == "compensation":
        return ok(kind, wage * Fraction(7, 10), "baht_per_month", "ค่าจ้างรายเดือน x ร้อยละ 70", "WCA2537 s.18",
                  "ไม่รวมเพดานขั้นต่ำและขั้นสูงที่กระทรวงแรงงานประกาศ")
    if kind in ("sso_contribution", "ewf_contribution"):
        if as_of is None:
            return missing("as_of")
        return (sso_contribution if kind == "sso_contribution" else ewf_contribution)(wage, as_of)
    return invalid(f"unknown kind: {kind}")
