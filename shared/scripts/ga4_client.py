# -*- coding: utf-8 -*-
r"""GA4 のデータを取りに行くための共通部品

**案件ごとに違うもの（どのシートを、どの指標で作るか）はここに書かない。**
ここにあるのは、どの案件でも同じになる部分だけ。

    ・認証とセキュリティソフト対策
    ・問い合わせのページ送り
    ・一時的な失敗の待ち直し
    ・GAS と同じ丸め方
    ・xlsx への書き出し

案件側は、これを使って「シートを作る関数」だけを書く。

    import ga4_client as G

    api = G.GA4("123456789")
    rows = api.report("2026-07-01", "2026-07-31",
                      ["sessionSource"], ["sessions"], order_metric="sessions")
    sheets = {"流入元": [["ソース", "セッション"]] +
                        [[G.dim(r, 0), G.to_int(G.met(r, 0))] for r in rows]}
    G.write_xlsx("out.xlsx", sheets)

**GASから乗り換えるときは、必ず全セルで突き合わせること。**
合計が合っていても、丸め・並び・表記が違えば下流が変わる。
手順は shared/GA4_LOCAL_FETCH.md、比較は shared/scripts/compare_xlsx.py。
"""
from __future__ import annotations

import math
import os
import sys
import time
from datetime import date, timedelta

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# セキュリティソフトが HTTPS を検査している PC でも通るようにする。
# 検査されていない PC では何もしない。理由は tls_env.py に書いてある。
try:
    import tls_env
    tls_env.enable()
except ImportError:      # 単体で持ち出したときも動くようにする
    pass

SCOPES = ["https://www.googleapis.com/auth/analytics.readonly"]


# ---------------------------------------------------------------- 丸め
def js_round(x: float) -> int:
    """JavaScript の Math.round と同じ丸め方。

    GAS の出力に一致させるために要る。0.5 の扱いが両者で違う。

      JavaScript  Math.round(6.25 * 10) = 63  → 6.3   （0.5 は必ず切り上げ）
      Python      round(62.5)           = 62  → 6.2   （0.5 は偶数側へ）

    この差は 0.1 だが、直帰率などの列にそのまま出る。実際、ある案件では
    5,714セル中4セルがこれだけの理由で食い違った。合計は完全に一致するため、
    セル単位で比べなければ気づけない。
    負の数も JavaScript に合わせて +∞ 方向へ倒す（Math.round(-2.5) = -2）。
    """
    return math.floor(x + 0.5)


def round1(v) -> float:
    """小数第1位まで。GAS の round1_ に相当。"""
    return js_round(float(v) * 10) / 10


def to_int(v) -> int:
    """整数へ。GAS の Math.round(...) に相当。"""
    return js_round(float(v))


def pct(v) -> float:
    """比率（0〜1）を % にして小数第1位まで。"""
    return round1(float(v) * 100)


def delta(cur, prev, up="▲", down="▼") -> str:
    """前月比。記号は案件の表記に合わせて変えられる。"""
    if not prev:
        return ""
    d = round1((cur - prev) / prev * 100)
    return (up if d >= 0 else down) + f"{abs(d)}".rstrip("0").rstrip(".") + "%"


# ---------------------------------------------------------------- 期間
def month_range(period: str) -> tuple[str, str]:
    """'2026-06' → ('2026-06-01', '2026-06-30')"""
    y, m = int(period[:4]), int(period[5:7])
    first = date(y, m, 1)
    nxt = date(y + (m == 12), (m % 12) + 1, 1)
    return first.isoformat(), (nxt - timedelta(days=1)).isoformat()


def shift(period: str, months: int) -> str:
    """'2026-06' の n か月前後を返す。"""
    y, m = int(period[:4]), int(period[5:7])
    total = y * 12 + (m - 1) + months
    return f"{total // 12:04d}-{total % 12 + 1:02d}"


