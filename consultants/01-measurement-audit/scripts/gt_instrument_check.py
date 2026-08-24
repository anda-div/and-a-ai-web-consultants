# -*- coding: utf-8 -*-
"""
gt_instrument_check.py — 計測器そのものの健全性を機械検査する（GROUND TRUTH の中核）
================================================================================
「数値が正しく転記されているか」ではなく、
「その数値を produce した計測器が壊れていないか」を検査する。

レポートの数値監査は、記載値と実測値を突き合わせれば済む。だが実務で結論を壊すのは
たいてい「両方とも一致しているが、元のGA4設定が壊れている」ケースである。
本スクリプトはその検出を自動化する。

使い方:
    python gt_instrument_check.py <入力ファイル...> [--out <出力フォルダ>] [--json]

    入力は GA4 / Search Console のエクスポート（.xlsx / .csv / .tsv）を何個でも渡してよい。
    シートや列の役割はヘッダー名から自動判定する（日本語・英語の両方に対応）。

    例:
      python gt_instrument_check.py _input/GA4_data/*.xlsx --out _runs/gt

出力:
    findings.json … 検査結果（機械可読）
    findings.md   … 所見（人が読む用。そのまま報告書のドラフトに使える）

検査項目（I-01〜I-10）の定義と閾値の根拠は references/01_検査カタログ.md を参照。
"""
import sys, os, re, json, csv, math, glob, argparse, statistics
from collections import Counter, defaultdict

try:
    import openpyxl
except ImportError:
    openpyxl = None

# ============================================================================
# 列名の辞書（日本語のGASエクスポートと英語のGA4 UIエクスポートの両方を拾う）
# ============================================================================
COL = {
    "page":      ["ページパス", "ページのurl", "ページパスとスクリーンクラス", "ページ",
                  "pagepath", "page path", "page path and screen class", "landing page",
                  "ランディングページ", "pagepathplusquerystring"],
    "title":     ["ページタイトル", "pagetitle", "page title", "page title and screen class"],
    "event":     ["イベント名", "eventname", "event name"],
    "views":     ["表示回数", "pv", "pv(表示回数)", "screenpageviews", "views", "ビュー数"],
    "users":     ["ユーザー数", "アクティブユーザー", "totalusers", "activeusers",
                  "total users", "active users", "users", "ユーザー"],
    "sessions":  ["セッション", "セッション数", "sessions"],
    "eventcount":["イベント数", "発生回数", "件数", "eventcount", "event count"],
    "keyevents": ["キーイベント", "コンバージョン", "keyevents", "key events", "conversions"],
    "engtime":   ["平均エンゲージ時間", "平均エンゲージメント時間", "滞在", "滞在(秒)",
                  "userengagementduration", "average engagement time"],
    "linkdomain":["リンクドメイン", "linkdomain", "link domain"],
    "linkurl":   ["リンクurl", "linkurl", "link url"],
    "clicks":    ["クリック", "クリック数", "clicks"],
    "impr":      ["表示回数", "impressions", "表示"],
    "query":     ["クエリ", "query", "検索キーワード"],
}

# ページ読み込みで自動発火するイベント（＝二重発火の影響を受ける）
AUTO_EVENTS   = {"page_view", "first_visit", "session_start", "user_engagement", "scroll"}
# ユーザーの操作で起きるイベント（＝正常性の対照群として使う）
ACTION_EVENTS = {"click", "form_start", "form_submit", "add_to_cart", "begin_checkout",
                 "purchase", "add_payment_info", "view_item", "search", "select_item",
                 "view_search_results", "select_promotion", "share", "login", "sign_up"}
# 本来コンバージョンにしてはいけないイベント
NEVER_KEY_EVENTS = {"page_view", "first_visit", "scroll", "click", "session_start",
                    "user_engagement", "view_item", "view_search_results"}
# 内部トラフィックを疑うパスの断片
INTERNAL_HINTS = ["_preview", "preview", "/admin", "/wp-admin", "?preview", "staging", "localhost"]


def norm(s):
    return re.sub(r"[\s　_\-()（）:：]", "", str(s or "")).lower()


def match_col(header, key):
    """ヘッダー1件が COL[key] のどれかに該当するか"""
    h = norm(header)
    for cand in COL[key]:
        c = norm(cand)
        if h == c or (len(c) >= 4 and c in h):
            return True
    return False


