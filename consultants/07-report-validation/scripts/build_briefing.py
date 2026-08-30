# -*- coding: utf-8 -*-
"""月初ブリーフィング（汎用）

毎月、白紙から考え始めるのをやめるための道具。
データを置いたら、まずこれを実行する。

  機械が揃えるもの（このスクリプト）
    ・先月までに出した提案の状況
    ・今月、効果を検証すべき提案（実装済みで未検証のもの）
    ・今月使える切り口（直近で使っていないもの）
    ・今月の主要指標

  AIが出すもの（Claude Code が、この出力を読んで書き足す）
    ・提案候補
    ・各候補の根拠と、台帳との重複チェック結果

  人が決めるもの
    ・候補のうち、どれをレポートに載せるか
    ・言い切り方と、相手への配慮

「考え出す」から「選んで磨く」に変えるのが狙い。
提案そのものを機械に作らせるのではない。

    python build_briefing.py            Config の対象期間で作る
    python build_briefing.py 2026-07    月を指定して作る
"""
from __future__ import annotations

import io
import json
import os
import sys
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from ledger import Ledger, find_dir  # noqa: E402
from report_config import load as load_config  # noqa: E402

HISTORY = "angles_history.json"


def prev_periods(period: str, n: int) -> list[str]:
    y, m = int(period[:4]), int(period[5:7])
    out = []
    for _ in range(n):
        m -= 1
        if m == 0:
            y, m = y - 1, 12
        out.append(f"{y:04d}-{m:02d}")
    return out


def load_catalog(cfg) -> dict:
    for d in (cfg.defaults_dir, os.path.dirname(os.path.abspath(__file__))):
        if not d:
            continue
        p = os.path.join(d, "angles_catalog.json")
        if os.path.exists(p):
            with io.open(p, encoding="utf-8") as f:
                return json.load(f)
    raise FileNotFoundError("angles_catalog.json が見つかりません")


def load_history(ldir: str) -> dict:
    p = os.path.join(ldir, HISTORY)
    if os.path.exists(p):
        with io.open(p, encoding="utf-8") as f:
            return json.load(f)
    return {"_comment": "使った切り口の履歴。build_briefing.py が読み、人が書き足す。",
            "used": []}


def kpi_lines(cfg) -> list[str]:
    """GA4のKPIサマリを読む。無ければ黙って飛ばす。"""
    try:
        import openpyxl
        wb = openpyxl.load_workbook(cfg.ga4_xlsx("site"), data_only=True)
        rows = [r for r in wb["01_KPIサマリ"].values if r and r[0]]
        def fmt(v):
            if isinstance(v, (int, float)):
                return f"{v:,.0f}" if float(v).is_integer() else f"{v:,.1f}"
            return str(v)

        out = []
        for r in rows[1:]:
            vals = [fmt(v) for v in r[1:4] if v is not None]
            out.append(f"| {r[0]} | " + " | ".join(vals) + " |")
        return out
    except Exception:
        return []


