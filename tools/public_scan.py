#!/usr/bin/env python3
"""公開前に顧客名、ローカルパス、認証情報、壊れたJSONを検査する。"""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path


TEXT_EXTENSIONS = {
    ".md", ".txt", ".py", ".ps1", ".js", ".mjs", ".json", ".csv",
    ".yml", ".yaml", ".toml", ".ini", ".cfg", ".gs", ".gitignore",
}
SKIP_PARTS = {".git", "__pycache__", ".venv", "node_modules", "output", "input"}

# 文字列を分割し、この検査ファイル自体に実案件名を残さない。
FORBIDDEN_TERMS = [
    "ライフ" + "エスコート",
    "life" + "-escort",
    "改善" + "ポケット",
    "abtest" + "-library-mcp",
    "ab" + "k_",
    "toun" + "be",
    "catering" + "-un",
]

SECRET_PATTERNS = {
    "Windowsの個人ローカルパス": re.compile(r"[A-Za-z]:\\Users\\[^\\\s]+", re.I),
    "メールアドレス": re.compile(r"\b[A-Z0-9._%+-]+@[A-Z0-9.-]+\.[A-Z]{2,}\b", re.I),
    "GA4測定ID": re.compile(r"\bG-[A-Z0-9]{7,}\b"),
    "GTMコンテナID": re.compile(r"\bGTM-[A-Z0-9]{5,}\b"),
    "GitHubトークン": re.compile(r"\b(?:ghp|github_pat)_[A-Za-z0-9_]{20,}\b"),
    "Google APIキー": re.compile(r"\bAIza[0-9A-Za-z_-]{30,}\b"),
    "AWSアクセスキー": re.compile(r"\bAKIA[0-9A-Z]{16}\b"),
    "秘密鍵": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="公開リポジトリの安全検査")
    parser.add_argument("root", nargs="?", default=".", type=Path)
    return parser.parse_args()


def is_text(path: Path) -> bool:
    return path.name in {"AGENTS.md", "CLAUDE.md", ".gitignore"} or path.suffix.lower() in TEXT_EXTENSIONS


def main() -> int:
    root = parse_args().root.resolve()
    issues: list[str] = []
    for path in sorted(root.rglob("*")):
        if not path.is_file() or any(part in SKIP_PARTS for part in path.relative_to(root).parts):
            continue
        if path.resolve() == Path(__file__).resolve() or not is_text(path):
            continue
        relative = path.relative_to(root)
        try:
            text = path.read_text(encoding="utf-8-sig")
        except UnicodeDecodeError:
            issues.append(f"{relative}: UTF-8で読めません")
            continue
        lowered = text.lower()
        for term in FORBIDDEN_TERMS:
            if term.lower() in lowered:
                issues.append(f"{relative}: 公開禁止語を検出")
        for label, pattern in SECRET_PATTERNS.items():
            if pattern.search(text):
                issues.append(f"{relative}: {label}らしき文字列を検出")
        if path.suffix.lower() == ".json":
            try:
                json.loads(text)
            except json.JSONDecodeError as exc:
                issues.append(f"{relative}:{exc.lineno}: JSON形式エラー")

    if issues:
        print("公開前検査: NG", file=sys.stderr)
        for issue in issues:
            print(f"- {issue}", file=sys.stderr)
        return 1
    print("公開前検査: OK（禁止語・代表的な秘密情報・JSON形式を確認）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
