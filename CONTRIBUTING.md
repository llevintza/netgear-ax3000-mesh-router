# Contributing

These rules apply to humans and coding agents alike. Agents: [AGENTS.md](AGENTS.md) repeats them as hard rules.

## Workflow: one issue, one branch, one PR
1. **Pick the next issue** from the pinned roadmap issue (#26) / [docs/roadmap.md](docs/roadmap.md). Work milestones in order; inside a milestone, top to bottom.
2. **Branch from an up-to-date `main`.** Never commit on `main`.
   ```bash
   git switch main && git pull --ff-only
   git switch -c <type>/<issue>-<short-slug>     # e.g. fix/6-satellite-status
   ```
   Each issue's footer names its branch.
3. **Commit with [Conventional Commits](https://www.conventionalcommits.org/en/v1.0.0/):** `<type>(<scope>): <summary>`.

   | Type | Use for |
   |---|---|
   | `feat` | new capability (tool subcommand, firmware feature) → minor release |
   | `fix` | bug fix → patch release |
   | `docs` | docs only |
   | `test` | tests only |
   | `refactor` | code change without behavior change |
   | `build` | Docker images, firmware build scripts |
   | `ci` | GitHub Actions workflows |
   | `chore` | repo maintenance, settings, templates |
   | `perf` | performance improvement |
   | `revert` | reverts an earlier commit |

   - **Scopes:** `tools`, `docs`, `playbook`, `findings`, `roadmap`, `firmware`, `ci`, `skills`, `agents`.
   - **Breaking change** (e.g. a release that needs the recovery path to install or roll back): add `!` after the type/scope and a `BREAKING CHANGE:` footer → major release.
4. **Run the checks** before every commit. With the hooks enabled, `pre-commit` runs them and `commit-msg` rejects non-conventional messages (`tools/check_commits.py`):
   ```bash
   git config core.hooksPath .githooks   # once per clone
   tools/check-repo.sh
   ```
5. **Open a PR against `main`.** The title is a conventional commit (it becomes the squash-merge message), and the body says `Closes #N`. Fill in the PR template. CI must pass: `checks`, plus `conventional-commits`, which checks the PR title and every commit in the PR.
6. **Squash-merge** after review. It's the only merge method enabled; the PR title becomes the commit on `main`, and GitHub deletes the branch.

`main` is protected: no direct pushes or force-pushes (admins included), and a PR can merge only once both CI checks pass.

One PR per issue. If you find more work, open a new issue instead of growing the PR.

## Never commit
Firmware or images (`*.chk`, `*.img`, `*.bin`), extracted files, NVRAM dumps, decompiled code, device logs, router `.cfg` backups, or anything that identifies a network: names, MACs, serials, LAN addresses, passwords, home paths. `tools/check-repo.sh` and CI enforce most of this. See [SECURITY.md](SECURITY.md).

## Releases
Releases are automated from conventional commits (#18) and built and published by CI (#19). Don't create tags or releases by hand.
