# -*- coding: utf-8 -*-
"""AIっぽさ撲滅憲法の機械点検。pptx / docx / md / txt を読み、当たりそうな箇所を列挙する。

使い方：python ai_check.py 資料.pptx [--all]
  --all  出典・目次の行も含めて点検する（既定では「出典」「目次」を含む行は飛ばす）

人の点検の代わりにはならない。拾ったものを人が読んで決める。
"""
import re, subprocess, sys
from pathlib import Path

BAN_VERBS = ["置く", "乗せる", "回す", "繋げ", "繋が", "つなげ", "落とし込", "寄り添", "伴走", "加速", "紐づけ", "紐付け"]
BAN_WORDS = ["可視化", "見える化", "最適化", "効率化", "実現", "活用", "推進", "強化", "向上", "促進", "定着", "価値",
             "貢献", "包括的", "体系的", "戦略的", "シームレス", "ソリューション", "アプローチ", "インサイト", "ナレッジ"]
BAN_PHRASES = ["することで", "を通じて", "において", "という観点", "に繋がる", "につながる", "が鍵", "が重要です", "と言えるでしょう",
               "結論から言うと", "まず初めに", "様々な", "適切な", "効果的な", "しっかりと", "ぜひ"]
MARKS = ["！", "✓", "✔", "▶", "★", "■", "◆"]
EMOJI = re.compile("[\U0001F300-\U0001FAFF\u2600-\u27BF]")

def load(path):
    p = Path(path)
    if p.suffix.lower() in (".pptx", ".docx", ".xlsx"):
        r = subprocess.run(["markitdown", str(p)], capture_output=True, text=True, encoding="utf-8", errors="replace")
        return r.stdout
    return p.read_text(encoding="utf-8", errors="replace")

def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    if not args:
        print(__doc__); return
    allrows = "--all" in sys.argv
    text = load(args[0])
    slide = "-"
    hits = []
    titles = []
    bullets_per_slide = {}
    for raw in text.splitlines():
        m = re.match(r"<!-- Slide number: (\d+) -->", raw)
        if m: slide = m.group(1); continue
        line = raw.strip()
        if not line: continue
        if not allrows and ("出典" in line or "目次" in line): continue
        if line.startswith("# "):
            t = line[2:]
            titles.append((slide, t))
            if "：" in t or re.search(r"\S:\s", t): hits.append((slide, "第1条 見出しが「A：B」", t))
            if re.search(r"(について|の全体像|とは|のポイント)$", t): hits.append((slide, "第2条 中身のない見出し", t))
        for v in BAN_VERBS:
            if v in line: hits.append((slide, f"第4条 比喩の動詞「{v}」", line[:80]))
        for w in BAN_WORDS:
            if w in line: hits.append((slide, f"第5条 一般論の語「{w}」", line[:80]))
        for ph in BAN_PHRASES:
            if ph in line: hits.append((slide, f"第6条 常套句「{ph}」", line[:80]))
        for mk in MARKS:
            if mk in line: hits.append((slide, f"第7条 記号「{mk}」", line[:80]))
        if EMOJI.search("".join(ch for ch in line if ch not in MARKS)): hits.append((slide, "第7条 絵文字", line[:80]))  # ★など記号の欄で数えたものは除く
        if line.count("／") >= 3: hits.append((slide, f"第11条 「／」が{line.count('／')}回", line[:80]))
        if re.match(r"^(\d+\.|[・\-\*])\s*", line):
            bullets_per_slide.setdefault(slide, 0); bullets_per_slide[slide] += 1
    # 第9条：箇条書きの数が毎回同じ
    counts = [c for s, c in bullets_per_slide.items() if c >= 3]
    if len(counts) >= 4 and len(set(counts)) == 1:
        hits.append(("-", "第9条 数をそろえて並べる", f"箇条書きのある{len(counts)}枚すべてが{counts[0]}項目"))
    # 第13条：体言止めの比率（文末が「。」で終わる行の割合）
    body = [l.strip() for l in text.splitlines() if l.strip() and not l.startswith("#") and not l.startswith("<!--") and not l.startswith("|")]
    long_lines = [l for l in body if len(l) >= 15]
    if long_lines:
        sent = sum(1 for l in long_lines if re.search(r"(です|ます|でした|ました|ません|ください)[。）]?$", l))
        ratio = sent / len(long_lines)
        if ratio < 0.3:
            hits.append(("-", "第13条 体言止めが多い", f"15字以上の行{len(long_lines)}のうち、です・ますで終わる行は{sent}（{ratio:.0%}）"))
    print(f"見出し {len(titles)} 件、指摘 {len(hits)} 件\n")
    print("■ 見出しだけを通して読む")
    for s, t in titles: print(f"  [{s}] {t}")
    print("\n■ 指摘（人が読んで決める）")
    for s, kind, l in hits: print(f"  [{s}] {kind}：{l}")

if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    main()
