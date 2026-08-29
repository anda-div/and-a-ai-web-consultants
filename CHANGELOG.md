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
