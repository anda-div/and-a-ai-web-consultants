#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""extract_pptx.py — PPTXから全テキストと数値台帳を抽出する（標準ライブラリのみ）

使い方: python extract_pptx.py <入力.pptx> <出力フォルダ>

出力:
  text.md      … 全スライドのテキスト（表示順・ノート含む）
  numbers.json … 数値台帳（スライド番号・数値・単位・文脈）
  numbers.md   … 数値台帳の一覧表（人間が読む用）
  summary.json … 件数サマリー
"""
import sys
import os
import json
import re
import zipfile
import posixpath
import xml.etree.ElementTree as ET

P = 'http://schemas.openxmlformats.org/presentationml/2006/main'
A = 'http://schemas.openxmlformats.org/drawingml/2006/main'
R = 'http://schemas.openxmlformats.org/officeDocument/2006/relationships'
REL = 'http://schemas.openxmlformats.org/package/2006/relationships'

# 数値＋単位（直後に付く単位を最長一致で拾う）
NUM_RE = re.compile(
    r'(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)'
    r'\s*(％|%|倍|万件|万人|万円|万|億円|億|兆|件|円|人|回|秒|分|位|ページ|枚|本|社|pt|px|ms)?'
)
DATE_LIKE = re.compile(r'^(19|20)\d{2}$')


def rels_map(z, part):
    """パーツのリレーション {rId: 解決済みパス} を返す"""
    d = posixpath.dirname(part)
    rp = posixpath.join(d, '_rels', posixpath.basename(part) + '.rels')
    m = {}
    if rp in z.namelist():
        root = ET.fromstring(z.read(rp))
        for rel in root.findall(f'{{{REL}}}Relationship'):
            if rel.get('TargetMode') == 'External':
                m[rel.get('Id')] = ('external', rel.get('Target'), rel.get('Type'))
            else:
                tgt = posixpath.normpath(posixpath.join(d, rel.get('Target')))
                m[rel.get('Id')] = ('internal', tgt, rel.get('Type'))
    return m


def slide_order(z):
    """presentation.xml の sldIdLst に基づく表示順のスライドパス一覧"""
    pres = ET.fromstring(z.read('ppt/presentation.xml'))
    rm = rels_map(z, 'ppt/presentation.xml')
    parts = []
    lst = pres.find(f'{{{P}}}sldIdLst')
    if lst is None:
        raise SystemExit('sldIdLst が見つかりません')
    for sld in lst.findall(f'{{{P}}}sldId'):
        rid = sld.get(f'{{{R}}}id')
        parts.append(rm[rid][1])
    return parts


def paragraphs(xml_bytes):
    """文書順の段落テキスト一覧（表・グループ図形内も含む）"""
    root = ET.fromstring(xml_bytes)
    out = []
    for p in root.iter(f'{{{A}}}p'):
        text = ''.join(t.text or '' for t in p.iter(f'{{{A}}}t'))
        text = text.strip()
        if text:
            out.append(text)
    return out


def notes_part(z, slide_part):
    for _, (kind, tgt, typ) in rels_map(z, slide_part).items():
        if kind == 'internal' and typ.endswith('/notesSlide'):
            return tgt
    return None


def extract_numbers(slide_no, paras):
    rows = []
    for para in paras:
        for m in NUM_RE.finditer(para):
            raw, unit = m.group(1), (m.group(2) or '')
            plain = raw.replace(',', '')
            kind = 'number'
            if unit == '' and DATE_LIKE.match(plain):
                kind = 'year?'  # 西暦の可能性（検算対象から外してよい候補）
            s = max(0, m.start() - 60)
            e = min(len(para), m.end() + 60)
            rows.append({
                'slide': slide_no,
                'raw': raw + unit,
                'value': float(plain),
                'unit': unit,
                'kind': kind,
                'context': para[s:e],
            })
    return rows


def main():
    if len(sys.argv) != 3:
        raise SystemExit('使い方: python extract_pptx.py <入力.pptx> <出力フォルダ>')
    src, outdir = sys.argv[1], sys.argv[2]
    os.makedirs(outdir, exist_ok=True)

    z = zipfile.ZipFile(src)
    parts = slide_order(z)

    text_lines = [f'# テキスト抽出: {os.path.basename(src)}', '']
    all_numbers = []
    total_paras = 0

    for i, part in enumerate(parts, start=1):
        paras = paragraphs(z.read(part))
        total_paras += len(paras)
        text_lines.append(f'## スライド {i}')
        for para in paras:
            text_lines.append(f'- {para}')
        npart = notes_part(z, part)
        if npart and npart in z.namelist():
            nparas = [t for t in paragraphs(z.read(npart)) if t != str(i)]
            if nparas:
                text_lines.append(f'### スライド {i} ノート')
                for para in nparas:
                    text_lines.append(f'- {para}')
        text_lines.append('')
        all_numbers.extend(extract_numbers(i, paras))

    with open(os.path.join(outdir, 'text.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(text_lines))

    with open(os.path.join(outdir, 'numbers.json'), 'w', encoding='utf-8') as f:
        json.dump(all_numbers, f, ensure_ascii=False, indent=1)

    md = ['# 数値台帳', '', '| スライド | 数値 | 文脈 |', '|---|---|---|']
    for r in all_numbers:
        ctx = r['context'].replace('|', '\\|')
        md.append(f"| {r['slide']} | {r['raw']} | {ctx} |")
    with open(os.path.join(outdir, 'numbers.md'), 'w', encoding='utf-8') as f:
        f.write('\n'.join(md))

    summary = {
        'file': os.path.basename(src),
        'slides': len(parts),
        'paragraphs': total_paras,
        'numbers': len(all_numbers),
    }
    with open(os.path.join(outdir, 'summary.json'), 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=1)

    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass
    print(json.dumps(summary, ensure_ascii=False))


if __name__ == '__main__':
    main()
