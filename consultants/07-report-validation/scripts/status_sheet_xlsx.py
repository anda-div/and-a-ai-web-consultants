# -*- coding: utf-8 -*-
"""実施状況シート（Excel）── お客様が提案の状態を伝える入口

Markdown の確認シート（`ledger.py --status-sheet`）と考え方は同じで、
**こちらの理解を書き込んで出し、違うところだけ直してもらう。**
違うのは、お客様が自分で直して返せること。

    出力　ledger.py --status-sheet 2026-10 --xlsx
    取込　ledger.py --import-sheet _input/実施状況/実施状況シート_2026-10.xlsx
          （既定は違いを表示するだけ。確認を取ってから --apply で反映する）

お客様は台帳の形式も状態の名前も知らない。そこでシートには
お客様の言葉（未着手／対応中／実装済み…）だけを出し、台帳の言葉への
読み替えはここで行う。

取り込みでは**お客様の記入を正とする。** 実装したか、いつ実装したか、
なぜやらないかは、お客様しか知らないため。ただし「実装済み → 未着手」の
ような**逆戻りだけは反映せずに止める。** 記入の取り違えであることが多く、
黙って入れると、検証済みの効果まで台帳から消える。
"""
from __future__ import annotations

import hashlib
import os
import re
from datetime import date, datetime

# お客様の言葉 → 台帳の状態
SHEET_TO_LEDGER = {
    "未着手": "提案中",
    "対応中": "実装待ち",
    "実装済み": "実装済み",
    "実装済み（提案前から）": "実装済み",
    "やらない": "却下",
    "保留": "保留",
}
SHEET_STATUSES = tuple(SHEET_TO_LEDGER)
LEDGER_TO_SHEET = {"提案中": "未着手", "実装待ち": "対応中",
                   "実装済み": "実装済み", "保留": "保留", "却下": "やらない"}

# 戻ってはいけない向き。済んだものを、済んでいない状態へ戻す記入。
DONE = ("実装済み", "検証済み")
NOT_DONE = ("提案中", "実装待ち", "保留")

SHEET_NAME = "実施状況"
META_NAME = "_meta"
HEADERS = ("提案ID", "提案", "対象ページ", "提案した月", "こちらの理解",
           "状態", "実装日", "補足", "出力時の状態", "出力時の実装日")
EDITABLE = ("状態", "実装日", "補足")
HEADER_ROW = 4
BEFORE_PROPOSAL = "提案前から実装済み"


# ---------------------------------------------------------------- 出力
def rows_for(lg, unconfirmed) -> list[dict]:
    """シートに載せる提案と、こちらの理解。

    却下・検証済みは載せない（決着している）。提案前から実装済みだったものも
    載せない（前後比較をしないので、聞くことが無い）。
    """
    order = []
    for i in lg.items:
        st = i["status"]
        if st in ("却下", "検証済み") or i.get("implemented_before_proposal"):
            continue
        if st == "実装済み" and not i.get("implemented_on"):
            rank, guess = 0, "実装済みと伺っています。**実装日**をご記入ください（おおよそで構いません）"
        elif i.get("maybe_done") and st in NOT_DONE:
            note = i["maybe_done"].get("note") or "対象ページで課題が見当たりませんでした"
            rank, guess = 1, f"実装済みの可能性があります（{note}）。ご確認ください"
        elif i.get("work_done_on") and st == "実装待ち":
            rank, guess = 2, (f"当社の作業は {i['work_done_on']} に完了しています。"
                              "公開されたら、状態を「実装済み」に、公開日を実装日にご記入ください")
        elif unconfirmed(i):
            rank, guess = 3, "以前に挙がっていた提案です。いまの状況を教えてください"
        elif st == "実装待ち":
            rank, guess = 4, i.get("status_note") or "実施が決まったと理解しています"
        elif st == "提案中":
            # 状態の補足があれば、それがこちらの理解。「中身を変えて残す」と
            # お答えいただいた提案に「まだご返答をいただいていません」と出すと、
            # 聞いたことを忘れているように読める
            rank, guess = 5, i.get("status_note") or "まだご返答をいただいていません"
        elif st == "保留":
            rank, guess = 6, (f"保留（{i.get('blocked_by') or '理由未確認'}）。"
                              f"{i.get('revisit_on') or '時期未定'} ごろ再検討の予定")
        else:   # 実装済み・実装日あり
            rank, guess = 7, f"{i['implemented_on']} に実装済みと理解しています"
        order.append((rank, i["id"], i, guess))
    order.sort(key=lambda t: (t[0], t[1]))
    return [{"item": i, "guess": g} for _r, _id, i, g in order]


