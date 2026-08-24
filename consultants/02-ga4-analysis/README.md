# JOB 02｜GA4データ解析

![GA4データ解析コンサルタント](assets/character.png)

GA4のエクスポートを、意思決定に使えるKPI・セグメント・変化点へ変換するAIです。単なる増減一覧ではなく、「何が変わり、どこを追加確認すべきか」を整理します。

## このJOBが行うこと

- GASによる月次データ取得
- CSVの読み込みと標準化
- KPI、チャネル、ランディングページ、デバイス、イベント分析
- 前期比較・構成比・寄与度の計算
- 異常値と追加取得候補の提示

## 入力

- `project_config.json`
- GA4のCSV、またはGAS出力をCSV保存したもの
- 完全に終了した対象期間と比較期間

## 出力

- `analysis.json`
- `analysis.md`
- JOB 05へ渡す `findings.json`

## 実行例

```bash
python scripts/analyze_ga4.py --input examples/ga4_export.csv --out output
```

GASを使う場合は `gas/ga4_monthly_export.gs` の設定ブロックだけを編集し、Google Apps Script上で実行します。実際のIDをGitへコミットしないでください。

CLI AIへの最初の依頼例:

> JOB 02として、inputのGA4データを対象月と前月で比較してください。増減だけでなく寄与度とセグメント差を計算し、追加確認が必要な点を分けてください。

[7人の一覧へ戻る](../../README.md)