# ---------------------------------------------------------------- API
class GA4:
    """GA4 Data API の薄い包み。GAS の runReport_ と同じふるまいにする。"""

    # 一度でも落ちると月次の取得がまるごと止まるので、待って数回やり直す。
    # 504（時間切れ）と 503（一時的な不調）は、混み具合で普通に起きる。
    RETRY_ON = ("DeadlineExceeded", "ServiceUnavailable", "InternalServerError",
                "ResourceExhausted", "TooManyRequests")
    TRIES = 4
    TIMEOUT = 300.0        # 秒。行数の多い問い合わせに合わせる

    def __init__(self, property_id: str):
        from google.analytics.data_v1beta import BetaAnalyticsDataClient
        self.client = BetaAnalyticsDataClient()
        self.property = f"properties/{property_id}"

    def _call(self, req):
        last = None
        for i in range(self.TRIES):
            try:
                return self.client.run_report(req, timeout=self.TIMEOUT)
            except Exception as e:
                last = e
                if type(e).__name__ not in self.RETRY_ON or i == self.TRIES - 1:
                    raise
                wait = 5 * (2 ** i)          # 5秒 → 10秒 → 20秒
                print(f"      {type(e).__name__}。{wait}秒待って"
                      f"やり直します（{i + 1}/{self.TRIES - 1}）")
                time.sleep(wait)
        raise last

    def report(self, start, end, dimensions=None, metrics=None, *,
               order_metric=None, order_dim=None, desc=True,
               dimension_filter=None, limit=100000):
        """全ページを取り切って行を返す（GAS と同じくページ送りする）。"""
        from google.analytics.data_v1beta.types import (
            DateRange, Dimension, Metric, OrderBy, RunReportRequest)

        dimensions = dimensions or []
        metrics = metrics or []
        order_bys = []
        if order_metric:
            order_bys = [OrderBy(
                metric=OrderBy.MetricOrderBy(metric_name=order_metric), desc=desc)]
        elif order_dim:
            order_bys = [OrderBy(
                dimension=OrderBy.DimensionOrderBy(dimension_name=order_dim),
                desc=False)]

        out, offset = [], 0
        while True:
            req = RunReportRequest(
                property=self.property,
                date_ranges=[DateRange(start_date=start, end_date=end)],
                dimensions=[Dimension(name=d) for d in dimensions],
                metrics=[Metric(name=m) for m in metrics],
                order_bys=order_bys,
                limit=limit, offset=offset, keep_empty_rows=False,
                dimension_filter=dimension_filter,
            )
            res = self._call(req)
            rows = list(res.rows)
            out.extend(rows)
            offset += len(rows)
            if not rows or offset >= (res.row_count or len(rows)) or len(rows) < limit:
                break
        return out

    def totals(self, start, end, metrics):
        """絞り込みなしの合計。指標の並び順で返す。"""
        rows = self.report(start, end, [], metrics)
        if not rows:
            return [0.0] * len(metrics)
        return [float(v.value) for v in rows[0].metric_values]

    def event_count(self, start, end, event_name) -> int:
        """1つのイベントの発生回数。"""
        rows = self.report(start, end, ["eventName"], ["eventCount"],
                           dimension_filter=event_filter(event_name))
        return to_int(rows[0].metric_values[0].value) if rows else 0


# ---------------------------------------------------------------- 絞り込み
#
# GAS は絞り込み条件を素のJSONで書く。Python のライブラリは型で書く。
# 対応が付きやすいよう、GAS と同じ組み立て方ができる部品を用意する。
#
#   GAS   { andGroup: { expressions: [ A, B ] } }
#   Python  f_and(A, B)
#
# これがないと、案件ごとに import と入れ子を書き直すことになる。

def _sf(field: str, match: str, value: str, case_sensitive: bool = False):
    from google.analytics.data_v1beta.types import Filter, FilterExpression
    mt = getattr(Filter.StringFilter.MatchType, match)
    return FilterExpression(filter=Filter(
        field_name=field,
        string_filter=Filter.StringFilter(
            match_type=mt, value=value, case_sensitive=case_sensitive)))


def f_exact(field: str, value: str, case_sensitive: bool = False):
    """完全一致。GAS の matchType: 'EXACT'"""
    return _sf(field, "EXACT", value, case_sensitive)


def f_contains(field: str, value: str, case_sensitive: bool = False):
    """部分一致。GAS の matchType: 'CONTAINS'"""
    return _sf(field, "CONTAINS", value, case_sensitive)