def export(lg, period: str, path: str, unconfirmed) -> int:
    """記入済みの実施状況シートを書き出す。戻り値は載せた件数。"""
    from openpyxl import Workbook
    from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
    from openpyxl.worksheet.datavalidation import DataValidation

    rows = rows_for(lg, unconfirmed)
    wb = Workbook()
    ws = wb.active
    ws.title = SHEET_NAME
    ws["A1"] = f"改善提案の実施状況（{period}）"
    ws["A1"].font = Font(size=14, bold=True)
    ws["A2"] = ("こちらで把握している状況を記入しています。違っているところだけ、"
                "黄色の列（状態・実装日・補足）を直してください。すべてに回答いただく必要はありません。")
    ws["A3"] = ("実装日はおおよそで構いません（例：2026-09、9月中旬）。"
                "提案より前から実装されていたものは、状態で「実装済み（提案前から）」を選んでください。")

    thin = Side(style="thin", color="BFBFBF")
    box = Border(left=thin, right=thin, top=thin, bottom=thin)
    for c, h in enumerate(HEADERS, 1):
        cell = ws.cell(row=HEADER_ROW, column=c, value=h)
        cell.font = Font(bold=True)
        cell.fill = PatternFill("solid", fgColor="D9D9D9")
        cell.border = box
    yellow = PatternFill("solid", fgColor="FFF2CC")
    wrap = Alignment(wrap_text=True, vertical="top")
    for r, row in enumerate(rows, HEADER_ROW + 1):
        i = row["item"]
        issued_status = LEDGER_TO_SHEET.get(i["status"], "")
        values = (i["id"], i["title"], i.get("target", ""), i.get("created", ""),
                  row["guess"].replace("**", ""), issued_status,
                  i.get("implemented_on") or "", "",
                  issued_status, i.get("implemented_on") or "")
        for c, v in enumerate(values, 1):
            cell = ws.cell(row=r, column=c, value=v)
            cell.alignment = wrap
            cell.border = box
            if HEADERS[c - 1] in EDITABLE:
                cell.fill = yellow
                cell.number_format = "@"   # 日付を勝手に数値へ変えさせない

    last = HEADER_ROW + max(len(rows), 1)
    dv = DataValidation(type="list", formula1='"' + ",".join(SHEET_STATUSES) + '"',
                        allow_blank=True, showDropDown=False)
    dv.error = "一覧から選んでください"
    dv.errorTitle = "状態"
    ws.add_data_validation(dv)
    col = HEADERS.index("状態") + 1
    letter = ws.cell(row=1, column=col).column_letter
    dv.add(f"{letter}{HEADER_ROW + 1}:{letter}{last + 50}")

    widths = (16, 40, 28, 10, 48, 18, 14, 30, 4, 4)
    for c, w in enumerate(widths, 1):
        ws.column_dimensions[ws.cell(row=1, column=c).column_letter].width = w
    # 突き合わせ用の列は隠す。お客様が直したかどうかを、出したときの値で判断する
    for h in ("出力時の状態", "出力時の実装日"):
        ws.column_dimensions[ws.cell(row=1, column=HEADERS.index(h) + 1).column_letter].hidden = True
    ws.freeze_panes = f"B{HEADER_ROW + 1}"

    meta = wb.create_sheet(META_NAME)
    meta["A1"], meta["B1"] = "period", period
    meta["A2"], meta["B2"] = "exported_on", date.today().isoformat()
    meta["A3"], meta["B3"] = "format", "status_sheet_v1"
    meta.sheet_state = "hidden"

    os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
    wb.save(path)
    return len(rows)


# ---------------------------------------------------------------- 読み取り
def sha1(path: str) -> str:
    h = hashlib.sha1()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def _text(v) -> str:
    if v is None:
        return ""
    if isinstance(v, datetime):
        return v.date().isoformat()
    if isinstance(v, date):
        return v.isoformat()
    return str(v).strip()


