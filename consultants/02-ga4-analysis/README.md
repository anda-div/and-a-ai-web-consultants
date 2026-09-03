# JOB 02｜GA4データ解析

![GA4データ解析コンサルタント](assets/character.png)

GA4のエクスポートを、意思決定に使えるKPI・セグメント・変化点へ変換するAIです。単なる増減一覧ではなく、「何が変わり、どこを追加確認すべきか」を整理します。

## このJOBが行うこと

- GASによる月次データ取得
- CSVの読み込みと標準化
- KPI、チャネル、ランディングページ、デバイス、イベント分析
- 前期比較・構成比・寄与度の計算
- 異常値と追加取得候補の提示

> ### データの取得は `shared/` にあります
>
> このJOBの `scripts/` は**取得済み**のGA4データを分析するもの（`analyze_ga4.py` は取得しません）です。**GA4・Search Console からのデータ取得は
> [`shared/scripts/ga4_client.py`](../../shared/scripts/) を使ってください。**
> ここに取得スクリプトを新しく書くと、共通部品と二重管理になります。
>
> | やりたいこと | 見る場所 |
> |---|---|
> | GA4からPythonで取得する | [`shared/GA4_LOCAL_FETCH.md`](../../shared/GA4_LOCAL_FETCH.md) |
> | Search Consoleから取得する | [`shared/SEARCH_CONSOLE_LOCAL_FETCH.md`](../../shared/SEARCH_CONSOLE_LOCAL_FETCH.md) |
> | 認証が通っているか確かめる | `python shared/scripts/ga4_client.py` |
> | 証明書エラーで止まった | [`shared/TLS_INSPECTION.md`](../../shared/TLS_INSPECTION.md) |
> | GASで回している案件を移す | [`shared/PORTING_RUNBOOK.md`](../../shared/PORTING_RUNBOOK.md) |
>
> `shared/scripts/ga4_client.py` が持つもの: 認証、ページ送り、504の待ち直し、
> トークン枠の自動待機、GASと一致する丸め、`runFunnelReport`（breakdown 対応）、
> GASのJSONと同じ形で書ける絞り込み、xlsx出力と全セル照合。

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
