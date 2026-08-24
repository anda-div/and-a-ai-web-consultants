# -*- coding: utf-8 -*-
"""
gt_reconcile.py — レポート記載値と独立再集計値の突合表を作る
================================================================================
第三者評価で最初にやるべきなのは「転記精度の検証」である。
ここで全項目が一致していれば、以降の指摘は「数え間違い」ではなく
「壊れた計測器の目盛りを読んでいた」という別の性質の話になる。
この切り分けを最初に済ませておくと、評価される側も受け入れやすい。

使い方:
    python gt_reconcile.py <突合定義.json> [--numbers <numbers.json>] [--out <出力先.md>]

突合定義.json の形式（配列）:
    [
      {"group": "GA4", "item": "セッション",     "reported": 2159, "measured": 2159},
      {"group": "GA4", "item": "PV",           "reported": 8784, "measured": 8784,
       "note": "一致するが実質は約4,392（I-01）", "verdict": "△"},
      {"group": "GA4", "item": "フォーム開始",   "reported": 37,   "measured": 19,
       "note": "37はサイト全体の合計（I-05）"},
      {"group": "SC",  "item": "CTR",          "reported": "5.2%", "measured": "5.19%"}
    ]

判定（verdict を書かなければ自動で付く）:
    ◎ 一致        … 相対誤差 0.5% 以内（丸めの範囲）
    △ 要注意      … 一致するが解釈に注意が必要（verdict で明示指定する）
    × 不一致      … 相対誤差 0.5% 超

--numbers を渡すと、レポート本文のどこにその数字が出ているか（修正すべき箇所）を
numbers.json（gt_extract.py の出力）から引いて併記する。
"""
import sys, os, re, json, argparse

TOL = 0.005


def to_num(v):
    if v is None:
        return None
    if isinstance(v, (int, float)):
        return float(v)
    s = str(v).strip().replace(",", "").replace("％", "%")
    m = re.search(r"-?\d+(?:\.\d+)?", s)
    return float(m.group(0)) if m else None


def judge(rep, mea):
    a, b = to_num(rep), to_num(mea)
    if a is None or b is None:
        return "―"
    if a == b:
        return "◎ 一致"
    base = max(abs(a), abs(b), 1e-9)
    return "◎ 一致" if abs(a - b) / base <= TOL else "× 不一致"


def locate(numbers, value):
    if not numbers:
        return ""
    target = to_num(value)
    if target is None:
        return ""
    hits = []
    for n in numbers:
        if abs(n["value"] - target) < 1e-9:
            hits.append(n["block"])
    hits = sorted(set(hits), key=lambda s: (len(s), s))
    if not hits:
        return "（本文に見当たらず）"
    return ", ".join(hits[:8]) + (f" ほか{len(hits)-8}件" if len(hits) > 8 else "")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("spec")
    ap.add_argument("--numbers")
    ap.add_argument("--out", default="突合表.md")
    a = ap.parse_args()

    with open(a.spec, encoding="utf-8") as f:
        rows = json.load(f)
    numbers = None
    if a.numbers and os.path.exists(a.numbers):
        with open(a.numbers, encoding="utf-8") as f:
            numbers = json.load(f)

    groups = {}
    for r in rows:
        groups.setdefault(r.get("group", ""), []).append(r)

    out = ["# 数値突合表\n",
           "レポート記載値と、生データからの独立再集計値の対照。\n"]
    stat = {"◎ 一致": 0, "△": 0, "× 不一致": 0, "―": 0}
    for g, items in groups.items():
        out.append(f"## {g}\n" if g else "## 突合\n")
        head = "| 項目 | レポート記載 | 実測 | 判定 | 備考 |"
        if numbers:
            head = "| 項目 | レポート記載 | 実測 | 判定 | 記載箇所 | 備考 |"
        out += [head, "|" + "---|" * (6 if numbers else 5)]
        for r in items:
            v = r.get("verdict") or judge(r.get("reported"), r.get("measured"))
            key = "△" if v.startswith("△") else v
            stat[key] = stat.get(key, 0) + 1
            cells = [str(r.get("item", "")), str(r.get("reported", "")),
                     str(r.get("measured", "")), v]
            if numbers:
                cells.append(locate(numbers, r.get("reported")))
            cells.append(str(r.get("note", "")))
            out.append("| " + " | ".join(cells) + " |")
        out.append("")

    total = sum(stat.values())
    mismatch = stat.get("× 不一致", 0)
    out.append("## 転記精度についての総評\n")
    if total and mismatch == 0:
        out.append(f"全{total}項目が実測値と一致した（丸めの範囲を含む）。"
                   "恣意的な切り上げ・切り捨ては見つかっていない。"
                   "したがって本評価の指摘は「数え間違い」ではなく、"
                   "**計測設定そのものの不備と、その状態のデータの読み方**に集中する。\n")
    else:
        out.append(f"全{total}項目のうち {mismatch} 項目が不一致。"
                   "不一致の各項目について、集計定義・母集団・期間のどれが原因かを特定すること"
                   "（多くの場合は「別の母集団の数字を並べていた」であり、単純な誤記ではない）。\n")
    out.append("| 判定 | 件数 |")
    out.append("|---|---|")
    for k, v in stat.items():
        if v:
            out.append(f"| {k} | {v} |")

    with open(a.out, "w", encoding="utf-8") as f:
        f.write("\n".join(out))
    print(f"突合 {total} 項目（不一致 {mismatch} 件）→ {a.out}")


if __name__ == "__main__":
    main()
