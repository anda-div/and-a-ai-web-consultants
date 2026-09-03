# JOB 06｜UX/UI改善設計

![UX/UI改善設計コンサルタント](assets/character.png)

優先課題を、実装・検証できる改善案へ変換するAIです。一般論の「分かりやすくする」で終わらず、対象画面、変更内容、状態、文言、計測、受入条件まで具体化します。

## このJOBが行うこと

- 課題から複数の改善案を発想
- 実装制約を踏まえた施策選定
- PC/SPのワイヤーフレーム仕様
- 文言・状態・エラー・例外の設計
- A/BテストまたはBefore/After検証計画

> ### データの取得は `shared/` にあります
>
> このJOBの `scripts/` は優先課題から**改善施策の仕様**を組み立てるものです。**GA4・Search Console からのデータ取得は
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

- JOB 05の `prioritized_issues.json`
- 現行画面キャプチャ、ブランド・法務・システム制約

## 出力

- 改善提案カード
- ワイヤーフレーム仕様書
- 実装受入条件
- JOB 07へ渡す `actions.json`

## 実行例

```bash
python scripts/build_action_specs.py --issues input/prioritized_issues.json --out output
```

CLI AIへの最初の依頼例:

> JOB 06として、上位課題を実装可能な改善案へ変換してください。PC/SP、状態変化、文言、計測イベント、受入条件まで書き、各案に元の課題IDを残してください。

[7人の一覧へ戻る](../../README.md)
