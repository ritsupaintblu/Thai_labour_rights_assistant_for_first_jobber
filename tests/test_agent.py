"""Run from the project root: python -m unittest discover -s tests -t ."""

import json
import unittest
from types import SimpleNamespace
from unittest.mock import patch

from fastapi.testclient import TestClient

from eval.run_answers import (behaviour_row, citation_hit, correction_ok, number_ok, refusal_ok, source_titles,
                              supporting_ok)

from src.agent.loop import RULE, WRITE, Agent, focus, rate_text
from src.agent.steps import (BELIEF, BELIEF_REPORTED, CHECK, DEDUCTION_TOPICS, DEPENDS, REWRITE, SCOPE, applies,
                             asks_own_deduction, check_belief, check_depends, check_results, penalty_sections,
                             question_date, refusal_scope, repealing_sections)
from src.agent.tools.search_law import penalties
from src.agent.tools.calculate import calculate
from src.agent.tools.get_rate import get_rate, place_in
from src.agent.tools.search_law import SearchLaw, section_rows
from src.answer import FORMAT, GAVE_UP, Evidence, build_answer, mentions_number, section_id, ungrounded_numbers
from src.retrieval.corpus import Hit
from src.retrieval.rerank import search_both

CHUNK = {"chunk_id": "x", "law": "LPA2541", "section": "41", "text": "ลาคลอดได้ไม่เกิน 120 วัน", "amendment_no": 9,
         "effective_date": "2025-12-07", "source_id": "lpa"}


def draft(**fields):
    return json.dumps({"answer": "ลาคลอดได้ 120 วัน", "citations": [{"law": "LPA2541", "section": "41"}], **fields}, ensure_ascii=False)


class FakeRetriever:
    def search(self, query, k=5):
        return [Hit(CHUNK, 0.9)]


def search_law(min_score=0.0):
    return SearchLaw(FakeRetriever(), min_score, titles={"lpa": "พ.ร.บ.คุ้มครองแรงงาน"})


def text(content):
    return SimpleNamespace(content=content, tool_calls=None)


def tool_call(name, arguments):
    function = SimpleNamespace(name=name, arguments=json.dumps(arguments, ensure_ascii=False))
    return SimpleNamespace(content=None, tool_calls=[SimpleNamespace(id="1", function=function)])


def scripted(*replies):
    """A model that says each reply in turn, and repeats the last."""
    left = list(replies)
    return lambda messages, tools=None: left.pop(0) if len(left) > 1 else left[0]


class Calculate(unittest.TestCase):
    def amount(self, *args, **kwargs):
        return calculate(*args, **kwargs)["value"]

    def test_severance_tiers_from_section_118(self):
        self.assertEqual(self.amount("severance", 25000, years=3, months=2), 150000)
        self.assertEqual(self.amount("severance", 400, "daily", years=12), 120000)
        self.assertEqual(self.amount("severance", 18000, months=8), 18000)
        self.assertEqual(self.amount("severance", 15000, years=1), 45000)
        self.assertEqual(self.amount("severance", 30000, years=25), 400000)
        self.assertEqual(self.amount("severance", 21000, years=7), 168000)

    def test_under_120_days_gets_no_severance(self):
        self.assertEqual(self.amount("severance", 15000, days=100), 0)
        self.assertEqual(self.amount("severance", 15000, days=119), 0)
        self.assertEqual(self.amount("severance", 15000, days=120), 15000)

    def test_twelve_months_is_a_full_year(self):
        self.assertEqual(self.amount("severance", 15000, months=12), 45000)

    def test_special_severance_needs_more_than_six_years(self):
        self.assertEqual(self.amount("special_severance", 500, "daily", years=6), 0)
        self.assertEqual(self.amount("special_severance", 500, "daily", years=8), 60000)

    def test_special_severance_rounds_up_over_180_days_and_caps_at_360(self):
        self.assertEqual(self.amount("special_severance", 500, "daily", years=8, months=6, days=1), 67500)
        self.assertEqual(self.amount("special_severance", 500, "daily", years=30), 180000)

    def test_overtime_multiples(self):
        self.assertEqual(self.amount("overtime", 125, "hourly", hours=2), 375)
        self.assertEqual(self.amount("holiday_overtime", 75, "hourly", hours=2), 450)
        self.assertEqual(self.amount("maritime_overtime", 36000, hours=2), 375)

    def test_holiday_work_depends_on_holiday_pay(self):
        self.assertEqual(self.amount("holiday_work", 100, "hourly", hours=8, paid_holiday=True), 800)
        self.assertEqual(self.amount("holiday_work", 400, "daily", hours=8), 800)
        self.assertEqual(calculate("holiday_work", 100, "hourly", hours=8)["status"], "needs_input")

    def test_social_security_uses_the_wage_base_and_rounds_half_up(self):
        self.assertEqual(self.amount("sso_contribution", 20000, as_of="2026-06-01"), 875)
        self.assertEqual(self.amount("sso_contribution", 12000, as_of="2026-06-01"), 600)
        self.assertEqual(self.amount("sso_contribution", 1500, as_of="2026-06-01"), 83)

    def test_welfare_fund_and_compensation(self):
        self.assertEqual(self.amount("ewf_contribution", 20000, as_of="2027-01-01"), 50)
        self.assertEqual(self.amount("compensation", 15000), 10500)

    def test_a_figure_the_user_did_not_give_is_asked_for(self):
        self.assertEqual(calculate("severance")["missing"], ["wage", "tenure"])
        self.assertEqual(calculate("severance", 0, years=3)["missing"], ["wage"])
        self.assertEqual(calculate("severance", 15000)["missing"], ["tenure"])
        self.assertEqual(calculate("overtime", wage_type="hourly", hours=2)["missing"], ["wage"])

    def test_wage_share_needs_the_percentage_its_section_states(self):
        self.assertEqual(self.amount("wage_share", 600, "daily", days=7, percent=50, basis="LPA2541 s.116"), 2100)
        self.assertEqual(self.amount("wage_share", 18000, days=60, percent=100, basis="LPA2541 s.59"), 36000)
        self.assertEqual(calculate("wage_share", 600, "daily", days=7, percent=70, basis="LPA2541 s.116")["status"], "invalid")
        self.assertEqual(calculate("wage_share", 600, "daily", days=7, percent=50, basis="s.116")["status"], "invalid")

    def test_the_explanation_shows_the_band_rate_and_ceiling_used(self):
        self.assertIn("ครบ 3 ปีแต่ไม่ครบ 6 ปี", calculate("severance", 25000, years=3, months=2)["explanation"])
        self.assertIn("25,000 / 30 x 180 = 150,000 บาท", calculate("severance", 25000, years=3, months=2)["explanation"])
        self.assertIn("ค่าจ้างต่อชั่วโมง 400 / 8 = 50 บาท", calculate("overtime", 400, "daily", hours=2)["explanation"])
        self.assertIn("1.5 เท่า", calculate("overtime", 400, "daily", hours=2)["explanation"])
        self.assertIn("เกินเพดาน 17,500 บาท", calculate("sso_contribution", 35000, as_of="2026-06-01")["explanation"])
        self.assertIn("82.50 บาท ปัดเศษ", calculate("sso_contribution", 1500, as_of="2026-06-01")["explanation"])
        self.assertIn("รวมไม่เกิน 360 วัน", calculate("special_severance", 24000, years=26)["explanation"])
        self.assertEqual(calculate("ewf_contribution", 20000, as_of="2026-11-01")["note"], "เริ่มเก็บจริงวันที่ 1 มกราคม 2570")

    def test_a_rate_with_no_exact_satang_is_not_rounded_in_the_explanation(self):
        # 25,000 / 30 / 8 is 104.1666..., so showing 104.17 x 1.5 x 2 would not give the amount shown
        explanation = calculate("overtime", 25000, hours=2)["explanation"]
        self.assertIn("25,000 / 30 / 8 x 1.5 x 2 ชั่วโมง = 312.50 บาท", explanation)
        self.assertNotIn("104", explanation)

    def test_bad_input_is_rejected(self):
        self.assertEqual(calculate("severance", -1)["status"], "invalid")
        self.assertEqual(calculate("bonus", 100)["status"], "invalid")
        self.assertEqual(calculate("sso_contribution", 100)["status"], "needs_input")
        self.assertEqual(calculate("sso_contribution", 100, as_of="not a date")["status"], "invalid")


