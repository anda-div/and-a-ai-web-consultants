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

# ヒートマップ表示領域。idは安定しているが、変更された場合は
# 「スクロール可能でclientHeightが大きい要素」を探す方にフォールバックする。
VISUAL_ID = "heatmapVisual"

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
        "heatmapDeviceType": "0",
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
        step = max(50, view - args.overlap)
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

    joined = stitch(tiles, total, view, out_dir, args.type)
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
        "tiles": [{"file": p.name, "scrollTop": t} for p, t in tiles],
        "joined": joined.name,
    }
    (out_dir / "capture_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[+] 結合画像: {joined}")
    print(f"[+] メタ情報: {out_dir / 'capture_meta.json'}")
    return joined


def stitch(tiles, total_css: int, view_css: int, out_dir: Path, kind: str) -> Path:
    """scrollTopの実測値をもとに決定的に結合する（画像差分による重なり探索は不要）。

    各タイルは scrollTop から view_css 分の内容を写している。
    スケール（画像px / CSS px）はタイル画像の高さから求める。
    """
    first = Image.open(tiles[0][0])
    scale = first.height / view_css
    width = first.width
    canvas = Image.new("RGB", (width, int(round(total_css * scale))), (255, 255, 255))

    for path, scroll_top in tiles:
        img = Image.open(path).convert("RGB")
        canvas.paste(img, (0, int(round(scroll_top * scale))))

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
        print("完了したらこのターミナルで Enter を押します。")
        input()
        ctx.close()
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
