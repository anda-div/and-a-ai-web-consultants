# Changelog

このプロジェクトはSemantic Versioningを参考にバージョン管理します。

## [Unreleased]

- AIウェブコンサルタント7人体制の初回公開版を準備。
- JOB 03に `CLARITY_METRICS.md` を追加。ClarityヒートマップをURLパラメータで状態指定し、要素別クリック数とスクロール到達率を実数で取得する手順を文書化。
- JOB 03に `scripts/clarity_metrics_extract.js` を追加。ヒートマップ画面から集計値をJSONで取り出す（日本語・英語UI対応）。
- JOB 03に `CLARITY_CAPTURE.md` と `scripts/clarity_heatmap_capture.py` を追加。`#heatmapVisual` の `scrollTop` を直接制御することで、熱とページ画像の位置ずれを起こさずに分割キャプチャ・結合する。
- `.gitignore` にClarity用ブラウザプロファイル（`.clarity_profile`）を追加。
- JOB 07に `scripts/deck_kit.py` を追加。PowerPointレポートの作図部品（ページの型・箱・表・グラフ・要約・注記・ヒートマップ配置・日本語の禁則処理）を、案件固有の値を持たない形でまとめた。
- JOB 07に `scripts/report_config.py` と `config.example/` を追加。会社名・計測ID・URL・テンプレート・配色・座標・固有名詞をConfigへ分離し、公開リポジトリ側には値を置かない構成にした。
- JOB 07の `README.md`・`JOB.md`・`AGENTS.md`・`CLAUDE.md` にレポート生成の手順と体裁ルール（本文の最小サイズ、収まらないときは文章を短くする）を追記。
- JOB 04に `COMPETITOR_SELECTION.md` を追加。競合の社数・カテゴリー・選び方・キャプチャの差分取得・履歴による新規性の担保・コスト上限の判断基準を明文化。枚数を削るときは社数ではなく1社あたりを削る、という基準を中心に据えた。
- JOB 07の `config.example` に `competitor` 設定と `competitor_history.json` を追加。
- JOB 07に `scripts/site_report_kit.py` を追加。ページの型6種（表2列／KPI＋グラフ／箱／キャプチャ左右／ヒートマップ／導線の図解）と、競合章の一括生成・用語集の自動分割をまとめた。
- JOB 07に `defaults/` を追加。章立て・体裁ルール・競合の方法論・ページ座標を既定値として公開側に置き、`_config/` は上書きだけを持つ形にした。`_config/` は納品後に提供者が直せないため、汎用側に寄せておくと改善を全利用者へ一斉に届けられる。
- JOB 07に `TEMPLATE_POLICY.md` を追加。テンプレートの有無と用紙比率を生成前に確定させる手順と確認文面。あわせて `scripts/inspect_template.py`（テンプレート解析）と `scripts/make_default_templates.py`（16:9 / 4:3 の既定雛形）を追加。
- `.gitignore` に pptx / xlsx / テンプレートフォルダの除外を追加。クライアント提供のテンプレートが公開リポジトリへ混入しないようにした。
- JOB 07の `site_report_kit.py` に `two_col_tables(fill=True)` と `kpi_and_chart(chart_h=...)` を追加。行数の少ない表やグラフでページ下半分が空くのを防ぐ。あわせて「ページの下半分を空けない」ルールを README・AGENTS・CLAUDE に明文化した。
- JOB 07の提案台帳に発注依頼書の出力（`--order-sheet`）と発注先の区分（`vendor`）を追加。同じ費用帯でも、文言の修正・広告の配分変更・計測の実装は渡す相手が違うため、発注先ごとに1枚ずつ出す。依頼書の末尾で反映日を尋ね、翌月の前後比較につなげる。社内向けの背景は依頼書に載せない。
- JOB 07の `check_layout.py` に制御文字の検査を追加。Windowsのパスを生の文字列にせずに書くと `` `` がエスケープとして解釈され、PowerPointで `_x000D_` と表示される。python-pptx では普通の文字列に見えるため、描画するまで気づけない。実案件でマニュアルに1件混入していたのを検出した。
- JOB 07の提案台帳に、実装を追いかけるための仕組みを追加。費用帯（外注したときの金額感で3段階）、発注指示（制作会社にそのまま渡せる文面）、保留の必須項目（何待ちか・いつ再検討するか）、打ち合わせ用の確認シート（状態を尋ねず、こちらが書いて訂正してもらう）、効く指標を「局所の比率」に統一するルール。`defaults/ledger_rules.json` に共通ルールを集約した。「コストゼロで直せます」という表現は、1文字の修正でも外注する運用が珍しくない現場では反発を招くため使わない、と明記。
- JOB 07に提案台帳の仕組みを追加。`PROPOSAL_LEDGER.md`（考え方と運用）、`scripts/ledger.py`（過去提案の照会・状態管理）、`scripts/build_briefing.py`（月初ブリーフィング）、`defaults/angles_catalog.json`（分析の切り口32本）。毎月の提案が枯渇する原因を「憶えていられない・角度が固定される・結果を確かめる前に次の月が来る」の3つに分け、それぞれを台帳・ローテーション・効果検証で埋める。照会は文字列だけでは足りないため、切り口を最も強い手がかりにする。
- JOB 07に `scripts/check_layout.py` を追加。生成したPPTXの重なり・枠外・画像のゆがみ・細すぎる画像・ページ下部の空き・本文の文字サイズを座標から測る。画像の内側に収まる注記（Before/Afterの吹き出し）と、分割して横並びにしたヒートマップは意図した表現として対象外にする。要対応があれば終了コード1を返す。実案件に適用して、これまで気づけていなかった細すぎるキャプチャ3件を検出した。
- JOB 07に `scripts/check_stray_files.py` を追加。複数行のコードをシェル経由で渡したときに `>` がリダイレクトと解釈されて生まれる0バイトのファイルを検出する。ルート `AGENTS.md`・`CLAUDE.md` に「複数行のコードをシェルの引数として渡さない」を追記。