class BuildAnswer(unittest.TestCase):
    def setUp(self):
        self.evidence = Evidence()
        self.evidence.add_search(search_law()("q"))

    def test_metadata_comes_from_the_tools_not_the_model(self):
        answer = build_answer(draft(citations=[{"law": "LPA2541", "section": "มาตรา 41", "effective_date": "1900-01-01"}]), self.evidence)
        self.assertEqual(answer.citations[0].section, "41")
        self.assertEqual(answer.citations[0].effective_date, "2025-12-07")
        self.assertEqual(answer.citations[0].source, "พ.ร.บ.คุ้มครองแรงงาน")

    def test_rejects_a_section_that_was_not_retrieved(self):
        with self.assertRaisesRegex(ValueError, "not in the search results"):
            build_answer(draft(citations=[{"law": "LPA2541", "section": "99"}]), self.evidence)

    def test_rejects_an_answer_with_no_citation(self):
        with self.assertRaisesRegex(ValueError, "needs a citation"):
            build_answer(draft(citations=[]), self.evidence)

    def test_not_found_and_clarifying_need_no_citation(self):
        self.assertTrue(build_answer(draft(citations=[], not_found=True), Evidence()).not_found)
        self.assertEqual(build_answer(draft(citations=[], clarifying_question="ทำงานนานเท่าไร"), Evidence()).citations, [])

    def test_rejects_broken_json(self):
        with self.assertRaisesRegex(ValueError, "not valid JSON"):
            build_answer("ลาคลอดได้ 120 วัน", self.evidence)

    def test_accepts_a_fenced_reply(self):
        self.assertEqual(build_answer(f"```json\n{draft()}\n```", self.evidence).citations[0].section, "41")

    def test_answer_must_state_the_calculated_amount(self):
        self.evidence.add_calculation(calculate("severance", 25000, years=3))
        with self.assertRaisesRegex(ValueError, "150000"):
            build_answer(draft(answer="ได้ 140,000 บาท"), self.evidence)
        self.assertEqual(build_answer(draft(answer="ได้ 150,000 บาท"), self.evidence).calculation.value, 150000)

    def test_a_one_word_answer_is_sent_back(self):
        with self.assertRaisesRegex(ValueError, "สั้นเกินไป"):
            build_answer(draft(answer="ได้"), self.evidence, min_chars=40)
        long_enough = "ลาคลอดได้ไม่เกิน 120 วัน โดยนับรวมวันหยุดที่อยู่ระหว่างวันลาด้วย"
        self.assertEqual(build_answer(draft(answer=long_enough), self.evidence, min_chars=40).answer, long_enough)
        self.assertTrue(build_answer(draft(answer="ไม่ทราบ", not_found=True, citations=[]), self.evidence, min_chars=40).not_found)

    def test_code_adds_the_working_after_the_answer(self):
        self.evidence.add_calculation(calculate("severance", 25000, years=3))
        answer = build_answer(draft(answer="ได้ 150,000 บาท"), self.evidence)
        self.assertTrue(answer.answer.startswith("ได้ 150,000 บาท\n\nวิธีคิด: ทำงาน 3 ปี อยู่ในช่วงครบ 3 ปีแต่ไม่ครบ 6 ปี"))
        self.assertEqual(answer.calculation.explanation, calculate("severance", 25000, years=3)["explanation"])

    def test_a_rate_used_is_cited_automatically(self):
        self.evidence.add_rate({"status": "found", "name": "min_wage_daily", "value": 372, "unit": "baht_per_day", "clause": "ข้อ 4", "effective_from": "2025-07-01", "source": "ประกาศ"})
        self.assertEqual(build_answer(draft(answer="วันละ 372 บาท"), self.evidence).citations[-1].section, "ข้อ 4")


    def test_calculation_is_cited_even_if_the_search_missed_its_section(self):
        evidence = Evidence()
        evidence.add_calculation(calculate("severance", 30000, years=25))
        answer = build_answer(draft(answer="ได้ 400,000 บาท", citations=[]), evidence)
        self.assertEqual((answer.citations[0].law, answer.citations[0].section), ("LPA2541", "118"))
        self.assertEqual(answer.citations[0].effective_date, section_rows()[("LPA2541", "118")]["effective_date"])

    def test_model_may_cite_the_section_behind_its_calculation(self):
        evidence = Evidence()
        evidence.add_calculation(calculate("severance", 30000, years=25))
        answer = build_answer(draft(answer="ได้ 400,000 บาท", citations=[{"law": "LPA2541", "section": "118"}]), evidence)
        self.assertEqual(len(answer.citations), 1)

    def test_every_calculation_rule_is_an_in_force_section(self):
        for kind, kwargs in [("severance", {"years": 1}), ("special_severance", {"years": 8}), ("overtime", {"hours": 1}),
                             ("holiday_work", {"hours": 1}), ("holiday_overtime", {"hours": 1}),
                             ("maritime_overtime", {"hours": 1}), ("sso_contribution", {"as_of": "2026-11-01"}),
                             ("ewf_contribution", {"as_of": "2027-01-01"}), ("compensation", {})]:
            law, section = calculate(kind, 15000, **kwargs)["legal_basis"].split(" s.")
            self.assertIn((law, section), section_rows(), kind)

    def test_citing_a_rate_announcement_by_name_is_not_an_error(self):
        evidence = Evidence()
        evidence.add_rate({"status": "found", "name": "min_wage_daily", "value": 372, "unit": "baht_per_day", "clause": "ข้อ 4", "effective_from": "2025-07-01", "source": "ประกาศ"})
        answer = build_answer(draft(answer="วันละ 372 บาท", citations=[{"law": "ประกาศ", "section": "ข้อ 4"}]), evidence)
        self.assertEqual([c.section for c in answer.citations], ["ข้อ 4"])

    def test_still_rejects_a_made_up_law_when_a_rate_was_used(self):
        evidence = Evidence()
        evidence.add_rate({"status": "found", "name": "min_wage_daily", "value": 372, "unit": "baht_per_day", "clause": "ข้อ 4", "effective_from": "2025-07-01", "source": "ประกาศ"})
        with self.assertRaisesRegex(ValueError, "not in the search results"):
            build_answer(draft(answer="วันละ 372 บาท", citations=[{"law": "ไม่มีจริง", "section": "9"}]), evidence)


class SectionId(unittest.TestCase):
    def test_paragraphs_and_prefixes_are_dropped(self):
        self.assertEqual(section_id("มาตรา 119 (5)"), "119")
        self.assertEqual(section_id("s.46"), "46")
        self.assertEqual(section_id("118 วรรคหนึ่ง"), "118")
        self.assertEqual(section_id("41/1"), "41/1")
        self.assertEqual(section_id("47 ทวิ"), "47 ทวิ")
        self.assertEqual(section_id("47 สัตต"), "47 สัตต")

    def test_every_section_in_the_corpus_reads_as_itself(self):
        self.assertEqual([s for _, s in section_rows() if section_id(s) != s], [])


class MentionsNumber(unittest.TestCase):
    def test_digits_with_commas(self):
        self.assertTrue(mentions_number(150000, "ได้ 150,000 บาท"))

    def test_thai_words_as_the_statutes_write_them(self):
        self.assertTrue(mentions_number(48, "สัปดาห์หนึ่งต้องไม่เกินสี่สิบแปดชั่วโมง"))
        self.assertTrue(mentions_number(3, "ภายในสามวันนับแต่วันที่เลิกจ้าง"))
        self.assertTrue(mentions_number(1.25, "ไม่น้อยกว่าหนึ่งจุดสองห้าเท่า"))

    def test_part_of_a_longer_number_does_not_count(self):
        self.assertFalse(mentions_number(3, "ภายในสามสิบวัน"))
        self.assertFalse(mentions_number(30, "สามสิบห้าวัน"))
        self.assertFalse(mentions_number(8, "สี่สิบแปดชั่วโมง"))
        self.assertFalse(mentions_number(1, "หนึ่งร้อยวัน"))
        self.assertFalse(mentions_number(3, "ได้ 300 บาท"))


