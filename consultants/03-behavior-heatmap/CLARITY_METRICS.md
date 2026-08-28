# Clarityヒートマップを「画像」ではなく「実数」で取る

JOB 03の補助手順。Microsoft Clarityのヒートマップは、画面を読み取らずにURLで状態を指定し、
画面上の集計値をそのまま数値で取り出せる。要素別クリック数とスクロール到達率が表になるため、
「どのUI要素が何%押されているか」を目視ではなく実数で比較できる。

画像判読は面積と色でしか語れない。実数化すると、同じ画面の中で
「絞り込みUIとカードのどちらが押されているか」のような配分の議論ができる。

## 1. 状態はURLで指定する

ヒートマップ画面の状態はすべてクエリパラメータに載る。UIを操作せずURLを組み立てれば、
同じ条件を何度でも再現できる。

```
https://clarity.microsoft.com/projects/view/<projectId>/heatmaps
  ?date=Last%2030%20days
  &Device=Mobile
  &heatmapType=0
  &heatmapDeviceType=0
  &url=<スクリーンショット対象ページのURL>
  &URL=2;<op>;<value>
```

| パラメータ | 意味 |
|---|---|
| `date` | 期間。`Last 30 days` 等。UIの選択肢と同じ文字列 |
| `Device` | `Mobile` / `Desktop` / `Tablet`。PCとSPを混ぜないために必ず指定する |
| `heatmapType` | `0`=タップ（クリック）、`1`=スクロール |
| `heatmapDeviceType` | 表示するデバイス枠 |
| `url` | ヒートマップの下敷きにするページのURL |
| `URL` | 集計対象ページの照合条件。`<group>;<op>;<value>` |

`URL` の `op`:

| op | 照合 |
|---|---|
| `1` | 次の値で終わる |
| `2` | を含む |
| `3` | 除外 |
| `4` | 完全一致 |

### 絞り込み後の状態だけを見る

クエリパラメータで絞り込みを実装しているサイトでは、`op=4`（完全一致）に
絞り込み後のURLをそのまま渡すと、その状態のヒートマップだけが得られる。

```
# 絞り込み前
URL=2;4;https://example.com/category/shoes/

# 絞り込み後（1つの選択肢）
URL=2;4;https://example.com/category/shoes/?stock=in&facet%5B%5D=round

# 絞り込み後（すべての選択肢をまとめて）
URL=2;2;/category/shoes/?stock=in
```

**`URL` の値は二重エンコードになる。** 対象URLに `%E3%83%A9` のようなエンコード済み文字が
含まれる場合、外側のクエリに載せるときに `%` をさらに `%25` にする
（`%E3%83%A9` → `%25E3%2583%25A9`）。ここを間違えると
「スクロール情報が見つかりませんでした」になるだけで、エラーにはならないので気づきにくい。
URLはスクリプトで組み立てる。

## 2. 数値の取り出し

`scripts/clarity_metrics_extract.js` を、ヒートマップ画面を開いた状態でブラウザの
コンソール（またはブラウザ自動化のJS実行）に貼ると、JSONが返る。

```js
// heatmapType=0（タップ）のとき
{
  "mode": "tap",
  "elementCount": 120,
  "totalClicks": 2000,
  "rows": [
    { "selector": "DIV.facet-icon[1]>IMG[1]",  "clicks": 200, "pct": 10.0 },
    { "selector": "DIV.facet-label[1]",        "clicks": 120, "pct": 6.0 },
    { "selector": "FIGURE.card-img[1]>IMG[1]", "clicks": 20,  "pct": 1.0 }
  ],
  "groups": { "facet": 800, "card": 100, "pager": 60, "masked": 500 }
}

// heatmapType=1（スクロール）のとき
{
  "mode": "scroll",
  "pageViews": 1200,
  "depth": [
    { "pct": 5,  "visitors": 1200, "reach": 100.0, "dropoff": 0.0 },
    { "pct": 10, "visitors": 1080, "reach": 90.0,  "dropoff": 10.0 }
  ]
}
```

