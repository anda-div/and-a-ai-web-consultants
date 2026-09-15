# -*- coding: utf-8 -*-
"""Ptengineヒートマップ 位置ずれのない分割キャプチャ＆結合

Clarityとの一番大きな違いは、**状態がURLに載らない**ことである。

    Clarity   ?date=…&Device=…&heatmapType=… で状態が決まる。URLが証拠になる
    Ptengine  URLにあるのは対象ページのパラメータとセッション用の値だけ。
              期間・デバイス・種別はUIの状態で、クライアント側に保存される

そのため、このスクリプトは**UIを操作して状態を作り、作れたことを画面から
読み戻して確かめてから**撮る。読み戻した値が意図と違えば、撮らずに止める。

**ここを省くと、前回の状態のまま撮った画像が、意図した条件の名前で保存される。**
状態は再読み込みしても残るため、URLにもファイル名にも痕跡がない。
実際にデバイスをPCへ切り替えたあと、URLを変えて開き直してもPCのままだった。

もう一つの違いは、**下敷きが保存済みの画像ではなく実サイト**であること。
撮るたびにページを読み込むため、同じ条件でも全高が変わる（実測で 12400→12406、
PCで 14145→15013）。**サイト改修があった月は、過去の熱が現在のページに乗る。**
そのため撮影時点の全高をメタに必ず残す。

【画面の構造】実機で確認

    document
      └ iframe#pt-heatmap            … UI全体。同一オリジン
          ├ div.deviceScrollWrap     … スクロールコンテナ（Clarityの #heatmapVisual 相当）
          │   ├ iframe               … 対象ページ（実サイト）
          │   └ canvas.hm-canvas     … 熱レイヤー。ページ全高ぶん描画済み
          └ ツールバー（種別タブ・デバイス・期間）

    scrollTop を書き換えると、ページ側の scrollY も同じ値になり、
    熱レイヤーはちょうど -scrollTop だけ動く。**ずれ幅が scrollTop と厳密に一致する**ので、
    結合位置は計算で決まる（実測: scrollTop=3000 → ページ 3000 / 熱 +180→-2820）。

【動作環境】Python 3.9以上 + Playwright
【必要ライブラリ】pip install -r requirements.txt
                  python -m playwright install chromium

【初回のみ：ログイン】
    python scripts/ptengine_heatmap_capture.py --login

【キャプチャ】
    python scripts/ptengine_heatmap_capture.py \
        --sid <ワークスペースID> \
        --page-url https://example.com/lp/a.html \
        --type click --device Mobile --date 2026-08 \
        --out output/lp_a_click
"""
from __future__ import annotations

import argparse
import json
import re
import sys
import time
from datetime import date, datetime, timedelta
from pathlib import Path
from urllib.parse import urlparse

sys.path.insert(0, str(Path(__file__).resolve().parent))

from heatmap_image import (  # noqa: E402
    AUTO_STICKY_MAX, detect_sticky, overlap_for, parse_trim, stitch,
)
from ptengine_dates import (  # noqa: E402
    disabled_reason, month_span, months_to_move,
)

try:
    from playwright.sync_api import sync_playwright
except ImportError:  # pragma: no cover
    raise SystemExit("Playwright が必要です: pip install -r requirements.txt")

APP = "https://www.ptengine.jp/app"

# UI全体を包む同一オリジンのiframe
UI_FRAME = "#pt-heatmap"
# スクロールコンテナ。Clarityの #heatmapVisual にあたる
SCROLLER = ".deviceScrollWrap"
# 熱レイヤー。準備完了の判定に使う
HEAT = "canvas.hm-canvas"

# 種別タブの表示名。**クラス名では選べない。**
# タブは `h-8 min-w-10 flex px-3 …` のようなユーティリティクラスだけを持ち、
# 種別を見分けられる印が無い。表示名で選ぶ。
TYPES = {
    "click": "クリック",
    "attention": "滞在",
    "exit": "離脱",
    "conversion": "コンバージョン",
}

DEVICES = {"Mobile": "スマートフォン", "Desktop": "PC", "Tablet": "タブレット"}

# 種別が選ばれているかの見分け方。
#
# **タブ自身には選択の印が付かない。** 代わりに、その下のサブ種別の
# ドロップダウンが種別に応じた名前になる（実測）。
#
#   クリック       → 「クリックヒートマップ」「要素クリック」
#   滞在           → 「アテンション」
#   離脱           → 「離脱率」
#   コンバージョン → 「要素コンバージョン」
#
# そこで、選択中の表示の中にこの語が含まれるかで確かめる。
TYPE_MARKS = {"click": "クリック", "attention": "アテンション",
              "exit": "離脱", "conversion": "コンバージョン"}

# 期間のプリセット。**月次では使わない。** 実行日から決まるため。
PRESETS = {"today": "今日", "yesterday": "昨日", "this-week": "今週",
           "last-week": "先週", "this-month": "今月", "last-month": "先月",
           "last-7-days": "過去 7 日間"}


# ---------------------------------------------------------------- 画面を読む
READ_STATE = """
() => {
  const d = document;
  const t = e => (e.textContent || '').replace(/\\s+/g, ' ').trim();
  const sel = [...d.querySelectorAll('.is-selected, .selected, .pt-dropdown-menu__item.is-selected')]
    .map(t).filter(s => s && s.length < 24);
  const sw = d.querySelector('DEVICE_SCROLLER');
  const heat = [...d.querySelectorAll('HEAT_SEL')];
  // 期間ラベル。**子要素の有無で絞ってはいけない。**
  // ラベルは必ず子を持つ要素の中にあり、「子が無い要素」に限ると常に空になる。
  // 空のまま verify() を通すと、期間を確かめているつもりで素通りする。
  // 一致した中で**最短**のものを採れば、外側の親要素を拾わずに済む。
  const label = [...d.querySelectorAll('*')].map(t)
    .filter(s => /\\d{1,2}\\/\\d{1,2}\\s*-\\s*\\d{1,2}\\/\\d{1,2}/.test(s))
    .sort((a, b) => a.length - b.length)[0] || '';
  return {
    selected: sel,
    dateLabel: label,
    scrollHeight: sw ? sw.scrollHeight : 0,
    clientHeight: sw ? sw.clientHeight : 0,
    clientWidth: sw ? sw.clientWidth : 0,
    heat: heat.map(c => [c.width, c.height]),
    // 離脱とコンバージョンは**熱のcanvasを使わず、％のラベルで描く**。
    // 描画が終わったかの手がかりが種別で違うので、両方を数えておく。
    pctLabels: [...d.querySelectorAll('*')].filter(
      e => e.children.length === 0 && /^\\d{1,3}(\\.\\d+)?%$/.test(t(e)) && e.offsetHeight > 4
    ).length,
  };
}
""".replace("DEVICE_SCROLLER", SCROLLER).replace("HEAT_SEL", HEAT)