class NumberCheck(unittest.TestCase):
    def check(self, answer, calculation=None, correction=None, **label):
        question = {"expected_number": 48, "expected_numbers": [48], "expected_behavior": "answer", **label}
        return number_ok(question, {"answer": answer, "correction": correction, "calculation": calculation})

    def test_every_labelled_figure_is_needed(self):
        self.assertFalse(self.check("สัปดาห์ละ 48 ชั่วโมง", expected_numbers=[48, 42]))
        self.assertTrue(self.check("สัปดาห์ละ 48 หรือ 42 ชั่วโมง", expected_numbers=[48, 42]))

    def test_an_outdated_figure_fails_even_beside_the_right_one(self):
        self.assertFalse(self.check("ลาได้ 120 วัน หรือ 98 วัน", expected_number=120, expected_numbers=[120], wrong_numbers=[98]))

    def test_a_correction_may_name_the_figure_it_corrects(self):
        self.assertTrue(self.check("ขั้นต่ำ 6 วัน ไม่ใช่ 10 วัน", expected_number=6, expected_numbers=[6], wrong_numbers=[10],
                                   expected_behavior="correct_premise"))

    def test_the_calculated_amount_must_be_the_expected_one(self):
        self.assertFalse(self.check("ได้ 48 บาท หรือ 50 บาท", calculation={"value": 50}))
        self.assertTrue(self.check("ได้ 48 บาท", calculation={"value": 48}))

    def test_a_question_with_no_expected_number_is_not_scored(self):
        self.assertIsNone(self.check("ตอบ", expected_number=None))


class SearchFloor(unittest.TestCase):
    def test_below_the_floor_is_not_found(self):
        self.assertEqual(search_law(min_score=0.95)("q")["status"], "not_found")
        self.assertEqual(search_law(min_score=0.5)("q")["results"][0]["section"], "41")


def fake_model(tool_replies=(), final=None, depends=None, check=None, belief=None):
    """A model that answers each step by its prompt. Records the calls, so a test can see what each step was shown."""
    tool_replies, final = list(tool_replies), list(final or [draft()])
    calls = []

    def complete(messages, tools=None):
        calls.append((messages, tools))
        system = messages[0]["content"]
        if system == REWRITE:
            return text("นายจ้างให้ลูกจ้างซึ่งเป็นหญิงมีครรภ์ลา")
        if system == DEPENDS:
            return text(json.dumps(depends or {"depends": False, "fact": None, "question": None, "cases": []}))
        if system == CHECK:
            return text(json.dumps(check or {"covers_topic": True, "answers": True, "quote": CHUNK["text"]}))
        if system in (BELIEF, BELIEF_REPORTED):
            return text(json.dumps(belief or {"belief": "x", "belief_is_wrong": False, "law_says": None}))
        if tools:
            return tool_replies.pop(0) if tool_replies else text("พร้อมสรุป")
        return text(final.pop(0) if len(final) > 1 else final[0])

    complete.calls = calls
    return complete


def run_agent(question="ลาคลอดได้กี่วัน", max_steps=5, hits=None, **model):
    complete = fake_model(**model)
    both = lambda question, rewrite, k=5: hits or [Hit(CHUNK, 0.9)]
    answer, trace = Agent(search_law(), both, complete, max_steps).run(question)
    return answer, trace, complete.calls


