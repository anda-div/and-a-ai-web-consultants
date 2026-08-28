# Clarityヒートマップを位置ずれなくキャプチャする

JOB 03の補助手順。ヒートマップ画像を証拠として使うには、
**熱の位置と画面要素の位置が一致していること**が前提になる。
ここがずれた画像は所見の根拠にならない。

## 1. なぜずれるのか

Clarityのヒートマップ表示は、ページのスクリーンショットの上に熱のレイヤーを重ねて描いている。
表示領域の外にある部分は、スクロールして描画されるまで熱が確定しない。

そのため、次の方法ではずれや欠けが起きやすい。

| 方法 | 起きること |
|---|---|
| 画面の一括ダウンロード | 表示領域外の熱が反映されず、位置が合わない |
| ブラウザの全画面キャプチャ拡張 | 重ねレイヤーが追従せず、熱だけが固定される |
| マウスホイールでのスクロール＋画面キャプチャ | ホバーでツールチップが出て画面に写り込む。スクロール量が一定にならない |

## 2. 解決の考え方

ヒートマップ表示領域は `#heatmapVisual` という**独立したスクロールコンテナ**である。

- `scrollHeight` はキャプチャ対象ページの全高（CSS px）
- `clientHeight` は1画面分の高さ
- **`scrollTop` を書き換えると、ページ画像と熱のレイヤーが同期して動く**

つまり、マウスを一切使わずに `scrollTop` を段階的に進めれば、
どの位置でも熱と画面が一致した状態でキャプチャできる。
さらに `scrollTop` の実測値が分かるので、**結合位置を計算で決められる**
（画像差分で重なりを探す必要がない）。

```js
const c = document.getElementById('heatmapVisual');
c.scrollHeight;      // 例: 7626  … ページ全高
c.clientHeight;      // 例: 1128  … 1画面分
c.scrollTop = 900;   // 熱とページが一緒に動く
```

## 3. 手順

`scripts/clarity_heatmap_capture.py` がこの手順を自動化する。

### 初回のみ：サインイン

```bash
python -m pip install -r requirements.txt
python -m playwright install chromium
python scripts/clarity_heatmap_capture.py --login
```

ブラウザが開くのでClarityにサインインし、ターミナルで Enter を押す。
認証情報は `--profile` のフォルダ（既定 `.clarity_profile`）に保存され、次回以降は再利用される。

**このフォルダは認証情報を含む。Gitに追加しないこと**（`.gitignore` に登録済み）。

### キャプチャ

```bash
# 絞り込み前・タップ
python scripts/clarity_heatmap_capture.py \
    --project <projectId> \
    --page-url https://example.com/category/shoes/ \
    --type tap --device Mobile \
    --out output/shoes_tap

# 絞り込み後・スクロール
python scripts/clarity_heatmap_capture.py \
    --project <projectId> \
    --page-url https://example.com/category/shoes/ \
    --url-match "https://example.com/category/shoes/?stock=in&facet%5B%5D=round" \
    --op exact \
    --type scroll --device Mobile \
    --out output/shoes_filtered_scroll
```

出力:

```
output/shoes_tap/
├── tiles/tile_000.png …        分割キャプチャ（原本を残す）
├── heatmap_tap_joined.png      結合画像
└── capture_meta.json           URL・期間・デバイス・ページ全高・各タイルのscrollTop
```

`capture_meta.json` があれば、その画像がどの条件で撮られたかを後から証明できる。
JOB.md Step 1 の画像台帳にはこのファイルの内容を転記する。

### 主なオプション

| オプション | 既定 | 用途 |
|---|---|---|
| `--type` | `tap` | `tap` / `scroll` |
| `--device` | `Mobile` | `Mobile` / `Desktop` / `Tablet`。PCとSPを混ぜない |
| `--date` | `Last 30 days` | UIの選択肢と同じ文字列 |
| `--op` | `exact` | URL照合。`exact` / `contains` / `endswith` / `exclude` |
| `--overlap` | `40` | タイル間の重なり（CSS px）。固定ヘッダーがある場合は増やす |
| `--tile-delay` | `1.2` | 1タイルごとの待機秒。熱の描画が追いつかない場合は増やす |
| `--settle` | `8.0` | 初回描画の待機秒 |
| `--channel` | なし | `chrome` を指定するとインストール済みChromeを使う |

## 4. 検証済みの範囲

| 項目 | 状態 |
|---|---|
| `#heatmapVisual` がスクロールコンテナであり `scrollHeight` がページ全高になること | 実機で確認 |
| `scrollTop` の書き換えで**ページ画像と熱が同期して動く**こと | 実機で確認 |
| URLパラメータだけで期間・デバイス・種別・対象URLの状態を再現できること | 実機で確認 |
| URL照合値の二重エンコード処理、結合位置の計算、引数検証 | 単体テストで確認 |
| サインイン済みプロファイルでの通し実行 | **未確認。初回は手元で1度通してから運用に乗せる** |

`#heatmapVisual` のidが変わった場合は、スクリプトが
「スクロール可能でclientHeightが大きい要素」を自動で探すフォールバックに切り替わる。
それでも見つからない場合はエラーで止まる。

## 5. 既存ツールとの使い分け

| ツール | 方式 | 向いている場面 |
|---|---|---|
| `clarity_heatmap_capture.py` | ブラウザ自動化。`scrollTop` を直接制御 | 毎月同じ条件で撮り直す。複数の状態を機械的に並べる |
| `clarity_auto_capture_v2.py` | 画面キャプチャ。キーボードでスクロール | 自動化が通らない画面。ブラウザ拡張や別ツールの画面も撮れる |
| `concat_captures.py` | 画像の重なり検出で結合 | 撮影済みの連番画像を後から結合する |

`clarity_heatmap_capture.py` は結合位置を `scrollTop` から計算するため、
`concat_captures.py` の重なり検出は不要。手元にある連番画像を結合する場合は従来どおり使う。

## 6. 画像を所見にするときの注意

画像が揃っても、色の濃さだけで意図や不満を断定しない（`AGENTS.md`）。

- 熱の位置と画面要素の対応を、**要素名または画面領域の言葉**で記述する
- 期間・デバイス・サンプル数（ページビュー数）を必ず併記する
- 「押されている」ことと「押したかった」ことは別。仮説として分けて書く
- 数値で語れる部分は画像判読ではなく実数を使う → [CLARITY_METRICS.md](CLARITY_METRICS.md)

## 参照

- 実数での取得は [CLARITY_METRICS.md](CLARITY_METRICS.md)
- [JOB.md](JOB.md) Step 1（画像台帳）・Step 2（画像整形）
- [shared/QUALITY_POLICY.md](../../shared/QUALITY_POLICY.md)
