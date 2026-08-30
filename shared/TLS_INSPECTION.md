# セキュリティソフトがHTTPSを検査しているPCで、APIに繋がらないとき

GA4やSearch ConsoleのAPIを**そのPCから直接**呼ぶようになると、ブラウザでは何も
起きないのに、Pythonとgcloudだけが証明書エラーで止まることがある。

原因はほぼ一つで、セキュリティソフトによるHTTPS検査である。GASをブラウザの中で
動かしていた頃は無縁だった問題なので、ローカル取得へ切り替える案件では
**最初に確認する項目**として扱う。

---

## 1. 何が起きているか

Norton・ESET・Kaspersky などのセキュリティソフトは、通信の中身を調べるために
HTTPSを一度復号し、**自分が発行した証明書に差し替えてから**アプリへ渡す。

```
本来   あなたのPC ────────── Google
実際   あなたのPC ── ソフト ── Google
                    ここで証明書が差し替わる
```

インストール時に、そのソフトのルート証明書がWindowsの証明書ストアへ入る。
ブラウザはWindowsの判断を借りるので、利用者から見て何も起きない。

Pythonとgcloudは**自前の検証（OpenSSL）**を使う。だから止まる。

## 2. 症状は2種類ある。混同すると直らない

| エラー文 | 意味 | 直し方 |
| --- | --- | --- |
| `unable to get local issuer certificate` | そのルート証明書を知らない | 証明書の束に足す |
| `Basic Constraints of CA cert not marked critical` | 知っているが、規格違反として弾いた | **足しても直らない**（後述） |

後者は Python 3.13 以降で既定が厳しくなったために起きる（`ssl.create_default_context()`
が `VERIFY_X509_STRICT` を既定で立てるようになった）。セキュリティソフトが
その場で生成するルート証明書は、RFC 5280 が CA 証明書に求める
「basicConstraints を critical にする」を満たしていないことが多い。

**証明書を束に足すと、エラー文が前者から後者へ変わるだけで、繋がらない。**
ここで「足したのに直らない」と迷いやすいので、エラー文を必ず読み分ける。

なお gcloud は自前の Python を同梱しており、そちらも新しいバージョンでは
同じ挙動になる。「gcloud だけ別の対処」が要る理由がここにある。

## 3. 切り分け

`shared/scripts/tls_env.py` を単体で実行すると、次を順に出す。

```
python shared/scripts/tls_env.py
```

1. 証明書を発行しているのは誰か（＝間に何が入っているか）
2. 対処なしで繋がるか
3. 対処を入れると繋がるか

発行者に `Norton` `ESET` `Kaspersky` などソフトの名前が出れば、この文書の話である。
`Google Trust Services` などが出るなら検査されていないので、別の原因（社内プロキシ、
ファイアウォール、DNS）を疑う。

手で確かめるなら次でよい。

```python
import socket, ssl
ctx = ssl._create_unverified_context()          # 検証せずに証明書だけ見る
with socket.create_connection(("analyticsdata.googleapis.com", 443)) as s:
    with ctx.wrap_socket(s, server_hostname="analyticsdata.googleapis.com") as ss:
        print(ss.getpeercert()["issuer"])
```

## 4. 対処

**セキュリティソフトの設定は変えない。** 検査を切る／除外リストに入れる方法も
あるが、客先のPCで保護設定に手を入れる判断はこちらが負うべきではない。
情報システム部門の許可が要る会社も多い。

代わりに、**判断する主体を OpenSSL から Windows へ移す**。ブラウザと同じ
判断になるだけで、検証をやめるわけではない。

| 通信の経路 | 使われる場面 | 対処 |
| --- | --- | --- |
| requests / urllib3（OpenSSL） | OAuth、REST API | `truststore` でWindowsの検証に委ねる |
| gRPC（BoringSSL） | GA4 Data API 本体 | certifi ＋ そのPCが信頼するルート証明書の束を渡す |
| gcloud（同梱Python） | 認証の初期設定 | 起動時に上記を効かせるラッパー経由で呼ぶ |

gRPC だけ別扱いなのは、BoringSSL が Windows の証明書ストアを見ないため。
ただし BoringSSL は 2. の規格チェックをしないので、束を渡すだけで通る。

### 導入

```
pip install truststore
```

