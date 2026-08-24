/************************************************************************
 * GA4 監査データ取得スクリプト（計測監査 GROUND TRUTH 用）
 * ---------------------------------------------------------------------
 * 目的：レポートの数値監査ではなく、「計測器そのものが壊れていないか」を
 *       検査するためのデータを、GA4から一括で書き出す。
 *
 *       通常のレポート用データ取得とは目的が違う。ここで取るのは
 *       「結論を出すための数字」ではなく「その数字が信用できるかを判定する材料」。
 *
 * 方針：GA4 Data API で取得できるものは、この1本ですべて取る。
 *       監査中に「あのディメンションも要る」と分かって取り直すのがいちばん時間を食うため。
 *
 * 出力シート（gt_instrument_check.py がそのまま読める形式）：
 *   GT01_イベント別        … eventName × イベント数・ユーザー数・キーイベント数（全イベント）
 *                             → キーイベント肥大（I-03）・ゼロ件CV（I-04）・I-02 の検査
 *   GT02_ページ別          … pagePath × 表示回数・ユーザー・セッション・イベント数・
 *                             キーイベント・直帰率・エンゲージ率・平均エンゲージ時間・収益
 *                             → 二重発火（I-01）・内部トラフィック（I-07）の検査
 *   GT03_イベント×ページ    … eventName × ページパス+クエリ × ページタイトル × 件数・ユーザー数
 *                             → ファネル母集団（I-05）・scroll到達・click集中の検査。最重要
 *   GT04_離脱クリック先      … 発生ページ × リンクドメイン × リンクURL × クリック数
 *                             → 外部ドメインへの流出（I-06）の確定
 *   GT05_ページタイトル一覧  … pageTitle × 表示回数 → 個人情報の混入（I-08）
 *   GT06_KPI              … セッション・ユーザー・PV・エンゲージ率・直帰率・収益の全体値
 *   GT07_ページ間遷移       … pageReferrer × ページパス+クエリ × 遷移PV
 *                             → 内部導線の集計、遷移元の再現
 *   GT08_CTA到達と転換      … ページ別「閲覧者／縦90%到達／到達率」の組み立て済み表
 *                             → 追従CTA等の定量根拠づくりに直接使える
 *   GT09_取得メモ           … 取得条件の記録（再現性のため）
 *
 * 事前準備（Apps Script「サービス（＋）」で追加）：
 *   - Google Analytics Data API   → 識別子 AnalyticsData
 *
 * 実行方法：下の「設定」を書き換えて、関数 runGroundTruth を実行。
 *   ※ 実行アカウントに GA4プロパティの閲覧権限が必要。
 *   ※ 書き出し先は GT_SPREADSHEET_ID で指定する。空 "" のままなら自動で用意する
 *      （紐づいたシート → 無ければ新規作成）。書き出し先のURLは実行ログに出る。
 *      先に確認したいときは関数 showTarget を実行する。
 *   ※ 所要時間の目安は1〜3分。GT03 が最も時間がかかる。
 *
 * よくあるエラー：
 *   "You do not have permission to access the requested document."
 *     → GT_SPREADSHEET_ID のシートに、実行アカウントの編集権限が無い。
 *       シートを共有するか、GT_SPREADSHEET_ID を "" にして実行し直す（新規作成される）。
 *   "AnalyticsData is not defined"
 *     → 「サービス（＋）」で Google Analytics Data API（識別子 AnalyticsData）を追加する。
 *   "User does not have sufficient permissions for this property."
 *     → 実行アカウントに GA4プロパティの閲覧権限が無い。
 *
 * GA4 Data API では取れないもの（別途ご用意いただく）：
 *   - GA4管理画面の「キーイベント」登録一覧 … 画面キャプチャ。
 *     何がCVに「登録されているか」はAPIからは読み取れない（発生件数しか返らない）。
 *   - GTMコンテナの中身 … JSONエクスポート。二重発火・0件イベントの「原因」特定に必要。
 *   - Search Console … 別ツール。管理画面からエクスポートする。
 *   - フォームのテスト送信の結果 … 実際に送信して確認する。
 ************************************************************************/

