# -*- coding: utf-8 -*-
"""sc_platform_export.py の、ブラウザを開かずに確かめられる部分。

    python shared/tests/test_sc_platform_export.py

画面の操作そのものは、実際にサインインした画面でしか確かめられない。
ここで見るのは、入力の形・集計開始日の読み取り・手で置いた zip の扱い・
API が通らないときにブラウザへ進むこと・失敗したら手順を出して止まること。
"""
import contextlib
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from datetime import date
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

import sc_platform_export as S  # noqa: E402

RID = "sc-creator-profile:instagram.com/example_account"


class 入力の形(unittest.TestCase):
    def test_画面のURLに識別子と期間を渡す(self):
        url = S.ui_url(RID, date(2026, 10, 1), date(2026, 10, 31))
        self.assertIn("resource_id=sc-creator-profile%3Ainstagram.com%2Fexample_account", url)
        self.assertIn("start_date=20261001", url)
        self.assertIn("end_date=20261031", url)

    def test_保存フォルダの名前に記号を持ち込まない(self):
        self.assertEqual(S.safe_name(RID), "instagram.com_example_account")


class 集計開始日(unittest.TestCase):
    def test_日本語の表示から読む(self):
        self.assertEqual(S.data_since("2026/10/15 以降のデータが表示されています"), "2026-10-15")
        self.assertEqual(S.data_since("2026年10月15日以降のデータ"), "2026-10-15")

    def test_英語の表示から読む(self):
        self.assertEqual(S.data_since("Showing data since Oct 15, 2026"), "2026-10-15")

    def test_表示が無ければ空(self):
        self.assertEqual(S.data_since("検索パフォーマンス"), "")


class 取得の流れ(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.base = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def run_main(self, *extra):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = S.main(["--resource", RID, "--start", "2026-10-01", "--end", "2026-10-31",
                           "--out", str(self.base), *extra])
        return code, out.getvalue()

    def test_手で置いたzipがあれば展開して記録する(self):
        folder = self.base / S.safe_name(RID)
        folder.mkdir(parents=True)
        with zipfile.ZipFile(folder / "export.zip", "w") as z:
            z.writestr("Queries.csv", "query,clicks\nx,1\n")
            z.writestr("Pages.csv", "page,clicks\n")
        with mock.patch.object(S, "browser_export", side_effect=AssertionError("開かない")):
            code, _ = self.run_main()
        self.assertEqual(code, 0)
        self.assertTrue((folder / "Queries.csv").exists())
        run = json.loads((self.base / "manifest.json").read_text(encoding="utf-8"))["runs"][-1]
        self.assertEqual(run["method"], "manual")

    def test_APIが通らなければブラウザへ進み_失敗したら手順を出して止まる(self):
        with mock.patch.object(S, "api_token", return_value="t"), \
             mock.patch.object(S, "api_query", return_value=(400, {})), \
             mock.patch.object(S, "browser_export",
                               side_effect=RuntimeError("「エクスポート」が見つかりません")) as be:
            code, text = self.run_main()
        self.assertEqual(code, 2)
        self.assertTrue(be.called)
        self.assertIn("手で書き出してください", text)
        self.assertIn("start_date=20261001", text)

    def test_APIが通ればブラウザを開かない(self):
        rows = {"rows": [{"keys": ["k"], "clicks": 1, "impressions": 10, "ctr": 0.1, "position": 2.0}]}
        with mock.patch.object(S, "api_token", return_value="t"), \
             mock.patch.object(S, "api_query", return_value=(200, rows)), \
             mock.patch.object(S, "browser_export", side_effect=AssertionError("開かない")):
            code, _ = self.run_main()
        self.assertEqual(code, 0)
        run = json.loads((self.base / "manifest.json").read_text(encoding="utf-8"))["runs"][-1]
        self.assertEqual(run["method"], "api")
        self.assertEqual(run["api_status"], 200)

    def test_開始日が終了日より後なら止める(self):
        with self.assertRaises(SystemExit), contextlib.redirect_stderr(io.StringIO()):
            S.main(["--resource", RID, "--start", "2026-10-31", "--end", "2026-10-01",
                    "--out", str(self.base)])


if __name__ == "__main__":
    unittest.main(verbosity=2)