# ============================================================================
# 入力の読み込み（xlsx / csv / tsv → 「表」のリスト）
# ============================================================================
class Table:
    def __init__(self, source, name, header, rows):
        self.source = source
        self.name = name
        self.header = [str(h or "") for h in header]
        self.rows = rows
        self.idx = {}
        for key in COL:
            for i, h in enumerate(self.header):
                if match_col(h, key):
                    self.idx.setdefault(key, i)

    def has(self, *keys):
        return all(k in self.idx for k in keys)

    def col(self, key, row):
        i = self.idx.get(key)
        return row[i] if i is not None and i < len(row) else None

    def num(self, key, row):
        v = self.col(key, row)
        if v is None or v == "":
            return None
        try:
            return float(str(v).replace(",", "").replace("%", "").strip())
        except ValueError:
            return None

    def __repr__(self):
        return f"<Table {os.path.basename(self.source)}::{self.name} cols={list(self.idx)}>"


def _clean(rows):
    """先頭の説明行を読み飛ばして、ヘッダー行から始まる表にする"""
    out = []
    for r in rows:
        if r is None:
            continue
        vals = [("" if c is None else c) for c in r]
        if any(str(v).strip() for v in vals):
            out.append(vals)
    return out


def load_tables(paths):
    tables = []
    for path in paths:
        ext = os.path.splitext(path)[1].lower()
        if ext in (".xlsx", ".xlsm"):
            if openpyxl is None:
                print(f"  ! openpyxl が無いため読めません: {path}", file=sys.stderr); continue
            wb = openpyxl.load_workbook(path, data_only=True, read_only=True)
            for ws in wb.worksheets:
                rows = _clean(list(ws.iter_rows(values_only=True)))
                tables += _split_blocks(path, ws.title, rows)
            wb.close()
        elif ext in (".csv", ".tsv", ".txt"):
            delim = "\t" if ext == ".tsv" else ","
            with open(path, encoding="utf-8-sig", errors="replace") as f:
                rows = _clean(list(csv.reader(f, delimiter=delim)))
            tables += _split_blocks(path, os.path.basename(path), rows)
        else:
            print(f"  - スキップ（未対応の拡張子）: {path}", file=sys.stderr)
    return tables


def _split_blocks(source, name, rows):
    """1シートに複数の表が縦に並んでいる場合（GASの出力でよくある）に分割する"""
    blocks, cur_head, cur_rows = [], None, []

    def is_header(r):
        hit = sum(1 for h in r if any(match_col(h, k) for k in COL))
        return hit >= 2

    for r in rows:
        if is_header(r):
            if cur_head and cur_rows:
                blocks.append(Table(source, name, cur_head, cur_rows))
            cur_head, cur_rows = r, []
        elif cur_head is not None:
            cur_rows.append(r)
    if cur_head and cur_rows:
        blocks.append(Table(source, name, cur_head, cur_rows))
    return blocks


# ============================================================================
# 統計ヘルパ
# ============================================================================
def binom_tail_log10(k, n, p=0.5):
    """n回中k回以上が起きる確率の log10（両側ではなく上側）。桁で示すために使う。"""
    if n == 0:
        return 0.0
    total = -math.inf
    for i in range(k, n + 1):
        lg = (math.lgamma(n + 1) - math.lgamma(i + 1) - math.lgamma(n - i + 1)
              + i * math.log(p) + (n - i) * math.log(1 - p))
        total = lg if total == -math.inf else max(total, lg) + math.log1p(math.exp(min(0.0, -abs(total - lg))))
    return total / math.log(10)


def human_odds(log10p):
    if log10p >= -1:
        return "偶然でも起こりうる"
    n = int(round(-log10p))
    return f"偶然に起こる確率は約 1/10^{n}"


# ============================================================================
# 検査本体
# ============================================================================
class Findings:
    def __init__(self):
        self.items = []

    def add(self, code, level, title, detail, evidence=None, howto=None, direction=None):
        self.items.append({
            "code": code, "level": level, "title": title, "detail": detail,
            "evidence": evidence or {}, "howto": howto, "direction": direction,
        })

    def ok(self, code, title, detail, evidence=None):
        self.items.append({"code": code, "level": "正常", "title": title,
                           "detail": detail, "evidence": evidence or {}})


def pick(tables, *keys, min_rows=3):
    """必要な列をすべて持つ表を、行数の多い順に返す"""
    cands = [t for t in tables if t.has(*keys) and len(t.rows) >= min_rows]
    return sorted(cands, key=lambda t: -len(t.rows))


