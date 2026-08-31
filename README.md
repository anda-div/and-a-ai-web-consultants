# AIウェブコンサルタント7人体制

![AIウェブコンサルタント7人](assets/team.png)

ウェブ解析・改善の実務を、7つの専門JOBに分けてCLI AIと進めるための公開ツールキットです。

CodexとClaude Codeのどちらでも利用できます。7人全員を使う必要はありません。必要なJOBを1人だけ、または2〜3人だけ選んで利用できます。

## 7人のAI

| JOB | 担当 | 主な入力 | 主な出力 |
|---|---|---|---|
| 01 | [計測設計・監査](consultants/01-measurement-audit/) | GA4設定、生データ、既存レポート | 計測監査・数値突合 |
| 02 | [GA4データ解析](consultants/02-ga4-analysis/) | GA4エクスポート | KPI・変化点・セグメント分析 |
| 03 | [行動・ヒートマップ分析](consultants/03-behavior-heatmap/) | Clarity画像、ページキャプチャ | 導線・熟読・離脱の所見 |
| 04 | [顧客・検索・競合調査](consultants/04-customer-search-competitor/) | Search Console、競合URL、顧客情報 | 検索意図・競合比較・顧客仮説 |
| 05 | [課題診断・優先順位](consultants/05-issue-prioritization/) | JOB 01〜04の所見 | 課題台帳・優先順位・着手順 |
| 06 | [UX/UI改善設計](consultants/06-ux-ui-design/) | 優先課題、証拠、制約 | 改善案・ワイヤーフレーム仕様 |
| 07 | [レポート・効果検証](consultants/07-report-validation/) | 全JOBの成果物、PPTXテンプレート | PPTXレポート生成、QA、Before/After検証 |

## 最短の使い方

```bash
git clone https://github.com/anda-div/and-a-ai-web-consultants.git
cd and-a-ai-web-consultants
```

1. 利用するJOBの `README.md` を読む。
2. 実案件データは、Git管理されない `input/` に置く。
3. CodexまたはClaude Codeをリポジトリのルートで起動する。
4. 例: 「JOB 02を使い、inputのGA4データを分析してください」と依頼する。
5. 成果物は `output/` に保存する。

Codexはルートの `AGENTS.md`、Claude Codeはルートの `CLAUDE.md` を読み、選択したJOBの手順へ進みます。

## フルセットで使う場合

標準フローは次のとおりです。

```text
計測監査 → GA4解析 ─┐
行動分析 ──────────┼→ 課題診断 → UX/UI改善 → レポート・効果検証
顧客・検索・競合 ──┘
```

各JOBは独立して利用できます。前段のJOBを使わない場合は、必要な情報を利用者が直接入力してください。

## APIをPCから直接呼ぶ場合

GA4などのAPIをこのPCから直接呼ぶ構成にすると、ブラウザでは何も起きないのに
PythonとgcloudだけがTLSの証明書エラーで止まることがあります。セキュリティソフトが
HTTPSを検査しているPCで起きます。着手前に一度だけ切り分けてください。

```bash
python shared/scripts/tls_env.py
```

対処と、お客様が自走される場合の書き方は [shared/TLS_INSPECTION.md](shared/TLS_INSPECTION.md) にあります。

GA4をPCから直接取得する構成そのもの（認証・GASとの一致確認・つまずきどころ）は
[shared/GA4_LOCAL_FETCH.md](shared/GA4_LOCAL_FETCH.md) にまとめています。
`gcloud` 内蔵のクライアントIDでは `analytics.readonly` が通らなくなっているため、
**自前のOAuthクライアントIDを1つ作る必要があります**。

Search Console も**公式APIがあり、同じ認証の仕組みで自動化できます**
（スコープを1つ足すだけ）。管理画面の書き出しと1セルも違わないファイルを作るための
注意点は [shared/SEARCH_CONSOLE_LOCAL_FETCH.md](shared/SEARCH_CONSOLE_LOCAL_FETCH.md) に
あります。この2つで、月次レポートの数値データ収集は全自動になります。

## データと機密情報

- 実クライアントのデータ、名称、URL、ID、認証情報をGitへコミットしないでください。
- `input/`、`output/`、`project_config.json`、認証ファイルは `.gitignore` の対象です。
- 公開サンプルは架空の企業・サイト・数値だけを使用しています。
- AIの出力は断定せず、根拠・計測条件・未検証範囲を併記してください。

## 対応するCLI AI

- Codex: リポジトリの `AGENTS.md` を利用します。公式仕様は [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md) を参照してください。
- Claude Code: リポジトリの `CLAUDE.md` を利用します。公式仕様は [Manage Claude's memory](https://docs.anthropic.com/en/docs/claude-code/memory) を参照してください。

CLI AI本体の契約・利用料金は本リポジトリに含まれません。

## ライセンス

コードと文書はMIT Licenseで公開します。第三者の商標、各種サービス、APIの利用条件は、それぞれの権利者の条件に従ってください。

## 導入・伴走支援

無料ファイルだけでは実案件へ適用できない場合、and,a株式会社が、初期設定、計測追加、分析設計、レポート生成、品質検証まで伴走します。

- 会社サイト: https://www.and-aaa.com/
- 提供: and,a株式会社

## 免責

本ツールキットは、分析結果、売上向上、計測の完全性を保証するものではありません。GA4、Google Search Console、Microsoft Clarity、Google Apps Script等の仕様変更により、手順やコードが動作しなくなる場合があります。必ずテスト環境で確認し、公開・計測変更は利用者の責任で実施してください。
