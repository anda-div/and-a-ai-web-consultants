#!/usr/bin/env python3
"""施策前後のmetric,value形式CSVを比較する。"""

from __future__ import annotations

import argparse
import csv
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Before/After指標を比較します。")
    parser.add_argument("--before", required=True, type=Path)
    parser.add_argument("--after", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path, help="Markdown出力先")
    parser.add_argument("--json-out", type=Path)
    return parser.parse_args()


def load(path: Path) -> dict[str, float]:
    result: dict[str, float] = {}
    with path.open(encoding="utf-8-sig", newline="") as handle:
        for row in csv.DictReader(handle):
            metric = str(row.get("metric", row.get("指標", ""))).strip()
            raw = str(row.get("value", row.get("値", "0"))).strip().replace(",", "").replace("%", "")
            if metric:
                result[metric] = float(raw)
    return result


def main() -> int:
    args = parse_args()
    before = load(args.before)
    after = load(args.after)
    metrics = sorted(set(before) | set(after))
    comparisons = []
    for metric in metrics:
        old = before.get(metric)
        new = after.get(metric)
        absolute = new - old if old is not None and new is not None else None
        rate = (absolute / old * 100) if absolute is not None and old else None
        comparisons.append({"metric": metric, "before": old, "after": new, "absolute_change": absolute, "change_rate_percent": rate})

    lines = ["# Before/After 効果検証", "", "> 前後期間の曜日・施策・計測条件・母数が比較可能かを別途確認してください。", "", "| 指標 | Before | After | 差 | 増減率 |", "|---|---:|---:|---:|---:|"]
    for item in comparisons:
        def fmt(value):
            return "-" if value is None else f"{value:,.2f}"
        rate_text = "-" if item["change_rate_percent"] is None else f"{item['change_rate_percent']:+.1f}%"
        lines.append(f"| {item['metric']} | {fmt(item['before'])} | {fmt(item['after'])} | {fmt(item['absolute_change'])} | {rate_text} |")
    lines += ["", "## 解釈前の確認", "", "- 比較期間の長さと曜日構成", "- 広告・キャンペーン・在庫・価格の変化", "- 計測定義・同意率・タグ実装の変化", "- セグメント別の逆方向の動き", "- 統計的な揺れと必要母数", ""]
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_text("\n".join(lines), encoding="utf-8")
    json_out = args.json_out or args.out.with_suffix(".json")
    json_out.write_text(json.dumps({"comparisons": comparisons}, ensure_ascii=False, indent=2), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
