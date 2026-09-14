# -*- coding: utf-8 -*-
"""ヒートマップ画像の共通処理が、実測で見つけた落とし穴を塞いだままであることを確かめる。

    python tests/test_heatmap_image.py

この処理は Clarity で何度も実測しながら直したもので、**直した理由が
コメントにしか残っていなかった。** Ptengine と共用にするにあたって、
次の4つを固定する。どれも「動いているように見えて壊れている」型である。

    ・左右の余白を、白でない画素の有無で判定してはいけない
      （枠線やスクロールバーが端に写り込んでいる）
    ・狭い側に合わせて切ってはいけない
      （実際に、2枚とも入力欄が右端で切れた画像ができた）
    ・貼り付く要素は、上と下で違う手がかりで測る
    ・結合位置は scrollTop から計算する（画像差分で探さない）

Pillow / numpy が無い環境では飛ばす。
"""
import os
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "scripts"))

try:
    import numpy as np
    from PIL import Image
    import heatmap_image as H
    READY = True
except ImportError:
    READY = False


def block(w, h, color=(40, 40, 40), bg=(255, 255, 255), left=0, right=None):
    """左右に白い余白、中央に中身のある画像を作る。"""
    im = Image.new("RGB", (w, h), bg)
    right = w if right is None else right
    for x in range(left, right):
        for y in range(0, h, 2):      # 中身の割合が10%を超えるよう密に置く
            im.putpixel((x, y), color)
    return im


@unittest.skipUnless(READY, "Pillow / numpy が無い環境のため飛ばす")
class 余白の判定(unittest.TestCase):

    def test_中身のある区間を返す(self):
        im = block(200, 60, left=50, right=150)
        got = H.trim_bounds(im, pad=0)
        self.assertEqual(got, (50, 150))

    def test_端に写り込んだ線では切らない(self):
        """**白でない画素が1つでもある列、では判定できない。**

        枠線やスクロールバーが端に写り込むため、その方法だと全幅が中身になる。
        列ごとの中身の割合で見る。
        """
        im = block(200, 60, left=50, right=150)
        for y in range(60):           # 左端に1pxの枠線
            im.putpixel((0, y), (0, 0, 0))
        got = H.trim_bounds(im, pad=0)
        self.assertEqual(got, (50, 150))

    def test_まばらな列は中身とみなさない(self):
        """スクロールバー（数%）が中身に混ざらないこと。"""
        im = block(200, 100, left=50, right=150)
        for y in range(0, 100, 50):   # 2% しか埋まらない列
            im.putpixel((190, y), (0, 0, 0))
        left, right = H.trim_bounds(im, pad=0)
        self.assertLess(right, 190)

    def test_切りすぎるときは切らない(self):
        im = Image.new("RGB", (200, 60), (255, 255, 255))
        for y in range(60):
            im.putpixel((100, y), (0, 0, 0))   # 幅1列だけ
        self.assertIsNone(H.trim_bounds(im, pad=0))

    def test_noneを渡したら切らない(self):
        im = block(200, 60, left=50, right=150)
        got, used = H.trim_margins(im, bounds=H.NO_TRIM)
        self.assertEqual(got.size, (200, 60))
        self.assertIsNone(used)


@unittest.skipUnless(READY, "Pillow / numpy が無い環境のため飛ばす")
class 幅をそろえる(unittest.TestCase):
    """**狭い側に合わせてはいけない。** 実際に中身が切れた画像ができた。"""

    def test_広い側にそろえる(self):
        self.assertEqual(H.widest((50, 150), (10, 190)), (10, 190))

    def test_片方しか判定できなくても使える(self):
        self.assertEqual(H.widest(None, (10, 190)), (10, 190))

    def test_どれも判定できなければ切らない(self):
        self.assertIsNone(H.widest(None, None))

    def test_切らない指定は混ぜない(self):
        self.assertEqual(H.widest(H.NO_TRIM, (10, 190)), (10, 190))

    def test_4種別ぶんを持ち寄れる(self):
        got = H.widest((60, 140), (50, 150), None, (55, 160))
        self.assertEqual(got, (50, 160))


@unittest.skipUnless(READY, "Pillow / numpy が無い環境のため飛ばす")
class 指定の読み取り(unittest.TestCase):

    def test_autoは自分で判定(self):
        self.assertIsNone(H.parse_trim("auto"))

    def test_明示した左右(self):
        self.assertEqual(H.parse_trim("5,100"), (5, 100))

    def test_左右が逆なら止める(self):
        with self.assertRaises(SystemExit):
            H.parse_trim("100,5")

    def test_読めない指定なら止める(self):
        with self.assertRaises(SystemExit):
            H.parse_trim("ひだり,みぎ")