SET_SCROLL = """
([sel, top]) => { const c = document.querySelector(sel); c.scrollTop = top; return c.scrollTop; }
"""

# 表示名で要素を探し、**印を付けるだけ**にする。クラス名に頼らない。
#
# **DOMの click() では開かない部品がある。** 期間のボタンがそれで、
# 合成イベントには反応せず、本物のマウス操作を待っている（実測）。
# そこで印を付けて、押すのは Playwright 側（実際のマウスイベント）に任せる。
MARK = "data-pt-hit"

MARK_BY_TEXT = """
([text, maxTop]) => {
  const t = e => (e.textContent || '').replace(/\\s+/g, ' ').trim();
  document.querySelectorAll('[MARK_ATTR]').forEach(e => e.removeAttribute('MARK_ATTR'));
  const hit = [...document.querySelectorAll('div, span, li, button, td')]
    .filter(e => t(e) === text && e.offsetHeight > 8 &&
                 (maxTop < 0 || e.getBoundingClientRect().top < maxTop))
    .sort((a, b) => a.getBoundingClientRect().width - b.getBoundingClientRect().width)[0];
  if (!hit) return false;
  hit.setAttribute('MARK_ATTR', '1');
  return true;
}
""".replace("MARK_ATTR", MARK)


def ui(page):
    """UI全体を包むフレームを返す。"""
    el = page.query_selector(UI_FRAME)
    if el is None:
        raise TimeoutError(
            f"{UI_FRAME} が見つかりません。ヒートマップが立ち上がっていません。"
            "ログイン状態と、そのページにヒートマップのデータがあるかを確認してください。")
    frame = el.content_frame()
    if frame is None:
        raise TimeoutError(f"{UI_FRAME} の中身を読めません。")
    return frame


def read_state(page) -> dict:
    return ui(page).evaluate(READ_STATE)


def click_text(page, text: str, max_top: int = -1) -> bool:
    """表示名で探して、**本物のマウス操作で**押す。

    合成イベント（DOMの click()）に反応しない部品があるため、
    印を付けてから Playwright に押させる。
    """
    frame = ui(page)
    if not frame.evaluate(MARK_BY_TEXT, [text, max_top]):
        return False
    frame.click(f"[{MARK}='1']", timeout=15_000)
    return True


# 初回だけ出る拡張機能の案内。**UI全体を押し下げるので先に消す。**
# 普段お使いのブラウザでは出ないため、自動化して初めて当たる。
DISMISS_BANNER = """
() => {
  const t = e => (e.textContent || '').replace(/\\s+/g, ' ').trim();
  const b = [...document.querySelectorAll('button, span, div, a')]
    .filter(e => e.offsetHeight > 8 && /^(スキップ|Skip|閉じる)$/.test(t(e)))
    .sort((a, b2) => t(a).length - t(b2).length)[0];
  if (!b) return false;
  b.setAttribute('MARK_ATTR', '1');
  return true;
}
""".replace("MARK_ATTR", MARK)


def open_date(page) -> bool:
    """期間のボタンを押す。**本物のマウス操作でないと開かない。**"""
    frame = ui(page)
    if not frame.evaluate(OPEN_DATE):
        return False
    frame.click(f"[{MARK}='1']", timeout=15_000)
    return True


def dismiss_banner(page) -> None:
    """案内バーが出ていれば閉じる。無ければ何もしない。"""
    for where in (ui(page), page):
        try:
            if where.evaluate(DISMISS_BANNER):
                where.click(f"[{MARK}='1']", timeout=10_000)
                page.wait_for_timeout(1200)
                print("[*] 拡張機能の案内バーを閉じました")
                return
        except Exception:
            pass


# ヒートマップリストは、アプリ画面の中の**別オリジンの入れ子iframe**で描かれる。
# メインフレームを見ても行は見つからない（実測：本文228字しかない）。
REPORT_HOST = "reportv3.ptengine.jp"


def list_url(sid: str) -> str:
    return f"{APP}/{sid}/insight/pagescene/pagescenelist"


def same_page(a: str, b: str) -> bool:
    """クエリと末尾スラッシュを無視して、同じページかを見る。

    リストの既定は「パラメーター除去後」で、URLはクエリを落として表示される。
    利用者が utm 付きのURLを渡しても照合できるようにする。
    """
    def norm(u: str) -> str:
        p = urlparse(u.strip())
        host = (p.netloc or "").lower().removeprefix("www.")
        return f"{host}{(p.path or '/').rstrip('/')}"
    return norm(a) == norm(b)


MARK_ROW = """
(want) => {
  const t = e => (e.textContent || '').replace(/\\s+/g, ' ').trim();
  const norm = u => { try { const p = new URL(u);
      return p.host.replace(/^www\\./, '') + (p.pathname || '/').replace(/\\/$/, ''); }
      catch (e) { return ''; } };
  const target = norm(want);
  const hit = [...document.querySelectorAll('a')]
    .find(e => e.offsetHeight > 4 && /^https?:\\/\\//.test(t(e)) && norm(t(e)) === target);
  if (!hit) return 0;
  hit.setAttribute('data-pt-pick', '1');
  return 1;
}
"""

LIST_ROWS = """
() => {
  const t = e => (e.textContent || '').replace(/\\s+/g, ' ').trim();
  return [...document.querySelectorAll('a')].map(t)
    .filter(s => /^https?:\\/\\//.test(s)).slice(0, 12);
}
"""


def report_frame(page):
    """リストを描いている入れ子iframeを返す。"""
    for f in page.frames:
        if REPORT_HOST in (f.url or ""):
            return f
    return None


# リストは**複数ページに分かれる**（実測で5ページ）。
# 表示中のページだけを見ると、対象が2ページ目以降にあるとき見つからない。
# 実際に、翌日になって順位が下がったLPが1ページ目から外れ、撮れなくなった。
# ページ送りをたどるより、**検索窓で絞り込む**ほうが確実で速い。
SEARCH_ROW = """
(path) => {
  const box = [...document.querySelectorAll('input')]
    .find(e => e.offsetHeight > 6 &&
               /キーワード|URL|検索|search/i.test(
                 (e.placeholder || '') + ' ' + (e.getAttribute('aria-label') || '')));
  if (!box) return false;
  box.setAttribute('MARK_ATTR', '1');
  return true;
}
""".replace("MARK_ATTR", MARK)


def search_list(frame, page, path: str) -> bool:
    """リストの検索窓で対象ページを絞り込む。"""
    if not frame.evaluate(SEARCH_ROW, path):
        return False
    box = frame.locator(f"[{MARK}='1']")
    box.click(timeout=10_000)
    box.fill(path, timeout=10_000)
    box.press("Enter", timeout=10_000)
    page.wait_for_timeout(4000)
    return True


