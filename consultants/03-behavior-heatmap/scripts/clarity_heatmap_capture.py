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
from datetime import date
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

sys.path.insert(0, str(Path(__file__).resolve().parent))

# 画像の結合・余白落とし・貼り付く要素の判定は Ptengine 側と同じ問題が出る。
# 二重管理にしないため heatmap_image.py に集めてある。
from heatmap_image import (  # noqa: E402
    AUTO_STICKY_MAX, detect_sticky, overlap_for, parse_trim, stitch,
    trim_bounds, trim_margins,
)

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


def date_params(value: str) -> dict:
    """期間の指定を、Clarityが受け取る形に直す。

    **月次レポートで「過去30日間」を使ってはいけない。**
    実行した日から遡るため、暦月とずれる。9月1日に撮れば 8/2〜9/1 になり、
    8月1日が抜けて9月1日が混ざる。実際にそれで撮ってしまった月がある。

    そこで暦月と任意の範囲を受け取れるようにする。
    Clarityのカスタム期間は**エポックミリ秒**で渡す（実測で確認。画面の表示が
    `08/01/2026 00:00 - 08/31/2026 23:59` になる）。

        2026-08                  … その月の1日 00:00 〜 末日 23:59
        2026-08-01..2026-08-31   … 指定した範囲
        Last 30 days             … UIの選択肢の文字列。そのまま渡す

    時刻はこのPCの時間帯で解釈する。Clarityの画面も同じ時間帯で表示する。
    """
    import re
    from datetime import datetime, timedelta

    def span(start, end) -> dict:
        # 終了日はその日を含む。23:59:59 まで取る。
        s = datetime(start.year, start.month, start.day)
        e = datetime(end.year, end.month, end.day, 23, 59, 59)
        return {"date": "Custom",
                "start": str(int(s.timestamp() * 1000)),
                "end": str(int(e.timestamp() * 1000))}

    m = re.fullmatch(r"(\d{4})-(\d{2})", value)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        first = date(y, mo, 1)
        nxt = date(y + (mo == 12), (mo % 12) + 1, 1)
        return span(first, nxt - timedelta(days=1))

    m = re.fullmatch(r"(\d{4}-\d{2}-\d{2})\.\.(\d{4}-\d{2}-\d{2})", value)
    if m:
        return span(date.fromisoformat(m.group(1)),
                    date.fromisoformat(m.group(2)))

    return {"date": value}


