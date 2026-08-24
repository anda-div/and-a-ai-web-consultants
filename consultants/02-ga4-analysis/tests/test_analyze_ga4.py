from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path
import unittest


SCRIPT = Path(__file__).parents[1] / "scripts" / "analyze_ga4.py"
SPEC = spec_from_file_location("analyze_ga4", SCRIPT)
MODULE = module_from_spec(SPEC)
SPEC.loader.exec_module(MODULE)


class AnalyzeGa4Test(unittest.TestCase):
    def test_pct_change(self):
        self.assertEqual(MODULE.pct_change(120, 100), 20)
        self.assertIsNone(MODULE.pct_change(10, 0))

    def test_analysis(self):
        rows = [
            {"period": "current", "channel": "Organic", "sessions": "120"},
            {"period": "previous", "channel": "Organic", "sessions": "100"},
        ]
        config = {"analysis": {"metric_columns": ["sessions"], "dimension_columns": ["channel"]}}
        result = MODULE.analyze(rows, config)
        self.assertEqual(result["totals"]["sessions"]["absolute_change"], 20)


if __name__ == "__main__":
    unittest.main()