class AgentLoop(unittest.TestCase):
    def test_answers_with_a_checked_citation(self):
        answer, _, _ = run_agent()
        self.assertEqual(answer.citations[0].amendment_no, 9)

    def test_the_tool_choice_does_not_see_the_law(self):
        _, _, calls = run_agent()
        messages = next(m for m, tools in calls if tools)
        self.assertEqual([m["role"] for m in messages], ["system", "user"])
        self.assertNotIn(FORMAT, messages[0]["content"])

    def test_refuses_without_calling_the_answer_step(self):
        answer, _, calls = run_agent(check={"covers_topic": False, "answers": False, "quote": ""})
        self.assertTrue(answer.not_found)
        self.assertEqual(answer.citations, [])
        self.assertFalse([m for m, tools in calls if m[0]["content"] == WRITE])

    def test_a_quote_that_is_not_in_the_results_lowers_confidence(self):
        answer, _, _ = run_agent(check={"covers_topic": True, "answers": True, "quote": "ข้อความที่แต่งขึ้นเองยาวพอสมควร"},
                                 final=[draft(confidence="high")])
        self.assertFalse(answer.not_found)
        self.assertEqual(answer.confidence, "low")

    def test_a_tool_result_is_answered_even_if_the_sections_do_not_answer(self):
        complete = fake_model(tool_replies=[tool_call("calculate", {"kind": "severance", "wage": 30000, "years": 25})],
                              final=[draft(answer="ได้ 400,000 บาท", citations=[])])

        def model(messages, tools=None):  # only the calculation's own rule covers the question
            if messages[0]["content"] == CHECK:
                covers = "มาตรา 118]" in messages[1]["content"]
                return text(json.dumps({"covers_topic": covers, "answers": False, "quote": ""}))
            return complete(messages, tools)
        answer, _ = Agent(search_law(), lambda question, rewrite, k=5: [Hit(CHUNK, 0.9)], model).run("q")
        self.assertEqual(answer.calculation.value, 400000)
        self.assertEqual(answer.citations[0].section, "118")

    SPOUSE = {**CHUNK, "section": "41/1", "text": "ให้ลูกจ้างมีสิทธิลาเพื่อช่วยเหลือคู่สมรสซึ่งคลอดบุตรได้ไม่เกิน 15 วัน"}
    TWO = [Hit(CHUNK, 0.9), Hit(SPOUSE, 0.8)]
    DEPENDS_ON = {"depends": True, "fact": "ผู้ถามเป็นผู้คลอดหรือคู่สมรส", "question": "ผู้ถามเป็นผู้คลอดเองหรือเป็นคู่สมรส",
                  "cases": ["ลาคลอดได้ไม่เกิน 120 วัน", "ลาเพื่อช่วยเหลือคู่สมรสซึ่งคลอดบุตร"]}

    def each_answers(self, depends):
        """A model whose check finds each section answers the question alone."""
        complete = fake_model(depends=depends)

        def model(messages, tools=None):
            if messages[0]["content"] == CHECK:
                own = next(c["text"] for c in (CHUNK, self.SPOUSE) if c["text"] in messages[1]["content"])
                return text(json.dumps({"covers_topic": True, "answers": True, "quote": own}))
            return complete(messages, tools)
        return Agent(search_law(), lambda question, rewrite, k=5: self.TWO, model)

    def test_asks_back_when_two_sections_each_answer_differently(self):
        answer, _ = self.each_answers(self.DEPENDS_ON).run("ลาคลอดได้กี่วัน")
        self.assertEqual(answer.clarifying_question, "ผู้ถามเป็นผู้คลอดเองหรือเป็นคู่สมรส")
        self.assertFalse(answer.not_found)

    def test_does_not_ask_back_when_the_differing_sections_are_in_two_acts(self):
        self.SPOUSE["law"] = "HOMEWORK2553"
        try:
            answer, _ = self.each_answers(self.DEPENDS_ON).run("ลาคลอดได้กี่วัน")
        finally:
            self.SPOUSE["law"] = "LPA2541"
        self.assertIsNone(answer.clarifying_question)

    def test_does_not_ask_back_when_only_one_section_answers(self):
        answer, _, _ = run_agent(hits=self.TWO, depends=self.DEPENDS_ON)  # the check quotes section 41 for both
        self.assertIsNone(answer.clarifying_question)

    def test_does_not_ask_back_without_quotes_from_two_sections(self):
        one_section = {**self.DEPENDS_ON, "cases": ["ลาคลอดได้ไม่เกิน", "ไม่เกิน 120 วัน"]}
        not_in_results = {**self.DEPENDS_ON, "cases": ["ลาคลอดได้ไม่เกิน 120 วัน", "ข้อความที่ไม่มีในผลค้นเลย"]}
        for depends in (one_section, not_in_results):
            answer, _ = self.each_answers(depends).run("ลาคลอดได้กี่วัน")
            self.assertIsNone(answer.clarifying_question)

    def test_does_not_ask_back_about_a_section_that_does_not_cover_the_question(self):
        complete = fake_model(depends=self.DEPENDS_ON)

        def model(messages, tools=None):
            if messages[0]["content"] == CHECK and "41/1" in messages[1]["content"] and "41]" not in messages[1]["content"]:
                return text(json.dumps({"covers_topic": False, "answers": False, "quote": ""}))
            return complete(messages, tools)
        answer, _ = Agent(search_law(), lambda question, rewrite, k=5: self.TWO, model).run("ลาคลอดได้กี่วัน")
        self.assertIsNone(answer.clarifying_question)

    def test_refuses_instead_of_asking_when_the_law_does_not_cover_it(self):
        answer, _, _ = run_agent(hits=self.TWO, depends=self.DEPENDS_ON, check={"covers_topic": False, "answers": False, "quote": ""})
        self.assertTrue(answer.not_found)
        self.assertIsNone(answer.clarifying_question)

    def test_a_calculated_amount_is_not_held_back_to_ask(self):
        answer, _, _ = run_agent(hits=self.TWO, depends=self.DEPENDS_ON,
                                 tool_replies=[tool_call("calculate", {"kind": "severance", "wage": 30000, "years": 25})],
                                 final=[draft(answer="ได้ 400,000 บาท", citations=[])])
        self.assertIsNone(answer.clarifying_question)
        self.assertEqual(answer.calculation.value, 400000)

    def test_asks_for_what_a_rate_needs(self):
        answer, _, _ = run_agent(tool_replies=[tool_call("get_rate", {"name": "min_wage_daily"})])
        self.assertIn("จังหวัด", answer.clarifying_question)

    def test_does_not_ask_where_the_user_works_when_the_rule_does_not_cover_it(self):
        complete = fake_model()

        def model(messages, tools=None):  # another country's minimum wage: the Thai rate does not cover it
            if messages[0]["content"] == CHECK and "(min_wage_daily)" in messages[1]["content"]:
                return text(json.dumps({"covers_topic": False, "answers": False, "quote": ""}))
            return complete(messages, tools)
        agent = Agent(search_law(), lambda question, rewrite, k=5: [Hit(CHUNK, 0.9)], model)
        answer, _ = agent.run("ค่าแรงขั้นต่ำของสหรัฐอเมริกาชั่วโมงละเท่าไร")
        self.assertIsNone(answer.clarifying_question)

    def test_code_asks_for_the_wage_a_deduction_needs(self):
        answer, trace, _ = run_agent(question="ประกันสังคมหักเดือนละเท่าไร",
                                     tool_replies=[tool_call("get_rate", {"name": "sso_employee_rate_percent"})])
        self.assertEqual(answer.clarifying_question, "ขอทราบค่าจ้าง")
        self.assertTrue([t for t in trace if t["arguments"].startswith("by code")])

    def test_asking_for_the_wage_states_the_rule_first(self):
        rule = draft(answer="หักร้อยละ 5 ของค่าจ้าง โดยใช้ฐานไม่เกิน 17,500 บาท", citations=[{"law": "SSA2533", "section": "46"}])
        answer, trace, calls = run_agent(question="ประกันสังคมหักเดือนละเท่าไร", final=[rule])
        self.assertEqual(answer.clarifying_question, "ขอทราบค่าจ้าง")
        self.assertEqual(answer.answer, "หักร้อยละ 5 ของค่าจ้าง โดยใช้ฐานไม่เกิน 17,500 บาท\n\nขอทราบค่าจ้าง")
        self.assertEqual([(c.law, c.section) for c in answer.citations][0], ("SSA2533", "46"))
        shown = next(m for m, _ in calls if m[0]["content"] == RULE)[1]["content"]
        self.assertIn("17500", shown)  # the ceiling comes from the rates table, not the model

    def test_a_rule_that_fails_the_checks_is_replaced_by_the_rates_code_found(self):
        answer, _, _ = run_agent(question="ประกันสังคมหักเดือนละเท่าไร", final=[draft(answer="หักเดือนละ 999 บาท")])
        self.assertNotIn("999", answer.answer)
        self.assertIn("17500", answer.answer)
        self.assertTrue(answer.answer.endswith("ขอทราบค่าจ้าง"))
        self.assertEqual(answer.clarifying_question, "ขอทราบค่าจ้าง")

    def test_asking_falls_back_to_the_question_alone_without_a_checked_rule(self):
        answer, _, _ = run_agent(question="ถูกเลิกจ้าง ได้ค่าชดเชยเท่าไร",
                                 tool_replies=[tool_call("calculate", {"kind": "severance", "wage": 0})],
                                 final=[draft(answer="ได้ 999 วัน")])
        self.assertEqual(answer.answer, "ขอข้อมูลเพิ่มเติมก่อนตอบ")
        self.assertIn("ค่าจ้าง", answer.clarifying_question)

    def test_the_most_deducted_is_calculated_at_the_ceiling(self):
        answer, trace, _ = run_agent(question="ปี 2570 ลูกจ้างถูกหักเงินสมทบประกันสังคมได้มากที่สุดเดือนละกี่บาท",
                                     tool_replies=[tool_call("calculate", {"kind": "sso_contribution", "wage": 0})],
                                     final=[draft(answer="สูงสุดเดือนละ 875 บาท", citations=[])])
        self.assertIsNone(answer.clarifying_question)
        self.assertEqual(answer.calculation.value, 875)
        self.assertIn("ถึงเพดาน 17,500 บาท", answer.answer)

    def test_a_date_rate_is_written_as_a_thai_date_without_the_other_date(self):
        rate = get_rate("ewf_collection_start", "2026-11-01")
        self.assertIn("คือวันที่ 1 มกราคม 2570", rate_text(rate))
        self.assertNotIn("2026-10-01", rate_text(rate))
        self.assertNotIn("ตุลาคม", rate_text(rate))

    def test_code_looks_up_a_rate_the_question_names(self):
        answer, trace, _ = run_agent(question="ค่าแรงขั้นต่ำวันละเท่าไร")
        self.assertIn("จังหวัด", answer.clarifying_question)
        _, trace, _ = run_agent(question="ทำงานที่นนทบุรี ค่าแรงขั้นต่ำวันละเท่าไร", final=[draft(answer="วันละ 372 บาท", citations=[])])
        self.assertEqual(next(t for t in trace if t["tool"] == "get_rate")["status"], "found")

    def test_the_place_in_the_question_overrides_the_model(self):
        answer, _, _ = run_agent(question="ทำงานร้านกาแฟที่เกาะสมุย ค่าแรงขั้นต่ำวันละเท่าไร",
                                 tool_replies=[tool_call("get_rate", {"name": "min_wage_daily", "province": "สุราษฎร์ธานี"})],
                                 final=[draft(answer="วันละ 400 บาท", citations=[])])
        self.assertIsNone(answer.clarifying_question)
        self.assertEqual(answer.citations[-1].section, "ข้อ 2 (3)")

    def test_figures_are_not_asked_for_a_rule_that_does_not_cover_the_question(self):
        complete = fake_model(tool_replies=[tool_call("calculate", {"kind": "severance", "wage": 0})])

        def model(messages, tools=None):  # the section answers, and the severance rule is unrelated
            if messages[0]["content"] == CHECK and "มาตรา 118]" in messages[1]["content"]:
                return text(json.dumps({"covers_topic": False, "answers": False, "quote": ""}))
            return complete(messages, tools)
        answer, _ = Agent(search_law(), lambda question, rewrite, k=5: [Hit(CHUNK, 0.9)], model).run("ลาคลอดได้ค่าจ้างเท่าไร")
        self.assertIsNone(answer.clarifying_question)

    def test_calculates_from_the_section_that_answers_when_no_kind_fits(self):
        leave = {**CHUNK, "section": "58", "text": "ให้นายจ้างจ่ายค่าจ้างให้แก่ลูกจ้างในวันลาเพื่อรับราชการทหาร"
                                                  "เท่ากับค่าจ้างในวันทำงานตลอดระยะเวลาที่ลา แต่ปีหนึ่งต้องไม่เกินหกสิบวัน"}
        share = {"kind": "wage_share", "wage": 15000, "percent": 100, "days": 10, "basis": "LPA2541 s.58"}
        complete = fake_model(tool_replies=[text("พร้อมสรุป"), tool_call("calculate", share)],
                              check={"covers_topic": True, "answers": True, "quote": leave["text"]},
                              final=[draft(answer="ได้ 5,000 บาท", citations=[])])
        agent = Agent(search_law(), lambda question, rewrite, k=5: [Hit(leave, 0.9)], complete)
        answer, trace = agent.run("เงินเดือน 15,000 บาท ลาไปฝึกทหาร 10 วัน ได้ค่าจ้างเท่าไร")
        self.assertEqual(answer.calculation.value, 5000)
        self.assertEqual(next(t for t in trace if t["tool"] == "calculate_from")["status"], "ok")

    def test_a_calculation_from_another_rule_is_not_kept(self):
        leave = {**CHUNK, "section": "58", "text": "ให้นายจ้างจ่ายค่าจ้างให้แก่ลูกจ้างในวันลาเพื่อรับราชการทหาร"}
        complete = fake_model(tool_replies=[text("พร้อมสรุป"), tool_call("calculate", {"kind": "compensation", "wage": 15000})],
                              check={"covers_topic": True, "answers": True, "quote": leave["text"]})
        agent = Agent(search_law(), lambda question, rewrite, k=5: [Hit(leave, 0.9)], complete)
        answer, trace = agent.run("เงินเดือน 15,000 บาท ลาไปฝึกทหาร 10 วัน ได้ค่าจ้างเท่าไร")
        self.assertIsNone(answer.calculation)
        self.assertEqual(next(t for t in trace if t["tool"] == "calculate_from")["status"], "follows another rule")

    def test_an_answer_with_numbers_it_worked_out_itself_is_asked_again(self):
        answer, _, _ = run_agent(final=[draft(answer="ลาคลอดได้ 120 วัน หรือ 4 เดือน รวม 60,000 บาท"), draft()])
        self.assertEqual(answer.answer, "ลาคลอดได้ 120 วัน")

    def test_a_question_asking_for_days_does_not_wait_for_a_wage(self):
        answer, _, _ = run_agent(question="ทำงานมา 22 ปีถูกเลิกจ้าง ได้ค่าชดเชยกี่วัน",
                                 tool_replies=[tool_call("calculate", {"kind": "severance", "wage": 0, "years": 22})])
        self.assertIsNone(answer.clarifying_question)

    SEVERANCE = {**CHUNK, "section": "118", "text": "ให้นายจ้างจ่ายค่าชดเชยให้แก่ลูกจ้างซึ่งเลิกจ้าง ทำงานครบสามปี"
                                                    "ให้จ่ายไม่น้อยกว่าค่าจ้างอัตราสุดท้ายหนึ่งร้อยแปดสิบวัน"}
    OVERTIME = {**CHUNK, "section": "61", "text": "ให้นายจ้างจ่ายค่าล่วงเวลาให้แก่ลูกจ้างในอัตราไม่น้อยกว่าหนึ่งเท่าครึ่ง"
                                                 "ของอัตราค่าจ้างต่อชั่วโมงในวันทำงานตามจำนวนชั่วโมงที่ทำ"}
    NOT_ANSWERED = {"covers_topic": True, "answers": False, "quote": ""}

    def test_code_asks_for_the_figures_of_a_formula_when_the_question_gives_none(self):
        # the model called no tool, and without the figures the check found that no section answers
        answer, trace, _ = run_agent(question="บริษัทปิดกิจการ จะได้ค่าชดเชยกี่บาท", hits=[Hit(self.SEVERANCE, 0.9)],
                                     check=self.NOT_ANSWERED)
        self.assertEqual(answer.clarifying_question, "ขอทราบค่าจ้าง และ อายุงาน")
        self.assertIn('"severance"', next(t for t in trace if t["arguments"].startswith("by code"))["arguments"])

    def test_figures_are_not_asked_for_a_formula_that_does_not_cover_the_question(self):
        answer, _, _ = run_agent(question="บริษัทปิดกิจการ จะได้ค่าชดเชยกี่บาท", hits=[Hit(self.SEVERANCE, 0.9)],
                                 check={"covers_topic": False, "answers": False, "quote": ""})
        self.assertIsNone(answer.clarifying_question)

    def test_a_rule_paying_a_share_of_the_wage_answers_without_figures(self):
        sick = {**CHUNK, "section": "57", "text": "ให้นายจ้างจ่ายค่าจ้างให้แก่ลูกจ้างในวันลาป่วยเท่ากับอัตราค่าจ้างในวันทำงาน"}
        answer, trace, _ = run_agent(question="ลาป่วยแล้วได้ค่าจ้างเท่าไร", hits=[Hit(sick, 0.9)],
                                     check={"covers_topic": True, "answers": True, "quote": sick["text"]},
                                     final=[draft(answer="ได้เท่ากับค่าจ้างในวันทำงาน", citations=[{"law": "LPA2541", "section": "57"}])])
        self.assertIsNone(answer.clarifying_question)
        self.assertFalse([t for t in trace if t["tool"] in ("calculate", "calculate_from")])

    def test_a_question_about_the_rate_is_answered_without_figures(self):
        answer, _, _ = run_agent(question="ค่าล่วงเวลาได้อัตราเท่าไร", hits=[Hit(self.OVERTIME, 0.9)],
                                 check={"covers_topic": True, "answers": True, "quote": self.OVERTIME["text"]},
                                 final=[draft(answer="หนึ่งเท่าครึ่งของค่าจ้างต่อชั่วโมง", citations=[{"law": "LPA2541", "section": "61"}])])
        self.assertIsNone(answer.clarifying_question)

    def test_given_some_figures_the_formula_that_covers_the_question_asks_for_the_rest(self):
        complete = fake_model(tool_replies=[text("พร้อมสรุป"), tool_call("calculate", {"kind": "overtime", "wage": 0, "hours": 3})],
                              check=self.NOT_ANSWERED)
        agent = Agent(search_law(), lambda question, rewrite, k=5: [Hit(self.OVERTIME, 0.9)], complete)
        answer, trace = agent.run("เมื่อวานทำโอที 3 ชั่วโมง จะได้เงินเท่าไร")
        self.assertEqual(answer.clarifying_question, "ขอทราบค่าจ้าง")
        self.assertEqual(next(t for t in trace if t["tool"] == "calculate_from")["status"], "needs_input")

    def test_asks_for_the_wage_a_calculation_needs_even_with_a_rate_found(self):
        replies = [tool_call("get_rate", {"name": "sso_employee_rate_percent"}), tool_call("calculate", {"kind": "sso_contribution", "wage": 0})]
        answer, _, _ = run_agent(question="ประกันสังคมหักเดือนละเท่าไร", tool_replies=replies)
        self.assertEqual(answer.clarifying_question, "ขอทราบค่าจ้าง")

    def test_a_year_in_the_question_sets_the_date(self):
        _, trace, calls = run_agent(question="ปี 2572 เงินเดือน 25,000 บาท ประกันสังคมหักเท่าไร",
                                    tool_replies=[tool_call("calculate", {"kind": "sso_contribution", "wage": 25000})],
                                    final=[draft(answer="ได้ 1,000 บาท", citations=[])])
        self.assertEqual(next(t for t in trace if t["tool"] == "calculate")["status"], "ok")
        self.assertIn("[ผลคำนวณ] 1,000 บาทต่อเดือน", calls[-1][0][1]["content"])

    def test_a_calculation_from_an_unrelated_rule_is_dropped(self):
        complete = fake_model(tool_replies=[tool_call("calculate", {"kind": "compensation", "wage": 18000})])

        def model(messages, tools=None):
            if messages[0]["content"] == CHECK and "WCA2537" in messages[1]["content"]:
                return text(json.dumps({"covers_topic": False, "answers": False, "quote": ""}))
            return complete(messages, tools)
        answer, trace = Agent(search_law(), lambda question, rewrite, k=5: [Hit(CHUNK, 0.9)], model).run("ลาคลอดได้กี่วัน")
        self.assertIsNone(answer.calculation)
        self.assertEqual([c.section for c in answer.citations], ["41"])
        self.assertTrue([t for t in trace if t["tool"] == "drop_calculation"])

    def test_a_calculation_whose_rule_covers_the_question_is_kept_though_not_retrieved(self):
        answer, trace, _ = run_agent(tool_replies=[tool_call("calculate", {"kind": "compensation", "wage": 18000})],
                                     final=[draft(answer="ได้ 12,600 บาท", citations=[])])
        self.assertEqual(answer.calculation.value, 12600)
        self.assertFalse([t for t in trace if t["tool"] == "drop_calculation"])

    def test_a_rate_the_check_finds_irrelevant_is_not_stated(self):
        complete = fake_model(tool_replies=[tool_call("get_rate", {"name": "sso_employee_rate_percent"})])

        def model(messages, tools=None):  # the section answers, and the rate alone is unrelated
            if messages[0]["content"] == CHECK:
                if "มาตรา 41" in messages[1]["content"]:
                    return text(json.dumps({"covers_topic": True, "answers": True, "quote": CHUNK["text"]}))
                return text(json.dumps({"covers_topic": False, "answers": False, "quote": ""}))
            return complete(messages, tools)
        agent = Agent(search_law(), lambda question, rewrite, k=5: [Hit(CHUNK, 0.9)], model)
        answer, _ = agent.run("ลาคลอดได้กี่วัน")
        self.assertEqual([c.section for c in answer.citations], ["41"])

    def test_a_later_call_with_the_details_supersedes_needs_input(self):
        replies = [tool_call("calculate", {"kind": "overtime", "wage": 100, "wage_type": "hourly"}),
                   tool_call("calculate", {"kind": "overtime", "wage": 100, "wage_type": "hourly", "hours": 2})]
        answer, _, _ = run_agent(tool_replies=replies, final=[draft(answer="ได้ 300 บาท", citations=[])])
        self.assertIsNone(answer.clarifying_question)
        self.assertEqual(answer.calculation.value, 300)

    def test_code_states_the_amount_if_the_model_will_not(self):
        answer, _, _ = run_agent(tool_replies=[tool_call("calculate", {"kind": "severance", "wage": 30000, "years": 25})],
                                 final=[draft(answer="คำนวณไม่ได้", citations=[])])
        self.assertIn("400,000", answer.answer)
        self.assertEqual(answer.calculation.value, 400000)
        self.assertEqual(answer.citations[0].section, "118")

    def test_code_states_the_rate_if_the_model_will_not(self):
        answer, _, _ = run_agent(tool_replies=[tool_call("get_rate", {"name": "min_wage_daily", "province": "นนทบุรี"})],
                                 final=[draft(answer="ไม่มีข้อมูล", citations=[])])
        self.assertIn("372", answer.answer)

    def test_tool_labels_and_section_prefixes_are_understood(self):
        answer, _, _ = run_agent(tool_replies=[tool_call("calculate", {"kind": "severance", "wage": 30000, "years": 25})],
                                 final=[draft(answer="ได้ 400,000 บาท", citations=[{"law": "LPA2541", "section": "s.118"},
                                                                                {"law": "ผลคำนวณ", "section": "x"}])])
        self.assertTrue(answer.answer.startswith("ได้ 400,000 บาท\n\nวิธีคิด:"))
        self.assertEqual([c.section for c in answer.citations], ["118"])

    def test_an_answer_must_state_the_rate_it_looked_up(self):
        answer, _, _ = run_agent(tool_replies=[tool_call("get_rate", {"name": "min_wage_daily", "province": "นนทบุรี"})],
                                 final=[draft(answer="ไม่มีข้อมูลอัตรา", citations=[]), draft(answer="วันละ 372 บาท", citations=[])])
        self.assertEqual(answer.answer, "วันละ 372 บาท")

    def test_code_fills_the_correction_when_a_belief_is_wrong(self):
        answer, _, _ = run_agent(question="ลาคลอดได้ 98 วันใช่ไหม", final=[draft(correction="จากโมเดล")],
                                 belief={"belief": "98 วัน", "belief_is_wrong": True, "law_says": "ไม่เกิน 120 วัน"})
        self.assertEqual(answer.correction, "ไม่เกิน 120 วัน")

    def test_a_right_belief_is_not_corrected(self):
        answer, _, _ = run_agent(question="ลาคลอดได้ 120 วันใช่ไหม", final=[draft(correction="จากโมเดล")])
        self.assertIsNone(answer.correction)

    def test_without_a_trigger_word_a_belief_must_be_stated_and_quoted(self):
        wrong = {"belief": "98 วัน", "belief_is_wrong": True, "law_says": "ไม่เกิน 120 วัน"}
        question = "เพื่อนบอกว่าลาคลอดได้ 98 วัน เลยวางแผนลาตามนั้น"
        answer, _, _ = run_agent(question=question, belief={**wrong, "stated": True, "quote": CHUNK["text"]})
        self.assertEqual(answer.correction, "ไม่เกิน 120 วัน")
        answer, _, _ = run_agent(question=question, belief={**wrong, "stated": False, "quote": CHUNK["text"]})
        self.assertIsNone(answer.correction)
        answer, _, _ = run_agent(question=question, belief={**wrong, "stated": True, "quote": "ข้อความที่ไม่มีในผลค้นจริง"})
        self.assertIsNone(answer.correction)

    def test_a_wrong_belief_is_answered_even_without_a_quote(self):
        answer, _, _ = run_agent(question="ลาคลอดได้ 98 วันใช่ไหม", check={"covers_topic": True, "answers": False, "quote": ""},
                                 belief={"belief": "98", "belief_is_wrong": True, "law_says": "ไม่เกิน 120 วัน"})
        self.assertFalse(answer.not_found)

    def test_unknown_tool_is_not_run(self):
        _, trace, _ = run_agent(tool_replies=[tool_call("delete_files", {})])
        self.assertEqual(next(t for t in trace if t["tool"] == "delete_files")["status"], "invalid")

    def test_bad_arguments_are_not_run(self):
        with patch("src.agent.loop.calculate") as tool:
            _, trace, _ = run_agent(tool_replies=[tool_call("calculate", {"kind": "severance", "wage": -5})])
        self.assertEqual(next(t for t in trace if t["tool"] == "calculate")["status"], "invalid")
        tool.assert_not_called()

    def test_extra_arguments_are_rejected(self):
        _, trace, _ = run_agent(tool_replies=[tool_call("search_law", {"query": "ลา", "path": "/etc"})])
        self.assertEqual(next(t for t in trace if t["tool"] == "search_law")["status"], "invalid")

    def test_searches_are_capped(self):
        call = tool_call("search_law", {"query": "ลา"})
        _, trace, _ = run_agent(tool_replies=[call, call, call])
        self.assertEqual([t["status"] for t in trace if t["tool"] == "search_law"], ["found", "found", "limit"])

    def test_stops_at_the_step_limit(self):
        call = tool_call("get_rate", {"name": "sso_wage_base_max"})
        _, trace, _ = run_agent(tool_replies=[call] * 9, max_steps=3)
        self.assertEqual(sum(t["tool"] == "get_rate" for t in trace), 3)

    def test_keeps_the_answer_step_retry(self):
        answer, _, _ = run_agent(final=["not json", draft()])
        self.assertEqual(answer.answer, "ลาคลอดได้ 120 วัน")

    def test_bad_step_output_falls_back_safely(self):
        complete = lambda messages, tools=None: text("not json")
        self.assertFalse(check_depends("q", "c", complete).depends)
        self.assertFalse(check_results("q", "c", complete).covers_topic)
        self.assertFalse(check_belief("ใช่ไหม", "c", complete).belief_is_wrong)


