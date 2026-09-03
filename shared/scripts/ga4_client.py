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


# ------------------------------------------------------------ クォータの見張り
#
# GA4 Data API は「1時間あたりのトークン」で頭を押さえてくる。案件によっては
# 月次の取得が数百本になり、**正しく書けていても途中で 429 で止まる**。
#
#   Exhausted property tokens for a project per hour.
#
# 待てば戻るので、失敗として捨てないこと。残りトークンは応答に入れてもらえる
# （returnPropertyQuota）ので、それを見て自分で速度を落とす。
#
# しきい値を残り 60 にしているのは、1本が十数トークンかかることがあるため。
# 0 まで使い切ってから待つと、待っている間に他の呼び出しが 429 を踏む。

class Quota:
    """残りトークンを覚えておき、少なくなったら次の時間帯まで待つ。

    **枠は用途ごとに分かれている。** `runReport` と `runFunnelReport` は
    別の枠を使い、ふつうはファネル側が先に尽きる。ひとまとめに扱うと、
    ファネルが尽きただけで runReport まで止まってしまい、進めるはずの
    シートが進まなくなる。**レーンを分けて数える。**
    """

    FLOOR = 60          # これを下回ったら待つ
    NAP = 300           # 待つ長さ（秒）。トークンは1時間未満で戻る

    # 見るバケット。**プロジェクト単位の1時間分がいちばん先に尽きる。**
    # 「Exhausted property tokens for a project per hour」はこれ。
    BUCKETS = ("tokensPerProjectPerHour", "tokens_per_project_per_hour",
               "tokensPerHour", "tokens_per_hour",
               "tokensPerDay", "tokens_per_day")

    def __init__(self):
        import threading
        self.lock = threading.Lock()
        self.left = {}      # レーン名 -> 直近に見えた残り
        self.waited = {}

    def update(self, pq, lane="report") -> None:
        """応答の propertyQuota から、いちばん残りの少ないトークンを覚える。"""
        if not pq:
            return
        vals = []
        for key in self.BUCKETS:
            v = pq.get(key) if isinstance(pq, dict) else getattr(pq, key, None)
            if v is None:
                continue
            r = (v.get("remaining") if isinstance(v, dict)
                 else getattr(v, "remaining", None))
            if r is not None:
                vals.append(int(r))
        if vals:
            with self.lock:
                self.left[lane] = min(vals)

    def wait_if_low(self, lane="report", log=print) -> None:
        while True:
            with self.lock:
                left = self.left.get(lane)
            if left is None or left > self.FLOOR:
                return
            log(f"      [{lane}] 残りトークンが {left}。"
                f"{self.NAP // 60}分待ちます", flush=True)
            time.sleep(self.NAP)
            with self.lock:
                self.left[lane] = None      # 待ったので、次の応答で見直す
                self.waited[lane] = self.waited.get(lane, 0) + 1

    def exhausted(self, lane="report", log=print) -> None:
        """429 を踏んだとき。**そのレーンだけ**まとまった時間待つ。"""
        log(f"      [{lane}] トークンを使い切りました。"
            f"{self.NAP // 60}分待ちます", flush=True)
        with self.lock:
            self.left[lane] = 0
        time.sleep(self.NAP)
        with self.lock:
            self.left[lane] = None
            self.waited[lane] = self.waited.get(lane, 0) + 1


QUOTA = Quota()


# ---------------------------------------------------------------- 認証の使い回し
#
# ファネルは素の HTTP で叩くため、呼ぶたびに access token が要る。
# 毎回 refresh すると、月次の取得で数百回の再発行になり、そこだけで数分かかる。
# 期限が切れるまでは同じものを使い回す。複数スレッドから呼ばれても
# 一度しか取り直さないよう、鍵をかける。

_CREDS = None
_CREDS_LOCK = None


def _access_token() -> str:
    """有効な access token を返す（期限が切れていれば取り直す）。"""
    global _CREDS, _CREDS_LOCK
    import threading

    import google.auth
    import google.auth.transport.requests

    if _CREDS_LOCK is None:
        _CREDS_LOCK = threading.Lock()
    with _CREDS_LOCK:
        if _CREDS is None:
            _CREDS, _ = google.auth.default(scopes=SCOPES)
        if not _CREDS.valid or _CREDS.expired:
            _CREDS.refresh(google.auth.transport.requests.Request())
        return _CREDS.token


