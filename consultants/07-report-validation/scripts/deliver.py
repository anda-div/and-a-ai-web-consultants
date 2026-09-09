# -*- coding: utf-8 -*-
"""納品ゲート ── 検査を通ったファイルにだけ「納品)」の名前を付ける

    python deliver.py <作業中.pptx> --out <納品フォルダ> [--period 2026-08] [--prev <前月の納品.pptx>]

なぜ要るのか
    値の検査（check_values.py）と体裁の検査（check_layout.py）はある。
    だが**実行するかどうかは人の意志に任されていた。** 締め切りに追われている人は飛ばす。
    飛ばしたものが納品され、翌朝クライアントが最初に気づく。実際に何度も起きた。

    そこで、納品ファイルへの改名を**このスクリプト経由に限定する。**
    内部で検査を走らせ、要対応が1件でもあれば改名しない。
    人がどんな状態でも、機械は同じ基準で判定する。

このスクリプトがすること
    1. 紛れ込んだごみファイルがないか（check_stray_files.py）
    2. 値がありえない状態になっていないか（check_values.py）
    3. 体裁が崩れていないか（check_layout.py）
       --prev を渡すと、**前月の納品ファイルを正とする。** 前月に同じ形で
       在った指摘は要対応にせず「前月と同じ」として記録に残す。前月より
       乱れたもの（重なりが大きくなった・件数が増えた・前月に無かった）だけを拾う。
       ただし**文字のはみ出しは前月を見ない。** 溢れた文字が意図であることはない。
    4. 文字が枠に収まっているか、PowerPoint 本人に測らせる（measure_text.ps1）
       3 の見積もりと違い、これは実測である。PowerPoint が無い環境では
       **飛ばしたことを記録に残す。**「測っていない」を「問題なし」にしない。
    5. すべて要対応0なら、納品フォルダへ「納品)<名前>_<日時>.pptx」で複製する
    6. 何を検査して通ったかを、同名の .check.txt に残す（納品後に問われたときの証拠）

このスクリプトがしないこと
    ・時間帯や作成からの経過時間で拒否しない。締め切りは人の事情であり、
      機械が口を出すことではない。
    ・「確認」を理由に拒否しない。確認は人が見る前提で、一覧を出すだけ。
    ・ファイルの中身を直さない。指摘だけ。

要対応を承知で通す場合は --force を付ける。その事実も .check.txt に残る。

終了コードは、納品できたら 0、拒否したら 1。
"""
from __future__ import annotations

import argparse
import datetime as dt
import io
import os
import shutil
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))

# 実測が「測れなかった」と言うときの終了コード。要対応と区別する
CANNOT_MEASURE = 2
# 応答が返らなかったときにも同じ扱いをする（PowerPointが確認の窓を出すと止まる）
TIMED_OUT = -1
# 実測の待ち時間。100ページ規模でも1分あれば終わる
MEASURE_TIMEOUT = 600


def _run(cmd: list[str], timeout: float | None = None) -> tuple[int, str]:
    try:
        r = subprocess.run(cmd, capture_output=True, text=True,
                           encoding="utf-8", errors="replace", timeout=timeout)
    except subprocess.TimeoutExpired:
        return TIMED_OUT, f"{timeout:.0f} 秒で応答が返りませんでした。\n"
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def run(script: str, args: list[str]) -> tuple[int, str]:
    """検査スクリプトを別プロセスで走らせ、終了コードと出力を返す。"""
    return _run([sys.executable, os.path.join(HERE, script)] + args)


def powershell() -> str | None:
    """PowerShell の実行ファイル。無ければ None。"""
    return shutil.which("pwsh") or shutil.which("powershell")


