#!/usr/bin/env python3
"""Search Console CSVを検索意図と機会の観点で要約する。"""

from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter, defaultdict
from pathlib import Path


ALIASES = {
    "query": ("query", "クエリ", "検索クエリ"),
    "page": ("page", "ページ", "landing page", "ランディング ページ"),
    "clicks": ("clicks", "クリック数", "クリック"),
    "impressions": ("impressions", "表示回数", "表示"),
    "ctr": ("ctr", "クリック率"),
    "position": ("position", "掲載順位", "平均掲載順位"),
}

DEFAULT_TERMS = {
    "比較・検討": ["比較", "おすすめ", "ランキング", "違い", "料金", "価格", "評判", "口コミ"],
    "疑問・課題": ["なぜ", "方法", "やり方", "できない", "原因", "とは", "how", "why"],
    "指名": [],
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Search Console CSVを分析します。")
    parser.add_argument("--input", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--config", type=Path, help="任意のJSON設定")
    parser.add_argument("--top", type=int, default=20)
    return parser.parse_args()


def normalize_header(value: str) -> str:
    return re.sub(r"[\s_\-]+", " ", value.strip().lower())


def resolve_columns(fieldnames: list[str]) -> dict[str, str]:
    normalized = {normalize_header(name): name for name in fieldnames}
    result: dict[str, str] = {}
    for canonical, aliases in ALIASES.items():
        for alias in aliases:
            if normalize_header(alias) in normalized:
                result[canonical] = normalized[normalize_header(alias)]
                break
    required = {"query", "clicks", "impressions"}
    missing = sorted(required - result.keys())
    if missing:
        raise ValueError(f"必須列が見つかりません: {', '.join(missing)}")
    return result


def number(value: object) -> float:
    text = str(value or "0").strip().replace(",", "").replace("%", "")
    try:
        return float(text)
    except ValueError:
        return 0.0


def load_config(path: Path | None) -> dict:
    config = {"brand_terms": [], "intent_terms": DEFAULT_TERMS, "low_ctr_threshold": 0.03}
    if path and path.exists():
        supplied = json.loads(path.read_text(encoding="utf-8-sig"))
        config.update(supplied)
        merged = dict(DEFAULT_TERMS)
        merged.update(supplied.get("intent_terms", {}))
        config["intent_terms"] = merged
    return config


def classify(query: str, config: dict) -> str:
    lower = query.lower()
    if any(term.lower() in lower for term in config.get("brand_terms", []) if term):
        return "指名"
    for label, terms in config["intent_terms"].items():
        if label == "指名":
            continue
        if any(term.lower() in lower for term in terms if term):
            return label
    return "一般・情報収集"


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    with args.input.open(encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        columns = resolve_columns(reader.fieldnames or [])
        rows = list(reader)

    analyzed = []
    intents: Counter[str] = Counter()
    intent_metrics: dict[str, dict[str, float]] = defaultdict(lambda: {"clicks": 0.0, "impressions": 0.0})
    for row in rows:
        query = str(row.get(columns["query"], "")).strip()
        clicks = number(row.get(columns["clicks"]))
        impressions = number(row.get(columns["impressions"]))
        raw_ctr_value = row.get(columns.get("ctr", ""))
        raw_ctr = number(raw_ctr_value)
        ctr = raw_ctr / 100 if "%" in str(raw_ctr_value) or raw_ctr > 1 else raw_ctr
        if "ctr" not in columns and impressions:
            ctr = clicks / impressions
        position = number(row.get(columns.get("position", ""))) if "position" in columns else None
        intent = classify(query, config)
        intents[intent] += 1
        intent_metrics[intent]["clicks"] += clicks
        intent_metrics[intent]["impressions"] += impressions
        analyzed.append({
            "query": query,
            "page": str(row.get(columns.get("page", ""), "")).strip(),
            "clicks": clicks,
            "impressions": impressions,
            "ctr": round(ctr, 6),
            "position": position,
            "intent": intent,
        })

    ranked = sorted(analyzed, key=lambda item: item["impressions"], reverse=True)
    opportunity = [
        item for item in ranked
        if item["impressions"] >= 10 and item["ctr"] < float(config["low_ctr_threshold"])
    ][: args.top]

    findings = []
    for index, item in enumerate(opportunity, start=1):
        findings.append({
            "finding_id": f"F-{index:03d}",
            "job": "04",
            "title": f"表示機会に対してCTRが低い検索語: {item['query']}",
            "fact": f"表示回数{item['impressions']:.0f}、CTR{item['ctr']:.1%}、平均掲載順位{item['position'] if item['position'] is not None else '未取得'}",
            "statement": f"{item['query']} は表示回数{item['impressions']:.0f}に対してCTRが{item['ctr']:.1%}です。",
            "hypothesis": "検索結果のタイトル・説明または遷移先が検索意図に十分応えていない可能性があります。",
            "evidence": {"query": item["query"], "page": item["page"]},
            "status": "未検証",
        })

    intent_summary = []
    for label, metrics in sorted(intent_metrics.items()):
        ctr = metrics["clicks"] / metrics["impressions"] if metrics["impressions"] else 0.0
        intent_summary.append({
            "intent": label,
            "queries": intents[label],
            "clicks": metrics["clicks"],
            "impressions": metrics["impressions"],
            "ctr": round(ctr, 6),
        })

    args.out.mkdir(parents=True, exist_ok=True)
    payload = {"row_count": len(analyzed), "intent_summary": intent_summary, "opportunities": opportunity}
    (args.out / "search_analysis.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    (args.out / "findings.json").write_text(json.dumps({"findings": findings}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# Search Console分析", "", f"対象行数: {len(analyzed)}", "", "## 検索意図別", ""]
    lines += ["| 検索意図 | クエリ数 | クリック | 表示回数 | CTR |", "|---|---:|---:|---:|---:|"]
    for item in intent_summary:
        lines.append(f"| {item['intent']} | {item['queries']} | {item['clicks']:.0f} | {item['impressions']:.0f} | {item['ctr']:.1%} |")
    lines += ["", "## 高表示・低CTRの機会", ""]
    if opportunity:
        lines += ["| クエリ | 表示回数 | CTR | 掲載順位 |", "|---|---:|---:|---:|"]
        for item in opportunity:
            lines.append(f"| {item['query']} | {item['impressions']:.0f} | {item['ctr']:.1%} | {item['position'] if item['position'] is not None else '-'} |")
    else:
        lines.append("該当なし。閾値は設定ファイルで変更できます。")
    (args.out / "search_analysis.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