def open_heatmap(ctx, page, sid: str, page_url: str, timeout_s: float):
    """リストから対象ページをクリックして、ヒートマップのタブを開く。

    **URLを組み立てて直接開くことはできない。**
    ヒートマップの起動には `ptengine_heatmap_token` が要り、これはリストの行を
    押したときに発行される。トークン無しで対象ページを開いても、サイトの計測タグが
    動くだけでヒートマップのUIは立ち上がらない（実測で確認）。

    リストは読み込みに時間がかかる（実測で15秒では足りない）。行が出るまで待つ。
    """
    page.goto(list_url(sid), wait_until="load", timeout=120_000)
    deadline = time.time() + timeout_s
    seen = []
    searched = False
    while time.time() < deadline:
        fr = report_frame(page)
        if fr is not None:
            try:
                # 1ページ目に無ければ、検索窓で絞り込んでから探し直す
                if not searched and fr.evaluate(LIST_ROWS):
                    searched = True
                    if not fr.evaluate(MARK_ROW, page_url):
                        path = urlparse(page_url).path or page_url
                        if search_list(fr, page, path):
                            print(f"[*] リストを「{path}」で絞り込みました")
                if fr.evaluate(MARK_ROW, page_url):
                    with ctx.expect_page(timeout=90_000) as info:
                        fr.click("[data-pt-pick='1']")
                    tab = info.value
                    tab.wait_for_load_state("load", timeout=120_000)
                    return tab
                seen = fr.evaluate(LIST_ROWS) or seen
            except Exception:
                pass                      # 描画の途中。次の周回で見る
        page.wait_for_timeout(2000)

    hint = ("\n  リストに出ているページ:\n    " + "\n    ".join(seen)) if seen else ""
    raise TimeoutError(
        f"ヒートマップリストに {page_url} が見つかりません。\n"
        "  リストの期間や絞り込みによっては、そのページが出ないことがあります。"
        "  画面で見えているURLをそのまま渡してください。" + hint)


# ---------------------------------------------------------------- 状態を作る
def set_device(page, device: str, timeout_s: float) -> None:
    """デバイスを切り替える。

    切り替えは見た目だけではない。**描画幅とページ全高が変わり、熱も再描画される**
    （実測: スマートフォン 375px・全高12400 → PC 1440px・全高14145）。
    PCは描画完了まで20秒以上かかることがある。
    """
    want = DEVICES[device]
    frame = ui(page)
    if want in read_state(page)["selected"]:
        return
    frame.click("[class*=devicePicker]")
    page.wait_for_timeout(600)
    if not click_text(page, want):
        raise RuntimeError(f"デバイス「{want}」が選べません。")
    settle(page, timeout_s, why=f"デバイス {want}")


def set_type(page, kind: str, timeout_s: float) -> None:
    """ヒートマップの種別を切り替える。

    種別ごとに描き方が違う。クリックと滞在は熱、離脱はブロック単位の率、
    コンバージョンは**どのコンバージョンを見るかの選択が別に要る**。
    """
    want = TYPES[kind]
    mark = TYPE_MARKS[kind]
    if any(mark in s for s in read_state(page)["selected"]):
        return
    # 種別タブは上のほうにある。同じ語が本文に出ても拾わないよう上端で絞る。
    # 案内バーが出ると全体が下へずれるため、余裕をみて 200px とする。
    if not click_text(page, want, 200):
        raise RuntimeError(f"種別「{want}」が選べません。")
    settle(page, timeout_s, why=f"種別 {want}")


# 期間のボタンを押す。**表示中の文言に頼らない。**
# ラベルは期間が変わるたびに変わるので、日付の形そのもので探す。
# ボタンはトグルなので、押したあと開いたかどうかを別に確かめる。
OPEN_DATE = ("""
() => {
  const t = e => (e.textContent || '').replace(/\\s+/g, ' ').trim();
  const re = /^\\d{1,2}\\/\\d{1,2}\\s*-\\s*\\d{1,2}\\/\\d{1,2}$/;
  document.querySelectorAll('[MARK_ATTR]').forEach(e => e.removeAttribute('MARK_ATTR'));
  const hit = [...document.querySelectorAll('div, span, button')]
    .filter(e => re.test(t(e)) && e.offsetHeight > 8)
    .sort((a, b) => t(a).length - t(b).length)[0];
  if (!hit) return false;
  hit.setAttribute('MARK_ATTR', '1');
  return true;
}
""").replace("MARK_ATTR", MARK)

# ピッカーが開いているか。
#
# **要素の有無では判定できない。** `.pt-picker-panel__shortarea` は閉じていても
# DOMに残っており、常に「開いている」と答えてしまう（実測）。
# 中の項目が**見えているか**（offsetHeight）で判定する。
DATE_PICKER_OPEN = """
() => {
  const t = e => (e.textContent || '').replace(/\\s+/g, ' ').trim();
  return [...document.querySelectorAll('div, span, li')]
    .some(e => t(e) === '期間指定' && e.offsetHeight > 8);
}
"""


PICK_DAY = """
([monthLabel, day]) => {
  const t = e => (e.textContent || '').replace(/\\s+/g, ' ').trim();
  // 月の見出しと表を対にする
  const tables = [...document.querySelectorAll('table')]
    .filter(x => x.rows.length >= 5 && [...x.rows[0].cells].some(c => /日|月|火/.test(t(c))));
  for (const tb of tables) {
    // 見出しは表の手前にある。さかのぼって「2026 年 9月」の形を探す
    let head = '', n = tb.parentElement;
    for (let i = 0; i < 5 && n; i++, n = n.parentElement) {
      const s = [...n.querySelectorAll('*')].map(t).find(x => /^20\\d\\d\\s*年\\s*\\d{1,2}月$/.test(x));
      if (s) { head = s.replace(/\\s+/g, ''); break; }
    }
    if (head !== monthLabel) continue;
    // 前後の月の日も同じ表に並ぶ。**1から始まる一番長い連番**が当月である
    const cells = [...tb.querySelectorAll('td')].filter(c => /^\\d{1,2}$/.test(t(c)));
    let best = null, run = null;
    for (let i = 0; i < cells.length; i++) {
      const v = parseInt(t(cells[i]), 10);
      if (v === 1) { run = { start: i, len: 1 }; }
      else if (run && v === run.len + 1) { run.len++; }
      else if (run) { if (!best || run.len > best.len) best = run; run = null; }
      if (run && (!best || run.len > best.len)) best = { ...run };
    }
    if (!best || day > best.len) return 'この月に ' + day + ' 日がありません';
    const cell = cells[best.start + day - 1];
    // **押せない日がある。** 未来の日と、遡れる範囲より古い日の両方。
    // 黙って効かないので、`disabled` だけを返して**理由は呼び出し側で決める**。
    // ここで「未来の日付」と決めつけると、古い月を指定したときに
    // 嘘の理由が出る（実測：1年以上前の月で「未来の日付」と表示された）。
    if (/disabled/.test(cell.className)) return 'disabled';
    cell.click();
    return true;
  }
  return '「' + monthLabel + '」の月が出ていません';
}
"""

