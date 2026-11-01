#!/usr/bin/env bash
# Repo guardrails, shared by the pre-commit hook (.githooks/pre-commit), CI and agents.
# Usage: tools/check-repo.sh [--staged]
#   --staged  check only what is staged (pre-commit); default checks the whole working tree.
set -euo pipefail
cd "$(dirname "$0")/.."

mode=${1:-all}
fail=0
note() { printf '  %s\n' "$*"; }

if [ "$mode" = "--staged" ]; then
  files=$(git diff --cached --name-only --diff-filter=ACMR)
else
  files=$(git ls-files -co --exclude-standard)
fi

echo "1/5 forbidden files (firmware, extracted data, dumps, logs, credentials)"
bad=$(printf '%s\n' "$files" | /usr/bin/grep -E '^(firmware|extracted|analysis|logs)/|\.(chk|img|bin|zip|trx)$|(^|/)\.env$' || true)
if [ -n "$bad" ]; then
  note "ERROR: these must never be committed (copyrighted firmware or sensitive data):"
  printf '%s\n' "$bad" | sed 's/^/    /'
  fail=1
else
  note ok
fi

echo "2/5 secrets (gitleaks)"
if command -v gitleaks >/dev/null; then
  if [ "$mode" = "--staged" ]; then leaks_cmd=(gitleaks protect --staged); else leaks_cmd=(gitleaks detect); fi
  if "${leaks_cmd[@]}" --no-banner --redact >/dev/null 2>&1; then
    note ok
  else
    note "ERROR: gitleaks found secrets (run: ${leaks_cmd[*]} -v)"; fail=1
  fi
else
  note "WARN: gitleaks not installed, skipped (brew install gitleaks)"
fi

echo "3/5 shell scripts (bash -n, shellcheck)"
sh_files=$(printf '%s\n' "$files" | /usr/bin/grep -E '\.sh$|^\.githooks/' || true)
for f in $sh_files; do
  [ -f "$f" ] || continue
  bash -n "$f" || { note "ERROR: syntax $f"; fail=1; }
done
if [ -n "$sh_files" ] && command -v shellcheck >/dev/null; then
  # shellcheck disable=SC2086
  shellcheck -S warning $sh_files || fail=1
fi
note "done"

echo "4/5 python (compile)"
py_files=$(printf '%s\n' "$files" | /usr/bin/grep -E '\.py$' || true)
for f in $py_files; do
  [ -f "$f" ] || continue
  python3 -I -m py_compile "$f" || { note "ERROR: $f"; fail=1; }
done
note "done"

echo "5/5 python tests (tools/tests)"
if [ -d tools/tests ] && ls tools/tests/test_*.py >/dev/null 2>&1; then
  python3 -I -m unittest discover -s tools/tests -q || fail=1
else
  note "no tests"
fi

if [ $fail -ne 0 ]; then echo "FAILED"; exit 1; fi
echo "all checks passed"
