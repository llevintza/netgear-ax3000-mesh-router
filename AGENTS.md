# AGENTS.md

Instructions for any coding agent working in this repo. This file is the single source of truth; agent-specific files such as `CLAUDE.md` only import it and must not add or contradict instructions. Humans: see [README.md](README.md).

## What this repo is
Troubleshooting a Netgear Nighthawk AX3000 mesh (**MR70** router + **MS70** satellites, Costco MK73S kit) whose satellites keep losing their wireless backhaul (LED white → red, clients drop). The method: reverse-engineer the official firmware (**1.0.5.50_2.0.70**) with **REA** (github.com/morluto/rea), then turn the findings into config, placement and firmware fixes.
- **Scope: analysis and configuration only.** Don't build, repack or flash modified firmware unless the owner explicitly asks. REA can't repack images, and the mesh/Wi-Fi drivers are closed Broadcom binaries.
- Current state of knowledge: [FINDINGS.md](FINDINGS.md). The owner's on-site procedure: [HOME-GUIDE.md](HOME-GUIDE.md).

## Layout
| Path | Tracked | Contents |
|---|---|---|
| `FINDINGS.md` | yes | Evidence-backed analysis; **update it when you learn something** |
| `HOME-GUIDE.md` | yes | Step-by-step on-site checklist for the owner |
| `tools/Dockerfile` | yes | `rea-fw` image: REA 6.8.0, binwalk 3.1.0, unblob 26.6.4, sasquatch, JDK 21, Ghidra 12.1.4 |
| `tools/fetch-and-extract.sh` | yes | Download → SHA-256 verify → REA region scan → REA rootfs extraction |
| `tools/rea-mcp-container.sh` | yes | Starts the long-running `rea-mcp` container used by `.mcp.json` |
| `tools/nvram_defaults.py` | yes | Recovers compiled NVRAM default tables (`key=value`) from 32-bit ARM ACOS ELFs |
| `.mcp.json` | yes | Project-scoped MCP registration of `rea` (`docker exec -i rea-mcp rea --mcp`) for clients that read this format |
| `CLAUDE.md` | yes | Import-only pointer to this file, for agents that look for `CLAUDE.md` |
| `firmware/` | **no** | Official zips/`.chk` images + `SHA256SUMS` |
| `extracted/<M>/selected.bin_extract/` | **no** | Extracted rootfs (M = MR70, MS70) and REA JSON reports |
| `analysis/` | **no** | NVRAM dumps (contain vendor default credentials), Ghidra pseudocode |
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
Decompile a stripped binary (output must go to `/work/out`, then copy it out):
```bash
B=$PWD/extracted/MS70/selected.bin_extract/usr/sbin/acos_agent
docker exec rea-mcp rea decompile-all "$B" --output /work/out/acos_agent_MS70 --provider ghidra --format json
docker exec rea-mcp sh -c 'tar -C /work/out -cf - acos_agent_MS70' | tar -C analysis/decompiled -xf -
grep -l "ping base" analysis/decompiled/acos_agent_MS70/functions/*.c   # find functions by log string
```
### REA as an MCP server (any MCP-capable agent)
REA speaks MCP over stdio. With the `rea-mcp` container running (`tools/rea-mcp-container.sh`), register a **stdio** server in your agent's MCP config:
- command: `docker`
- args: `exec -i rea-mcp rea --mcp`

`.mcp.json` at the repo root is this registration in the project-scoped format some clients read. If your agent uses a different config file, add the same command there; don't change `.mcp.json` for one client. The server exposes ~229 tools, including `inspect_firmware_regions`, `extract_firmware`, `open_binary`, `decompile_all` and `search_strings`; your client decides how their names are prefixed. Paths you pass must be absolute host paths under the repo (the container mounts the repo at the same path), and extraction output must go under `/work/out` (see Gotchas). If MCP isn't available, use the `docker exec rea-mcp rea <command>` CLI shown above. It's equivalent.