# ---------------------------------------------------------------- I-01 / I-02
def check_double_fire(tables, F):
    cands = pick(tables, "page", "views", "users")
    if not cands:
        F.add("I-01", "未検査", "page_view の二重発火",
              "ページ別のPV・ユーザー数の表が見つからなかったため検査できていない。"
              "GA4「レポート → エンゲージメント → ページとスクリーン」のエクスポートが必要。")
        return None
    # 集計期間の違う表が混ざっていることがあるため、候補表をすべて個別に検査する
    results = []
    for t in cands:
        pv, us = Counter(), Counter()
        for r in t.rows:
            p_, v_, u_ = t.col("page", r), t.num("views", r), t.num("users", r)
            if not p_ or v_ is None or u_ is None:
                continue
            pv[str(p_)] += int(v_); us[str(p_)] += int(u_)
        pages = [k for k in pv if us[k] > 0]
        if len(pages) < 20:
            continue
        ratios = sorted(pv[k] / us[k] for k in pages)
        med = statistics.median(ratios)
        exact2 = sum(1 for k in pages if abs(pv[k] / us[k] - 2.0) < 1e-9)
        even = sum(1 for k in pages if pv[k] % 2 == 0)
        n = len(pages)
        log10p = binom_tail_log10(even, n)
        bands = [("PV 1-3", 1, 3), ("PV 4-9", 4, 9), ("PV 10-49", 10, 49),
                 ("PV 50-199", 50, 199), ("PV 200+", 200, 10**9)]
        band_rows = []
        for label, lo, hi in bands:
            sub = [k for k in pages if lo <= pv[k] <= hi]
            if sub:
                e = sum(1 for k in sub if pv[k] % 2 == 0)
                band_rows.append({"帯": label, "ページ数": len(sub), "偶数": e,
                                  "偶数率": f"{100*e/len(sub):.0f}%"})
        suspect = (med >= 1.8 and even / n >= 0.70) or exact2 >= n * 0.25
        results.append({
            "表": f"{os.path.basename(t.source)}::{t.name}",
            "ページ数": n, "1ユーザーあたりビュー数の中央値": round(med, 2),
            "ちょうど2.00のページ数": exact2, "表示回数が偶数のページ数": even,
            "偶数の割合": f"{100*even/n:.1f}%", "偶数偏りのlog10p": round(log10p, 1),
            "規模帯別の偶奇": band_rows, "判定": "二重発火の疑い" if suspect else "所見なし",
            "_pv": pv, "_us": us, "_suspect": suspect, "_log10p": log10p,
            "_med": med, "_even": even, "_n": n, "_exact2": exact2,
        })
    if not results:
        F.add("I-01", "未検査", "page_view の二重発火",
              "ページ数が少なく、分布による判定ができなかった。")
        return None

    hits = [r for r in results if r["_suspect"]]
    ev = {"検査した表": [{k: v for k, v in r.items() if not k.startswith("_")} for r in results]}
    if hits:
        h = max(hits, key=lambda r: r["_n"])
        F.add("I-01", "重大", "page_view が二重に発火している疑いが強い",
              f"全{h['_n']}ページのうち{h['_even']}ページ（{100*h['_even']/h['_n']:.1f}%）で表示回数が偶数。"
              f"1ユーザーあたりのビュー数は中央値{h['_med']:.2f}で、ちょうど2.00のページが{h['_exact2']}件ある。"
              "通常のサイトではほとんどのページが1.0〜1.4に収まり、"
              "「1人が1回だけ見た＝PV1」という奇数が最頻値になるため、この分布は自然な閲覧行動では説明できない。"
              f"偶数への偏りは{human_odds(h['_log10p'])}。"
              f"（判定に使った表：{h['表']}）",
              evidence=ev,
              howto="GA4「レポート → リアルタイム」を開いた状態で、別のタブでサイトのページを1回だけ開く。"
                    "「イベント数（イベント名別）」で page_view が2カウントされれば確定（30秒）。",
              direction="GTMの「GA4設定タグ」と「GA4イベントタグ（page_view）」が両方 All Pages で発火していないか、"
                        "テーマに gtag が直書きされていてGTMからも送っていないか、"
                        "Shopify等のチャネルアプリと併用していないかを確認する。"
                        "修正までは PV・エンゲージメント率・直帰率をレポートに載せない。")
        best = h
    else:
        F.ok("I-01", "page_view の二重発火は検出されなかった",
             "候補の表すべてで、分布に二重発火の兆候は見られなかった。", ev)
        best = max(results, key=lambda r: r["_n"])
    return {"pv": best["_pv"], "us": best["_us"], "suspect": best["_suspect"]}


