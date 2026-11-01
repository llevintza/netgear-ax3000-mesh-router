# Netgear AX3000 mesh: satellite backhaul troubleshooting

Troubleshooting a Netgear Nighthawk AX3000 mesh (MR70 router + 2× MS70 satellites). The satellites keep losing their wireless link to the router: the LED turns red, and clients on the satellites get slow speeds and drops.

The approach is to reverse-engineer the official firmware (**1.0.5.50_2.0.70**) with [REA](https://github.com/morluto/rea), work out what the satellites actually do, and turn that into config, placement and firmware fixes. Building custom firmware is out of scope.

## Start here
| If you want… | Read |
|---|---|
| What we found in the firmware and why the satellites drop | [FINDINGS.md](FINDINGS.md) |
| What to do at home, step by step | [HOME-GUIDE.md](HOME-GUIDE.md) |
| How to work on this repo (developers and coding agents) | [AGENTS.md](AGENTS.md) |

## Short version
- The red LED means the satellite has lost contact with the router: about 25 s of failed pings, or the 5 GHz link dropping (decompiled from `acos_agent`).
- The backhaul shares the 5 GHz radio with the clients. Factory defaults pick the 5 GHz channel automatically and allow DFS (radar) channels, so a radar detection forces a channel change and cuts the satellites off.
- Main fix: pin 5 GHz to a non-DFS channel (36–48), then run BH optimization on `routerlogin.net/debug.htm`, check placement, and use wired backhaul if needed.

## Reproduce the analysis
Requirements: Docker (tested with Colima on Apple silicon), about 5 GB free in Docker, Python 3.
```bash
docker build -t rea-fw tools/        # Linux toolchain: REA, binwalk, unblob, Ghidra
tools/fetch-and-extract.sh           # download official firmware, verify SHA-256, extract rootfs
tools/rea-mcp-container.sh           # optional: REA as an MCP server for any MCP-capable agent
```
Firmware images, extracted files, NVRAM dumps, decompiled code and device logs are **not** in git: they're Netgear's copyrighted material or contain credentials. The scripts regenerate them locally.

## Repo layout
```
FINDINGS.md        analysis with evidence (file paths, functions, NVRAM keys)
HOME-GUIDE.md      on-site checklist
AGENTS.md          instructions for any coding agent (CLAUDE.md is an import-only pointer)
tools/             Dockerfile, extraction + MCP scripts, NVRAM table decoder
firmware/ extracted/ analysis/ logs/   local only (gitignored)
```
