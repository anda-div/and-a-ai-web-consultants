"""
Clarityヒートマップ 位置ずれのない分割キャプチャ＆結合
=====================================================

Clarityのヒートマップ表示領域（`#heatmapVisual`）は独立したスクロールコンテナで、
`scrollTop` を書き換えるとページ画像とヒートマップのレイヤーが同期して動く。
この性質を使い、マウス座標を一切使わずに全ページ分を分割キャプチャして縦に結合する。

画面座標を指定しないため、既定のダウンロードや画面キャプチャで起きる
「ボタン位置とヒートマップ位置がずれる」問題が起きない。

【動作環境】Python 3.9以上 + Playwright
【必要ライブラリ】pip install -r ../requirements.txt
                  python -m playwright install chromium

【初回のみ：ログイン】
    python scripts/clarity_heatmap_capture.py --login

    ブラウザが開くのでClarityにサインインする。認証情報は
    --profile で指定したフォルダに保存され、次回以降は再利用される。
    このフォルダはGitに追加しないこと（.gitignoreに追加済みのパスを使う）。

【キャプチャ】
    python scripts/clarity_heatmap_capture.py \
        --project <projectId> \
        --page-url https://example.com/category/shoes/ \
        --type tap \
        --device Mobile \
        --out output/heatmap_shoes_tap

    絞り込み後の状態を撮る場合は --url-match に絞り込み後のURLを渡す:
    --url-match "https://example.com/category/shoes/?stock=in&facet%5B%5D=round" --op exact

URLパラメータの意味は ../CLARITY_METRICS.md を参照。
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path
from urllib.parse import quote, urlencode

try:
    from PIL import Image
except ImportError:  # pragma: no cover
    print("Pillow が必要です: pip install -r ../requirements.txt", file=sys.stderr)
    raise

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    print("Playwright が必要です: pip install -r ../requirements.txt", file=sys.stderr)
    raise


BASE = "https://clarity.microsoft.com"
HEATMAP_TYPES = {"tap": "0", "scroll": "1"}
MATCH_OPS = {"endswith": "1", "contains": "2", "exclude": "3", "exact": "4"}
# ヒートマップを描画する画面幅。実測で確かめた対応。
#
# 名前から想像すると逆になる。実際に撮って幅と高さを見て確かめた結果：
#   0 → 幅  410px / 高さ 12471px  スマートフォン
#   1 → 幅 1413px / 高さ 10236px  タブレット
#   2 → 幅 1492px / 高さ  6471px  PC
# 既定値が 0 なので、指定を忘れるとPCのつもりでスマートフォンを撮ることになる。
DEVICE_VIEWS = {"Mobile": "0", "Tablet": "1", "Desktop": "2"}

# ヒートマップ表示領域。idは安定しているが、変更された場合は
# 「スクロール可能でclientHeightが大きい要素」を探す方にフォールバックする。
VISUAL_ID = "heatmapVisual"

# 貼り付く要素を自動判定するときの上限（CSS px）。
# これより大きく切ることはしない。本文を削る事故を防ぐため。
AUTO_STICKY_MAX = 200

FIND_VISUAL = """
(id) => {
  const byId = document.getElementById(id);
  if (byId && byId.scrollHeight > byId.clientHeight + 50) return id;
  let best = null;
  for (const e of document.querySelectorAll('div')) {
    if (e.scrollHeight <= e.clientHeight + 50) continue;
    if (e.clientHeight < 300) continue;
    if (!best || e.scrollHeight > best.scrollHeight) best = e;
  }
  if (!best) return null;
  best.setAttribute('data-capture-target', '1');
  return null;
}
"""

READ_GEOMETRY = """
(sel) => {
  const c = document.querySelector(sel);
  if (!c) return null;
  return { scrollHeight: c.scrollHeight, clientHeight: c.clientHeight, scrollTop: c.scrollTop };
}
"""

SET_SCROLL = """
([sel, top]) => {
  const c = document.querySelector(sel);
  c.scrollTop = top;
  return c.scrollTop;
}
"""


def build_url(args: argparse.Namespace) -> str:
    """Clarityヒートマップ画面のURLを組み立てる。

    URL照合条件の値は二重エンコードになる。urlencode に quote を渡して
    `%` を `%25` に変換させることで、エンコード済み文字を含むURLでも壊れない。
    """
    match_value = args.url_match or args.page_url
    params = {
        "date": args.date,
        "Device": args.device,
        "heatmapType": HEATMAP_TYPES[args.type],
        # Device はセッションの絞り込み、heatmapDeviceType は
        # 「どの画面幅で描画するか」。両方そろえないと、
        # スマートフォンで絞り込んでもPC幅の画面が出てくる。
        "heatmapDeviceType": (args.heatmap_device_type
                              if args.heatmap_device_type is not None
                              else DEVICE_VIEWS.get(args.device, "0")),
        "url": args.page_url,
        "URL": f"2;{MATCH_OPS[args.op]};{match_value}",
    }
    return f"{BASE}/projects/view/{args.project}/heatmaps?" + urlencode(
        params, quote_via=quote
    )


def wait_for_visual(page, timeout_s: float) -> str:
    """ヒートマップ表示領域が現れてスクロール可能になるまで待ち、セレクタを返す。"""
    deadline = time.time() + timeout_s
    selector = f"#{VISUAL_ID}"
    while time.time() < deadline:
        page.evaluate(FIND_VISUAL, VISUAL_ID)
        for sel in (f"#{VISUAL_ID}", "[data-capture-target='1']"):
            geo = page.evaluate(READ_GEOMETRY, sel)
            if geo and geo["scrollHeight"] > geo["clientHeight"] + 50:
                return sel
        time.sleep(1.0)
    raise TimeoutError(
        "ヒートマップ表示領域が見つかりません。"
        "ログイン状態、期間・デバイス・URL照合条件、描画完了を確認してください。"
    )


def capture(args: argparse.Namespace) -> Path:
    out_dir = Path(args.out)
    tiles_dir = out_dir / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    url = build_url(args)
    print(f"[*] {url}")

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(Path(args.profile).expanduser()),
            headless=False,
            channel=args.channel or None,
            viewport={"width": args.window_width, "height": args.window_height},
            locale="ja-JP",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(url, wait_until="load", timeout=90_000)
        page.wait_for_timeout(int(args.settle * 1000))

        sel = wait_for_visual(page, args.timeout)
        geo = page.evaluate(READ_GEOMETRY, sel)
        total, view = geo["scrollHeight"], geo["clientHeight"]
        # 貼り付く要素を消す場合、その高さぶんは隣のタイルで埋めるので、
        # 重なりをその合計より広く取っておく必要がある。
        # 自動判定は撮り終えないと分からないため、先に広めに取っておく。
        auto = args.sticky_top == "auto" or args.sticky_bottom == "auto"
        overlap = args.overlap
        if auto:
            overlap = max(overlap, AUTO_STICKY_MAX * 2 + 8)
        else:
            need = int(args.sticky_top) + int(args.sticky_bottom)
            if need > 0:
                overlap = max(overlap, need + 8)
        step = max(50, view - overlap)
        print(f"[*] 領域 {sel} / ページ高さ {total}px / 表示高さ {view}px / 送り {step}px")

        locator = page.locator(sel)
        tiles: list[tuple[Path, int]] = []
        top = 0
        index = 0
        seen: set[int] = set()
        while index < args.max_tiles:
            actual = page.evaluate(SET_SCROLL, [sel, top])
            page.wait_for_timeout(int(args.tile_delay * 1000))
            if actual in seen:
                break
            seen.add(actual)
            path = tiles_dir / f"tile_{index:03d}.png"
            locator.screenshot(path=str(path))
            tiles.append((path, int(actual)))
            print(f"    tile {index:03d}  scrollTop={int(actual)}")
            if actual + view >= total - 1:
                break
            top = int(actual) + step
            index += 1
        ctx.close()

    if not tiles:
        raise RuntimeError("キャプチャが取得できませんでした。")

    def resolve(value, side: str) -> int:
        if value != "auto":
            return int(value)
        got = detect_sticky(tiles, view, side)
        got = min(got, AUTO_STICKY_MAX)
        print(f"[*] 貼り付く要素（{side}）を {got}px と判定しました")
        return got

    sticky_top = resolve(args.sticky_top, "top")
    sticky_bottom = resolve(args.sticky_bottom, "bottom")

    joined = stitch(tiles, total, view, out_dir, args.type,
                    sticky_css=sticky_top,
                    sticky_bottom_css=sticky_bottom)
    meta = {
        "clarityUrl": url,
        "pageUrl": args.page_url,
        "urlMatch": args.url_match or args.page_url,
        "matchOp": args.op,
        "device": args.device,
        "date": args.date,
        "heatmapType": args.type,
        "pageHeightCss": total,
        "viewHeightCss": view,
        "stickyTopCss": sticky_top,
        "stickyBottomCss": sticky_bottom,
        "tiles": [{"file": p.name, "scrollTop": t} for p, t in tiles],
        "joined": joined.name,
    }
    (out_dir / "capture_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[+] 結合画像: {joined}")
    print(f"[+] メタ情報: {out_dir / 'capture_meta.json'}")
    return joined


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
        # 1行だけの跳ねで打ち切らないよう、9行の移動平均でならす
        k = np.ones(9) / 9
        sd = np.convolve(sd, k, mode="same")
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


def trim_margins(im: Image.Image, pad: int = 4) -> Image.Image:
    """左右の白い余白を落とし、ページ本体だけにする。

    Clarityは表示領域の中央にページを縮小表示するため、両側に白い帯が残る。
    そのまま資料に貼ると、ページが小さく余白ばかりの図になる。

    「白でない画素が1つでもある列」を探すやり方では切れない。
    枠線やスクロールバーが端に写り込んでいて、端の列も白ではないため。
    **列ごとに中身の割合を見て、その割合が高い列が連続する一番長い区間**を取る。
    上下は切らない（ページの先頭と末尾は情報として残す）。
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
        return im
    left = max(0, left - pad)
    right = min(im.width, right + pad)
    return im.crop((left, 0, right, im.height))


