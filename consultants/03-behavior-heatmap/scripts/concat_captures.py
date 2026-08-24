"""
Clarity ヒートマップ 連結ツール（汎用公開版）


clarity_auto_capture_v2.py が出力した連番PNG群を、
重複を自動検出して縦方向に連結し、1枚の縦長画像にする。

【3つの実行モード】

[1] 設定ファイル駆動モード（推奨・人為ミス防止）
    python concat_captures.py
      → _scripts/concat_captures_config.txt を読み込み
      → _scripts/BeforeConCat/*.zip を展開・連結
      → _scripts/AfterConCat/<指定名>.png に出力

[2] 単一フォルダモード（既存）
    python concat_captures.py "C:\\pyClarity\\captures_20260518_153022"
      → そのフォルダ内の連番PNGを連結
      → フォルダ内に _stitched.png を出力

[3] バッチモード（既存）
    python concat_captures.py --all "C:\\pyClarity"
      → 親フォルダ配下の captures_* 全フォルダを一括連結

【依存】 Pillow (PIL), numpy
"""

import sys
import re
import shutil
import zipfile
from pathlib import Path
from PIL import Image
import numpy as np


# ──────────────────────────────────────
# 設定駆動モードのパス定義
# ──────────────────────────────────────
DEFAULT_BEFORE_DIRNAME = "BeforeConCat"
DEFAULT_AFTER_DIRNAME  = "AfterConCat"
DEFAULT_TEMP_DIRNAME   = "_temp_unzip"
DEFAULT_CONFIG_NAME    = "concat_captures_config.txt"


# ──────────────────────────────────────
# 重複検出
# ──────────────────────────────────────
def find_vertical_overlap(arr_a, arr_b, *,
                          min_overlap=20,
                          max_overlap_pct=0.95,
                          sig_cols=200):
    """arr_a 下部と arr_b 上部の重複ピクセル数を返す。"""
    h_a, w_a = arr_a.shape[:2]
    h_b, w_b = arr_b.shape[:2]
    w = min(w_a, w_b)

    max_overlap = min(int(h_a * max_overlap_pct),
                      int(h_b * max_overlap_pct))
    if max_overlap < min_overlap:
        return 0, float("inf")

    cw = min(sig_cols, w)
    start = (w - cw) // 2
    sig_a = arr_a[:, start:start + cw].astype(np.float32).mean(axis=(1, 2))
    sig_b = arr_b[:, start:start + cw].astype(np.float32).mean(axis=(1, 2))

    best_overlap = min_overlap
    best_score = float("inf")

    for overlap in range(min_overlap, max_overlap + 1):
        a_bottom = sig_a[h_a - overlap:h_a]
        b_top = sig_b[0:overlap]
        diff = float(np.mean((a_bottom - b_top) ** 2))
        if diff < best_score:
            best_score = diff
            best_overlap = overlap

    return best_overlap, best_score


# ──────────────────────────────────────
# フォルダ単位の連結
# ──────────────────────────────────────
def numeric_key(path: Path) -> int:
    m = re.match(r"^(\d+)", path.stem)
    return int(m.group(1)) if m else 0