/* ============================ 設定（ここだけ書き換える）============================ */

// 書き出し先スプレッドシートID（URLの /d/ と /edit の間の文字列）
//   空文字 "" のままでも動く。その場合は
//     ① このスクリプトがスプレッドシートに紐づいていれば、そのシートに書く
//     ② 紐づいていなければ、実行アカウントのドライブに新規作成する（URLは実行ログに出る）
//   IDを指定したのに「You do not have permission to access the requested document.」が出る場合は、
//   実行アカウントにそのシートの編集権限が無い。共有設定を直すか、この欄を "" にして作り直す。
const GT_SPREADSHEET_ID = "";

// 監査対象の GA4 プロパティID（数字のみ）
const GT_PROPERTY_ID = "＜プロパティIDを入れる＞";

// 監査対象の期間（レポートが対象にしている期間と必ず一致させること）
const GT_START = "2026-06-01";
const GT_END   = "2026-06-30";

// 案件固有のCVイベント名。0件でも必ず行を出す（「設計されているのに0件」の検出に使う）
const GT_CUSTOM_CV_EVENTS = [];

// GT03（イベント×ページ）は既定で全イベントを分解する。
// 行数が多すぎて実行時間が延びる場合のみ、ここに絞り込むイベント名を入れる（空なら全件）。
const GT_EVENTS_TO_SPLIT = [];

const GT_ROW_LIMIT = 100000;

/* ============================ 実行本体 ============================ */
function runGroundTruth() {
  var ss = gtSS_();
  Logger.log("書き出し先: " + ss.getName() + "\n" + ss.getUrl());

  gtEvents_();                 // GT01
  gtPages_();                  // GT02
  gtEventByPage_();            // GT03
  gtOutbound_();               // GT04
  gtTitles_();                 // GT05
  gtKpi_();                    // GT06
  gtTransitions_();            // GT07
  gtScrollReach_();            // GT08
  gtMemo_();                   // GT09

  Logger.log("完了。GT01〜GT09 を書き出しました。\n" + ss.getUrl());
  try {
    ss.toast("計測監査用の監査データを取得しました（GT01〜GT09）。", "完了", 5);
  } catch (e) { /* 画面が開いていない場合は無視 */ }
  return ss.getUrl();
}

/**
 * 書き出し先だけを先に確認したいときに実行する。
 * 実行ログにスプレッドシートのURLが出る。
 */
function showTarget() {
  var ss = gtSS_();
  Logger.log("書き出し先: " + ss.getName() + "\n" + ss.getUrl());
  return ss.getUrl();
}

/* -------- GT01 イベント別（キーイベント数を含む・全イベント） -------- */
function gtEvents_() {
  var res = gtReportFallback_({ dimensions: ["eventName"], metrics: ["eventCount", "totalUsers"] },
                              ["keyEvents"]);
  var withKey = res.metrics.length === 3;
  var out = [withKey ? ["イベント名", "イベント数", "ユーザー数", "キーイベント"]
                     : ["イベント名", "イベント数", "ユーザー数"]];
  var seen = {};
  res.rows.forEach(function (r) {
    var name = r.dimensionValues[0].value;
    seen[name] = true;
    var m = r.metricValues.map(function (v) { return Math.round(Number(v.value)); });
    out.push(withKey ? [name, m[0], m[1], m[2]] : [name, m[0], m[1]]);
  });
  // 「設計されているのに0件」を可視化するため、指定したCVイベントは0行でも必ず出す
  GT_CUSTOM_CV_EVENTS.forEach(function (name) {
    if (!seen[name]) { out.push(withKey ? [name, 0, 0, 0] : [name, 0, 0]); seen[name] = true; }
  });
  gtWrite_("GT01_イベント別", out);
  gtNote_("GT01_イベント別",
    "※ キーイベント数の合計がセッション数を超えていたら、まず設定ミス（成果の定義が実態と食い違っている）。" +
    "※ 名前がCVらしいのに0件のイベントは「成果が無い」のではなく「計測できていない」可能性がある。" +
    "※ ページ読み込みで自動発火するイベント（page_view / first_visit / session_start / scroll）と、" +
    "ユーザーの操作で起きるイベント（click / form_start / purchase 等）の1人あたり件数を比べると、" +
    "二重発火なのか計測タグが2セットなのかを切り分けられる。" +
    (withKey ? "" : "※ このプロパティでは keyEvents 指標が取得できなかったため、キーイベント列は空。"));
  return out;
}

