"""Stdlib-only tests. Run: python3 -m unittest scripts.test_teacher_skill -v"""

import json
import subprocess
import sys
import unittest
from pathlib import Path

SCRIPT = Path(__file__).parent / "teacher_skill.py"


def run(payload: dict) -> subprocess.CompletedProcess:
    return subprocess.run(
        [sys.executable, str(SCRIPT)],
        input=json.dumps(payload),
        capture_output=True,
        text=True,
    )


class TeacherSkillTests(unittest.TestCase):
    def test_linear_step_explain_to_demonstrate(self):
        result = run(
            {"current_node": "explain", "data": {}, "retry_count": 0, "max_retries": 2}
        )
        self.assertEqual(json.loads(result.stdout)["next_node"], "demonstrate")

    def test_check_not_understood_loops_and_increments_retry(self):
        result = run(
            {
                "current_node": "check",
                "data": {"understood": False},
                "retry_count": 0,
                "max_retries": 2,
            }
        )
        out = json.loads(result.stdout)
        self.assertEqual(out["next_node"], "explain")
        self.assertEqual(out["retry_count"], 1)
        self.assertFalse(out["done"])

    def test_check_retries_exhausted_ends(self):
        result = run(
            {
                "current_node": "check",
                "data": {"understood": False},
                "retry_count": 2,
                "max_retries": 2,
            }
        )
        out = json.loads(result.stdout)
        self.assertEqual(out["next_node"], "end")
        self.assertTrue(out["done"])
        self.assertGreaterEqual(
            out["retry_count"], out["max_retries"]
        )  # exhausted, not success

    def test_check_understood_ends_below_max(self):
        result = run(
            {
                "current_node": "check",
                "data": {"understood": True},
                "retry_count": 1,
                "max_retries": 2,
            }
        )
        out = json.loads(result.stdout)
        self.assertEqual(out["next_node"], "end")
        self.assertLess(
            out["retry_count"], out["max_retries"]
        )  # success, not exhausted

    def test_malformed_json_fails_cleanly(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)],
            input="not json",
            capture_output=True,
            text=True,
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error", json.loads(proc.stderr))

    def test_missing_required_key_fails_cleanly(self):
        proc = subprocess.run(
            [sys.executable, str(SCRIPT)], input="{}", capture_output=True, text=True
        )
        self.assertEqual(proc.returncode, 1)
        self.assertIn("error", json.loads(proc.stderr))


if __name__ == "__main__":
    unittest.main()
