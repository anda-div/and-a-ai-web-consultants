# 既存の案件を、PCからの直接取得へ移す手順

GAS や管理画面からの書き出しで回している案件を、この PC から直接取得する方式へ移す。
**上から順に実行すれば終わる**ように書いてある。

いちばん大事なのは最後の検証で、そこを飛ばすと**数値が静かに変わる**。
月次レポートは積み上がるものなので、途中で基準が変わると過去の記録が使えなくなる。

---

## 0. 前提の確認（5分）

### 認証は案件ごとではなく、PCごと

OAuth クライアントは当社のもので、案件ごとに作る必要はない。
必要なのは「サインインするアカウントが、そのプロパティを見られること」だけ。

```bash
python shared/scripts/ga4_client.py
```

`認証情報: 見つかりました` と出れば、この PC では設定済み。
出なければ [GA4_LOCAL_FETCH.md](GA4_LOCAL_FETCH.md) の手順を1回だけ行う。

### 対象のプロパティに手が届くか

移植先の GA4 プロパティIDで、1本だけ問い合わせて確かめる。

```python
import sys; sys.path.insert(0, "shared/scripts")
import ga4_client as G
api = G.GA4("<プロパティID>")
print(api.totals("2026-07-01", "2026-07-31", ["sessions"]))
```

数字が返れば、その案件は**GCPの作業なしで着手できる**。
`PermissionDenied` なら、そのアカウントをGA4のプロパティに招待してもらう。

### ごみファイルを先に片付ける

```bash
python consultants/07-report-validation/scripts/check_stray_files.py <案件フォルダ>
```

シェルのリダイレクト事故でできたファイルが混ざっていることがある。
`python` のようなコマンド名のファイルがあると、`where` がそれを拾って
**ツールが起動しなくなる**。中身があっても起きる。

---

## 1. いまの出力を、動かせない基準として保存する（10分）

**移植の前に、現行方式の出力を必ず1〜2か月分確保する。**
これが無いと、正しく移せたかを確かめる方法がなくなる。

- GAS 方式なら、最後に実行した xlsx をそのまま退避する
- 管理画面からの書き出しなら、**2か月分を先に書き出しておいてもらう**

比較対象は多いほどよい。1か月分しかない場合の代替は
[GA4_LOCAL_FETCH.md](GA4_LOCAL_FETCH.md) の「過去1か月分しか残っていないとき」を見る。

---

## 2. いまの GAS を読み、取得の定義に写す（本体）

ここが作業の中心で、**ここだけは案件ごとに違う**。

### 何を写すのか

| GAS 側 | 写す先 |
|---|---|
| シートの名前と並び | `write_xlsx` に渡す辞書の順 |
| 列見出し | 各シートの1行目 |
| 指標・ディメンション | `api.report(...)` の引数 |
| 並び順（`orderBys`） | `order_metric` / `order_dim` |
| 取得件数の上限 | `limit` |
| 丸め方 | `G.to_int` / `G.round1` / `G.pct` |
| **業務ルール** | **自分で書く。ここが抜けやすい** |

### 業務ルールを見落とさない

指標をそろえただけでは足りない案件がある。実例：

```js
// キャンペーン名の読み替えと名寄せ（ある案件の GAS より）
CAMPAIGN_ALIAS_TO_SB = ['google_p-max', 'meta_rt', 'meta_asc'];
CAMPAIGN_CANONICAL   = { 'google_p-max': 'google_pmax_cpn', ... };
```

この案件では、**広告経由の6割が読み替え対象の名称**だった。
写し損ねても合計は動かないのに、広告別の内訳だけが変わる。
GAS の中の定数・条件分岐・置換は、**1つ残らず洗い出してから**書き始める。

### 絞り込み条件の写し方

GAS は素のJSONで書く。Python は型で書く。**同じ形で書ける部品**を用意してあるので、
入れ子の構造をそのまま写せる。

| GAS | 共通部品 |
| --- | --- |
| `{ filter: { stringFilter: { matchType: 'EXACT', value: v } } }` | `G.f_exact(field, v)` |
| `matchType: 'CONTAINS'` | `G.f_contains(field, v)` |
| `matchType: 'BEGINS_WITH'` | `G.f_begins(field, v)` |
| `matchType: 'FULL_REGEXP'` | `G.f_regex(field, pattern)` |
| `inListFilter: { values: [...] }` | `G.f_in(field, [...])` |
| `{ andGroup: { expressions: [A, B] } }` | `G.f_and(A, B)` |
| `{ orGroup: { expressions: [A, B] } }` | `G.f_or(A, B)` |
| `{ notExpression: A }` | `G.f_not(A)` |

