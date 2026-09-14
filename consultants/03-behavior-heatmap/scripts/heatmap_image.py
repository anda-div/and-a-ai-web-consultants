# -*- coding: utf-8 -*-
"""ヒートマップ画像の共通処理（Clarity / Ptengine どちらからも使う）

分割して撮った画像を1枚に結合する部分は、ツールが違っても同じ問題が出る。

    ・表示領域の中央にページが置かれ、左右に白い帯が残る
    ・画面に貼り付く要素（ヘッダー・固定バー）が全タイルに写り込む
    ・種別ごとに余白の判定が食い違い、同じページなのに幅がそろわない

Clarityで実測しながら潰した処理をここに集める。**二重管理にしない。**
片方で見つけた改善が、もう片方にも届くようにする。

結合は `scrollTop` の実測値から計算で行う。画像差分で重なりを探す必要はない。
"""
from __future__ import annotations

from pathlib import Path

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    raise SystemExit("Pillow が必要です: pip install -r requirements.txt")

# 貼り付く要素を自動判定するときの上限（CSS px）。
# これより大きく切ることはしない。本文を削る事故を防ぐため。
AUTO_STICKY_MAX = 200

NO_TRIM = "none"       # 「余白を落とさない」の指定


def parse_trim(value):
    """--trim の値を解く。auto なら None（自分で判定させる）。"""
    if not value or value == "auto":
        return None
    if value == NO_TRIM:
        return NO_TRIM
    try:
        left, right = (int(v) for v in str(value).split(","))
    except ValueError:
        raise SystemExit(f"--trim の指定が読めません: {value}（「L,R」か auto か none）")
    if right <= left:
        raise SystemExit(f"--trim の左右が逆です: {value}")
    return left, right


def trim_bounds(im: "Image.Image", pad: int = 4):
    """ページ本体が写っている左右の位置を返す。切るべきでなければ None。

    ヒートマップは表示領域の中央にページを置くため、両側に白い帯が残る。
    そのまま資料に貼ると、ページが小さく余白ばかりの図になる。

    「白でない画素が1つでもある列」を探すやり方では切れない。
    枠線やスクロールバーが端に写り込んでいて、端の列も白ではないため。
    **列ごとに中身の割合を見て、その割合が高い列が連続する一番長い区間**を取る。
    """
    import numpy as np

    a = np.asarray(im.convert("RGB"), dtype=np.int16)
    ratio = (a < 249).any(axis=2).mean(axis=0)   # 列ごとの「白でない」割合
    solid = ratio >= 0.10                        # スクロールバー（数%）は外れる

    best = (0, -1)
    start = None
    for x in range(len(solid) + 1):
        if x < len(solid) and solid[x]:
            if start is None:
                start = x
        elif start is not None:
            if x - start > best[1] - best[0]:
                best = (start, x)
            start = None

    left, right = best
    if right - left < im.width * 0.05:      # 切りすぎは疑わしいのでやめる
        return None
    return max(0, left - pad), min(im.width, right + pad)


def trim_margins(im: "Image.Image", pad: int = 4, bounds=None):
    """左右の白い余白を落とし、ページ本体だけにする。上下は切らない。

    `bounds` を渡すと、その左右で切る。**種別の違う画像で幅をそろえるために使う。**
    同じページ・同じデバイスでも、自動判定に任せると幅が違う画像になる。
    点が疎に散る種別（クリック）は余白と見なされる列が多く、
    面で塗られる種別（スクロール・熟読）は判定が食い違う。

    返り値は (画像, 実際に使った左右)。使わなかったときの左右は None。
    """
    if bounds == NO_TRIM:
        return im, None
    if bounds is None:
        bounds = trim_bounds(im, pad)
    if bounds is None:
        return im, None
    left, right = bounds
    left = max(0, min(left, im.width - 1))
    right = max(left + 1, min(right, im.width))
    return im.crop((left, 0, right, im.height)), (left, right)


def widest(*bounds):
    """複数の判定を持ち寄って、**広い側**にそろえる。

    狭い側に合わせてはいけない。実測では、点が疎な種別の判定が常に狭く出た。
    狭い側に合わせた結果、**2枚とも入力欄が右端で切れた画像**になったことがある。
    寸法は一致していたので、数字だけでは気づけなかった。

    「どちらかが中身と見なした列は切り落とさない」という決め方にする。
    """
    got = [b for b in bounds if b and b != NO_TRIM]
    if not got:
        return None
    return (min(b[0] for b in got), max(b[1] for b in got))


