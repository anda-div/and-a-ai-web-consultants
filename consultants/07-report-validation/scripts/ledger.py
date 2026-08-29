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
    python ledger.py --stats                集計
"""
from __future__ import annotations

import argparse
import io
import json
import os
import re
import sys
from datetime import date

STATUSES = ("提案中", "実装待ち", "実装済み", "検証済み", "却下", "保留")
DEFAULT_DIR = "_ledger"
FILENAME = "proposals.json"
RULES_FILE = "ledger_rules.json"


def load_rules() -> dict:
    """共通ルール（費用帯・指標の決め方・保留の扱い）を読む。

    公開側の defaults/ に置く。ここを直せば全利用者へ届く。
    """
    here = os.path.dirname(os.path.abspath(__file__))
    for c in (os.path.join(here, "defaults", RULES_FILE),
              os.path.join(os.path.dirname(here), "defaults", RULES_FILE),
              os.path.join(here, RULES_FILE)):
        if os.path.exists(c):
            with io.open(c, encoding="utf-8") as f:
                return json.load(f)
    return {}


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

    def low_cost(self) -> list[dict]:
        """低コスト帯で、まだ実装されていないもの。

        まとめて1回の発注にできる候補。個別に見積を取ると件数ぶん
        手続きが増え、それ自体が実装されない理由になる。
        """
        return [i for i in self.pending()
                if (i.get("cost_band") or cost_band(i.get("effort", ""))) == "低"]

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
                   note: str = "") -> dict:
        item = self.get(pid)
        if item is None:
            raise KeyError(f"台帳に {pid} がありません")
        if status not in STATUSES:
            raise ValueError(f"状態は {' / '.join(STATUSES)} のいずれかです")
        item["status"] = status
        if note:
            item["status_note"] = note
        if status == "実装済み":
            item["implemented_on"] = on or date.today().isoformat()
        if status == "保留" and not (item.get("blocked_by") and item.get("revisit_on")):
            raise ValueError(
                "保留にするときは --blocked-by と --revisit-on が必要です。"
                "何待ちかが書かれていないと、提案は静かに消えます。")
        return item

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
    groups = [("低", "低コスト帯（まとめて1回の発注にできます）"),
              ("中", "見積が必要なもの"),
              ("高", "次期リニューアルで検討するもの")]
    for band, head in groups:
        rows = [i for i in lg.pending()
                if (i.get("cost_band") or cost_band(i.get("effort", ""))) == band]
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
    ap.add_argument("--blocked-by", default="", help="保留にするとき：何待ちか")
    ap.add_argument("--revisit-on", default="", help="保留にするとき：再検討の目安 YYYY-MM")
    ap.add_argument("--stats", action="store_true", help="集計を表示")
    a = ap.parse_args()

    lg = Ledger(a.path)

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
            item = lg.set_status(a.set, a.status, on=a.date, note=a.note)
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
        rows = lg.low_cost()
        print(f"低コスト帯の未実装：{len(rows)} 件")
        print("外注しても金額が小さいものです。"
              "**個別に見積を取らず、まとめて1回の発注にする**のが要点です。\n")
        for i in rows:
            print(line(i) + f"   工数 {i.get('effort','')}")
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
