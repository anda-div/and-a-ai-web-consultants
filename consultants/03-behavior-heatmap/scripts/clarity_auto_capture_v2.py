"""
Microsoft Clarity ヒートマップ 自動スクロール＆キャプチャツール v2
=================================================================

【v2の改善点】
  - マウスホイールではなくキーボード（↓キー）でスクロール
  - キャプチャ中はマウスをコンテンツ外に退避
  - Clarityのホバーツールチップ干渉を回避

【動作環境】Windows PC + Python 3.8以上
【必要ライブラリ】pip install pyautogui pillow keyboard

【使い方】
  1. Clarityのヒートマップ画面をブラウザで開く
  2. ページ先頭までスクロールしておく
  3. このスクリプトを実行
  4. 画面の指示に従い 4つの位置を指定
  5. Spaceキーで自動キャプチャ開始
  6. ページ末尾で自動停止（または Escキーで手動停止）
"""

import pyautogui
import keyboard
import time
import os
import sys
from datetime import datetime
from PIL import Image, ImageChops
import argparse
import json

# PyAutoGUIの安全設定
pyautogui.FAILSAFE = True  # マウスを左上隅に移動すると緊急停止
pyautogui.PAUSE = 0.05


def get_position(prompt_message: str) -> tuple:
    """ユーザーにマウスで座標を指定してもらう"""
    print(f"\n>>> {prompt_message}")
    print("    → マウスを移動して Enter キーを押してください")
    input()
    pos = pyautogui.position()
    print(f"    ✓ 座標取得: ({pos.x}, {pos.y})")
    return (pos.x, pos.y)


def images_are_similar(img1: Image.Image, img2: Image.Image, threshold: float = 0.99) -> bool:
    """2枚の画像がほぼ同一かどうかを判定（ページ末尾検出用）"""
    if img1.size != img2.size:
        return False
    img1_rgb = img1.convert("RGB")
    img2_rgb = img2.convert("RGB")
    diff = ImageChops.difference(img1_rgb, img2_rgb)
    pixels = list(diff.getdata())
    total = len(pixels)
    matching = sum(1 for r, g, b in pixels if r <= 10 and g <= 10 and b <= 10)
    ratio = matching / total
    return ratio >= threshold


