# -*- coding: utf-8 -*-
r"""1ページ分のヒートマップを、レポートに必要な4枚まとめて撮る

月次レポートに要るのは、1ページにつき次の4枚である。

    PC  クリック / PC  スクロール
    SP  クリック / SP  スクロール

これを1コマンドで撮り、決まった名前で1か所に集める。

    python _scripts\clarity\clarity_capture_set.py ^
        --project <プロジェクトID> ^
        --page-url https://example.com/ ^
        --name top

**なぜまとめて撮るのか**

画面に貼り付くヘッダーの高さは、クリックマップでは自動で測れるが、
スクロールマップでは測れない。スクロールマップは全面が色で覆われ、
どの位置も同じように見えるためである。

そこで、**同じページのクリックマップで測った値を、スクロールマップに引き継ぐ**。
別々に実行すると、スクロールマップだけ継ぎ目にヘッダーが並ぶ。

なお、スクロールマップではヘッダーが厚く描かれることがある。
引き継いだ値でまだ継ぎ目に帯が出る場合は、--scroll-sticky-top で増やす
（ある案件では、クリック69px に対して 180px で消えた）。

出力

    <out>/<name>_pc_click.png
    <out>/<name>_pc_scroll.png
    <out>/<name>_sp_click.png
    <out>/<name>_sp_scroll.png
    <out>/<name>_capture_log.json     どの条件で撮ったかの記録
"""
from __future__ import annotations

import argparse
import io
import json
import shutil
import subprocess
import sys
import time
from pathlib import Path

HERE = Path(__file__).resolve().parent
CAPTURE = HERE / "clarity_heatmap_capture.py"

# 出力名に使う短い呼び方
SHORT = {"Desktop": "pc", "Mobile": "sp", "Tablet": "tab"}
KIND = {"tap": "click", "scroll": "scroll"}


def run(args: list[str]) -> None:
    r = subprocess.run([sys.executable, str(CAPTURE)] + args)
    if r.returncode != 0:
        raise SystemExit(f"キャプチャに失敗しました: {' '.join(args)}")


def read_meta(out_dir: Path) -> dict:
    with io.open(out_dir / "capture_meta.json", encoding="utf-8") as f:
        return json.load(f)


def widest(*bounds):
    """いくつかの「左右」のうち、いちばん広い範囲を返す。

    どれも None なら None（＝切らない）。片方だけあるならそれを使う。
    """
    got = [b for b in bounds if b]
    if not got:
        return None
    return min(b[0] for b in got), max(b[1] for b in got)


def fmt(b) -> str:
    return f"{b[0]}〜{b[1]}" if b else "判定なし"