def run_ps(script: str, args: list[str]) -> tuple[int, str]:
    """PowerShell の検査を走らせる。PowerShell が無ければ「測れなかった」。"""
    exe = powershell()
    if not exe:
        return CANNOT_MEASURE, "PowerShell が無いため、文字の実測はできません。"
    rc, out = _run([exe, "-NoProfile", "-ExecutionPolicy", "Bypass",
                    "-File", os.path.join(HERE, script)] + args,
                   timeout=MEASURE_TIMEOUT)
    # 0（はみ出しなし）と 1（はみ出しあり）以外は、**測れなかったとして扱う。**
    # PowerPointが確認の窓を出した、ファイルが開けない、COMが落ちた——
    # どれも「はみ出しがある」という意味ではない。既存3検査の判定を巻き添えにしない。
    return (rc if rc in (0, 1) else CANNOT_MEASURE), out


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="検査を通ったファイルにだけ納品名を付ける")
    ap.add_argument("pptx", help="作業中のレポート")
    ap.add_argument("--out", required=True, help="納品ファイルを置くフォルダ")
    ap.add_argument("--name", default="月次レポート", help="納品名の本体。既定「月次レポート」")
    ap.add_argument("--period", help="対象月 2026-08（値の検査に渡す）")
    ap.add_argument("--prev",
                    help="前月の納品ファイル。値の検査（前月との比較）と、"
                         "体裁の検査（前月より乱れていないかの基準）に渡す")
    ap.add_argument("--stray-dir", help="ごみファイルを探すフォルダ。既定は pptx のあるフォルダの親")
    ap.add_argument("--no-measure", action="store_true",
                    help="PowerPoint による文字の実測を行わない。"
                         "飛ばした事実は記録に残る")
    ap.add_argument("--force", action="store_true",
                    help="要対応があっても納品する。その事実は記録に残る")
    a = ap.parse_args()

    if not os.path.exists(a.pptx):
        print(f"ファイルがありません: {a.pptx}")
        return 1

    stray_dir = a.stray_dir or os.path.dirname(os.path.dirname(os.path.abspath(a.pptx)))
    values_args = [a.pptx]
    if a.period:
        values_args += ["--period", a.period]
    if a.prev:
        values_args += ["--prev", a.prev]

    # 体裁は前月の納品ファイルを基準にする。毎月同じ土台から作る資料には、
    # 図の作りそのものに由来する重なりが残る（フロー図の矢印ラベルは、上下
    # いっぱいに伸びた列の上に置くのが図の作りで、どこへ置いても列と交差する）。
    # それを毎月直させても意味がないので、**前月より乱れたかどうか**を見る。
    # 前月より大きくなったもの・増えたもの・前月に無かったものは要対応のまま。
    layout_args = [a.pptx]
    if a.prev:
        layout_args += ["--baseline", a.prev]

    steps = [
        ("ごみファイルの検査", "check_stray_files.py", [stray_dir], run),
        ("値の検査",         "check_values.py",      values_args, run),
        ("体裁の検査",       "check_layout.py",      layout_args, run),
    ]
    if not a.no_measure:
        # 体裁の検査は文字の高さを**見積もる**。PowerPoint があるなら、
        # 見積もらずに本人に測らせる。折り返したあとの高さが分かる唯一の方法である。
        steps.append(("文字の実測", "measure_text.ps1", [a.pptx], run_ps))

    log = [f"納品ゲート  {dt.datetime.now():%Y-%m-%d %H:%M:%S}",
           f"対象: {os.path.abspath(a.pptx)}", ""]
    failed, skipped = [], []
    for label, script, args, runner in steps:
        print(f"── {label}（{script}）")
        rc, out = runner(script, args)
        print(out.rstrip())
        log += [f"[{label}] {script} → 終了コード {rc}", out.rstrip(), ""]
        if rc == CANNOT_MEASURE and runner is run_ps:
            # 「測れなかった」を「問題なし」にしない。飛ばしたことを残す
            skipped.append(label)
            print(f"   ※ {label}は行えませんでした。記録に残します。")
        elif rc != 0:
            failed.append(label)

    print("=" * 60)
    if failed and not a.force:
        print(f"納品しません。要対応が残っています: {', '.join(failed)}")
        print("直してからもう一度。承知の上で通すなら --force（記録に残ります）。")
        return 1

    os.makedirs(a.out, exist_ok=True)
    stamp = dt.datetime.now().strftime("%Y%m%d_%H%M")
    dst = os.path.join(a.out, f"納品){a.name}_{stamp}.pptx")
    shutil.copy2(a.pptx, dst)

    if failed:
        log.append(f"★ --force により、要対応（{', '.join(failed)}）を承知で納品した")
    if a.no_measure:
        log.append("※ --no-measure により、文字の実測を行っていない")
    elif skipped:
        log.append(f"※ {'・'.join(skipped)}は行えなかった"
                   "（PowerPoint が無い）。見積もりだけで通している")
    log.append(f"納品: {dst}")
    with io.open(dst[:-5] + ".check.txt", "w", encoding="utf-8") as f:
        f.write("\n".join(log) + "\n")

    if a.no_measure or skipped:
        print("※ 文字の実測は行っていません。"
              "PowerPoint のある PC で measure_text.ps1 を通してください。")
    print(("★ --force で通しました: " if failed else "納品できます: ") + dst)
    print(f"検査の記録: {dst[:-5]}.check.txt")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