# 月送り・年送りの矢印。4つ並ぶ（実測）。
#
#   pt-picker-panel__icon-btn pt-icon-d-arrow-left    « 年を戻す
#   pt-picker-panel__icon-btn pt-icon-arrow-left      ‹ 月を戻す
#   pt-picker-panel__icon-btn pt-icon-arrow-right     › 月を進める
#   pt-picker-panel__icon-btn pt-icon-d-arrow-right   » 年を進める
#
# **中身はSVGで、文字は入っていない。** 矢印の文字（‹ ›）で探しても見つからない。
# クラス名にちゃんと向きが入っているので、そちらで選ぶ。
#
# **押し方が期間ボタンと逆である。** 実測した結果はこうだった。
#
#   期間ボタン       … DOMの click() では開かない。本物のマウス操作が要る
#   カレンダーの矢印 … 本物のマウス操作では**動かない**。DOMの click() で動く
#
# 同じ画面の中で作法が違う。どちらかに揃えようとすると、片方が黙って効かなくなる。
MOVE_MONTH = """
([back, year]) => {
  const dir = back ? 'left' : 'right';
  const cls = 'pt-icon-' + (year ? 'd-' : '') + 'arrow-' + dir;
  let b = [...document.querySelectorAll('button')]
    .find(e => (e.className || '').toString().includes(cls) && e.offsetHeight > 3);
  if (!b) {
    // クラス名が変わったときの保険。向きの語だけを手がかりにする
    const re = back ? /(prev|left)/i : /(next|right)/i;
    const dbl = year ? /(^|[^a-z])d-/i : null;
    b = [...document.querySelectorAll('button')]
      .filter(e => e.offsetHeight > 3 && re.test((e.className || '').toString()))
      .filter(e => !dbl || dbl.test((e.className || '').toString()))[0];
  }
  if (!b) return 'ボタンが見つかりません';
  if (b.disabled) return 'ボタンが押せません（無効）';
  b.click();
  return true;
}
"""

# パネルの見出し。**画面全体から拾うと、関係のない文字列まで混ざる。**
# 見出しの入れ物を先に探し、無いときだけ全体から拾う。
READ_MONTHS = """
() => {
  const t = e => (e.textContent || '').replace(/\\s+/g, '').trim();
  const heads = [...document.querySelectorAll('.pt-date-range-picker__header')]
    .filter(e => e.offsetHeight > 4).map(t)
    .filter(s => /^20\\d\\d年\\d{1,2}月$/.test(s));
  if (heads.length) return heads;
  return [...new Set([...document.querySelectorAll('*')].map(t)
    .filter(s => /^20\\d\\d年\\d{1,2}月$/.test(s)))];
}
"""

def months_shown(frame) -> list:
    """カレンダーに出ている月を (年, 月) で返す。左のパネルが先頭。"""
    out = []
    for s in frame.evaluate(READ_MONTHS):
        m = re.fullmatch(r"(20\d\d)年(\d{1,2})月", s)
        if m:
            out.append((int(m.group(1)), int(m.group(2))))
    return out


def show_month(frame, page, want: date) -> None:
    """カレンダーに指定の月を出す。

    パネルは2か月ぶん並ぶ（例：9月と10月）。どちらかに出ていればよい。

    **1か月ずつ送ると、古い月では何十回も押すことになる。**
    12か月以上離れていれば年送り（`d-arrow`）でまとめて詰める。
    """
    for _ in range(48):
        shown = months_shown(frame)
        if not shown:
            raise RuntimeError(
                "カレンダーの月の見出しが読めません。画面の作りが変わった可能性があります。")
        move = months_to_move(shown, want)
        if move is None:
            return
        back, year, _diff = move
        got = frame.evaluate(MOVE_MONTH, [back, year])
        if got is not True:
            raise RuntimeError(
                f"カレンダーを {want.year}年{want.month}月 へ動かせません: {got}"
                f"（いま出ているのは {shown}）")
        page.wait_for_timeout(250)
    raise RuntimeError(f"カレンダーに {want.year}年{want.month}月 を出せません。")


def open_picker(page, frame) -> None:
    """期間のピッカーを開く。**開いたことを2回続けて確かめる。**

    ボタンはトグルなので、開いているときに押すと閉じる。だから
    「開いていなければ押す」で書くのだが、ここに落とし穴がある。

    **閉じかけのピッカーは、一瞬「開いている」ように見える。**
    直前の「適用」で閉じ始めた枠がまだ高さを持っているあいだに
    見にいくと、開いていると判断して押さずに進み、そのあと消える。
    次の操作が「要素が見えません」で落ちる（実測）。

    500ms あけて2回続けて開いていることを条件にする。
    """
    for _ in range(5):
        if frame.evaluate(DATE_PICKER_OPEN):
            page.wait_for_timeout(500)
            if frame.evaluate(DATE_PICKER_OPEN):
                return
            continue        # 消えかけだった。押し直す
        if not open_date(page):
            raise RuntimeError("期間のボタンが見つかりません。画面の作りが変わった可能性があります。")
        page.wait_for_timeout(1200)
    raise RuntimeError("期間のピッカーが開きません。")


def pick_day(frame, want: date) -> None:
    """カレンダーの1日を押す。押せない日なら、**理由を分けて**知らせる。"""
    label = f"{want.year}年{want.month}月"
    got = frame.evaluate(PICK_DAY, [label, want.day])
    if got is True:
        return
    if got == "disabled":
        raise RuntimeError(disabled_reason(want))
    raise RuntimeError(f"{want} を選べません: {got}")


