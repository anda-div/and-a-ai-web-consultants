# -*- coding: utf-8 -*-
"""Search Console の SNS プロパティ（Instagram など）の検索データを書き出す

Search Console の「プラットフォーム プロパティ」（Instagram・TikTok・X・YouTube）は、
2026-10 時点で Search Console API に対応していない。画面の識別子
`sc-creator-profile:instagram.com/<アカウント>` を API に渡すと、`sites.get` は 404、
`searchAnalytics.query` は 400（INVALID_ARGUMENT）になる。権限ではなく形式として
受け付けていない。

そこで、画面の「エクスポート → CSV をダウンロード」をブラウザ操作で行う。
**取得の前に API を1回試し、通れば API で取ってブラウザは開かない。**
API が対応したら、ブラウザ操作は自然に使われなくなる。

    初回のみ（Google アカウントでサインイン。自動操作なしのブラウザが開く）
    python shared/scripts/sc_platform_export.py --login-plain

    取得
    python shared/scripts/sc_platform_export.py \\
        --resource "sc-creator-profile:instagram.com/<アカウント>" \\
        --start 2026-10-01 --end 2026-10-31 --out _input/search_console_sns/2026-10

    画面の作りを調べる（ボタンが見つからなくなったとき）
    python shared/scripts/sc_platform_export.py --resource ... --start ... --end ... \\
        --out ... --discover

サインインはお客様ご自身が行う。パスワードをこのスクリプト・設定ファイル・
CLI AI に渡さない。サインイン状態は `--profile`（既定 `.sc_profile`）に保存され、
**このフォルダは Git に入れない**（`.gitignore` 登録済み）。

手順と注意は shared/SEARCH_CONSOLE_PLATFORM_EXPORT.md。
"""
from __future__ import annotations

import argparse
import csv
import io
import json
import os
import re
import sys
import time
import zipfile
from datetime import date, datetime
from pathlib import Path
from urllib.parse import quote, urlencode

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# セキュリティソフトが HTTPS を検査している PC でも通るようにする。
# 検査されていない PC では何もしない。理由は tls_env.py に書いてある。
try:
    import tls_env
    tls_env.enable()
except ImportError:      # 単体で持ち出したときも動くようにする
    pass

UI_BASE = "https://search.google.com/search-console/performance/search-analytics"
API_BASE = "https://searchconsole.googleapis.com/webmasters/v3/sites"
SCOPE = "https://www.googleapis.com/auth/webmasters.readonly"

# 画面の文言。日本語と英語の両方で探す。見つからなくなったら --discover で調べ、ここを直す
EXPORT_LABELS = ("エクスポート", "Export")
CSV_LABELS = ("CSV をダウンロード", "CSVをダウンロード", "Download CSV")
# 「2026/10/15 以降のデータが表示されています」のような、集計開始日の表示
SINCE_PATTERNS = (
    r"(\d{4})[/年.-](\d{1,2})[/月.-](\d{1,2})日?\s*以降",
    r"(?:since|from)\s+([A-Z][a-z]{2,8})\s+(\d{1,2}),?\s+(\d{4})",
)
MONTHS = {m: n for n, m in enumerate(
    ("jan", "feb", "mar", "apr", "may", "jun", "jul", "aug", "sep", "oct", "nov", "dec"), 1)}


# ---------------------------------------------------------------- 入力の形
def parse_day(s: str) -> date:
    try:
        return datetime.strptime(s, "%Y-%m-%d").date()
    except ValueError:
        raise SystemExit(f"日付は YYYY-MM-DD で指定してください: {s}")


def ui_url(resource: str, start: date, end: date) -> str:
    """検索パフォーマンスの画面のURL。期間は YYYYMMDD で渡す。"""
    return UI_BASE + "?" + urlencode({
        "resource_id": resource,
        "start_date": start.strftime("%Y%m%d"),
        "end_date": end.strftime("%Y%m%d"),
    })


def safe_name(resource: str) -> str:
    """プロパティごとの保存フォルダ名。記号はファイル名に使えるものへ置き換える。"""
    name = resource.split(":", 1)[-1]
    return re.sub(r"[^\w.-]+", "_", name).strip("_") or "property"