def detect_sticky(tiles, view_css: int, side: str) -> int:
    """画面に貼り付く要素の高さを、タイル画像から測る（CSS px）。

    上端と下端で、効く手がかりが違う。実測して使い分けている。

    **上端（ヘッダー）はばらつきで見る。**
    スクロールしても動かない部分は、どのタイルでも似た絵になるため、
    タイル間のばらつきが本文より小さい。半透明のヘッダーは後ろが透けて
    タイルごとに見た目が変わるので「1枚目と同じか」では判定できないが、
    それでも本文よりはばらつきが小さい（実測：ヘッダー38 / 本文83）。

    **下端（固定バーやチャットボタン）は1枚目との一致で見る。**
    下端はばらつきが本文と近く、ばらつきでは分けられない
    （実測：下端15 / 本文19）。一方、絵そのものは1枚目とよく一致する。

    tiles は (パス, scrollTop) の並び。
    """
    import numpy as np

    use = [p for p, _ in (tiles[:-1] if side == "bottom" else tiles)][:8]
    if len(use) < 3:
        return 0

    stack = np.stack([np.asarray(Image.open(p).convert("L"), dtype=np.float32)
                      for p in use])
    tile_h = stack.shape[1]
    scale = tile_h / view_css
    limit_rows = int(tile_h * 0.3)

    if side == "top":
        sd = stack.std(axis=0).mean(axis=1)
        # 1行だけの跳ねで打ち切らないよう、9行の移動平均でならす。
        #
        # **端は値を複製してから畳み込む。** そのまま mode="same" にすると、
        # 先頭の数行が0で埋められたぶん平均が下がり、貼り付く要素が無いのに
        # 「ある」と判定される（実測：ヘッダー無しの画像で数px出た）。
        # 下振れは切りすぎる向きに効くので、本文を削る事故につながる。
        k = np.ones(9) / 9
        pad = len(k) // 2
        sd = np.convolve(np.pad(sd, pad, mode="edge"), k, mode="same")[pad:-pad]
        body = float(np.median(sd[int(tile_h * 0.4):int(tile_h * 0.9)]))
        if body < 1.0:
            return 0
        limit = body * 0.6
        n = 0
        for v in sd[:limit_rows]:
            if v >= limit:
                break
            n += 1
        return int(round(n / scale))

    base, others = stack[0], stack[1:]
    n = 0
    for h in range(10, limit_rows + 1, 10):
        diffs = [float(np.abs(a[-h:] - base[-h:]).mean()) for a in others]
        if sum(1 for d in diffs if d < 12.0) / len(diffs) < 0.6:
            break
        n = h
    return int(round(n / scale))


def stitch(tiles, total_css: int, view_css: int, out_path: Path,
           sticky_css: int = 0, sticky_bottom_css: int = 0, trim=None):
    """scrollTopの実測値をもとに決定的に結合する（画像差分による重なり探索は不要）。

    各タイルは scrollTop から view_css 分の内容を写している。
    スケール（画像px / CSS px）はタイル画像の高さから求める。

    高さは「ページ全体の高さ」ではなく、**実際にスクロールできた範囲**で決める。
    表示領域の幅に合わせてページを縮小する実装では、スクロールできる量が
    ページ全高より小さい。ページ全高を使うと、下半分が真っ白な画像になる。

    返り値は (保存先, 実際に使った左右, 自分で判定した左右)。
    """
    first = Image.open(tiles[0][0])
    scale = first.height / view_css
    width = first.width
    reached_css = max(t for _, t in tiles) + view_css
    height_css = min(total_css, reached_css)
    canvas = Image.new("RGB", (width, int(round(height_css * scale))), (255, 255, 255))

    # 画面に貼り付く要素（上のヘッダー、下のバーやチャットボタン）は、
    # すべてのタイルに写り込む。そのまま並べると継ぎ目ごとに繰り返し現れる。
    # 2枚目以降は上を、最後以外は下を切り落とす。
    # そこに入るはずの中身は、隣のタイルの重なり部分が持っている。
    cut_top = int(round(sticky_css * scale)) if sticky_css > 0 else 0
    cut_bottom = int(round(sticky_bottom_css * scale)) if sticky_bottom_css > 0 else 0
    last = len(tiles) - 1

    for i, (path, scroll_top) in enumerate(tiles):
        img = Image.open(path).convert("RGB")
        y = int(round(scroll_top * scale))
        top = cut_top if i > 0 else 0
        bottom = img.height - cut_bottom if i < last else img.height
        if bottom - top < 10:
            continue
        if top or bottom != img.height:
            img = img.crop((0, top, img.width, bottom))
            y += top
        canvas.paste(img, (0, y))

    # 自分で判定した左右は、切るかどうかに関わらず必ず控えておく。
    # 呼び出し側が、種別ごとの判定を持ち寄って決めるため。
    detected = trim_bounds(canvas)
    canvas, used = trim_margins(canvas, bounds=trim)
    out_path.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(out_path)
    return out_path, used, detected


def overlap_for(overlap: int, sticky_top, sticky_bottom) -> int:
    """タイル間の重なりを決める。

    貼り付く要素を消す場合、その高さぶんは隣のタイルで埋めるので、
    重なりをその合計より広く取っておく必要がある。
    自動判定は撮り終えないと分からないため、先に広めに取っておく。
    """
    if sticky_top == "auto" or sticky_bottom == "auto":
        return max(overlap, AUTO_STICKY_MAX * 2 + 8)
    need = int(sticky_top) + int(sticky_bottom)
    return max(overlap, need + 8) if need > 0 else overlap
