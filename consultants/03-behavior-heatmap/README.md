# JOB 03｜行動・ヒートマップ分析

![行動・ヒートマップ分析コンサルタント](assets/character.png)

Microsoft Clarity または Ptengine のヒートマップとページキャプチャから、利用者の行動上の摩擦を探すAIです。ヒートマップだけで心理を断定せず、画面構造とGA4の変化を組み合わせます。

## このJOBが行うこと

- Clarity連番キャプチャの結合
- ヒートマップの位置ずれのないキャプチャ（**Clarity / Ptengine の両方**）
- Clarityヒートマップの実数化（要素別クリック配分・スクロール到達率）
- PC/SPページの再現可能なキャプチャ
- クリック集中、無反応クリック、到達不足、導線競合の記録
- 証拠画像と所見の台帳化

> ### データの取得は `shared/` にあります
>
> このJOBの `scripts/` はヒートマップと画面の**キャプチャ**を行うものです。**GA4・Search Console からのデータ取得は
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
| [CLARITY_CAPTURE.md](CLARITY_CAPTURE.md) | **Clarity**のヒートマップを位置ずれなくキャプチャする。熱とページ画像を同期させて分割撮影・結合する。1ページ4枚が約2分で揃う |
| [PTENGINE_CAPTURE.md](PTENGINE_CAPTURE.md) | **Ptengine**のヒートマップを位置ずれなくキャプチャする。状態がURLに載らないため、UIを操作して作った状態を読み戻して確かめてから撮る |

## セットアップ

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
```

初回のみサインインする（ブラウザが開く。閉じたら完了。キー入力は不要）:

```bash
python scripts/clarity_heatmap_capture.py --login
```

1ページ分（PC・SP × クリック・スクロールの4枚）をまとめて撮る。**約2分・見守り不要**:

```bash
python scripts/clarity_capture_set.py \
    --project <projectId> \
    --page-url https://example.com/category/shoes/ \
    --name shoes
```

1枚だけ撮り直す:

```bash
python scripts/clarity_heatmap_capture.py \
    --project <projectId> \
    --page-url https://example.com/category/shoes/ \
    --type tap --device Mobile \
    --out output/shoes_tap
```

### Ptengineの場合

やることは同じで、**状態の作り方だけが違います。** Ptengineは期間・デバイス・種別が
URLに載らないため、UIを操作して作った状態を**画面から読み戻して確かめてから**撮ります。

```bash
python scripts/ptengine_heatmap_capture.py --login          # 初回のみ

python scripts/ptengine_capture_set.py \
    --sid <ワークスペースID> \
    --page-url https://example.com/lp/a.html \
    --name lp_a --date 2026-08
```

種別は クリック / 滞在 / 離脱 / コンバージョン の4つです。
期間は暦月で指定します。**プリセット（先月・今月）には読み替えません。**
実行した日に依存するため、月末の深夜に始めた取得が日付をまたぐとずれるからです。
**遡れるのは約12か月まで**で、それより古い月はPtengine側で選べません。

詳細と、実機で分かった19の落とし穴は [PTENGINE_CAPTURE.md](PTENGINE_CAPTURE.md) にあります。

> **Ptengineは下敷きが実サイトです。** Clarityは保存済みのスクリーンショットに
> 熱を重ねますが、Ptengineは撮影時点のページを読み込みます。
> **サイト改修があった月は、過去の熱が現在のページに乗ります。**
> 撮影時点のページ全高を記録に残すので、前月と見比べてください。

### ツールの使い分け

| | Clarity | Ptengine |
|---|---|---|
| 状態の指定 | URLで完全に再現できる | UIを操作し、読み戻して確かめる |
| 下敷き | 保存済みのスクリーンショット（凍結） | 実サイト（撮影時点） |
| 種別 | タップ / スクロール | クリック / 滞在 / 離脱 / コンバージョン |
| 実数 | `clarity_metrics_extract.js` | GraphQL（未実装。画像を先に整えています） |

結合・余白落とし・貼り付く要素の判定は `scripts/heatmap_image.py` で**共用**しています。
片方で見つけた改善が、もう片方にも届きます。

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