/* -------- GT02 ページ別（二重発火・内部トラフィックの判定に使う） -------- */
function gtPages_() {
  var base = { dimensions: ["pagePath"],
               metrics: ["screenPageViews", "totalUsers", "sessions", "eventCount",
                         "bounceRate", "engagementRate", "userEngagementDuration"],
               orderByMetric: "screenPageViews" };
  var res = gtReportFallback_(base, ["keyEvents", "totalRevenue"]);
  var extra = res.metrics.length - 7;
  var head = ["ページパス", "表示回数", "ユーザー数", "セッション数", "イベント数",
              "直帰率(%)", "エンゲージメント率(%)", "平均エンゲージ時間(秒)"];
  if (extra >= 1) head.push("キーイベント");
  if (extra >= 2) head.push("収益");
  var out = [head];
  res.rows.forEach(function (r) {
    var m = r.metricValues.map(function (v) { return Number(v.value); });
    var row = [r.dimensionValues[0].value, Math.round(m[0]), Math.round(m[1]),
               Math.round(m[2]), Math.round(m[3]),
               Math.round(m[4] * 1000) / 10, Math.round(m[5] * 1000) / 10,
               m[1] ? Math.round(m[6] / m[1] * 10) / 10 : 0];
    if (extra >= 1) row.push(Math.round(m[7]));
    if (extra >= 2) row.push(Math.round(m[8]));
    out.push(row);
  });
  gtWrite_("GT02_ページ別", out);
  gtNote_("GT02_ページ別",
    "※ 表示回数 ÷ ユーザー数 が多くのページで 2.00 前後に固定される、" +
    "表示回数が偶数のページが 8 割を超える、といった分布は自然な閲覧行動では起こらない（page_view の二重発火）。" +
    "※ 1ユーザーあたりの閲覧回数が極端に多いページ、一般ユーザーが到達できないURL（_preview 等）は" +
    "内部トラフィックの可能性がある。" +
    "※ 二重発火がある場合、直帰率・エンゲージメント率は指標として使えない" +
    "（1ページしか見ていないセッションでも自動的に『2ページ以上』を満たすため）。");
}

/* -------- GT03 イベント×ページ（ファネル母集団の検査。最重要） -------- */
function gtEventByPage_() {
  var o = { dimensions: ["eventName", "pagePathPlusQueryString", "pageTitle"],
            metrics: ["eventCount", "totalUsers"], orderByMetric: "eventCount" };
  if (GT_EVENTS_TO_SPLIT.length) {
    o.dimensionFilter = { filter: { fieldName: "eventName",
      inListFilter: { values: GT_EVENTS_TO_SPLIT.concat(GT_CUSTOM_CV_EVENTS) } } };
  }
  var rows;
  try {
    rows = gtReport_(o);
  } catch (e) {
    // ページタイトルとの3次元が拒否された場合はパスのみに落とす
    o.dimensions = ["eventName", "pagePathPlusQueryString"];
    rows = gtReport_(o);
  }
  var three = o.dimensions.length === 3;
  var out = [three ? ["イベント名", "ページパス", "ページタイトル", "イベント数", "ユーザー数"]
                   : ["イベント名", "ページパス", "イベント数", "ユーザー数"]];
  rows.forEach(function (r) {
    var d = r.dimensionValues.map(function (v) { return v.value; });
    var m = r.metricValues.map(function (v) { return Math.round(Number(v.value)); });
    out.push(d.concat([m[0], m[1]]));
  });
  gtWrite_("GT03_イベント×ページ", out);
  gtNote_("GT03_イベント×ページ",
    "※ 拡張計測機能の form_start / form_submit はフォームの種類を区別しない。" +
    "問い合わせフォームも、商品ページの『カートに追加』も、検索窓も、フッターのメルマガ登録欄も、" +
    "決済画面の入力欄も、すべて同じイベントになる。" +
    "『イベント』レポートに出るのはサイト全体の合計だけなので、ページ別に分解しない限り" +
    "『どのページで起きたか』は分からない。ファネルの各段は、必ずこの表で同じ1ページに揃えてから描くこと。" +
    "※ scroll は既定で縦90%到達で発火する。ページ下部のCTAへの到達数として使える。" +
    "※ click は外部ドメインへのリンクでのみ発火する。1ページに集中していれば、" +
    "そのページの主要CTAのリンク先が外部である可能性が高い（GT04で確定）。");
}

