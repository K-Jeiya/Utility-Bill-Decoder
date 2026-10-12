"""Offline tests: no network, no API key. They test OUR logic with a stubbed model.
They do NOT measure extraction accuracy on real bills - that needs the real images.

Run:  python -m unittest discover -s tests -v
"""
import json
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from bill_extractor import extract_bill
from calculations import bill_stats, history_stats
from question_answerer import answer_questions
from validators import (LEVEL1_COLUMNS, LEVEL2_COLUMNS, SCHEMA_KEYS, find_pii, normalize_bill,
                        parse_json_loose, validate_bill, validate_level1_file, validate_level2_file,
                        write_csv)

# Correct JSON for training bill KESC_0008, copied from the competition guide (section 5.7).
GUIDE_KESC_0008 = {
    "provider": "KE", "tariff": "A1-R", "sanctioned_load_kw": 3, "bill_month": "2026-04",
    "reading_date": "2026-04-03", "issue_date": "2026-04-07", "due_date": "2026-04-21",
    "previous_reading": 8819, "current_reading": 8970, "units_consumed": 151,
    "charges": [{"type": "fixed", "amount": 900}, {"type": "energy", "amount": 1054},
                {"type": "energy", "amount": 663.51}, {"type": "quarterly_adjustment", "amount": 52.91},
                {"type": "fpa", "amount": 125.27}, {"type": "surcharge", "amount": 64.93}],
    "total_charges": 2860.62,
    "taxes": [{"type": "electricity_duty", "amount": 29.41}, {"type": "gst", "amount": 520.21},
              {"type": "municipal_tax", "amount": 20}],
    "total_taxes": 569.62, "current_bill": 3430.24, "arrears": -0.53,
    "payable_within_due_date": 3430, "payable_after_due_date": 3716,
}


class FakeClient:
    """Returns canned responses in order; records prompts."""
    def __init__(self, responses):
        self.responses, self.prompts = list(responses), []

    def generate_json(self, prompt, image=None, mime=None, label=""):
        self.prompts.append(prompt)
        return self.responses.pop(0)


class ValidatorTests(unittest.TestCase):
    def test_guide_example_is_clean(self):
        self.assertEqual(validate_bill(GUIDE_KESC_0008, "KESC_0008", "KE"), [])

    def test_missing_field_and_bad_values_are_fatal(self):
        bad = dict(GUIDE_KESC_0008)
        del bad["tariff"]
        self.assertTrue(any(i.code == "missing_fields" for i in validate_bill(bad, "X")))
        bad = dict(GUIDE_KESC_0008, provider="KESC", due_date="21-04-2026", arrears="-0.53")
        codes = {i.code for i in validate_bill(bad, "X")}
        self.assertTrue({"bad_provider", "bad_date", "not_numeric"} <= codes)

    def test_normalisation_is_safe(self):
        raw = dict(GUIDE_KESC_0008, provider="KESC", units_consumed="151", arrears="0.53CR",
                   payable_after_due_date="Rs. 3,716", due_date="21st Apr 2026", bill_month="APR 2026",
                   charges=[{"type": "FCA", "amount": "125.27"}, {"type": "energy", "amount": 0},
                            {"type": "weird", "amount": 5}], taxes=None)
        bill, _ = normalize_bill(raw)
        self.assertEqual((bill["provider"], bill["units_consumed"], bill["arrears"]), ("KE", 151, -0.53))
        self.assertEqual((bill["payable_after_due_date"], bill["due_date"], bill["bill_month"]), (3716, "2026-04-21", "2026-04"))
        self.assertEqual(bill["charges"], [{"type": "fpa", "amount": 125.27}, {"type": "other", "amount": 5}])
        self.assertEqual(bill["taxes"], [])
        self.assertEqual(list(bill), SCHEMA_KEYS)

    def test_inconsistent_totals_warn_without_changing_amounts(self):
        raw = json.loads(json.dumps(GUIDE_KESC_0008))
        raw["total_charges"] = 2000
        issues = validate_bill(raw, "X")
        self.assertTrue(any(i.code == "charges_sum_mismatch" and i.severity == "warning" for i in issues))
        self.assertEqual(raw["total_charges"], 2000)

    def test_parse_json_loose(self):
        self.assertEqual(parse_json_loose('```json\n{"a": 1,}\n```'), {"a": 1})
        self.assertEqual(parse_json_loose('Here: {"a": [1,2,]} done'), {"a": [1, 2]})

    def test_pii_detection(self):
        self.assertTrue(any(s == "fatal" for s, _ in find_pii("CNIC 42101-1234567-1")))
        self.assertTrue(any(s == "warning" for s, _ in find_pii("meter 123456789012")))
        self.assertEqual(find_pii("Your bill is PKR 3,430.24 for 151 units"), [])