def _is_number(v) -> bool:
    try:
        float(v)
        return True
    except (TypeError, ValueError):
        return False


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

    # クォータ切れは「混んでいる」のとは違い、待つ長さが桁で違う。
    # 分けて数え、こちらは根気よく待つ。
    # 月次1回分でファネルを数百本投げると、1時間あたりの枠に何度も当たる。
    # 5分待ちを何十回か繰り返せるだけの根気を持たせる（= 5時間ぶん）。
    QUOTA_TRIES = 60

    def _call(self, req):
        last = None
        quota_hits = 0
        i = 0
        while True:
            QUOTA.wait_if_low("report")
            try:
                res = self.client.run_report(req, timeout=self.TIMEOUT)
                QUOTA.update(getattr(res, "property_quota", None), "report")
                return res
            except Exception as e:
                last = e
                name = type(e).__name__
                if name in ("ResourceExhausted", "TooManyRequests"):
                    quota_hits += 1
                    if quota_hits > self.QUOTA_TRIES:
                        raise
                    QUOTA.exhausted("report")
                    continue
                i += 1
                if name not in self.RETRY_ON or i >= self.TRIES:
                    raise
                wait = 5 * (2 ** (i - 1))    # 5秒 → 10秒 → 20秒
                print(f"      {name}。{wait}秒待って"
                      f"やり直します（{i}/{self.TRIES - 1}）", flush=True)
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
                return_property_quota=True,
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

    # ------------------------------------------------------------ ファネル
    #
    # ファネルは runReport ではなく runFunnelReport で取る。まだ v1alpha
    # にしかなく、Python のライブラリからは呼べない。素の HTTP で叩く。
    # GAS 側も同じ理由で UrlFetchApp を使っている案件が多い。
    #
    #   GAS   UrlFetchApp.fetch(".../v1alpha/properties/N:runFunnelReport", ...)
    #   Python  api.funnel(start, end, [api.funnel_page_step(...), ...])
    #
    # ★ 対応しているのは funnelBreakdown だけで、segments は組んでいない。
    #
    # 「ある行動をしたセッションの数」のような**セッション単位の集合**は、
    # runReport の dimensionFilter では取れない。イベント単位で評価されるため、
    # eventName と pageLocation の AND は必ず 0 になる。
    # runFunnelReport の segments はセッション単位に対応しているが、ここでは未実装。
    # **代わりに、その条件をステップ1に置く**（2段のファネルにする）ことで足りる。
    #
    # ただし、ファネルで取れるのは人数・セッション数であって**収益ではない**。
    # 収益がセッション単位で必要なときは、まず item スコープで表せるかを考える
    # （itemRevenue を itemBrand / itemName で絞り、eventName を混ぜない。
    #   混ぜると「dimensions and metrics are incompatible」になる）。
    # 商品属性では表せず、行動でしか定義できない集合の収益は、APIでは取れない。
    #
    def funnel(self, start, end, steps, open_funnel: bool = False) -> list[float]:
        """ステップごとの人数を、ステップの順に返す。

        `steps` は runFunnelReport の `funnel.steps` に渡すものをそのまま。
        GAS のコードから写しやすいよう、素の dict を受け取る。
        """
        return [u for _, u in self.funnel_rows(start, end, steps, open_funnel)]

    def funnel_table(self, start, end, steps, *, open_funnel: bool = False,
                     breakdown: str | None = None,
                     breakdown_limit: int | None = None
                     ) -> list[tuple[list[str], float]]:
        """ファネルの表をそのまま返す（ディメンション値の並び, 人数）。

        `breakdown` を渡すと funnelBreakdown が付き、ステップ×その項目の
        組み合わせで返る（GAS が `funnelBreakdown` を使っている案件向け）。
        """
        return self._funnel_call(start, end, steps, open_funnel,
                                 breakdown, breakdown_limit)

    def funnel_rows(self, start, end, steps,
                    open_funnel: bool = False) -> list[tuple[str, float]]:
        """ステップごとの（名前, 人数）を、ステップの順に返す。

        名前は GA4 が返すディメンション値（「1. トップページ」のように
        番号が付く）。GAS が出力していたシートに、この名前がそのまま
        入っている案件があるため、数値だけでは足りない。

        GAS 側の取り出し方に合わせ、ディメンション値のうち
        「空でない・(not set) でない・数値でない」最初のものを名前に使う。
        見つからなければ「ステップ N」とする。
        """
        out = []
        for dims, u in self._funnel_call(start, end, steps, open_funnel,
                                         None, None):
            name = None
            for v in dims:
                if v and v != "(not set)" and not _is_number(v):
                    name = v
                    break
            out.append((name or f"ステップ {len(out) + 1}", u))
        return out

    def _funnel_call(self, start, end, steps, open_funnel,
                     breakdown, breakdown_limit):
        import requests

        url = (f"https://analyticsdata.googleapis.com/v1alpha/{self.property}"
               ":runFunnelReport")
        body = self._funnel_body(start, end, steps, open_funnel,
                                 breakdown, breakdown_limit)
        last = None
        quota_hits = 0
        i = 0
        while True:
            QUOTA.wait_if_low("funnel")
            token = _access_token()
            res = requests.post(
                url, headers={"Authorization": f"Bearer {token}"},
                json=body, timeout=self.TIMEOUT)
            if res.status_code == 200:
                try:
                    QUOTA.update(res.json().get("propertyQuota"), "funnel")
                except Exception:
                    pass
                break
            last = f"{res.status_code}: {res.text[:300]}"
            if res.status_code == 429:
                # クォータ切れ。待てば戻るので、失敗にしない。
                quota_hits += 1
                if quota_hits > self.QUOTA_TRIES:
                    raise RuntimeError(f"runFunnelReport が失敗しました（{last}）")
                QUOTA.exhausted("funnel")
                continue
            i += 1
            if res.status_code not in (500, 503, 504) or i >= self.TRIES:
                raise RuntimeError(f"runFunnelReport が失敗しました（{last}）")
            wait = 5 * (2 ** (i - 1))
            print(f"      HTTP {res.status_code}。{wait}秒待って"
                  f"やり直します（{i}/{self.TRIES - 1}）", flush=True)
            time.sleep(wait)

        # 返り方が2通りある。subReports がある版とない版。
        tbl = (res.json().get("funnelTable") or {})
        if tbl.get("subReports"):
            rows = tbl["subReports"][0].get("rows") or []
        else:
            rows = tbl.get("rows") or res.json().get("rows") or []
        out = []
        for r in rows:
            dims = [dv.get("value") for dv in (r.get("dimensionValues") or [])]
            mv = r.get("metricValues") or []
            out.append((dims, float(mv[0]["value"]) if mv else 0.0))
        return out

    @staticmethod
    def _funnel_body(start, end, steps, open_funnel, breakdown, limit):
        body = {"dateRanges": [{"startDate": start, "endDate": end}],
                "funnel": {"isOpenFunnel": bool(open_funnel), "steps": steps},
                # 残りトークンを返してもらう。これが無いと、こちらから
                # 速度を落としようがなく 429 を踏み続けることになる。
                "returnPropertyQuota": True}
        if breakdown:
            bd = {"breakdownDimension": {"name": breakdown}}
            if limit:
                bd["limit"] = limit
            body["funnelBreakdown"] = bd
        return body

    @staticmethod
    def funnel_step(name: str, expr: dict) -> dict:
        """ファネルの1ステップ。`expr` は filterExpression の中身。"""
        return {"name": name, "isDirectlyFollowedBy": False,
                "filterExpression": expr}

    @staticmethod
    def funnel_field(field: str, match: str, value: str,
                     negate: bool = False) -> dict:
        """1つの項目で絞るステップ条件。`match` は GAS と同じ名前。

            funnel_field("pageLocation", "CONTAINS", "cart_index.html")
            funnel_field("pageLocation", "FULL_REGEXP", r".*A.*", negate=True)
        """
        inner = {"funnelFieldFilter": {
            "fieldName": field,
            "stringFilter": {"matchType": match, "value": value}}}
        return {"notExpression": inner} if negate else inner

    @staticmethod
    def funnel_event(event_name: str) -> dict:
        """イベントで絞るステップ条件。"""
        return {"funnelEventFilter": {"eventName": event_name}}

    @staticmethod
    def funnel_rates(users) -> list[tuple[float, float | None, float]]:
        """人数の並びから（人数, 次への率, 通算の率）を作る。

        最後のステップの「次への率」は None。GAS が空欄にしているのに合わせる。
        """
        first = users[0] if users else 0.0
        out = []
        for i, u in enumerate(users):
            nxt = (users[i + 1] / u) if (i + 1 < len(users) and u) else None
            out.append((u, nxt, (u / first) if first else 0))
        return out


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
