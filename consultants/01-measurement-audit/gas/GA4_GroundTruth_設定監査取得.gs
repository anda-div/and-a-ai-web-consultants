/************************************************************************
 * GA4 設定監査スクリプト（計測監査 GROUND TRUTH 用）
 * ---------------------------------------------------------------------
 * 目的：GA4の「設定そのもの」を丸ごと書き出す。
 *
 *       同梱の GA4_GroundTruth_監査データ取得.gs が取るのは【数値】。
 *       こちらが取るのは【設定】。計測器の故障を診断するには両方が要る。
 *
 *       管理画面のキャプチャを1枚ずつ集める必要はほとんど無い。
 *       Admin API で機械可読に取れるものは、すべてこの1本で取る。
 *
 * 出力シート：
 *   CF01_プロパティ        … 対象プロパティの基本情報（タイムゾーン・通貨・所属アカウント）
 *   CF02_データストリーム    … 測定ID・ドメイン・ストリーム種別
 *   CF03_拡張計測機能       … scroll / 離脱クリック / フォームの操作 等のON/OFF
 *   CF04_キーイベント       … 何がCVとして登録されているか（発生0件でも出る）★
 *   CF05_作成イベント       … 「イベントを作成」の条件。0件イベントの原因調査に直結 ★★
 *   CF06_イベント編集ルール   … イベント名やパラメータの書き換え設定
 *   CF07_Google広告リンク    … リンク先のCID・パーソナライズド広告の有効/無効 ★
 *   CF08_カスタム定義        … カスタムディメンション／カスタム指標
 *   CF09_変更履歴           … いつ誰が設定を変えたか ★
 *   CF10_その他の設定        … データ保持期間・アトリビューション・BigQueryリンク
 *   CF11_取得メモ           … 取得条件の記録
 *
 * ★ 403「insufficient authentication scopes」が出たときは、まず showGrantedScopes を実行する。
 *   実際に付与されているスコープがログに出るので、原因を推測せずに確定できる。
 *
 * ★ 確実な方法【C・推奨】マニフェストにスコープを明記する
 *   Apps Script エディタ左の「プロジェクトの設定」（歯車）→
 *   「"appsscript.json" マニフェスト ファイルをエディタで表示する」にチェック →
 *   エディタに現れた appsscript.json に、次の oauthScopes を追記して保存 → 再実行 → 権限を再承認。
 *
 *     "oauthScopes": [
 *       "https://www.googleapis.com/auth/analytics.readonly",
 *       "https://www.googleapis.com/auth/script.external_request",
 *       "https://www.googleapis.com/auth/spreadsheets",
 *       "https://www.googleapis.com/auth/drive",
 *       "https://www.googleapis.com/auth/userinfo.email"
 *     ]
 *
 *   サービスの追加（下記A・B）だけではスコープが付かないことがあるため、
 *   確実に通したい場合はCを行う。
 *
 * 事前準備（どちらか一方でよい）：
 *   【A・最も簡単】すでに runGroundTruth（数値取得側）を動かした Apps Script プロジェクトに、
 *     このスクリプトを新しいファイルとして追加する。
 *     → Data API のスコープ（analytics.readonly）をそのまま使えるため、追加設定は不要。
 *
 *   【B】新しいプロジェクトで動かす場合は、「サービス（＋）」から
 *     「Google Analytics Admin API」（識別子 AnalyticsAdmin）を追加する。
 *     追加した直後の初回実行で、権限の再承認を求められる。必ず承認すること。
 *
 *   ※「Request had insufficient authentication scopes.」というエラーが出る場合は、
 *     この事前準備が済んでいない。GA4側の権限の問題ではない。
 *
 * 実行方法：下の GTC_PROPERTIES を対象プロパティIDに書き換えて runConfigAudit を実行。
 *   ※ 実行アカウントに各プロパティの閲覧権限が必要（編集権限は不要）。
 *   ※ 書き出し先は自動で用意する（新規作成される。URLは実行ログに出る）。
 *
 * Admin API でも取得できないもの（これだけは画面のキャプチャが必要）：
 *   - 内部トラフィックの定義（IPフィルタ）
 *   - 除外する参照のリスト
 *   - クロスドメイン測定の「ドメインの設定」
 *   - Googleタグの「接続済みのタグ」
 *   → いずれも 管理 → データストリーム → Googleタグ →「タグの設定を行う」→ 設定を編集 にある。
 ************************************************************************/

