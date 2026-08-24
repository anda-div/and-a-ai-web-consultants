"""
高画質 ウェブページキャプチャーツール
========================================
依存関係: playwright, Pillow(任意)
用途: レポートに掲載するウェブページの全画面キャプチャーを高画質で取得

使い方:
  python web_capture.py urls.txt
  python web_capture.py --url https://example.com
  python web_capture.py  (対話モード)

出力: ./web_captures/ に PC版・SP版の全画面キャプチャーを保存
"""

import os
import sys
import time
import re
from urllib.parse import urlparse
from playwright.sync_api import sync_playwright

# ========== 設定 ==========
OUTPUT_DIR = "./web_captures"

# PC設定
PC_VIEWPORT_WIDTH = 1440
PC_VIEWPORT_HEIGHT = 900
PC_DEVICE_SCALE_FACTOR = 2  # Retina相当 → 実質 2880px幅

# SP設定
SP_VIEWPORT_WIDTH = 393
SP_VIEWPORT_HEIGHT = 852
SP_DEVICE_SCALE_FACTOR = 3  # iPhone相当 → 実質 1179px幅
SP_USER_AGENT = (
    "Mozilla/5.0 (iPhone; CPU iPhone OS 17_0 like Mac OS X) "
    "AppleWebKit/605.1.15 (KHTML, like Gecko) "
    "Version/17.0 Mobile/15E148 Safari/604.1"
)

# ページ読み込み待機（秒）
WAIT_AFTER_LOAD = 8
# スクロール後の待機（lazy load対策）
WAIT_AFTER_SCROLL = 2


def url_to_filename(url, prefix=""):
    """URLからファイル名を生成"""
    parsed = urlparse(url)
    name = parsed.netloc + parsed.path
    name = re.sub(r'[^a-zA-Z0-9._-]', '_', name)
    name = re.sub(r'_+', '_', name).strip('_')
    if name.endswith('_'):
        name = name[:-1]
    if prefix:
        name = f"{prefix}_{name}"
    return name + ".png"


def dismiss_overlays(page):
    """
    Cookie同意バナー・GDPRポップアップ・ニュースレター誘導などのオーバーレイを
    可能な限り自動で閉じる。

    戦略:
      1. よくある「同意/閉じる」ボタンをテキスト/role/共通selectorで探してクリック
      2. クリックしてもなお残るバナー系を CSS で強制非表示
    """
    # ── 戦略1: テキストマッチでボタンクリック ──
    button_texts = [
        # 日本語
        "同意する", "すべて同意", "すべて受け入れる", "同意して進む",
        "同意", "受け入れる", "了承する", "OKして閉じる", "閉じる",
        # 英語
        "Accept All", "Accept all", "Accept", "I Accept",
        "Agree", "I Agree", "OK", "Got it", "Allow All",
        "Allow", "Continue", "Yes, I agree",
    ]
    for txt in button_texts:
        try:
            # role=button で text 完全一致
            loc = page.get_by_role("button", name=txt, exact=True)
            if loc.count() > 0:
                loc.first.click(timeout=1500)
                page.wait_for_timeout(400)
                break
        except Exception:
            pass
        try:
            # text=で部分一致
            loc = page.locator(f'text="{txt}"').first
            if loc.is_visible(timeout=500):
                loc.click(timeout=1500)
                page.wait_for_timeout(400)
                break
        except Exception:
            pass

    # ── 戦略2: 既知のCookie/同意バナー系selectorをCSSで非表示 ──
    page.evaluate("""
        () => {
            const selectors = [
                '#onetrust-banner-sdk', '#onetrust-consent-sdk',
                '.onetrust-banner-sdk', '.ot-sdk-container',
                '#cookiebanner', '.cookiebanner', '#cookie-banner',
                '#cookie-notice', '.cookie-notice', '#CookieNotice',
                '[id*="cookie-consent"]', '[class*="cookie-consent"]',
                '[id*="CookieConsent"]', '[class*="CookieConsent"]',
                '#gdpr-banner', '.gdpr-banner', '[id*="gdpr"]', '[class*="gdpr"]',
                '#truste-consent-track', '#consent_blackbar',
                '.qc-cmp-ui-container', '.fc-consent-root',
                '#CybotCookiebotDialog', '.CybotCookiebotDialog',
                '[aria-label*="cookie"]', '[aria-label*="Cookie"]',
                '[aria-label*="consent"]', '[aria-label*="Consent"]',
                '[role="dialog"][aria-modal="true"]',
            ];
            selectors.forEach(s => {
                document.querySelectorAll(s).forEach(el => {
                    el.style.setProperty('display', 'none', 'important');
                    el.style.setProperty('visibility', 'hidden', 'important');
                    el.style.setProperty('opacity', '0', 'important');
                    el.style.setProperty('pointer-events', 'none', 'important');
                });
            });
            // bodyのscroll lockを解除
            document.body.style.overflow = 'auto';
            document.documentElement.style.overflow = 'auto';
        }
    """)


def scroll_full_page(page):
    """ページ全体をスクロールしてlazy loadコンテンツを読み込む"""
    page.evaluate("""
        async () => {
            const delay = ms => new Promise(resolve => setTimeout(resolve, ms));
            const height = document.body.scrollHeight;
            const step = window.innerHeight;
            for (let y = 0; y < height; y += step) {
                window.scrollTo(0, y);
                await delay(300);
            }
            window.scrollTo(0, document.body.scrollHeight);
            await delay(500);
            window.scrollTo(0, 0);
            await delay(500);
        }
    """)


