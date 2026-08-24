# クイックスタート

## 1人だけ使う

対象JOBへ移動し、`README.md` の入力を `input/` に置きます。CLI AIをそのフォルダで起動し、README記載の依頼例を渡してください。

```bash
cd consultants/02-ga4-analysis
copy project_config.example.json project_config.json
python scripts/analyze_ga4.py --input examples/ga4_export.csv --out output
```

## 7人で使う

ルートでCLI AIを起動し、次のように依頼します。

> 7人の標準ワークフローで進めてください。まず入力一覧と計測上の注意を確認し、JOB 02〜04を並行、JOB 05〜07を順に実行してください。事実・仮説・提案を分け、すべての重要主張を所見IDから追跡可能にしてください。

## 実案件で必ず行うこと

- `examples/` は架空データです。実データで置き換えてください。
- 実データはGit管理されない `input/`、生成物は `output/` に置いてください。
- 認証情報は環境変数または利用サービスの秘密管理機能を使ってください。
- 公開・納品前にJOB 07と `python tools/public_scan.py .` を実行してください。