def check_event_ratio(tables, F, pageinfo):
    """自動発火イベントと操作起因イベントの「1人あたり」を比べる（二重発火の裏づけ）"""
    # サイト全体のイベント表を使う。ページ次元を持つ表（イベント×ページ）を掴むと、
    # 同じイベント名の行が何本もあり、値が最後の1行で上書きされてしまう。
    cands = [t for t in pick(tables, "event", "users")
             if (t.has("eventcount") or t.has("views")) and not t.has("page")]
    if not cands:
        return None
    t = cands[0]
    ev = {}
    for r in t.rows:
        name = t.col("event", r)
        cnt = t.num("eventcount", r)
        if cnt is None:
            cnt = t.num("views", r)
        usr = t.num("users", r)
        if not name or cnt is None:
            continue
        # ユーザー数0の行を捨ててはいけない。「設計されているのに0件」の検出（I-04）は、
        # まさにその行を見るための検査である。
        usr = int(usr or 0)
        ev[str(name).strip()] = {"件数": int(cnt), "ユーザー": usr,
                                 "1人あたり": round(cnt / usr, 2) if usr else None}
    if not ev:
        return None
    auto = {k: v for k, v in ev.items() if k in AUTO_EVENTS}
    act  = {k: v for k, v in ev.items() if k in ACTION_EVENTS}
    detail = []
    if "session_start" in ev and "page_view" in ev:
        detail.append(f"page_view は1人あたり{ev['page_view']['1人あたり']}、"
                      f"session_start は{ev['session_start']['1人あたり']}。")
    if act:
        _r = [v["1人あたり"] for v in act.values() if v["1人あたり"] is not None]
        avg = statistics.mean(_r) if _r else 0.0
        detail.append(f"操作起因イベント（{ '・'.join(sorted(act)) }）の1人あたりは平均{avg:.2f}。")
    F.ok("I-02", "イベント種別ごとの1人あたり件数",
         ("ページ読み込みで自動発火するイベントだけが突出していれば二重発火、"
          "全イベントが一様に倍なら計測が2セット。" + " ".join(detail)),
         {"自動発火": auto, "操作起因": act, "全イベント": ev})
    return ev


# ---------------------------------------------------------------- I-03 / I-04
def check_key_events(tables, F, events, sessions=None):
    cands = pick(tables, "event", "keyevents")
    key_by_event = {}
    if cands:
        t = cands[0]
        for r in t.rows:
            name, k = t.col("event", r), t.num("keyevents", r)
            if name and k is not None:
                key_by_event[str(name).strip()] = int(k)
    # キーイベント数が0のものは「登録されていない」か「登録されているが発生0」のどちらか。
    # ここで0を混ぜると「指定されている」と誤って書いてしまうため、実際に計上された分だけを挙げる。
    # （何が登録されているかの確定には、GA4管理画面のキーイベント一覧が要る）
    bad = sorted(k for k, v in key_by_event.items() if v > 0 and k in NEVER_KEY_EVENTS)

    total_key = sum(key_by_event.values()) if key_by_event else None
    if total_key is not None and sessions:
        ratio = total_key / sessions
        if ratio > 1.0:
            F.add("I-03", "重大", "キーイベント（成果）の定義が実態と食い違っている",
                  f"キーイベントの合計 {total_key:,} 件はセッション数 {int(sessions):,} を超えており、"
                  f"1セッションあたり {ratio:.1f} 件のコンバージョンという計算になる。"
                  "この状態では成果指標として機能しない。"
                  + (f" キーイベントに指定されている自動イベント：{ '・'.join(bad) }。" if bad else ""),
                  evidence={"キーイベント合計": total_key, "セッション": int(sessions),
                            "1セッションあたり": round(ratio, 2), "本来CVでないもの": bad},
                  howto="GA4「管理 → キーイベント」の一覧を開き、page_view・first_visit・scroll・click が"
                        "オンになっていないか確認する。",
                  direction="page_view・first_visit・scroll・click をキーイベントから外す。"
                            "サンクスページをCVにしたい場合は、page_location が特定URLを含む page_view を条件に"
                            "作成イベント（例：generate_lead）を作り、そちらをキーイベントにする。"
                            "健全性の目安：キーイベント数がセッション数を超えていたら、まず設定ミス。")
        else:
            F.ok("I-03", "キーイベントの規模は妥当",
                 f"キーイベント合計 {total_key:,} 件／セッション {int(sessions):,}（{ratio:.2f}件/セッション）。",
                 {"本来CVでないもの": bad})
    elif bad:
        F.add("I-03", "重大", "本来コンバージョンでないイベントがキーイベントに指定されている",
              f"キーイベントに {'・'.join(bad)} が含まれている。"
              "キーイベントの指定は、レポートの「キーイベント数」だけでなく、Google広告の入札最適化の目標・"
              "オーディエンスの条件・アトリビューションにも同時に効く。"
              "全ページ・全訪問で発火するイベントを成果にすると、広告は「ページを開いただけの人」に向けて"
              "最適化される。",
              evidence={"本来CVでないもの": bad},
              direction="該当イベントをキーイベントから外し、実際の成果（フォーム送信・電話タップ・purchase）を"
                        "計測できるようにしたうえで登録し直す。")

    # I-04 ゼロ件イベント
    if events:
        zeros = [k for k, v in events.items() if v.get("件数", 0) == 0]
        cvlike = [k for k in zeros
                  if re.search(r"(cv\d*|conversion|contact|tel|tell|phone|call|lead|inquiry|"
                               r"電話|問合|問い合わせ|送信|完了|申込)", k, re.I)]
        if cvlike:
            F.add("I-04", "重大", "CV計測用に作られたイベントが1件も発生していない",
                  f"名前から見てコンバージョンとして設計されたイベントが0件：{ '・'.join(cvlike) }。"
                  "「成果が無い」のか「計測できていない」のかで打ち手が正反対になるため、"
                  "この2つを区別しないまま結論を出してはならない。",
                  evidence={"0件のイベント": zeros, "CVらしき0件イベント": cvlike},
                  howto="GA4「管理 → データ表示 → イベント」で該当イベントの状態を見る。"
                        "「ストリーム データが検出されませんでした」と出ていれば、1件も届いていない。",
                  direction="GTMコンテナを確認し、送信側のイベント名とGA4側の待ち受け名が一致しているかを見る"
                            "（tel_tap と tell_tap のような表記ゆれで永久に0件になることがある）。")