def stitch(tiles, total_css: int, view_css: int, out_dir: Path, kind: str,
           sticky_css: int = 0, sticky_bottom_css: int = 0) -> Path:
    """scrollTopの実測値をもとに決定的に結合する（画像差分による重なり探索は不要）。

    各タイルは scrollTop から view_css 分の内容を写している。
    スケール（画像px / CSS px）はタイル画像の高さから求める。

    高さは「ページ全体の高さ」ではなく、**実際にスクロールできた範囲**で決める。
    Clarityは表示領域の幅に合わせてページを縮小するため、
    スクロールできる量はページ全高より小さい。ページ全高を使うと、
    下半分が真っ白な画像になる。
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

    canvas = trim_margins(canvas)
    joined = out_dir / f"heatmap_{kind}_joined.png"
    canvas.save(joined)
    return joined


def login(args: argparse.Namespace) -> None:
    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(Path(args.profile).expanduser()),
            headless=False,
            channel=args.channel or None,
            viewport={"width": args.window_width, "height": args.window_height},
            locale="ja-JP",
        )
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        page.goto(f"{BASE}/projects", wait_until="load", timeout=90_000)
        print("ブラウザでClarityにサインインしてください。")
        print("済んだら、そのブラウザの窓を閉じてください。")
        print("（このターミナルでのキー入力は要りません）")
        print()

        # ターミナルの入力待ちにしない。AIの実行環境や `!` 経由では
        # 標準入力が閉じており、input() が即座に EOFError になるため。
        # ブラウザが閉じられたことを、開いているページ数で判断する。
        deadline = time.time() + args.login_timeout
        last = -1
        while time.time() < deadline:
            try:
                if not ctx.pages:
                    break
            except Exception:
                break          # 窓ごと閉じられた
            left = int(deadline - time.time())
            if left // 30 != last:
                last = left // 30
                print(f"  待機中… 残り {left // 60}分{left % 60}秒")
            time.sleep(2.0)
        else:
            print("時間切れです。もう一度実行してください。")

        try:
            ctx.close()
        except Exception:
            pass
    print(f"認証情報を保存しました: {args.profile}")


def parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(
        description="Clarityヒートマップの分割キャプチャ＆結合",
    )
    p.add_argument("--login", action="store_true", help="初回のサインインだけを行う")
    p.add_argument("--project", help="ClarityのプロジェクトID")
    p.add_argument("--page-url", help="ヒートマップの下敷きにするページのURL")
    p.add_argument(
        "--url-match",
        help="集計対象ページの照合値。省略時は --page-url を使う",
    )
    p.add_argument(
        "--op", default="exact", choices=sorted(MATCH_OPS), help="URL照合の方法"
    )
    p.add_argument(
        "--type", default="tap", choices=sorted(HEATMAP_TYPES), help="ヒートマップ種別"
    )
    p.add_argument("--device", default="Mobile", help="Mobile / Desktop / Tablet")
    p.add_argument("--date", default="Last 30 days", help="期間。UIの選択肢と同じ文字列")
    p.add_argument("--out", default="output/clarity_heatmap", help="出力フォルダ")
    p.add_argument(
        "--profile",
        default=".clarity_profile",
        help="認証情報を保存するブラウザプロファイルのフォルダ。Gitに追加しない",
    )
    p.add_argument(
        "--heatmap-device-type",
        default=None,
        help="描画する画面幅の指定を直接与える（0/1/2）。通常は --device から決まる",
    )
    p.add_argument(
        "--sticky-top",
        default="auto",
        help="画面上部に貼り付くヘッダーの高さ（CSS px）。2枚目以降から取り除き、"
             "継ぎ目ごとにヘッダーが繰り返すのを防ぐ。auto で自動判定（既定）、0で無効",
    )
    p.add_argument(
        "--sticky-bottom",
        default="auto",
        help="画面下部に貼り付く要素の高さ（CSS px）。固定バーやチャットボタンなど。"
             "最後のタイル以外から取り除く。auto で自動判定（既定）、0で無効",
    )
    p.add_argument(
        "--login-timeout",
        type=float,
        default=900.0,
        help="--login でサインインを待つ上限（秒）。既定15分",
    )
    p.add_argument(
        "--channel",
        default="",
        help="インストール済みブラウザを使う場合に指定（例: chrome）",
    )
    p.add_argument("--window-width", type=int, default=1920)
    p.add_argument("--window-height", type=int, default=1200)
    p.add_argument("--overlap", type=int, default=40, help="タイル間の重なり（CSS px）")
    p.add_argument("--settle", type=float, default=8.0, help="初回描画の待機秒")
    p.add_argument("--tile-delay", type=float, default=1.2, help="1タイルごとの待機秒")
    p.add_argument("--timeout", type=float, default=60.0, help="表示領域待ちの上限秒")
    p.add_argument("--max-tiles", type=int, default=60, help="安全装置")
    args = p.parse_args(argv)

    if not args.login:
        missing = [n for n in ("project", "page_url") if not getattr(args, n)]
        if missing:
            p.error("--" + " と --".join(m.replace("_", "-") for m in missing) + " が必要です")
    return args


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.login:
        login(args)
        return 0
    capture(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
