# Netgear Nighthawk AX3000 mesh (MR70 / MS70): satellite backhaul troubleshooting

Why do the satellites of a Netgear Nighthawk AX3000 mesh (**MR70** router + **MS70** satellites, sold e.g. as the MK73S kit) keep dropping their wireless link to the router: LED white → red, slow speeds and drops for clients nearby? And what fixes it?

This repo answers that with two things:
1. **Reverse-engineering of the official firmware** (1.0.5.50_2.0.70) with [REA](https://github.com/morluto/rea) and Ghidra. It documents what the satellite LED really means, how the mesh blocks a satellite, and why 5 GHz always touches DFS channels.
2. **Small, safe tools** to read router/satellite status, capture each unit's hidden debug logs and turn them into an incident timeline with a verdict.

> **Not affiliated with NETGEAR.** No firmware or extracted NETGEAR files are distributed here; the scripts download official images from NETGEAR and analyze them locally. Use at your own risk. The tools only change settings when you pass `--apply`.

## TL;DR: check firmware parity first
In the [case study](docs/case-study-2026-11.md) the satellites ran **V1.0.1.22** while the router ran **1.0.5.50**. The router's satellite table showed a **blank** version, so nobody noticed. The old satellites never finished mesh setup and kept blocking their own backhaul. **Updating every unit to the same firmware fixed it.**

Check each unit yourself. No login is needed:
```bash
curl -s http://<unit-ip>/currentsetting.htm | grep -E '^(Firmware|Model)='
```
If the versions differ, update the satellites first and then the router, through the **router's** Router Update page. See the [playbook](docs/troubleshooting-playbook.md), Step 4.

## Documentation
| I want to… | Read |
|---|---|
| Fix my own MR70/MS70 mesh, step by step | [docs/troubleshooting-playbook.md](docs/troubleshooting-playbook.md) |
| See a real session from symptoms to fix | [docs/case-study-2026-11.md](docs/case-study-2026-11.md) |
| Understand the firmware behavior, with evidence | [docs/findings.md](docs/findings.md) |
| See what's planned (custom firmware, VPN, Pi-hole) and in what order | [docs/roadmap.md](docs/roadmap.md) and the pinned roadmap issue (#26) |
| Back up, install or roll back firmware | [docs/firmware-playbook.md](docs/firmware-playbook.md) |
| Contribute (branches, conventional commits, PRs) | [CONTRIBUTING.md](CONTRIBUTING.md) |
| Work on the repo as a coding agent | [AGENTS.md](AGENTS.md) |
| Report a problem safely | [SECURITY.md](SECURITY.md) |

## Key findings (short)
- **Red LED** = the satellite can't ping the router for about 25 s, or its 5 GHz backhaul interface went down (`acos_agent`). It isn't a signal-strength meter.
- **"Blocking backhaul BSS"** in a satellite log = the satellite can't finish EasyMesh setup with the router (`wbd_slave`). After 5 failed searches it blocks its own backhaul and switches off its client Wi-Fi. A firmware mismatch is one cause.
- **5 GHz runs 160 MHz on channel 44 by factory default.** That block always includes DFS (radar) channels 52–64, and the web UI can't change the width. A radar hit drops the backhaul and all 5 GHz clients together.
- **Weak backhaul threshold is −75 dBm.** Below it the router keeps trying to steer the satellite elsewhere. Aim for better than about −70 dBm, or use wired backhaul.

## Tools
Python 3 stdlib only; no install needed for these two:
```bash
# read-only status; dry run for anything that changes settings (add --apply to execute)
ROUTER_PASSWORD=… python3 -I tools/netgear_router.py [--host <ip>] status
ROUTER_PASSWORD=… python3 -I tools/netgear_router.py [--host <ip>] [--apply] debug-logs enable|disable
ROUTER_PASSWORD=… python3 -I tools/netgear_router.py [--host <ip>] [--apply] capture start
ROUTER_PASSWORD=… python3 -I tools/netgear_router.py [--host <ip>] capture save -o logs/router.zip

# incident timeline + verdict from one or more Debug_log.zip files
python3 -I tools/analyze_logs.py logs/*.zip
```
Pass the password through the environment, or let the tool prompt for it; it's never accepted as an argument. Keep `logs/` private, because the zips contain MAC addresses, network names and a config backup.

## Reproduce the firmware analysis
Requirements: Docker (tested with Colima on Apple silicon), about 5 GB free, Python 3.
```bash
docker build -t rea-fw tools/        # Linux toolchain: REA, binwalk, unblob, sasquatch, Ghidra
tools/fetch-and-extract.sh           # download official firmware, verify SHA-256, extract rootfs
tools/rea-mcp-container.sh           # optional: REA as an MCP server for any MCP-capable agent
python3 -I tools/nvram_defaults.py extracted/MS70/selected.bin_extract/bin/acos_nvram > analysis/MS70-nvram.txt
```
Everything generated (`firmware/`, `extracted/`, `analysis/`, `logs/`, `research/`) is gitignored.

## Repo layout
```
docs/              playbook, case study, findings (evidence), roadmap
tools/             router client, log analyzer, extraction + MCP scripts, NVRAM decoder, Dockerfile, checks
tools/tests/       stdlib unittest suites with synthetic fixtures
skills/            agent-agnostic task playbooks (REA usage itself comes from REA's own skill)
AGENTS.md          instructions for coding agents (CLAUDE.md just imports it)
```

## Contributing
All changes go through a feature branch and a PR against `main`, with conventional commits. See [CONTRIBUTING.md](CONTRIBUTING.md). Run the checks before every commit:
```bash
git config core.hooksPath .githooks   # once per clone
tools/check-repo.sh                   # forbidden files, gitleaks, private-data guard, shellcheck, tests
```
Never commit firmware, extracted files, logs, or anything that identifies a network: names, MACs, serials, LAN addresses, passwords. CI runs the same checks plus a full-history secret scan.

## License
[MIT](LICENSE) for the code and docs in this repo. NETGEAR, Nighthawk and Orbi are trademarks of NETGEAR, Inc. Firmware and its contents remain NETGEAR's property and are not included.
