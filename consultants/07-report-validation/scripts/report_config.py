# -*- coding: utf-8 -*-
"""Config ローダー（汎用）

クライアント固有の値は一切持たない。プロジェクト直下の `_config/` にある
JSON 群を読み、レポート生成スクリプトから使いやすい形で返すだけの部品。

将来この部品は公開リポジトリ（JOB 07）へ移す。
そのため、ここにクライアント名・URL・数値を書いてはいけない。

使い方:
    from report_config import load
    cfg = load()
    cfg.ga4_xlsx("ad_lp")        -> 入力Excelの絶対パス
    cfg.color("navy")            -> RGBColor
    cfg.report("ad_lp")          -> reports.json の該当レポート定義
"""
from __future__ import annotations

import json
import os
import re


class Config:
    def __init__(self, root: str):
        self.root = root
        self.dir = os.path.join(root, "_config")
        self.client = self._load("client.json")
        self.analytics = self._load("analytics.json")
        self.reports_def = self._load("reports.json")
        self.branding = self._load("branding.json")
        self.sources = self._load("data_sources.json")

    # ------------------------------------------------------------ 基本
    def _load(self, name: str) -> dict:
        path = os.path.join(self.dir, name)
        if not os.path.exists(path):
            raise FileNotFoundError(
                f"Config が見つかりません: {path}\n"
                f"_config/ にクライアント固有の設定を置いてください。")
        with open(path, encoding="utf-8") as f:
            return json.load(f)

    def path(self, *parts: str) -> str:
        """プロジェクト直下からの相対パスを絶対パスにする"""
        return os.path.join(self.root, *[p.replace("/", os.sep) for p in parts])

    # ------------------------------------------------------------ 入力
    def ga4_xlsx(self, report_key: str) -> str:
        ga4 = self.sources["ga4"]
        return self.path(ga4["dir"], ga4["files"][report_key])

    def search_console_xlsx(self, period_key: str) -> str:
        sc = self.sources["search_console"]
        name = (sc["file_pattern"]
                .replace("{site_key}", self.reports_def["site_key"])
                .replace("{period}", period_key))
        return self.path(sc["dir"], name)

    # ------------------------------------------------------------ 体裁
    def template(self) -> str:
        return self.path(self.branding["template"]["path"])

    def slide_size_cm(self):
        s = self.branding["slide_size_cm"]
        return s["width"], s["height"]

    def color(self, key: str):
        from pptx.dml.color import RGBColor
        return RGBColor.from_string(self.branding["colors"][key])

    def colors(self) -> dict:
        return {k: self.color(k) for k in self.branding["colors"]}

    # ------------------------------------------------------------ 出力
    def output(self, report_key: str, period_key: str, version: int) -> str:
        r = self.report(report_key)
        name = (self.reports_def["naming"]
                .replace("{report_name}", r["name"])
                .replace("{site_key}", self.reports_def["site_key"])
                .replace("{period}", period_key)
                .replace("{version}", str(version)))
        return self.path(self.reports_def["output_dir"], name)

    # ------------------------------------------------------------ 定義
    def report(self, key: str) -> dict:
        for r in self.reports_def["reports"]:
            if r["key"] == key:
                return r
        raise KeyError(f"reports.json に '{key}' がありません")

    def ga4_property(self, key: str) -> dict:
        for p in self.analytics["ga4_properties"]:
            if p["key"] == key:
                return p
        raise KeyError(f"analytics.json に GA4プロパティ '{key}' がありません")

    def form_pages(self) -> dict:
        return {k: v for k, v in self.analytics["form_pages"].items()
                if not k.startswith("_")}

    def author_line(self) -> str:
        """表紙の『◯◯ 御中 ／ 制作：◯◯』"""
        return (f"{self.client['end_client']['name']} 御中"
                f"　／　制作：{self.client['report_author_label']}")

    # ------------------------------------------------------------ 遷移元の分類
    def referrer_bucket(self, src) -> str:
        """参照元URLを表示用の区分名に寄せる。ルールは analytics.json 側で定義する。"""
        rules = self.analytics["referrer_buckets"]
        if src is None:
            return rules["null_label"]
        s = str(src)
        head = s.split("?")[0]
        for rule in rules["rules"]:
            if "contains" in rule and rule["contains"] in s:
                return rule["label"]
            if "regex" in rule and re.match(rule["regex"], head):
                return rule["label"]
        return rules["default_label"]


def find_root(start: str | None = None) -> str:
    """`_config/` を持つ最も近い親ディレクトリをプロジェクト直下とみなす"""
    cur = os.path.abspath(start or os.path.dirname(__file__))
    while True:
        if os.path.isdir(os.path.join(cur, "_config")):
            return cur
        parent = os.path.dirname(cur)
        if parent == cur:
            raise FileNotFoundError(
                "_config/ が見つかりません。プロジェクト直下に配置してください。")
        cur = parent


def load(start: str | None = None) -> Config:
    return Config(find_root(start))


if __name__ == "__main__":
    import sys
    sys.stdout.reconfigure(encoding="utf-8")
    c = load()
    print("プロジェクト直下 :", c.root)
    print("クライアント     :", c.client["client"]["name"])
    print("エンドクライアント:", c.client["end_client"]["name"])
    print("テンプレート     :", c.template())
    print("用紙サイズ(cm)   :", c.slide_size_cm())
    print("配色             :", list(c.branding["colors"]))
    print("GA4(広告LP)      :", c.ga4_xlsx("ad_lp"))
    print("GA4(サイト)      :", c.ga4_xlsx("site"))
    print("フォームページ   :", len(c.form_pages()), "件")
    print("表紙の制作者行   :", c.author_line())