class Deductions(unittest.TestCase):
    def test_a_deduction_from_the_askers_own_pay(self):
        topic = DEDUCTION_TOPICS["sso_contribution"]
        self.assertTrue(asks_own_deduction("ปี 2572 ประกันสังคมจะหักเงินเดือนเดือนละเท่าไร", topic))
        self.assertFalse(asks_own_deduction("เงินเดือน 25,000 บาท ประกันสังคมหักเดือนละเท่าไร", topic))
        self.assertFalse(asks_own_deduction("เงินสมทบประกันสังคมที่ลูกจ้างถูกหักสูงสุดเดือนละเท่าไร", topic))
        self.assertFalse(asks_own_deduction("ประกันสังคมหักร้อยละเท่าไร", topic))


class Rates(unittest.TestCase):
    def test_a_place_in_the_question_is_found_with_its_province(self):
        self.assertEqual(place_in("ทำงานร้านกาแฟที่เกาะสมุย"), ("สุราษฎร์ธานี", "เกาะสมุย"))
        self.assertEqual(place_in("อยู่ กทม."), ("กรุงเทพมหานคร", None))
        self.assertEqual(place_in("ทำงานโรงแรม"), (None, None))

    def test_an_unknown_province_is_asked_for(self):
        result = get_rate("min_wage_daily", "2026-11-01", "ทุกจังหวัด")
        self.assertEqual((result["status"], result["missing"]), ("needs_input", ["province"]))


