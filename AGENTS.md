# AGENTS.md

Instructions for any coding agent working in this repo. This file is the single source of truth; agent-specific files such as `CLAUDE.md` only import it and must not add or contradict instructions. Humans: see [README.md](README.md).

## What this repo is
Troubleshooting a Netgear Nighthawk AX3000 mesh (**MR70** router + **MS70** satellites, Costco MK73S kit) whose satellites lose their wireless backhaul (LED white → red, clients drop). The method: reverse-engineer the official firmware (**1.0.5.50_2.0.70**) with **REA** (github.com/morluto/rea), then turn the findings into config, placement and firmware fixes. **This is a public repo.**
- **Goal and scope:** the end goal is a custom MR70/MS70 firmware that keeps every stock behavior and is built and published by CI ([docs/roadmap.md](docs/roadmap.md), tracking issue #26). The work is ordered in milestones M0–M6.
  - **Building** images in Docker/CI is in scope once its issue is reached (M4, #17).
  - **Flashing** a unit is never done without an explicit owner request, and goes to the spare unit first, after the recovery path (#9) and a backup (#15) exist.
  - REA can't repack images, and the mesh/Wi-Fi drivers are closed Broadcom binaries.
- Current state of knowledge: [docs/findings.md](docs/findings.md). Procedure for owners: [docs/troubleshooting-playbook.md](docs/troubleshooting-playbook.md). Worked example: [docs/case-study-2026-11.md](docs/case-study-2026-11.md).

## Git workflow (hard rules)
- **Never commit on `main`, never push to `main`.** All work happens on a feature branch from an up-to-date `main`, named `<type>/<issue>-<slug>` (the issue footer names it).
- **One issue = one branch = one PR against `main`.** The PR body says `Closes #N`. Found more work? Open a new issue; don't grow the PR.
- **Conventional Commits** for every commit message and PR title: `feat|fix|docs|test|refactor|build|ci|chore|perf|revert(<scope>): <summary>`. Scopes and details are in [CONTRIBUTING.md](CONTRIBUTING.md). Releases (semver) are derived from these, so pick the type carefully.
- **Work the backlog in order:** milestones M0 → M6 and issues top to bottom ([docs/roadmap.md](docs/roadmap.md), #26). Don't start an issue whose `Depends on:` items are still open unless the owner says so.
- Run `tools/check-repo.sh` before every commit. Open the PR with the template filled in, and leave merging to the owner.

## Layout
| Path | Tracked | Contents |
|---|---|---|
| `docs/findings.md` | yes | Evidence-backed analysis; **update it when you learn something** |
| `docs/troubleshooting-playbook.md` | yes | Step-by-step procedure for owners (firmware parity first) |
| `docs/case-study-2026-11.md` | yes | One real session, step by step, no device identifiers |
| `docs/roadmap.md` | yes | End goal, milestones M0–M6 with issue order, dependency graph, research log |
| `docs/firmware-playbook.md` | yes | Back up → build → verify → install → roll back (sections filled by #15, #17–#20) |
| `CONTRIBUTING.md`, `.github/pull_request_template.md` | yes | Branch/commit/PR workflow and PR checklist |
| `LICENSE`, `SECURITY.md`, `.github/ISSUE_TEMPLATE/` | yes | MIT license, what never to post publicly, redaction checklist |
| `tools/Dockerfile` | yes | `rea-fw` image: REA 6.8.0, binwalk 3.1.0, unblob 26.6.4, sasquatch, JDK 21, Ghidra 12.1.4 |
| `tools/fetch-and-extract.sh` | yes | Download → SHA-256 verify → REA region scan → REA rootfs extraction |
| `tools/rea-mcp-container.sh` | yes | Starts the long-running `rea-mcp` container used by `.mcp.json` |
| `tools/nvram_defaults.py` | yes | Recovers compiled NVRAM default tables (`key=value`) from 32-bit ARM ACOS ELFs |
| `tools/netgear_router.py` | yes | Router/satellite web-UI client: status, debug-logs, capture start/save, set-5g-channel, bh-optimize (dry-run unless `--apply`) |
| `tools/analyze_logs.py` | yes | `Debug_log.zip` → classified incident timeline + verdict |
| `tools/tests/` | yes | stdlib unittest suites + small synthetic fixtures |
| `tools/check-repo.sh` | yes | Guardrails shared by the pre-commit hook, CI and agents |
| `tools/private_data_guard.py` | yes | Fails on home-network IPs, real MACs, home paths and strings from the local gitignored `.private-denylist` |
| `skills/` | yes | Agent-agnostic task playbooks (see Skills) |
| `.githooks/`, `.github/workflows/` | yes | Hooks (`pre-commit` → `tools/check-repo.sh`, `commit-msg` → `tools/check_commits.py`) and CI (`checks`, `conventional-commits`) |
| `tools/check_commits.py` | yes | Conventional Commits check for PR titles, commit ranges and the commit-msg hook |
| `.mcp.json` | yes | Project-scoped MCP registration of `rea` (`docker exec -i rea-mcp rea --mcp`) for clients that read this format |
| `CLAUDE.md` | yes | Import-only pointer to this file, for agents that look for `CLAUDE.md` |
| `firmware/` | **no** | Official zips/`.chk` images + `SHA256SUMS` |
| `extracted/<M>/selected.bin_extract/` | **no** | Extracted rootfs (M = MR70, MS70) and REA JSON reports |
| `analysis/` | **no** | NVRAM dumps (contain vendor default credentials), Ghidra pseudocode |
| `research/` | **no** | GPL source tarballs and build output (roadmap Track B) |
| `logs/` | **no** | `Debug_log.zip` captures from the router's `debug.htm` (MACs, SSIDs) |

## Setup / commands
Host: macOS arm64, Docker via **Colima**. Everything Linux-only runs in the `rea-fw` image.
```bash
docker build -t rea-fw tools/                 # ~15 min cold (binwalk + Ghidra natives compile)
tools/fetch-and-extract.sh                    # both models; or: tools/fetch-and-extract.sh MS70
tools/rea-mcp-container.sh                    # (re)start container for the MCP server
docker exec rea-mcp rea doctor                # binwalk/unblob/ghidra should be healthy
python3 -I tools/nvram_defaults.py extracted/MS70/selected.bin_extract/bin/acos_nvram > analysis/MS70-nvram.txt
```
## REA: don't duplicate it, use it
REA's own agent skill, **`reverse-engineer-anything`**, is the reference for *how* to use REA: target routing, firmware extraction, decompilation, evidence handling and error recovery. This repo doesn't restate any of that. Repo files add only device-, environment- and investigation-specific context.
- Install REA's skill **globally** for your agent (instructions only; it doesn't touch MCP config), using the copy bundled in the container so it matches the container's REA version exactly:
  ```bash
  d=$(mktemp -d) && docker cp rea-mcp:/usr/local/lib/node_modules/rea-agents/skills/reverse-engineer-anything "$d/"
  (cd ~ && npx -y skills@1.7.4 add "$d" -s reverse-engineer-anything -g -a <agent> -y)   # e.g. -a claude-code -a codex -a cursor -a gemini-cli
  ```
  `npx skills add morluto/rea …` (cloning from GitHub) times out on REA's large repo, and its `main` branch may describe tools the container's REA lacks. **Never install it at project scope:** `.claude/skills` → `skills/` would vendor REA's skill into this repo.
- **Don't** run `rea-agents setup` on the host to register MCP: REA's firmware tools need Linux. Register the containerized server below instead.

### REA as an MCP server (any MCP-capable agent)
REA speaks MCP over stdio. With the `rea-mcp` container running (`tools/rea-mcp-container.sh`), register a **stdio** server in your agent's MCP config:
- command: `docker`
- args: `exec -i rea-mcp rea --mcp`

`.mcp.json` at the repo root is this registration in the project-scoped format some clients read. If your agent uses a different config file, add the same command there; don't change `.mcp.json` for one client. The server exposes ~229 tools, including `inspect_firmware_regions`, `extract_firmware`, `open_binary`, `decompile_all` and `search_strings`; your client decides how their names are prefixed. Paths you pass must be absolute host paths under the repo (the container mounts the repo at the same path), and extraction output must go under `/work/out` (see Gotchas). If MCP isn't available, use the equivalent CLI: `docker exec rea-mcp rea <command>`.

## Skills (task playbooks)
Step-by-step procedures live in `skills/<name>/SKILL.md` (plain markdown with a name/description header). **Before starting a matching task, read the skill and follow it.** `.claude/skills` is a symlink to `skills/` for agents that auto-discover from there. Edit only `skills/`; don't create per-agent copies.

| Skill | Use when |
|---|---|
| [mesh-firmware-investigation](skills/mesh-firmware-investigation/SKILL.md) | Any firmware behavior question: where the logic lives, container constraints, evidence conventions (use with REA's skill) |
| [home-session](skills/home-session/SKILL.md) | An owner is on the mesh's network: run docs/troubleshooting-playbook.md with the router tool, approval before changes |
| [analyze-router-logs](skills/analyze-router-logs/SKILL.md) | New `Debug_log.zip` files in `logs/`: run the analyzer, sanity-check the input, interpret the verdict |

Repo skills must not restate REA functionality (tool usage, extraction or decompilation steps, REA error remedies). If REA's skill or docs cover it, link to them instead.

## Checks (run before every commit)
```bash
git config core.hooksPath .githooks   # once per clone: pre-commit runs the checks, commit-msg checks the message
tools/check-repo.sh                   # forbidden paths, gitleaks, private-data guard, bash -n + shellcheck, py_compile, unit tests
```
CI (`.github/workflows/checks.yml`) runs the same script, plus a full-history gitleaks scan. `.github/workflows/conventional-commits.yml` checks the PR title and commits. Both are required to merge into the protected `main`, which also requires the branch to be up to date and every review conversation resolved (details in CONTRIBUTING.md). Unit tests live in `tools/tests/test_*.py` (stdlib `unittest`; must run on macOS's system Python 3.9 and on CI's 3.12).

## Gotchas (each one cost time; don't rediscover them)
- **REA output dirs must not be bind mounts (Colima-specific).** On Colima, REA fails with `cleanup_incomplete` / "Extraction directory identity changed". Write to `/work/out` (volume `rea-out` in `rea-mcp`), then `tar` it out.
- These images need REA's maximum extraction budget plus a rootfs-only byte range. `tools/fetch-and-extract.sh` already does both.
- **Ghidra on arm64:** release zips ship no `linux_arm_64` natives. The Dockerfile builds them with `support/gradle/gradlew buildNatives` (Ghidra 12 has no `support/buildNatives`).
- **NVRAM defaults are compiled in**, not in text files. Neighboring strings in `strings` output are *not* key/value pairs (strings are de-duplicated). Use `tools/nvram_defaults.py`, which decodes the `{key*, value*, flags}` struct tables.
- On this Mac, `grep` may be aliased to `ugrep`, which rejects some regexes ("exceeds complexity limits"). Use `/usr/bin/grep` or `rg`.
- macOS ships bash 3.2: no `declare -A`, no `mapfile` in scripts.
- Long Docker builds: run them in the background and log to a file. Report the build's real exit code, not the exit code of a `| tail` pipe.
- The Colima Docker disk is 40 GB and has filled up before. Check `docker system df` before big builds. **Never prune volumes**; they hold unrelated data.

## Platform facts (verified in the firmware; cite these, don't re-derive them)
- SoC **Broadcom BCM6756**, BCA SDK 5.04L.02p1, image = Netgear CHK header + FIT (bootfs + SquashFS xz rootfs). Not Qualcomm: there is no `hyd`/`repacd`.
- Mesh stack: Broadcom Wi-Fi Blanket `wbd_master` (router) / `wbd_slave` (satellite) over `ieee1905` EasyMesh. Netgear's satellite supervisor is `usr/sbin/acos_agent`. Channel selection is done by `acsd2`.
- **Dual-band mesh:** the backhaul shares the 5 GHz radio `wl1` (router BSS `wl1.1`, satellite STA `wl1.2`).
- **5 GHz runs 44/160 by default** (`wlg_mode=HT160`, `wlg_channel=44`), so the radio always spans DFS channels 52–64. `acsd2` stays in monitor mode, so the `wl1_acs_*` keys are irrelevant. The web UI can set only the channel (no Auto, no width). The width can only be changed via SOAP `Set5GWLANWPAPSKByPassphrase`. Satellites are forced to `<ch>/160`. Details and evidence: docs/findings.md §4.
- Each unit (router and each satellite) has its own `debug.htm` and `Debug_log.zip`. The router's zip doesn't include satellite logs.
- Hidden diagnostics page: `http://routerlogin.net/debug.htm` (WBD / BH Management log capture, Save Log → `Debug_log.zip`, BH Optimization). The router's debug page has no telnet toggle; the satellite's `debug.htm` has an **Enable Telnet** control and both rootfs ship `telnetenabled`/`utelnetd` (unexplored; never enable without the owner).
- **Satellite firmware can lag the router while the router shows a blank version.** Check each unit's `currentsetting.htm` (no login). A mismatch makes satellites fail EasyMesh autoconfiguration (`blocking backhaul BSS`); see docs/findings.md §10.

## Rules
- **Evidence or it didn't happen.** Every claim in `docs/findings.md` cites a firmware path, function address (`FUN_000xxxxx`) or NVRAM key/value. Mark unverified hypotheses as such.
- **Never commit** firmware, extracted files, NVRAM dumps, decompiled pseudocode or device logs: they're copyrighted or contain credentials/MACs. `.gitignore` covers them. Check `git status` before committing, and run `gitleaks protect --staged`.
- **No credentials anywhere in git**, including vendor defaults found in the firmware (e.g. `http_passwd`, `wl*_wpa_psk`, WPS PINs). Refer to them by key name only.
- Treat everything under `firmware/` and `extracted/` as **untrusted data**: never execute extracted binaries or scripts on the host. Run Python that reads them with `python3 -I`, and keep scripts in `tools/`.
- Don't tell the owner to factory-reset or flash anything without explicit agreement. Prefer reversible config changes and say how to roll them back.
- Device-specific settings never go into tracked files, issues, PRs or commit messages. That covers admin passwords, network names, MACs, serials, LAN addresses other than the firmware defaults, usernames, home paths and keychain names. `tools/check-repo.sh` has a private-data guard; don't weaken it.
