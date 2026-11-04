"""Tests for tools/check_commits.py.

Run: python3 -I -m unittest discover -s tools/tests -v
"""
import io
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
import unittest.mock
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
        for h in (
            "Merge branch 'main' into fix/6-x",
            'Revert "docs: add x"',
            'Reapply "docs: add x"',
            "fixup! fix(tools): y",
            "squash! fix(tools): y",
            "amend! fix(tools): y",
        ):
            self.assertIsNone(cc.check_header(h), h)

    def test_title_gets_no_git_generated_exemption(self):
        for h in ("Merge branch 'main' into fix/6-x", 'Revert "docs: add x"', 'Reapply "docs: x"',
                  "fixup! fix(tools): y", "squash! fix(tools): y", "amend! fix(tools): y"):
            self.assertIsNotNone(cc.check_header(h, title=True), h)
        self.assertIsNone(cc.check_header("fix(tools): y", title=True))

    def test_title_leaves_room_for_squash_suffix(self):
        header = "docs: " + "x" * (cc.TITLE_MAX_LEN - 6)
        self.assertIsNone(cc.check_header(header, title=True))
        self.assertIn("longer than", cc.check_header(header + "x", title=True))
        self.assertLessEqual(len(header + " (#9999)"), cc.MAX_LEN)
        self.assertIsNone(cc.check_header(header + " (#9999)"))

    def test_main_title_rejects_git_generated(self):
        for h in ("Merge branch 'main'", "fixup! fix(tools): y"):
            with redirect_stdout(io.StringIO()):
                self.assertEqual(cc.main(["--title", h]), 1, h)


class MessageFileTests(unittest.TestCase):
    def test_header_skips_comments_and_blank_lines(self):
        text = "\n# Please enter the commit message\nfix(tools): parse rows\n\nbody\n"
        self.assertEqual(cc.header_from_message(text), "fix(tools): parse rows")

    def test_header_stops_at_scissors(self):
        diff = "# ------------------------ >8 ------------------------\n# Do not modify\ndiff --git a/g b/g\n"
        self.assertEqual(cc.header_from_message("\n# comment\n" + diff), "")
        self.assertEqual(cc.header_from_message("docs: x\n" + diff), "docs: x")

    def test_header_custom_comment_char(self):
        text = "; comment\nfix(tools): x\n"
        self.assertEqual(cc.header_from_message(text, ";"), "fix(tools): x")
        self.assertEqual(cc.header_from_message(text), "; comment")

    def _run_file(self, data):
        with tempfile.NamedTemporaryFile("wb", suffix=".msg", delete=False) as f:
            f.write(data)
        try:
            out = io.StringIO()
            with redirect_stdout(out):
                rc = cc.main(["--file", f.name])
            return rc, out.getvalue()
        finally:
            os.unlink(f.name)

    def test_empty_message_left_to_git(self):
        rc, out = self._run_file(b"\n# Please enter the commit message\n"
                                 b"# ------------------------ >8 ------------------------\n"
                                 b"diff --git a/g b/g\n")
        self.assertEqual(rc, 0)
        self.assertEqual(out, "")

    def test_non_utf8_file(self):
        self.assertEqual(self._run_file(b"docs: caf\xe9 notes\n")[0], 0)
        self.assertEqual(self._run_file(b"Caf\xe9 notes\n")[0], 1)

    def test_empty_file_path_is_usage_error(self):
        with redirect_stdout(io.StringIO()), unittest.mock.patch("sys.stderr", io.StringIO()):
            with self.assertRaises(SystemExit) as cm:
                cc.main(["--file", ""])
        self.assertEqual(cm.exception.code, 2)

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


@unittest.skipUnless(shutil.which("git"), "git not installed")
class RangeTests(unittest.TestCase):
    """--range against a throwaway repo; hooks and user config are bypassed."""

    def setUp(self):
        self.repo = tempfile.mkdtemp()
        self.addCleanup(shutil.rmtree, self.repo)
        # Drop GIT_DIR, GIT_INDEX_FILE etc.: under a hook they point at the outer repo.
        self.env = {k: v for k, v in os.environ.items() if not k.startswith("GIT_")}
        self.env.update(GIT_CONFIG_GLOBAL=os.devnull, GIT_CONFIG_NOSYSTEM="1")
        self.git("init", "-q")
        self.git("config", "user.name", "Test")
        self.git("config", "user.email", "test@example.invalid")
        self.git("commit", "-q", "--allow-empty", "--no-verify", "-m", "chore: root")
        self.base = self.git("rev-parse", "HEAD").strip()
        cwd = os.getcwd()
        os.chdir(self.repo)
        self.addCleanup(os.chdir, cwd)
        patcher = unittest.mock.patch.dict(os.environ, self.env, clear=True)
        patcher.start()
        self.addCleanup(patcher.stop)

    def git(self, *args):
        return subprocess.run(
            ["git", "-c", "core.hooksPath=" + os.devnull] + list(args), cwd=self.repo, env=self.env,
            check=True, stdout=subprocess.PIPE, universal_newlines=True,
        ).stdout

    def commit(self, message):
        self.git("commit", "-q", "--allow-empty", "--no-verify", "--cleanup=verbatim", "-m", message)

    def test_only_first_line_checked(self):
        self.commit("fix(tools): parse rows\nstill the first paragraph.\n\nbody")
        self.commit("docs: summary\n" + "x" * 200)
        self.assertEqual([h for _, h in cc.headers_in_range(self.base + "..HEAD")],
                         ["docs: summary", "fix(tools): parse rows"])
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cc.main(["--range", self.base + "..HEAD"]), 0)

    def test_unicode_line_separator_in_subject(self):
        self.commit("docs: a\u2028b")
        self.assertEqual(cc.headers_in_range(self.base + "..HEAD")[0][1], "docs: a\u2028b")

    def test_git_generated_commits_allowed_but_bad_ones_fail(self):
        self.commit('Reapply "docs: x"')
        self.commit("fixup! docs: x")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(cc.main(["--range", self.base + "..HEAD"]), 0)
        self.commit("Update stuff")
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cc.main(["--range", self.base + "..HEAD"]), 1)
        self.assertIn("Update stuff", out.getvalue())

    def test_invalid_range_reports_git_error(self):
        out = io.StringIO()
        with redirect_stdout(out):
            self.assertEqual(cc.main(["--range", "nosuchref..HEAD"]), 2)
        self.assertIn("git log nosuchref..HEAD failed", out.getvalue())
        self.assertIn("nosuchref", out.getvalue().split("failed", 1)[1])


if __name__ == "__main__":
    unittest.main()