/* -------- GT04 離脱クリック先（外部ドメインへの流出） --------
 * 「どのページから」「どのドメインへ」出たかの組み合わせで取る。
 * ドメイン別の合計だけでは「あのページのクリックがこのドメイン向けだった」ことを確定できない。
 * ディメンションの組み合わせはプロパティによって拒否されることがあるため、段階的に落とす。 */
function gtOutbound_() {
  var TRY = [
    { dims: ["pagePath", "linkDomain", "linkUrl"], head: ["発生ページ", "リンクドメイン", "リンクURL"] },
    { dims: ["pagePath", "linkDomain"],            head: ["発生ページ", "リンクドメイン"] },
    { dims: ["linkDomain", "linkUrl"],             head: ["リンクドメイン", "リンクURL"] },
    { dims: ["linkDomain"],                        head: ["リンクドメイン"] }
  ];
  var out = null, used = "", lastErr = "";
  for (var i = 0; i < TRY.length; i++) {
    try {
      var rows = gtReport_({
        dimensions: TRY[i].dims,
        metrics: ["eventCount", "totalUsers"],
        dimensionFilter: { filter: { fieldName: "eventName",
          stringFilter: { matchType: "EXACT", value: "click" } } },
        orderByMetric: "eventCount"
      });
      out = [TRY[i].head.concat(["イベント数", "ユーザー数"])];
      rows.forEach(function (r) {
        var d = r.dimensionValues.map(function (v) { return v.value; });
        var m = r.metricValues.map(function (v) { return Math.round(Number(v.value)); });
        out.push(d.concat([m[0], m[1]]));
      });
      used = TRY[i].dims.join(" × ");
      break;
    } catch (e) {
      lastErr = String(e).slice(0, 160);
    }
  }
  if (!out) {
    out = [["リンクドメイン", "イベント数", "ユーザー数"],
           ["（linkDomain ディメンションが利用できませんでした）", "", ""],
           [lastErr, "", ""]];
  }
  gtWrite_("GT04_離脱クリック先", out);
  gtNote_("GT04_離脱クリック先",
    "取得できたディメンション: " + (used || "（取得失敗）") + "\n" +
    "※ click（離脱クリック）は外部ドメインへのリンクでのみ発火する。" +
    "レポートが『ページの出口』をサイト内遷移だけで集計していると、最大の出口を丸ごと見落とす。" +
    "行き先が自社の別ドメイン（EC・予約サイト等）なら、そのページは成果が別ドメインで計上されているだけで、" +
    "『CVに繋がっていない』のではない。" +
    "※ 発生ページの列が取れていれば「このページのクリックが、このドメイン向けだった」ことまで確定できる。" +
    "取れていない場合は、ドメイン別の合計と GT03 のページ別 click 件数を突き合わせた推定にとどまるため、" +
    "レポートには推定であると明記すること。");
}