def capture_url(url, output_dir, prefix="", browser_pc=None, browser_sp=None, p=None):
    """1つのURLをPC・SP両方でキャプチャー"""
    results = []

    # === PC版 ===
    print(f"  📸 PC版キャプチャー中...")
    try:
        if browser_pc is None:
            browser_pc = p.chromium.launch(headless=True)
        context = browser_pc.new_context(
            viewport={"width": PC_VIEWPORT_WIDTH, "height": PC_VIEWPORT_HEIGHT},
            device_scale_factor=PC_DEVICE_SCALE_FACTOR,
            locale="ja-JP",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(WAIT_AFTER_LOAD)
        dismiss_overlays(page)
        time.sleep(0.5)
        scroll_full_page(page)
        dismiss_overlays(page)  # スクロール中に再表示されるサイト対策で2度目
        time.sleep(WAIT_AFTER_SCROLL)

        filename = url_to_filename(url, f"{prefix}_PC" if prefix else "PC")
        filepath = os.path.join(output_dir, filename)
        page.screenshot(path=filepath, full_page=True, type="png", timeout=120000)
        file_size = os.path.getsize(filepath)

        try:
            from PIL import Image
            img = Image.open(filepath)
            print(f"     ✅ {filepath}")
            print(f"     📐 {img.size[0]}x{img.size[1]}px ({file_size:,} bytes)")
        except ImportError:
            print(f"     ✅ {filepath} ({file_size:,} bytes)")
        results.append(filepath)
        context.close()
    except Exception as e:
        print(f"     ❌ PC版エラー: {e}")

    # === SP版 ===
    print(f"  📱 SP版キャプチャー中...")
    try:
        if browser_sp is None:
            browser_sp = p.chromium.launch(headless=True)
        context = browser_sp.new_context(
            viewport={"width": SP_VIEWPORT_WIDTH, "height": SP_VIEWPORT_HEIGHT},
            device_scale_factor=SP_DEVICE_SCALE_FACTOR,
            user_agent=SP_USER_AGENT,
            is_mobile=True,
            locale="ja-JP",
        )
        page = context.new_page()
        page.goto(url, wait_until="domcontentloaded", timeout=30000)
        time.sleep(WAIT_AFTER_LOAD)
        dismiss_overlays(page)
        time.sleep(0.5)
        scroll_full_page(page)
        dismiss_overlays(page)  # スクロール中に再表示されるサイト対策で2度目
        time.sleep(WAIT_AFTER_SCROLL)

        filename = url_to_filename(url, f"{prefix}_SP" if prefix else "SP")
        filepath = os.path.join(output_dir, filename)
        page.screenshot(path=filepath, full_page=True, type="png", timeout=120000)
        file_size = os.path.getsize(filepath)

        try:
            from PIL import Image
            img = Image.open(filepath)
            print(f"     ✅ {filepath}")
            print(f"     📐 {img.size[0]}x{img.size[1]}px ({file_size:,} bytes)")
        except ImportError:
            print(f"     ✅ {filepath} ({file_size:,} bytes)")
        results.append(filepath)
        context.close()
    except Exception as e:
        print(f"     ❌ SP版エラー: {e}")

    return results


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    print("=" * 60)
    print("高画質 ウェブページキャプチャーツール")
    print("=" * 60)
    print(f"PC: {PC_VIEWPORT_WIDTH}x{PC_VIEWPORT_HEIGHT} × {PC_DEVICE_SCALE_FACTOR}倍")
    print(f"    = 実質 {PC_VIEWPORT_WIDTH * PC_DEVICE_SCALE_FACTOR}px幅")
    print(f"SP: {SP_VIEWPORT_WIDTH}x{SP_VIEWPORT_HEIGHT} × {SP_DEVICE_SCALE_FACTOR}倍")
    print(f"    = 実質 {SP_VIEWPORT_WIDTH * SP_DEVICE_SCALE_FACTOR}px幅")
    print(f"保存先: {os.path.abspath(OUTPUT_DIR)}")
    print("=" * 60)
    print()

    urls = []

    if len(sys.argv) > 1:
        if sys.argv[1] == "--url":
            urls = [("", sys.argv[2])]
        elif os.path.isfile(sys.argv[1]):
            with open(sys.argv[1], 'r', encoding='utf-8') as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith('#'):
                        continue
                    if ',' in line:
                        parts = line.split(',', 1)
                        urls.append((parts[0].strip(), parts[1].strip()))
                    else:
                        urls.append(("", line))
            print(f"ファイルから {len(urls)} URL を読み込みました")
        else:
            urls = [("", sys.argv[1])]

    if not urls:
        print("URLを入力してください（空行で開始、'q'で終了）:")
        while True:
            url = input("  URL: ").strip()
            if url.lower() == 'q':
                break
            if url == "":
                if urls:
                    break
                continue
            prefix = input("  連番（任意、例: 02）: ").strip()
            urls.append((prefix, url))

    if not urls:
        print("URLが指定されていません。終了します。")
        return

    with sync_playwright() as p:
        browser_pc = p.chromium.launch(headless=True)
        browser_sp = p.chromium.launch(headless=True)

        for i, item in enumerate(urls):
            if isinstance(item, tuple):
                prefix, url = item
            else:
                prefix, url = "", item

            print(f"\n[{i+1}/{len(urls)}] {url}")
            capture_url(url, OUTPUT_DIR, prefix=prefix,
                       browser_pc=browser_pc, browser_sp=browser_sp, p=p)

        browser_pc.close()
        browser_sp.close()

    print()
    print("=" * 60)
    print(f"全キャプチャー完了。保存先: {os.path.abspath(OUTPUT_DIR)}")
    print("=" * 60)


if __name__ == "__main__":
    main()
