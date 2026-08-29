# JOB 07｜レポート・効果検証

![レポート・効果検証コンサルタント](assets/character.png)

7人の成果を、意思決定しやすいレポートへまとめ、納品前の独立QAと施策後のBefore/After検証を行うAIです。制作とチェックを分離し、数字・根拠・体裁を追跡します。

## このJOBが行うこと

- 課題・施策・根拠のレポート構成
- **PowerPointレポートの生成**（テンプレートの体裁を保ったまま組み立てる）
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

## レポート生成の部品

レポートの体裁は案件ごとに違います。そこで「作図の部品」と「案件固有の値」を分けています。

| ファイル | 役割 |
|---|---|
| `scripts/report_config.py` | `_config/` のJSONを読み込む。値は一切持たない |
| `scripts/deck_kit.py` | 作図部品。配色・レイアウト名・座標はすべてConfigから受け取る |
| `config.example/` | Configのひな形（架空値）。`_config` としてコピーして使う |

`deck_kit` が提供するもの:

- ページの型 … `content`（見出し＋サブタイトル）`section`（章扉）`title_slide`
- 要素 … `box`（自動高さ・余白ルール付き）`table` `chart` `summary` `note`
- 日本語の体裁 … 禁則処理、言語指定、本文の最小サイズの強制
- レイアウト補助 … 箱の高さ揃え、必要高さの見積り、収まるフォントサイズの算出
- ヒートマップ … 縦長画像の分割と横並び配置
- 品質チェック … 本文最小サイズに収まらない箱の一覧（`report_overflow`）

```python
from pptx import Presentation
from report_config import load
from deck_kit import build_kit

cfg = load()                        # 直近の親にある _config/ を探す
prs = Presentation(cfg.template())
K   = build_kit(prs, cfg)

s = K.content("流入分析", "どこから来た人が成果に近いか")
K.table(s, K.LEFT, 2.2, K.WIDTH, [["チャネル", "セッション"], ["自然検索", "1,234"]])
K.summary(s, "自然検索が最大の入口です。")
K.note(s, "出所：GA4（対象期間）")
K.report_overflow()                 # 文章を短くすべき箱を一覧表示
prs.save("output/report.pptx")
```

## 検証・効果測定の実行例

```powershell
powershell -NoProfile -ExecutionPolicy Bypass -File scripts/render_slides.ps1 -PptxPath input/report.pptx -OutDir output/slides
python scripts/extract_pptx.py input/report.pptx output/extract
python scripts/compare_periods.py --before input/before.csv --after input/after.csv --out output/effect.md
```

## 文章は毎回書き起こす

`deck_kit` が持つのは「描き方」であって「書く内容」ではありません。
本文・所見・提案は、その月のデータを見てCLI AIが書き起こします。
先月の文章を使い回さないでください（`docs/WORKFLOW.md` の「毎月の新規性」を参照）。

## 体裁のルール

- 本文は `branding.json` の `body_min_pt` を下回らない。収まらないときは
  **文字を小さくせず、文章を短くする**。`report_overflow()` が対象を一覧表示する。
- 箱の高さは見積りより常に高く作る。実表示は事前に読み切れないため、
  余白が無くなるより余白がある方が読みやすい。
- 画像は元のアスペクト比を保つ。出所のキャプションは画像と重ねず、外側に置く。

## 表・グラフ・注記が本文最小サイズの対象外である理由

表のセル、グラフの目盛・凡例、フッターの注記、画像に重ねるラベルは、
本文ではなく図の付属要素です。列数の多い比較表を本文と同じ大きさにすると
縦に収まらなくなるため、これらは対象外としています。ただし読める大きさ
（目安8pt以上）は確保してください。

CLI AIへの最初の依頼例:

> JOB 07として、各JOBの成果を課題ID・施策ID・根拠が追えるレポートにまとめてください。生成後は独立チェックに切り替え、修正前に指摘報告を出してください。

[7人の一覧へ戻る](../../README.md)