def main():
    parser = argparse.ArgumentParser(
        description="Clarity ヒートマップ 自動スクロール＆キャプチャ v2"
    )
    parser.add_argument(
        "--scroll-presses", type=int, default=10,
        help="1回のスクロールで↓キーを押す回数。デフォルト: 10"
    )
    parser.add_argument(
        "--scroll-delay", type=float, default=1.0,
        help="スクロール後の待機時間（秒）。デフォルト: 1.0"
    )
    parser.add_argument(
        "--output-dir", type=str, default=None,
        help="出力フォルダ名。未指定時は自動生成"
    )
    parser.add_argument(
        "--max-captures", type=int, default=200,
        help="最大キャプチャ枚数（安全装置）。デフォルト: 200"
    )
    parser.add_argument(
        "--similarity-threshold", type=float, default=0.99,
        help="ページ末尾検出の類似度閾値。デフォルト: 0.99"
    )
    parser.add_argument(
        "--duplicate-count", type=int, default=3,
        help="末尾判定に必要な連続類似画像数。デフォルト: 3"
    )
    parser.add_argument(
        "--use-pagedown", action="store_true",
        help="↓キーの代わりにPageDownキーを使う"
    )

    args = parser.parse_args()

    print("=" * 60)
    print("  Clarity ヒートマップ 自動キャプチャ v2")
    print("  （キーボードスクロール＋マウス退避方式）")
    print("=" * 60)
    print()
    print("【準備】")
    print("  ・Clarityのヒートマップ画面をブラウザで表示してください")
    print("  ・ページの先頭（最上部）までスクロールしておいてください")
    print("  ・FAILSAFE: マウスを画面左上隅に移動すると緊急停止します")
    print()

    # ── STEP 1: キャプチャ範囲の指定 ──
    print("─" * 40)
    print("STEP 1: キャプチャ範囲を指定します")
    print("─" * 40)

    top_left = get_position(
        "キャプチャ範囲の【左上】にマウスを移動してください"
    )
    bottom_right = get_position(
        "キャプチャ範囲の【右下】にマウスを移動してください"
    )

    region_x = top_left[0]
    region_y = top_left[1]
    region_w = bottom_right[0] - top_left[0]
    region_h = bottom_right[1] - top_left[1]

    if region_w <= 0 or region_h <= 0:
        print("\n❌ エラー: 右下の座標が左上より右下にある必要があります。")
        sys.exit(1)

    capture_region = (region_x, region_y, region_w, region_h)
    print(f"\n  ✓ キャプチャ範囲: {region_w}x{region_h}px")

    # ── STEP 2: マウス退避位置 ──
    print()
    print("─" * 40)
    print("STEP 2: マウス退避位置を指定します")
    print("─" * 40)

    park_pos = get_position(
        "マウスの【退避位置】を指定してください\n"
        "    （ヒートマップに干渉しない場所＝ヘッダーバーや画面端など）\n"
        "    ※ キャプチャ範囲外がベストです"
    )

    # ── STEP 3: クリック位置（フォーカス用） ──
    print()
    print("─" * 40)
    print("STEP 3: コンテンツエリアのクリック位置を指定します")
    print("─" * 40)

    click_pos = get_position(
        "Clarityの【コンテンツエリア内】にマウスを移動してください\n"
        "    （キーボードスクロールのフォーカスを得るために1回クリックします）\n"
        "    ※ ヒートマップのクリック要素がない余白部分がベストです"
    )

    # ── STEP 4: 設定確認 ──
    scroll_key = "pagedown" if args.use_pagedown else "down"
    scroll_desc = "PageDown" if args.use_pagedown else f"↓キー × {args.scroll_presses}回"

    print()
    print("─" * 40)
    print("STEP 4: 設定確認")
    print("─" * 40)
    print(f"  キャプチャ範囲:  {region_w}x{region_h}px")
    print(f"  マウス退避位置:  ({park_pos[0]}, {park_pos[1]})")
    print(f"  クリック位置:    ({click_pos[0]}, {click_pos[1]})")
    print(f"  スクロール方式:  {scroll_desc}")
    print(f"  描画待ち時間:    {args.scroll_delay} 秒")
    print(f"  最大キャプチャ:  {args.max_captures} 枚")

    # 出力フォルダ
    if args.output_dir:
        output_dir = args.output_dir
    else:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_dir = f"captures_{timestamp}"

    os.makedirs(output_dir, exist_ok=True)
    print(f"  出力フォルダ:    {output_dir}/")

    # 設定をJSONに保存
    config = {
        "region": capture_region,
        "park_position": park_pos,
        "click_position": click_pos,
        "scroll_key": scroll_key,
        "scroll_presses": args.scroll_presses,
        "scroll_delay": args.scroll_delay,
        "timestamp": datetime.now().isoformat(),
    }
    with open(os.path.join(output_dir, "_config.json"), "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)

    # ── STEP 5: 開始待ち ──
    print()
    print("─" * 40)
    print("STEP 5: キャプチャ開始")
    print("─" * 40)
    print()
    print("  📌 Spaceキー → 開始")
    print("  📌 Escキー   → 途中停止")
    print("  📌 マウス左上隅 → 緊急停止")
    print()
    print("  ⏳ Spaceキーを押すと3秒後に開始します...")

    keyboard.wait("space")
    for i in range(3, 0, -1):
        print(f"    {i}...")
        time.sleep(1)

    print("\n  🚀 キャプチャ開始！\n")

    # ── 初期フォーカス取得 ──
    # コンテンツエリアをクリックしてフォーカスを得る
    pyautogui.click(click_pos[0], click_pos[1])
    time.sleep(0.3)
    # マウスを退避
    pyautogui.moveTo(park_pos[0], park_pos[1], duration=0.2)
    time.sleep(0.5)

    # ── メインループ ──
    capture_count = 0
    prev_image = None
    similar_count = 0

    try:
        while capture_count < args.max_captures:
            # Escキーチェック
            if keyboard.is_pressed("escape"):
                print("\n  ⏹ Escキーで停止しました")
                break

            # ① マウスが退避位置にいることを確認
            pyautogui.moveTo(park_pos[0], park_pos[1], duration=0.05)
            time.sleep(0.2)

            # ② キャプチャ
            capture_count += 1
            filename = f"{capture_count:04d}.png"
            filepath = os.path.join(output_dir, filename)

            current_image = pyautogui.screenshot(region=capture_region)
            current_image.save(filepath)
            print(f"    [{capture_count:4d}] {filename}", end="")

            # ③ ページ末尾判定
            if prev_image is not None:
                if images_are_similar(
                    prev_image, current_image,
                    threshold=args.similarity_threshold
                ):
                    similar_count += 1
                    print(f"  ← 類似 ({similar_count}/{args.duplicate_count})", end="")
                    if similar_count >= args.duplicate_count:
                        print(f"\n\n  🏁 ページ末尾を検出")
                        # 重複画像を削除
                        for i in range(similar_count):
                            dup_num = capture_count - i
                            dup_path = os.path.join(output_dir, f"{dup_num:04d}.png")
                            if os.path.exists(dup_path):
                                os.remove(dup_path)
                        capture_count -= similar_count
                        break
                else:
                    similar_count = 0

            print()
            prev_image = current_image

            # ④ キーボードでスクロール
            if args.use_pagedown:
                pyautogui.press("pagedown")
            else:
                for _ in range(args.scroll_presses):
                    pyautogui.press("down")
                    time.sleep(0.02)

            # ⑤ 描画待ち
            time.sleep(args.scroll_delay)

    except pyautogui.FailSafeException:
        print("\n\n  🛑 FAILSAFE発動。停止しました。")
    except KeyboardInterrupt:
        print("\n\n  ⏹ Ctrl+C で停止しました")

    # ── 結果サマリー ──
    print()
    print("=" * 60)
    print("  完了！")
    print("=" * 60)
    print(f"  保存枚数:   {capture_count} 枚")
    print(f"  出力先:     {os.path.abspath(output_dir)}/")
    print()
    print("  → 連結ツールに渡してください")
    print()


if __name__ == "__main__":
    main()
