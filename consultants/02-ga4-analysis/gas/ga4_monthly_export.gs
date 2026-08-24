/**
 * GA4月次分析用データ取得（汎用公開版）
 * 事前にGoogle Apps Scriptの「サービス」で Google Analytics Data API を追加してください。
 * 実際のIDはGitへコミットしないでください。
 */
const CONFIG = {
  spreadsheetId: "", // 空ならこのスクリプトを紐づけたSpreadsheetを使用
  propertyId: "000000000",
  current: { start: "2026-07-01", end: "2026-07-31" },
  previous: { start: "2026-06-01", end: "2026-06-30" },
  conversionEvents: ["generate_lead"],
  rowLimit: 100000
};

function runMonthlyExport() {
  validateConfig_();
  const reports = [
    { sheet: "01_channel", dimensions: ["sessionDefaultChannelGroup"] },
    { sheet: "02_source_medium", dimensions: ["sessionSourceMedium"] },
    { sheet: "03_landing_page", dimensions: ["landingPagePlusQueryString"] },
    { sheet: "04_page", dimensions: ["pagePath"] },
    { sheet: "05_device", dimensions: ["deviceCategory"] },
    { sheet: "06_events", dimensions: ["eventName"] }
  ];
  reports.forEach(function(spec) {
    const rows = [["period"].concat(spec.dimensions).concat(["sessions", "totalUsers", "conversions", "engagementRate"])];
    rows.push.apply(rows, fetchPeriod_("current", CONFIG.current, spec.dimensions));
    rows.push.apply(rows, fetchPeriod_("previous", CONFIG.previous, spec.dimensions));
    writeSheet_(spec.sheet, rows);
  });
  writeReadme_();
}

function fetchPeriod_(label, period, dimensions) {
  const request = {
    dateRanges: [{ startDate: period.start, endDate: period.end }],
    dimensions: dimensions.map(function(name) { return { name: name }; }),
    metrics: ["sessions", "totalUsers", "conversions", "engagementRate"].map(function(name) { return { name: name }; }),
    limit: CONFIG.rowLimit
  };
  const response = AnalyticsData.Properties.runReport(request, "properties/" + CONFIG.propertyId);
  return (response.rows || []).map(function(row) {
    const dims = (row.dimensionValues || []).map(function(v) { return v.value || ""; });
    const mets = (row.metricValues || []).map(function(v) { return v.value || "0"; });
    return [label].concat(dims).concat(mets);
  });
}

function writeSheet_(name, values) {
  const ss = CONFIG.spreadsheetId ? SpreadsheetApp.openById(CONFIG.spreadsheetId) : SpreadsheetApp.getActiveSpreadsheet();
  let sheet = ss.getSheetByName(name);
  if (!sheet) sheet = ss.insertSheet(name);
  sheet.clearContents();
  if (values.length) sheet.getRange(1, 1, values.length, values[0].length).setValues(values);
  sheet.setFrozenRows(1);
}

function writeReadme_() {
  writeSheet_("00_README", [
    ["項目", "値"],
    ["propertyId", CONFIG.propertyId],
    ["current", CONFIG.current.start + " - " + CONFIG.current.end],
    ["previous", CONFIG.previous.start + " - " + CONFIG.previous.end],
    ["注意", "完全に終了した期間だけを指定し、出力Excelを公開Gitへ置かないでください。"]
  ]);
}

function validateConfig_() {
  if (!/^\d+$/.test(CONFIG.propertyId) || CONFIG.propertyId === "000000000") {
    throw new Error("CONFIG.propertyIdを実際のGA4プロパティIDへ変更してください。変更後のファイルは公開Gitへコミットしないでください。");
  }
}