# ---------------------------------------------------------------- I-05
def check_funnel_population(tables, F):
    """ページ別イベントとサイト全体イベントの差＝ファネルの母集団不一致を検出する"""
    site = {}
    for t in pick(tables, "event", "eventcount"):
        if t.has("page"):
            continue
        for r in t.rows:
            name, c, u = t.col("event", r), t.num("eventcount", r), t.num("users", r)
            if name and c is not None:
                site.setdefault(str(name).strip(), {"件数": int(c),
                                                    "ユーザー": int(u) if u else None})
    bypage = defaultdict(lambda: defaultdict(lambda: [0, 0]))
    for t in pick(tables, "event", "page", "eventcount"):
        for r in t.rows:
            name, pg = t.col("event", r), t.col("page", r)
            c, u = t.num("eventcount", r), t.num("users", r)
            if not name or not pg or c is None:
                continue
            slot = bypage[str(name).strip()][str(pg).split("?")[0]]
            slot[0] += int(c); slot[1] += int(u or 0)
    if not bypage:
        F.add("I-05", "未検査", "ファネル各段の母集団一致",
              "イベント×ページの表が見つからないため検査できていない。"
              "GA4探索で「イベント名 × ページパス」を出力すると確定できる。"
              "form_start / form_submit は『イベント』レポートにしか出ないため、"
              "ページ別に分解しない限り『どのページで起きたか』は分からない。",
              direction="ファネルの各段は、必ず同じ1ページ（同じ母集団）の数字に揃えて描く。")
        return
    rows = []
    for name, pages in bypage.items():
        if name not in site:
            continue
        total = site[name]["件数"]
        top = sorted(pages.items(), key=lambda kv: -kv[1][0])
        share = top[0][1][0] / total if total else 0
        rows.append({"イベント": name, "サイト全体": total,
                     "最大ページ": top[0][0], "そのページの件数": top[0][1][0],
                     "占有率": f"{100*share:.0f}%", "発火ページ数": len(pages)})
        if name in ("form_start", "form_submit") and share < 0.9 and len(pages) > 1:
            F.add("I-05", "重大", f"{name} はサイト全体の合計であり、特定ページの数ではない",
                  f"{name} はサイト全体で{total}件だが、{len(pages)}ページに分散しており、"
                  f"最大のページ（{top[0][0]}）でも{top[0][1][0]}件（{100*share:.0f}%）にとどまる。"
                  "拡張計測機能の form_start / form_submit はフォームの種類を区別せず、"
                  "問い合わせフォームも、商品ページの『カートに追加』も、検索窓も、"
                  "フッターのメルマガ登録欄も、決済画面の入力欄も、すべて同じイベントになる。"
                  "この値をページ到達数の下段に置くと、上の集団に含まれない人が下の段に現れ、"
                  "割り算そのものが成立しない。",
                  evidence={"内訳（上位）": [{"ページ": p, "件数": v[0], "ユーザー": v[1]}
                                             for p, v in top[:12]]},
                  direction="ファネルの各段を、すべて同じ1ページの数字に統一して書き直す。")
    if rows:
        F.ok("I-05", "イベントのページ分散", "各イベントがどのページに集中しているか。", {"分散": rows})


