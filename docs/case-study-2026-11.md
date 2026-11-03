# Case study (Nov 2026): satellites dropping because of a firmware mismatch

A real troubleshooting session on one MR70 router + two MS70 satellites, driven by a coding agent with this repo's tools while the owner was at home. Device identifiers (MACs, network names, serials, LAN addresses, passwords) are deliberately left out; units are called **Router**, **Satellite-1** and **Satellite-2**, and `<router-ip>` / `<sat-ip>` stand for their LAN addresses.

**Result:** the satellites ran firmware **V1.0.1.22** while the router ran **1.0.5.50**. After updating everything to 1.0.5.50, the LEDs are solid blue, the satellites' "not connecting" page is gone, and clients attach to the satellites again. The evidence for every claim is in [findings.md §10](findings.md#10-live-session-2026-11-01-root-cause-was-a-satellite-firmware-mismatch).

## Symptoms reported
- Satellite LEDs went white → red, and clients near the satellites got slow speeds and drops.
- Logging in to a satellite's web page showed **"Your Satellite is not connecting to the network"** (`IA_hijack.htm`).
- In the router's Attached Devices list, clients near the satellites showed up as connected to the router.

## What the agent did, step by step
Every state-changing step was shown as a dry run first and applied only after the owner approved it. The password was read from the OS keychain into an environment variable for each command and never printed, logged or committed.

### 1. Read-only baseline
1. `curl http://<unit-ip>/currentsetting.htm` on all three units. This page needs **no login** and prints `Firmware=`, `Model=` and `RegionTag=`:
   - Router: `V1.0.5.50`, MR70, board `U12H414T02_NETGEAR`.
   - Both satellites: **`V1.0.1.22`**, MS70, board `U12H414T20_NETGEAR`.
2. `python3 -I tools/netgear_router.py status` on the router:
   - Configured 5 GHz: `wlg_mode=HT160`, `wlg_channel=44` (factory).
   - **In use:** channel **161 at 80 MHz**, and the satellites followed 161.
   - The satellite table listed **only one** satellite, with a **blank** firmware version. So the version mismatch wasn't visible on the router.
3. The satellites rejected the router's admin password and accepted the **factory default admin login**. This is a sign they never received the mesh configuration.

### 2. Logs from every unit
1. With approval: `--apply debug-logs enable` and `--apply capture start` on the router and both satellites (`--host <sat-ip>`).
   - The satellite `debug.htm` differs from the router's (no `debug_frame.htm` frame). The tool was fixed to fall back to `debug.htm`, and tests were added.
2. `capture save` from all three, then `python3 -I tools/analyze_logs.py logs/*.zip`.
3. Findings:
   - Both satellites logged **`AP-Autoconfiguration search count N exceeds threshold of 5 … blocking backhaul BSS`** every 5 s. In the firmware (findings §3) that means the satellite never completed EasyMesh setup with the router. After 5 failed searches it blocks its own backhaul and switches off its client Wi-Fi.
   - One satellite had a kernel NULL-pointer crash in the 5 GHz driver thread (`wl1-kthrd`).
   - There were **no radar/DFS events**. Analyzer verdict: *LINK DROP WITHOUT RADAR*.
   - The weakest backhaul RSSI seen was about −75 dBm.
4. A 60-minute ping monitor (every 5 s) logged both satellites going down and up together for about 5 minutes. That window later turned out to be the update reboots.

**Diagnosis:** old satellite agent firmware (1.0.1.22) talking to a newer controller (1.0.5.50). The satellites kept failing EasyMesh autoconfiguration, so the radio itself wasn't the problem.

### 3. Firmware update
- The tool doesn't upload firmware; the owner did this in the browser.
- The firmware zips were downloaded from Netgear's support site and checked against SHA-256 sums (`tools/fetch-and-extract.sh`).
- The satellite web UI on 1.0.1.22 has **no Router Update menu**.
- **Attempt 1 failed:** the owner uploaded the MS70 1.0.5.50 `.chk` on the satellite's hidden `http://<sat-ip>/UPG_upgrade.htm`. The satellite said: *"This firmware file is incorrect!"*
  - The agent checked the file header: board ID `U12H414T20_NETGEAR`, which matches the satellite. So it wasn't the wrong file.
  - The satellite's own web log shows the upload arriving and being rejected about 2 s later, with no reason. Inferred: the old firmware's upload check rejects this image directly.
- **Attempt 2 succeeded:** the update through the **router's** update page, which also manages the satellites. The release notes' order is satellites first, then the router: ADVANCED → Administration → Router Update → Manual Update → choose the satellite → upload.
  - *(Which exact button the owner used isn't recorded.)*
- The units rebooted and resynced. The ping monitor showed both satellites dropping in and out together for ~5 minutes during this window.

### 4. Verification after the update (read-only)
| Check | Before | After |
|---|---|---|
| Firmware (`currentsetting.htm`) | Router 1.0.5.50, satellites 1.0.1.22 | All **1.0.5.50** |
| "Blocking backhaul BSS" log lines | every 5 s on both satellites | **0** |
| `wl1-kthrd` driver crash | present | **none** |
| Satellite web page | `IA_hijack.htm` "not connecting" | normal |
| Satellite admin login | factory default | **router's password** (synced) |
| Clients near satellites | listed on the router | listed on their satellite |
| LEDs | white → red | **solid blue** |
| 5 GHz (all units) | configured 44/160, running 161/80 | **44/160** ("Up to 2400 Mbps") |

A 6-hour ping monitor afterwards showed:
- the router up throughout
- Satellite-1: two short drops (about 20 s and 45 s)
- Satellite-2: one ~2.5-minute unstable period shortly after the update

That compares with repeated multi-minute drops before.

## Misconfigurations and oddities found
| # | Finding | Impact | Status |
|---|---|---|---|
| 1 | **Satellite firmware older than router** (1.0.1.22 vs 1.0.5.50), hidden by a blank version in the router's table | Root cause: EasyMesh autoconfig never completed → backhaul blocked, LED red | **Fixed** (updated) |
| 2 | Satellites still on the **factory default admin login** | Anyone on the LAN could log in to a satellite | **Fixed** by the update (satellites now use the router's password) |
| 3 | 5 GHz **configured 44/160 but running 161/80** | Configured and actual channels didn't match. Cause not in the logs (inferred: an earlier automatic move) | After the update, all units are on 44/160 |
| 4 | 44/160 always includes **DFS channels 52–64** (findings §4) | A radar hit would drop the backhaul and all 5 GHz clients | **Latent**: no radar seen; the web UI can't change the width |
| 5 | Satellite-1 backhaul about **−76 dBm**, just past the −75 dBm "weak" threshold (findings §5) | The router keeps flagging it as weak and trying to steer it; short drops possible | Open: move it closer if drops recur |
| 6 | Router's satellite table shows **one row** for two satellites | Cosmetic / UI. The update page lists both | Open |
| 7 | Debug log capture left enabled on all units | Logs in RAM, slight overhead; ticks survive reboots | Turn off with `--apply debug-logs disable` |

## Takeaways for other MR70/MS70 owners
1. **Check firmware parity first,** on each satellite itself: `http://<sat-ip>/currentsetting.htm`. Don't trust the router's satellite table.
2. Update satellites through the router's update flow. A satellite's own hidden upgrade page may reject a large version jump.
3. Look for `blocking backhaul BSS` in the satellite's `Debug_log.zip` (`tools/analyze_logs.py` classifies it). It means "can't talk to the controller", not "bad signal".
4. The playbook for doing all of this is [troubleshooting-playbook.md](troubleshooting-playbook.md).