/* -------- GT05 ページタイトル一覧（個人情報の混入チェック） -------- */
function gtTitles_() {
  var rows = gtReport_({
    dimensions: ["pageTitle"], metrics: ["screenPageViews", "totalUsers"],
    orderByMetric: "screenPageViews"
  });
  var out = [["ページタイトル", "表示回数", "ユーザー数"]];
  rows.forEach(function (r) {
    var m = r.metricValues.map(function (v) { return Math.round(Number(v.value)); });
    out.push([r.dimensionValues[0].value, m[0], m[1]]);
  });
  gtWrite_("GT05_ページタイトル一覧", out);
  gtNote_("GT05_ページタイトル一覧",
    "※ 注文完了ページ等が顧客名をタイトルに含める仕様のCMS（Shopify等）では、" +
    "意図せず個人情報がGA4に送信されていることがある。Googleアナリティクスの利用規約は" +
    "個人を特定できる情報の送信を禁止している。");
}

/* -------- GT06 KPI（全体値） -------- */
function gtKpi_() {
  var base = { dimensions: [],
               metrics: ["sessions", "totalUsers", "newUsers", "screenPageViews",
                         "engagementRate", "bounceRate", "averageSessionDuration",
                         "eventCount"] };
  var res = gtReportFallback_(base, ["keyEvents", "totalRevenue"]);
  var v = res.rows.length ? res.rows[0].metricValues.map(function (x) { return Number(x.value); })
                          : res.metrics.map(function () { return 0; });
  var out = [["指標", "値"],
             ["セッション", Math.round(v[0])],
             ["ユーザー数", Math.round(v[1])],
             ["新規ユーザー数", Math.round(v[2])],
             ["PV(表示回数)", Math.round(v[3])],
             ["エンゲージメント率(%)", Math.round(v[4] * 1000) / 10],
             ["直帰率(%)", Math.round(v[5] * 1000) / 10],
             ["平均セッション時間(秒)", Math.round(v[6] * 10) / 10],
             ["イベント数(総数)", Math.round(v[7])]];
  if (res.metrics.length >= 9)  out.push(["キーイベント数(合計)", Math.round(v[8])]);
  if (res.metrics.length >= 10) out.push(["収益", Math.round(v[9])]);
  gtWrite_("GT06_KPI", out);
  gtNote_("GT06_KPI",
    "※ page_view が二重発火している場合、PV・エンゲージメント率・直帰率は指標として使えない。" +
    "エンゲージセッションは「10秒超の滞在 または 2ページ以上の閲覧 または キーイベント発生」で判定されるため、" +
    "page_view が2回発火すると1ページしか見ていないセッションでも自動的にエンゲージ扱いになる。" +
    "※ キーイベント数がセッション数を超えていたら、まず設定ミス。");
}

/* -------- GT07 ページ間遷移（内部導線の再現） -------- */
function gtTransitions_() {
  var rows = gtReport_({
    dimensions: ["pageReferrer", "pagePathPlusQueryString"],
    metrics: ["screenPageViews", "totalUsers"], orderByMetric: "screenPageViews"
  });
  var out = [["遷移元(pageReferrer)", "遷移先(ページパス)", "遷移PV", "ユーザー数"]];
  rows.forEach(function (r) {
    var m = r.metricValues.map(function (v) { return Math.round(Number(v.value)); });
    out.push([r.dimensionValues[0].value, r.dimensionValues[1].value, m[0], m[1]]);
  });
  gtWrite_("GT07_ページ間遷移", out);
  gtNote_("GT07_ページ間遷移",
    "※ この表はサイト内の遷移しか返さない。外部ドメインへ出ていった人は遷移先が存在しないため現れない。" +
    "『ページの出口』をこの表だけで集計すると、最大の出口を見落とすことがある（GT04と併読すること）。" +
    "※ 遷移PVは page_view の二重発火の影響を受ける。構成比は影響を受けない。");
}