def stitch_folder(folder: Path, output: Path = None,
                  verbose: bool = True) -> Path | None:
    """folder 内の 0001.png 等を順番に連結して1枚に。"""
    pngs = sorted(
        [p for p in folder.glob("*.png") if re.match(r"^\d+", p.stem)],
        key=numeric_key,
    )

    if not pngs:
        if verbose:
            print(f"  [SKIP] {folder} に連番PNGがありません")
        return None

    if verbose:
        print(f"\n[CONCAT] {folder.name}")
        print(f"  対象: {len(pngs)} 枚")

    images = []
    for p in pngs:
        try:
            img = Image.open(p).convert("RGB")
            images.append(img)
        except Exception as e:
            if verbose:
                print(f"  [WARN] {p.name} 読み込み失敗: {e}")

    if not images:
        if verbose:
            print(f"  [SKIP] 有効な画像なし")
        return None

    arrs = [np.array(img) for img in images]

    widths = [a.shape[1] for a in arrs]
    if len(set(widths)) > 1:
        target_w = widths[0]
        if verbose:
            print(f"  [INFO] 幅にばらつき {set(widths)} → {target_w}px に統一")
        for i in range(1, len(arrs)):
            if arrs[i].shape[1] != target_w:
                img = Image.fromarray(arrs[i])
                ratio = target_w / arrs[i].shape[1]
                new_h = int(arrs[i].shape[0] * ratio)
                img = img.resize((target_w, new_h), Image.LANCZOS)
                arrs[i] = np.array(img)

    w = arrs[0].shape[1]

    if len(arrs) == 1:
        result = Image.fromarray(arrs[0])
        if output is None:
            output = folder / "_stitched.png"
        result.save(output)
        if verbose:
            print(f"  [OUT] {output}  ({w}x{arrs[0].shape[0]}px)")
        return output

    if verbose:
        print(f"  重複を検出中...")
    overlaps = []
    for i in range(len(arrs) - 1):
        overlap, score = find_vertical_overlap(arrs[i], arrs[i + 1])
        overlaps.append(overlap)
        if verbose and ((i + 1) % 5 == 0 or i == 0 or i == len(arrs) - 2):
            print(f"    [{i+1:3d}→{i+2:3d}] overlap={overlap:4d}px  score={score:.1f}")

    y_offsets = [0]
    for i, overlap in enumerate(overlaps):
        prev_h = arrs[i].shape[0]
        y_offsets.append(y_offsets[i] + prev_h - overlap)

    last_h = arrs[-1].shape[0]
    total_h = y_offsets[-1] + last_h

    if verbose:
        print(f"  連結後サイズ: {w}x{total_h}px")
        print(f"  （連結なしなら {w}x{sum(a.shape[0] for a in arrs)}px だった）")

    canvas = np.zeros((total_h, w, 3), dtype=np.uint8)
    for arr, y_off in zip(arrs, y_offsets):
        h = arr.shape[0]
        canvas[y_off:y_off + h] = arr

    result = Image.fromarray(canvas)

    if output is None:
        output = folder / "_stitched.png"
    output.parent.mkdir(parents=True, exist_ok=True)
    result.save(output)

    if verbose:
        print(f"  [OUT] {output}")

    return output


def stitch_all(parent: Path) -> list:
    """parent 直下の captures_* フォルダを全部連結。"""
    targets = sorted([p for p in parent.iterdir()
                      if p.is_dir() and p.name.startswith("captures_")])
    if not targets:
        print(f"ERROR: {parent} に captures_* フォルダがありません")
        return []

    print(f"バッチ処理: {len(targets)} フォルダ")
    results = []
    for t in targets:
        try:
            r = stitch_folder(t)
            if r:
                results.append(r)
        except Exception as e:
            print(f"  [ERROR] {t.name}: {e}")
    print(f"\n=== 完了: {len(results)} / {len(targets)} フォルダ ===")
    return results


# ──────────────────────────────────────
# 設定ファイル駆動モード
# ──────────────────────────────────────
def url_to_pagename(url: str) -> str:
    """URLからページ短縮名を生成する。"""
    u = url.strip().rstrip("/")
    if re.match(r"^https?://[^/]+$", u):
        return "TOP"
    parts = [p for p in u.split("/") if p and "//" not in p]
    tail = parts[-1] if parts else "page"
    safe = re.sub(r"[^0-9A-Za-z_-]+", "_", tail).strip("_")
    return safe or "page"


def _fix_zip_extension(name: str) -> tuple:
    """ZIPファイル名の拡張子を補正。(補正後の名前, 補正したか) を返す。"""
    original = name
    # .を打ち忘れて「.zipのつもりがzipで終わっている」ケースを補正
    if name.endswith("zip") and not name.endswith(".zip"):
        # 「xxxzip」→「xxx.zip」
        name = name[:-3] + ".zip"
    # 拡張子そのものがない場合は付加
    elif not name.lower().endswith(".zip"):
        name = name + ".zip"
    return name, (name != original)