Python 側は、入口で1行呼ぶだけでよい。検査されていないPCでは何もしない。

```python
import tls_env
tls_env.enable()
```

gcloud は `shared/scripts/gcloud.cmd` を経由して呼ぶ。素の gcloud は使わない。

認証の初期設定は、長いURLを手で打たずに済むよう1コマンドにまとめてある。

```
shared\scripts\adc_login.cmd <プロジェクトID>
```

ラッパーがしていることは3つだけで、gcloud本体にもセキュリティソフトにも
手を加えない。

- `CLOUDSDK_PYTHON` … 同梱Pythonではなく、`truststore` を入れたPythonを使う
- `CLOUDSDK_PYTHON_SITEPACKAGES=1` … site-packages を読ませる（既定では読まない）
- `PYTHONPATH` … 起動時に自動で読まれる `sitecustomize.py` を置いた場所を足す

### 証明書の束の置き場所

既定は `~/.and-a/ca_bundle.pem`。環境変数 `CA_BUNDLE_FILE` で変えられる。

**案件フォルダの中には置かない。** 束の中身はそのPCが信頼している証明書なので、
別のPCへ同期されると意味を失う（クラウド同期しているフォルダに置くと起きる）。

## 5. 設定作業でつまずいた点

対処そのものより、ここで時間を取られた。同じ環境なら同じ順で起きる。

### 長いURLをコマンドラインに書くと壊れる

スコープ指定は `https://...analytics.readonly,https://...cloud-platform` と長い。
シェルがこれを分割し、`'loud-platform"' は認識されていません` のような
意味の分からないエラーになる。**バッチに書いて1語で呼ぶ**（`adc_login.cmd`）。
お客様に手順を渡す場合も、この形にしておく。

### `cmd /c "..."` が対話モードで起動してしまう

Git Bash から呼ぶと、MSYS が `/c` を Windows のパスへ書き換えるため、
cmd はオプションを受け取れず対話モードで立ち上がる。
`.cmd` は **`cmd /c` を挟まず直接実行する**。

### カレントフォルダのごみファイルがツール検出を壊す

Windows の `where python` は**カレントフォルダを最初に見る**。
シェルのリダイレクト事故で `python` という名前のファイルができていると、
それを Python 本体だと誤認し、gcloud が
`you must have Python installed and on your PATH` で止まる。

- 候補は使う前に「`.exe` であり、実際に起動する」ことを確かめる（`gcloud.cmd` はそうしている）
- `check_stray_files.py` はコマンド名と同じ名前のファイルも報告する（**中身があっても**）

## 6. 案件での扱い

### 見積り・スケジュール

ローカル取得へ切り替える案件では、**着手前**に切り分けを1回走らせる。
検査下だと分かっていれば30分で終わるが、知らずに認証で詰まると半日溶ける。

### お客様が自走される場合

自走設計の納品では、**お客様のPCで同じことが起きる**。マニュアルには次を書く。

- 症状（ブラウザは普通に見えるのに、取得コマンドだけ証明書エラーで止まる）
- 切り分けの1コマンドと、その読み方
- 対処（`pip install truststore` と、gcloudはラッパー経由）
- **セキュリティソフトの設定は変えなくてよい**こと

最後の一文が要る。情報システム部門に掛け合う話だと受け取られると、
そこで導入が止まる。

### 提案時に触れておく

GASからローカル取得へ移す利点を説明する際、この一点は実費として先に言う。
「ブラウザの中で動いていたものを、PCの中へ持ってくる」以上、PCの事情を
受けるようになるのは避けられない。後から出すと不信を招く。

---

## 付録：この文書が生まれた経緯

ある案件でGA4のローカル取得を検証した際、`gcloud` と Python の両方が
`CERTIFICATE_VERIFY_FAILED` で止まった。

最初は「ルート証明書を知らないだけ」と判断し、Windowsの証明書ストアから
取り出して certifi の束に足した。**これは外れだった。** エラー文が
`unable to get local issuer certificate` から
`Basic Constraints of CA cert not marked critical` へ変わっただけで、
繋がらなかった。証明書は最初から信頼されており、規格違反で弾かれていた。

エラー文の変化を追わずに「効かなかった」で終えていれば、
セキュリティソフトを切る方向へ進んでいた。切り分けの手順を残す理由がここにある。
