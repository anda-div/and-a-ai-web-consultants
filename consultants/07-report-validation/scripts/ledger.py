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
            "metric": kw.get("metric", ""),
            "baseline": kw.get("baseline", ""),
            "expected": kw.get("expected", ""),
            "priority": kw.get("priority", 0),
            "status": kw.get("status", "提案中"),
            "status_note": kw.get("status_note", ""),
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
    ap.add_argument("--stats", action="store_true", help="集計を表示")
    a = ap.parse_args()

    lg = Ledger(a.path)

    if a.set:
        if not a.status:
            print("--status を指定してください（" + " / ".join(STATUSES) + "）")
            return 1
        item = lg.set_status(a.set, a.status, on=a.date, note=a.note)
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
