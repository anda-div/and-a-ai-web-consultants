# Changelog

このプロジェクトはSemantic Versioningを参考にバージョン管理します。

## [Unreleased]

- AIウェブコンサルタント7人体制の初回公開版を準備。
- JOB 03に `CLARITY_METRICS.md` を追加。ClarityヒートマップをURLパラメータで状態指定し、要素別クリック数とスクロール到達率を実数で取得する手順を文書化。
- JOB 03に `scripts/clarity_metrics_extract.js` を追加。ヒートマップ画面から集計値をJSONで取り出す（日本語・英語UI対応）。
- JOB 03に `CLARITY_CAPTURE.md` と `scripts/clarity_heatmap_capture.py` を追加。`#heatmapVisual` の `scrollTop` を直接制御することで、熱とページ画像の位置ずれを起こさずに分割キャプチャ・結合する。
- `.gitignore` にClarity用ブラウザプロファイル（`.clarity_profile`）を追加。