def parse_config(config_path: Path) -> list:
    """
    設定ファイルを読んで [(出力名, ZIP名), ...] のリストを返す。

    対応するフォーマット（markdown風・推奨）:
      # ヒートマップ対象URL
      https://example.com/some/path/
      ## SP                           ← デバイス(SP/PC)
      ### CLICK_capture_folder: xxx.zip
      ### SCROLL_capture_folder: xxx.zip
      ## PC
      ### CLICK_capture_folder: xxx.zip
      ### SCROLL_capture_folder: xxx.zip

    出力名は H<NN>_<ページ>_<デバイス>_<タイプ> 形式で自動生成される。
    例: H01_TOP_SP_Click, H02_TOP_SP_Scroll, ...
    """
    entries = []
    current_url = None
    current_device = None
    h_counter = 0

    with open(config_path, encoding="utf-8") as f:
        for lineno, raw in enumerate(f, 1):
            line = raw.rstrip()
            stripped = line.strip()
            if not stripped:
                continue

            # === H3: ### CLICK_/SCROLL_capture_folder: zipname ===
            if stripped.startswith("###"):
                content = stripped.lstrip("#").strip()
                if ":" not in content:
                    continue
                key, _, val = content.partition(":")
                key = key.strip()
                val = val.strip()
                if not val:
                    continue

                key_upper = key.upper()
                if key_upper.startswith("CLICK"):
                    type_label = "Click"
                elif key_upper.startswith("SCROLL"):
                    type_label = "Scroll"
                else:
                    print(f"  [WARN] 行{lineno}: 不明な種別: {key}")
                    continue

                zip_name, fixed = _fix_zip_extension(val)
                if fixed:
                    print(f"  [FIX] 行{lineno}: 拡張子を補正: {val} → {zip_name}")

                if current_url is None:
                    print(f"  [WARN] 行{lineno}: URLが先に定義されていない")
                    continue
                if current_device is None:
                    print(f"  [WARN] 行{lineno}: デバイス(SP/PC)が先に定義されていない")
                    continue

                h_counter += 1
                page_name = url_to_pagename(current_url)
                output_name = f"H{h_counter:02d}_{page_name}_{current_device}_{type_label}"
                entries.append((output_name, zip_name))
                continue

            # === H2: ## SP / ## PC ===
            if stripped.startswith("##"):
                content = stripped.lstrip("#").strip()
                device = content.upper()
                if device in ("PC", "SP"):
                    current_device = device
                else:
                    current_device = None
                continue

            # === H1: # ヘッダ（URLブロックの境界）===
            if stripped.startswith("#"):
                # 新しいURLブロックの開始 → URL/デバイス状態をリセット
                current_url = None
                current_device = None
                continue

            # === URL ===
            if stripped.startswith("http://") or stripped.startswith("https://"):
                current_url = stripped
                continue

            # === （旧フォーマット互換）"出力名,ZIP名" ===
            if "," in stripped:
                out_name, _, zip_name = stripped.partition(",")
                out_name = out_name.strip()
                zip_name = zip_name.strip()
                if out_name and zip_name:
                    if out_name.lower().endswith(".png"):
                        out_name = out_name[:-4]
                    zip_name, fixed = _fix_zip_extension(zip_name)
                    if fixed:
                        print(f"  [FIX] 行{lineno}: 拡張子を補正 → {zip_name}")
                    entries.append((out_name, zip_name))
                continue

            print(f"  [SKIP] 行{lineno}: 不明な行: {stripped[:60]}")

    return entries


