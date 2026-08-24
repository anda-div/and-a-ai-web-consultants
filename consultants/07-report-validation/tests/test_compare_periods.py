import csv
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class ComparePeriodsTest(unittest.TestCase):
    def test_changes(self):
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            before = tmp_path / "before.csv"
            after = tmp_path / "after.csv"
            for path, value in ((before, 10), (after, 12)):
                with path.open("w", encoding="utf-8", newline="") as handle:
                    writer = csv.writer(handle)
                    writer.writerow(["metric", "value"])
                    writer.writerow(["sessions", value])
            report = tmp_path / "effect.md"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "compare_periods.py"), "--before", str(before), "--after", str(after), "--out", str(report)], check=True)
            data = json.loads(report.with_suffix(".json").read_text(encoding="utf-8-sig"))
            self.assertEqual(data["comparisons"][0]["absolute_change"], 2)
            self.assertAlmostEqual(data["comparisons"][0]["change_rate_percent"], 20)


if __name__ == "__main__":
    unittest.main()