def read(path: str) -> tuple[str, list[dict]]:
    """シートを読む。戻り値は (対象月, 行)。見出しの名前で列を探す。"""
    from openpyxl import load_workbook
    wb = load_workbook(path, data_only=True)
    if SHEET_NAME not in wb.sheetnames:
        raise ValueError(f"「{SHEET_NAME}」のシートがありません。"
                         "ledger.py --status-sheet --xlsx で出したシートか確かめてください")
    ws = wb[SHEET_NAME]
    period = ""
    if META_NAME in wb.sheetnames:
        period = _text(wb[META_NAME]["B1"].value)
    head = {}
    for r in range(1, 15):
        vals = [_text(c.value) for c in ws[r]]
        if "提案ID" in vals and "状態" in vals:
            head = {v: n for n, v in enumerate(vals) if v}
            start = r + 1
            break
    if not head:
        raise ValueError("見出しの行（提案ID・状態）が見つかりません")
    out = []
    for row in ws.iter_rows(min_row=start, values_only=True):
        rec = {h: _text(row[n]) if n < len(row) else "" for h, n in head.items()}
        if rec.get("提案ID"):
            out.append(rec)
    return period, out


# ---------------------------------------------------------------- 日付
def parse_date(v: str) -> tuple[str, str]:
    """実装日の記入を読む。戻り値は (台帳に入れる値, 読めなかったときの原文)。

    おおよそでよいと案内しているので、月までの記入（2026-09、9月中旬）も受ける。
    読めないものは推測で埋めず、原文を補足に残して「実装日の確認待ち」にする。
    """
    s = (v or "").strip().replace("／", "/").translate(
        str.maketrans("０１２３４５６７８９", "0123456789"))
    if not s:
        return "", ""
    if BEFORE_PROPOSAL in s or "提案前" in s:
        return BEFORE_PROPOSAL, ""
    m = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})[-/.月](\d{1,2})日?(?:\s.*)?", s)
    if m:
        y, mo, d = map(int, m.groups())
        try:
            return date(y, mo, d).isoformat(), ""
        except ValueError:
            return "", s
    m = re.fullmatch(r"(\d{4})[-/.年](\d{1,2})月?(?:\s*(上旬|中旬|下旬|頃|ごろ|末))?", s)
    if m and 1 <= int(m.group(2)) <= 12:
        return f"{int(m.group(1)):04d}-{int(m.group(2)):02d}", ""
    return "", s


