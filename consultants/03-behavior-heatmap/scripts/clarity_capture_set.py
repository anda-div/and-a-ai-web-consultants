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
    p.add_argument("--date", default="Last 30 days", help="期間。UIの選択肢と同じ文字列")
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
        d1 = work / f"{a.name}_{short}_click"
        t0 = time.time()
        print(f"■ {device} クリックマップ")
        run(common + ["--type", "tap", "--device", device, "--out", str(d1)])
        m1 = read_meta(d1)
        top, bottom = m1["stickyTopCss"], m1["stickyBottomCss"]

        # 2) スクロールマップ。1) で測った値をそのまま使う。
        #    スクロールマップは全面が色で覆われ、自動判定が効かないため。
        d2 = work / f"{a.name}_{short}_scroll"
        s_top = a.scroll_sticky_top if a.scroll_sticky_top is not None else top
        note = "引き継ぎ" if s_top == top else "指定値"
        print(f"■ {device} スクロールマップ（貼り付き 上{s_top}/下{bottom} {note}）")
        run(common + ["--type", "scroll", "--device", device, "--out", str(d2),
                      "--sticky-top", str(s_top), "--sticky-bottom", str(bottom)])
        m2 = read_meta(d2)

        for kind, d, m in (("tap", d1, m1), ("scroll", d2, m2)):
            src = d / m["joined"]
            dst = out / f"{a.name}_{short}_{KIND[kind]}.png"
            shutil.copy2(src, dst)
            log.append({
                "file": dst.name,
                "device": device,
                "kind": KIND[kind],
                "pageUrl": a.page_url,
                "urlMatch": m["urlMatch"],
                "date": a.date,
                "stickyTopCss": m["stickyTopCss"],
                "stickyBottomCss": m["stickyBottomCss"],
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
