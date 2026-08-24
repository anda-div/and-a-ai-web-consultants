import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class PrioritizeTest(unittest.TestCase):
    def test_priority_and_ids(self):
        data = {"findings": [
            {"finding_id": "F-1", "title": "大", "evidence": 5, "impact": 5, "confidence": 5, "effort": 1, "risk": 1, "urgency": 5},
            {"finding_id": "F-2", "title": "小", "evidence": 1, "impact": 1, "confidence": 1, "effort": 5, "risk": 5, "urgency": 1},
        ]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "findings.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            out = tmp_path / "out"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "prioritize_findings.py"), "--input", str(source), "--out", str(out)], check=True)
            result = json.loads((out / "prioritized_issues.json").read_text(encoding="utf-8-sig"))
            self.assertEqual(result["issues"][0]["title"], "大")
            self.assertEqual(result["issues"][0]["issue_id"], "I-001")


if __name__ == "__main__":
    unittest.main()