# ---------------------------------------------------------------- I-06
def check_outbound(tables, F):
    for t in pick(tables, "linkdomain"):
        agg = Counter()
        for r in t.rows:
            d = t.col("linkdomain", r)
            c = t.num("eventcount", r) or t.num("clicks", r) or t.num("users", r)
            if d and c:
                agg[str(d)] += int(c)
        if agg:
            top = agg.most_common(10)
            F.add("I-06", "中", "外部ドメインへの離脱クリックが発生している",
                  "click（拡張計測機能の離脱クリック）は外部ドメインへのリンクでのみ発火する。"
                  "レポートが『出口』をサイト内遷移だけで集計していると、"
                  "最大の出口を丸ごと見落とす。行き先が自社の別ドメイン（EC・予約サイト等）の場合、"
                  "そのページは『CVに繋がっていない』のではなく『成果が別ドメインで計上されている』。",
                  evidence={"リンク先ドメイン上位": [{"ドメイン": d, "クリック": c} for d, c in top]},
                  direction="レポートの対象範囲（どのドメインまでを見るか）を明示し、"
                            "外部ドメインが最大の出口である場合はその旨を本文に書く。")
            return
    # linkDomain が無い場合は click のページ集中で代替検出
    for t in pick(tables, "event", "page", "eventcount"):
        clicks = Counter()
        for r in t.rows:
            if str(t.col("event", r)).strip() != "click":
                continue
            c = t.num("eventcount", r)
            if c:
                clicks[str(t.col("page", r)).split("?")[0]] += int(c)
        if clicks:
            total = sum(clicks.values()); top = clicks.most_common(1)[0]
            if top[1] / total >= 0.5:
                F.add("I-06", "中", "離脱クリックが1ページに集中している",
                      f"click {total}件のうち{top[1]}件（{100*top[1]/total:.0f}%）が {top[0]} に集中している。"
                      "そのページの主要CTAのリンク先が外部ドメインである可能性が高い。"
                      "実サイトでリンク先を確認すること。",
                      evidence={"上位": [{"ページ": p, "クリック": c} for p, c in clicks.most_common(8)]},
                      howto="GA4探索でディメンション「リンク ドメイン」を追加し、イベント名 click で絞ると確定できる。")
            return


# ---------------------------------------------------------------- I-07 / I-08
def check_internal_and_pii(tables, F, pageinfo):
    if pageinfo:
        pv, us = pageinfo["pv"], pageinfo["us"]
        odd = []
        for k in pv:
            if us[k] and pv[k] / us[k] >= 8:
                odd.append({"ページ": k, "PV": pv[k], "ユーザー": us[k],
                            "1人あたり": round(pv[k] / us[k], 1)})
        hint = [k for k in pv if any(h in k.lower() for h in INTERNAL_HINTS)]
        if odd or hint:
            F.add("I-07", "中", "内部トラフィックが除外されていない可能性がある",
                  "一般ユーザーには到達できないURL、または1人あたりの閲覧回数が極端なページが含まれている。"
                  "全体に占める比率は小さくても、ユーザー数・平均エンゲージメント時間・1人あたり閲覧数に影響する。",
                  evidence={"1人あたりが極端なページ": sorted(odd, key=lambda x: -x["1人あたり"])[:10],
                            "内部用らしきURL": hint[:10]},
                  direction="GA4の内部トラフィック除外（IPフィルタ）を設定する。")
    # PII（ページタイトルに個人名）
    for t in pick(tables, "title"):
        hits = []
        for r in t.rows:
            ttl = str(t.col("title", r) or "")
            if re.search(r"[一-龥ぁ-んァ-ヶA-Za-z]{1,8}\s*(様|さま|さん)[、,。\s]", ttl) or \
               re.search(r"(様|さん)、ありがとう", ttl):
                hits.append(ttl[:60])
        if hits:
            F.add("I-08", "留意", "ページタイトルに個人を特定しうる情報が記録されている",
                  "Googleアナリティクスの利用規約は、個人を特定できる情報の送信を禁止している。"
                  "姓のみであれば直ちに重大な違反となるかは判断が分かれるが、"
                  "意図せず個人情報が送信されている状態であることは確かである。",
                  evidence={"該当タイトル（先頭10件）": sorted(set(hits))[:10],
                            "件数": len(set(hits))},
                  direction="GA4のデータストリーム設定でページタイトルを書き換えるか、GTMでフィルタする。")
            return


