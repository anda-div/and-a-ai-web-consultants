# -*- coding: utf-8 -*-
"""紛れ込んだごみファイルを見つける（納品前チェック用）

シェル経由で複数行のコードを渡すと、コード中の `>`（比較演算子、f文字列の
桁揃え `{i:>3}`、正規表現の `[^>]*>` など）が出力リダイレクトとして解釈され、
直後の語をファイル名とするファイルが作られることがある。

    if i > 12:        →  「12」という空ファイルができる
    f"{i:>3}"         →  「3}」という空ファイルができる

黙って増えるため気づきにくい。納品フォルダに混ざる前にここで落とす。

見るものは2つある。

1. **空ファイル** … 上のとおり。中身がないので害は少ないが、納品物に混ざる。
2. **コマンド名と同じ名前のファイル** … こちらは実害が出る。
   Windows の `where python` は**カレントフォルダを最初に見る**ため、
   `python` という名前のファイルがあると、それを Python 本体だと誤認する。
   これを使ってツールを探す仕組み（gcloud など）が起動しなくなる。
   **中身があっても起きる**ので、空ファイル検査だけでは捕まらない。

    python _scripts/check_stray_files.py [対象フォルダ]

★予防策：複数行のコードをシェルの引数として渡さない。
  ファイルに書いてから `python そのファイル.py` で実行する。
"""
from __future__ import annotations

import os
import sys

# 中身が空でも意味を持つファイル（作ってよいもの）
ALLOW_NAMES = {".gitkeep", ".gitignore", "__init__.py", ".nojekyll"}
ALLOW_EXT = (".md", ".txt", ".py", ".json", ".ps1", ".gs", ".csv",
             ".pptx", ".xlsx", ".png", ".jpg", ".yml", ".yaml")
SKIP_DIRS = {".git", "__pycache__", "node_modules", ".venv", "venv"}

# 拡張子なしでこの名前のファイルがあると、コマンド探索がそちらを拾う。
COMMAND_NAMES = {
    "python", "python3", "py", "pip", "pipx",
    "pwsh", "powershell", "cmd", "bash", "sh", "zsh",
    "node", "npm", "npx", "yarn", "deno",
    "git", "gh", "gcloud", "gsutil", "bq", "aws", "az",
    "docker", "kubectl", "make", "cargo", "go", "java", "ruby", "perl",
    "curl", "wget", "code", "where", "which", "dotnet",
}


def find(root: str) -> tuple[list[str], list[str]]:
    """(空ファイル, コマンド名と同じ名前のファイル) を返す。"""
    empty, shadow = [], []
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in files:
            p = os.path.join(cur, n)
            rel = os.path.relpath(p, root)

            # コマンド名と同じ名前は、大きさに関係なく報告する
            if n.lower() in COMMAND_NAMES:
                shadow.append(rel)
                continue

            try:
                if os.path.getsize(p) != 0:
                    continue
            except OSError:
                continue
            if n in ALLOW_NAMES or n.lower().endswith(ALLOW_EXT):
                continue
            empty.append(rel)
    return sorted(empty), sorted(shadow)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    empty, shadow = find(root)

    if not empty and not shadow:
        print("ごみファイルは見つかりませんでした。")
        return 0

    if shadow:
        print(f"コマンド名と同じ名前のファイルが {len(shadow)} 件あります。")
        print("これは実害が出ます。`where python` などがカレントフォルダを")
        print("先に見るため、ツールの起動に失敗します。")
        for h in shadow:
            print("   ", h)
        print()

    if empty:
        print(f"空ファイルが {len(empty)} 件あります。"
              "シェルのリダイレクトで作られた可能性があります。")
        for h in empty:
            print("   ", h)
        print()

    print("中身を確認し、不要であれば削除してください。")
    print("再発防止：複数行のコードはファイルに書いてから実行してください"
          "（コード中の > がリダイレクトとして解釈されます）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
