# JOB 04｜顧客・検索・競合調査

![顧客・検索・競合調査コンサルタント](assets/character.png)

Search Console、顧客情報、競合サイトを使い、「誰が何を探し、比較し、どこで迷うか」を整理するAIです。競合の表面的な模倣ではなく、検索意図と選択基準の違いを可視化します。

## このJOBが行うこと

- Search Console CSVのクエリ・ページ分析
- CTR改善機会と意図クラスタの抽出
- **競合の選定**（社数・カテゴリー・固定コアと入れ替え枠の設計）
- 競合ページのPC/SP比較
- 顧客仮説、比較軸、未充足ニーズの整理

## 入力

- Search ConsoleのCSV
- 自社・競合URL
- 顧客ヒアリング、FAQ、問い合わせ理由等

## 出力

- 検索意図クラスタ
- 競合比較表
- 顧客仮説とカスタマージャーニー材料
- JOB 05へ渡す `findings.json`

## 競合の選び方

競合比較はレポートで最も枚数を食う章になりやすく、生成コストを最も左右します。
一方で改善提案の質はここで決まります。判断基準を [`COMPETITOR_SELECTION.md`](COMPETITOR_SELECTION.md) にまとめました。

要点だけ挙げると次のとおりです。

- **最低3社**。下回ると「ほぼ全社が持っている」という論拠が使えなくなる
- **上限12社。推奨9社**（3カテゴリー×3社）
- **枚数を削るときは社数ではなく1社あたりを削る** … 12社×1枚と4社×3枚は同じ枚数だが、前者だけが論拠として強い
- **固定コア＋入れ替え枠**を推奨。生成開始時に利用者へ3択で尋ねる
- **キャプチャは差分方式**。FVのみ比較し、変化した競合だけ全点を取り直す
- 上限は社数ではなく**キャプチャ点数**でも持つ

## 実行例

```bash
python scripts/analyze_search_console.py --input input/search_console.csv --out output
python scripts/capture_competitors.py --urls input/competitors.txt --out output/captures
```

CLI AIへの最初の依頼例:

> JOB 04として、Search Consoleと競合URLを調査してください。検索意図、比較軸、未充足ニーズを分け、競合の優劣を断定せず証拠付きで整理してください。

[7人の一覧へ戻る](../../README.md)
