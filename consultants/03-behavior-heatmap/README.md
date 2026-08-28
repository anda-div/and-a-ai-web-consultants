# JOB 03｜行動・ヒートマップ分析

![行動・ヒートマップ分析コンサルタント](assets/character.png)

Microsoft Clarityのクリック・スクロール画像とページキャプチャから、利用者の行動上の摩擦を探すAIです。ヒートマップだけで心理を断定せず、画面構造とGA4の変化を組み合わせます。

## このJOBが行うこと

- Clarity連番キャプチャの結合
- Clarityヒートマップの位置ずれのないキャプチャ
- Clarityヒートマップの実数化（要素別クリック配分・スクロール到達率）
- PC/SPページの再現可能なキャプチャ
- クリック集中、無反応クリック、到達不足、導線競合の記録
- 証拠画像と所見の台帳化

## 入力

- PC/SP × クリック/スクロールのClarity画像
- または ClarityのプロジェクトIDと対象ページURL（画像を介さず直接取得する場合）
- 対象ページURLまたは全画面キャプチャ
- 対象期間、デバイス、サンプル数

## 出力

- 証拠画像一覧
- 要素別クリック配分・スクロール到達率のJSON
- 行動所見と反証候補
- JOB 05へ渡す `findings.json`

## 手順書

| 文書 | 内容 |
|---|---|
| [JOB.md](JOB.md) | 実行手順（画像台帳 → 観測 → 反証 → 引き渡し） |
| [CLARITY_METRICS.md](CLARITY_METRICS.md) | ヒートマップを画像ではなく実数で取る。URLで状態を指定し、要素別クリック数とスクロール到達率を数値化する |
| [CLARITY_CAPTURE.md](CLARITY_CAPTURE.md) | ヒートマップを位置ずれなくキャプチャする。熱とページ画像を同期させて分割撮影・結合する |

## セットアップ

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

Clarityヒートマップを直接取得する（初回のみサインイン）:

```bash
python scripts/clarity_heatmap_capture.py --login
python scripts/clarity_heatmap_capture.py \
    --project <projectId> \
    --page-url https://example.com/category/shoes/ \
    --type tap --device Mobile \
    --out output/shoes_tap
```

手元の連番画像やページを扱う:

```bash
python scripts/concat_captures.py input/clarity --out output/clarity_joined.png
python scripts/web_capture_segments.py --url https://example.com --name output/page
```

要素別クリック配分を数値で取る場合は、ヒートマップ画面を開いた状態で
`scripts/clarity_metrics_extract.js` をブラウザのコンソールに貼る（詳細は [CLARITY_METRICS.md](CLARITY_METRICS.md)）。

CLI AIへの最初の依頼例:

> JOB 03として、inputのPC/SPヒートマップを分析してください。観測事実と心理仮説を分け、各所見に証拠画像名と追加確認方法を付けてください。

[7人の一覧へ戻る](../../README.md)
