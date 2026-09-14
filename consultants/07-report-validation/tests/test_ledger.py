# -*- coding: utf-8 -*-
"""提案台帳の本体 ── 本文の訂正と、作業完了／公開の区別を確かめる。

    python tests/test_ledger.py

危ないのは**社外へ出る紙**である。`--order-sheet` は制作会社へそのまま渡す。
そこに次のどちらかが載ると、実害が出る。

    ・実行できない指示（実装してみて誤りと分かった発注指示が直っていない）
    ・済んだ作業（当社の実装が終わり、先方の公開だけを待っているもの）

どちらも「台帳の中では辻褄が合っている」ので、目では気づけない。
"""
import os
import sys
import tempfile
import unittest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "scripts"))

import ledger as L  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.lg = L.Ledger(os.path.join(self.tmp.name, "_ledger", "proposals.json"))

    def tearDown(self):
        self.tmp.cleanup()

    def add(self, **kw):
        base = dict(period="2026-06", title="題", target="/form",
                    angle="measurement", effort="設定のみ", vendor="制作",
                    vendor_brief="指示", status="実装待ち")
        base.update(kw)
        return self.lg.add(**base)


class 本文の訂正(Base):
    """状態は --set、本文は --amend。入口を分ける。"""

    def test_発注指示を直せる(self):
        p = self.add(vendor_brief="送信完了ページの表示をトリガーにする")
        item, _ = self.lg.amend(p["id"], "vendor_brief",
                                "送信完了メッセージの表示をトリガーにする",
                                reason="完了ページが存在しなかった",
                                kind="実装してみて方法が誤りと判明")
        self.assertIn("メッセージ", item["vendor_brief"])

    def test_直した記録が残る(self):
        """いつ・何を・なぜ。次の提案の材料になる。"""
        p = self.add(metric="旧指標")
        self.lg.amend(p["id"], "metric", "新指標", reason="改名したため")
        r = p["amendments"][-1]
        self.assertEqual((r["field"], r["before"], r["after"]),
                         ("metric", "旧指標", "新指標"))
        self.assertTrue(r["on"])
        self.assertEqual(r["reason"], "改名したため")

    def test_理由が無ければ受け付けない(self):
        """なぜ直したかが残らないと、同じ誤りを次でもう一度書く。"""
        p = self.add()
        with self.assertRaises(ValueError):
            self.lg.amend(p["id"], "title", "新しい題", reason="  ")

    def test_状態は本文の口から変えられない(self):
        p = self.add()
        for f in ("status", "implemented_on", "blocked_by"):
            with self.assertRaises(ValueError):
                self.lg.amend(p["id"], f, "x", reason="理由")

    def test_知らない訂正の型は受け付けない(self):
        p = self.add()
        with self.assertRaises(ValueError):
            self.lg.amend(p["id"], "title", "新", reason="理由", kind="でたらめ")

    def test_工数を直すと費用帯も付け替わる(self):
        """古い帯が残ると、発注の束が狂う。"""
        p = self.add(effort="設定のみ")
        self.assertEqual(p["cost_band"], "低")
        item, _ = self.lg.amend(p["id"], "effort", "中規模改修",
                                reason="想定より大きかった")
        self.assertEqual(item["cost_band"], "高")
        self.assertEqual(self.lg.low_cost(), [])

    def test_重複判定の軸を動かしたら知らせる(self):
        """target × angle が他とぶつかれば、同じ提案が2件になる。"""
        self.add(target="/price", angle="price")
        p = self.add(target="/form", angle="price")
        _item, warn = self.lg.amend(p["id"], "target", "/price",
                                    reason="対象を取り違えていた",
                                    kind="対象や切り口の取り違え")
        self.assertIn("対象URL × 切り口が同じ", warn)

    def test_ぶつからなければ黙る(self):
        p = self.add(target="/form", angle="price")
        _item, warn = self.lg.amend(p["id"], "target", "/contact",
                                    reason="対象を取り違えていた")
        self.assertEqual(warn, "")


class 作業完了と公開(Base):
    """作業が終わった日と、変更が世に出た日は別である。"""

    def test_公開待ちは発注依頼書に出さない(self):
        """作業は終わっている。**発注するものが無い。**"""
        p = self.add()
        self.assertEqual([i["id"] for i in self.lg.low_cost()], [p["id"]])
        self.lg.set_status(p["id"], "実装待ち", work_done="2026-09-14")
        self.assertEqual(self.lg.low_cost(), [])
        self.assertNotIn("指示", L.order_sheet(self.lg, vendor="制作"))

    def test_公開待ちは進捗ではなく公開日を尋ねる(self):
        p = self.add()
        self.lg.set_status(p["id"], "実装待ち", work_done="2026-09-14")
        sheet = L.status_sheet(self.lg, "2026-09")
        self.assertIn("作業が完了し、公開をお待ちしているもの", sheet)
        self.assertIn("公開日", sheet)
        # 「実施が決まったと理解しています」＝作業が止まって見える書き方
        self.assertNotIn("実施が決まったと理解しています", sheet)

    def test_確認シートに二度出さない(self):
        p = self.add()
        self.lg.set_status(p["id"], "実装待ち", work_done="2026-09-14")
        self.assertEqual(L.status_sheet(self.lg, "2026-09").count(p["id"]), 1)

    def test_前後比較の起点は公開日のまま(self):
        """作業完了日を起点にすると、変化が無い期間を「実装後」として比べる。"""
        p = self.add()
        self.lg.set_status(p["id"], "実装待ち", work_done="2026-09-14")
        self.assertIsNone(p["implemented_on"])
        self.assertEqual(self.lg.verify_due("2026-10"), [])
        self.lg.set_status(p["id"], "実装済み", on="2026-09-20")
        self.assertEqual(p["implemented_on"], "2026-09-20")
        self.assertEqual([i["id"] for i in self.lg.verify_due("2026-10")],
                         [p["id"]])

    def test_着手待ちは今までどおり発注依頼書に出る(self):
        self.add()
        self.assertIn("指示", L.order_sheet(self.lg, vendor="制作"))


if __name__ == "__main__":
    unittest.main(verbosity=2)