def run_from_config(config_path: Path = None, base_dir: Path = None) -> bool:
    """設定ファイル駆動で一括処理。成功なら True。"""
    if base_dir is None:
        base_dir = Path(__file__).parent
    if config_path is None:
        config_path = base_dir / DEFAULT_CONFIG_NAME

    if not config_path.exists():
        print(f"ERROR: 設定ファイルが見つかりません: {config_path}")
        print(f"       テンプレートを作成するには: --init オプション")
        return False

    before_dir = base_dir / DEFAULT_BEFORE_DIRNAME
    after_dir  = base_dir / DEFAULT_AFTER_DIRNAME
    temp_dir   = base_dir / DEFAULT_TEMP_DIRNAME

    if not before_dir.exists():
        print(f"ERROR: 入力フォルダが見つかりません: {before_dir}")
        print(f"       このフォルダを作って、その中にZIPファイルを置いてください")
        return False

    after_dir.mkdir(exist_ok=True)
    if temp_dir.exists():
        shutil.rmtree(temp_dir, ignore_errors=True)
    temp_dir.mkdir(exist_ok=True)

    entries = parse_config(config_path)
    if not entries:
        print(f"ERROR: 設定ファイルに有効なエントリがありません")
        return False

    # ヘッダー
    print("=" * 60)
    print(f"設定ファイル: {config_path.name}")
    print(f"エントリ数:   {len(entries)}")
    print(f"入力フォルダ: {before_dir}")
    print(f"出力フォルダ: {after_dir}")
    print("=" * 60)

    # 事前チェック（全ZIPが揃っているか）
    print("\n--- 事前チェック（全ZIPの存在確認） ---")
    missing = []
    for out_name, zip_name in entries:
        zip_path = before_dir / zip_name
        mark = "OK" if zip_path.exists() else "NG"
        print(f"  [{mark}] {out_name + '.png':35s} ← {zip_name}")
        if not zip_path.exists():
            missing.append(zip_name)

    if missing:
        print(f"\n❌ ERROR: {len(missing)}個のZIPが見つかりません")
        for m in missing:
            print(f"     - {m}")
        print(f"\n  入力フォルダ {before_dir} の中身を確認してください。")
        print(f"  または concat_captures_config.txt のZIP名を実際のファイル名に合わせてください。")
        return False

    # 連結実行
    print(f"\n--- 連結処理開始 ---")
    successes = []
    failures = []

    for i, (out_name, zip_name) in enumerate(entries, 1):
        zip_path = before_dir / zip_name
        print(f"\n[{i}/{len(entries)}] {out_name}.png  ← {zip_name}")

        # 展開
        extract_dir = temp_dir / Path(zip_name).stem
        if extract_dir.exists():
            shutil.rmtree(extract_dir)
        extract_dir.mkdir(parents=True)

        try:
            with zipfile.ZipFile(zip_path, "r") as z:
                z.extractall(extract_dir)
        except Exception as e:
            print(f"  [ERROR] ZIP展開失敗: {e}")
            failures.append(out_name)
            continue

        # 実際の captures フォルダを特定
        # ZIPの中身がサブフォルダ1つだけの場合はその中を使う
        actual_dir = extract_dir
        items = [p for p in extract_dir.iterdir() if not p.name.startswith(".")]
        if len(items) == 1 and items[0].is_dir():
            actual_dir = items[0]

        # 連結
        output_path = after_dir / f"{out_name}.png"
        try:
            result = stitch_folder(actual_dir, output=output_path, verbose=False)
            if result:
                size = output_path.stat().st_size
                with Image.open(output_path) as img:
                    w, h = img.size
                print(f"  [OK] {output_path.name}  ({w}x{h}px, {size:,} bytes)")
                successes.append(out_name)
            else:
                print(f"  [ERROR] 連結失敗（連番PNGが見つからない可能性）")
                failures.append(out_name)
        except Exception as e:
            print(f"  [ERROR] 連結中に例外: {e}")
            failures.append(out_name)

    # 後片付け
    shutil.rmtree(temp_dir, ignore_errors=True)

    # サマリー
    print()
    print("=" * 60)
    print(f"完了: 成功 {len(successes)} / {len(entries)}")
    if failures:
        print(f"失敗: {failures}")
    print(f"出力先: {after_dir}")
    print("=" * 60)
    return len(failures) == 0