def data_since(text: str) -> str:
    """画面の文から集計開始日を読む。読めなければ空。

    プロパティは**登録した日からしか集計されない。** 指定期間の頭にデータが無いのは
    正常で、それを書かずに渡すと「月の前半が0」と読まれる。
    """
    m = re.search(SINCE_PATTERNS[0], text)
    if m:
        y, mo, d = map(int, m.groups())
        return date(y, mo, d).isoformat()
    m = re.search(SINCE_PATTERNS[1], text)
    if m and m.group(1)[:3].lower() in MONTHS:
        return date(int(m.group(3)), MONTHS[m.group(1)[:3].lower()], int(m.group(2))).isoformat()
    return ""


# ---------------------------------------------------------------- API
def api_token() -> str:
    """ADC からトークンを取る。取れなければ空（ブラウザでの取得へ進む）。"""
    try:
        import google.auth
        import google.auth.transport.requests
        creds, _ = google.auth.default(scopes=[SCOPE])
        creds.refresh(google.auth.transport.requests.Request())
        return creds.token or ""
    except Exception:
        return ""


def api_query(token: str, resource: str, start: date, end: date, dims: list[str],
              row_limit: int = 25000) -> tuple[int, dict]:
    import urllib.error
    import urllib.request
    url = f"{API_BASE}/{quote(resource, safe='')}/searchAnalytics/query"
    body = json.dumps({"startDate": start.isoformat(), "endDate": end.isoformat(),
                       "dimensions": dims, "rowLimit": row_limit}).encode()
    req = urllib.request.Request(url, data=body, method="POST", headers={
        "Authorization": f"Bearer {token}", "Content-Type": "application/json"})
    try:
        with urllib.request.urlopen(req, timeout=60) as r:
            return r.status, json.loads(r.read() or b"{}")
    except urllib.error.HTTPError as e:
        try:
            return e.code, json.loads(e.read() or b"{}")
        except ValueError:
            return e.code, {}


def api_export(token: str, resource: str, start: date, end: date, out: Path) -> list[str]:
    """API で、画面の書き出しと同じ単位（検索語句・ページ・日付）の CSV を作る。"""
    files = []
    for dim, name in (("query", "クエリ.csv"), ("page", "ページ.csv"), ("date", "日付.csv")):
        status, data = api_query(token, resource, start, end, [dim])
        if status != 200:
            raise RuntimeError(f"API {dim}: {status}")
        path = out / name
        with io.open(path, "w", encoding="utf-8-sig", newline="") as f:
            w = csv.writer(f)
            w.writerow([dim, "clicks", "impressions", "ctr", "position"])
            for row in data.get("rows") or []:
                w.writerow([row["keys"][0], row.get("clicks", 0), row.get("impressions", 0),
                            row.get("ctr", 0), row.get("position", 0)])
        files.append(path.name)
    return files


# ---------------------------------------------------------------- ブラウザ
def profile_in_use(profile: Path) -> bool:
    """そのプロファイルを開いているブラウザが残っているか。

    同じプロファイルを2つのブラウザで開くと、後から閉じた側の状態で
    上書きされる（サインインした内容が消える）。起動前に確かめる。
    JOB 03 の clarity_heatmap_capture.py と同じ判定。
    """
    if sys.platform == "win32":
        lock = profile / "lockfile"
        if not lock.exists():
            return False
        try:
            with open(lock, "a"):
                pass
        except PermissionError:
            return True
        return False
    return (profile / "SingletonLock").is_symlink()


