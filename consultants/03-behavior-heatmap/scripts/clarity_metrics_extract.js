/*
 * Clarityヒートマップ画面から集計値を数値で取り出す
 * =================================================
 *
 * 使い方
 *   1. Clarityのヒートマップ画面を開く（URLパラメータで状態を指定しておく）
 *      詳細は ../CLARITY_METRICS.md
 *   2. このファイルの中身をブラウザのコンソールに貼って実行する
 *      （ブラウザ自動化からJSを実行する場合も同じ。最後の式の値が返る）
 *   3. 返ってきたJSONを output/ に保存する
 *
 * heatmapType=0（タップ）なら要素別クリック数、
 * heatmapType=1（スクロール）なら深度別到達率を返す。
 *
 * GROUPS は対象サイトに合わせて書き換える。Clarityは要素を1つずつ並べるため、
 * 束ねずに順位だけを見るとカード類が過小に見える。
 */

const GROUPS = {
  // 絞り込み・ファセットUI
  facet: /facet|filter|refine|js_facet_item/i,
  // 商品カード（画像）
  card: /card-img|item-figure|product-img/i,
  // ページ送り
  pager: /pager|pagination/i,
  // 検索・絞り込みモーダルを開くボタン
  searchButton: /search-modal|search-button/i,
};

(() => {
  const text = document.body.innerText || '';

  // ── 共通ヘルパ ──────────────────────────────────────────────
  const lines = text
    .split('\n')
    .map((s) => s.trim())
    .filter((s) => s.length > 0);

  const toInt = (s) => parseInt(String(s).replace(/,/g, ''), 10);

  // ── タップ（クリック）モード ────────────────────────────────
  // 「<セレクタ>」の次行に「N クリック (X.XX%)」が並ぶ。
  // 表示言語で文言が変わるため日本語・英語の両方を受ける。
  const CLICK_ROW = /^([\d,]+)\s*(?:クリック|clicks?)\s*[（(]\s*([\d.]+)\s*%\s*[）)]$/;

  const rows = [];
  for (let i = 1; i < lines.length; i += 1) {
    const m = lines[i].match(CLICK_ROW);
    if (m) {
      rows.push({
        selector: lines[i - 1],
        clicks: toInt(m[1]),
        pct: parseFloat(m[2]),
      });
    }
  }

  if (rows.length > 0) {
    // 総クリック数は画面下部の「N タップ」から取り、無ければ1位の件数と割合から逆算する
    const totalFromLabel = text.match(/([\d,]+)\s*(?:タップ|クリック|taps?|clicks?)\s*$/m);
    const totalClicks = totalFromLabel
      ? toInt(totalFromLabel[1])
      : Math.round((rows[0].clicks / rows[0].pct) * 100);

    const groups = {};
    Object.keys(GROUPS).forEach((name) => {
      groups[name] = rows
        .filter((r) => GROUPS[name].test(r.selector))
        .reduce((sum, r) => sum + r.clicks, 0);
    });
    // マスクされた要素（テキストを含む要素はセレクタが伏せられる）
    groups.masked = rows
      .filter((r) => /^[•\s]+$/.test(r.selector))
      .reduce((sum, r) => sum + r.clicks, 0);

    const groupPct = {};
    Object.keys(groups).forEach((name) => {
      groupPct[name] = totalClicks
        ? Math.round((groups[name] / totalClicks) * 1000) / 10
        : null;
    });

    return JSON.stringify(
      {
        mode: 'tap',
        capturedAt: new Date().toISOString(),
        pageUrl: location.href,
        elementCount: rows.length,
        totalClicks,
        groups,
        groupPct,
        rows,
      },
      null,
      1,
    );
  }

  // ── スクロールモード ────────────────────────────────────────
  // 「5%」「1,200 (100%)」「0%」の3行が1組で並ぶ。
  const DEPTH = /^(\d+)%$/;
  const VISITORS = /^([\d,]+)\s*[（(]\s*([\d.]+)\s*%\s*[）)]$/;
  const DROP = /^([\d.]+)%$/;

  const depth = [];
  for (let i = 0; i < lines.length - 1; i += 1) {
    const d = lines[i].match(DEPTH);
    if (!d) continue;
    const v = lines[i + 1].match(VISITORS);
    if (!v) continue;
    const drop = (lines[i + 2] || '').match(DROP);
    depth.push({
      pct: parseInt(d[1], 10),
      visitors: toInt(v[1]),
      reach: parseFloat(v[2]),
      dropoff: drop ? parseFloat(drop[1]) : null,
    });
  }

  if (depth.length > 0) {
    const pv = text.match(/([\d,]+)\s*(?:ページ\s*ビュー|page\s*views?)/i);
    return JSON.stringify(
      {
        mode: 'scroll',
        capturedAt: new Date().toISOString(),
        pageUrl: location.href,
        pageViews: pv ? toInt(pv[1]) : null,
        depth,
      },
      null,
      1,
    );
  }

  return JSON.stringify({
    mode: 'unknown',
    hint: 'ヒートマップの描画完了を待ってから再実行する。データが無い場合は期間・デバイス・URL照合条件を見直す。',
    pageUrl: location.href,
  });
})();
