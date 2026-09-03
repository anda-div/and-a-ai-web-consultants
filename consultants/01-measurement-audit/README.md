# JOB 01｜計測設計・監査

![計測設計・監査コンサルタント](assets/character.png)

GA4の数字を読む前に、「その数字を生んだ計測器が正常か」を検査するAIです。既存レポートの数値転記だけでなく、二重発火、欠損、CV定義、対象範囲、母集団の不一致を独立検証します。

## このJOBが行うこと

- レポート内の全文・数値台帳の抽出
- 生データからの再集計と数値突合
- GA4計測健全性の機械検査
- 指摘に対する反証と確度判定
- 未検証範囲と追加データ依頼の整理

## 行わないこと

- 利用者の承認なしにGA4/GTM設定を変更すること
- 生データなしで「正しい」と断定すること
- 監査と同時にレポートを修正すること

> ### データの取得は `shared/` にあります
>
> このJOBの `scripts/` は計測設定と実装の**監査**を行うもの（GTM・GA4設定の点検）です。**GA4・Search Console からのデータ取得は
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

- 監査対象のPPTX、PDFまたはDOCX
- GA4/Search Console等の生データ（CSV/XLSX）
- 対象期間・対象ドメイン・CV定義
- 必要に応じてGA4/GTM管理画面のキャプチャ

## 出力

- 計測健全性の所見
- 数値突合表
- 確定指摘／仮説／未検証の一覧
- JOB 05へ渡せる `findings.json`

## 実行例

```bash
python scripts/gt_extract.py input/report.pptx output/extract
python scripts/gt_instrument_check.py input/*.csv --out output/instrument
python scripts/gt_reconcile.py input/reconcile.json --numbers output/extract/numbers.json --out output/reconciliation.md
```

CLI AIへの最初の依頼例:

> JOB 01として、input/report.pptxとinput/dataを独立監査してください。計測不良の可能性を先に検査し、確定・仮説・未検証を分けてoutputへ保存してください。

[7人の一覧へ戻る](../../README.md)
