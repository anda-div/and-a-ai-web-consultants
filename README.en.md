[日本語](README.md) | **English**

# Seven AI Web Consultants

![Seven AI web consultants](assets/team.png)

A toolkit for doing real web-analytics work with a CLI coding agent, split into
seven specialist jobs.

Works with both Codex and Claude Code. You do not need all seven. Pick one job,
or two or three — each runs on its own.

> **A note on language.** This page is the English entry point. The working
> documents — runbooks, field notes, per-job instructions — are written in
> Japanese, because that is the language we work in every day. They are linked
> from here and are readable through translation. We keep this page short and
> stable on purpose, so it does not fall behind the Japanese source.

## The seven jobs

| Job | Role | Main input | Main output |
|---|---|---|---|
| 01 | [Measurement audit](consultants/01-measurement-audit/) | GA4 configuration, raw data, existing reports | Audit findings, figure reconciliation |
| 02 | [GA4 analysis](consultants/02-ga4-analysis/) | GA4 exports | KPIs, change points, segment analysis |
| 03 | [Behaviour & heatmaps](consultants/03-behavior-heatmap/) | Clarity images, page captures | Findings on paths, attention, drop-off |
| 04 | [Customers, search & competitors](consultants/04-customer-search-competitor/) | Search Console, competitor URLs, customer data | Search intent, competitive comparison, customer hypotheses |
| 05 | [Issue diagnosis & prioritisation](consultants/05-issue-prioritization/) | Findings from jobs 01–04 | Issue ledger, priority, order of work |
| 06 | [UX/UI design](consultants/06-ux-ui-design/) | Priority issues, evidence, constraints | Improvement proposals, wireframe specs |
| 07 | [Reporting & validation](consultants/07-report-validation/) | Everything above, PPTX templates | Generated PPTX, QA, before/after validation |

## Getting started

```bash
git clone https://github.com/anda-div/and-a-ai-web-consultants.git
cd and-a-ai-web-consultants
```

1. Read the `README.md` of the job you want to use.
2. Put real client data in `input/`. It is git-ignored.
3. Start Codex or Claude Code at the repository root.
4. Ask for what you want, e.g. *"Use job 02 to analyse the GA4 data in input."*
5. Deliverables go to `output/`.

Codex reads `AGENTS.md` at the root; Claude Code reads `CLAUDE.md`. Both then
follow the instructions for the job you chose.

Used as a full set, the standard flow is:

```text
Measurement audit → GA4 analysis ─┐
Behaviour analysis ───────────────┼→ Issue diagnosis → UX/UI design → Reporting
Customers / search / competitors ─┘
```

## What is actually in here

This is not a wrapper around an API. Most of the value is in **notes from things
that went wrong on real client work**, written down so the next person does not
lose the same day we did.

A few examples, all of which apply outside Japan too:

- **Microsoft Clarity heatmaps drift.** Clarity paints heat over a stored
  screenshot, so the colours do not land on the buttons they belong to. The
  official FAQ says you cannot re-capture that screenshot. We drive the page
  ourselves instead and stitch the tiles, which removes the drift entirely.
  We also document the failures we hit doing it — capturing the wrong element,
  pages that do not scroll, and a date range that silently meant "the last 30
  days" rather than the month we asked for.
  → [Field notes (English summary)](docs/en/CLARITY_HEATMAP_NOTES.md)

- **TLS-inspecting security software breaks Python and gcloud, but not the
  browser.** Python 3.13 turned on strict X.509 checking, and many corporate
  root certificates violate RFC 5280. Adding the certificate to the bundle does
  *not* fix it. → [shared/TLS_INSPECTION.md](shared/TLS_INSPECTION.md) (Japanese)

- **Moving a report off Google Apps Script onto direct API calls.** Totals can
  match while individual cells differ — rounding, ordering, and business rules
  hide inside the old script. The runbook makes you compare every cell before
  switching, and tells you when a remaining difference means the *old* side was
  wrong. → [shared/PORTING_RUNBOOK.md](shared/PORTING_RUNBOOK.md) (Japanese)

## Calling APIs directly from your machine

If Python and `gcloud` fail with certificate errors while the browser works
fine, security software is inspecting HTTPS on that machine. Check once before
you start:

```bash
python shared/scripts/tls_env.py
```

For GA4, note that `gcloud`'s built-in client ID no longer gets
`analytics.readonly` — **you need your own OAuth client**. Search Console has an
official API and works through the same authentication with one extra scope.

Shared components: `shared/scripts/ga4_client.py` (authentication, retries,
JavaScript-compatible rounding, xlsx output) and `shared/scripts/compare_xlsx.py`
(cell-by-cell comparison). **Which sheets to build is client-specific**, so that
part stays in each client's own repository — never here.

## Data and confidentiality

- Never commit real client data, names, URLs, IDs, or credentials.
- `input/`, `output/`, `project_config.json` and credential files are git-ignored.
- Public samples use fictional companies, sites, and figures only.
- AI output should carry its evidence, its measurement conditions, and what has
  not been verified — not a bare assertion.

## Supported CLI agents

- **Codex** — uses `AGENTS.md`. See [Custom instructions with AGENTS.md](https://learn.chatgpt.com/docs/agent-configuration/agents-md).
- **Claude Code** — uses `CLAUDE.md`. See [Manage Claude's memory](https://docs.anthropic.com/en/docs/claude-code/memory).

Subscriptions and usage fees for the agents themselves are not included here.

## Licence

Code and documents are published under the MIT Licence. Third-party trademarks,
services, and APIs remain subject to their own terms.

## Who makes this

Built and maintained by **and,a Inc.** (Tokyo, Japan), from work we do for real
clients every month. If the free files are not enough to apply this to a live
account, we also do the hands-on work: setup, additional measurement, analysis
design, report generation, and quality checking.

- Company: https://www.and-aaa.com/

## Disclaimer

This toolkit does not guarantee analysis results, revenue improvement, or
measurement completeness. GA4, Google Search Console, Microsoft Clarity, and
Google Apps Script change their specifications; procedures and code may stop
working. Test before you rely on anything, and take responsibility for your own
publishing and measurement changes.