/* -------- GT08 CTA到達と転換（ページ別の到達率を組み立てる） -------- */
function gtScrollReach_() {
  var pu = {}, pv = {};
  gtReport_({ dimensions: ["pagePath"], metrics: ["totalUsers", "screenPageViews"],
              orderByMetric: "totalUsers" }).forEach(function (r) {
    var p = r.dimensionValues[0].value;
    pu[p] = (pu[p] || 0) + Math.round(Number(r.metricValues[0].value));
    pv[p] = (pv[p] || 0) + Math.round(Number(r.metricValues[1].value));
  });
  var su = {};
  gtReport_({ dimensions: ["pagePath"], metrics: ["totalUsers"],
              dimensionFilter: { filter: { fieldName: "eventName",
                stringFilter: { matchType: "EXACT", value: "scroll" } } },
              orderByMetric: "totalUsers" }).forEach(function (r) {
    var p = r.dimensionValues[0].value;
    su[p] = (su[p] || 0) + Math.round(Number(r.metricValues[0].value));
  });
  var keys = Object.keys(pu).sort(function (a, b) { return pu[b] - pu[a]; });
  var out = [["ページパス", "閲覧者(ユーザー)", "縦90%到達(ユーザー)", "到達率", "表示回数"]];
  keys.slice(0, 60).forEach(function (p) {
    var s = su[p] || 0;
    out.push([p, pu[p], s, pu[p] ? Math.round(s / pu[p] * 1000) / 10 + "%" : "―", pv[p]]);
  });
  gtWrite_("GT08_CTA到達と転換", out);
  gtNote_("GT08_CTA到達と転換",
    "※ scroll は既定で縦90%到達で発火するため、ページ下部に置かれたCTAへの到達数として使える。" +
    "『CTAが無いから送れていない』のか『CTAはあるが見られていない』のかは、この表で切り分けられる。" +
    "※ さらに GT07 から「そのページ → 問い合わせフォーム」の遷移PVを引き、" +
    "（二重発火があれば2で割ってから）到達者数で割ると、到達者の転換率が出る。" +
    "この指標は正式なCV定義が未確定でも試算でき、施策の効果検証の補助指標としてそのまま使える。" +
    "※ ユーザー数はページごとに重複排除されるため、合計は全体のユーザー数と一致しない。");
}

