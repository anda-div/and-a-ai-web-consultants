import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]


class BuildActionsTest(unittest.TestCase):
    def test_traceability(self):
        data = {"issues": [{"issue_id": "I-009", "title": "課題", "source_finding_ids": ["F-001"], "selected": True}]}
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp)
            source = tmp_path / "issues.json"
            source.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
            out = tmp_path / "out"
            subprocess.run([sys.executable, str(ROOT / "scripts" / "build_action_specs.py"), "--issues", str(source), "--out", str(out)], check=True)
            result = json.loads((out / "actions.json").read_text(encoding="utf-8-sig"))["actions"][0]
            self.assertEqual(result["issue_id"], "I-009")
            self.assertEqual(result["source_finding_ids"], ["F-001"])
            self.assertEqual(result["action_id"], "A-001")


if __name__ == "__main__":
    unittest.main()
