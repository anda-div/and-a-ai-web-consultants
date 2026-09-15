# -*- coding: utf-8 -*-
"""Ptengineの期間指定まわりを、ブラウザ無しで確かめる。

ここで押さえているのは、実機で**実際に間違えた**判断である。

    ・1年以上前の月を指定したら「未来の日付です」と表示した
    ・暦月を「先月」に読み替えていた（実行した日に依存する）
    ・古い月へ1か月ずつ送っていた

`ptengine_heatmap_capture.py` は Playwright を要求するため読み込めない。
判断の部分だけを `ptengine_dates.py` に切り出してあるので、そちらを試す。
"""
import sys
import unittest
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))

from ptengine_dates import disabled_reason, month_span, months_to_move


class 期間の読み取り(unittest.TestCase):
    def test_暦月は月初から月末になる(self):
        self.assertEqual(month_span("2026-08"), (date(2026, 8, 1), date(2026, 8, 31)))

    def test_短い月でも末日を正しく出す(self):
        self.assertEqual(month_span("2026-02"), (date(2026, 2, 1), date(2026, 2, 28)))
        self.assertEqual(month_span("2024-02"), (date(2024, 2, 1), date(2024, 2, 29)))

    def test_年をまたぐ月も末日を正しく出す(self):
        self.assertEqual(month_span("2026-12"), (date(2026, 12, 1), date(2026, 12, 31)))

    def test_範囲指定はそのまま読む(self):
        self.assertEqual(month_span("2026-07-10..2026-07-20"),
                         (date(2026, 7, 10), date(2026, 7, 20)))

    def test_プリセットの名前は暦月として読まない(self):
        # 「先月」等はここでは None になり、呼び出し側でプリセットとして扱う
        for v in ("last-month", "this-month", "過去 7 日間", "2026/08", ""):
            self.assertIsNone(month_span(v), v)


class 押せない日の理由(unittest.TestCase):
    """**セルには理由が書かれていない。** 未来の日も古すぎる日も同じ `disabled`。"""

    今日 = date(2026, 9, 15)

    def test_未来の日はそう言う(self):
        r = disabled_reason(date(2026, 10, 1), self.今日)
        self.assertIn("未来の日付", r)
        self.assertNotIn("遡れる範囲", r)

    def test_古すぎる日を未来と言わない(self):
        # 実機で出た誤り。1年以上前の月に「未来の日付です」と表示していた
        r = disabled_reason(date(2025, 8, 1), self.今日)
        self.assertIn("遡れる範囲の外", r)
        self.assertNotIn("未来", r)

    def test_今日は未来ではない(self):
        self.assertNotIn("未来", disabled_reason(self.今日, self.今日))

    def test_理由に日付が入る(self):
        self.assertIn("2025-08-01", disabled_reason(date(2025, 8, 1), self.今日))


class 月送りの決め方(unittest.TestCase):
    """パネルは2か月ぶん並ぶ。どちらかに出ていれば動かさない。"""

    def test_左のパネルに出ていれば動かさない(self):
        self.assertIsNone(months_to_move([(2026, 9), (2026, 10)], date(2026, 9, 1)))

    def test_右のパネルに出ていても動かさない(self):
        self.assertIsNone(months_to_move([(2026, 9), (2026, 10)], date(2026, 10, 1)))

    def test_近い過去は月送りで戻る(self):
        back, year, diff = months_to_move([(2026, 9), (2026, 10)], date(2026, 8, 1))
        self.assertTrue(back)
        self.assertFalse(year)
        self.assertEqual(diff, -1)

    def test_12か月以上離れたら年送りを使う(self):
        # 1か月ずつでは何十回も押すことになる
        back, year, diff = months_to_move([(2026, 9), (2026, 10)], date(2025, 9, 1))
        self.assertTrue(back)
        self.assertTrue(year)
        self.assertEqual(diff, -12)

    def test_11か月なら年送りは使わない(self):
        # 年送りは12か月動くので、ここで使うと行き過ぎる
        back, year, diff = months_to_move([(2026, 9), (2026, 10)], date(2025, 10, 1))
        self.assertTrue(back)
        self.assertFalse(year)
        self.assertEqual(diff, -11)

    def test_未来へも進める(self):
        back, year, diff = months_to_move([(2026, 1), (2026, 2)], date(2026, 5, 1))
        self.assertFalse(back)
        self.assertFalse(year)
        self.assertEqual(diff, 4)

    def test_年をまたぐ差を正しく数える(self):
        _back, _year, diff = months_to_move([(2026, 2), (2026, 3)], date(2025, 11, 1))
        self.assertEqual(diff, -3)


if __name__ == "__main__":
    unittest.main(verbosity=2)
