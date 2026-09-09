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

sys.path.insert(0, SCRIPTS)

try:
    from pptx import Presentation  # noqa: F401
    from test_check_values import deck
    import deliver
    READY = True
except ImportError:
    READY = False


def gate(pptx, out, *extra):
    """既定では --no-measure。PowerPoint のある PC でしか通らないテストにしない。

    実測そのもの（measure_text.ps1）は PowerPoint に依存するため、ここでは
    「飛ばしたことが記録に残るか」だけを確かめる。
    """
    if "--measure" in extra:
        extra = tuple(x for x in extra if x != "--measure")
    else:
        extra = tuple(extra) + ("--no-measure",)
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

    def test_実測を飛ばしたら記録に残る(self):
        """「測っていない」を「問題なし」にしない。"""
        p = deck([("t", ["集計期間: 2026/08/01〜08/31"], None)])
        rc, out = gate(p, self.out)
        self.assertEqual(rc, 0, out)
        rec = [f for f in os.listdir(self.out) if f.endswith(".check.txt")][0]
        with open(os.path.join(self.out, rec), encoding="utf-8") as f:
            self.assertIn("文字の実測を行っていない", f.read())

    def test_実測が失敗しても要対応にしない(self):
        """4つめの検査（PowerPoint）の不調で、既存3検査の判定を巻き添えにしない。

        COM は落ちる。確認の窓が出て止まることもある。それは「はみ出しがある」
        という意味ではない。0（なし）と 1（あり）以外は**測れなかった**として扱い、
        納品ゲートは飛ばした事実だけを記録する。
        """
        if not deliver.powershell():
            self.skipTest("PowerShell が無い環境のため飛ばす")
        with tempfile.TemporaryDirectory() as d:
            stub = os.path.join(d, "こわれた検査.ps1")
            with open(stub, "w", encoding="utf-8-sig") as f:
                f.write("Write-Output '測れませんでした'\nexit 99\n")
            rc, out = deliver.run_ps(stub, [])
            self.assertEqual(rc, deliver.CANNOT_MEASURE, out)

    def test_missing_file(self):
        rc, _ = gate(os.path.join(self.out, "nothing.pptx"), self.out)
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)
