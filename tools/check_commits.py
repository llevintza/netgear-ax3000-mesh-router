#!/usr/bin/env python3
"""Check commit messages and PR titles against Conventional Commits (see CONTRIBUTING.md).

Usage:
  python3 -I tools/check_commits.py --title "fix(tools): stop after 401"   # a PR title
  python3 -I tools/check_commits.py --range origin/main..HEAD              # every non-merge commit in a range
  python3 -I tools/check_commits.py --file .git/COMMIT_EDITMSG             # commit-msg hook

Only the header (the first line of the message) is checked. Exit code 1 if anything fails,
2 on usage or git errors.

Length: commit headers may be up to MAX_LEN characters. PR titles get TITLE_MAX_LEN, which
leaves room for the " (#NNNN)" suffix GitHub appends when it squash-merges, so the commit
that lands on main still fits MAX_LEN.

Git-generated headers (Merge, Revert "...", Reapply "...", fixup!/squash!/amend!) are
accepted in commit messages so authors can iterate, but never in a PR title: the title
becomes the squash commit on main and must always be conventional.
"""
import argparse
import re
import subprocess
import sys

TYPES = ("feat", "fix", "docs", "test", "refactor", "build", "ci", "chore", "perf", "revert")
MAX_LEN = 100
TITLE_MAX_LEN = MAX_LEN - len(" (#9999)")
HEADER = re.compile(
    r"^(?P<type>[a-z]+)"
    r"(?:\((?P<scope>[a-z0-9][a-z0-9._/-]*)\))?"
    r"(?P<breaking>!)?"
    r": (?P<summary>\S.*)$"
)
# Headers git writes itself. Allowed for commits only (see the module docstring).
GIT_GENERATED = re.compile(r"^(Merge |Revert \"|Reapply \"|fixup! |squash! |amend! )")
# `git commit -v` appends the diff below this line; everything after it is ignored by git.
SCISSORS = " ------------------------ >8 ------------------------"


def check_header(header, title=False):
    """Return an error string, or None if the header is valid.

    title=True applies the PR-title rules: no git-generated exemptions, TITLE_MAX_LEN.
    """
    header = header.rstrip("\r\n")
    if not title and GIT_GENERATED.match(header):
        return None
    m = HEADER.match(header)
    if not m:
        return "not '<type>(<scope>): <summary>'"
    if m.group("type") not in TYPES:
        return "unknown type '%s' (allowed: %s)" % (m.group("type"), ", ".join(TYPES))
    limit = TITLE_MAX_LEN if title else MAX_LEN
    if len(header) > limit:
        return "longer than %d characters" % limit
    if m.group("summary").endswith("."):
        return "summary ends with a period"
    return None


def comment_char():
    """git's core.commentChar, falling back to '#' (also for 'auto' or outside a repo)."""
    try:
        out = subprocess.run(
            ["git", "config", "core.commentChar"],
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, universal_newlines=True,
        ).stdout.strip()
    except OSError:
        return "#"
    return out if out and out != "auto" else "#"


def header_from_message(text, comment="#"):
    """First non-empty, non-comment line before the scissors line; "" if there is none."""
    for line in text.split("\n"):
        line = line.rstrip("\r")
        if line == comment + SCISSORS:
            break
        if line.strip() and not line.startswith(comment):
            return line
    return ""


class GitError(Exception):
    pass


def headers_in_range(rev_range):
    """[(short sha, header)] for every non-merge commit in rev_range, header = first line."""
    try:
        proc = subprocess.run(
            ["git", "log", "--no-merges", "--format=%h%x00%B%x1e", rev_range],
            stdout=subprocess.PIPE, stderr=subprocess.PIPE,
        )
    except OSError as e:
        raise GitError("cannot run git: %s" % e)
    if proc.returncode != 0:
        raise GitError("git log %s failed:\n%s" % (rev_range, proc.stderr.decode("utf-8", "replace").strip()))
    items = []
    for record in proc.stdout.decode("utf-8", "replace").split("\x1e"):
        record = record.lstrip("\n")
        if not record:
            continue
        sha, _, body = record.partition("\x00")
        items.append((sha, body.split("\n", 1)[0]))
    return items


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    g = ap.add_mutually_exclusive_group(required=True)
    g.add_argument("--title", help="a single header, e.g. a PR title")
    g.add_argument("--range", dest="rev_range", help="git revision range, e.g. origin/main..HEAD")
    g.add_argument("--file", help="commit message file (commit-msg hook)")
    args = ap.parse_args(argv)

    is_title = args.title is not None
    if is_title:
        items = [("PR title", args.title)]
    elif args.file is not None:
        if not args.file:
            ap.error("--file needs a path")
        try:
            with open(args.file, encoding="utf-8", errors="replace") as f:
                header = header_from_message(f.read(), comment_char())
        except OSError as e:
            print("ERROR cannot read commit message file: %s" % e)
            return 2
        if not header:
            return 0  # empty message: let git abort the commit with its own message
        items = [("commit message", header)]
    else:
        if not args.rev_range:
            ap.error("--range needs a revision range")
        try:
            items = headers_in_range(args.rev_range)
        except GitError as e:
            print("ERROR %s" % e)
            return 2

    bad = 0
    for label, header in items:
        err = check_header(header, title=is_title)
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
