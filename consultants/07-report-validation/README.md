# JOB 07｜レポート・効果検証

![レポート・効果検証コンサルタント](assets/character.png)

7人の成果を、意思決定しやすいレポートへまとめ、納品前の独立QAと施策後のBefore/After検証を行うAIです。制作とチェックを分離し、数字・根拠・体裁を追跡します。

## このJOBが行うこと

- 課題・施策・根拠のレポート構成
- PowerPointからの全文・数値抽出
- 全スライドのレンダリング確認
- 数値トレーサビリティと回帰チェック
- Before/Afterの効果検証と次の一手

## 入力

- JOB 01〜06の成果物
- PPTXテンプレートまたは既存レポート
- 効果検証用の前後データ

## 出力

- PPTXまたはレポート原稿
- 納品前チェック報告
- 効果検証報告
- 次月の継続観測項目

## 実行例

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/render_slides.ps1 -PptxPath input/report.pptx -OutDir output/slides
python scripts/extract_pptx.py input/report.pptx output/extract
python scripts/compare_periods.py --before input/before.csv --after input/after.csv --out output/effect.md
```

CLI AIへの最初の依頼例:

> JOB 07として、各JOBの成果を課題ID・施策ID・根拠が追えるレポートにまとめてください。生成後は独立チェックに切り替え、修正前に指摘報告を出してください。

[7人の一覧へ戻る](../../README.md)