def login_plain(profile: Path, timeout: float) -> int:
    """自動操作なしのブラウザで、利用者に Google アカウントでサインインしてもらう。

    自動操作のブラウザでは、Google のサインインがメールアドレスの次の画面から進まない。
    自動操作の目印を外してすり抜ける方法は、ボット対策の回避になるので採らない。
    撮影と同じ版の Chromium を自動操作なしで開き、同じプロファイルに入ってもらう。
    """
    import subprocess
    from playwright.sync_api import sync_playwright
    profile = profile.expanduser().resolve()
    if profile_in_use(profile):
        print(f"このプロファイルを開いているブラウザが残っています: {profile}")
        print("閉じてからもう一度実行してください（同時に開くと上書きされます）")
        return 1
    profile.mkdir(parents=True, exist_ok=True)
    with sync_playwright() as pw:
        exe = pw.chromium.executable_path
    url = "https://search.google.com/search-console"
    if sys.platform == "win32":
        ps = ("$p = Start-Process -FilePath $env:SC_EXE -PassThru "
              "-ArgumentList @(\"--user-data-dir=`\"$env:SC_PROFILE`\"\", "
              "'--no-first-run', $env:SC_URL); "
              "Start-Sleep -Seconds 3; "
              "[void](New-Object -ComObject WScript.Shell).AppActivate($p.Id); $p.Id")
        env = dict(os.environ, SC_EXE=exe, SC_PROFILE=str(profile), SC_URL=url)
        subprocess.run(["powershell", "-NoProfile", "-Command", ps], env=env, check=True)
    else:
        subprocess.Popen([exe, f"--user-data-dir={profile}", "--no-first-run", url])
    print("自動操作なしのブラウザを開きました。")
    print("タイトルの末尾が「- Chromium」の窓で、Search Console にサインインしてください。")
    print("（普段の Chrome でサインインしても、このプロファイルには入りません）")
    print("SNS のプロパティが一覧に出ることを確かめたら、その窓を閉じてください。\n")
    time.sleep(5.0)
    deadline = time.time() + timeout
    while time.time() < deadline:
        if not profile_in_use(profile):
            print(f"サインイン状態を保存しました: {profile}")
            return 0
        time.sleep(2.0)
    print("時間切れです。窓を閉じてから、もう一度実行してください。")
    return 1


def manual_steps(resource: str, start: date, end: date, out: Path) -> str:
    """手で書き出す手順。ブラウザ操作が通らなかったときに表示して止まる。"""
    return "\n".join([
        "手で書き出してください（数分で済みます）。",
        f"  1. ふだんのブラウザで次を開く（Search Console にサインインした状態で）",
        f"     {ui_url(resource, start, end)}",
        f"  2. 期間が {start}〜{end} になっていることを確かめる",
        "  3. 右上の「エクスポート」→「CSV をダウンロード」を押す",
        f"  4. ダウンロードした zip を {out} に置く（展開しなくてよい）",
        "  5. もう一度このスクリプトを実行すると、置いた zip を展開して記録します",
    ])


def signed_out(page) -> bool:
    return "accounts.google.com" in page.url


def find_clickable(page, labels: tuple[str, ...]):
    """文言でボタン・メニュー項目を探す。aria-label と見えている文字の両方を見る。"""
    for label in labels:
        for loc in (page.get_by_role("button", name=label),
                    page.get_by_role("menuitem", name=label),
                    page.locator(f"[aria-label='{label}']"),
                    page.get_by_text(label, exact=True)):
            try:
                if loc.count() and loc.first.is_visible():
                    return loc.first
            except Exception:
                continue
    return None


def discover(page, out: Path) -> Path:
    """画面のボタンと文言を書き出す。画面の作りが変わったときに、どこを直すか調べるため。"""
    items = page.evaluate("""() => Array.from(document.querySelectorAll(
        'button,[role=button],[role=menuitem],[aria-label]')).slice(0, 400).map(e => ({
        tag: e.tagName, role: e.getAttribute('role'), aria: e.getAttribute('aria-label'),
        text: (e.innerText || '').trim().slice(0, 80)}))""")
    path = out / "_discover.json"
    path.write_text(json.dumps({"url": page.url, "items": items}, ensure_ascii=False, indent=1),
                    encoding="utf-8")
    page.screenshot(path=str(out / "_discover.png"), full_page=True)
    return path


