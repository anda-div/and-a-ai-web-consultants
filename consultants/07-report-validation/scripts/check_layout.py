# -*- coding: utf-8 -*-
"""生成したPowerPointの体裁を検査する（納品前チェック）

スライドの座標はファイルの中に正確に入っている。目で見るより速く、正確に
測れることは測ってしまい、人の目は「文章として正しいか」に使う。

    python check_layout.py <レポート.pptx> [オプション]

検査するもの

    重なり      内容どうしが重なっていないか
    枠外        図形が用紙からはみ出していないか
    下の空き    内容の下端と要約枠の間が空きすぎていないか
    画像のゆがみ 画像が元の縦横比のまま置かれているか
    細い画像    縦長すぎて何が写っているか読めなくなっていないか
    文字サイズ  本文が読める大きさを下回っていないか
    制御文字    パスのエスケープ漏れで _x000D_ などが混ざっていないか

見つからないもの（人の目が必要）

    解説と画面が食い違っていないか、数値の意味が正しいか、
    言い過ぎていないか、宛先・日付が正しいか。

終了コードは、重大な指摘が1件でもあれば 1、無ければ 0。
"""
from __future__ import annotations

import argparse
import os
import re
import sys
import zipfile

from pptx import Presentation
from pptx.enum.shapes import MSO_SHAPE_TYPE

EMU_CM = 360000.0

# 内容として扱う図形（装飾の線や矢印は対象外）
CONTENT_TYPES = {"autoShape", "pic", "graphicFrame", "tbl", "sp"}


def cm(v) -> float:
    return (v or 0) / EMU_CM


class Shape:
    """検査に必要な情報だけを取り出した図形"""

    def __init__(self, sh, slide_no: int):
        self.raw = sh
        self.slide = slide_no
        self.x = cm(sh.left)
        self.y = cm(sh.top)
        self.w = cm(sh.width)
        self.h = cm(sh.height)
        self.tag = sh._element.tag.rsplit("}", 1)[-1]
        self.text = ""
        if getattr(sh, "has_text_frame", False):
            self.text = sh.text_frame.text.strip()
        self.is_picture = self.tag == "pic"
        self.is_connector = self.tag == "cxnSp"

    @property
    def right(self) -> float:
        return self.x + self.w

    @property
    def bottom(self) -> float:
        return self.y + self.h

    @property
    def label(self) -> str:
        if self.text:
            return self.text.split("\n")[0][:30]
        if self.is_picture:
            return f"画像（左 {self.x:.1f}cm・上 {self.y:.1f}cm）"
        return {"tbl": "表", "graphicFrame": "表またはグラフ"}.get(self.tag, "図形")

    @property
    def has_content(self) -> bool:
        """中身のある図形か。空の装飾用の箱は重なり判定から外す。"""
        if self.is_connector:
            return False
        if self.tag in ("pic", "graphicFrame"):
            return True
        return bool(self.text)


def collect(slide, slide_no: int) -> list[Shape]:
    """グループは中身に展開して集める（枠だけの重なりを数えないため）"""
    out = []

    def walk(shapes):
        for sh in shapes:
            if sh.shape_type is not None and sh._element.tag.endswith("}grpSp"):
                walk(sh.shapes)
                continue
            try:
                if sh.left is None or sh.top is None:
                    continue
            except (AttributeError, TypeError):
                continue
            out.append(Shape(sh, slide_no))

    walk(slide.shapes)
    return out


def overlap_area(a: Shape, b: Shape) -> tuple[float, float, float]:
    ow = min(a.right, b.right) - max(a.x, b.x)
    oh = min(a.bottom, b.bottom) - max(a.y, b.y)
    if ow <= 0 or oh <= 0:
        return 0.0, 0.0, 0.0
    return ow * oh, ow, oh


def inside(inner: Shape, outer: Shape, tol: float = 0.05) -> bool:
    """inner が画像 outer の内側に完全に収まっているか"""
    if not outer.is_picture:
        return False
    return (inner.x >= outer.x - tol and inner.y >= outer.y - tol
            and inner.right <= outer.right + tol
            and inner.bottom <= outer.bottom + tol)


def control_chars(path: str) -> list[tuple[int, str, str, str]]:
    """XMLに退避された制御文字を探す。

    Windowsのパスを生の文字列にせずに書くと、\\r や \\b が
    エスケープとして解釈される。python-pptx では普通の文字列に
    見えるが、PowerPointでは _x000D_ のように表示される。
    """
    out = []
    with zipfile.ZipFile(path) as z:
        names = sorted((n for n in z.namelist()
                        if n.startswith("ppt/slides/slide")),
                       key=lambda n: int(re.findall(r"(\d+)", n)[0]))
        for n in names:
            xml = z.read(n).decode("utf-8", "ignore")
            no = int(re.findall(r"(\d+)", n)[0])
            for m in re.finditer(r"_x00[0-9A-Fa-f]{2}_", xml):
                ctx = re.sub(r"<[^>]*>", "", xml[max(0, m.start() - 60):m.end() + 30])
                out.append((no, "制御文字", ctx.strip()[:40],
                            f"{m.group(0)} が文字として入っています。"
                            "パスを書いた文字列のエスケープ漏れです"))
    return out


