---
name: mesh-firmware-investigation
description: Repo-specific map for investigating the MR70/MS70 firmware (which binaries hold the mesh, backhaul, LED and channel logic, environment constraints, how to record evidence). Use together with REA's own `reverse-engineer-anything` skill whenever a question about this router's behavior needs the firmware.
---

# MR70/MS70 firmware investigation

**How to use REA (routing, extraction, decompilation, evidence handling, error recovery) is REA's own `reverse-engineer-anything` skill, not this file.** Install it if your agent doesn't have it (see AGENTS.md → REA). This skill only adds what REA can't know: this device, this environment, and this investigation's conventions.

## Environment constraints (this repo's container setup)
- REA runs in the `rea-mcp` container (`tools/rea-mcp-container.sh`). The repo is mounted at the **same absolute path**, so pass host paths unchanged.
- REA output directories must be under **`/work/out`** (a Docker volume), not under the repo. On Colima, bind mounts trigger REA's `cleanup_incomplete` / "Extraction directory identity changed". Copy results out with `docker exec rea-mcp sh -c 'tar -C /work/out -cf - <dir>' | tar -C analysis/decompiled -xf -`.
- The extracted rootfs already exists (or run `tools/fetch-and-extract.sh`). Don't re-extract to answer behavior questions.

## Where the logic lives (32-bit ARM EABI5, stripped)
Paths relative to `extracted/<M>/selected.bin_extract/`.

| Question area | Start here | Known so far (see FINDINGS.md) |
|---|---|---|
| Satellite LED / router reachability | MS70 `usr/sbin/acos_agent` | `FUN_00012a3c` 5 s supervisor loop; `FUN_00012064` ping check (5 failures → red, 2 successes → normal); `FUN_0001251c` wl1 link check (DHCP release on link loss) |
| Mesh controller/agent, backhaul steering | MR70 `usr/sbin/wbd_master`, MS70 `usr/sbin/wbd_slave`, `usr/lib/libwbdshared.so` | "Blocking backhaul BSS", weak backhaul STA policy `wbd_weak_sta_cfg_bh` |
| EasyMesh transport | `usr/sbin/ieee1905` | — |
| 5 GHz channel / width / DFS | `lib/libwlanUtil.so` (`set_wirelss_5g_1_channel/_mode`, MS70 `cb_satallite_wl1_chanspec`), `usr/sbin/acsd2` | default 44/160 → DFS 52–64 always in use; acsd2 in monitor mode unless `wl1_chanspec=="0"` |
| Web UI / SOAP handlers | MR70 `usr/sbin/httpd` | `wireless.cgi` `FUN_000d8818` writes only `wlg_channel`; SOAP `FUN_000a07c4` → `sa_set5GWirelessMode` `FUN_0008f8b0` writes `wlg_mode` |
| NVRAM access & defaults | `usr/lib/libacos_shared.so` (`acosNvramConfig_get/set/match`), `bin/acos_nvram` | decode default tables with `tools/nvram_defaults.py` (ACOS-specific struct tables; REA's string tools show keys but not key→value pairs) |
| Web UI pages | MR70/MS70 `www/*.htm` | `WLG_wireless2.htm` (Wireless Setup), `debug.htm` → `debug_frame.htm` (`newdebug.cgi`, `bh_opt.cgi`); `<%NNN%>` placeholders are filled by httpd |

Interface naming: `wl0` = 2.4 GHz, `wl1` = 5 GHz (shared fronthaul + backhaul); router backhaul BSS `wl1.1`, satellite backhaul STA `wl1.2`.

## Recording evidence (this repo's convention)
- Every claim in `FINDINGS.md` cites the binary path + `FUN_000xxxxx` (or NVRAM key/value, or web page + line). Mark it **verified (code)** or **inferred**. If new evidence contradicts an existing claim, correct the claim. Don't leave both versions.
- Keep raw pseudocode and REA outputs in `analysis/` (gitignored). Quote only the few lines needed as evidence; the code is Netgear's proprietary material.
- Never write credential values found in the firmware (`http_passwd`, `wl*_wpa_psk`, WPS PINs, …). Refer to keys by name.
- Don't run extracted binaries (no emulation) unless the owner asks.
