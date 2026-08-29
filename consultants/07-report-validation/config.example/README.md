# config.example — Configのひな形

レポート生成は「汎用エンジン」と「Config」に分かれています。

| | 中身 | 置き場所 |
|---|---|---|
| 汎用エンジン | 作図部品、ページの型、体裁ルール、品質チェック | このリポジトリ（公開） |
| Config | 会社名、計測ID、URL、テンプレート、配色、固有名詞 | 利用者の環境（非公開） |

**このリポジトリに実案件の値をコミットしないでください。**
以下のファイルはすべて架空の値です。

## 使い方

1. このフォルダを、作業プロジェクトの直下へ `_config` という名前でコピーします。

   ```bash
   cp -r consultants/07-report-validation/config.example /path/to/your-project/_config
   ```

2. 各JSONの値を実案件のものへ書き換えます。
3. `_config/` を `.gitignore` に追加します。
4. スクリプトは `_config/` を自動で探します。パスを引数で渡す必要はありません。

   ```python
   from report_config import load
   from deck_kit import build_kit
   from pptx import Presentation

   cfg = load()                       # 直近の親にある _config/ を見つける
   prs = Presentation(cfg.template())
   K   = build_kit(prs, cfg)
   ```

## ファイル

| ファイル | 何を書くか | 更新のタイミング |
|---|---|---|
| `client.json` | 会社名、レポートに載せる制作者名 | 初期のみ |
| `analytics.json` | 計測プロパティ、タグ、セグメント判定、CV定義 | 計測を追加したとき |
| `reports.json` | 生成するレポートの定義、章立ての採否、**対象期間** | 毎月（対象期間） |
| `branding.json` | テンプレート、用紙サイズ、配色、レイアウト名、座標 | テンプレート変更時 |
| `data_sources.json` | 入力ファイルの置き場所とシート名 | データ取得方法を変えたとき |
| `glossary.example.txt` | 登場してよい／いけない固有名詞 | 案件開始時と、指摘を受けたとき |

## 注意

- `branding.json` の `layouts` と `geometry_cm` は**テンプレート固有の実測値**です。
  テンプレートを差し替えたら必ず測り直してください。座標が合っていないと、
  注記がフッターの装飾に重なるなどの崩れが起きます。
- `analytics.json` の `regex` はJSON文字列です。バックスラッシュは
  `\\.` のように二重にしてください。
