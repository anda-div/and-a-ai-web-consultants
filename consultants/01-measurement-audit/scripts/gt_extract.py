# -*- coding: utf-8 -*-
"""
gt_extract.py — 評価対象のレポートから、全文テキストと数値台帳を抜き出す
================================================================================
対応形式： .pptx / .pdf / .docx / .md / .txt

使い方:
    python gt_extract.py <対象ファイル> <出力フォルダ>

出力:
    text.md      … 全文（PPTXはスライド単位、PDFはページ単位に区切る）
    numbers.json … 数値台帳（値・単位・出現位置・前後の文脈）
    numbers.md   … 数値台帳の一覧（人が読む用）

なぜ数値台帳を作るのか:
    レポート監査でいちばん時間を食うのは「どの数字が何回、どこに出てくるか」の把握である。
    同じ指標が別ページで違う値になっている、派生値（○倍・○%増）が元の数字と合わない、
    といった破綻は、全数を並べないと見えない。目視では必ず取りこぼす。

依存: 標準ライブラリのみ（PDFのみ pypdf があれば使う）
"""
import sys, os, re, json, zipfile, posixpath
import xml.etree.ElementTree as ET

P   = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A   = 'http://schemas.openxmlformats.org/drawingml/2006/main'
W   = 'http://schemas.openxmlformats.org/wordprocessingml/2006/main'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'    # .rels の要素
R   = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'  # r:id 属性

NUM_RE = re.compile(
    r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)'
    r'\s*(％|%|pt|倍|万件|万人|万円|万|億円|億|兆|件|円|人|回|秒|分|位|ページ|枚|本|社|px|ms)?'
)
YEAR_RE = re.compile(r'^(19|20)\d{2}$')


# ------------------------------------------------------------------ PPTX
def _slide_order(z):
    """presentation.xml の並び順どおりにスライドのパスを返す"""
    pres = 'ppt/presentation.xml'
    if pres not in z.namelist():
        return sorted(n for n in z.namelist()
                      if re.match(r'ppt/slides/slide\d+\.xml$', n))
    rels = {}
    rp = 'ppt/_rels/presentation.xml.rels'
    for r in ET.fromstring(z.read(rp)):
        rels[r.get('Id')] = posixpath.normpath(posixpath.join('ppt', r.get('Target')))
    out = []
    root = ET.fromstring(z.read(pres))
    for sid in root.iter(f'{{{P}}}sldId'):
        rid = sid.get(f'{{{R}}}id')
        if rid in rels:
            out.append(rels[rid])
    return out


def read_pptx(path):
    blocks = []
    with zipfile.ZipFile(path) as z:
        for i, part in enumerate(_slide_order(z), 1):
            if part not in z.namelist():
                continue
            root = ET.fromstring(z.read(part))
            lines = []
            for para in root.iter(f'{{{A}}}p'):
                txt = "".join(t.text or "" for t in para.iter(f'{{{A}}}t'))
                if txt.strip():
                    lines.append(txt.strip())
            # ノート
            nrels = posixpath.join(posixpath.dirname(part), '_rels',
                                   posixpath.basename(part) + '.rels')
            if nrels in z.namelist():
                for r in ET.fromstring(z.read(nrels)):
                    if 'notesSlide' in (r.get('Type') or ''):
                        np = posixpath.normpath(
                            posixpath.join(posixpath.dirname(part), r.get('Target')))
                        if np in z.namelist():
                            nroot = ET.fromstring(z.read(np))
                            ntxt = [("".join(t.text or "" for t in p.iter(f'{{{A}}}t'))).strip()
                                    for p in nroot.iter(f'{{{A}}}p')]
                            ntxt = [x for x in ntxt if x]
                            if ntxt:
                                lines.append("〔ノート〕" + " / ".join(ntxt))
            blocks.append((f"スライド {i}", lines))
    return blocks


# ------------------------------------------------------------------ DOCX
def read_docx(path):
    with zipfile.ZipFile(path) as z:
        root = ET.fromstring(z.read('word/document.xml'))
    lines = []
    for para in root.iter(f'{{{W}}}p'):
        txt = "".join(t.text or "" for t in para.iter(f'{{{W}}}t'))
        if txt.strip():
            lines.append(txt.strip())
    return [("本文", lines)]