class Grounding(unittest.TestCase):
    DATA = "ให้จ่ายไม่น้อยกว่าหนึ่งเท่าครึ่ง ร้อยละเจ็ดสิบห้าของค่าจ้าง [LPA2541 มาตรา 75] ค่าจ้างวันละ 400 บาท 10 วัน"

    def test_numbers_from_the_data_or_the_question_are_grounded(self):
        self.assertEqual(ungrounded_numbers("1. ได้ 1.5 เท่า ร้อยละ 75 ตามมาตรา 75 วันละ 400 บาท ปี 2568", self.DATA), [])

    def test_one_step_of_arithmetic_from_the_data_is_grounded(self):
        self.assertEqual(ungrounded_numbers("หักสูงสุดเดือนละ 875 บาท", "เพดาน 17500 บาทต่อเดือน อัตรา 5 เปอร์เซ็นต์"), [])

    def test_a_number_worked_out_by_the_model_is_not(self):
        self.assertEqual(ungrounded_numbers("ได้ 3,500 บาท (400 x 10 x 0.75)", self.DATA), [0.75, 3500])


class QuestionDate(unittest.TestCase):
    def test_a_buddhist_or_common_era_year_sets_the_date(self):
        self.assertEqual(question_date("ปี 2572 ประกันสังคมหักเท่าไร", "2026-11-01"), "2029-01-01")
        self.assertEqual(question_date("ตั้งแต่เดือนตุลาคม 2574", "2026-11-01"), "2031-10-01")
        self.assertEqual(question_date("in 2030", "2026-11-01"), "2030-01-01")
        self.assertEqual(question_date("ปี 2569 นี้", "2026-11-01"), "2026-11-01")

    def test_act_years_and_amounts_are_not_dates(self):
        self.assertIsNone(question_date("พ.ร.บ.การทำงานของคนต่างด้าว พ.ศ. 2551 ยังใช้ไหม", "2026-11-01"))
        self.assertIsNone(question_date("เงินเดือน 2,575 บาท", "2026-11-01"))
        self.assertIsNone(question_date("ลาคลอดได้กี่วัน", "2026-11-01"))