def set_date(page, value: str, timeout_s: float) -> None:
    """期間を指定する。指定できたことを**必ず画面から読み戻して確かめる。**

    カレンダーの日セルは `<td class="available">` で、日付を表す属性を持たない。
    さらに前後の月の日（30, 31, 1, 2 …）が同じ表に並ぶ。
    そのため「1」を押すと前月末を押してしまう危険がある。
    **1から始まる一番長い連番が当月**という決め方で選び、最後にラベルで確かめる。
    """
    frame = ui(page)
    open_picker(page, frame)
    span = month_span(value)

    # **暦月を渡されたら、プリセットに読み替えない。**
    # 以前は「先月」と一致すればプリセットで済ませていたが、これは
    # 実行した日に依存する。月末の23時台に始めた取得が日付をまたぐと、
    # 「先月」の指す月がその場で1つずれる。暦月はカレンダーで指定する。
    if span is None:
        name = PRESETS.get(value)
        if name is None:
            raise SystemExit(
                f"--date の指定が読めません: {value}\n"
                "暦月（2026-08）か範囲（2026-08-01..2026-08-31）、"
                f"またはプリセット（{' / '.join(PRESETS)}）を渡してください。")
        if not click_text(page, name):
            raise RuntimeError(f"期間「{name}」が選べません。")
    else:
        start, end = span
        print(f"[*] 期間はカレンダーで指定します（{start} 〜 {end}）")
        # ピッカーが描き直されている最中は、押しても「見えない」で弾かれる。
        # **開き直してから**試す。待つだけでは、閉じてしまった場合に戻らない。
        for _ in range(3):
            try:
                if click_text(page, "期間指定"):
                    break
            except Exception:
                pass
            page.wait_for_timeout(800)
            open_picker(page, frame)
        else:
            raise RuntimeError("「期間指定」が選べません。")
        page.wait_for_timeout(500)
        # **年は、月の見出しで担保している。** PICK_DAY は
        # 「2026年8月」のように年を含む見出しと一致した表の中でしか押さない。
        # 適用後の期間ラベルには年が無い（「08/01-08/31」）ため、
        # ここで年をそろえておかないと、あとの検証では年のずれを見つけられない。
        for want in (start, end):
            show_month(frame, page, want)
            pick_day(frame, want)
            page.wait_for_timeout(400)

    if not click_text(page, "適用"):
        raise RuntimeError("「適用」が押せません。")
    settle(page, timeout_s, why=f"期間 {value}")


# ---------------------------------------------------------------- 覆いをどける
#
# **下敷きが実サイトなので、撮影時に出ていたポップアップがそのまま画像に入る。**
# Clarityは保存済みのスクリーンショットなので、この問題は起きなかった。
# 画面中央に出るモーダルは、Clarityの「上下端の固定要素を切る」では消せない。
#
# ここで守るべき一線は **ページの高さを変えないこと**。
# 高さが変わると、Ptengineが測ったときのページと形が変わり、熱の位置がずれる。
# そのため**流れから外れている要素（fixed / absolute / sticky）だけ**を隠し、
# 隠したあとに高さを測り直して、変わっていないことを確かめる。

PAGE_DOC = """
  const host = [...document.querySelectorAll('iframe')].find(f => f.clientWidth > 100);
  if (!host) return { error: '対象ページのiframeが見つかりません' };
  let d;
  try { d = host.contentDocument; } catch (e) { d = null; }
  if (!d) return { error: '対象ページを読めません（別オリジン）' };
"""

DETECT_OVERLAY = ("""
() => {
""" + PAGE_DOC + """
  const w = host.contentWindow;
  const vh = w.innerHeight || 1, vw = w.innerWidth || 1;
  const out = [];
  // **body の配下だけを見てはいけない。** モーダルは html 直下に足されることがあり、
  // body に限ると見つからない（実測：html直下のモーダルを取りこぼした）。
  for (const e of d.querySelectorAll('*')) {
    const cs = w.getComputedStyle(e);
    if (!['fixed', 'sticky', 'absolute'].includes(cs.position)) continue;
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue;
    const r = e.getBoundingClientRect();
    if (r.width * r.height < vw * vh * 0.15) continue;   // 小さいものは無視
    if (r.width < 40 || r.height < 40) continue;
    out.push({ tag: e.tagName, id: e.id || '',
               cls: (e.className || '').toString().slice(0, 60),
               w: Math.round(r.width), h: Math.round(r.height),
               pos: cs.position,
               text: (e.textContent || '').replace(/\\s+/g, ' ').trim().slice(0, 40) });
  }
  return { overlays: out.slice(0, 6) };
}
""")

HIDE_SELECTOR = ("""
(sel) => {
""" + PAGE_DOC + """
  const w = host.contentWindow;
  const before = d.documentElement.scrollHeight;
  let hidden = 0, skipped = [];
  for (const e of d.querySelectorAll(sel)) {
    const cs = w.getComputedStyle(e);
    if (!['fixed', 'sticky', 'absolute'].includes(cs.position)) {
      // **流れの中にある要素は隠さない。** 隠すとページが縮み、熱の位置がずれる。
      skipped.push(e.tagName + '.' + (e.className || '').toString().slice(0, 30)
                   + '（position: ' + cs.position + '）');
      continue;
    }
    e.style.setProperty('display', 'none', 'important');
    hidden++;
  }
  return { hidden, skipped, before, after: d.documentElement.scrollHeight };
}
""")


def hide_overlays(page, selectors: str) -> dict:
    """対象ページの覆いを隠す。**高さが変わったら知らせる。**"""
    frame = ui(page)
    got = frame.evaluate(HIDE_SELECTOR, selectors)
    if got.get("error"):
        raise RuntimeError(got["error"])
    if got["skipped"]:
        print("[*] 流れの中にある要素は隠しませんでした（隠すと熱の位置がずれます）:")
        for s in got["skipped"]:
            print(f"      {s}")
    if got["before"] != got["after"]:
        print(f"[!] 隠したことでページ高さが {got['before']} → {got['after']} に変わりました。"
              "**熱の位置がずれている可能性があります。** 画像を必ず目で確かめてください。")
    else:
        print(f"[*] 覆いを {got['hidden']} 件隠しました（ページ高さは変わらず）")
    return got


# ------------------------------------------------ 貼り付く要素を DOM から測る
#
# Clarityは下敷きが保存済みのスクリーンショットなので、画像の統計から測るしかない。
# **Ptengineは下敷きが生ページで、同一オリジンで中を読める。** ならば
# 「画面に貼り付いている要素」を直接測れる。推定より実測の方が当然強い。
#
# 画像の統計では実際に外した。**熱はページと一緒に動き、貼り付くヘッダーの上を
# 流れていく。** そのためヘッダーの帯はタイルごとに絵が変わり、
# 「ばらつきが小さい」という手がかりが効かない
# （実測：高さ72pxのヘッダーを 8px と判定し、継ぎ目ごとにヘッダーが並んだ）。
#
# 対象にするのは**画面幅に広がり、上端か下端に接している帯**だけ。
# 隅の丸いボタン（実測：50x50、下端から95px上）は切らない。
# そこまで切ると本文を145px失う。
MEASURE_STICKY = ("""
() => {
""" + PAGE_DOC + """
  const w = host.contentWindow;
  const vh = w.innerHeight || 1, vw = w.innerWidth || 1;
  let top = 0, bottom = 0;
  const items = [];
  for (const e of d.querySelectorAll('*')) {
    const cs = w.getComputedStyle(e);
    if (cs.position !== 'fixed' && cs.position !== 'sticky') continue;
    if (cs.display === 'none' || cs.visibility === 'hidden' || cs.opacity === '0') continue;
    const r = e.getBoundingClientRect();
    if (r.height < 4) continue;
    if (r.width < vw * 0.5) continue;      // 隅のボタンは帯ではない
    if (r.height > vh * 0.5) continue;     // モーダルは貼り付く要素ではない
    const name = e.tagName + (e.id ? '#' + e.id : '');
    if (r.top <= 2 && r.bottom > top) { top = r.bottom; items.push(name + ' 上' + Math.round(r.bottom) + 'px'); }
    else if (r.bottom >= vh - 2 && vh - r.top > bottom) { bottom = vh - r.top; items.push(name + ' 下' + Math.round(vh - r.top) + 'px'); }
  }
  return { top: Math.round(top), bottom: Math.round(bottom), items };
}
""")


