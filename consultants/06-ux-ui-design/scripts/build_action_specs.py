#!/usr/bin/env python3
"""優先課題から、検証可能な改善施策仕様の下書きを生成する。"""

from __future__ import annotations

import argparse
import json
from pathlib import Path


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="改善課題から施策仕様を生成します。")
    parser.add_argument("--issues", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--all", action="store_true", help="selected=falseの課題も対象にする")
    return parser.parse_args()


def load_issues(path: Path) -> list[dict]:
    payload = json.loads(path.read_text(encoding="utf-8-sig"))
    issues = payload.get("issues", payload) if isinstance(payload, dict) else payload
    if not isinstance(issues, list):
        raise ValueError("issues配列が見つかりません。")
    return [item for item in issues if isinstance(item, dict)]


def build_action(issue: dict, index: int) -> dict:
    title = issue.get("title", "名称未設定の課題")
    return {
        "action_id": f"A-{index:03d}",
        "issue_id": issue.get("issue_id", "未採番"),
        "source_finding_ids": issue.get("source_finding_ids", []),
        "title": f"{title}に対する改善案",
        "problem": issue.get("fact", issue.get("statement", "根拠を追記してください。")),
        "hypothesis": issue.get("hypothesis", "ユーザーの判断または操作を妨げている要因を追加調査してください。"),
        "change": {
            "target_page": "対象URLまたは画面名を記入",
            "device": ["PC", "SP"],
            "before": "現在の状態を記入",
            "after": "変更後の状態を記入",
            "copy": "必要な文言を記入",
            "states": ["通常", "読込中", "エラー", "該当なし"],
        },
        "expected_change": "どの行動・指標を、どの方向へ変えるか記入",
        "measurement": {
            "primary_metric": "主要指標を記入",
            "guardrail_metrics": ["悪化させてはいけない指標を記入"],
            "events": ["必要な計測イベントを記入"],
            "method": "A/BテストまたはBefore/After",
            "minimum_period": "曜日構成と母数を考慮して記入",
        },
        "constraints": ["ブランド・システム・法務・運用上の制約を記入"],
        "acceptance_criteria": ["PC/SPで表示と操作を確認", "計測イベントを確認", "対象外画面への副作用を確認"],
        "evidence": issue.get("evidence", {}),
        "status": "要レビュー",
    }


def main() -> int:
    args = parse_args()
    issues = load_issues(args.issues)
    targets = issues if args.all else [item for item in issues if item.get("selected", True)]
    actions = [build_action(issue, index) for index, issue in enumerate(targets, start=1)]
    args.out.mkdir(parents=True, exist_ok=True)
    (args.out / "actions.json").write_text(json.dumps({"actions": actions}, ensure_ascii=False, indent=2), encoding="utf-8")

    lines = ["# UX/UI改善施策仕様", "", "> この文書は実装前の下書きです。現行画面・ブランド・システム制約を確認して確定してください。", ""]
    for action in actions:
        lines += [
            f"## {action['action_id']} {action['title']}", "",
            f"- 対応課題: {action['issue_id']}",
            f"- 問題: {action['problem']}",
            f"- 仮説: {action['hypothesis']}",
            f"- 対象: {action['change']['target_page']}",
            f"- Before: {action['change']['before']}",
            f"- After: {action['change']['after']}",
            f"- 期待変化: {action['expected_change']}",
            f"- 主要指標: {action['measurement']['primary_metric']}",
            f"- 検証方法: {action['measurement']['method']}", "",
            "### PC/SPワイヤーフレーム確認項目", "",
            "- 情報の優先順位と視線導線", "- タップ領域・文字サイズ・折返し", "- 通常／読込中／エラー／該当なし", "- 実装後に取得するイベント", "",
        ]
    if not actions:
        lines.append("選択済みの課題がありません。`--all` を付けるか、入力の `selected` を確認してください。")
    (args.out / "wireframe_specs.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