def check(path: str, *, max_gap: float, min_pt: float, min_img_w: float,
          summary_prefix: str, margin: float) -> tuple[list, list]:
    prs = Presentation(path)
    SW, SH = cm(prs.slide_width), cm(prs.slide_height)
    major, minor = [], []

    # 描画するまで見えないため、最初に拾っておく
    for n, kind, label, detail in control_chars(path):
        major.append((n, kind, label, detail))

    for n, slide in enumerate(prs.slides, 1):
        shapes = collect(slide, n)
        content = [s for s in shapes if s.has_content]

        # ---------------------------------------------------- 重なり
        for i, a in enumerate(content):
            for b in content[i + 1:]:
                area, ow, oh = overlap_area(a, b)
                if area <= 0:
                    continue
                # かすっているだけのものは数えない
                if ow < 0.15 or oh < 0.15:
                    continue
                # キャプチャの上に注記を重ねるのは意図した表現（改善案のBefore/Afterなど）。
                # 画像の内側に完全に収まっているものは指摘しない。
                if inside(a, b) or inside(b, a):
                    continue
                small = min(a.w * a.h, b.w * b.h)
                if small <= 0 or area / small < 0.08:
                    continue
                major.append((n, "重なり",
                              f"{a.label} × {b.label}",
                              f"{ow:.2f} × {oh:.2f} cm 重複"))

        # ---------------------------------------------------- 枠外
        for s in shapes:
            if s.is_connector:
                continue
            if s.x < -margin or s.y < -margin or s.right > SW + margin or s.bottom > SH + margin:
                over = max(-s.x, -s.y, s.right - SW, s.bottom - SH)
                major.append((n, "枠外", s.label, f"{over:.2f} cm はみ出し"))

        # ---------------------------------------------------- 画像
        pics = [s for s in shapes if s.is_picture]
        split_layout = len(pics) > 1   # 分割して横並びにしているページ
        for s in shapes:
            if not s.is_picture or s.w <= 0 or s.h <= 0:
                continue
            try:
                px, py = s.raw.image.size
            except Exception:
                px = py = 0
            if px and py:
                want, got = py / px, s.h / s.w
                if want and abs(want - got) / want > 0.02:
                    major.append((n, "画像のゆがみ", s.label,
                                  f"元 {want:.2f} → 配置 {got:.2f}"))
            if s.w < min_img_w and not split_layout:
                bucket = major if s.w < min_img_w / 2 else minor
                bucket.append((n, "細い画像", s.label,
                               f"幅 {s.w:.1f} cm（縦横比 {s.h / s.w:.1f}:1）。"
                               "解説で触れた箇所を切り出してから貼る"))

        # ---------------------------------------------------- 文字サイズ
        # 注記（要約枠より下の帯）は小さくてよい。本文だけを見る。
        summ0 = next((s for s in shapes if s.text.startswith(summary_prefix)), None)
        body_limit = summ0.y if summ0 else SH
        for s in shapes:
            if not getattr(s.raw, "has_text_frame", False):
                continue
            if s.y >= body_limit - 0.3:
                continue
            # 箱の中の本文だけを見る。キャプションやグラフのラベルは
            # 小さくてよい（意図した使い分けを指摘しても意味がない）。
            if s.tag != "sp" or s.raw.shape_type == MSO_SHAPE_TYPE.TEXT_BOX:
                continue
            for par in s.raw.text_frame.paragraphs:
                for r in par.runs:
                    if r.font.size and r.font.size.pt < min_pt and r.text.strip():
                        minor.append((n, "文字が小さい", r.text.strip()[:26],
                                      f"{r.font.size.pt:.1f} pt"))
                        break
                else:
                    continue
                break

        # ---------------------------------------------------- 下の空き
        summ = summ0
        if summ:
            limit = summ.y
            body = [s for s in content if s is not summ and s.y < limit - 0.3]
            if body:
                gap = limit - max(s.bottom for s in body)
                if gap >= max_gap:
                    minor.append((n, "下が空いている", "",
                                  f"{gap:.1f} cm。行を増やす／要素を大きくする／解釈を足す"))

    return major, minor


def report(path: str, major: list, minor: list) -> int:
    name = os.path.basename(path)
    print(f"■ {name}")
    for title, items in (("要対応", major), ("確認", minor)):
        if not items:
            continue
        print(f"\n【{title}】{len(items)} 件")
        for n, kind, label, detail in items:
            head = f"  P{n:>3}  {kind}"
            print(f"{head:<22} {detail}")
            if label:
                print(f"{'':<22} {label}")
    if not major and not minor:
        print("  指摘はありません。")
    elif not major:
        print(f"\n要対応はありません（確認 {len(minor)} 件）。")
    print()
    return 1 if major else 0


def main() -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    ap = argparse.ArgumentParser(description="PowerPointの体裁を検査する")
    ap.add_argument("pptx", nargs="+", help="検査するファイル")
    ap.add_argument("--max-gap", type=float, default=3.0,
                    help="内容の下端と要約枠の間の許容量(cm)。既定 3.0")
    ap.add_argument("--min-pt", type=float, default=6.0,
                    help="箱の中の本文の最小サイズ(pt)。既定 6.0（これを下回ると"
                         "どんな意図でも読めない）。注記帯とキャプションは対象外")
    ap.add_argument("--min-img-width", type=float, default=5.0,
                    help="画像の最小幅(cm)。既定 5.0")
    ap.add_argument("--margin", type=float, default=0.02,
                    help="枠外判定の許容量(cm)。既定 0.02")
    ap.add_argument("--summary-prefix", default="【このページの要約】",
                    help="要約枠の書き出し。下の空きの判定に使う")
    a = ap.parse_args()

    rc = 0
    for p in a.pptx:
        if not os.path.exists(p):
            print(f"ファイルがありません: {p}")
            rc = 1
            continue
        major, minor = check(p, max_gap=a.max_gap, min_pt=a.min_pt,
                             min_img_w=a.min_img_width,
                             summary_prefix=a.summary_prefix, margin=a.margin)
        rc |= report(p, major, minor)
    return rc


if __name__ == "__main__":
    raise SystemExit(main())