# ---------------------------------------------------------------- 突き合わせ
def diff(lg, rows: list[dict], *, period: str, revisit_months: int = 3) -> dict:
    """シートと台帳の違いを出す。台帳はまだ書き換えない。

    戻り値:
      changes   反映するもの（id・前後・理由）
      conflicts 反映せずに止めるもの（逆戻り）
      unknown   台帳に無いID
      unreadable 実装日が読めなかったもの
    """
    res = {"changes": [], "conflicts": [], "unknown": [], "unreadable": []}
    for r in rows:
        pid = r.get("提案ID", "")
        item = lg.get(pid)
        if item is None:
            res["unknown"].append(pid)
            continue
        sheet_st = r.get("状態", "")
        issued_st = r.get("出力時の状態", "")
        note = r.get("補足", "")
        when, raw = parse_date(r.get("実装日", ""))
        issued_when = r.get("出力時の実装日", "")
        if sheet_st and sheet_st not in SHEET_TO_LEDGER:
            res["unknown"].append(f"{pid}（状態「{sheet_st}」を読めません）")
            continue

        status_touched = bool(sheet_st) and sheet_st != issued_st
        date_touched = (r.get("実装日", "") or "") != (issued_when or "")
        if not (status_touched or date_touched or note):
            continue   # 直されていない。台帳がその後で動いていても、こちらを正とする
        if raw:
            res["unreadable"].append((pid, raw))

        # 状態を直していなければ、いまの台帳の状態のまま（日付・補足だけを入れる）
        sheet_eff = sheet_st if status_touched else LEDGER_TO_SHEET.get(item["status"], sheet_st)
        if when == BEFORE_PROPOSAL:
            sheet_eff = "実装済み（提案前から）"
        to = SHEET_TO_LEDGER.get(sheet_eff, item["status"])
        before = item["status"]

        if before in DONE and to in NOT_DONE:
            res["conflicts"].append({
                "id": pid, "title": item["title"], "before": before, "to": to,
                "sheet": sheet_eff, "note": note,
                "why": f"台帳では「{before}」です。済んだものを戻す記入なので、"
                       "取り違えでないかお客様に確かめてから --set で直してください"})
            continue
        if before == "検証済み" and to != "検証済み":
            # 検証済みは「実装済み」と記入されても下げない（前後比較の結果が消える）
            if not note:
                continue
            to = "検証済み"

        ch = {"id": pid, "title": item["title"], "before": before, "to": to,
              "sheet": sheet_eff, "note": note, "date": "", "date_unknown": False,
              "before_proposal": False, "blocked_by": "", "revisit_on": "",
              "remarks": []}
        if sheet_eff == "実装済み（提案前から）":
            ch["before_proposal"] = True
            ch["date_unknown"] = True
            ch["remarks"].append("提案前から実装済み。前後比較はしません")
        elif to == "実装済み":
            if when and when != BEFORE_PROPOSAL:
                ch["date"] = when
                if len(when) == 7:
                    ch["remarks"].append("実装日は月まで（おおよそ）")
            elif item.get("implemented_on") and not date_touched:
                ch["date"] = item["implemented_on"]
            else:
                ch["date_unknown"] = True
                ch["remarks"].append("実装日の確認待ち（次のシートに再掲します）")
        if to == "保留":
            ch["blocked_by"] = item.get("blocked_by") or note or "お客様の判断待ち（理由未記入）"
            ch["revisit_on"] = item.get("revisit_on") or _add_months(period, revisit_months)
            if not item.get("revisit_on"):
                ch["remarks"].append(f"再検討の時期は未記入のため {ch['revisit_on']} としました")
        if to == "却下" and not note:
            ch["remarks"].append("やらない理由が未記入です。同じ案を出し直さないため、"
                                 "分かればひとこと伺ってください")
        if before == "却下" and to != "却下":
            ch["remarks"].append("台帳では却下でした。お客様の記入を正とします")
        unchanged = (to == before and not note and not ch["before_proposal"]
                     and (ch["date"] or "") == (item.get("implemented_on") or ""))
        if unchanged:
            continue
        res["changes"].append(ch)
    return res


def _add_months(period: str, n: int) -> str:
    try:
        y, m = int(period[:4]), int(period[5:7])
    except (ValueError, IndexError):
        d = date.today()
        y, m = d.year, d.month
    m += n
    y += (m - 1) // 12
    m = (m - 1) % 12 + 1
    return f"{y:04d}-{m:02d}"


def apply(lg, changes: list[dict], *, source: str) -> None:
    """突き合わせた結果を台帳へ入れる。"""
    for ch in changes:
        item = lg.get(ch["id"])
        if ch["blocked_by"]:
            item["blocked_by"] = ch["blocked_by"]
        if ch["revisit_on"]:
            item["revisit_on"] = ch["revisit_on"]
        if ch["before_proposal"]:
            item["implemented_before_proposal"] = True
        note = ch["note"]
        if ch["before_proposal"] and BEFORE_PROPOSAL not in note:
            note = f"{BEFORE_PROPOSAL}。{note}".rstrip("。") if note else BEFORE_PROPOSAL
        if ch["to"] == "検証済み":
            # 状態は動かさず、補足だけを残す
            item["status_note"] = note
            lg.log_status(item, item["status"], item["status"], source=source, note=note)
            continue
        lg.set_status(ch["id"], ch["to"], on=ch["date"], note=note,
                      date_unknown=ch["date_unknown"], source=source)


def find_sheets(root: str, rel_dir: str) -> list[str]:
    """お客様から戻ったシートの置き場にある xlsx。"""
    base = os.path.join(root, rel_dir)
    if not os.path.isdir(base):
        return []
    return sorted(os.path.join(base, f) for f in os.listdir(base)
                  if f.lower().endswith(".xlsx") and not f.startswith("~$"))