def browser_export(resource: str, start: date, end: date, out: Path, profile: Path,
                   timeout: float, do_discover: bool) -> dict:
    from playwright.sync_api import sync_playwright
    if profile_in_use(profile):
        raise RuntimeError("サインイン用のプロファイルを、別のブラウザが開いています。閉じてから実行してください")
    url = ui_url(resource, start, end)
    with sync_playwright() as pw:
        # 撮影は画面ありで行う。headless は別の実行ファイルで、サインイン済みでも
        # 切れていると誤判定したことがある（JOB 03 で実地確認）
        ctx = pw.chromium.launch_persistent_context(
            str(profile), headless=False, accept_downloads=True, locale="ja-JP",
            viewport={"width": 1440, "height": 1000})
        page = ctx.pages[0] if ctx.pages else ctx.new_page()
        try:
            page.goto(url, wait_until="domcontentloaded", timeout=90_000)
            page.wait_for_timeout(4000)
            if signed_out(page):
                raise RuntimeError("サインインが切れています。--login-plain でサインインし直してください")
            page.wait_for_load_state("networkidle", timeout=int(timeout * 1000))
            if do_discover:
                p = discover(page, out)
                return {"discover": str(p)}
            text = page.inner_text("body")
            since = data_since(text)
            btn = find_clickable(page, EXPORT_LABELS)
            if btn is None:
                raise RuntimeError("「エクスポート」が見つかりません（画面の作りが変わった可能性）")
            btn.click()
            page.wait_for_timeout(800)
            item = find_clickable(page, CSV_LABELS)
            if item is None:
                raise RuntimeError("「CSV をダウンロード」が見つかりません（画面の作りが変わった可能性）")
            with page.expect_download(timeout=int(timeout * 1000)) as dl:
                item.click()
            # 手で置いた zip（out 直下）と取り違えないよう、分けて保存する
            zpath = out / "_download" / (dl.value.suggested_filename or "export.zip")
            zpath.parent.mkdir(exist_ok=True)
            dl.value.save_as(str(zpath))
            return {"zip": f"_download/{zpath.name}", "data_since": since, "url": url}
        finally:
            ctx.close()