def measure_sticky(page) -> dict | None:
    """対象ページの、上端・下端に貼り付く帯の高さ（CSS px）。読めなければ None。"""
    try:
        got = ui(page).evaluate(MEASURE_STICKY)
    except Exception:
        return None
    if not got or got.get("error"):
        return None
    return got


def warn_overlays(page, quiet: bool = False) -> list:
    """大きな覆いが出ていれば知らせる。**勝手には消さない。**

    自動で閉じると、CTAや同意ボタンのような**押してはいけないもの**まで
    押しかねない。何が出ているかを見せて、--hide で指定してもらう。
    """
    got = ui(page).evaluate(DETECT_OVERLAY)
    if got.get("error"):
        return []
    found = got.get("overlays") or []
    if found and not quiet:
        print(f"[!] 対象ページに大きな覆いが {len(found)} 件出ています。"
              "画像に写り込み、下の本文を隠します。")
        for o in found:
            name = o["id"] and f"#{o['id']}" or (o["cls"] and f".{o['cls'].split()[0]}") or o["tag"]
            print(f"      {name}  {o['w']}x{o['h']}  {o['pos']}  「{o['text']}」")
        print("    消す場合は --hide にCSSセレクタを渡してください（例: --hide \".modal,#popup\"）")
    return found


# ---------------------------------------------------------------- 準備完了の判定
# 描画が終わったと判断する手がかりは、**種別で違う**。
#
#   クリック・滞在        熱の canvas。高さがページ全高とほぼ一致する
#   離脱・コンバージョン  **canvas を使わない。** ブロックごとの％ラベルで描く
#
# ここを一緒くたにすると、離脱とコンバージョンが永久に「描画待ち」になる
# （実測：熱 [] のまま待ち続けて失敗した）。
CANVAS_KINDS = ("click", "attention")
LABEL_KINDS = ("exit", "conversion")
MIN_LABELS = 5


def settle(page, timeout_s: float, why: str = "") -> dict:
    """状態を切り替えたあと、描画が落ち着くのを**待つだけ**。落ちない。

    デバイス・種別・期間を切り替える途中では、画面上の組み合わせが
    まだ目的のものではない。その組み合わせにデータが無ければ何も描画されず、
    ここで止めると**次の切り替えにたどり着けない。**

    実例：離脱のままPCへ切り替えると何も出ない（PCに離脱データが無いため）。
    そこで途中の待ちは緩くし、**撮る直前の厳密な判定に任せる。**
    """
    try:
        return wait_ready(page, min(timeout_s, 30.0), why=why)
    except TimeoutError:
        return read_state(page)


def wait_ready(page, timeout_s: float, why: str = "", strict_kind: str = "") -> dict:
    """描画が終わるまで待つ。

    **読み込み中を表すクラスは当てにならない。** 熱レイヤーが描けているのに
    `[class*=loading]` が残っていることを実測で確認した。離脱でも残り続ける。

    `strict_kind` を渡すと、その種別の手がかりだけで判断する。
    渡さない場合は「どちらかが出ていればよい」とする（デバイスや期間を
    切り替えた直後は、画面上の種別がまだ目的のものとは限らないため）。
    """
    deadline = time.time() + timeout_s
    last = {}
    want_canvas = strict_kind in CANVAS_KINDS or not strict_kind
    want_labels = strict_kind in LABEL_KINDS or not strict_kind
    held, times = None, 0
    while time.time() < deadline:
        st = read_state(page)
        last = st
        total = st["scrollHeight"]
        if total > 0:
            if want_canvas and st["heat"]:
                tall = max(h for _w, h in st["heat"])
                if abs(tall - total) <= max(40, total * 0.01):
                    return st       # 一致したなら、それ以上待つ理由はない
                # **一致を完了の条件にしてはいけない。**
                # 熱レイヤーの高さは「Ptengineが測ったときのページ高さ」で、
                # 下敷きが生ページである以上、実行ごとに変わる
                # （実測：同じページ・同じ期間・同じデバイスで 12344 と 14198）。
                # 一致を待つと、描画は終わっているのに待ち続けて時間切れになり、
                # 「データが無い可能性があります」という**見当違いの理由**が出る。
                # 高さが動かなくなったことをもって「描き終わった」とする。
                # 食い違いそのものは撮ったあとに警告し、記録に残す（③）。
                if tall == held:
                    times += 1
                    if times >= 3:
                        return st
                else:
                    held, times = tall, 0
            if want_labels and st.get("pctLabels", 0) >= MIN_LABELS:
                return st
        time.sleep(1.0)
    raise TimeoutError(
        f"ヒートマップの描画が終わりません（{why}）。"
        f"全高 {last.get('scrollHeight')} / 熱 {last.get('heat')}"
        f" / ％ラベル {last.get('pctLabels')}。"
        "そのページ・そのデバイスにデータがない可能性があります。"
        "--timeout を延ばすか、画面を目で確かめてください。")


def verify(page, kind: str, device: str, date_value: str) -> dict:
    """撮る直前に、画面の状態が意図どおりかを確かめる。

    **状態はURLにもファイル名にも残らない。** ここで確かめないと、
    前回の状態のまま撮った画像が、意図した条件の名前で保存される。
    """
    st = read_state(page)
    sel = st["selected"]
    bad = []
    if DEVICES[device] not in sel:
        bad.append(f"デバイス: {DEVICES[device]} のはずが {sel}")
    mark = TYPE_MARKS[kind]
    if not any(mark in s for s in sel):
        bad.append(f"種別: {TYPES[kind]}（表示に「{mark}」を含むはず）のはずが {sel}")

    span = month_span(date_value)
    if span:
        start, end = span
        want = f"{start.month:02d}/{start.day:02d}-{end.month:02d}/{end.day:02d}"
        got = (st["dateLabel"] or "").replace(" ", "")
        if not got:
            # **読めないまま通してはいけない。** 期間を確かめているつもりで
            # 素通りし、前回の期間のまま撮った画像が今月の名前で保存される。
            bad.append("期間: ラベルを読めません（画面の作りが変わった可能性）")
        elif want not in got:
            bad.append(f"期間: {want} のはずが「{got}」")
    if bad:
        raise RuntimeError("画面の状態が指定と違います。撮影を中止します。\n  "
                           + "\n  ".join(bad))
    return st


