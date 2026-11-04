"""Tests for tools/check_commits.py.

Run: python3 -I -m unittest discover -s tools/tests -v
"""
import io
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import check_commits as cc  # noqa: E402


class HeaderTests(unittest.TestCase):
    def test_valid(self):
        for h in (
            "fix(tools): stop retrying after 401",
            "docs: add roadmap",
            "feat(firmware)!: require recovery path to roll back",
            "ci(release-please): pin action",
            "chore(github/templates): add PR template",
            "revert: feat(tools): add backup",
        ):
            self.assertIsNone(cc.check_header(h), h)

    def test_invalid(self):
        cases = {
            "Prepare for public release": "not '<type>",
            "Fix(tools): capital type": "not '<type>",
            "feature: wrong type": "unknown type",
            "fix(tools):no space": "not '<type>",
            "fix(Tools): uppercase scope": "not '<type>",
            "fix(): empty scope": "not '<type>",
            "docs: ends with period.": "period",
            "docs: " + "x" * 100: "longer than",
            "": "not '<type>",
        }
        for header, expected in cases.items():
            err = cc.check_header(header)
            self.assertIsNotNone(err, header)
            self.assertIn(expected, err, header)

    def test_git_generated_messages_ignored(self):
        for h in ("Merge branch 'main' into fix/6-x", 'Revert "docs: add x"', "fixup! fix(tools): y"):
            self.assertIsNone(cc.check_header(h), h)


class MessageFileTests(unittest.TestCase):
    def test_header_skips_comments_and_blank_lines(self):
        text = "\n# Please enter the commit message\nfix(tools): parse rows\n\nbody\n"
        self.assertEqual(cc.header_from_message(text), "fix(tools): parse rows")

    def test_main_file_and_title(self):
        with tempfile.NamedTemporaryFile("w", suffix=".msg", delete=False) as f:
            f.write("docs(playbook): add backup\n\nCloses #15\n")
        try:
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cc.main(["--file", f.name]), 0)
        finally:
            os.unlink(f.name)
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cc.main(["--title", "Update stuff"]), 1)
        self.assertIn("PR title", out.getvalue())


if __name__ == "__main__":
    unittest.main()