def period_in_files(out: Path) -> str:
    """書き出しに入っている「フィルタ.csv」の期間（2026/10/15-2026/10/23）を読む。

    **フォルダ名や指定は、中身の期間の証拠にならない。** Clarity では「過去30日間」の
    まま撮って、フォルダ名だけが対象月になっていたことがある。書き出しそのものが
    持っている期間を読み、指定と突き合わせる。
    """
    for name in ("フィルタ.csv", "Filters.csv"):
        p = out / name
        if not p.exists():
            continue
        with io.open(p, encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if len(row) >= 2 and row[0] in ("日付", "Date"):
                    return row[1].strip()
    return ""


def first_day_in_files(out: Path) -> str:
    """日別の CSV の最初の日付。プロパティの集計開始日の手がかりにする。

    画面の「○月○日以降」の表示は、2026-10 の実画面では出なかった（期間の頭に
    データが無くても、グラフが登録日から始まるだけ）。そこで書き出しの中身から読む。
    日別のファイルは名前で探さない。実画面では「平均読み込み時間のチャート.csv」
    という、中身と合わない名前で書き出された。**見出しの1列目が「日付」のもの**を使う。
    """
    for p in sorted(out.glob("*.csv")):
        with io.open(p, encoding="utf-8-sig") as f:
            rows = list(csv.reader(f))
        if not rows or rows[0][:1] not in (["日付"], ["Date"]):
            continue
        days = [r[0] for r in rows[1:] if r and re.fullmatch(r"\d{4}-\d{2}-\d{2}", r[0])]
        if days:
            return min(days)
    return ""


def same_period(text: str, start: date, end: date) -> bool:
    want = f"{start:%Y/%m/%d}-{end:%Y/%m/%d}"
    return text.replace(" ", "") == want


def unpack(zpath: Path, out: Path) -> list[str]:
    """書き出しの zip を展開する。中身の CSV の名前を返す。"""
    names = []
    with zipfile.ZipFile(zpath) as z:
        for n in z.namelist():
            if n.endswith("/"):
                continue
            target = out / Path(n).name           # フォルダ構造は持ち込まない
            target.write_bytes(z.read(n))
            names.append(target.name)
    return names


# ---------------------------------------------------------------- 本体
def export_one(resource: str, start: date, end: date, base: Path, *, profile: Path,
               timeout: float, use_api: bool, do_discover: bool) -> dict:
    out = base / safe_name(resource)
    out.mkdir(parents=True, exist_ok=True)
    rec = {"resource": resource, "start": start.isoformat(), "end": end.isoformat(),
           "collected_at": datetime.now().isoformat(timespec="seconds"),
           "method": "", "files": [], "data_since": "", "api_status": None, "note": ""}

    # 手で書き出した zip が置いてあれば、それを使う（失敗したときの予備の続き）
    placed = sorted(out.glob("*.zip"))
    if placed and not do_discover:
        rec.update(method="manual", files=unpack(placed[-1], out), source=placed[-1].name)
        check_period(rec, out, start, end)
        return rec

    if use_api and not do_discover:
        token = api_token()
        if token:
            status, _ = api_query(token, resource, start, end, ["query"], row_limit=1)
            rec["api_status"] = status
            if status == 200:
                rec.update(method="api", files=api_export(token, resource, start, end, out))
                return rec
        else:
            rec["api_status"] = "no-credentials"

    got = browser_export(resource, start, end, out, profile, timeout, do_discover)
    if "discover" in got:
        rec.update(method="discover", files=[Path(got["discover"]).name, "_discover.png"])
        return rec
    zpath = out / got["zip"]
    rec.update(method="browser", files=unpack(zpath, out), source=got["zip"],
               data_since=got["data_since"], url=got["url"])
    check_period(rec, out, start, end)
    return rec


def check_period(rec: dict, out: Path, start: date, end: date) -> None:
    """書き出しの期間を記録し、指定と違えば止める。"""
    got = period_in_files(out)
    rec["period_in_file"] = got
    if got and not same_period(got, start, end):
        raise RuntimeError(f"書き出しの期間が指定と違います（書き出し {got}／指定 {start}〜{end}）。"
                           "画面の期間を確かめてください")
    first = first_day_in_files(out)
    rec["first_day_in_file"] = first
    if not rec.get("data_since") and first and first > start.isoformat():
        # 期間の頭にデータが無い。登録日より前は集計されないため、正常のことが多い
        rec["data_since"] = first
        rec["note"] = (f"{start} から、{first} の前日まではデータがありません。"
                       "プロパティを登録した日より前は集計されないため、正常のことが多い")


def main(argv=None) -> int:
    ap =argparse.ArgumentParser(description="Search Console の SNS プロパティの検索データを書き出す")
    ap.add_argument("--resource", action="append", default=[],
                    help="画面のURLの resource_id そのまま。複数並べてよい")
    ap.add_argument("--start", help="YYYY-MM-DD")
    ap.add_argument("--end", help="YYYY-MM-DD")
    ap.add_argument("--out", help="保存先フォルダ。プロパティごとにサブフォルダを作る")
    ap.add_argument("--profile", default=".sc_profile",
                    help="サインイン状態を保存するフォルダ。Git に入れない")
    ap.add_argument("--login-plain", action="store_true",
                    help="自動操作なしのブラウザを開き、Google アカウントでサインインしてもらう")
    ap.add_argument("--login-timeout", type=float, default=900.0)
    ap.add_argument("--timeout", type=float, default=60.0, help="画面の読み込みと書き出しを待つ上限（秒）")
    ap.add_argument("--no-api", action="store_true", help="API を試さず、ブラウザで取る")
    ap.add_argument("--discover", action="store_true",
                    help="書き出さずに、画面のボタンと文言を _discover.json に書き出す")
    a = ap.parse_args(argv)

    profile = Path(a.profile)
    if a.login_plain:
        return login_plain(profile, a.login_timeout)
    if not (a.resource and a.start and a.end and a.out):
        ap.error("--resource・--start・--end・--out が必要です")
    start, end = parse_day(a.start), parse_day(a.end)
    if start > end:
        ap.error("--start が --end より後になっています")
    base = Path(a.out)

    records, failed = [], []
    for rid in a.resource:
        try:
            rec = export_one(rid, start, end, base, profile=profile, timeout=a.timeout,
                             use_api=not a.no_api, do_discover=a.discover)
            records.append(rec)
            print(f"取得しました（{rec['method']}）: {rid}")
            for f in rec["files"]:
                print(f"    {f}")
            if rec.get("data_since"):
                print(f"    集計開始日: {rec['data_since']}（それより前にデータが無いのは正常）")
        except Exception as e:  # 1つ失敗しても残りは取る
            failed.append(rid)
            print(f"\n取得できませんでした: {rid}\n  理由: {e}\n")
            print(manual_steps(rid, start, end, base / safe_name(rid)))
            print()

    if records:
        base.mkdir(parents=True, exist_ok=True)
        path = base / "manifest.json"
        old = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {"runs": []}
        old["runs"].extend(records)
        path.write_text(json.dumps(old, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        print(f"\n記録: {path}")
    if failed:
        print(f"取得できなかったプロパティ: {len(failed)} 件。上の手順で手で書き出してください。")
        print("レポートでは、その欄を「取得できず」として飛ばして進めます。")
        return 2
    return 0


if __name__ == "__main__":
    sys.stdout.reconfigure(encoding="utf-8")
    raise SystemExit(main())
