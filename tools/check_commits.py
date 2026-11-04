#!/usr/bin/env python3
"""Check commit messages and PR titles against Conventional Commits (see CONTRIBUTING.md).

Usage:
  python3 -I tools/check_commits.py --title "fix(tools): stop after 401"   # a PR title
  python3 -I tools/check_commits.py --range origin/main..HEAD              # every non-merge commit in a range
  python3 -I tools/check_commits.py --file .git/COMMIT_EDITMSG             # commit-msg hook

Only the header (first line) is checked. Exit code 1 if anything fails.
"""
import argparse
import re
import subprocess
import sys

TYPES = ("feat", "fix", "docs", "test", "refactor", "build", "ci", "chore", "perf", "revert")
MAX_LEN = 100
HEADER = re.compile(
    r"^(?P<type>[a-z]+)"
    r"(?:\((?P<scope>[a-z0-9][a-z0-9._/-]*)\))?"
    r"(?P<breaking>!)?"
    r": (?P<summary>\S.*)$"
)
# Messages git writes itself; left alone (squash-merge on GitHub replaces them anyway).
GIT_GENERATED = re.compile(r"^(Merge |Revert \"|fixup! |squash! |amend! )")


def check_header(header):
    """Return an error string, or None if the header is valid."""
    header = header.rstrip("\n")
    if GIT_GENERATED.match(header):
        return None
    m = HEADER.match(header)
    if not m:
        return "not '<type>(<scope>): <summary>'"
    if m.group("type") not in TYPES:
        return "unknown type '%s' (allowed: %s)" % (m.group("type"), ", ".join(TYPES))
    if len(header) > MAX_LEN:
        return "longer than %d characters" % MAX_LEN
    if m.group("summary").endswith("."):
        return "summary ends with a period"
    return None


def header_from_message(text):
    """First non-empty line that isn't a git comment."""
    for line in text.splitlines():
        if line.strip() and not line.startswith("#"):
            return line
    return ""


def headers_in_range(rev_range):
    out = subprocess.run(
        ["git", "log", "--no-merges", "--format=%h %s", rev_range],
        check=True, capture_output=True, text=True,
    ).stdout
    return [tuple(line.split(" ", 1)) for line in out.splitlines() if line]


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--title", help="a single header, e.g. a PR title")
    g.add_argument("--range", dest="rev_range", help="git revision range, e.g. origin/main..HEAD")
    g.add_argument("--file", help="commit message file (commit-msg hook)")
    args = ap.parse_args(argv)

    if args.title is not None:
        items = [("PR title", args.title)]
    elif args.file:
        with open(args.file, encoding="utf-8") as f:
            items = [("commit message", header_from_message(f.read()))]
    else:
        items = headers_in_range(args.rev_range)

    bad = 0
    for label, header in items:
        err = check_header(header)
        if err:
            bad += 1
            print("ERROR %s: %s\n  %r" % (label, err, header))
    if bad:
        print("\nExpected Conventional Commits, e.g. 'fix(tools): stop retrying after 401'. See CONTRIBUTING.md.")
        return 1
    print("ok: %d header(s) checked" % len(items))
    return 0


if __name__ == "__main__":
    sys.exit(main())