# ------------------------------------------------------------------ PDF
def read_pdf(path):
    try:
        from pypdf import PdfReader
    except ImportError:
        try:
            from PyPDF2 import PdfReader
        except ImportError:
            print("PDFを読むには pypdf が必要です:  pip install pypdf", file=sys.stderr)
            sys.exit(2)
    r = PdfReader(path)
    return [(f"ページ {i}", [l.strip() for l in (p.extract_text() or "").splitlines() if l.strip()])
            for i, p in enumerate(r.pages, 1)]


# ------------------------------------------------------------------ TEXT
def read_text(path):
    with open(path, encoding="utf-8", errors="replace") as f:
        body = f.read()
    return [("本文", [l.strip() for l in body.splitlines() if l.strip()])]


READERS = {".pptx": read_pptx, ".docx": read_docx, ".pdf": read_pdf,
           ".md": read_text, ".txt": read_text}


# ------------------------------------------------------------------ 数値台帳
def harvest(blocks):
    out = []
    for bi, (label, lines) in enumerate(blocks, 1):
        for line in lines:
            for m in NUM_RE.finditer(line):
                raw, unit = m.group(1), m.group(2) or ""
                if not unit and YEAR_RE.match(raw):
                    continue                      # 西暦は数値台帳に入れない
                try:
                    val = float(raw.replace(",", ""))
                except ValueError:
                    continue
                s, e = max(0, m.start() - 22), min(len(line), m.end() + 22)
                out.append({"block": label, "block_index": bi,
                            "raw": raw + unit, "value": val, "unit": unit,
                            "context": line[s:e], "line": line})
    return out


def main():
    if len(sys.argv) < 3:
        print(__doc__); sys.exit(1)
    src, outdir = sys.argv[1], sys.argv[2]
    ext = os.path.splitext(src)[1].lower()
    if ext not in READERS:
        print(f"未対応の形式です: {ext}"); sys.exit(1)
    os.makedirs(outdir, exist_ok=True)

    blocks = READERS[ext](src)
    md = [f"# テキスト抽出: {os.path.basename(src)}\n"]
    for label, lines in blocks:
        md.append(f"## {label}")
        md += [f"- {l}" for l in lines]
        md.append("")
    with open(os.path.join(outdir, "text.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(md))

    nums = harvest(blocks)
    with open(os.path.join(outdir, "numbers.json"), "w", encoding="utf-8") as f:
        json.dump(nums, f, ensure_ascii=False, indent=2)

    # 同じ値が複数箇所に出るものを先に並べる（表記ゆれ・不整合が見つかりやすい）。
    # 単位なしの1桁は箇条書きの番号などノイズが多いため、末尾に分けて置く。
    by_val, meaning = {}, {}
    for n in nums:
        by_val.setdefault(n["raw"], []).append(n["block"])
        meaning[n["raw"]] = bool(n["unit"]) or abs(n["value"]) >= 10
    main_keys = [k for k in by_val if meaning[k]]
    sub_keys  = [k for k in by_val if not meaning[k]]
    rows = ["# 数値台帳\n", f"総数 {len(nums)} 件 / ユニーク {len(by_val)} 種\n",
            "## 主要な数値（単位つき、または10以上）\n",
            "| 値 | 出現数 | 出現ブロック |", "|---|---|---|"]
    for raw in sorted(main_keys, key=lambda k: -len(by_val[k])):
        blks = sorted(set(by_val[raw]))
        shown = ", ".join(blks[:14]) + (f" ほか{len(blks)-14}件" if len(blks) > 14 else "")
        rows.append(f"| {raw} | {len(by_val[raw])} | {shown} |")
    rows += ["", "## 参考（単位なしの1桁。箇条書き番号などを多く含む）\n",
             "| 値 | 出現数 |", "|---|---|"]
    for raw in sorted(sub_keys, key=lambda k: -len(by_val[k])):
        rows.append(f"| {raw} | {len(by_val[raw])} |")
    with open(os.path.join(outdir, "numbers.md"), "w", encoding="utf-8") as f:
        f.write("\n".join(rows))

    print(json.dumps({"file": os.path.basename(src), "blocks": len(blocks),
                      "lines": sum(len(l) for _, l in blocks), "numbers": len(nums)},
                     ensure_ascii=False))


if __name__ == "__main__":
    main()
