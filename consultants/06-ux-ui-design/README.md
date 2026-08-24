# JOB 06｜UX/UI改善設計

![UX/UI改善設計コンサルタント](assets/character.png)

優先課題を、実装・検証できる改善案へ変換するAIです。一般論の「分かりやすくする」で終わらず、対象画面、変更内容、状態、文言、計測、受入条件まで具体化します。

## このJOBが行うこと

- 課題から複数の改善案を発想
- 実装制約を踏まえた施策選定
- PC/SPのワイヤーフレーム仕様
- 文言・状態・エラー・例外の設計
- A/BテストまたはBefore/After検証計画

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