class LinkedSections(unittest.TestCase):
    def test_a_penalty_section_is_linked_to_the_duty_it_names(self):
        self.assertEqual(penalties()[("FOREIGN2560", "8")], [("FOREIGN2560", "101")])
        self.assertEqual(penalties()[("FOREIGN2560", "9")], [("FOREIGN2560", "102")])
        self.assertIn(("LPA2541", "144"), penalties()[("LPA2541", "61")])  # listed after "บทบัญญัติดังต่อไปนี้"

    def test_an_exception_named_after_the_penalty_is_not_a_duty(self):
        # s.101 ends "เว้นแต่เป็นคนต่างด้าวตามมาตรา 63"
        self.assertNotIn(("FOREIGN2560", "101"), penalties().get(("FOREIGN2560", "63"), []))

    def test_a_penalty_question_gets_the_duty_and_its_penalty(self):
        found = penalty_sections("คนต่างด้าวทำงานโดยไม่มีใบอนุญาตมีโทษอย่างไร", "", [{"law": "FOREIGN2560"}])
        self.assertIn(("FOREIGN2560", "8"), found)
        self.assertIn(("FOREIGN2560", "101"), found)
        self.assertEqual(penalty_sections("คนต่างด้าวทำงานโดยไม่มีใบอนุญาตได้ไหม", "", [{"law": "FOREIGN2560"}]), [])

    def test_a_question_whether_an_act_is_in_force_gets_the_section_repealing_it(self):
        self.assertEqual(repealing_sections("พ.ร.บ.การทำงานของคนต่างด้าว พ.ศ. 2551 ยังใช้บังคับอยู่ไหม"), [("FOREIGN2560", "3")])
        self.assertEqual(repealing_sections("พ.ร.บ.คุ้มครองแรงงาน พ.ศ. 2541 ยังใช้บังคับอยู่ไหม"), [])


class Applies(unittest.TestCase):
    PREGNANT ="ห้ามมิให้นายจ้างให้ลูกจ้างซึ่งเป็นหญิงมีครรภ์ทำงานในระหว่างเวลา 22.00 นาฬิกา"
    CHILD = "ห้ามมิให้นายจ้างให้ลูกจ้างซึ่งเป็นเด็กอายุต่ำกว่าสิบแปดปีทำงานในระหว่างเวลา 22.00 นาฬิกา"

    def test_a_rule_for_a_group_the_question_does_not_mention_is_dropped(self):
        self.assertFalse(applies(self.PREGNANT, "ผู้หญิงทำงานกะดึกได้ไหม"))
        self.assertTrue(applies(self.PREGNANT, "ท้องอยู่ ทำงานกะดึกได้ไหม"))
        self.assertTrue(applies("ให้นายจ้างจัดให้ลูกจ้างมีวันหยุด", "ผู้หญิงทำงานกะดึกได้ไหม"))

    def test_an_age_under_18_counts_as_a_child_but_years_of_service_do_not(self):
        self.assertTrue(applies(self.CHILD, "ลูกอายุ 16 ปี ทำงานกะดึกได้ไหม"))
        self.assertTrue(applies(self.CHILD, "A 17-year-old working nights?"))
        self.assertFalse(applies(self.CHILD, "ทำงานมา 3 ปี ทำงานกะดึกได้ไหม"))
        self.assertFalse(applies(self.CHILD, "อายุครบ 60 ปี ทำงานกะดึกได้ไหม"))


