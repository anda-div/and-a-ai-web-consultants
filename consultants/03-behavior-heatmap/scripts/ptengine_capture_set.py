# -*- coding: utf-8 -*-
r"""1ページ分のPtengineヒートマップを、種別×デバイスでまとめて撮る

    python scripts/ptengine_capture_set.py ^
        --sid <ワークスペースID> ^
        --page-url https://example.com/lp/a.html ^
        --name lp_a --date 2026-08

**なぜまとめて撮るのか**

理由は2つあり、どちらも別々に撮ると壊れる。

1. **貼り付く要素の高さは、クリック以外では測れない。**
   滞在（アテンション）と離脱は画面が面で塗られ、どの位置も同じように見えるため、
   タイル間のばらつきでも1枚目との一致でも判定できない。
   **クリックで測った値を他の種別へ引き継ぐ。**

2. **左右の余白の判定が、種別ごとに食い違う。**
   点が疎に散るクリックは「中身がない列」と見なす列が多く、狭く出る。
   面で塗られる種別は広く出る。別々に切ると、同じページ・同じデバイスなのに
   幅の違う画像ができ、並べたときに縮尺がずれる。
   **全種別の判定を持ち寄り、広い側でまとめて切る。**

**データが無い種別があっても止まらない。** コンバージョンは、そのページに
コンバージョンが設定されていなければ何も描かれない。1種別の失敗で
他の7枚を失わないよう、記録に残して次へ進む。

出力

    <out>/<name>_pc_click.png … <name>_sp_conversion.png
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
CAPTURE = HERE / "ptengine_heatmap_capture.py"
sys.path.insert(0, str(HERE))
from heatmap_image import widest  # noqa: E402

SHORT = {"Desktop": "pc", "Mobile": "sp", "Tablet": "tab"}
# クリックを先頭に置く。**貼り付く要素の高さをここで測り、後続へ引き継ぐ。**
ORDER = ["click", "attention", "exit", "conversion"]


def read_meta(out_dir: Path):
    p = out_dir / "capture_meta.json"
    if not p.exists():
        return None
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def fmt(b) -> str:
    return f"{b[0]}〜{b[1]}" if b else "判定なし"


def crop_to(src: Path, dst: Path, bounds) -> None:
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
    p = argparse.ArgumentParser(description="1ページ分のPtengineヒートマップをまとめて撮る")
    p.add_argument("--sid", required=True, help="ワークスペースID")
    p.add_argument("--page-url", required=True, help="対象ページのURL")
    p.add_argument("--name", required=True, help="出力名の頭（top、lp_a など）")
    p.add_argument("--date", default="last-month",
                   help="期間。月次では暦月を渡す（2026-08）")
    p.add_argument("--devices", default="Desktop,Mobile", help="カンマ区切り")
    p.add_argument("--types", default=",".join(ORDER),
                   help="撮る種別。カンマ区切り。click / attention / exit / conversion")
    p.add_argument("--out", default="output/ptengine_captures")
    p.add_argument("--work", default="output/ptengine_work")
    p.add_argument("--profile", default=".ptengine_profile")
    p.add_argument("--hide", default="",
                   help="対象ページの覆い（ポップアップ等）を隠すCSSセレクタ。"
                        "**サイトごとに違う。** 初回は指定せずに実行し、"
                        "報告された覆いを見てから決める")
    p.add_argument("--settle", type=float, default=None)
    p.add_argument("--timeout", type=float, default=None)
    p.add_argument("--tile-delay", type=float, default=None)
    p.add_argument("--window-height", type=int, default=None,
                   help="ブラウザの高さ。**表示領域の高さを決め、タイル枚数を左右する**")
    a = p.parse_args()

    out, work = Path(a.out), Path(a.work)
    out.mkdir(parents=True, exist_ok=True)
    log: list[dict] = []
    skipped: list[str] = []

    common = ["--sid", a.sid, "--page-url", a.page_url,
              "--date", a.date, "--profile", a.profile]
    if a.hide:
        common += ["--hide", a.hide]
    for flag, val in (("--settle", a.settle), ("--timeout", a.timeout),
                      ("--tile-delay", a.tile_delay),
                      ("--window-height", a.window_height)):
        if val is not None:
            common += [flag, str(val)]

    kinds = [k.strip() for k in a.types.split(",") if k.strip()]
    kinds.sort(key=lambda k: ORDER.index(k) if k in ORDER else 99)

    for device in [d.strip() for d in a.devices.split(",") if d.strip()]:
        short = SHORT.get(device, device.lower())
        t0 = time.time()
        metas: dict[str, dict] = {}
        sticky = None            # クリックで測った (上, 下)

        for kind in kinds:
            d = work / f"{a.name}_{short}_{kind}"
            args = common + ["--type", kind, "--device", device,
                             "--out", str(d), "--trim", "none"]
            if sticky is not None:
                # Ptengineは種別に関係なくDOMから測れるが、**8枚が同じ高さで
                # 切られていることを記録の上で保証する**ため、最初に測った値を渡す。
                # （Clarityは技術的にも引き継ぎが必須。事情が違う）
                args += ["--sticky-top", str(sticky[0]),
                         "--sticky-bottom", str(sticky[1])]
                note = f"（貼り付き 上{sticky[0]}/下{sticky[1]} 引き継ぎ）"
            else:
                note = "（貼り付きはここで判定）"
            print(f"■ {device} {kind} {note}")

            r = subprocess.run([sys.executable, str(CAPTURE)] + args)
            m = read_meta(d) if r.returncode == 0 else None
            if m is None:
                # データが無い種別・描画が終わらない種別で起きる。
                # **止めない。** 撮れなかったことを記録して次へ進む。
                print(f"   × {device} {kind} は撮れませんでした。記録して次へ進みます。")
                skipped.append(f"{device}/{kind}")
                continue
            metas[kind] = m
            if sticky is None:
                sticky = (m["stickyTopCss"], m["stickyBottomCss"])

        if not metas:
            print(f"   {device} は1枚も撮れませんでした。")
            continue

        # 左右の余白は、**全種別そろってからまとめて切る。**
        # 狭い側に合わせると、入力欄が端で切れた画像になる（Clarityで実際に起きた）。
        bounds = widest(*[m.get("trimDetected") for m in metas.values()])
        if bounds:
            detail = " / ".join(f"{k} {fmt(m.get('trimDetected'))}"
                                for k, m in metas.items())
            print(f"   左右 {bounds[0]}〜{bounds[1]} で {len(metas)} 枚とも切ります（{detail}）")

        for kind, m in metas.items():
            src = work / f"{a.name}_{short}_{kind}" / m["joined"]
            dst = out / f"{a.name}_{short}_{kind}.png"
            crop_to(src, dst, bounds)
            log.append({
                "file": dst.name, "device": device, "kind": kind,
                "pageUrl": a.page_url, "date": a.date,
                # 指定ではなく、画面から読み戻した値を残す
                "observedSelection": m.get("observedSelection"),
                "observedDateLabel": m.get("observedDateLabel"),
                "pageHeightCss": m.get("pageHeightCss"),
                "viewHeightCss": m.get("viewHeightCss"),
                "stickyTopCss": m["stickyTopCss"],
                "stickyBottomCss": m["stickyBottomCss"],
                "trimLeftRight": list(bounds) if bounds else None,
                "trimDetected": m.get("trimDetected"),
                "tiles": len(m["tiles"]),
                "capturedAt": m.get("capturedAt"),
            })
            print(f"   → {dst}")
        print(f"   {device} 所要 {int(time.time() - t0)} 秒")

    (out / f"{a.name}_capture_log.json").write_text(
        json.dumps({"captured": log, "skipped": skipped},
                   ensure_ascii=False, indent=1), encoding="utf-8")
    print()
    print(f"[+] {len(log)} 枚を {out} に置きました")
    if skipped:
        print(f"[!] 撮れなかった組み合わせ: {'、'.join(skipped)}")
        print("    そのページにその種別のデータがあるか、画面で確かめてください。")
    print(f"[+] 撮影条件の記録: {out / (a.name + '_capture_log.json')}")

    # 下敷きは実サイト。前月と全高が大きく違えば、ページが変わっている
    heights = {(e["device"], e["pageHeightCss"]) for e in log if e.get("pageHeightCss")}
    if heights:
        print()
        print("[*] 撮影時点のページ全高: "
              + "、".join(f"{d} {h}px" for d, h in sorted(heights)))
        print("    **前月と大きく違う場合は、ページ自体が変わっています。**")
        print("    過去の熱が現在のページに乗るため、所見の位置がずれます。")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
