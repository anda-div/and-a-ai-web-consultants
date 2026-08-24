#!/usr/bin/env python3
"""URL一覧をPC/SPの2サイズで全ページ撮影する。"""

from __future__ import annotations

import argparse
import asyncio
import re
from pathlib import Path
from urllib.parse import urlparse

from playwright.async_api import async_playwright


DEVICES = {"pc": (1440, 1000), "sp": (390, 844)}


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="競合URLをPC/SPで撮影します。")
    parser.add_argument("--urls", required=True, type=Path)
    parser.add_argument("--out", required=True, type=Path)
    parser.add_argument("--wait", type=int, default=1500, help="表示後の待機ミリ秒")
    return parser.parse_args()


def slug(url: str) -> str:
    parsed = urlparse(url)
    value = f"{parsed.netloc}{parsed.path}".strip("/") or "page"
    return re.sub(r"[^0-9A-Za-z._-]+", "_", value)[:100]


async def capture(urls: list[str], out: Path, wait_ms: int) -> None:
    out.mkdir(parents=True, exist_ok=True)
    async with async_playwright() as playwright:
        browser = await playwright.chromium.launch(headless=True)
        for name, (width, height) in DEVICES.items():
            context = await browser.new_context(viewport={"width": width, "height": height})
            page = await context.new_page()
            for index, url in enumerate(urls, start=1):
                try:
                    await page.goto(url, wait_until="networkidle", timeout=60000)
                    await page.wait_for_timeout(wait_ms)
                    await page.screenshot(path=out / f"{index:02d}_{slug(url)}_{name}.png", full_page=True)
                except Exception as exc:  # URL単位で継続する
                    (out / f"{index:02d}_{slug(url)}_{name}.error.txt").write_text(str(exc), encoding="utf-8")
            await context.close()
        await browser.close()


def main() -> int:
    args = parse_args()
    urls = [line.strip() for line in args.urls.read_text(encoding="utf-8-sig").splitlines() if line.strip() and not line.lstrip().startswith("#")]
    asyncio.run(capture(urls, args.out, args.wait))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