class AnswerChecks(unittest.TestCase):
    def test_a_rate_citation_counts_when_its_announcement_is_labelled(self):
        q = {"gold_sections": [{"law": "LPA2541", "section": "90"}], "gold_sources": ["min_wage_no14"], "expected_behavior": "answer"}
        rate = {"law": None, "section": "ข้อ 4", "source": source_titles()["min_wage_no14"]}
        self.assertTrue(citation_hit(q, {"citations": [rate]}))
        self.assertFalse(citation_hit({**q, "gold_sources": []}, {"citations": [rate]}))

    def test_a_real_quote_about_something_else_does_not_count(self):
        context = "ลาคลอดได้ไม่เกิน 120 วัน\n\nฝ่าฝืนข้อบังคับเกี่ยวกับการทำงานหรือระเบียบของนายจ้าง"
        reply = lambda quote: lambda messages, tools=None: text(json.dumps({"covers_topic": True, "answers": True, "quote": quote}))
        self.assertFalse(check_results("หนังสือเตือนมีอายุนานแค่ไหน", context, reply("ฝ่าฝืนข้อบังคับเกี่ยวกับการทำงานหรือระเบียบ")).answers)
        self.assertTrue(check_results("ลาคลอดได้กี่วัน", context, reply("ลาคลอดได้ไม่เกิน 120 วัน")).answers)

    def test_the_answer_sees_the_quoted_section_only(self):
        rows = [{"law": "LPA2541", "section": "23", "text": "ไม่เกินสี่สิบแปดชั่วโมง"},
                {"law": "MARITIME2558", "section": "48", "text": "คนประจำเรือ"},
                {"law": "LPA2541", "section": "24", "text": "ทำงานล่วงเวลา"}]
        self.assertEqual([r["section"] for r in focus(rows, "สี่สิบแปดชั่วโมง")], ["23"])
        self.assertEqual(len(focus(rows, "ไม่มีในผลค้น")), 3)

    def test_the_answer_also_sees_the_whole_section_and_others_that_answer(self):
        rows = [{"law": "LPA2541", "section": "23", "text": "ไม่เกินสี่สิบแปดชั่วโมง"},
                {"law": "MARITIME2558", "section": "48", "text": "คนประจำเรือ"},
                {"law": "LPA2541", "section": "24", "text": "ทำงานล่วงเวลา"}]
        shown = focus(rows, "สี่สิบแปดชั่วโมง", also={("LPA2541", "24")})
        self.assertEqual([r["section"] for r in shown], ["23", "24"])
        self.assertTrue(shown[0]["text"].startswith("มาตรา 23"))  # the full section, not the chunk found

    def test_a_workplace_matter_is_refused_as_left_to_the_contract(self):
        def model(messages, tools=None):
            if messages[0]["content"] == SCOPE:
                return text(json.dumps({"workplace": True, "topic": "เรื่องเบี้ยขยัน"}))
            return fake_model(check={"covers_topic": False, "answers": False, "quote": ""})(messages, tools)
        answer, trace = Agent(search_law(), lambda question, rewrite, k=5: [Hit(CHUNK, 0.9)], model).run("ต้องได้เบี้ยขยันไหม")
        self.assertTrue(answer.not_found)
        self.assertEqual(answer.citations, [])
        self.assertTrue(answer.answer.startswith("กฎหมายที่ระบบมีไม่ได้บังคับเรื่องเบี้ยขยัน จึงขึ้นกับสัญญาจ้างหรือข้อบังคับของบริษัท"))

    def test_another_kind_of_question_keeps_the_plain_refusal(self):
        reply = lambda answer: lambda messages, tools=None: text(json.dumps(answer, ensure_ascii=False))
        self.assertIsNone(refusal_scope("ค่าครองชีพที่ญี่ปุ่น", reply({"workplace": False, "topic": "ค่าครองชีพ"})))
        self.assertIsNone(refusal_scope("x", reply({"oops": 1})))
        self.assertEqual(refusal_scope("x", reply({"workplace": True, "topic": "ค่าอาหาร 50 บาท"})), "นี้")

    def test_a_refusal_is_scored_by_its_kind(self):
        workplace, outside = {"refusal": "not_required"}, {"refusal": "outside"}
        left_to_contract = {"answer": "กฎหมายที่ระบบมีไม่ได้บังคับเรื่องเบี้ยขยัน", "not_found": True}
        plain = {"answer": "ไม่ทราบ เนื่องจากข้อมูลนี้เกินขอบเขตของเนื้อหาที่มีอยู่", "not_found": True}
        self.assertTrue(refusal_ok(workplace, left_to_contract))
        self.assertFalse(refusal_ok(workplace, plain))
        self.assertTrue(refusal_ok(outside, plain))
        self.assertFalse(refusal_ok(outside, left_to_contract))
        self.assertFalse(refusal_ok(workplace, {**left_to_contract, "not_found": False}))
        self.assertIsNone(refusal_ok({}, plain))

    def test_supporting_figures_are_scored_apart(self):
        q = {"expected_number": 75, "expected_numbers": [75], "supporting_numbers": [3], "expected_behavior": "answer"}
        answer = {"answer": "จ่ายร้อยละ 75", "correction": None, "calculation": None}
        self.assertTrue(number_ok(q, answer))
        self.assertFalse(supporting_ok(q, answer))


class SearchBoth(unittest.TestCase):
    def test_keeps_the_best_score_across_wordings(self):
        other = {**CHUNK, "chunk_id": "y"}

        class Retriever:
            candidates = 10

            def search(self, query, k=5):
                return {"a": [Hit(CHUNK, 0.1), Hit(other, 0.5)], "b": [Hit(CHUNK, 0.9)]}[query]

        hits = search_both(Retriever(), ["a", "b"], k=5)
        self.assertEqual([(h.chunk["chunk_id"], h.score) for h in hits], [("x", 0.9), ("y", 0.5)])

    def test_the_same_wording_is_not_searched_twice(self):
        seen = []

        class Retriever:
            candidates = 10

            def search(self, query, k=5):
                seen.append(query)
                return []

        search_both(Retriever(), ["a", "a"])
        self.assertEqual(seen, ["a"])


class BehaviourMetrics(unittest.TestCase):
    def test_counts_mistakes_in_both_directions(self):
        def question(i, behaviour):
            return {"id": i, "expected_behavior": behaviour}

        def record(i, ask=None, correction=None):
            return {"id": i, "answer": {"clarifying_question": ask, "correction": correction, "not_found": False}}

        questions = [question("a", "ask_clarification"), question("b", "ask_clarification"), question("c", "answer"),
                     question("d", "correct_premise")]
        row = behaviour_row("m", [record("a", "?"), record("b"), record("c", "?", "x"), record("d")], questions)
        self.assertEqual((row["ask_recall"], row["over_ask"], row["ask_precision"]), ("1/2", "1/2", "1/2"))
        self.assertEqual((row["correction_filled"], row["false_corrections"]), ("0/1", "1/3"))

    def test_a_correction_must_say_what_the_reference_says(self):
        q = {"expected_behavior": "correct_premise", "correction_terms": ["จ่ายค่าจ้าง"], "expected_numbers": [30]}
        answer = {"not_found": False, "correction": "ปีหนึ่งต้องไม่เกินสามสิบวันทำงาน"}
        self.assertFalse(correction_ok(q, answer))
        self.assertTrue(correction_ok(q, {**answer, "correction": "นายจ้างจ่ายค่าจ้างไม่เกิน 30 วัน"}))


class Api(unittest.TestCase):
    def setUp(self):
        agent = Agent(search_law(), lambda question, rewrite, k=5: [Hit(CHUNK, 0.9)], fake_model())
        patcher = patch("src.api.main.build_agent", return_value=agent)
        patcher.start()
        self.addCleanup(patcher.stop)

    def test_ask_returns_a_validated_answer(self):
        from src.api.main import app
        with TestClient(app) as client:
            body = client.post("/ask", json={"question": "ลาคลอดได้กี่วัน"}).json()
        self.assertEqual(body["citations"][0]["section"], "41")
        self.assertEqual(body["as_of"], "2026-11-01")

    def test_empty_question_is_rejected(self):
        from src.api.main import app
        with TestClient(app) as client:
            self.assertEqual(client.post("/ask", json={"question": ""}).status_code, 422)


if __name__ == "__main__":
    unittest.main()
