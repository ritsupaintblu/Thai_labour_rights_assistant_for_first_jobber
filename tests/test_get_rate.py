"""Run from the project root: python -m unittest discover -s tests -t ."""

import unittest
from collections import Counter, defaultdict

from src.agent.tools.get_rate import get_rate, load_rates

AS_OF = "2026-11-01"
# from the summary table on the last page of the announcement: rate -> provinces and districts
SUMMARY_TABLE = {400: 6, 380: 2, 372: 5, 359: 1, 358: 1, 357: 5, 356: 1, 355: 3, 354: 2, 352: 15,
                 351: 3, 350: 3, 349: 5, 348: 5, 347: 16, 345: 4, 337: 3}
THAI_PROVINCES = 77


class TableChecks(unittest.TestCase):
    def setUp(self):
        self.rows, self.titles = load_rates()
        self.wages = [r for r in self.rows if r["name"] == "min_wage_daily" and not r["business"]]

    def test_every_source_is_in_the_manifest(self):
        self.assertEqual([r["source_id"] for r in self.rows if r["source_id"] not in self.titles], [])

    def test_matches_the_announcements_summary_table(self):
        self.assertEqual(dict(Counter(int(r["value"]) for r in self.wages)), SUMMARY_TABLE)

    def test_every_province_has_one_general_rate(self):
        general = Counter(r["province"] for r in self.wages if not r["district"])
        self.assertEqual(len(general), THAI_PROVINCES)
        self.assertEqual([p for p, n in general.items() if n > 1], [])

    def test_periods_do_not_overlap(self):
        periods = defaultdict(list)
        for r in self.rows:
            periods[r["name"], r["province"], r["district"], r["business"]].append(r)
        for key, rows in periods.items():
            rows.sort(key=lambda r: r["effective_from"])
            for earlier, later in zip(rows, rows[1:]):
                self.assertTrue(earlier["effective_to"], key)
                self.assertLess(earlier["effective_to"], later["effective_from"], key)


class Lookups(unittest.TestCase):
    def value(self, *args, **kwargs):
        result = get_rate(*args, **kwargs)
        self.assertEqual(result["status"], "found", result)
        return result["value"]

    def test_social_security(self):
        self.assertEqual(self.value("sso_employee_rate_percent", AS_OF), 5)
        self.assertEqual(self.value("sso_employee_rate_percent", "2022-11-01"), 3)
        self.assertEqual(self.value("sso_wage_base_min", AS_OF), 1650)
        self.assertEqual(self.value("sso_wage_base_max", AS_OF), 17500)
        self.assertEqual(self.value("sso_wage_base_max", "2028-12-31"), 17500)
        self.assertEqual(self.value("sso_wage_base_max", "2029-01-01"), 20000)
        self.assertEqual(self.value("sso_wage_base_max", "2032-01-01"), 23000)

    def test_employee_welfare_fund(self):
        self.assertEqual(self.value("ewf_employee_rate_percent", "2027-01-01"), 0.25)
        self.assertEqual(self.value("ewf_employee_rate_percent", "2031-10-01"), 0.5)
        self.assertEqual(self.value("ewf_collection_start", AS_OF), "2027-01-01")

    def test_minimum_wage(self):
        self.assertEqual(self.value("min_wage_daily", AS_OF, province="กรุงเทพมหานคร"), 400)
        self.assertEqual(self.value("min_wage_daily", AS_OF, province="กทม"), 400)
        self.assertEqual(self.value("min_wage_daily", AS_OF, province="จังหวัดนนทบุรี"), 372)
        self.assertEqual(self.value("min_wage_daily", AS_OF, province="ยะลา"), 337)

    def test_districts_with_their_own_rate(self):
        self.assertEqual(self.value("min_wage_daily", AS_OF, province="เชียงใหม่", district="เมืองเชียงใหม่"), 380)
        self.assertEqual(self.value("min_wage_daily", AS_OF, province="เชียงใหม่", district="อำเภอฝาง"), 357)
        self.assertEqual(self.value("min_wage_daily", AS_OF, province="สงขลา", district="หาดใหญ่"), 380)
        self.assertEqual(self.value("min_wage_daily", AS_OF, province="สุราษฎร์ธานี", district="เกาะสมุย"), 400)

    def test_business_overrides_province(self):
        self.assertEqual(self.value("min_wage_daily", AS_OF, province="ยะลา", business="service"), 400)
        self.assertEqual(self.value("min_wage_daily", AS_OF, business="hotel_type_2_4"), 400)
        self.assertEqual(self.value("min_wage_daily", AS_OF, province="ยะลา", business="other"), 337)

    def test_names_the_source_by_manifest_title(self):
        result = get_rate("sso_employee_rate_percent", AS_OF)
        self.assertEqual(result["source"], "กฎกระทรวงกำหนดอัตราเงินสมทบกองทุนประกันสังคม พ.ศ. 2565")
        self.assertEqual(result["clause"], "ข้อ 3 (2) บัญชี ข.")

    def test_general_answer_warns_about_business_rates(self):
        self.assertIn("สถานบริการ", get_rate("min_wage_daily", AS_OF, province="ยะลา")["note"])

    def test_asks_for_what_it_needs(self):
        self.assertEqual(get_rate("min_wage_daily", AS_OF), {"status": "needs_input", "missing": ["province"]})
        self.assertEqual(get_rate("min_wage_daily", AS_OF, province="เชียงใหม่"), {"status": "needs_input", "missing": ["district"]})

    def test_does_not_guess_outside_the_table(self):
        self.assertEqual(get_rate("sso_wage_base_max", "2020-01-01")["status"], "not_found")
        self.assertEqual(get_rate("min_wage_daily", "2025-06-30", province="กรุงเทพมหานคร")["status"], "not_found")

    def test_rejects_bad_arguments(self):
        for args, kwargs in [(("bonus", AS_OF), {}), (("min_wage_daily", "01/11/2026"), {"province": "ยะลา"}),
                             (("min_wage_daily", None), {}), (("min_wage_daily", AS_OF), {"province": "ไม่มีจังหวัดนี้"}),
                             (("min_wage_daily", AS_OF), {"province": "ยะลา", "business": "bar"}),
                             (("sso_wage_base_max", AS_OF), {"province": "ยะลา"})]:
            self.assertEqual(get_rate(*args, **kwargs)["status"], "invalid", args)


if __name__ == "__main__":
    unittest.main()
