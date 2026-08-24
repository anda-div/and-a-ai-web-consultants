#!/usr/bin/env python3
"""複数JOBの所見を統合し、根拠・効果・実行性で優先順位を付ける。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


SCORE_KEYS = ("evidence", "impact", "confidence", "effort", "risk", "urgency")
DEFAULTS = {"evidence": 3, "impact": 3, "confidence": 3, "effort": 3, "risk": 2, "urgency": 3}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="所見を統合して改善課題を優先順位付けします。")
    parser.add_argument("--input", required=True, type=Path, help="JSONファイルまたはJSON群のディレクトリ")
    parser.add_argument("--config", type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--top", type=int, default=5)
    return parser.parse_args()


def load_config(path: Path | None) -> dict:
    config = {"top_n": 5, "weights": {key: 1.0 for key in SCORE_KEYS}}
    if path and path.exists():
        supplied = json.loads(path.read_text(encoding="utf-8-sig"))
        config.update(supplied)
        config["weights"] = {**{key: 1.0 for key in SCORE_KEYS}, **supplied.get("weights", {})}
    return config


def load_findings(path: Path) -> list[dict]:
    files = sorted(path.rglob("*.json")) if path.is_dir() else [path]
    findings: list[dict] = []
    for file in files:
        payload = json.loads(file.read_text(encoding="utf-8-sig"))
        values = payload.get("findings", []) if isinstance(payload, dict) else payload
        if not isinstance(values, list):
            raise ValueError(f"所見の配列がありません: {file}")
        for value in values:
            if isinstance(value, dict):
                item = dict(value)
                item.setdefault("source_file", file.name)
                findings.append(item)
    return findings


def bounded(value: object, default: int) -> float:
    if isinstance(value, str):
        mapped = {"high": 5, "medium": 3, "low": 2}.get(value.lower())
        if mapped is not None:
            return float(mapped)
    try:
        return max(1.0, min(5.0, float(value)))
    except (TypeError, ValueError):
        return float(default)


def signature(item: dict) -> str:
    value = " ".join(str(item.get(key, "")) for key in ("title", "fact", "hypothesis"))
    return "".join(value.lower().split())[:200]


def score(item: dict, weights: dict) -> tuple[float, dict[str, float]]:
    supplied = item.get("priority_scores", {})
    values = {}
    for key in SCORE_KEYS:
        raw = supplied.get(key)
        if raw is None:
            raw = item.get("evidence_score") if key == "evidence" else item.get(key)
        values[key] = bounded(raw, DEFAULTS[key])
    benefit = values["evidence"] * weights["evidence"]
    benefit += values["impact"] * weights["impact"]
    benefit += values["confidence"] * weights["confidence"]
    benefit += values["urgency"] * weights["urgency"]
    cost = values["effort"] * weights["effort"] + values["risk"] * weights["risk"]
    return round(benefit * 5 / max(cost, 1), 2), values


def main() -> int:
    args = parse_args()
    config = load_config(args.config)
    raw = load_findings(args.input)
    deduplicated: list[dict] = []
    seen: set[str] = set()
    for item in raw:
        key = signature(item)
        if key and key in seen:
            continue
        seen.add(key)
        deduplicated.append(item)

    issues = []
    for item in deduplicated:
        total, values = score(item, config["weights"])
        issues.append({
            "issue_id": "",
            "source_finding_ids": [item.get("finding_id", "未採番")],
            "title": item.get("title", item.get("statement", "名称未設定の課題")),
            "fact": item.get("fact", item.get("statement", "")),
            "hypothesis": item.get("hypothesis", ""),
            "scores": values,
            "priority_score": total,
            "evidence": item.get("evidence", {}),
            "status": "候補",
        })
    issues.sort(key=lambda value: value["priority_score"], reverse=True)
    for index, issue in enumerate(issues, start=1):
        issue["issue_id"] = f"I-{index:03d}"
        issue["rank"] = index
        issue["selected"] = index <= int(config.get("top_n", args.top) or args.top)

    selected = [issue for issue in issues if issue["selected"]]
    args.out.mkdir(parents=True, exist_ok=True)
    payload = {"issues": issues, "selected_issue_ids": [item["issue_id"] for item in selected]}
    (args.out / "prioritized_issues.json").write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# 改善課題の優先順位", "", f"入力所見: {len(raw)}件 / 重複除外後: {len(issues)}件", "", "| 順位 | 課題ID | 課題 | スコア | 今月着手 |", "|---:|---|---|---:|:---:|"]
    for item in issues:
        lines.append(f"| {item['rank']} | {item['issue_id']} | {item['title']} | {item['priority_score']:.2f} | {'●' if item['selected'] else '-'} |")
    lines += ["", "## 採点の考え方", "", "根拠・影響・確度・緊急度を便益、工数・リスクを負担として相対評価します。1〜5点の初期値はAIの仮置きであり、最終決定は事業条件を知る担当者が行ってください。", ""]
    (args.out / "prioritized_issues.md").write_text("\n".join(lines), encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