/* ============================ 設定（ここだけ書き換える）============================ */

// 監査対象のGA4プロパティID（数字のみ）。複数指定できる。
const GTC_PROPERTIES = ["＜プロパティIDを入れる＞"];

// 変更履歴をさかのぼる日数（GA4の保持上限まで。取れない分は自動で無視される）
const GTC_HISTORY_DAYS = 365;

// 書き出し先スプレッドシートID。空 "" なら自動で用意する（推奨）
const GTC_SPREADSHEET_ID = "";

const GTC_API = "https://analyticsadmin.googleapis.com/v1alpha";

/* ============================ 実行本体 ============================ */
function runConfigAudit() {
  gtcPreflight_();
  var ss = gtcSS_();
  Logger.log("書き出し先: " + ss.getName() + "\n" + ss.getUrl());

  var props = [], streams = [], enh = [], keys = [], creates = [], edits = [];
  var ads = [], dims = [], hist = [], other = [], errs = [];

  GTC_PROPERTIES.forEach(function (pid) {
    var pname = "properties/" + pid;

    // --- プロパティ本体 ---
    var p = gtcGet_(GTC_API + "/" + pname, errs, pid + " プロパティ");
    var account = p && p.parent ? p.parent : "";
    props.push([pid, p ? (p.displayName || "") : "（取得失敗）", account,
                p ? (p.timeZone || "") : "", p ? (p.currencyCode || "") : "",
                p ? (p.industryCategory || "") : "", p ? (p.createTime || "") : "",
                p ? (p.propertyType || "") : ""]);

    // --- データストリーム ---
    var sres = gtcGet_(GTC_API + "/" + pname + "/dataStreams?pageSize=200", errs, pid + " データストリーム");
    var slist = (sres && sres.dataStreams) || [];
    slist.forEach(function (s) {
      var w = s.webStreamData || {};
      streams.push([pid, gtcTail_(s.name), s.displayName || "", s.type || "",
                    w.measurementId || "", w.defaultUri || "", s.createTime || ""]);

      // --- 拡張計測機能 ---
      var e = gtcGet_(GTC_API + "/" + s.name + "/enhancedMeasurementSettings", errs,
                      pid + " 拡張計測機能 " + (s.displayName || ""));
      if (e) {
        enh.push([pid, s.displayName || "", gtcB_(e.streamEnabled), gtcB_(e.pageChangesEnabled),
                  gtcB_(e.scrollsEnabled), gtcB_(e.outboundClicksEnabled),
                  gtcB_(e.siteSearchEnabled), gtcB_(e.formInteractionsEnabled),
                  gtcB_(e.videoEngagementEnabled), gtcB_(e.fileDownloadsEnabled),
                  e.searchQueryParameter || ""]);
      }

      // --- 作成イベント（★ここが本命）---
      var c = gtcGet_(GTC_API + "/" + s.name + "/eventCreateRules?pageSize=200", errs,
                      pid + " 作成イベント " + (s.displayName || ""));
      ((c && c.eventCreateRules) || []).forEach(function (r) {
        var conds = (r.eventConditions || []).map(function (x) {
          return x.field + " " + (x.comparisonType || "") + " " + (x.value || "")
                 + (x.negated ? "（否定）" : "");
        }).join(" AND ");
        creates.push([pid, s.displayName || "", r.destinationEvent || "",
                      conds || "（条件なし）",
                      r.sourceCopyParameters === true ? "元のパラメータをコピーする" : "コピーしない",
                      (r.parameterMutations || []).map(function (m) {
                        return m.parameter + "=" + m.parameterValue;
                      }).join(" / "),
                      gtcTail_(r.name)]);
      });

      // --- イベント編集ルール ---
      var ed = gtcGet_(GTC_API + "/" + s.name + "/eventEditRules?pageSize=200", errs,
                       pid + " イベント編集ルール " + (s.displayName || ""));
      ((ed && ed.eventEditRules) || []).forEach(function (r) {
        var conds = (r.eventConditions || []).map(function (x) {
          return x.field + " " + (x.comparisonType || "") + " " + (x.value || "");
        }).join(" AND ");
        edits.push([pid, s.displayName || "", r.displayName || "", conds || "（条件なし）",
                    (r.parameterMutations || []).map(function (m) {
                      return m.parameter + "=" + m.parameterValue;
                    }).join(" / ")]);
      });
    });

    // --- キーイベント（★登録されているものが、発生0件でも出る）---
    var k = gtcGet_(GTC_API + "/" + pname + "/keyEvents?pageSize=200", errs, pid + " キーイベント");
    if (!k) k = gtcGet_(GTC_API + "/" + pname + "/conversionEvents?pageSize=200", errs,
                        pid + " コンバージョンイベント（旧名）");
    var klist = (k && (k.keyEvents || k.conversionEvents)) || [];
    klist.forEach(function (x) {
      keys.push([pid, x.eventName || "", x.countingMethod || "",
                 x.custom === true ? "カスタム" : "既定",
                 x.deletable === true ? "削除可" : "削除不可",
                 x.createTime || "",
                 (x.defaultValue ? (x.defaultValue.numericValue + " " + x.defaultValue.currencyCode) : "")]);
    });

    // --- Google広告リンク ---
    var g = gtcGet_(GTC_API + "/" + pname + "/googleAdsLinks?pageSize=200", errs, pid + " Google広告リンク");
    ((g && g.googleAdsLinks) || []).forEach(function (x) {
      ads.push([pid, x.customerId || "", gtcB_(x.adsPersonalizationEnabled),
                x.canManageClients === true ? "MCC" : "アカウント",
                x.creatorEmailAddress || "", x.createTime || ""]);
    });

    // --- カスタム定義 ---
    var cd = gtcGet_(GTC_API + "/" + pname + "/customDimensions?pageSize=200", errs, pid + " カスタムディメンション");
    ((cd && cd.customDimensions) || []).forEach(function (x) {
      dims.push([pid, "ディメンション", x.displayName || "", x.parameterName || "",
                 x.scope || "", x.description || ""]);
    });
    var cm = gtcGet_(GTC_API + "/" + pname + "/customMetrics?pageSize=200", errs, pid + " カスタム指標");
    ((cm && cm.customMetrics) || []).forEach(function (x) {
      dims.push([pid, "指標", x.displayName || "", x.parameterName || "",
                 x.scope || "", x.description || ""]);
    });

    // --- その他の設定 ---
    var dr = gtcGet_(GTC_API + "/" + pname + "/dataRetentionSettings", errs, pid + " データ保持");
    if (dr) other.push([pid, "データ保持期間", dr.eventDataRetention || "",
                        "リセット: " + gtcB_(dr.resetUserDataOnNewActivity)]);
    var at = gtcGet_(GTC_API + "/" + pname + "/attributionSettings", errs, pid + " アトリビューション");
    if (at) other.push([pid, "アトリビューション",
                        (at.reportingAttributionModel || "") + " / " + (at.acquisitionConversionEventLookbackWindow || ""),
                        "その他CV: " + (at.otherConversionEventLookbackWindow || "")]);
    var bq = gtcGet_(GTC_API + "/" + pname + "/bigQueryLinks?pageSize=50", errs, pid + " BigQueryリンク");
    other.push([pid, "BigQueryリンク",
                (bq && bq.bigQueryLinks && bq.bigQueryLinks.length) ? (bq.bigQueryLinks.length + "件") : "なし",
                (bq && bq.bigQueryLinks || []).map(function (x) { return x.project; }).join(", ")]);

    // --- 変更履歴 ---
    if (account) {
      var since = new Date();
      since.setDate(since.getDate() - GTC_HISTORY_DAYS);
      var body = {
        property: pname,
        earliestChangeTime: since.toISOString(),
        pageSize: 200
      };
      var h = gtcPost_(GTC_API + "/" + account + ":searchChangeHistoryEvents", body, errs,
                       pid + " 変更履歴", true);
      ((h && h.changeHistoryEvents) || []).forEach(function (ev) {
        (ev.changes || []).forEach(function (ch) {
          hist.push([pid, ev.changeTime || "", ev.userActorEmail || (ev.actorType || ""),
                     ch.action || "", ch.resource || "",
                     gtcResourceLabel_(ch)]);
        });
      });
    }
  });

  gtcWrite_("CF01_プロパティ",
    [["プロパティID", "表示名", "所属アカウント", "タイムゾーン", "通貨", "業種", "作成日時", "種別"]].concat(props));
  gtcWrite_("CF02_データストリーム",
    [["プロパティID", "ストリームID", "表示名", "種別", "測定ID", "既定URL", "作成日時"]].concat(streams));
  gtcWrite_("CF03_拡張計測機能",
    [["プロパティID", "ストリーム", "有効", "履歴変更時のPV", "スクロール", "離脱クリック",
      "サイト内検索", "フォームの操作", "動画", "ファイルDL", "検索パラメータ"]].concat(enh));
  gtcNote_("CF03_拡張計測機能",
    "※ ページビューの計測はGA4の仕様で常時ONのため、この一覧には現れない（無効化できない）。" +
    "※「フォームの操作」がONだと form_start / form_submit が発火する。これはフォームの種類を区別しないため、" +
    "問い合わせフォームもカート追加も検索窓もメルマガ欄も、すべて同じイベントになる。" +
    "※「離脱クリック」がONだと外部ドメインへのリンクで click が発火する。" +
    "ただしクロスドメイン測定に設定済みのドメインへのリンクでは発火しない。");
  gtcWrite_("CF04_キーイベント",
    [["プロパティID", "イベント名", "カウント方法", "種別", "削除可否", "作成日時", "既定値"]].concat(keys));
  gtcNote_("CF04_キーイベント",
    "※ ここに page_view / first_visit / scroll / click があれば、成果の定義が実態と食い違っている。" +
    "キーイベントの指定はGoogle広告の入札最適化・オーディエンス・アトリビューションにも同時に効く。" +
    "※ このAPIは「登録されているキーイベント」を返す。発生件数は数値側（GT01）で確認すること。");
  gtcWrite_("CF05_作成イベント",
    [["プロパティID", "ストリーム", "作成されるイベント名", "条件", "パラメータのコピー",
      "パラメータの上書き", "ルールID"]].concat(creates));
  gtcNote_("CF05_作成イベント",
    "※ 作成イベントは「元になるイベントが発火したときに、条件に合えば別名のイベントを作る」仕組み。" +
    "したがって元イベントが0件なら、作成イベントも連鎖して永久に0件になる。" +
    "CVイベントが0件のとき、まずこの表で『何を条件にしているか』を確認し、" +
    "その条件のイベントが実際に発生しているかを数値側で照合する。");
  gtcWrite_("CF06_イベント編集ルール",
    [["プロパティID", "ストリーム", "ルール名", "条件", "パラメータの上書き"]].concat(edits));
  gtcWrite_("CF07_Google広告リンク",
    [["プロパティID", "顧客ID(CID)", "パーソナライズド広告", "種別", "リンクしたユーザー", "リンク日時"]].concat(ads));
  gtcNote_("CF07_Google広告リンク",
    "※ リンクが無ければ、そのプロパティのキーイベントがGoogle広告にインポートされることはない。" +
    "リンクがある場合、「そのキーイベントが実際に入札の最適化目標として使われているか」は" +
    "Google広告側（ツールと設定 → コンバージョン →「コンバージョン」列に含める）でしか確認できない。" +
    "ここで判明したCIDを添えて確認を依頼すること。");
  gtcWrite_("CF08_カスタム定義",
    [["プロパティID", "区分", "表示名", "パラメータ名", "範囲", "説明"]].concat(dims));
  gtcWrite_("CF09_変更履歴",
    [["プロパティID", "変更日時", "実行者", "操作", "リソース", "内容"]].concat(hist));
  gtcNote_("CF09_変更履歴",
    "※「設定はしたが、動作確認されないまま運用が続いている」という推定を、事実で裏づけられることがある。" +
    "CVイベントの作成日時と、そのイベントが最後に発生した日を突き合わせるとよい。");
  gtcWrite_("CF10_その他の設定",
    [["プロパティID", "項目", "値", "補足"]].concat(other));
  gtcWrite_("CF11_取得メモ", [
    ["項目", "内容"],
    ["対象プロパティ", GTC_PROPERTIES.join(" / ")],
    ["変更履歴の遡及日数", GTC_HISTORY_DAYS],
    ["取得日時", Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyy-MM-dd HH:mm")],
    ["取得アカウント", gtcWho_()],
    ["書き出し先", ss.getUrl()],
    ["用途", "計測監査（GA4設定の独立検証）"],
    ["APIで取れないもの",
      "内部トラフィックの定義／除外する参照のリスト／クロスドメイン測定のドメイン設定／" +
      "Googleタグの「接続済みのタグ」。いずれも 管理 → データストリーム → Googleタグ →" +
      "「タグの設定を行う」→ 設定を編集 の画面キャプチャが必要。"],
    ["エラー件数", errs.length]
  ]);
  if (errs.length) {
    gtcWrite_("CF99_取得エラー", [["対象", "内容"]].concat(errs));
  }

  Logger.log("完了。CF01〜CF11 を書き出しました（エラー " + errs.length + " 件）。\n" + ss.getUrl());
  try { ss.toast("GA4設定の監査データを取得しました。", "完了", 5); } catch (e) {}
  return ss.getUrl();
}

/** 書き出し先だけ先に確認したいときに実行する */
function showConfigTarget() {
  var ss = gtcSS_();
  Logger.log("書き出し先: " + ss.getName() + "\n" + ss.getUrl());
  return ss.getUrl();
}

/**
 * 【診断用】このスクリプトに実際に付与されているOAuthスコープを表示する。
 * 403（スコープ不足）が出たら、まずこれを実行する。推測で対処しないための関数。
 *
 * ログに analytics.readonly（または analytics.edit）が含まれていなければ、
 * それがそのまま原因。マニフェスト（appsscript.json）に追記して再承認する。
 */
function showGrantedScopes() {
  var token = ScriptApp.getOAuthToken();
  var res = UrlFetchApp.fetch(
    "https://www.googleapis.com/oauth2/v1/tokeninfo?access_token=" + encodeURIComponent(token),
    { muteHttpExceptions: true });
  var body = res.getContentText();
  Logger.log("付与されているスコープ:");
  Logger.log(body);
  var ok = body.indexOf("analytics.readonly") >= 0 || body.indexOf("auth/analytics") >= 0;
  Logger.log(ok
    ? "→ Analytics のスコープは付与されています。403が出る場合は別の原因です。"
    : "→ Analytics のスコープが付与されていません。これが403の原因です。"
      + " appsscript.json の oauthScopes に"
      + " https://www.googleapis.com/auth/analytics.readonly を追加し、保存して再実行してください。");
  return body;
}

/* ========================= 共通処理 ========================= */
/**
 * 実行前の確認。
 * Apps Script は「コード内でどのサービスを使っているか」を静的に見てOAuthスコープを決める。
 * Admin API のサービスが未追加だと、UrlFetch で叩いても 403（スコープ不足）になる。
 * 30件のエラーを並べる前に、ここで止めて原因を明示する。
 */
function gtcPreflight_() {
  var hasAdmin = false;
  try { hasAdmin = (typeof AnalyticsAdmin !== "undefined"); } catch (e) { hasAdmin = false; }
  var hasData = false;
  try { hasData = (typeof AnalyticsData !== "undefined"); } catch (e) { hasData = false; }

  if (!hasAdmin && !hasData) {
    throw new Error(
      "【事前準備が未完了です】Analytics系のサービスが1つも追加されていません。\n" +
      "次のどちらかを行ってから、もう一度 runConfigAudit を実行してください。\n" +
      "  A（簡単）runGroundTruth を動かした Apps Script プロジェクトに、このスクリプトを追加する\n" +
      "  B  「サービス（＋）」から Google Analytics Admin API（識別子 AnalyticsAdmin）を追加する\n" +
      "※ 追加直後の初回実行では、権限の再承認を求められます。必ず承認してください。\n" +
      "※ これは GA4 側の閲覧権限の問題ではありません。");
  }
  // 実際に1回呼んでスコープの付与を確実にする（失敗しても続行してよい）
  try {
    if (hasAdmin) { AnalyticsAdmin.Properties.get("properties/" + GTC_PROPERTIES[0]); }
  } catch (e) { /* 権限が無い場合は後段の個別エラーで拾う */ }
}

function gtcFetch_(url, options, errs, label, optional) {
  options = options || {};
  options.headers = { Authorization: "Bearer " + ScriptApp.getOAuthToken() };
  options.muteHttpExceptions = true;
  var res = UrlFetchApp.fetch(url, options);
  var code = res.getResponseCode();
  var text = res.getContentText();
  if (code === 200) {
    try { return JSON.parse(text); } catch (e) { errs.push([label, "JSON解析に失敗: " + e]); return null; }
  }
  // 404 は「その設定が存在しない」ことが多いので、エラーではなく空として扱う
  if (code === 404) return null;
  // スコープ不足は全件同じ結果になるため、1件目で止めて原因を明示する
  if (code === 403 && text.indexOf("insufficient authentication scopes") >= 0) {
    // 補助的な項目（optional）は、権限不足でも全体を止めない
    if (optional) { errs.push([label, "スコープ不足のため取得できませんでした（この項目だけ analytics.edit が必要です）。他の項目は取得できています。変更履歴も必要な場合は appsscript.json の oauthScopes に https://www.googleapis.com/auth/analytics.edit を追記して再承認してください。"]); return null; }
    throw new Error(
      "【OAuthスコープが不足しています】Analytics のAPIを呼ぶ権限がスクリプトに付与されていません。\n" +
      "  A（簡単）runGroundTruth を動かした Apps Script プロジェクトに、このスクリプトを追加する\n" +
      "  B  「サービス（＋）」から Google Analytics Admin API（識別子 AnalyticsAdmin）を追加し、\n" +
      "      実行時に表示される権限の再承認を承認する\n" +
      "※ これは GA4 側の閲覧権限の問題ではありません（GA4の権限は足りています）。" + "  C（確実）appsscript.json の oauthScopes に https://www.googleapis.com/auth/analytics.readonly を追記して再承認する。" + "  まず showGrantedScopes を実行すると、実際に付与されているスコープが分かります。");
  }
  errs.push([label, "HTTP " + code + " " + text.slice(0, 300)]);
  return null;
}

function gtcGet_(url, errs, label, optional) {
  return gtcFetch_(url, { method: "get" }, errs, label, optional);
}

function gtcPost_(url, body, errs, label, optional) {
  return gtcFetch_(url, {
    method: "post", contentType: "application/json", payload: JSON.stringify(body)
  }, errs, label, optional);
}

function gtcB_(v) { return v === true ? "ON" : (v === false ? "OFF" : "―"); }

function gtcTail_(name) {
  if (!name) return "";
  var p = String(name).split("/");
  return p[p.length - 1];
}

function gtcResourceLabel_(ch) {
  var a = ch.resourceAfterChange || {};
  var b = ch.resourceBeforeChange || {};
  function label(o) {
    if (!o) return "";
    if (o.keyEvent)        return "キーイベント: " + (o.keyEvent.eventName || "");
    if (o.conversionEvent) return "CVイベント: " + (o.conversionEvent.eventName || "");
    if (o.googleAdsLink)   return "広告リンク: " + (o.googleAdsLink.customerId || "");
    if (o.dataStream)      return "ストリーム: " + (o.dataStream.displayName || "");
    if (o.property)        return "プロパティ: " + (o.property.displayName || "");
    if (o.enhancedMeasurementSettings) return "拡張計測機能";
    if (o.customDimension) return "カスタムディメンション: " + (o.customDimension.displayName || "");
    return JSON.stringify(o).slice(0, 120);
  }
  var la = label(a), lb = label(b);
  if (la && lb && la !== lb) return lb + " → " + la;
  return la || lb || "";
}

function gtcWho_() {
  try { return Session.getActiveUser().getEmail() || "（取得できず）"; }
  catch (e) { return "（取得できず）"; }
}

var _GTC_SS = null;
function gtcSS_() {
  if (_GTC_SS) return _GTC_SS;
  if (GTC_SPREADSHEET_ID && GTC_SPREADSHEET_ID.indexOf("＜") < 0) {
    try {
      var byId = SpreadsheetApp.openById(GTC_SPREADSHEET_ID);
      byId.getName(); _GTC_SS = byId; return _GTC_SS;
    } catch (e) {
      Logger.log("指定されたスプレッドシートを開けませんでした（権限が無い可能性）。代わりの書き出し先を探します。\n" + e);
    }
  }
  try {
    var active = SpreadsheetApp.getActiveSpreadsheet();
    if (active) { active.getName(); _GTC_SS = active; return _GTC_SS; }
  } catch (e) { /* スタンドアロンの場合 */ }
  _GTC_SS = SpreadsheetApp.create("GroundTruth_GA4設定監査_"
    + Utilities.formatDate(new Date(), "Asia/Tokyo", "yyyyMMdd_HHmm"));
  Logger.log("新しいスプレッドシートを作成しました。\n  " + _GTC_SS.getUrl());
  return _GTC_SS;
}

function gtcWrite_(name, values) {
  var ss = gtcSS_();
  var sh = ss.getSheetByName(name);
  if (sh) { sh.clear(); } else { sh = ss.insertSheet(name); }
  if (!values.length) values = [["データがありません"]];
  if (values.length === 1) values.push(values[0].map(function () { return ""; }));
  var w = 0;
  values.forEach(function (r) { if (r.length > w) w = r.length; });
  values = values.map(function (r) {
    var c = r.slice();
    while (c.length < w) c.push("");
    return c.map(function (v) { return (v === null || v === undefined) ? "" : v; });
  });
  sh.getRange(1, 1, values.length, w).setValues(values);
  sh.getRange(1, 1, 1, w).setFontWeight("bold").setBackground("#1F497D").setFontColor("#FFFFFF");
  sh.setFrozenRows(1);
  sh.autoResizeColumns(1, w);
}

function gtcNote_(name, text) {
  var sh = gtcSS_().getSheetByName(name);
  if (!sh) return;
  var r = sh.getLastRow() + 2;
  sh.getRange(r, 1).setValue(text).setFontColor("#808080").setWrap(true);
}