# ──────────────────────────────────────
# テンプレート設定ファイル生成
# ──────────────────────────────────────
def write_config_template(path: Path):
    """設定ファイルのテンプレートを書き出す。"""
    template = """# Clarity 連結ツール設定ファイル
# ============================================================
# このファイルを編集してから「python concat_captures.py」を実行してください。
#
# 形式: <出力ファイル名>,<入力ZIPファイル名>
#
# - 出力ファイル名: 拡張子(.png)は自動で付くので不要
# - 入力ZIPファイル: _scripts/BeforeConCat/ に置いたZIPの名前
# - # で始まる行と空行は無視される
# - カンマで区切る（前後の空白はOK）
#
# 推奨の出力ファイル名規則: H<番号>_<ページ>_<デバイス>_<タイプ>
#   例: H01_TOP_PC_Click, H02_TOP_PC_Scroll, ...
#
# このファイル自体は、毎月、その月のZIPファイル名に合わせて編集してください。
# ============================================================

# 対象月分（実際のZIPファイル名に書き換えてください）
H01_TOP_PC_Click,captures_YYYYMMDD_HHMMSS.zip
H02_TOP_PC_Scroll,captures_YYYYMMDD_HHMMSS.zip
H03_TOP_SP_Click,captures_YYYYMMDD_HHMMSS.zip
H04_TOP_SP_Scroll,captures_YYYYMMDD_HHMMSS.zip
H05_contact_SP_Click,captures_YYYYMMDD_HHMMSS.zip
H06_contact_SP_Scroll,captures_YYYYMMDD_HHMMSS.zip
H07_product_SP_Click,captures_YYYYMMDD_HHMMSS.zip
H08_product_SP_Scroll,captures_YYYYMMDD_HHMMSS.zip
"""
    path.write_text(template, encoding="utf-8")
    print(f"[OK] テンプレート作成: {path}")


def init_workspace(base_dir: Path = None):
    """BeforeConCat/, AfterConCat/, config を初期化。"""
    if base_dir is None:
        base_dir = Path(__file__).parent
    before_dir = base_dir / DEFAULT_BEFORE_DIRNAME
    after_dir  = base_dir / DEFAULT_AFTER_DIRNAME
    config     = base_dir / DEFAULT_CONFIG_NAME

    before_dir.mkdir(exist_ok=True)
    after_dir.mkdir(exist_ok=True)
    print(f"[OK] フォルダ作成: {before_dir}")
    print(f"[OK] フォルダ作成: {after_dir}")

    if config.exists():
        print(f"[SKIP] 設定ファイルは既に存在: {config}")
    else:
        write_config_template(config)


# ──────────────────────────────────────
# CLI
# ──────────────────────────────────────
def main():
    args = sys.argv[1:]

    # 引数なし → 設定ファイル駆動（デフォルト）
    if not args:
        run_from_config()
        return

    # --init → ワークスペース初期化
    if args[0] == "--init":
        init_workspace()
        return

    # --config <path>
    if args[0] == "--config":
        if len(args) < 2:
            print("ERROR: --config の後にパスを指定")
            sys.exit(1)
        run_from_config(config_path=Path(args[1]))
        return

    # --all <parent>
    if args[0] == "--all":
        if len(args) < 2:
            print("ERROR: --all の後に親フォルダを指定")
            sys.exit(1)
        parent = Path(args[1])
        if not parent.is_dir():
            print(f"ERROR: {parent} はフォルダではありません")
            sys.exit(1)
        stitch_all(parent)
        return

    # 単一フォルダモード
    folder = Path(args[0])
    if not folder.is_dir():
        print(f"ERROR: {folder} はフォルダではありません")
        sys.exit(1)

    output = None
    if "--out" in args:
        idx = args.index("--out")
        if idx + 1 >= len(args):
            print("ERROR: --out の後に出力パスを指定")
            sys.exit(1)
        output = Path(args[idx + 1])

    stitch_folder(folder, output)


if __name__ == "__main__":
    main()
