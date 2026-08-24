"""
全画面キャプチャ（分割撮影＋連結方式）
========================================
用途：スクロールに応じて内容が生成される／ページ高が変化するLP等で、
      通常の full_page 撮影だと「下部が空白・黒帯になる」場合の確実な取得方法。

方式：画面（ビューポート）単位で少しずつスクロールしながら撮影し、最後に縦連結して1枚にする。
      各スクロール位置では内容が正しく描画されるため、遅延生成型のページでも欠落しない。
      ※ 追従（position:fixed）要素は1枚目だけ残し、2枚目以降は非表示にして重複を防ぐ。

使い方：
  python web_capture_segments.py --url https://example.com --name PC_LP2_xxx
  python web_capture_segments.py --url https://example.com --name SP_LP2_xxx --sp
出力：カレントディレクトリに <name>.png（連結後の1枚）
"""

import argparse
import os
from playwright.sync_api import sync_playwright
from PIL import Image

Image.MAX_IMAGE_PIXELS = None

PC_W, PC_H, PC_SCALE = 1440, 900, 2
SP_W, SP_H, SP_SCALE = 393, 852, 3
SP_UA = ("Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
         "AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Mobile/15E148 Safari/604.1")

HIDE_FIXED_JS = """
() => {
  let n = 0;
  document.querySelectorAll('body *').forEach(el => {
    const s = getComputedStyle(el);
    if (s.position === 'fixed' || s.position === 'sticky') {
      el.setAttribute('data-cap-hidden', '1');
      el.style.setProperty('visibility', 'hidden', 'important');
      n++;
    }
  });
  return n;
}
"""

EXPAND_JS = """
async () => {
  // 最下部までゆっくりスクロールして遅延生成を出し切る
  const step = Math.round(window.innerHeight * 0.8);
  let guard = 0;
  while (guard++ < 400) {
    const before = document.body.scrollHeight;
    window.scrollBy(0, step);
    await new Promise(r => setTimeout(r, 120));
    const y = window.scrollY, h = document.body.scrollHeight;
    if (y + window.innerHeight >= h - 4 && h === before) break;
  }
  window.scrollTo(0, 0);
  await new Promise(r => setTimeout(r, 500));
  return document.body.scrollHeight;
}
"""


FORCE_VISIBLE_CSS = """
*, *::before, *::after {
  animation-duration: 0s !important; animation-delay: 0s !important;
  transition: none !important; scroll-behavior: auto !important;
}
[data-aos], .aos-init, .aos-animate,
[class*="fade"], [class*="Fade"], [class*="anim"], [class*="Anim"],
[class*="inview"], [class*="InView"], [class*="scroll"], [class*="reveal"],
[class*="show"], [class*="appear"], [class*="slide"] {
  opacity: 1 !important; visibility: visible !important; transform: none !important;
}
"""

FORCE_VISIBLE_JS = """
() => {
  let n = 0;
  document.querySelectorAll('body *').forEach(el => {
    const s = getComputedStyle(el);
    if (s.display === 'none') return;
    if (s.position === 'fixed' || s.position === 'sticky') return;  // 追従要素は触らない
    let t = false;
    if (parseFloat(s.opacity) < 0.99) { el.style.setProperty('opacity','1','important'); t = true; }
    if (s.visibility === 'hidden')    { el.style.setProperty('visibility','visible','important'); t = true; }
    if (s.transform && s.transform !== 'none') { el.style.setProperty('transform','none','important'); t = true; }
    if (t) n++;
  });
  document.querySelectorAll('img').forEach(img => {
    const ds = img.getAttribute('data-src') || img.getAttribute('data-original') || img.getAttribute('data-lazy-src');
    if (ds && !img.src.includes(ds)) img.src = ds;
    const dss = img.getAttribute('data-srcset'); if (dss) img.srcset = dss;
    img.loading = 'eager';
  });
  document.querySelectorAll('[data-aos]').forEach(el => el.classList.add('aos-animate'));
  return n;
}
"""