def build_url(args: argparse.Namespace) -> str:
    """Clarityヒートマップ画面のURLを組み立てる。

    URL照合条件の値は二重エンコードになる。urlencode に quote を渡して
    `%` を `%25` に変換させることで、エンコード済み文字を含むURLでも壊れない。
    """
    match_value = args.url_match or args.page_url
    params = {
        **date_params(args.date),
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


def wait_for_visual(page, timeout_s: float):
    """ヒートマップ表示領域を待って、(セレクタ, 分割して撮るか) を返す。

    **1画面に収まるページでは、表示領域がスクロールしない。**
    ログインだけのページなど、内容が少ないページで起きる。
    実測では、スクロールデータが 5%〜95% すべて「訪問者の100%」で
    ドロップオフ0%、つまり全員が最下部に到達しているページだった。

    以前はスクロールできることを条件にしていたため、こうしたページで
    「表示領域が見つかりません」と誤って失敗していた。
    スクロールしないなら、分割せず1枚で撮ればよい。
    """
    deadline = time.time() + timeout_s
    own = f"#{VISUAL_ID}"

    # ★ #heatmapVisual があるなら、それ以外は見ない。
    #
    # 以前は「スクロールできる大きなdiv」を代わりに探していたが、
    # 1画面に収まるページでは #heatmapVisual がスクロールしないため、
    # 代わりに**左側のランキングパネル**（クリック数の多い順・312要素で
    # 37,000px）が選ばれてしまった。ヒートマップではないものを、
    # ヒートマップとして保存していたことになる。
    while time.time() < deadline:
        geo = page.evaluate(READ_GEOMETRY, own)
        if geo and geo["clientHeight"] >= 300:
            if geo["scrollHeight"] > geo["clientHeight"] + 50:
                return own, True
            print(f"[*] 表示領域がスクロールしません（高さ "
                  f"{geo['clientHeight']}px）。"
                  f"1画面に収まるページとみて、1枚で撮ります。")
            return own, False
        time.sleep(1.0)

    # id が見つからない場合だけ、代わりを探す。
    # id が変わったときの保険であり、上の取り違えとは別の話。
    page.evaluate(FIND_VISUAL, VISUAL_ID)
    sub = "[data-capture-target='1']"
    geo = page.evaluate(READ_GEOMETRY, sub)
    if geo and geo["scrollHeight"] > geo["clientHeight"] + 50:
        print(f"[*] #{VISUAL_ID} が見つからないため、代わりの要素を使います。")
        return sub, True

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

        sel, tiled = wait_for_visual(page, args.timeout)
        geo = page.evaluate(READ_GEOMETRY, sel)
        total, view = geo["scrollHeight"], geo["clientHeight"]

        if not tiled:
            # スクロールしない＝1画面に収まっている。1枚撮って終わり。
            path = tiles_dir / "tile_000.png"
            page.locator(sel).screenshot(path=str(path))
            ctx.close()
            raw = Image.open(path).convert("RGB")
            detected = trim_bounds(raw)
            im, used = trim_margins(raw, bounds=parse_trim(args.trim))
            joined = out_dir / f"heatmap_{args.type}_joined.png"
            im.save(joined)
            (out_dir / "capture_meta.json").write_text(
                json.dumps({
                    "clarityUrl": url,
                    "pageUrl": args.page_url,
                    "urlMatch": args.url_match or args.page_url,
                    "matchOp": args.op,
                    "device": args.device,
                    "date": args.date,
                    "heatmapType": args.type,
                    "pageHeightCss": total,
                    "viewHeightCss": view,
                    "stickyTopCss": 0,
                    "stickyBottomCss": 0,
                    "trimLeftRight": list(used) if used else None,
                    "trimDetected": list(detected) if detected else None,
                    "onePiece": True,
                    "tiles": [{"file": path.name, "scrollTop": 0}],
                    "joined": joined.name,
                }, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"[+] 結合画像: {joined}（1枚撮り {im.size[0]}x{im.size[1]}）")
            print(f"[+] メタ情報: {out_dir / 'capture_meta.json'}")
            return joined
        overlap = overlap_for(args.overlap, args.sticky_top, args.sticky_bottom)
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

    joined, used, detected = stitch(tiles, total, view,
                                    out_dir / f"heatmap_{args.type}_joined.png",
                                    sticky_css=sticky_top,
                                    sticky_bottom_css=sticky_bottom,
                                    trim=parse_trim(args.trim))
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
        "trimLeftRight": list(used) if used else None,
        "trimDetected": list(detected) if detected else None,
        "tiles": [{"file": p.name, "scrollTop": t} for p, t in tiles],
        "joined": joined.name,
    }
    (out_dir / "capture_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8"
    )
    print(f"[+] 結合画像: {joined}")
    print(f"[+] メタ情報: {out_dir / 'capture_meta.json'}")
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
    p.add_argument(
        "--date", default="Last 30 days",
        help="期間。月次レポートでは暦月を渡す（2026-08）。"
             "任意の範囲は 2026-08-01..2026-08-31。"
             "UIの選択肢の文字列（Last 30 days など）もそのまま使えるが、"
             "実行日から遡るため月次には向かない")
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
    p.add_argument(
        "--trim", default="auto",
        help="左右の余白を落とす位置。既定は auto（自分で判定）。"
             "「L,R」で明示。クリックマップの値をスクロールマップに"
             "引き継いで幅をそろえるために使う。"
             "「none」で余白を落とさない")
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
