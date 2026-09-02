# -*- coding: utf-8 -*-
"""deliver.py（納品ゲート）が、通すべきものを通し、止めるべきものを止めることを確かめる。

    python tests/test_deliver.py

python-pptx が無い環境では飛ばす。
"""
import os
import subprocess
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
SCRIPTS = os.path.join(ROOT, "scripts")
sys.path.insert(0, os.path.join(ROOT, "tests"))

try:
    from pptx import Presentation  # noqa: F401
    from test_check_values import deck
    READY = True
except ImportError:
    READY = False


def gate(pptx, out, *extra):
    cmd = [sys.executable, os.path.join(SCRIPTS, "deliver.py"), pptx,
           "--out", out, "--stray-dir", out] + list(extra)
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8",
                       errors="replace")
    return r.returncode, r.stdout


@unittest.skipUnless(READY, "python-pptx が必要")
class TestDeliver(unittest.TestCase):

    def setUp(self):
        self.out = tempfile.mkdtemp()

    def delivered(self):
        return [f for f in os.listdir(self.out) if f.startswith("納品)") and f.endswith(".pptx")]

    def test_clean_deck_is_delivered_with_record(self):
        p = deck([("t", ["集計期間: 2026/08/01〜08/31", "収益 ¥12.3M"], None)])
        rc, out = gate(p, self.out, "--period", "2026-08")
        self.assertEqual(rc, 0, out)
        self.assertEqual(len(self.delivered()), 1)
        recs = [f for f in os.listdir(self.out) if f.endswith(".check.txt")]
        self.assertEqual(len(recs), 1)

    def test_reversed_period_is_refused(self):
        p = deck([("t", ["集計期間: 2026/08/01〜07/31"], None)])
        rc, out = gate(p, self.out)
        self.assertEqual(rc, 1)
        self.assertIn("納品しません", out)
        self.assertEqual(self.delivered(), [])

    def test_force_delivers_and_records_it(self):
        p = deck([("t", ["集計期間: 2026/08/01〜07/31"], None)])
        rc, out = gate(p, self.out, "--force")
        self.assertEqual(rc, 0)
        self.assertEqual(len(self.delivered()), 1)
        rec = [f for f in os.listdir(self.out) if f.endswith(".check.txt")][0]
        with open(os.path.join(self.out, rec), encoding="utf-8") as f:
            self.assertIn("--force", f.read())

    def test_missing_file(self):
        rc, _ = gate(os.path.join(self.out, "nothing.pptx"), self.out)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