def crop_to(src: Path, dst: Path, bounds) -> None:
    """左右を切って保存する。bounds が None なら、そのまま複製する。"""
    if not bounds:
        shutil.copy2(src, dst)
        return
    from PIL import Image
    im = Image.open(src)
    left = max(0, min(bounds[0], im.width - 1))
    right = max(left + 1, min(bounds[1], im.width))
    im.crop((left, 0, right, im.height)).save(dst)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    p = argparse.ArgumentParser(
        description="1ページ分のヒートマップ4枚をまとめて撮る")
    p.add_argument("--project", required=True, help="ClarityのプロジェクトID")
    p.add_argument("--page-url", required=True, help="対象ページのURL")
    p.add_argument("--name", required=True, help="出力名の頭（top、lp1 など）")
    p.add_argument("--url-match", help="集計対象の照合値。省略時は --page-url")
    p.add_argument("--op", default="exact",
                   choices=["contains", "endswith", "exact", "exclude"])
    p.add_argument(
        "--date", default="Last 30 days",
        help="期間。月次レポートでは暦月を渡す（2026-08）。"
             "任意の範囲は 2026-08-01..2026-08-31。"
             "UIの選択肢の文字列（Last 30 days など）もそのまま使えるが、"
             "実行日から遡るため月次には向かない")
    p.add_argument("--devices", default="Desktop,Mobile",
                   help="撮るデバイス。カンマ区切り")
    p.add_argument("--out", default="_input/clarity_captures/stitched",
                   help="仕上がりの置き場所")
    p.add_argument("--work", default="_output/clarity_work",
                   help="途中の分割画像の置き場所")
    p.add_argument("--scroll-sticky-top", type=int, default=None,
                   help="スクロールマップだけヘッダーを厚く切る（CSS px）。"
                        "省略時はクリックマップで測った値をそのまま使う")
    p.add_argument("--settle", type=float, default=None,
                   help="初回描画の待機秒。縦に長いページでは増やす")
    p.add_argument("--timeout", type=float, default=None,
                   help="表示領域が現れるまで待つ上限秒")
    p.add_argument("--tile-delay", type=float, default=None,
                   help="1タイルごとの待機秒")
    p.add_argument("--profile", default=".clarity_profile")
    a = p.parse_args()

    out = Path(a.out)
    out.mkdir(parents=True, exist_ok=True)
    work = Path(a.work)
    log: list[dict] = []

    common = ["--project", a.project, "--page-url", a.page_url,
              "--op", a.op, "--date", a.date, "--profile", a.profile]
    if a.url_match:
        common += ["--url-match", a.url_match]
    # 縦に長いページは描画に時間がかかる。既定のままだと
    # 「表示領域が見つかりません」で止まる（実測：37,000px のページで発生）。
    for flag, val in (("--settle", a.settle), ("--timeout", a.timeout),
                      ("--tile-delay", a.tile_delay)):
        if val is not None:
            common += [flag, str(val)]

    for device in [d.strip() for d in a.devices.split(",") if d.strip()]:
        short = SHORT.get(device, device.lower())

        # 1) クリックマップ。貼り付く要素の高さはここで自動判定させる。
        #    左右の余白は落とさずに撮る。2枚そろってから 3) でまとめて切る。
        d1 = work / f"{a.name}_{short}_click"
        t0 = time.time()
        print(f"■ {device} クリックマップ")
        run(common + ["--type", "tap", "--device", device, "--out", str(d1),
                      "--trim", "none"])
        m1 = read_meta(d1)
        top, bottom = m1["stickyTopCss"], m1["stickyBottomCss"]

        # 2) スクロールマップ。1) で測った値をそのまま使う。
        #    スクロールマップは全面が色で覆われ、自動判定が効かないため。
        d2 = work / f"{a.name}_{short}_scroll"
        s_top = a.scroll_sticky_top if a.scroll_sticky_top is not None else top
        note = "引き継ぎ" if s_top == top else "指定値"
        print(f"■ {device} スクロールマップ（貼り付き 上{s_top}/下{bottom} {note}）")
        run(common + ["--type", "scroll", "--device", device, "--out", str(d2),
                      "--sticky-top", str(s_top), "--sticky-bottom", str(bottom),
                      "--trim", "none"])
        m2 = read_meta(d2)

        # 3) 左右の余白を落とすのは、2枚とも撮り終えた**ここ**で行う。
        #
        #    それぞれに任せると、同じページ・同じデバイスなのに幅の違う画像が
        #    できる（実測：MyPage PC で クリック 567px / スクロール 1492px）。
        #    幅が違うと、並べたときや同じ枠に収めたときに縮尺がずれ、
        #    所見が指している位置も合わなくなる。
        #
        #    **クリックマップの判定は狭く出る。** 点が疎なため「中身がない列」と
        #    見なされる列が多い。実測では常にクリック側が狭かった。
        #
        #      MyPage PC   クリック 567 / スクロール 1492（正しいのは1492）
        #      MyPage SP   クリック 374 / スクロール  410（正しいのは 410）
        #      Driving SP  クリック 326 / スクロール  352（正しいのは 352）
        #
        #    そこで**両方の判定を持ち寄り、広い側で揃える。**
        #    どちらかが中身と見なした列は切り落とさない、という決め方である。
        #    狭い側に合わせると、上のように入力欄が切れた画像になる。
        bounds = widest(m1.get("trimDetected"), m2.get("trimDetected"))
        if bounds:
            print(f"   左右 {bounds[0]}〜{bounds[1]} で2枚とも切ります"
                  f"（クリック {fmt(m1.get('trimDetected'))} / "
                  f"スクロール {fmt(m2.get('trimDetected'))}）")

        for kind, d, m in (("tap", d1, m1), ("scroll", d2, m2)):
            src = d / m["joined"]
            dst = out / f"{a.name}_{short}_{KIND[kind]}.png"
            crop_to(src, dst, bounds)
            log.append({
                "file": dst.name,
                "device": device,
                "kind": KIND[kind],
                "pageUrl": a.page_url,
                "urlMatch": m["urlMatch"],
                "date": a.date,
                "stickyTopCss": m["stickyTopCss"],
                "stickyBottomCss": m["stickyBottomCss"],
                "trimLeftRight": list(bounds) if bounds else None,
                "trimDetected": m.get("trimDetected"),
                "tiles": len(m["tiles"]),
            })
            print(f"   → {dst}")
        print(f"   {device} 所要 {int(time.time() - t0)} 秒")

    (out / f"{a.name}_capture_log.json").write_text(
        json.dumps(log, ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"[+] {len(log)} 枚を {out} に置きました")
    print(f"[+] 撮影条件の記録: {out / (a.name + '_capture_log.json')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
