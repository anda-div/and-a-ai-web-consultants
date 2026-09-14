# -*- coding: utf-8 -*-
"""提案台帳（汎用）

毎月の改善提案を1か所に貯める。狙いは3つ。

  1. 出した提案を憶えていなくてよくする
     「前に似た案を出したかもしれない」という不安が、提案を止める。
     台帳に照会すれば済むなら、迷わず出せる。

  2. 実装された提案を追いかける
     実装日が入っていれば、翌月に前後比較ができる。
     効いた／効かなかったのどちらでも、次の問いが生まれる。

  3. 提案が資産として積み上がる
     却下された案も、却下の理由ごと残す。同じ案を出し直さないため、
     そして状況が変われば再提示できるようにするため。

台帳の中身はクライアント固有のため `_ledger/proposals.json` に置く。
このファイル（読み書きの仕組み）はクライアント固有の値を持たない。

    python ledger.py                        一覧
    python ledger.py --pending              未実装のものだけ
    python ledger.py --verify-due 2026-07   その月に検証すべきもの
    python ledger.py --similar "追従CTA"     似た提案を探す
    python ledger.py --angle price_transparency  切り口で照会する（こちらが確実）
    python ledger.py --set P-2026-06-001 --status 実装済み --date 2026-07-15
    python ledger.py --order-sheet          低コスト帯をまとめた発注依頼書
    python ledger.py --stats                集計

    python ledger.py --amend P-2026-06-001 --field vendor_brief \
        --value "..." --reason "実装したら成立しなかった" \
        --reason-kind 実装してみて方法が誤りと判明
    python ledger.py --amendments           直した記録（同じ誤りを次に書かないため）
    python ledger.py --amend-fix P-2026-06-001 --at 2 --reason-kind 表現の修正 \
        --why "..."                         記録した型の取り違えを直す（事実は凍結）
    python ledger.py --set <ID> --status 実装待ち --work-done 2026-09-14
        こちらの作業は完了。公開待ちのものを発注依頼書から外す

    python ledger.py --init-inbox           過去資料の取り込み口を作る
    python ledger.py --import               置かれた原本から取り込みの下書きを作る
    python ledger.py --import-apply <下書き> 埋まった下書きを台帳へ入れる
    python ledger.py --check 2026-09        レポートを書く前の警告
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import date

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import ledger_import  # noqa: E402  取り込みの本体（台帳を引数で受け取る）

STATUSES = ("提案中", "実装待ち", "実装済み", "検証済み", "却下", "保留")

# 本文として直せる項目。状態は --set、本文は --amend と入口を分ける。
#
# **提案は、書いた時点では間違っていることがある。** 計測まわりでは特に多い。
# 提案を書く時点で対象サイトの実装を完全には把握できず、着手して初めて
# 「その方法では成立しない」と分かる（送信完了ページが無い、など）。
# 直す口が無いと、誤った指示がそのまま発注依頼書で社外へ出る。
AMENDABLE = ("title", "target", "angle", "metric", "metric_kind",
             "baseline", "expected", "effort", "vendor", "vendor_brief")


def amend_kinds() -> dict:
    """訂正の型。defaults/ledger_rules.json に置く。"""
    return (RULES.get("amend_reasons") or {}).get("kinds") or {}


def kind_in_briefing(kind: str) -> bool:
    """その型を月初ブリーフィングに出すか。

    **スクリプトに型名を書かない。** 「表現の修正は出さない」と書いてしまうと、
    型を足したときに絞り込みが黙ってずれる。判断はカタログ側に持たせる。
    """
    spec = amend_kinds().get(kind)
    if isinstance(spec, dict):
        return bool(spec.get("briefing", True))
    return bool(kind)
DEFAULT_DIR = "_ledger"
FILENAME = "proposals.json"
RULES_FILE = "ledger_rules.json"
INBOX_FILE = "proposals_inbox.json"
INBOX_README = "inbox_readme_template.md"
CATALOG_FILE = "angles_catalog.json"


def defaults_path(name: str) -> str:
    """公開側の defaults/ にある既定ファイルを探す。無ければ空文字。"""
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(here, "defaults", name),
              os.path.join(os.path.dirname(here), "defaults", name),
              os.path.join(here, name)):
        if os.path.exists(c):
            return c
    return ""


def load_json(name: str) -> dict:
    """既定のJSONを読む。公開側の defaults/ に置く。

    ここを直せば全利用者へ届く。`_config/` を個別に直してもらう必要がない。
    """
    p = defaults_path(name)
    if not p:
        return {}
    with io.open(p, encoding="utf-8") as f:
        return json.load(f)


def load_rules() -> dict:
    """共通ルール（費用帯・指標の決め方・保留の扱い）を読む。"""
    return load_json(RULES_FILE)


RULES = load_rules()


def cost_band(effort: str) -> str:
    """外注したときの費用感。内製できるかどうかでは分けない。

    1文字の修正でも外注する運用は珍しくない。責任の所在をはっきり
    させるための判断であって、費用の問題ではないことが多い。
    そのため「自分で直せば無料」を前提にした区分は現場で機能しない。
    """
    for band, spec in (RULES.get("cost_bands") or {}).items():
        if band.startswith("_"):
            continue
        if effort in (spec.get("efforts") or []):
            return band
    return ""

def unconfirmed_import(item: dict) -> bool:
    """過去資料から取り込んだまま、実施状況をまだ確かめていない提案か。

    取り込んだ時点で分かっているのは「昔こういう提案があった」だけで、
    **いま実施済みかどうかは分かっていない。** 確認シートで訂正をもらって
    初めて確定する（そのとき --set が status_confirmed_on を入れる）。

    確かめる前にこれを発注依頼書へ載せると、**すでに実施されているかもしれない
    提案を制作会社へ発注することになる。** 工数を推測で埋めた場合に起きる。
    """
    return bool(item.get("imported_on")) and not item.get("status_confirmed_on")

# 表記ゆれを吸収して照合するための前処理
_NORM = str.maketrans("ＣＴＡＥＶＦＬＰ０１２３４５６７８９", "CTAEVFLP0123456789")
_STOP = ("する", "こと", "ため", "など", "および", "を", "に", "の", "が", "は",
         "改善", "対応", "実装", "設置", "追加", "見直し", "最適化")


def find_dir(root: str = ".") -> str:
    """台帳フォルダを探す。無ければ作る場所を返す。"""
    for c in (os.path.join(root, DEFAULT_DIR),
              os.path.join(os.path.dirname(os.path.abspath(root)), DEFAULT_DIR)):
        if os.path.isdir(c):
            return c
    return os.path.join(root, DEFAULT_DIR)


def project_root(ledger_dir: str) -> str:
    """台帳フォルダの親。取り込み口（_proposals_inbox）はここに置く。"""
    return os.path.dirname(os.path.abspath(ledger_dir)) or "."


class Ledger:
    def __init__(self, path: str | None = None):
        self.path = path or os.path.join(find_dir(), FILENAME)
        if os.path.exists(self.path):
            with io.open(self.path, encoding="utf-8") as f:
                self.data = json.load(f)
        else:
            self.data = {"_comment": "提案台帳。ledger.py が読み書きする。",
                         "proposals": []}
        self.items = self.data.setdefault("proposals", [])

    # ------------------------------------------------------------ 保存
    def save(self) -> None:
        os.makedirs(os.path.dirname(self.path), exist_ok=True)
        with io.open(self.path, "w", encoding="utf-8") as f:
            f.write(json.dumps(self.data, ensure_ascii=False, indent=2) + "\n")

    # ------------------------------------------------------------ 追加
    def new_id(self, period: str) -> str:
        pre = f"P-{period}-"
        used = [int(i["id"].rsplit("-", 1)[-1]) for i in self.items
                if i["id"].startswith(pre)]
        return f"{pre}{max(used, default=0) + 1:03d}"

    def add(self, *, period: str, title: str, **kw) -> dict:
        item = {
            "id": self.new_id(period),
            "created": period,
            "report": kw.get("report", ""),
            "title": title,
            "target": kw.get("target", ""),
            "angle": kw.get("angle", ""),
            "evidence": kw.get("evidence", []),
            "effort": kw.get("effort", ""),
            "cost_band": kw.get("cost_band") or cost_band(kw.get("effort", "")),
            "vendor": kw.get("vendor", ""),
            "vendor_brief": kw.get("vendor_brief", ""),
            "metric": kw.get("metric", ""),
            "metric_kind": kw.get("metric_kind", ""),
            "baseline": kw.get("baseline", ""),
            "expected": kw.get("expected", ""),
            "priority": kw.get("priority", 0),
            "status": kw.get("status", "提案中"),
            "status_note": kw.get("status_note", ""),
            "blocked_by": kw.get("blocked_by", ""),
            "revisit_on": kw.get("revisit_on", ""),
            "decision_owner": kw.get("decision_owner", ""),
            # 作業が終わった日と、変更が世に出た日は別である。
            # 当社の実装が終わっても、先方が公開するまで数値は動かない。
            # 前後比較の起点は implemented_on（公開日）のほう。
            "work_done_on": kw.get("work_done_on", ""),
            "implemented_on": kw.get("implemented_on"),
            "verification": kw.get("verification"),
        }
        self.items.append(item)
        return item

    # ------------------------------------------------------------ 参照
    def get(self, pid: str) -> dict | None:
        return next((i for i in self.items if i["id"] == pid), None)

    def pending(self) -> list[dict]:
        """まだ実装されていないもの。再提示の判断材料になる。"""
        return [i for i in self.items if i["status"] in ("提案中", "実装待ち", "保留")]

    def low_cost(self, vendor: str = "") -> list[dict]:
        """低コスト帯で、まだ実装されていないもの。

        まとめて1回の発注にできる候補。個別に見積を取ると件数ぶん
        手続きが増え、それ自体が実装されない理由になる。

        ただし発注先が違えば1回にはまとまらない。文言の修正、広告の
        配分変更、計測の実装は、渡す相手が別である。vendor で絞る。
        """
        # 作業が終わっているものは載せない。**発注するものが無い。**
        # 「実装待ち」には2つの意味が混ざる ――「着手を待っている」と
        # 「作業は終わり、先方の公開を待っている」。後者を依頼書に載せると、
        # 済んだ作業を制作会社へ発注することになる。
        out = [i for i in self.pending()
               if not unconfirmed_import(i) and not i.get("work_done_on")
               and (i.get("cost_band") or cost_band(i.get("effort", ""))) == "低"]
        if vendor:
            out = [i for i in out if i.get("vendor") == vendor]
        return out

    def vendors(self) -> list[str]:
        """低コスト帯に出てくる発注先の一覧"""
        seen = []
        for i in self.low_cost():
            v = i.get("vendor") or "（未設定）"
            if v not in seen:
                seen.append(v)
        return seen

    def revisit_due(self, period: str) -> list[dict]:
        """再検討の期日が来た保留。催促ではなく、期日が来たという事実。"""
        return [i for i in self.items
                if i["status"] == "保留" and i.get("revisit_on")
                and i["revisit_on"][:7] <= period]

    def verify_due(self, period: str) -> list[dict]:
        """その月に効果を検証すべきもの（実装済みで未検証）"""
        out = []
        for i in self.items:
            if i["status"] != "実装済み" or not i.get("implemented_on"):
                continue
            if i["implemented_on"][:7] < period:
                out.append(i)
        return out

    # ------------------------------------------------------------ 照合
    @staticmethod
    def _keys(text: str) -> set[str]:
        t = (text or "").translate(_NORM).lower()
        t = re.sub(r"[（）()「」【】、。・／/＋+]", " ", t)
        words = {w for w in re.split(r"\s+", t) if len(w) >= 2}
        for s in _STOP:
            words.discard(s)
        # 日本語は空白で切れないため、2文字ずつの重なりでも見る
        body = re.sub(r"\s+", "", t)
        words |= {body[i:i + 3] for i in range(max(0, len(body) - 2))}
        return words

    def similar(self, text: str = "", *, target: str = "", angle: str = "",
                threshold: float = 0.30):
        """似た提案を探す。完全一致ではなく、判断のための候補を出す。

        文字列の重なりは、短いほうを分母にする（重なり係数）。
        「全ページに追従CTAを置く」と
        「全ページ追従CTA＋FV簡易見積フォームを設置する」のように
        長さが違うと、集合全体を分母にする式では取りこぼす。

        ただし文字列だけでは限界がある。
        「料金を分かりやすく表示する」と
        「料金・最低保証を事前提示し、依頼フローを図解する」は
        同じことを言っているのに、共通する文字がほとんど無い。

        そこで切り口（angle）を最も強い手がかりにする。
        提案を出すときは自分が使った切り口が分かっているはずなので、
        必ず angle を渡すこと。
        """
        want = self._keys(text) if text else set()
        hits = []
        for i in self.items:
            score = 0.0
            if want:
                have = self._keys(i["title"])
                if have:
                    score = len(want & have) / min(len(want), len(have))
            if angle and i.get("angle") == angle:
                score += 0.35
            if target and i.get("target") and target in i["target"]:
                score += 0.15
            if score >= threshold:
                hits.append((round(score, 3), i))
        return sorted(hits, key=lambda x: -x[0])

    # ------------------------------------------------------------ 更新
    def set_status(self, pid: str, status: str, *, on: str = "",
                   note: str = "", work_done: str = "") -> dict:
        item = self.get(pid)
        if item is None:
            raise KeyError(f"台帳に {pid} がありません")
        if status not in STATUSES:
            raise ValueError(f"状態は {' / '.join(STATUSES)} のいずれかです")
        item["status"] = status
        # 人が状態を確かめた印。取り込んだだけの提案と、確認シートで訂正を
        # もらった提案を区別する。取り込んだままのものは発注依頼書へ載せない。
        item["status_confirmed_on"] = date.today().isoformat()
        if note:
            item["status_note"] = note
        if work_done:
            item["work_done_on"] = work_done
        if status == "実装済み":
            item["implemented_on"] = on or date.today().isoformat()
        if status == "保留" and not (item.get("blocked_by") and item.get("revisit_on")):
            raise ValueError(
                "保留にするときは --blocked-by と --revisit-on が必要です。"
                "何待ちかが書かれていないと、提案は静かに消えます。")
        return item

    def amend(self, pid: str, field: str, value: str, *, reason: str,
              kind: str) -> tuple[dict, str]:
        """提案の本文を直し、直した事実を残す。

        **提案は、書いた時点では間違っていることがある。**
        着手して初めて「その方法では成立しない」と分かることがあり、
        計測まわりでは珍しくない。直す口が無いと、誤った指示が
        そのまま発注依頼書で社外へ出る。

        理由を必ず書かせる。**何をどう間違えたかが、次の提案の材料になる。**
        同じ切り口で同じ誤りを繰り返さないために、月初ブリーフィングが持ち出す。

        戻り値は (提案, 警告文)。
        """
        item = self.get(pid)
        if item is None:
            raise KeyError(f"台帳に {pid} がありません")
        if field not in AMENDABLE:
            raise ValueError(
                f"{field} は本文の項目ではありません。直せるのは "
                f"{' / '.join(AMENDABLE)} です。"
                "状態（status・実装日・保留の条件）は --set で変えてください。")
        if not reason.strip():
            raise ValueError(
                "--reason を書いてください。**なぜ直したかが残らないと、"
                "同じ誤りを次の提案でもう一度書きます。**")
        kinds = amend_kinds()
        if kinds and kind not in kinds:
            raise ValueError(
                "--reason-kind を指定してください。型は "
                f"{' / '.join(kinds)} のいずれかです。\n"
                "型はブリーフィングの絞り込みに使います。**型の無い記録は"
                "絞り込みから漏れ、取り違えた記録はひとつの事象を複数件に見せます。**")

        before = item.get(field, "")
        if before == value:
            # 同じ値で追記すると、空振りの記録が増えるだけで古い記録は残る。
            # 型を直したいのなら、直す先は本文ではなく記録のほうである。
            raise ValueError(
                f"{field} はすでにその値です。何も変わりません。\n"
                "記録した型や理由だけを直したいときは --amend-fix を使ってください。")
        item[field] = value
        item.setdefault("amendments", []).append(
            {"on": date.today().isoformat(), "field": field,
             "before": before, "after": value,
             "reason": reason, "kind": kind})

        warn = ""
        if field == "effort":
            # 工数が変われば費用帯も変わる。古い帯を残すと発注の束が狂う
            item["cost_band"] = cost_band(value)
        if field in ("target", "angle"):
            # 重複判定の軸を動かした。別の提案と衝突していないか見る
            hit = next((o for o in self.items
                        if o["id"] != pid and o.get("angle") == item.get("angle")
                        and o.get("target") and item.get("target")
                        and o["target"] == item["target"]), None)
            if hit:
                warn = (f"直した結果、{hit['id']}「{hit['title']}」と"
                        "対象URL × 切り口が同じになりました。"
                        "どちらかに寄せるか、片方を却下にしてください。")
        return item, warn

    def amend_fix(self, pid: str, at: int, *, kind: str = "",
                  reason: str = "", why: str = "") -> dict:
        """記録した**型と理由だけ**を直す。

        なぜ書き換えを許すのか。

            どの項目を何から何へ変えたかは **事実** で、書き換えてはいけない。
            それがどの型に当たるかは **解釈** で、後から分かることがある。
            事実は凍結し、解釈は直せるようにする。

        型の取り違えは起きる。今回は依頼の説明が3項目をひとつの事象として
        まとめていたため、受け取った側が3件とも同じ型で記録した。
        型はブリーフィングの絞り込みに使うので、取り違えると
        **ひとつの事象が複数件に見え、「同じ誤りを繰り返さない」信号が薄まる。**

        直した事実は記録の中に残す（消さない）。
        """
        item = self.get(pid)
        if item is None:
            raise KeyError(f"台帳に {pid} がありません")
        log = item.get("amendments") or []
        if not log:
            raise ValueError(f"{pid} に直した記録がありません")
        if not 1 <= at <= len(log):
            raise ValueError(f"番号は 1〜{len(log)} です（--amendments で確認できます）")
        kinds = amend_kinds()
        if kind and kinds and kind not in kinds:
            raise ValueError(f"訂正の型は {' / '.join(kinds)} のいずれかです")
        if not why.strip():
            raise ValueError(
                "--why を書いてください（なぜ型を直すのか）。"
                "**取り違えた原因が残らないと、同じ取り違えがまた起きます。**")

        rec = log[at - 1]
        fix = {"on": date.today().isoformat(), "why": why}
        if kind and kind != rec.get("kind"):
            fix["was_kind"] = rec.get("kind", "")
            rec["kind"] = kind
        if reason and reason != rec.get("reason"):
            fix["was_reason"] = rec.get("reason", "")
            rec["reason"] = reason
        # 型も理由も変わらないときは、**経緯だけを追記する。**
        # 値が動かないことと、残すものが無いことは別である。
        # 値は正しいが原因が残っていない記録（この仕組みができる前に手で直したものなど）を、
        # 書き換えずに説明できるようにする。
        rec.setdefault("fixed", []).append(fix)
        return rec

    def amendments(self) -> list[tuple[dict, dict, int]]:
        """直した記録を新しい順に。(提案, 訂正, その提案の中での番号)。"""
        out = []
        for i in self.items:
            for n, a in enumerate(i.get("amendments") or [], 1):
                out.append((i, a, n))
        return sorted(out, key=lambda t: t[1].get("on", ""), reverse=True)

    def set_verification(self, pid: str, *, period: str, metric: str,
                         before, after, note: str = "") -> dict:
        item = self.get(pid)
        if item is None:
            raise KeyError(f"台帳に {pid} がありません")
        item["verification"] = {"period": period, "metric": metric,
                                "before": before, "after": after, "note": note}
        item["status"] = "検証済み"
        return item

    # ------------------------------------------------------------ 集計
    def stats(self) -> dict:
        out = {s: 0 for s in STATUSES}
        for i in self.items:
            out[i["status"]] = out.get(i["status"], 0) + 1
        out["合計"] = len(self.items)
        return out


# ---------------------------------------------------------------- 発注依頼書
def order_sheet(lg: "Ledger", *, issued: str = "", to: str = "",
                deadline: str = "", vendor: str = "") -> str:
    """低コスト帯をまとめた、制作会社にそのまま渡せる1枚。

    1件ずつ出すと、件数ぶん見積・発注・検収の手続きが発生する。
    金額ではなく手続きの回数が実装されない理由になっている場合があるため、
    同じ費用帯のものを1回の依頼にまとめる。

    末尾で実装日を尋ねているのが要点。これが返ってこないと、
    翌月の前後比較ができない。
    """
    rows = [i for i in lg.low_cost(vendor) if i.get("vendor_brief")]
    labels = ((RULES.get("bundling") or {}).get("vendor_labels") or {})
    lab = labels.get(vendor) or labels.get("_default") or {}
    subject = lab.get("subject", "修正のご依頼")
    scope = lab.get("scope", "いずれも小規模な作業です。")
    L = [f"# {subject}", ""]
    L += ["| | |", "|---|---|",
          f"| 発行日 | {issued or '　'} |",
          f"| 宛先 | {to or '　'} |",
          f"| 件名 | {subject}（{len(rows)}件） |",
          f"| ご希望納期 | {deadline or '　'} |", ""]
    L += ["## ご依頼の趣旨", "", f"下記 {len(rows)} 件は、{scope}", ""]
    if len(rows) >= 2:
        # 1件しか無いときにこの断り書きを出すと、かえって不自然になる
        L += ["**1件ずつではなく、まとめて1回のご対応としてお願いしたい**という趣旨です。",
              "1件あたりの作業は小さくても、見積・発注・検収の手続きは"
              "件数ぶん発生するためです。", ""]
    L += ["## 修正の明細", ""]
    for n, i in enumerate(rows, 1):
        L += [f"### {n}. {i['title']}", "",
              f"- **対象**：{i.get('target', '')}",
              f"- **作業区分**：{i.get('effort', '')}",
              f"- **ご依頼内容**：{i['vendor_brief']}"]
        # 社内向けの背景（なぜ効くと考えているか）は載せない。
        # レポートに書くことであって、作業の依頼書には要らない。
        L += [f"- **管理番号**：{i['id']}", ""]
    if not rows:
        L += ["（該当する項目がありません）", ""]
    L += ["## 変更してよい範囲", "",
          "- **上記の明細に書かれた箇所のみ**を変更してください。"]
    if vendor == "制作":
        L.append("- 書体・文字サイズ・色・配置・レイアウトは**変更しないでください**。")
    L += [
          "- 明細に書かれていない箇所で、あわせて直すべき点にお気づきの場合は、",
          "  **修正せずにご指摘だけください。** 別途ご相談させていただきます。", ""]
    L += ["## ご確認いただきたいこと", "",
          ("- [ ] 上記をまとめて1回のご対応としていただけるか"
           if len(rows) >= 2 else "- [ ] ご対応いただけるか"),
          "- [ ] お見積りの要否と、必要な場合は金額",
          "- [ ] 着手可能な時期", ""]
    L += ["## 作業完了後にお知らせください", "",
          "**修正を反映した日付**（おおよそで構いません）をご連絡ください。",
          "",
          "反映日の前後で同じ日数を切って比較し、**効果を確認するために使います。**",
          "日付が分からないと、数値が動いた理由をこの修正に結びつけられません。", ""]
    L += ["| 管理番号 | 反映日 |", "|---|---|"]
    for i in rows:
        L.append(f"| {i['id']} | 　 |")
    L.append("")
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 確認シート
def status_sheet(lg: "Ledger", period: str) -> str:
    """打ち合わせに持っていく、記入済みの実施状況シート。

    「あれはどうなりましたか」と尋ねると一方向の催促になり、
    答えるほうは気まずい。こちらの理解を書いて出し、
    違っていたら訂正してもらう形にする。
    空欄を埋めるより、書かれた内容を直すほうが答えやすい。
    """
    L = [f"# 提案の実施状況　確認シート（{period}）", "",
         "こちらで把握している状況です。**違っているところだけ訂正してください。**",
         "すべてに回答いただく必要はありません。", ""]
    # 費用帯が決まっていないものを落とさない。
    # 過去資料から取り込んだ提案には工数の見立てが無いのが普通で、
    # 3つの帯だけで回すと**取り込んだ提案が1件も載らない確認シート**になる。
    # 訂正をもらうための紙なので、そこが抜けると取り込み自体が無駄になる。
    #
    # 見出しで**出所を主張しない。** 取り込む対象には他社が作った提案書や
    # 社内メモも含まれる。「お出ししていた」と書くと、他社の提案を自社のものとして
    # 出しているように読める。信頼の話なので、ここは言い方を選ぶ。
    groups = [("低", "低コスト帯（まとめて1回の発注にできます）"),
              ("中", "見積が必要なもの"),
              ("高", "次期リニューアルで検討するもの"),
              ("", "これまでに挙がっていた提案（いまの状況を教えてください）")]
    listed = set()

    # 作業が終わり、公開を待っているもの。
    # 「実装待ち」と同じ扱いにすると「実施が決まったと理解しています」と出て、
    # **当社の作業が止まっているように読める。** 実際に待っているのは公開の判断で、
    # ここで聞くべきは進捗ではなく**公開日**である。前後比較の起点になる。
    waiting = [i for i in lg.pending() if i.get("work_done_on")]
    if waiting:
        listed |= {i["id"] for i in waiting}
        L += ["## 作業が完了し、公開をお待ちしているもの", "",
              "**こちら側の作業は終わっています。**公開の判断だけをお待ちしている状態です。",
              "",
              "| ID | 提案 | 作業完了 | 公開日（ご記入ください） |", "|---|---|---|---|"]
        for i in waiting:
            L.append(f"| {i['id']} | {i['title']} | {i['work_done_on']} |  |")
        L += ["",
              "> **公開日が分かると、その前後で比較できます。**",
              "> 数値が動く起点は作業完了日ではなく公開日のため、"
              "公開後に日付をお知らせください。", ""]

    for band, head in groups:
        if band:
            rows = [i for i in lg.pending()
                    if i["id"] not in listed and not unconfirmed_import(i)
                    and (i.get("cost_band") or cost_band(i.get("effort", ""))) == band]
        else:
            # 取り込んだまま状態を確かめていないものは、工数が埋まっていても
            # ここに出す。**確かめる前に「まとめて発注できます」と並べない。**
            rows = [i for i in lg.pending() if i["id"] not in listed]
        listed |= {i["id"] for i in rows}
        if not rows:
            continue
        L += [f"## {head}", "",
              "| ID | 提案 | 工数 | こちらの理解 | 訂正 |", "|---|---|---|---|---|"]
        for i in rows:
            guess = {"提案中": "まだご返答をいただいていません",
                     "実装待ち": "実施が決まったと理解しています",
                     "保留": f"保留（{i.get('blocked_by') or '理由未確認'}）"}.get(
                i["status"], i["status"])
            L.append(f"| {i['id']} | {i['title']} | {i.get('effort','')} | {guess} |  |")
        L.append("")
    done = [i for i in lg.items if i["status"] in ("実装済み", "検証済み")]
    if done:
        L += ["## 実施済みと理解しているもの", "",
              "| ID | 提案 | 実装日 | 訂正 |", "|---|---|---|---|"]
        for i in done:
            L.append(f"| {i['id']} | {i['title']} | {i.get('implemented_on') or '日付未確認'} |  |")
        L.append("")
        L += ["> **実装日が分かると、翌月に前後比較ができます。**",
              "> おおよその日付でも構いません。", ""]
    L += ["## この先の進め方", "",
          "- 低コスト帯は、**まとめて1回の発注**にすると見積も決裁も1回で済みます。",
          "- 実施しないと決まったものは、**理由をひとことだけ**いただけると助かります。",
          "  同じ提案を出し直さずに済み、状況が変わったときに出し直せます。",
          "- いま決められないものは「保留」で構いません。"
          "**何待ちかと、いつ頃また見るか**だけ決めさせてください。", ""]
    return "\n".join(L) + "\n"


# ---------------------------------------------------------------- 表示
def line(i: dict) -> str:
    mark = {"提案中": "・", "実装待ち": "▷", "実装済み": "■", "検証済み": "✓",
            "却下": "×", "保留": "－"}.get(i["status"], "・")
    tgt = f"  [{i['target']}]" if i.get("target") else ""
    return f"  {mark} {i['id']}  {i['status']:<5} {i['title']}{tgt}"


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="提案台帳")
    ap.add_argument("--path", help="台帳のファイル（既定 _ledger/proposals.json）")
    ap.add_argument("--pending", action="store_true", help="未実装のものだけ表示")
    ap.add_argument("--verify-due", metavar="YYYY-MM", help="その月に検証すべきもの")
    ap.add_argument("--similar", metavar="文言", help="似た提案を探す")
    ap.add_argument("--angle", default="",
                    help="切り口で照会する（--similar と併用すると精度が上がる）")
    ap.add_argument("--target", default="", help="対象URLで絞る")
    ap.add_argument("--set", metavar="ID", help="状態を変える提案のID")
    ap.add_argument("--status", help=" / ".join(STATUSES))
    ap.add_argument("--date", default="", help="実装日 YYYY-MM-DD")
    ap.add_argument("--note", default="", help="状態の補足")
    ap.add_argument("--low-cost", action="store_true",
                    help="低コスト帯の未実装を表示（まとめて発注する候補）")
    ap.add_argument("--revisit-due", metavar="YYYY-MM",
                    help="再検討の期日が来た保留を表示")
    ap.add_argument("--status-sheet", metavar="YYYY-MM",
                    help="打ち合わせ用の確認シートを出す")
    ap.add_argument("--order-sheet", action="store_true",
                    help="低コスト帯をまとめた発注依頼書を出す")
    ap.add_argument("--issued", default="", help="発注依頼書の発行日")
    ap.add_argument("--to", default="", help="発注依頼書の宛先")
    ap.add_argument("--deadline", default="", help="発注依頼書の希望納期")
    ap.add_argument("--vendor", default="",
                    help="発注先で絞る（制作／広告運用／計測 など）")
    ap.add_argument("--blocked-by", default="", help="保留にするとき：何待ちか")
    ap.add_argument("--revisit-on", default="", help="保留にするとき：再検討の目安 YYYY-MM")
    ap.add_argument("--stats", action="store_true", help="集計を表示")
    ap.add_argument("--init-inbox", action="store_true",
                    help="過去資料の取り込み口（_proposals_inbox）を作り、"
                         "クライアントへ渡すREADMEを置く")
    ap.add_argument("--import", dest="do_import", action="store_true",
                    help="取り込み口に置かれた原本を読み、AIが埋める下書きを作る。"
                         "取り込み済みの原本は飛ばす")
    ap.add_argument("--import-apply", metavar="下書き.json",
                    help="埋まった下書きを台帳へ入れる。"
                         "target × angle で重複を判定し、原本を _archive/ へ退避する")
    ap.add_argument("--dry-run", action="store_true",
                    help="--import-apply で、台帳に書かずに結果だけ見る")
    ap.add_argument("--check", metavar="YYYY-MM",
                    help="レポートを書く前の警告（未取り込みの原本／台帳の放置）")
    ap.add_argument("--amend", metavar="ID",
                    help="提案の本文を直す（題・対象・切り口・指標・発注指示など）。"
                         "状態は --set、本文は --amend と入口を分けている")
    ap.add_argument("--field", help="直す項目: " + " / ".join(AMENDABLE))
    ap.add_argument("--value", help="直したあとの値")
    ap.add_argument("--reason", default="",
                    help="なぜ直したか（必須）。次の提案で同じ誤りを書かないために残す")
    ap.add_argument("--reason-kind", default="",
                    help="訂正の型（必須）。defaults/ledger_rules.json の amend_reasons")
    ap.add_argument("--amend-fix", metavar="ID",
                    help="記録した型と理由だけを直す。"
                         "どの項目を何から何へ変えたかは書き換えられない")
    ap.add_argument("--at", type=int,
                    help="--amend-fix で直す記録の番号（--amendments で確認）")
    ap.add_argument("--why", default="",
                    help="--amend-fix で、なぜ型を直すのか（必須）")
    ap.add_argument("--amendments", action="store_true",
                    help="直した記録を新しい順に表示する")
    ap.add_argument("--work-done", default="",
                    help="こちら側の作業が終わった日 YYYY-MM-DD。"
                         "公開待ちのものを発注依頼書から外す。"
                         "前後比較の起点は公開日（--date）のほう")
    a = ap.parse_args()

    lg = Ledger(a.path)
    ldir = os.path.dirname(os.path.abspath(lg.path))
    root = project_root(ldir)
    spec = load_json(INBOX_FILE)

    if a.init_inbox:
        tpl = defaults_path(INBOX_README)
        readme = io.open(tpl, encoding="utf-8").read() if tpl else ""
        made = ledger_import.init_inbox(root, spec, readme)
        base = os.path.join(root, spec.get("dir_name", "_proposals_inbox"))
        if made:
            print(f"取り込み口を作りました: {base}")
            for p in made:
                print(f"  {os.path.relpath(p, root)}")
        else:
            print(f"取り込み口は既にあります: {base}")
        print()
        print("**5つの箱が空のまま、が最もあり得る失敗です。**")
        print("クライアントに書き出してもらう前提にせず、"
              "まず自社の過去レポートから初期投入してください。")
        print("クライアントにお願いするのは、こちらが持っていない資料だけにします。")
        return 0

    if a.do_import:
        done = {r.get("sha1") for r in (lg.data.get("imports") or [])}
        found, skipped = ledger_import.scan(root, spec, done)
        base = os.path.join(root, spec.get("dir_name", "_proposals_inbox"))
        if not os.path.isdir(base):
            print(f"取り込み口がありません: {base}")
            print("`ledger.py --init-inbox` で作れます。")
            return 1
        if skipped:
            print(f"取り込み済みのため飛ばしました: {len(skipped)} 件")
        if not found:
            print("未取り込みの原本はありません。")
            return 0
        cat = load_json(CATALOG_FILE)
        draft = ledger_import.build_draft(root, spec, cat, found, ldir)
        out = os.path.join(ldir, f"import_{draft['created']}.json")
        os.makedirs(ldir, exist_ok=True)
        with io.open(out, "w", encoding="utf-8", newline="\n") as f:
            f.write(json.dumps(draft, ensure_ascii=False, indent=2) + "\n")
        print(f"未取り込みの原本 {len(found)} 件から下書きを作りました。")
        print(f"  {out}")
        print()
        for s in draft["sources"]:
            mark = "×" if s["読めなかった理由"] else " "
            print(f"  {mark} [{s['folder']}] {s['file']}　{s['文字数']:,} 字"
                  + (f"　{s['読めなかった理由']}" if s["読めなかった理由"] else ""))
        print()
        print("次にすること: 各 sources の「全文」を読み、proposals を埋めてから")
        print(f"  python ledger.py --import-apply \"{out}\"")
        print()
        print("**target（対象URL）と angle（切り口）は必ず埋めてください。**")
        print("この2つが重複判定の軸です。空だと、同じ提案を来月もう一度出します。")
        return 0

    if a.import_apply:
        if not os.path.exists(a.import_apply):
            print(f"下書きがありません: {a.import_apply}")
            return 1
        with io.open(a.import_apply, encoding="utf-8") as f:
            draft = json.load(f)
        period = (a.check or draft.get("created", ""))[:7] or date.today().isoformat()[:7]
        res = ledger_import.apply_draft(lg, draft, spec, period=period,
                                        archive_root=root, dry_run=a.dry_run)
        if res["incomplete"]:
            print(f"【埋まっていない】{len(res['incomplete'])} 件　"
                  "推測で埋めず、00_未分類 に落として人に聞いてください。")
            for row, miss in res["incomplete"]:
                print(f"  ・{row.get('title') or '（題名なし）'}"
                      f"　不足: {'、'.join(miss)}")
            print()
        if res["duplicates"]:
            print(f"【すでに台帳にある】{len(res['duplicates'])} 件　"
                  "対象URL × 切り口が同じものです。")
            for row, hit in res["duplicates"]:
                print(f"  ・{row.get('title')}")
                print(f"      既存 {hit['id']}　{hit['title']}（{hit['status']}）")
            print()
        print(f"【台帳へ入れた】{len(res['added'])} 件"
              + ("　※ --dry-run のため書き込んでいません" if a.dry_run else ""))
        for i in res["added"]:
            print(line(i))
        if res["moved"]:
            print(f"\n原本 {len(res['moved'])} 件を _archive/ へ退避しました。"
                  "以後は台帳だけを読みます。")
        if res["kept"]:
            print(f"\n入口に残した原本：{len(res['kept'])} 件")
            print("台帳に入っていないものを退避すると、情報が黙って消えます。"
                  "埋めてからもう一度実行してください。")
            print("読んだうえで提案が無かった原本は、下書きの「提案なし」に"
                  "ファイル名を書いてください。")
            for f in res["kept"]:
                print(f"  ・{f}")
        if res["added"] and not a.dry_run:
            print("\n次にすること: 確認シートを打ち合わせに持っていってください。")
            print(f"  python ledger.py --status-sheet {period}")
            print("こちらの理解を記入した一覧を出し、**違うところだけ訂正してもらいます。**")
        return 1 if res["incomplete"] else 0

    if a.check:
        warns = ledger_import.warnings(lg, root, spec, a.check)
        if not warns:
            print(f"{a.check}　レポートを書く前の確認：問題ありません。")
            return 0
        print(f"{a.check}　レポートを書く前に片付けること：{len(warns)} 件\n")
        for w in warns:
            print(f"  ・{w}")
        print()
        return 1

    def show_kinds():
        """型を選ばせる。**未指定のまま通さない。** 取り違えの多くはここで防げる。"""
        print("訂正の型を --reason-kind で指定してください。")
        print("型はブリーフィングの絞り込みに使います。"
              "取り違えると、ひとつの事象が複数件に見えます。\n")
        for k, spec in amend_kinds().items():
            note = spec.get("note", "") if isinstance(spec, dict) else str(spec)
            mark = "月初に出る" if kind_in_briefing(k) else "月初に出ない"
            print(f"  {k}　（{mark}）")
            print(f"      {note}")

    if a.amend:
        if not a.field or a.value is None:
            print("--field と --value を指定してください。")
            print("直せる項目: " + " / ".join(AMENDABLE))
            return 1
        if not a.reason_kind:
            show_kinds()
            return 1
        try:
            item, warn = lg.amend(a.amend, a.field, a.value,
                                  reason=a.reason, kind=a.reason_kind)
        except (KeyError, ValueError) as e:
            print(str(e))
            return 1
        lg.save()
        rec = item["amendments"][-1]
        print(f"直しました　{item['id']}　{a.field}")
        print(f"  前: {rec['before'] or '（空）'}")
        print(f"  後: {rec['after'] or '（空）'}")
        print(f"  理由: {rec['reason']}" + (f"（{rec['kind']}）" if rec['kind'] else ""))
        if warn:
            print(f"\n※ {warn}")
        if a.field == "vendor_brief":
            print("\n発注依頼書に出る文面です。"
                  "すでに発注済みであれば、訂正を先方へお伝えしてください。")
        return 0

    if a.amend_fix:
        if not (a.reason_kind or a.reason or a.why):
            print("型を直すなら --reason-kind、経緯だけを残すなら --why を指定してください。\n")
            show_kinds()
            return 1
        if a.at is None:
            print("--at で記録の番号を指定してください（--amendments で確認できます）。")
            return 1
        try:
            rec = lg.amend_fix(a.amend_fix, a.at, kind=a.reason_kind,
                               reason=a.reason, why=a.why)
        except (KeyError, ValueError) as e:
            print(str(e))
            return 1
        lg.save()
        fix = rec["fixed"][-1]
        moved = "was_kind" in fix or "was_reason" in fix
        head = "記録の型を直しました" if moved else "記録に経緯を追記しました"
        print(f"{head}　{a.amend_fix}　{a.at} 件目（{rec['field']}）")
        if "was_kind" in fix:
            print(f"  型　　前: {fix['was_kind'] or '（空）'}　→　後: {rec['kind']}")
        if "was_reason" in fix:
            print(f"  理由　前: {fix['was_reason']}")
            print(f"  　　　後: {rec['reason']}")
        if not moved:
            print(f"  型　　{rec.get('kind') or '（無し）'}（変えていません）")
        print(f"  {'直した' if moved else '書き残す'}理由: {fix['why']}")
        print()
        print("どの項目を何から何へ変えたかは変えていません。"
              "**事実は凍結し、解釈だけを直しています。**")
        if moved and not kind_in_briefing(rec.get("kind", "")):
            print("この型は月初ブリーフィングに出なくなります。")
        return 0

    if a.amendments:
        rows = lg.amendments()
        if not rows:
            print("直した記録はありません。")
            return 0
        print(f"直した記録：{len(rows)} 件")
        print("**提案は、書いた時点では間違っていることがあります。**"
              "同じ誤りを次に書かないための記録です。")
        print("型を取り違えたときは --amend-fix <ID> --at <番号> で直せます。\n")
        for i, r, n in rows:
            ang = f"／切り口 {i['angle']}" if i.get("angle") else ""
            out = "" if kind_in_briefing(r.get("kind", "")) else "　※月初には出ない"
            print(f"  {r['on']}  {i['id']}  {n} 件目　{r['field']}{ang}{out}")
            print(f"      前: {r['before'] or '（空）'}")
            print(f"      後: {r['after'] or '（空）'}")
            print(f"      理由: {r['reason']}"
                  + (f"（{r['kind']}）" if r.get("kind") else "　※型なし"))
            for f in r.get("fixed") or []:
                was = []
                if "was_kind" in f:
                    was.append(f"型 {f['was_kind'] or '（空）'}")
                if "was_reason" in f:
                    was.append("理由")
                what = f"{'・'.join(was)}を訂正" if was else "経緯を追記"
                print(f"      ← {f['on']} に{what}：{f['why']}")
        return 0

    if a.set:
        if not a.status:
            print("--status を指定してください（" + " / ".join(STATUSES) + "）")
            return 1
        target = lg.get(a.set)
        if target is None:
            print(f"台帳に {a.set} がありません")
            return 1
        if a.blocked_by:
            target["blocked_by"] = a.blocked_by
        if a.revisit_on:
            target["revisit_on"] = a.revisit_on
        try:
            item = lg.set_status(a.set, a.status, on=a.date, note=a.note,
                                 work_done=a.work_done)
        except ValueError as e:
            print(str(e))
            return 1
        lg.save()
        print("更新しました")
        print(line(item))
        return 0

    if a.similar or a.angle:
        hits = lg.similar(a.similar or "", target=a.target, angle=a.angle)
        what = f"「{a.similar}」" if a.similar else f"切り口 {a.angle}"
        if not hits:
            print(f"{what} に似た提案は台帳にありません。新しい提案として出せます。")
            return 0
        print(f"{what} に似た提案が {len(hits)} 件あります。")
        print("そのまま出さず、状態と却下理由を見てから判断してください。\n")
        for sc, i in hits:
            ang = f"／切り口 {i['angle']}" if i.get("angle") else ""
            print(line(i) + f"   （近さ {sc}{ang}）")
            if i.get("status_note"):
                print(f"      {i['status_note']}")
        return 0

    if a.verify_due:
        due = lg.verify_due(a.verify_due)
        print(f"{a.verify_due} に効果を検証すべき提案：{len(due)} 件")
        for i in due:
            print(line(i) + f"   実装 {i['implemented_on']}／指標 {i.get('metric','')}")
        return 0

    if a.order_sheet:
        if not a.vendor:
            print("発注先を指定してください（--vendor）。"
                  "同じ費用帯でも、渡す相手が違えば1回の依頼にまとまりません。")
            print("\n低コスト帯に出てくる発注先：")
            for v in lg.vendors():
                n = len(lg.low_cost(v if v != "（未設定）" else ""))
                print(f"  {v}　{len(lg.low_cost(v))} 件" if v != "（未設定）"
                      else f"  {v}")
            return 1
        print(order_sheet(lg, issued=a.issued, to=a.to,
                          deadline=a.deadline, vendor=a.vendor))
        return 0

    if a.status_sheet:
        print(status_sheet(lg, a.status_sheet))
        return 0

    if a.revisit_due:
        due = lg.revisit_due(a.revisit_due)
        if not due:
            print(f"{a.revisit_due} 時点で、再検討の期日が来た保留はありません。")
            return 0
        print(f"再検討の期日が来た保留：{len(due)} 件")
        print("催促ではなく、期日が来たという事実として持ち出してください。\n")
        for i in due:
            print(line(i))
            print(f"      待っているもの：{i.get('blocked_by','（未記入）')}"
                  f"／再検討 {i.get('revisit_on','')}")
        return 0

    if a.low_cost:
        rows = lg.low_cost(a.vendor)
        print(f"低コスト帯の未実装：{len(rows)} 件"
              + (f"（発注先 {a.vendor}）" if a.vendor else ""))
        print("外注しても金額が小さいものです。"
              "**個別に見積を取らず、まとめて1回の発注にする**のが要点です。\n")
        for i in rows:
            print(line(i) + f"   工数 {i.get('effort','')}"
                  f"／発注先 {i.get('vendor') or '（未設定）'}")
            if i.get("vendor_brief"):
                print(f"      発注指示：{i['vendor_brief']}")
        return 0

    if a.stats:
        print("台帳の状況")
        for k, v in lg.stats().items():
            print(f"  {k:<6} {v:>3} 件")
        return 0

    items = lg.pending() if a.pending else lg.items
    title = "未実装の提案" if a.pending else "提案台帳"
    print(f"{title}：{len(items)} 件　（{lg.path}）\n")
    for period in sorted({i["created"] for i in items}):
        print(f"■ {period}")
        for i in [x for x in items if x["created"] == period]:
            print(line(i))
        print()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
