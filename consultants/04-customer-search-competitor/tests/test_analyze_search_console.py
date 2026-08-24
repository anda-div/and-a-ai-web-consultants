import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class SearchConsoleTest(unittest.TestCase):
    def test_japanese_headers_and_findings(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "search.csv"
            with source.open("w", encoding="utf-8-sig", newline="") as handle:
                writer = csv.writer(handle)
                writer.writerow(["クエリ", "ページ", "クリック数", "表示回数", "CTR", "掲載順位"])
                writer.writerow(["サービス 比較", "/compare", 2, 500, "0.4%", 8.1])
            out = tmp_path / "out"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "analyze_search_console.py"), "--input", str(source), "--out", str(out)], check=True)
            payload = json.loads((out / "findings.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(len(payload["findings"]), 1)
            self.assertEqual(payload["findings"][0]["job"], "04")


if __name__ == "__main__":
    unittest.main()