# ---------------------------------------------------------------- I-09
def check_sc_coverage(tables, F):
    """Search Console：クエリ別の合計と全体値の乖離＝匿名化クエリの被覆率"""
    qtab = [t for t in pick(tables, "query", "clicks") if len(t.rows) >= 20]
    if not qtab:
        return
    t = qtab[0]
    qc = qi = 0
    for r in t.rows:
        c = t.num("clicks", r)
        i = t.num("impr", r)
        if c is not None: qc += c
        if i is not None: qi += i
    # 全体値（日別・国別など、クエリ以外の表）から合計を求める
    tot_c = tot_i = 0
    for t2 in tables:
        if t2 is t or "query" in t2.idx:
            continue
        if not t2.has("clicks"):
            continue
        c = sum(t2.num("clicks", r) or 0 for r in t2.rows)
        i = sum(t2.num("impr", r) or 0 for r in t2.rows)
        if c > tot_c:
            tot_c, tot_i = c, i
    if tot_c and qc and qc < tot_c * 0.95:
        F.add("I-09", "中", "Search Console のクエリ別データの被覆率が低い",
              f"エクスポートされたクエリの合計はクリック {int(qc):,}・表示 {int(qi):,} だが、"
              f"全体値はクリック {int(tot_c):,}・表示 {int(tot_i):,}。"
              f"クエリ別に見えているのはクリックの {100*qc/tot_c:.1f}%"
              + (f"・表示の {100*qi/tot_i:.1f}%" if tot_i else "") +
              "にとどまり、残りはGoogleの匿名化クエリである。"
              "「指名検索が中心」「非指名を取りこぼしている」といった結論は、"
              "見えている範囲の中での構成比にすぎず、実際の比率は確定できない。",
              evidence={"クエリ合計クリック": int(qc), "全体クリック": int(tot_c),
                        "被覆率(クリック)": f"{100*qc/tot_c:.1f}%"},
              direction="「クエリ別に見えているのはクリックの約N%で、残りは匿名化されている」旨を明記し、"
                        "断定を『見えている範囲では』に改める。")


# ---------------------------------------------------------------- I-10
def check_session_consistency(tables, F, events):
    """タグが2セット入っていれば session_start / first_visit も倍になる。
    ここが正常なのに page_view だけ2.00前後なら、原因は config の重複に絞れる。"""
    if not events:
        return
    ss = events.get("session_start", {})
    fv = events.get("first_visit", {})
    pvv = events.get("page_view", {})
    ev = {"session_start": ss, "first_visit": fv, "page_view": pvv}
    bad = []
    if ss.get("件数") and ss.get("ユーザー"):
        r = ss["件数"] / ss["ユーザー"]
        ev["session_startの1人あたり"] = round(r, 2)
        if r >= 1.9:
            bad.append(f"session_start が1人あたり{r:.2f}")
    if fv.get("件数") and fv.get("ユーザー"):
        r = fv["件数"] / fv["ユーザー"]
        ev["first_visitの1人あたり"] = round(r, 2)
        if r >= 1.5:
            bad.append(f"first_visit が1人あたり{r:.2f}")
    if bad:
        F.add("I-10", "重大", "計測タグ自体が2セット入っている疑い",
              "セッション開始や初回訪問まで倍になっている（" + "／".join(bad) + "）。"
              "page_view だけでなく計測全体が二重化しているため、"
              "ユーザー数・セッション数も含めて数値を使えない。",
              evidence=ev,
              direction="タグの重複を解消してから、当月データの再取得可否を確認する。")
    else:
        F.ok("I-10", "計測タグは1セットとみられる",
             "session_start・first_visit は正常な範囲。"
             "page_view だけが2.00前後に固定されている場合、原因は gtag の config 呼び出しの重複"
             "（GTMの設定タグとイベントタグの併用など）に絞り込める。", ev)