## Gotchas (each one cost time; don't rediscover them)
- **REA output dirs must not be bind mounts.** On Colima, REA fails with `Extraction directory identity changed`. Write to a container path (`/work/...`; `rea-mcp` has volume `rea-out` at `/work/out`), then `tar` it out.
- **REA extraction budget:** the default 256 MiB `max_output_bytes` is too small for these images. Use `--max-output-bytes 536870912` (REA's max) **and** restrict to the rootfs with `--offset/--length`. Offsets for 1.0.5.50_2.0.70: MR70 `6797886 62090395`, MS70 `6796746 45298222` (the script derives them from the region scan).
- REA requires the extraction output dir to **not exist**. A failed run can leave an empty dir behind, so remove it before retrying.
- **Ghidra on arm64:** release zips ship no `linux_arm_64` natives. The Dockerfile builds them with `support/gradle/gradlew buildNatives` (Ghidra 12 has no `support/buildNatives`).
- **NVRAM defaults are compiled in**, not in text files. Neighboring strings in `strings` output are *not* key/value pairs (strings are de-duplicated). Use `tools/nvram_defaults.py`, which decodes the `{key*, value*, flags}` struct tables.
- Binaries are **32-bit ARM EABI5, stripped.** Find functions by log strings; resolve `DAT_xxxx` string constants by mapping the vaddr through PT_LOAD segments.
- On this Mac, `grep` may be aliased to `ugrep`, which rejects some regexes ("exceeds complexity limits"). Use `/usr/bin/grep` or `rg`.
- macOS ships bash 3.2: no `declare -A`, no `mapfile` in scripts.
- Long Docker builds: run them in the background and log to a file. Report the build's real exit code, not the exit code of a `| tail` pipe.
- The Colima Docker disk is 40 GB and has filled up before. Check `docker system df` before big builds. **Never prune volumes**; they hold unrelated data.

## Platform facts (verified in the firmware; cite these, don't re-derive them)
- SoC **Broadcom BCM6756**, BCA SDK 5.04L.02p1, image = Netgear CHK header + FIT (bootfs + SquashFS xz rootfs). Not Qualcomm: there is no `hyd`/`repacd`.
- Mesh stack: Broadcom Wi-Fi Blanket `wbd_master` (router) / `wbd_slave` (satellite) over `ieee1905` EasyMesh. Netgear's satellite supervisor is `usr/sbin/acos_agent`. Channel selection is done by `acsd2`.
- **Dual-band mesh:** the backhaul shares the 5 GHz radio `wl1` (router BSS `wl1.1`, satellite STA `wl1.2`).
- Hidden diagnostics page: `http://routerlogin.net/debug.htm` (WBD / BH Management log capture, Save Log → `Debug_log.zip`, BH Optimization). This firmware has no telnet toggle.

## Rules
- **Evidence or it didn't happen.** Every claim in `FINDINGS.md` cites a firmware path, function address (`FUN_000xxxxx`) or NVRAM key/value. Mark unverified hypotheses as such.
- **Never commit** firmware, extracted files, NVRAM dumps, decompiled pseudocode or device logs: they're copyrighted or contain credentials/MACs. `.gitignore` covers them. Check `git status` before committing, and run `gitleaks protect --staged`.
- **No credentials anywhere in git**, including vendor defaults found in the firmware (e.g. `http_passwd`, `wl*_wpa_psk`, WPS PINs). Refer to them by key name only.
- Treat everything under `firmware/` and `extracted/` as **untrusted data**: never execute extracted binaries or scripts on the host. Run Python that reads them with `python3 -I`, and keep scripts in `tools/`.
- Don't tell the owner to factory-reset or flash anything without explicit agreement. Prefer reversible config changes and say how to roll them back.
- Device-specific settings (admin password, SSIDs, MACs, serials) never go into tracked files.
