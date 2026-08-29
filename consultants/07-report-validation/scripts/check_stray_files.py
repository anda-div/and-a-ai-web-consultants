# -*- coding: utf-8 -*-
"""紛れ込んだ空ファイルを見つける（納品前チェック用）

シェル経由で複数行のコードを渡すと、コード中の `>`（比較演算子、f文字列の
桁揃え `{i:>3}`、正規表現の `[^>]*>` など）が出力リダイレクトとして解釈され、
直後の語をファイル名とする0バイトのファイルが作られることがある。

    if i > 12:        →  「12」という空ファイルができる
    f"{i:>3}"         →  「3}」という空ファイルができる

黙って増えるため気づきにくい。納品フォルダに混ざる前にここで落とす。

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


def find(root: str) -> list[str]:
    hits = []
    for cur, dirs, files in os.walk(root):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for n in files:
            p = os.path.join(cur, n)
            try:
                if os.path.getsize(p) != 0:
                    continue
            except OSError:
                continue
            if n in ALLOW_NAMES or n.lower().endswith(ALLOW_EXT):
                continue
            hits.append(os.path.relpath(p, root))
    return sorted(hits)


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    root = sys.argv[1] if len(sys.argv) > 1 else "."
    hits = find(root)
    if not hits:
        print("空ファイルは見つかりませんでした。")
        return 0
    print(f"空ファイルが {len(hits)} 件あります。"
          "シェルのリダイレクトで作られた可能性があります。")
    for h in hits:
        print("   ", h)
    print("\n中身を確認し、不要であれば削除してください。")
    print("再発防止：複数行のコードはファイルに書いてから実行してください"
          "（コード中の > がリダイレクトとして解釈されます）。")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
