# JOB 05｜課題診断・優先順位

![課題診断・優先順位コンサルタント](assets/character.png)

JOB 01〜04の所見を束ね、重複を除き、「何から着手するか」を決めるAIです。声の大きさや思いつきではなく、証拠、影響、工数、リスク、確度で課題を並べます。

## このJOBが行うこと

- 複数JOBの所見統合と重複排除
- 症状・原因・制約の分離
- 証拠強度、影響、工数、リスク、確度の採点
- 今月着手／次月検証／継続観測の分類
- 毎月3〜5件の実行可能な改善テーマの選定

> ### データの取得は `shared/` にあります
>
> このJOBの `scripts/` は他JOBの**所見を統合**して優先順位を付けるものです。**GA4・Search Console からのデータ取得は
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

- JOB 01〜04の `findings.json` またはCSV
- 事業KPI、実装制約、予算、期限

## 出力

- 優先課題台帳
- 上位課題の診断カード
- JOB 06へ渡す `prioritized_issues.json`

## 実行例

```bash
python scripts/prioritize_findings.py --input examples/findings.json --config project_config.example.json --out output
```

CLI AIへの最初の依頼例:

> JOB 05として、inputの所見を統合してください。症状と原因を分け、証拠・影響・工数・リスク・確度で採点し、今月着手する3〜5件を選んでください。

[7人の一覧へ戻る](../../README.md)