# ---------------------------------------------------------------- 撮る
def capture(args: argparse.Namespace) -> Path:
    out_dir = Path(args.out)
    tiles_dir = out_dir / "tiles"
    tiles_dir.mkdir(parents=True, exist_ok=True)

    with sync_playwright() as pw:
        ctx = pw.chromium.launch_persistent_context(
            user_data_dir=str(Path(args.profile).expanduser()),
            headless=False,
            channel=args.channel or None,
            viewport={"width": args.window_width, "height": args.window_height},
            locale="ja-JP",
        )
        launcher = ctx.pages[0] if ctx.pages else ctx.new_page()
        print("[*] ヒートマップリストから対象ページを開きます")
        page = open_heatmap(ctx, launcher, args.sid, args.page_url, args.timeout)
        page.wait_for_selector(UI_FRAME, timeout=int(args.timeout * 1000))
        page.wait_for_timeout(int(args.settle * 1000))
        # 初回だけ出る拡張機能の案内。UI全体を押し下げるので先に消す
        dismiss_banner(page)
        url = page.url

        # 状態は残る。毎回きちんと作り直す
        set_device(page, args.device, args.timeout)
        set_type(page, args.type, args.timeout)
        set_date(page, args.date, args.timeout)
        # 撮る直前に、**その種別の手がかりで**描画完了を確かめる。
        # ここまでの待ちは種別が切り替わる途中なので緩くしてある。
        st = wait_ready(page, args.timeout,
                        why=f"種別 {TYPES[args.type]}", strict_kind=args.type)
        st = verify(page, args.type, args.device, args.date)

        # 覆い（サイト側のポップアップ）の扱い。**下敷きが実サイトゆえの問題。**
        hide_info = None
        if args.hide:
            hide_info = hide_overlays(page, args.hide)
            page.wait_for_timeout(1500)
            st = read_state(page)
        overlays = warn_overlays(page)
        overlay_keys = {(o["tag"], o["cls"], o["w"], o["h"]) for o in overlays}

        frame = ui(page)
        total, view = st["scrollHeight"], st["clientHeight"]
        locator = frame.locator(SCROLLER)
        print(f"[*] ページ全高 {total}px / 表示 {view}px / 幅 {st['clientWidth']}px")
        print(f"[*] 期間ラベル「{st['dateLabel']}」／選択 {st['selected']}")

        # 熱レイヤーの高さは、Ptengineが計測したときのページ高さである。
        # 下敷きが生ページなので、いま読み込んだページとは高さが違いうる。
        #
        # **高い側と低い側で意味が違う。** 実機で並べて確かめた。
        #   熱がページより高い … 上端ぞろえで、余りが下に伸びるだけ。
        #                        上・中・下のどこでも位置は合っていた（実測）。
        #   熱がページより低い … **下の方に熱が存在しない。**
        #                        熱が無いのか、描き終わっていないのか区別できない。
        heat_h = max((h for _w, h in st["heat"]), default=0)
        if heat_h and abs(heat_h - total) > max(40, total * 0.02):
            print(f"[*] 熱レイヤー {heat_h}px ／ ページ {total}px（差 {heat_h - total:+d}px）。"
                  "熱は計測時のページ高さで描かれます。")
            if heat_h < total:
                print(f"[!] **ページの下 {total - heat_h}px に熱がありません。**"
                      "熱が無いのか、描き終わっていないのかは区別できません。"
                      "下端を目で確かめてください。")

        tiles: list[tuple[Path, int]] = []
        # 貼り付く要素は、スクロールしてから現れるものがある（戻るボタン等）。
        # タイルごとに測って**いちばん厚かったとき**を採る。
        #
        # **「測れて0件」と「測れなかった」を分ける。** 貼り付く帯が
        # そもそも無いページで両者を混ぜると、実測が成功しているのに
        # 画像の統計へ落ちてしまう（実測：帯の無いLPで、下に10pxの
        # 根拠のない切り落としが入った）。読めたかどうかは ok で持つ。
        measured = {"ok": False, "top": 0, "bottom": 0, "items": []}

        def note_sticky() -> None:
            got = measure_sticky(page)
            if not got:
                return
            measured["ok"] = True
            measured["top"] = max(measured["top"], got["top"])
            measured["bottom"] = max(measured["bottom"], got["bottom"])
            for s in got["items"]:
                if s not in measured["items"]:
                    measured["items"].append(s)

        # 覆いは撮影中に出入りする。見かけたものを溜めて記録に残す
        if total <= view + 50:
            # 1枚なら継ぎ目が無いので切る必要はないが、
            # 何が貼り付いていたかは記録に残す
            note_sticky()
            path = tiles_dir / "tile_000.png"
            locator.screenshot(path=str(path))
            tiles.append((path, 0))
            print("[*] 1画面に収まるため、1枚で撮ります。")
        else:
            overlap = overlap_for(args.overlap, args.sticky_top, args.sticky_bottom)
            step = max(50, view - overlap)
            top, index, seen = 0, 0, set()
            while index < args.max_tiles:
                actual = int(frame.evaluate(SET_SCROLL, [SCROLLER, top]))
                page.wait_for_timeout(int(args.tile_delay * 1000))
                if actual in seen:
                    break
                seen.add(actual)
                # **覆いは時間差で出る。** 開始時に無くても、途中から現れて
                # そこから先の全タイルに写り込む。撮る直前に毎回消す。
                if args.hide:
                    try:
                        frame.evaluate(HIDE_SELECTOR, args.hide)
                    except Exception:
                        pass
                for o in warn_overlays(page, quiet=True):
                    key = (o["tag"], o["cls"], o["w"], o["h"])
                    if key not in overlay_keys:
                        overlay_keys.add(key)
                        overlays.append(o)
                note_sticky()
                path = tiles_dir / f"tile_{index:03d}.png"
                locator.screenshot(path=str(path))
                tiles.append((path, actual))
                print(f"    tile {index:03d}  scrollTop={actual}")
                if actual + view >= total - 1:
                    break
                top, index = actual + step, index + 1
        ctx.close()

    if not tiles:
        raise RuntimeError("キャプチャが取得できませんでした。")

    if measured["ok"]:
        print("[*] 貼り付く要素を画面から実測しました: "
              + (" / ".join(measured["items"]) if measured["items"] else "なし"))

    def resolve(value, side: str) -> int:
        if value != "auto":
            return int(value)
        # **実測できたなら、画像の統計より実測を採る。**
        # 見つからなかった（0px）のも実測の結果である。ここで画像の統計へ
        # 落とすと、帯の無いページに根拠のない切り落としが入る。
        if measured["ok"]:
            got = min(measured[side], AUTO_STICKY_MAX)
            print(f"[*] 貼り付く要素（{side}）は実測 {got}px です")
            return got
        got = min(detect_sticky(tiles, view, side), AUTO_STICKY_MAX)
        print(f"[*] 貼り付く要素（{side}）を画像から {got}px と判定しました")
        return got

    sticky_top = resolve(args.sticky_top, "top")
    sticky_bottom = resolve(args.sticky_bottom, "bottom")
    joined_path = out_dir / f"heatmap_{args.type}_joined.png"
    joined, used, detected = stitch(tiles, total, view, joined_path,
                                    sticky_css=sticky_top,
                                    sticky_bottom_css=sticky_bottom,
                                    trim=parse_trim(args.trim))

    meta = {
        "tool": "Ptengine",
        "pageUrl": args.page_url,
        # 実際に開かれたURL（リストから発行されたトークン付き）。長いので原本のまま
        "openedUrl": url,
        "sid": args.sid,
        "device": args.device,
        "deviceLabel": DEVICES[args.device],
        "heatmapType": args.type,
        "typeLabel": TYPES[args.type],
        "date": args.date,
        # 画面から読み戻した値。**指定ではなく実際の状態を残す。**
        "observedSelection": st["selected"],
        "observedDateLabel": st["dateLabel"],
        # 下敷きは実サイト。撮影時点の全高を残し、前月と比べられるようにする
        "pageHeightCss": total,
        # 熱レイヤーの高さ＝Ptengineが計測したときのページ高さ。
        # pageHeightCss と食い違うなら、熱と要素の位置がずれている
        "heatHeightCss": heat_h or None,
        "viewHeightCss": view,
        "viewWidthCss": st["clientWidth"],
        "stickyTopCss": sticky_top,
        "stickyBottomCss": sticky_bottom,
        # どうやって決めたか。実測できたなら、その中身も残す
        "stickySource": "dom" if measured["ok"] else "image",
        "stickyElements": measured["items"] or None,
        "trimLeftRight": list(used) if used else None,
        "trimDetected": list(detected) if detected else None,
        # 下敷きは実サイト。撮影時に何が覆っていたかを残す
        "hideSelector": args.hide or None,
        "hidden": hide_info.get("hidden") if hide_info else None,
        "overlaysSeen": overlays or None,
        "capturedAt": datetime.now().isoformat(timespec="seconds"),
        "tiles": [{"file": p.name, "scrollTop": t} for p, t in tiles],
        "joined": joined.name,
    }
    (out_dir / "capture_meta.json").write_text(
        json.dumps(meta, ensure_ascii=False, indent=1), encoding="utf-8")
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
        page.goto(APP, wait_until="load", timeout=90_000)
        print("ブラウザでPtengineにサインインしてください。")
        print("済んだら、そのブラウザの窓を閉じてください。")
        print("（このターミナルでのキー入力は要りません）")
        print()
        deadline = time.time() + args.login_timeout
        last = -1
        while time.time() < deadline:
            try:
                if not ctx.pages:
                    break
            except Exception:
                break
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
    p = argparse.ArgumentParser(description="Ptengineヒートマップの分割キャプチャ＆結合")
    p.add_argument("--login", action="store_true", help="初回のサインインだけを行う")
    p.add_argument("--sid", help="ワークスペースID（アプリURLの /app/<ここ>/ ）")
    p.add_argument("--page-url", help="対象ページのURL（クエリも含めてそのまま）")
    p.add_argument("--type", default="click", choices=sorted(TYPES),
                   help="ヒートマップ種別。click / attention / exit / conversion")
    p.add_argument("--device", default="Mobile", choices=sorted(DEVICES),
                   help="Mobile / Desktop / Tablet。PCとSPを混ぜない")
    p.add_argument("--date", default="last-month",
                   help="期間。月次では暦月を渡す（2026-08）。"
                        "範囲は 2026-08-01..2026-08-31。"
                        f"プリセット（{' / '.join(PRESETS)}）は実行日から決まるため月次に向かない")
    p.add_argument("--out", default="output/ptengine_heatmap", help="出力フォルダ")
    p.add_argument("--profile", default=".ptengine_profile",
                   help="認証情報を保存するフォルダ。Gitに追加しない")
    p.add_argument("--sticky-top", default="auto",
                   help="上に貼り付くヘッダーの高さ(CSS px)。auto で自動判定、0で無効")
    p.add_argument("--sticky-bottom", default="auto",
                   help="下に貼り付く固定バーの高さ(CSS px)。auto で自動判定、0で無効")
    p.add_argument("--hide", default="",
                   help="対象ページの覆い（ポップアップ等）を隠すCSSセレクタ。"
                        "カンマ区切り。**流れの中にある要素は隠さない**"
                        "（隠すとページが縮み、熱の位置がずれるため）")
    p.add_argument("--trim", default="auto",
                   help="左右の余白を落とす位置。auto / 「L,R」 / none")
    p.add_argument("--channel", default="", help="インストール済みブラウザ（例: chrome）")
    # **幅を狭めない。** 種別タブのラベルは `hidden lg:block` で、
    # 画面が狭いと文字が消えてアイコンだけになる。表示名で選んでいるため、
    # 狭い窓では「種別が選べません」で止まる。
    p.add_argument("--window-width", type=int, default=1920)
    p.add_argument("--window-height", type=int, default=1600,
                   help="ブラウザの高さ。**表示領域の高さを決め、タイル枚数を左右する。**"
                        "Ptengineの表示領域はツールバーのぶんだけ低く、実測で"
                        "「ウィンドウの高さ − 約220px」だった。1200だと表示633pxで、"
                        "12400pxのページが55枚になる。1600なら約13枚に減る")
    p.add_argument("--overlap", type=int, default=40, help="タイル間の重なり(CSS px)")
    p.add_argument("--settle", type=float, default=10.0, help="初回描画の待機秒")
    p.add_argument("--tile-delay", type=float, default=1.2, help="1タイルごとの待機秒")
    p.add_argument("--timeout", type=float, default=90.0,
                   help="描画完了を待つ上限秒。PC表示は20秒以上かかることがある")
    p.add_argument("--max-tiles", type=int, default=80, help="安全装置")
    p.add_argument("--login-timeout", type=float, default=900.0)
    a = p.parse_args(argv)
    if not a.login:
        missing = [n for n in ("sid", "page_url") if not getattr(a, n)]
        if missing:
            p.error("--" + " と --".join(m.replace("_", "-") for m in missing) + " が必要です")
    return a


def main(argv=None) -> int:
    args = parse_args(argv)
    if args.login:
        login(args)
        return 0
    capture(args)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