@unittest.skipUnless(READY, "Pillow / numpy が無い環境のため飛ばす")
class 結合(unittest.TestCase):
    """結合位置は scrollTop から計算する。画像差分で重なりを探さない。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def tiles(self, view=100, step=80, total=300, mark=True):
        """各タイルの先頭行に、そのタイル番号を明るさで書き込む。"""
        out = []
        top = 0
        i = 0
        while top < total:
            im = Image.new("RGB", (50, view), (255, 255, 255))
            if mark:
                for x in range(50):
                    im.putpixel((x, 0), (i * 20, i * 20, i * 20))
            p = self.d / f"t{i:02d}.png"
            im.save(p)
            out.append((p, min(top, total - view)))
            if top + view >= total:
                break
            top += step
            i += 1
        return out

    def test_到達した範囲までの高さになる(self):
        tiles = self.tiles(view=100, step=80, total=300)
        out, _used, _det = H.stitch(tiles, 300, 100, self.d / "j.png",
                                    trim=H.NO_TRIM)
        im = Image.open(out)
        self.assertEqual(im.height, 300)

    def test_ページ全高より小さい方を採る(self):
        """**スクロールできた範囲で決める。**

        表示領域の幅に合わせてページを縮小する実装では、スクロールできる量が
        ページ全高より小さい。全高を使うと下半分が真っ白な画像になる。
        """
        tiles = [(self.tiles(view=100, total=100)[0][0], 0)]
        out, _u, _d = H.stitch(tiles, 9999, 100, self.d / "j.png", trim=H.NO_TRIM)
        self.assertEqual(Image.open(out).height, 100)

    def test_貼り付く要素は2枚目以降の上を切る(self):
        """切らないと、継ぎ目ごとにヘッダーが繰り返し現れる。"""
        tiles = self.tiles(view=100, step=80, total=300)
        out, _u, _d = H.stitch(tiles, 300, 100, self.d / "j.png",
                               sticky_css=10, trim=H.NO_TRIM)
        a = np.asarray(Image.open(out).convert("L"))
        # 1枚目の先頭（y=0）は残る
        self.assertLess(a[0].mean(), 250)
        # 2枚目の先頭が入るはずの位置は、切られて隣のタイルの中身で埋まる
        second_top = tiles[1][1]
        self.assertGreater(a[second_top].mean(), 250)

    def test_最後のタイルの下は切らない(self):
        """最後だけは下端まで要る。切ると本文が欠ける。"""
        tiles = self.tiles(view=100, step=80, total=300)
        out, _u, _d = H.stitch(tiles, 300, 100, self.d / "j.png",
                               sticky_bottom_css=10, trim=H.NO_TRIM)
        self.assertEqual(Image.open(out).height, 300)

    def test_切る左右を渡せる(self):
        tiles = self.tiles(view=100, step=80, total=300)
        out, used, _d = H.stitch(tiles, 300, 100, self.d / "j.png",
                                 trim=(10, 40))
        self.assertEqual(used, (10, 40))
        self.assertEqual(Image.open(out).width, 30)

    def test_切らなくても判定値は残す(self):
        """呼び出し側が、種別ごとの判定を持ち寄って決めるため。"""
        tiles = []
        for i in range(3):
            im = block(200, 100, left=50, right=150)
            p = self.d / f"b{i}.png"
            im.save(p)
            tiles.append((p, i * 80))
        _out, used, detected = H.stitch(tiles, 300, 100, self.d / "j.png",
                                        trim=H.NO_TRIM)
        self.assertIsNone(used)
        self.assertIsNotNone(detected)


@unittest.skipUnless(READY, "Pillow / numpy が無い環境のため飛ばす")
class 貼り付く要素(unittest.TestCase):
    """上と下で違う手がかりを使う。実測で決めた使い分け。"""

    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.d = Path(self.tmp.name)

    def tearDown(self):
        self.tmp.cleanup()

    def make(self, n=5, view=100, header=0, footer=0):
        rng = np.random.default_rng(0)
        out = []
        for i in range(n):
            a = rng.integers(0, 255, size=(view, 50), dtype=np.uint8)
            if header:
                a[:header] = 200          # どのタイルでも同じ＝ばらつきが小さい
            if footer:
                a[-footer:] = 100
            p = self.d / f"s{i}.png"
            Image.fromarray(a, mode="L").convert("RGB").save(p)
            out.append((p, i * 80))
        return out

    def test_上のヘッダーを測れる(self):
        got = H.detect_sticky(self.make(header=20), 100, "top")
        self.assertGreater(got, 5)
        self.assertLessEqual(got, H.AUTO_STICKY_MAX)

    def test_下の固定バーを測れる(self):
        got = H.detect_sticky(self.make(footer=20), 100, "bottom")
        self.assertGreater(got, 5)

    def test_貼り付く要素が無ければ0(self):
        self.assertEqual(H.detect_sticky(self.make(), 100, "top"), 0)

    def test_タイルが少なければ判定しない(self):
        self.assertEqual(H.detect_sticky(self.make(n=2, header=20), 100, "top"), 0)


@unittest.skipUnless(READY, "Pillow / numpy が無い環境のため飛ばす")
class 重なりの決め方(unittest.TestCase):
    """貼り付く要素を切るぶん、重なりを広く取っておく必要がある。"""

    def test_自動判定なら上限ぶん広く取る(self):
        got = H.overlap_for(40, "auto", "auto")
        self.assertGreaterEqual(got, H.AUTO_STICKY_MAX * 2)

    def test_値が決まっていればその合計より広く取る(self):
        self.assertGreaterEqual(H.overlap_for(40, 60, 50), 110)

    def test_切らないなら指定のまま(self):
        self.assertEqual(H.overlap_for(40, 0, 0), 40)


if __name__ == "__main__":
    unittest.main(verbosity=2)