# ============================================================================
# 出力
# ============================================================================
LEVEL_ORDER = {"重大": 0, "中": 1, "留意": 2, "未検査": 3, "正常": 4}


def to_markdown(F, inputs):
    L = []
    L.append("# 計測監査 ― 計測健全性の機械検査 結果\n")
    L.append("本ファイルは `gt_instrument_check.py` の出力です。"
             "各項目は**そのまま指摘の下書き**として使えますが、"
             "確定させる前に必ず「別の説明が成り立たないか」を検討してください"
             "（references/04_対抗仮説カタログ.md）。\n")
    L.append("## 入力\n")
    for p in inputs:
        L.append(f"- `{p}`")
    L.append("")
    items = sorted(F.items, key=lambda x: (LEVEL_ORDER.get(x["level"], 9), x["code"]))
    sev = [i for i in items if i["level"] in ("重大", "中", "留意")]
    L.append(f"## 総括\n\n検出 {len(sev)} 件"
             f"（重大 {sum(1 for i in sev if i['level']=='重大')} ／ "
             f"中 {sum(1 for i in sev if i['level']=='中')} ／ "
             f"留意 {sum(1 for i in sev if i['level']=='留意')}）。\n")
    for i in items:
        L.append(f"### [{i['code']}]（{i['level']}）{i['title']}\n")
        L.append(i["detail"] + "\n")
        if i.get("evidence"):
            L.append("**根拠データ**\n")
            L.append("```json")
            L.append(json.dumps(i["evidence"], ensure_ascii=False, indent=2))
            L.append("```\n")
        if i.get("howto"):
            L.append(f"**ご自身で確認する方法**：{i['howto']}\n")
        if i.get("direction"):
            L.append(f"**修正の方向**：{i['direction']}\n")
    return "\n".join(L)


def main():
    ap = argparse.ArgumentParser(description="計測器そのものの健全性を検査する")
    ap.add_argument("inputs", nargs="+", help="GA4/SC のエクスポート（xlsx/csv/tsv）")
    ap.add_argument("--out", default=".", help="出力フォルダ")
    ap.add_argument("--json", action="store_true", help="標準出力にもJSONを出す")
    a = ap.parse_args()

    paths = []
    for pat in a.inputs:
        hit = glob.glob(pat)
        paths += hit if hit else [pat]
    paths = [p for p in paths if os.path.isfile(p)]
    if not paths:
        print("入力ファイルが見つかりません", file=sys.stderr); sys.exit(1)

    print(f"入力 {len(paths)} ファイルを読み込みます…")
    tables = load_tables(paths)
    print(f"  表を {len(tables)} 個 検出しました")

    F = Findings()
    pageinfo = check_double_fire(tables, F)
    events = check_event_ratio(tables, F, pageinfo)

    # セッション数は session_start を第一候補にする（チャネル別表の最大値などを拾わないため）
    sessions = None
    if events and "session_start" in events:
        sessions = events["session_start"]["件数"]
    if sessions is None:
        for t in tables:
            if t.has("sessions") and not t.has("page") and not t.has("event"):
                v = [x for x in (t.num("sessions", r) for r in t.rows) if x]
                if v:
                    sessions = max(v); break

    check_key_events(tables, F, events, sessions)
    check_funnel_population(tables, F)
    check_outbound(tables, F)
    check_internal_and_pii(tables, F, pageinfo)
    check_sc_coverage(tables, F)
    check_session_consistency(tables, F, events)

    os.makedirs(a.out, exist_ok=True)
    with open(os.path.join(a.out, "findings.json"), "w", encoding="utf-8") as f:
        json.dump({"inputs": paths, "findings": F.items}, f, ensure_ascii=False, indent=2)
    md = to_markdown(F, paths)
    with open(os.path.join(a.out, "findings.md"), "w", encoding="utf-8") as f:
        f.write(md)

    sev = [i for i in F.items if i["level"] in ("重大", "中", "留意")]
    print(f"\n検出 {len(sev)} 件")
    for i in sorted(sev, key=lambda x: LEVEL_ORDER.get(x["level"], 9)):
        print(f"  [{i['code']}] {i['level']}  {i['title']}")
    un = [i for i in F.items if i["level"] == "未検査"]
    for i in un:
        print(f"  [{i['code']}] 未検査  {i['title']}")
    print(f"\n出力: {os.path.join(a.out, 'findings.md')} / findings.json")
    if a.json:
        print(json.dumps(F.items, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
