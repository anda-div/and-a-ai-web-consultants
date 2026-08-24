#!/usr/bin/env python3
"""正規化したGA4 CSVを期間比較し、JSON/Markdown/所見を出力する。"""

from __future__ import annotations

import argparse
import csv
import json
import math
from collections import defaultdict
from pathlib import Path


def number(value: str | int | float | None) -> float:
    if value is None or value == "":
        return 0.0
    if isinstance(value, (int, float)):
        return float(value)
    text = str(value).strip().replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def pct_change(current: float, previous: float) -> float | None:
    if previous == 0:
        return None
    return (current - previous) / previous * 100


def load_config(path: Path | None) -> dict:
    if not path:
        return {}
    return json.loads(path.read_text(encoding="utf-8-sig"))


def load_rows(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as fh:
        return list(csv.DictReader(fh))


def infer_columns(rows: list[dict[str, str]], config: dict) -> tuple[list[str], list[str]]:
    if not rows:
        raise ValueError("入力CSVにデータ行がありません。")
    fields = list(rows[0])
    period_col = config.get("analysis", {}).get("period_column", "period")
    configured_metrics = config.get("analysis", {}).get("metric_columns")
    if configured_metrics:
        metrics = [c for c in configured_metrics if c in fields]
    else:
        metrics = []
        for field in fields:
            if field == period_col:
                continue
            values = [r.get(field, "") for r in rows if r.get(field, "") != ""][:30]
            if values and sum(1 for v in values if _looks_numeric(v)) / len(values) >= 0.8:
                metrics.append(field)
    configured_dims = config.get("analysis", {}).get("dimension_columns")
    dimensions = [c for c in (configured_dims or fields) if c not in metrics and c != period_col]
    if not metrics:
        raise ValueError("数値指標列を判定できません。configのanalysis.metric_columnsで指定してください。")
    return dimensions, metrics


def _looks_numeric(value: str) -> bool:
    text = str(value).strip().replace(",", "").replace("%", "")
    try:
        float(text)
        return True
    except ValueError:
        return False


def analyze(rows: list[dict[str, str]], config: dict) -> dict:
    period_col = config.get("analysis", {}).get("period_column", "period")
    current_label = config.get("analysis", {}).get("current_label", "current")
    previous_label = config.get("analysis", {}).get("comparison_label", "previous")
    dimensions, metrics = infer_columns(rows, config)

    totals: dict[str, dict[str, float]] = {current_label: defaultdict(float), previous_label: defaultdict(float)}
    grouped: dict[str, dict[str, dict[str, dict[str, float]]]] = {
        d: defaultdict(lambda: {current_label: defaultdict(float), previous_label: defaultdict(float)})
        for d in dimensions
    }

    ignored_periods: set[str] = set()
    for row in rows:
        period = row.get(period_col, "").strip()
        if period not in totals:
            ignored_periods.add(period or "(blank)")
            continue
        for metric in metrics:
            value = number(row.get(metric))
            totals[period][metric] += value
            for dim in dimensions:
                key = row.get(dim, "").strip() or "(not set)"
                grouped[dim][key][period][metric] += value

    total_comparison = {}
    for metric in metrics:
        cur = totals[current_label][metric]
        prev = totals[previous_label][metric]
        total_comparison[metric] = {
            "current": cur,
            "previous": prev,
            "absolute_change": cur - prev,
            "percent_change": pct_change(cur, prev),
        }

    breakdowns = {}
    for dim, values in grouped.items():
        items = []
        for key, periods in values.items():
            metric_values = {}
            for metric in metrics:
                cur = periods[current_label][metric]
                prev = periods[previous_label][metric]
                metric_values[metric] = {
                    "current": cur,
                    "previous": prev,
                    "absolute_change": cur - prev,
                    "percent_change": pct_change(cur, prev),
                }
            items.append({"value": key, "metrics": metric_values})
        breakdowns[dim] = items

    return {
        "period_column": period_col,
        "current_label": current_label,
        "comparison_label": previous_label,
        "metrics": metrics,
        "dimensions": dimensions,
        "ignored_periods": sorted(ignored_periods),
        "totals": total_comparison,
        "breakdowns": breakdowns,
    }


def make_findings(result: dict, limit: int = 5) -> list[dict]:
    candidates = []
    for dim, items in result["breakdowns"].items():
        for item in items:
            for metric, values in item["metrics"].items():
                candidates.append((abs(values["absolute_change"]), dim, item["value"], metric, values))
    candidates.sort(reverse=True, key=lambda x: x[0])
    findings = []
    for index, (_, dim, value, metric, values) in enumerate(candidates[:limit], 1):
        rate = values["percent_change"]
        rate_text = "比較元が0のため増減率なし" if rate is None else f"{rate:+.1f}%"
        findings.append({
            "finding_id": f"F-{index:03d}",
            "job": "02",
            "statement": f"{dim}={value} の {metric} は {values['previous']:.2f} から {values['current']:.2f}（{rate_text}）",
            "evidence": [f"absolute_change={values['absolute_change']:.2f}"],
            "confidence": "high",
            "status": "confirmed",
            "next_check": "原因を断定せず、関連するページ・施策・計測変更を確認する。",
        })
    return findings


def markdown(result: dict, findings: list[dict]) -> str:
    lines = ["# GA4期間比較レポート", "", "## 全体", "", "| 指標 | 比較期間 | 対象期間 | 差 | 増減率 |", "|---|---:|---:|---:|---:|"]
    for metric, values in result["totals"].items():
        rate = values["percent_change"]
        rate_text = "—" if rate is None or not math.isfinite(rate) else f"{rate:+.1f}%"
        lines.append(f"| {metric} | {values['previous']:.2f} | {values['current']:.2f} | {values['absolute_change']:+.2f} | {rate_text} |")
    lines += ["", "## 変化量の大きい所見", ""]
    for finding in findings:
        lines.append(f"- **{finding['finding_id']}** {finding['statement']}")
    if result["ignored_periods"]:
        lines += ["", "## 除外された期間ラベル", "", ", ".join(result["ignored_periods"])]
    lines += ["", "> 原因は本レポートだけでは確定していません。関連施策、計測変更、ページ内容を追加確認してください。", ""]
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--finding-limit", type=int, default=5)
    args = parser.parse_args()

    config = load_config(args.config)
    result = analyze(load_rows(args.input), config)
    findings = make_findings(result, args.finding_limit)
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "analysis.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "findings.json").write_text(json.dumps(findings, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "analysis.md").write_text(markdown(result, findings), encoding="utf-8")
    print(f"Wrote {args.out}")


if __name__ == "__main__":
    main()