def capture(url, name, sp=False, wait=3500, seg_wait=550, max_segments=200, force_visible=False):
    vh = SP_H if sp else PC_H
    scale = SP_SCALE if sp else PC_SCALE
    tmpdir = "_segments_" + name
    os.makedirs(tmpdir, exist_ok=True)
    parts = []

    with sync_playwright() as pw:
        b = pw.chromium.launch()
        if sp:
            ctx = b.new_context(viewport={"width": SP_W, "height": SP_H},
                                device_scale_factor=SP_SCALE, user_agent=SP_UA,
                                is_mobile=True, has_touch=True)
        else:
            ctx = b.new_context(viewport={"width": PC_W, "height": PC_H},
                                device_scale_factor=PC_SCALE)
        pg = ctx.new_page()
        print(f"  読み込み: {url}")
        pg.goto(url, wait_until="domcontentloaded", timeout=120000)
        pg.wait_for_timeout(wait)

        print("  遅延生成を出し切る（最下部まで往復）…")
        h = pg.evaluate(EXPAND_JS)
        print(f"    確定ページ高: {h}px（CSS）")
        if force_visible:
            pg.add_style_tag(content=FORCE_VISIBLE_CSS)
            print(f"    強制表示モード：非表示要素 {pg.evaluate(FORCE_VISIBLE_JS)}個を表示に")

        captured_to = 0     # 撮影済みの位置（CSS px）
        y_target = 0
        i = 0
        while i < max_segments:
            pg.evaluate(f"() => window.scrollTo(0, {y_target})")
            pg.wait_for_timeout(seg_wait)
            if force_visible:
                pg.evaluate(FORCE_VISIBLE_JS)
                pg.wait_for_timeout(220)
            actual = pg.evaluate("() => Math.round(window.scrollY)")
            h = pg.evaluate("() => document.body.scrollHeight")
            fp = os.path.join(tmpdir, f"{i:04d}.png")
            pg.screenshot(path=fp, full_page=False)

            # 既に撮った範囲と重なる分を上から切り落として重複を防ぐ
            overlap_css = captured_to - actual
            if overlap_css > 0:
                im = Image.open(fp)
                cut = int(round(overlap_css * scale))
                if cut < im.size[1]:
                    im.crop((0, cut, im.size[0], im.size[1])).save(fp)
                else:
                    os.remove(fp); fp = None
            if fp:
                parts.append(fp)
            captured_to = actual + vh
            i += 1
            if i == 1:
                n = pg.evaluate(HIDE_FIXED_JS)   # 追従要素は1枚目のみ残す
                print(f"    追従(fixed/sticky)要素 {n}個を2枚目以降は非表示に")
            if captured_to >= h - 2:
                break
            y_target = captured_to
        print(f"  分割撮影: {len(parts)}枚（ページ高 {h}px）")
        b.close()

    # 縦連結
    ims = [Image.open(p).convert("RGB") for p in parts]
    W = max(im.size[0] for im in ims)
    H = sum(im.size[1] for im in ims)
    canvas = Image.new("RGB", (W, H), (255, 255, 255))
    y = 0
    for im in ims:
        canvas.paste(im, (0, y)); y += im.size[1]
    out = name if name.endswith(".png") else name + ".png"
    canvas.save(out)
    print(f"  ✅ {out}  {W}x{H}px  {os.path.getsize(out)/1048576:.1f}MB")

    for p in parts:
        try: os.remove(p)
        except Exception: pass
    try: os.rmdir(tmpdir)
    except Exception: pass


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--url", required=True)
    ap.add_argument("--name", required=True)
    ap.add_argument("--sp", action="store_true")
    ap.add_argument("--wait", type=int, default=3500)
    ap.add_argument("--force-visible", action="store_true",
                    help="アニメーションで非表示の要素を強制表示（白紙になる場合に使用）")
    a = ap.parse_args()
    capture(a.url, a.name, a.sp, a.wait, force_visible=a.force_visible)
