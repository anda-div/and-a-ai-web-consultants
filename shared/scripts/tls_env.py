# -*- coding: utf-8 -*-
"""セキュリティソフトがHTTPSを検査しているPCでも、APIに繋がるようにする

背景・切り分け・案件での扱いは shared/TLS_INSPECTION.md に書いてある。
ここは要点だけ。

Norton・ESET・Kaspersky などは、通信の中身を調べるためにHTTPSを一度復号し、
自分が発行した証明書に差し替えてから渡す。ブラウザはそのソフトのルート証明書を
信頼するよう自動設定されるので、人が見る画面では何も起きない。

Python は自前の検証（OpenSSL）を使うため、次のどちらかで止まる。

  ・そのルート証明書を知らない     → unable to get local issuer certificate
  ・知っていても規格違反として弾く → Basic Constraints of CA cert not marked critical

後者は Python 3.13 以降で既定が厳しくなったために起きる。**証明書を束に足しても
直らない。** 判断する主体を Windows に移す（truststore）。検証はやめない。

GA4 Data API は gRPC も使う。gRPC は Windows の判断を借りられないので、
そちらには証明書の束を渡す。

使い方

    import tls_env
    tls_env.enable()      # 検査されていないPCでは、何もしないで返る

    python tls_env.py     # 単体で実行すると切り分けを表示する
"""
from __future__ import annotations

import io
import os
import subprocess
import sys

# 通信を検査するソフトが差し込むルート証明書の見分け方（表示と判定に使う）
INTERCEPTORS = ("Norton", "Symantec Web", "NortonLifeLock", "ESET", "Kaspersky",
                "Avast", "AVG", "Bitdefender", "Sophos", "McAfee", "Trend Micro",
                "F-Secure", "Fortinet", "Zscaler", "Netskope", "Blue Coat",
                "Dr.Web", "Comodo Internet Security", "BullGuard")

# 繋がるべき相手。案件で増えたらここに足す。
DEFAULT_HOSTS = ("oauth2.googleapis.com",
                 "analyticsdata.googleapis.com",
                 "analyticsadmin.googleapis.com",
                 "cloudresourcemanager.googleapis.com")

_done = False


def bundle_path() -> str:
    """証明書の束の置き場所。

    中身は「このPCが信頼している証明書」なので、PCに紐づく場所へ置く。
    案件フォルダへ置くと、クラウド同期で別のPCへ渡ったときに意味を失う。
    """
    p = os.environ.get("CA_BUNDLE_FILE")
    if p:
        return p
    return os.path.join(os.path.expanduser("~"), ".and-a", "ca_bundle.pem")


def windows_roots() -> list[tuple[str, str]]:
    """Windows が信頼しているルート証明書を (名前, base64) で取り出す。"""
    if os.name != "nt":
        return []
    ps = (
        "$o=@(); "
        "foreach($s in 'Cert:\\LocalMachine\\Root','Cert:\\CurrentUser\\Root'){ "
        "foreach($c in (Get-ChildItem $s -ErrorAction SilentlyContinue)){ "
        "$o += ($c.Subject + '|||' + [Convert]::ToBase64String($c.RawData)) } } "
        "$o -join \"`n\""
    )
    try:
        r = subprocess.run(["powershell", "-NoProfile", "-Command", ps],
                           capture_output=True, text=True, timeout=120)
    except Exception:
        return []
    out, seen = [], set()
    for line in r.stdout.splitlines():
        if "|||" not in line:
            continue
        subject, b64 = line.split("|||", 1)
        b64 = b64.strip()
        if b64 and b64 not in seen:
            seen.add(b64)
            out.append((subject.strip(), b64))
    return out


