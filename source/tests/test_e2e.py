"""End-to-end run of main.main() with a STUBBED model on temporary placeholder files.
Proves the orchestration, CSV writing and validation work; says nothing about real accuracy."""
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parent))

import main as app
from config import Settings
from test_logic import GUIDE_KESC_0008
from validators import read_csv_strict


class StubClient:
    def __init__(self, settings):
        self.calls = 0

    def generate_json(self, prompt, image=None, mime=None, label=""):
        self.calls += 1
        if ":extract" in label:
            return json.dumps({"bill": GUIDE_KESC_0008, "facts": {"usage_history": []}})
        ids = [line.split(":")[0] for line in prompt.split("QUESTIONS:\n")[1].splitlines() if line.startswith("Q")]
        return json.dumps({"answers": {i: f"Stub answer for {i}: taxes are PKR 569.62." for i in ids}})


class E2E(unittest.TestCase):
    def test_full_run(self):
        from PIL import Image
        with tempfile.TemporaryDirectory() as tmp:
            tmp = Path(tmp)
            (tmp / "bills").mkdir()
            Image.new("RGB", (50, 50), "white").save(tmp / "bills" / "KESC_9999.png")
            (tmp / "level1.csv").write_text("bill_id,json\nKESC_9999,\n", encoding="utf-8")
            (tmp / "level2.csv").write_text('bill_id,question_id,question,answer\n'
                                            'KESC_9999,Q1,"What, exactly, is my tax?",\n'
                                            'KESC_9999,Q2,Peak month?,\n', encoding="utf-8")
            settings = Settings("google", "gemini-3.1-flash-lite", "TESTKEY1234567890", None, 3, 5, 0, 10, tmp / "logs")
            argv = ["main.py", "--mode", "train", "--bills-dir", str(tmp / "bills"),
                    "--level1-template", str(tmp / "level1.csv"), "--level2-template", str(tmp / "level2.csv"),
                    "--out-dir", str(tmp / "out")]
            with mock.patch.object(sys, "argv", argv), mock.patch.object(app, "GeminiClient", StubClient), \
                    mock.patch.object(app, "load_settings", return_value=settings), \
                    mock.patch.object(app, "PROJECT_ROOT", tmp):
                # train mode builds its own rows; use test mode semantics via explicit templates
                argv[2] = "test"
                code = app.main()
            self.assertEqual(code, 1)  # test mode demands 10/120 rows, so a 1-bill run must be reported as fatal
            _, l1 = read_csv_strict(tmp / "out" / "level1.csv")
            _, l2 = read_csv_strict(tmp / "out" / "level2.csv")
            self.assertEqual(json.loads(l1[0]["json"])["total_taxes"], 569.62)
            self.assertEqual([r["question"] for r in l2], ["What, exactly, is my tax?", "Peak month?"])
            self.assertTrue(all(r["answer"] for r in l2))
            self.assertIn("row_count", (tmp / "reports" / "validation_report_test.md").read_text())
            # templates untouched
            self.assertEqual((tmp / "level1.csv").read_text(encoding="utf-8"), "bill_id,json\nKESC_9999,\n")


if __name__ == "__main__":
    unittest.main()