/* -------- GT09 取得メモ（再現性の担保） -------- */
function gtMemo_() {
  var who = "";
  try { who = Session.getActiveUser().getEmail() || "（取得できず）"; }
  catch (e) { who = "（取得できず）"; }
  gtWrite_("GT09_取得メモ", [
    ["項目", "内容"],
    ["プロパティID", GT_PROPERTY_ID],
    ["対象期間", GT_START + " 〜 " + GT_END],
    ["書き出し先", gtSS_().getUrl()],
    ["GT03の分解対象", GT_EVENTS_TO_SPLIT.length
      ? GT_EVENTS_TO_SPLIT.concat(GT_CUSTOM_CV_EVENTS).join(" / ") : "全イベント"],
    ["0件でも出すCVイベント", GT_CUSTOM_CV_EVENTS.join(" / ") || "（指定なし）"],
    ["取得日時", Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyy-MM-dd HH:mm")],
    ["取得アカウント", who],
    ["用途", "計測監査（計測健全性の独立検証）"],
    ["APIで取れないもの",
      "GA4管理画面のキーイベント登録一覧（画面キャプチャ）／GTMコンテナ（JSON）／" +
      "Search Console（別ツールからエクスポート）／フォームのテスト送信の結果"],
    ["注意", "この表を残しておくと、後から『どの条件で取った数字か』を再現できる。" +
             "監査の指摘は、再現できて初めて指摘になる。"]
  ]);
}

/* ========================= 共通処理 ========================= */
function gtReport_(o) {
  var all = [];
  var offset = 0;
  while (true) {
    var req = {
      dateRanges: [{ startDate: GT_START, endDate: GT_END }],
      dimensions: (o.dimensions || []).map(function (n) { return { name: n }; }),
      metrics: (o.metrics || []).map(function (n) { return { name: n }; }),
      limit: o.limit || GT_ROW_LIMIT, offset: offset, keepEmptyRows: false
    };
    if (o.orderByMetric) req.orderBys = [{ metric: { metricName: o.orderByMetric }, desc: true }];
    if (o.dimensionFilter) req.dimensionFilter = o.dimensionFilter;
    var res = AnalyticsData.Properties.runReport(req, "properties/" + GT_PROPERTY_ID);
    var rows = res.rows || [];
    rows.forEach(function (r) { all.push(r); });
    var total = Number(res.rowCount || rows.length);
    offset += rows.length;
    var lim = o.limit || GT_ROW_LIMIT;
    if (rows.length === 0 || offset >= total || rows.length < lim) break;
  }
  return all;
}

/**
 * 追加で取りたい指標（プロパティによっては未対応）を付けて試し、
 * 失敗したら付けずに取り直す。
 */
function gtReportFallback_(o, optional) {
  var withOpt = [];
  (o.metrics || []).forEach(function (m) { withOpt.push(m); });
  (optional || []).forEach(function (m) { withOpt.push(m); });
  try {
    var o2 = { dimensions: o.dimensions, metrics: withOpt,
               orderByMetric: o.orderByMetric, dimensionFilter: o.dimensionFilter,
               limit: o.limit };
    return { rows: gtReport_(o2), metrics: withOpt };
  } catch (e) {
    return { rows: gtReport_(o), metrics: o.metrics };
  }
}

/**
 * 書き出し先のスプレッドシートを決める。
 *   ① GT_SPREADSHEET_ID が指定されていて、開けるならそれを使う
 *   ② このスクリプトがスプレッドシートに紐づいていれば、そのシート
 *   ③ どちらでもなければ、実行アカウントのドライブに新規作成する
 * 権限エラーで止まらないようにするための仕組み。一度決めたら実行中は使い回す。
 */
var _GT_SS = null;
function gtSS_() {
  if (_GT_SS) return _GT_SS;

  if (GT_SPREADSHEET_ID && GT_SPREADSHEET_ID.indexOf("＜") < 0) {
    try {
      var byId = SpreadsheetApp.openById(GT_SPREADSHEET_ID);
      byId.getName();                       // 実際に読めるかここで確かめる
      _GT_SS = byId;
      return _GT_SS;
    } catch (e) {
      Logger.log("指定されたスプレッドシートを開けませんでした（権限が無い可能性があります）。\n"
                 + "  ID: " + GT_SPREADSHEET_ID + "\n  " + String(e).slice(0, 200)
                 + "\n  → 代わりの書き出し先を探します。");
    }
  }

  try {
    var active = SpreadsheetApp.getActiveSpreadsheet();
    if (active) {
      active.getName();
      _GT_SS = active;
      Logger.log("このスクリプトが紐づいているスプレッドシートに書き出します: " + active.getName());
      return _GT_SS;
    }
  } catch (e) { /* 紐づいていない（スタンドアロン）場合はここに来る */ }

  var name = "GroundTruth_監査データ_" + GT_PROPERTY_ID + "_"
             + GT_START.replace(/-/g, "") + "-" + GT_END.replace(/-/g, "");
  _GT_SS = SpreadsheetApp.create(name);
  Logger.log("新しいスプレッドシートを作成しました。\n  " + _GT_SS.getUrl());
  return _GT_SS;
}

function gtWrite_(name, values) {
  var ss = gtSS_();
  var sh = ss.getSheetByName(name);
  if (sh) { sh.clear(); } else { sh = ss.insertSheet(name); }
  if (!values.length) values = [["データがありません"]];
  var w = 0;
  values.forEach(function (r) { if (r.length > w) w = r.length; });
  values = values.map(function (r) {
    var c = r.slice();
    while (c.length < w) c.push("");
    return c;
  });
  sh.getRange(1, 1, values.length, w).setValues(values);
  sh.getRange(1, 1, 1, w).setFontWeight("bold")
    .setBackground("#1F497D").setFontColor("#FFFFFF");
  sh.setFrozenRows(1);
  sh.autoResizeColumns(1, w);
}

function gtNote_(name, text) {
  var sh = gtSS_().getSheetByName(name);
  if (!sh) return;
  var r = sh.getLastRow() + 2;
  sh.getRange(r, 1).setValue(text).setFontColor("#808080").setWrap(true);
}