def build_bundle(dest: str | None = None) -> tuple[str, list[str]]:
    """certifi の一覧に、このPCが信頼するルート証明書を足した束を作る。

    戻り値は (束のパス, 検査ソフトとして見つかった証明書の名前)。
    """
    import certifi

    dest = dest or bundle_path()
    with io.open(certifi.where(), encoding="utf-8") as f:
        base = f.read()

    added, found = [], []
    for subject, b64 in windows_roots():
        body = "\n".join(b64[i:i + 64] for i in range(0, len(b64), 64))
        if body in base:          # certifi に既にあるものは足さない
            continue
        added.append(f"# {subject}\n-----BEGIN CERTIFICATE-----\n"
                     f"{body}\n-----END CERTIFICATE-----\n")
        if any(k.lower() in subject.lower() for k in INTERCEPTORS):
            found.append(subject)

    os.makedirs(os.path.dirname(os.path.abspath(dest)), exist_ok=True)
    with io.open(dest, "w", encoding="utf-8") as f:
        f.write(base)
        if not base.endswith("\n"):
            f.write("\n")
        f.write("\n# ---- このPCが信頼しているルート証明書 ----\n")
        f.write("".join(added))
    return dest, found


def enable(verbose: bool = False) -> None:
    """証明書の扱いを、このPCの事情に合わせる。2度呼んでも害はない。"""
    global _done
    if _done:
        return
    _done = True

    # 1) OpenSSL の判断を Windows の判断に置き換える（requests・OAuth が通る）
    try:
        import truststore
        truststore.inject_into_ssl()
        if verbose:
            print("  証明書の検証を Windows に任せました（truststore）")
    except ImportError:
        if verbose:
            print("  truststore が未導入です → pip install truststore")

    # 2) gRPC には証明書の束を渡す（GA4 のデータ取得が通る）
    if not os.environ.get("GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"):
        p = bundle_path()
        if not os.path.exists(p):
            try:
                p, _ = build_bundle(p)
            except Exception:
                return
        os.environ["GRPC_DEFAULT_SSL_ROOTS_FILE_PATH"] = p
        if verbose:
            print(f"  gRPC に渡す証明書の束: {p}")


# ---------------------------------------------------------------- 切り分け
def issuer_of(host: str) -> str:
    """検証せずに証明書を取り、発行者を返す。間に何が入っているかが分かる。"""
    import socket
    import ssl
    import tempfile
    try:
        ctx = ssl._create_unverified_context()
        with socket.create_connection((host, 443), timeout=10) as s:
            with ctx.wrap_socket(s, server_hostname=host) as ss:
                pem = ssl.DER_cert_to_PEM_cert(ss.getpeercert(binary_form=True))
        with tempfile.NamedTemporaryFile("w", suffix=".pem", delete=False) as f:
            f.write(pem)
            path = f.name
        info = ssl._ssl._test_decode_cert(path)
        os.unlink(path)
        d = dict(x[0] for x in info["issuer"])
        return d.get("organizationName") or d.get("commonName") or "不明"
    except Exception:
        return "取得できません"


def diagnose(hosts=DEFAULT_HOSTS) -> int:
    sys.stdout.reconfigure(encoding="utf-8")
    import requests

    def reach() -> int:
        ng = 0
        for h in hosts:
            try:
                requests.get(f"https://{h}/", timeout=15)
                print(f"    OK  {h}")
            except Exception as e:
                ng += 1
                print(f"    NG  {h}  {str(e)[:60]}")
        return ng

    print("■ 証明書を発行しているのは誰か")
    who = issuer_of(hosts[1] if len(hosts) > 1 else hosts[0])
    print(f"    {hosts[1] if len(hosts) > 1 else hosts[0]}  →  {who}")
    if any(k.lower() in who.lower() for k in INTERCEPTORS):
        print("    通信が検査されています。この対処が要ります。")
    else:
        print("    検査は行われていません。繋がらないなら別の原因です")
        print("    （社内プロキシ・ファイアウォール・DNS）。")
    print()

    print("■ 対処なしで繋がるか")
    if reach() == 0:
        print()
        print("対処は要りません。")
        return 0
    print()

    print("■ 対処を入れて、もう一度")
    enable(verbose=True)
    print()
    if reach():
        print()
        print("まだ繋がりません。社内プロキシなど、別の原因が考えられます。")
        return 1
    print()
    print("繋がりました。呼び出し側は起動時に tls_env.enable() を呼んでください。")
    print("gcloud には shared/scripts/gcloud.cmd を使ってください。")
    return 0


if __name__ == "__main__":
    raise SystemExit(diagnose())