def f_begins(field: str, value: str, case_sensitive: bool = False):
    """前方一致。GAS の matchType: 'BEGINS_WITH'"""
    return _sf(field, "BEGINS_WITH", value, case_sensitive)


def f_ends(field: str, value: str, case_sensitive: bool = False):
    """後方一致。GAS の matchType: 'ENDS_WITH'"""
    return _sf(field, "ENDS_WITH", value, case_sensitive)


def f_regex(field: str, pattern: str, case_sensitive: bool = False):
    """正規表現の完全一致。GAS の matchType: 'FULL_REGEXP'

    GAS 側が `.*banner.*|.*cpc.*` のように全体一致で書いていることが多い。
    部分一致のつもりで移すと結果が変わるので、GASの綴りをそのまま持ってくる。
    """
    return _sf(field, "FULL_REGEXP", pattern, case_sensitive)


def f_in(field: str, values, case_sensitive: bool = False):
    """いずれかに一致。GAS の inListFilter"""
    from google.analytics.data_v1beta.types import Filter, FilterExpression
    return FilterExpression(filter=Filter(
        field_name=field,
        in_list_filter=Filter.InListFilter(
            values=list(values), case_sensitive=case_sensitive)))


def f_and(*exprs):
    """すべてを満たす。GAS の andGroup"""
    from google.analytics.data_v1beta.types import (
        FilterExpression, FilterExpressionList)
    keep = [e for e in exprs if e is not None]
    if len(keep) == 1:
        return keep[0]
    return FilterExpression(and_group=FilterExpressionList(expressions=keep))


def f_or(*exprs):
    """いずれかを満たす。GAS の orGroup"""
    from google.analytics.data_v1beta.types import (
        FilterExpression, FilterExpressionList)
    keep = [e for e in exprs if e is not None]
    if len(keep) == 1:
        return keep[0]
    return FilterExpression(or_group=FilterExpressionList(expressions=keep))


def f_not(expr):
    """満たさない。GAS の notExpression"""
    from google.analytics.data_v1beta.types import FilterExpression
    return FilterExpression(not_expression=expr)


def event_filter(event_name: str):
    """イベント名の完全一致で絞り込む条件を作る。"""
    return f_exact("eventName", event_name)


def dim(row, i):
    """行の i 番目のディメンション値。"""
    return row.dimension_values[i].value


def met(row, i):
    """行の i 番目の指標値（数値）。"""
    return float(row.metric_values[i].value)


# ---------------------------------------------------------------- 書き出し
def write_xlsx(path: str, sheets) -> None:
    """{シート名: 2次元配列} を xlsx に落とす。

    シートの並びは渡した順。GASの出力と同じ順にすること。
    """
    import openpyxl

    wb = openpyxl.Workbook()
    wb.remove(wb.active)
    for name, rows in (sheets.items() if hasattr(sheets, "items") else sheets):
        ws = wb.create_sheet(title=str(name)[:31])
        for r in rows:
            ws.append(list(r))
    d = os.path.dirname(os.path.abspath(path))
    if d:
        os.makedirs(d, exist_ok=True)
    wb.save(path)


# ---------------------------------------------------------------- 認証
def check_auth(scopes=None) -> int:
    """認証が通っているかだけを確かめる。設定を案内するために使う。"""
    sys.stdout.reconfigure(encoding="utf-8")
    try:
        import google.auth
        creds, project = google.auth.default(scopes=scopes or SCOPES)
        print("認証情報: 見つかりました")
        print(f"  種類          : {type(creds).__name__}")
        print(f"  プロジェクト  : {project or '（未設定）'}")
        return 0
    except Exception as e:
        print("認証情報が見つかりません。")
        print(f"  {type(e).__name__}: {e}")
        print()
        print("次を一度だけ実行してください（PCごとに1回。案件ごとには不要）。")
        print("  shared\\scripts\\adc_login.cmd <プロジェクトID>")
        print()
        print("素の gcloud ではなく shared\\scripts\\gcloud.cmd を使ってください。")
        print("セキュリティソフトがHTTPSを検査しているPCでは、素の gcloud は")
        print("証明書の検証で止まります（理由は tls_env.py に書いてあります）。")
        return 1


if __name__ == "__main__":
    raise SystemExit(check_auth())