```python
# GAS 側
#   const AD_MEDIA_REGEX = '.*banner.*|.*cpc.*|.*paid.*|.*display.*|.*video.*';
#   function segmentFilter_Ad_SB() {
#     return { andGroup: { expressions: [ mediumIsAd(), campaignIsSB() ] } }; }
ad  = G.f_regex("sessionMedium", ".*banner.*|.*cpc.*|.*paid.*|.*display.*|.*video.*")
cpn = G.f_or(G.f_contains("sessionCampaignName", "_cpn"),
             G.f_in("sessionCampaignName", ["google_p-max", "meta_rt"]))
ad_sb = G.f_and(ad, cpn)
```

**正規表現は GAS の綴りをそのまま持ってくる。** `FULL_REGEXP` は全体一致なので、
`.*` を省くと結果が変わる。

### 書き方

案件フォルダに `fetch_ga4.py` を置き、共通部品を読み込む。

```python
import sys, os
sys.path.insert(0, r"<リポジトリ>\shared\scripts")
import ga4_client as G

def sheet_channel(api, cur):
    rows = api.report(*cur, ["sessionDefaultChannelGroup"],
                      ["sessions", "totalUsers", "bounceRate"],
                      order_metric="sessions")
    out = [["チャネル", "セッション", "ユーザー数", "直帰率(%)"]]
    for r in rows:
        out.append([G.dim(r, 0), G.to_int(G.met(r, 0)),
                    G.to_int(G.met(r, 1)), G.pct(G.met(r, 2))])
    return out
```

プロパティID・対象期間・イベント名は、コードではなく Config に置く。
案件ごとに違うのはそこだけなので、書き換える場所を1か所にまとめる。

---

## 3. 突き合わせる（合否はここで決まる）

```bash
python shared/scripts/compare_xlsx.py 旧.xlsx 新.xlsx
```

**差 0 になるまで切り替えない。**

### よく出る差と、その正体

| 症状 | 正体 |
|---|---|
| 小数第1位だけ 0.1 違う | 丸め方。`G.round1` を使っているか（JavaScript は 0.5 を切り上げ、Python は偶数側へ倒す） |
| 日本語URLが `%E3%81%8A...` | 復号していない。`urllib.parse.unquote` を通す |
| 値は同じで行の順が違う | 並び順。同数のときの第2・第3キーまで合わせる |
| 国名・デバイス名が違う | 表記。APIは識別子、管理画面は日本語 |
| 行数が違う | 取得件数の上限、または絞り込み条件 |

合計が合っていても安心しない。**合計が合うからこそ気づきにくい。**

---

## 4. 切り替えの条件（5つとも満たすこと）

1. 1か月分がセル単位で完全一致すること
2. 別の月でも一致すること
3. 一時的な通信エラーから自力で回復すること（共通部品が待ち直す）
4. 認証が切れたときの戻し方が手順書に書けること
5. セキュリティソフトの検査下でも動き、その手順が書けること

**「何か月動かしたか」で決めない。** 確かめるべきことが確かめられたかで決める。
期間はお客様を待たせる理由にならない。

### 従来の方法を残す

切り替えたあとも、しばらくは GAS や管理画面からの書き出しができる状態にしておく。
新しい仕組みが止まった月に、戻る先が必要になる。

---

## 5. ヒートマップを使っている案件

[consultants/03-behavior-heatmap/CLARITY_CAPTURE.md](../consultants/03-behavior-heatmap/CLARITY_CAPTURE.md) を見る。

```bash
python consultants/03-behavior-heatmap/scripts/clarity_heatmap_capture.py --login
python consultants/03-behavior-heatmap/scripts/clarity_capture_set.py \
    --project <projectId> --page-url <URL> --name <出力名>
```

1ページ分（PC・SP × クリック・スクロールの4枚）が約2分で揃う。見守りは要らない。

**既に手作業で撮っている案件では、出力名を既存の規則に合わせる。**
`--name H01_top` とすれば `H01_top_pc_click.png` のように出るので、
後工程を変えずに差し替えられる。

デバイス指定は名前から想像すると逆になる（`0`=スマートフォン / `2`=PC）。
`--device Desktop` と書けば正しく解決される。

---

## つまずいたら

| 症状 | 見る場所 |
|---|---|
| 証明書のエラーで止まる | [TLS_INSPECTION.md](TLS_INSPECTION.md) |
| 「このアプリはブロックされます」 | [GA4_LOCAL_FETCH.md](GA4_LOCAL_FETCH.md) 1章 |
| Search Console も自動化したい | [SEARCH_CONSOLE_LOCAL_FETCH.md](SEARCH_CONSOLE_LOCAL_FETCH.md) |
| ヒートマップの継ぎ目・ずれ | [CLARITY_CAPTURE.md](../consultants/03-behavior-heatmap/CLARITY_CAPTURE.md) 4章 |