### 要素をグループに束ねる

Clarityは要素を1つずつ並べるため、カードが30枚あればカードのクリックは30行に分散する。
そのまま順位を見ると「フィルタが1位、カードは圏外」に見えてしまう。
**CSSセレクタでグループに束ねてから合計する。**

スクリプトの `GROUPS` を対象サイトに合わせて書き換える。

```js
const GROUPS = {
  facet: /facet|refine|js_facet_item/,   // 絞り込みUI
  card:  /card-img|item-figure/,         // 商品カード
  pager: /pager|pagination/,             // ページ送り
};
```

### 割合ではなく「1ページビューあたり」で比較する

状態が違うページを比べるときは、総クリック数に対する割合だけでは足りない。
マスク要素の量が状態によって変わるため、分母がずれる。

```
1ページビューあたりのタップ回数 = グループのクリック数 ÷ ページビュー数
```

ページビュー数は `heatmapType=1`（スクロール）側に出る。
タップとスクロールを同じ条件で2回取り、この指標に直してから比較する。

## 3. スクロール到達率をピクセルに翻訳する

Clarityのスクロール深度は**ページ高さに対する割合**である。ページ高さは
絞り込み結果の件数などで変わるため、状態間で深度%を直接比較してはいけない。

見たい要素の到達率を出す手順:

1. Playwrightで対象状態のページを実測し、要素の `getBoundingClientRect().top + scrollY` と
   `document.documentElement.scrollHeight` を取る（`scripts/web_capture_segments.py` と同じ環境）
2. `要素の位置 ÷ ページ高さ` で深度%に換算する
3. Clarityの前後の測定点（5%刻み）で線形補間する

```
例: 一覧1件目 800px / ページ高さ 6,400px = 12.5%
    Clarity 10% → 90.0% / 15% → 80.0%
    12.5% の到達率 ≒ 90.0 − (2.5/5) × 10.0 = 85.0%
    → 一覧を1件も見ずに離脱 15.0%
```

補間値は推定値であることを所見に明記する。

## 4. 落とし穴

| 事象 | 内容 |
|---|---|
| テキストマスク | テキストを含む要素は `•••` にマスクされ、セレクタが判別できない。商品名リンクのタップはカードグループに入らないため、**カード側が過小評価**になる。画像・数値ラベルはマスクされない。どちらの向きに過小評価が働くかを所見に書く |
| 期間 | 期間はClarityのデータ保持期間に縛られる。GA4の分析期間と一致しないことを明記する |
| 母集団 | 状態別に取ると、ページビュー数が状態ごとに大きく違う。少ない状態は信頼区間が広い。ページビュー数を必ず併記する |
| UIの言語 | ランキングやスクロール表の文言が表示言語で変わる。抽出スクリプトは日本語・英語の両方に対応させてある |
| 集計の重複 | 1つのURLに複数の絞り込み値が入る場合、選択肢別の合計は状態数と一致しない。選択肢間の比較にのみ使う |

## 5. JOB 05への引き渡し

数値で取れても、それは観測事実にとどまる。心理・原因は仮説として分けて書く
（`shared/QUALITY_POLICY.md` 5節）。

```json
{
  "finding_id": "F-012",
  "fact": "絞り込み実行後の状態で、総タップの約7割が絞り込みUIに向かっている（SP・30日・1,200PV）",
  "interpretation": "利用者は1回の絞り込みで探索を終えず、条件を足していく",
  "hypothesis": "結果件数が少ないため、条件を変えて探し直している",
  "next_check": "結果件数別に同じ集計を分ける。在庫側の件数を実測する",
  "evidence": "clarity_tap_filtered.json / clarity_scroll_filtered.json"
}
```

## 参照

- 画面キャプチャとして取る場合は [CLARITY_CAPTURE.md](CLARITY_CAPTURE.md)
- [JOB.md](JOB.md) Step 3（観測）・Step 4（反証）
- [shared/QUALITY_POLICY.md](../../shared/QUALITY_POLICY.md)