def build(period: str) -> str:
    cfg = load_config()
    ldir = find_dir(cfg.root)
    lg = Ledger(os.path.join(ldir, "proposals.json"))
    cat = load_catalog(cfg)
    hist = load_history(ldir)

    cool = cat.get("cooldown_months", 3)
    recent = set()
    for e in hist.get("used", []):
        if e.get("period") in prev_periods(period, cool):
            recent |= set(e.get("angles", []))

    L = []
    A = L.append
    A(f"# {period} 月初ブリーフィング")
    A("")
    A("白紙から考え始めないための材料です。**提案そのものはまだ書いていません。**")
    A("下の「4. 提案候補」を Claude Code に埋めてもらい、そこから人が選びます。")
    A("")

    # ---------------------------------------------------------- 1
    A("## 1. 台帳の状況")
    A("")
    st = lg.stats()
    A("| 状態 | 件数 |")
    A("|---|---|")
    for k, v in st.items():
        if k != "合計":
            A(f"| {k} | {v} |")
    A(f"| **合計** | **{st['合計']}** |")
    A("")

    pend = lg.pending()
    if pend:
        A(f"### まだ実装されていない提案（{len(pend)} 件）")
        A("")
        A("同じ課題が今月も残っているなら、**新しい提案を足す前に、これらの再提示を検討します。**")
        A("出し直しは重複ではありません。状況が変わっていないという事実の報告です。")
        A("")
        A("| ID | 対象 | 提案 | 工数 |")
        A("|---|---|---|---|")
        for i in pend:
            A(f"| {i['id']} | {i.get('target','')} | {i['title']} | {i.get('effort','')} |")
        A("")

    low = lg.low_cost()
    if low:
        A(f"### 低コスト帯（{len(low)} 件）")
        A("")
        A("外注しても金額が小さいものです。**個別に見積を取らず、"
          "まとめて1回の発注にする**のが要点です。")
        A("1文字の修正でも、見積・発注・検収の手続きは1件ぶん発生します。"
          "手続きの回数そのものが、実装されない理由になっている場合があります。")
        A("")
        A("| ID | 提案 | 工数 | 発注指示 |")
        A("|---|---|---|---|")
        for i in low:
            A(f"| {i['id']} | {i['title']} | {i.get('effort','')} | "
              f"{i.get('vendor_brief','') or '—'} |")
        A("")

    revisit = lg.revisit_due(period)
    if revisit:
        A(f"### 再検討の期日が来た保留（{len(revisit)} 件）")
        A("")
        A("催促ではなく、**期日が来たという事実**として持ち出してください。")
        A("")
        for i in revisit:
            A(f"- {i['id']}　{i['title']}")
            A(f"    - 待っていたもの：{i.get('blocked_by','（未記入）')}")
        A("")

    rejected = [i for i in lg.items if i["status"] == "却下"]
    if rejected:
        A(f"### 却下された提案（{len(rejected)} 件）")
        A("")
        A("**同じ案を出し直さないため**に載せています。却下の理由が解消していれば再提示できます。")
        A("")
        for i in rejected:
            A(f"- {i['id']}　{i['title']}")
            if i.get("status_note"):
                A(f"    - 理由：{i['status_note']}")
        A("")

    # ---------------------------------------------------------- 2
    A("## 2. 今月、効果を検証すべき提案")
    A("")
    due = lg.verify_due(period)
    if not due:
        A("実装済みで未検証の提案はありません。")
        A("")
        A("> 実装された提案があれば、次のように台帳へ記録してください。"
          "記録があると、翌月に前後比較ができます。")
        A("> ")
        A("> ```bash")
        A("> python _scripts/report/ledger.py --set P-2026-06-001 "
          "--status 実装済み --date 2026-07-15")
        A("> ```")
    else:
        A("**ここが今月のレポートの出発点です。**効いたか効かなかったかで、次の提案が決まります。")
        A("")
        A("| ID | 提案 | 実装日 | 見る指標 | 実装前の値 |")
        A("|---|---|---|---|---|")
        for i in due:
            A(f"| {i['id']} | {i['title']} | {i['implemented_on']} | "
              f"{i.get('metric','')} | {i.get('baseline','')} |")
        A("")
        A("実装日の前後で同じ日数を切り、同じ条件で比較します。")
        A("`compare_periods.py` が使えます。結果は次のように台帳へ戻します。")
        A("")
        A("```bash")
        A("python _scripts/report/ledger.py --set <ID> --status 検証済み")
        A("```")
    A("")

    # ---------------------------------------------------------- 3
    A("## 3. 今月の切り口候補")
    A("")
    A(f"直近 {cool} か月（{'、'.join(prev_periods(period, cool))}）で使った切り口を外しました。")
    A("**新しさはひらめきではなく、ここのローテーションが生みます。**")
    A("")
    by_cat = defaultdict(list)
    for a in cat["angles"]:
        if a["key"] not in recent:
            by_cat[a["category"]].append(a)
    if recent:
        A(f"今回外したもの：{'、'.join(sorted(recent))}")
        A("")
    for c in sorted(by_cat):
        A(f"### {c}")
        A("")
        for a in by_cat[c]:
            A(f"- **{a['name']}**　`{a['key']}`")
            A(f"    - 問い：{a['question']}")
            A(f"    - 必要なデータ：{'、'.join(a['needs'])}")
            A(f"    - 出やすい所見：{a['typical']}")
        A("")

    # ---------------------------------------------------------- 4
    A("## 4. 今月の主要指標")
    A("")
    kpi = kpi_lines(cfg)
    if kpi:
        A("| 指標 | 当月 | 前月 | 前月比 |")
        A("|---|---|---|---|")
        L.extend(kpi)
    else:
        A("GA4データがまだ置かれていません。"
          "`_input/GA4_data/` に配置してから、もう一度実行してください。")
    A("")

    # ---------------------------------------------------------- 5
    A("## 5. 提案候補（ここから先は Claude Code が書きます）")
    A("")
    A("### Claude Code への依頼文（そのままコピーできます）")
    A("")
    A("```text")
    A(f"このブリーフィング（_runs/briefing_{period}.md）を読んでください。")
    A("")
    A("1. 「3. 今月の切り口候補」から3本選び、選んだ理由を書いてください。")
    A("2. その3本と、今月のデータから、改善提案の候補を10本出してください。")
    A("3. 各候補について、次を必ず書いてください。")
    A("     ・根拠（どのシートの何の数値か、どのキャプチャのどこか）")
    A("     ・工数の見立て（文言のみ／設定のみ／軽微改修／中規模改修／中期）")
    A("     ・効く指標。**できる限り「局所の比率」にすること。**")
    A("       良い例：到達→開始の率、閲覧→カート追加の率")
    A("       避ける：セッション数、問い合わせ件数、売上")
    A("       理由：分子と分母が同じ段階にあれば、広告のロジック変更・競合の動き・")
    A("             季節性は両方に等しくかかるため、比率は環境変化に残る。")
    A("     ・制作会社にそのまま渡せる発注指示（低コスト帯は必須）")
    A("4. 各候補について台帳を照会し、結果を併記してください。")
    A("     python _scripts/report/ledger.py --similar \"<候補の文言>\" --angle <切り口>")
    A("     新規／再提示（IDを明記）／却下済みのため出さない、のいずれかに分類。")
    A("5. 推測で数値を作らないでください。根拠が出せない候補は、出さずに理由を書いてください。")
    A("```")
    A("")
    A("### 候補（Claude Code が記入）")
    A("")
    A("| # | 提案 | 切り口 | 根拠 | 工数 | 効く指標 | 台帳照会 |")
    A("|---|---|---|---|---|---|---|")
    for n in range(1, 11):
        A(f"| {n} |  |  |  |  |  |  |")
    A("")

    # ---------------------------------------------------------- 6
    A("## 6. 人が決めること")
    A("")
    A("候補が出そろったら、ここから先は機械にもAIにも任せません。")
    A("")
    A("- [ ] 10本のうち、今月のレポートに載せる3〜5本を選ぶ")
    A("- [ ] 効果の見立てが言い過ぎになっていないか確かめる")
    A("- [ ] 先方が読んで気分を害する書き方になっていないか確かめる")
    A("- [ ] 直近の打ち合わせでの発言と矛盾していないか確かめる")
    A("- [ ] 低コスト帯は、まとめて1回の発注にできる形にする")
    A("- [ ] 選んだ提案を台帳へ登録する（次の月の資産になります）")
    A("- [ ] 使った切り口を `_ledger/angles_history.json` に記録する")
    A("")
    return "\n".join(L) + "\n"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    cfg = load_config()
    period = sys.argv[1] if len(sys.argv) > 1 else cfg.reports_def["current_period"]["key"]
    text = build(period)
    out_dir = cfg.path("_runs")
    os.makedirs(out_dir, exist_ok=True)
    out = os.path.join(out_dir, f"briefing_{period}.md")
    with io.open(out, "w", encoding="utf-8") as f:
        f.write(text)
    print(f"=== 保存 === {out}")
    print(f"行数: {len(text.splitlines())}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