class CalculationTests(unittest.TestCase):
    def test_history_split_and_counts(self):
        # SYNTHETIC numbers, only to check arithmetic (not real bill data).
        hist = [{"month": f"2025-{m:02d}", "units": u} for m, u in
                zip(range(4, 13), [100, 250, 200, 201, 50, 300, 10, 20, 30])]
        hist += [{"month": "2026-01", "units": 40}, {"month": "2026-02", "units": 60},
                 {"month": "2026-03", "units": 80}, {"month": "2026-04", "units": 151}]
        stats = history_stats(hist, "2026-04", 151)
        prev = stats["previous_months_stats"]
        self.assertEqual(prev["count"], 12)
        self.assertEqual(prev["months_above"]["200"], 3)   # 250, 201, 300 (200 itself is not above)
        self.assertEqual(prev["months_at_or_above"]["200"], 4)
        self.assertEqual(prev["highest"], {"month": "2025-09", "units": 300})
        self.assertEqual(stats["current_month_bar"]["units"], 151)

    def test_bill_stats_on_guide_example(self):
        s = bill_stats(GUIDE_KESC_0008)
        self.assertEqual(s["taxes_share_of_current_bill_pct"], 16.61)
        self.assertEqual(s["charges_by_type"]["energy"], 1717.51)
        self.assertEqual(s["late_payment_extra_amount"], 286)
        self.assertEqual(s["reading_difference"], 151)


class PipelineTests(unittest.TestCase):
    def test_extraction_retries_then_succeeds(self):
        good = json.dumps({"bill": GUIDE_KESC_0008, "facts": {"usage_history": [{"month": "2026-04", "units": "151"}]}})
        client = FakeClient(["not json at all", good])
        res = extract_bill(client, "KESC_0008", b"x", "image/png", 3)
        self.assertEqual(res.attempts, 2)
        self.assertEqual(res.bill["total_taxes"], 569.62)
        self.assertEqual(res.facts["usage_history"], [{"month": "2026-04", "units": 151}])
        self.assertIn("not usable JSON", client.prompts[1])

    def test_extraction_gives_up_without_fabricating(self):
        res = extract_bill(FakeClient(["{}", "{}", "{}"]), "KESC_0008", b"x", "image/png", 3)
        self.assertIsNone(res.bill)
        self.assertEqual(res.issues[0].code, "extraction_failed")

    def test_consistency_retry_happens_once(self):
        wrong = dict(GUIDE_KESC_0008, total_charges=2000)
        client = FakeClient([json.dumps({"bill": wrong}), json.dumps({"bill": GUIDE_KESC_0008})])
        res = extract_bill(client, "KESC_0008", b"x", "image/png", 3)
        self.assertEqual(res.bill["total_charges"], 2860.62)
        self.assertEqual(len(client.prompts), 2)

    def test_qa_maps_ids_and_retries_only_missing(self):
        qs = [("Q1", "How much tax?"), ("Q2", "Peak month?")]
        first = json.dumps({"answers": {"Q1": "Taxes are PKR 569.62, about 16.6% of the bill.", "Q2": ""}})
        second = json.dumps({"answers": {"Q2": "Highest month was July 2025."}})
        client = FakeClient([first, second])
        answers, issues = answer_questions(client, "KESC_0008", b"x", "image/png", GUIDE_KESC_0008, {}, qs, 3)
        self.assertEqual(set(answers), {"Q1", "Q2"})
        self.assertEqual([i for i in issues if i.severity == "fatal"], [])
        self.assertNotIn("Q1: How much tax?", client.prompts[1])

    def test_qa_rejects_urdu_and_reports_missing(self):
        qs = [("Q1", "Anything?")]
        bad = json.dumps({"answers": {"Q1": "یہ اردو ہے"}})
        answers, issues = answer_questions(FakeClient([bad, bad]), "B", b"x", "image/png", None, {}, qs, 2)
        self.assertEqual(answers, {})
        self.assertEqual(issues[-1].code, "no_answer")


class CsvTests(unittest.TestCase):
    def test_roundtrip_and_validation(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            l1_tpl = [{"bill_id": "KESC_0008", "json": ""}]
            l2_tpl = [{"bill_id": "KESC_0008", "question_id": "Q1", "question": 'Why "high", please?', "answer": ""}]
            l1 = [{"bill_id": "KESC_0008", "json": json.dumps(GUIDE_KESC_0008, separators=(",", ":"))}]
            l2 = [dict(l2_tpl[0], answer="Because, as billed, taxes are PKR 569.62.")]
            write_csv(tmp / "l1.csv", LEVEL1_COLUMNS, l1)
            write_csv(tmp / "l2.csv", LEVEL2_COLUMNS, l2)
            self.assertIn('{""provider"":""KE""', (tmp / "l1.csv").read_text(encoding="utf-8"))
            self.assertEqual(validate_level1_file(tmp / "l1.csv", l1_tpl, 1), [])
            self.assertEqual(validate_level2_file(tmp / "l2.csv", l2_tpl, 1, expected_per_bill=None), [])
            # tampered question and empty answer must be fatal
            bad = [dict(l2_tpl[0], question="Changed?", answer="")]
            write_csv(tmp / "l2b.csv", LEVEL2_COLUMNS, bad)
            codes = {i.code for i in validate_level2_file(tmp / "l2b.csv", l2_tpl, 1, expected_per_bill=None)}
            self.assertTrue({"template_changed", "empty_answer"} <= codes)


if __name__ == "__main__":
    unittest.main()
