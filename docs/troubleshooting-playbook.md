# Troubleshooting playbook: MR70/MS70 satellites losing the backhaul

For anyone with a Netgear Nighthawk AX3000 mesh (MR70 router + MS70 satellites) whose satellite LEDs go white → red, or whose clients near a satellite get slow speeds and drops. Background: [findings.md](findings.md). A worked example: [case-study-2026-11.md](case-study-2026-11.md).

**Two ways to run it:**
- **By hand:** every step has a browser route.
- **With a coding agent:** an agent on your laptop runs the repo's tools and analyzes logs. Tell it: *"Read AGENTS.md and follow docs/troubleshooting-playbook.md with the `home-session` skill. Ask me before any change."* You do the physical parts (labels, LEDs, moving units, cables) and approve each change.

## Before you start
- Use a laptop on the mesh's own network. Ethernet to the router is best, because some steps restart Wi-Fi.
- Python 3 (stdlib only) for the tools. Docker isn't needed for this playbook.
- **Admin password:** give it to the tools only through the `ROUTER_PASSWORD` environment variable, or type it at the tool's prompt. For example, read it from your OS keychain inline: `ROUTER_PASSWORD="$(…)" python3 -I tools/netgear_router.py …`. Never put it in a file, a shell history line, an issue or a chat log.
- **Don't factory-reset.** It wipes the mesh pairing, resets 5 GHz to HT160, and usually doesn't fix the cause.
- Everything collected goes in `logs/` (gitignored). The `Debug_log.zip` files contain MAC addresses, network names and a config backup. **Never share or commit them.**

Find the satellites' LAN addresses in the router's **Attached Devices** page (Connected Satellites), or with `python3 -I tools/netgear_router.py status`.

---

## Step 0: Firmware parity (2 min, read-only) ← do this first
On **each unit**, open this page (no login needed):
```bash
curl -s http://<router-ip>/currentsetting.htm | grep -E '^(Firmware|Model)='
curl -s http://<satellite-ip>/currentsetting.htm | grep -E '^(Firmware|Model)='
```
- All units should report the **same** version (latest at the time of writing: **V1.0.5.50**).
- **Don't trust the router's satellite table.** It can show a blank satellite version while the satellite runs much older firmware.
- **Signs of a mismatch:**
  - Logging in to a satellite shows *"Your Satellite is not connecting to the network"*.
  - The satellite only accepts the factory default admin login, not the router's password.
  - Clients near a satellite appear as connected to the router.

**If versions differ, go to Step 4 (update) before anything else.** That was the whole fix in the case study.

## Step 1: Physical inventory (5 min)
1. Check each satellite's label model (expected **MS70**). This repo's analysis covers MR70/MS70 only.
2. Note each satellite's room, distance to the router, and the walls or floors in between.
3. Note each LED: white/blue = OK, red = lost the router.

## Step 2: Baseline status (read-only, 5 min)
```bash
python3 -I tools/netgear_router.py status
python3 -I tools/netgear_router.py status --json > logs/status-router-$(date +%F).json
```
Record:
- **`wlg_mode`**: factory is **HT160** (findings §4).
- **The configured channel** (factory 44) **and the channel actually in use** (the Router Status "5G Channel" row). They can differ, e.g. configured 44/160 but running 161/80.
- **The satellite table:** how each satellite connects (2.4/5 GHz or wired) and to which node.

**Browser route:** ADVANCED → Administration → **Router Status** (5G Channel row) and **Attached Devices**. The "Backhaul Status" column always says "Good"; it's a fixed label, not a measurement.

## Step 3: Start log capture on all units (5 min to set up)
The router's log doesn't include the satellites, and the satellites' logs hold the LED and ping evidence. Capture on **every** unit:
```bash
python3 -I tools/netgear_router.py debug-logs enable                 # dry run: shows the request
python3 -I tools/netgear_router.py --apply debug-logs enable
python3 -I tools/netgear_router.py --apply capture start
# repeat with --host <satellite-ip> for each satellite
```
**Browser route:** open `http://<unit-ip>/debug.htm`, tick **WBD Log Capture** and **BH Management Log Capture** (the page reloads after each tick), keep Store location = **System Memory**, then click **Start Capture**.

Leave it running until a satellite goes red at least once, or about an hour. Note the **time** of each red LED.

## Step 4: Update firmware (only if Step 0 found a mismatch or old firmware)
The tool doesn't upload firmware. Do this in the browser.
1. Download the MR70 and MS70 images from Netgear's support site. `tools/fetch-and-extract.sh` downloads and checks SHA-256 if you use the research setup.
2. On the **router**: ADVANCED → Administration → **Router Update**. Use **Check** or **Manual Update**, and pick the satellite from the satellite list there. **Satellites first, then the router** (Netgear's release notes).
3. Don't unplug anything. Wait until all LEDs are steady (several minutes; the satellites drop in and out while they reboot).
4. Re-run Step 0 on every unit.

> A satellite's own hidden `http://<satellite-ip>/UPG_upgrade.htm` rejected the correct MS70 image with *"This firmware file is incorrect"* when jumping from 1.0.1.22 to 1.0.5.50. Use the router's update flow.

## Step 5: Save logs and get a verdict (5 min)
```bash
python3 -I tools/netgear_router.py capture save -o logs/router-$(date +%F-%H%M).zip
python3 -I tools/netgear_router.py --host <sat-1-ip> capture save -o logs/sat1-$(date +%F-%H%M).zip
python3 -I tools/netgear_router.py --host <sat-2-ip> capture save -o logs/sat2-$(date +%F-%H%M).zip
python3 -I tools/analyze_logs.py logs/router-*.zip logs/sat1-*.zip logs/sat2-*.zip
```
**Browser route:** on each unit's `debug.htm`, click **Save Debug Log** and move the `Debug_log.zip` files into `logs/`, renamed per unit.

Compare the incident times with your red-LED times. The **VERDICT** line picks the row in Step 6.

## Step 6: Fix, by verdict
| Verdict / signal | What to do |
|---|---|
| `blocking backhaul BSS` / autoconfig threshold lines on a satellite | The satellite can't complete mesh setup with the router. **Check firmware parity (Step 0)** and update (Step 4). If versions match, use the satellite's **Sync** button near the router, then move it back. |
| **DFS / radar** | The radio has to leave DFS spectrum: **80 MHz width + channel 36/40/44/48**. The web UI **can't** change the width (findings §4), and the tool doesn't do it yet ([roadmap](roadmap.md)). Check whether the Nighthawk app offers a 5 GHz mode setting. If not, the robust fix is **wired Ethernet backhaul**. |
| **Weak signal / RSSI** (below about −75 dBm) | Move that satellite closer (halfway between the router and the area to cover, in the open, up high), aiming for better than about −70 dBm. Or wire it; wired backhaul is detected automatically. Optional afterwards: `--apply bh-optimize` once, then reboot the router (findings §6). |
| **Controller unreachable while link up** | Not radio-related. Re-capture with Wi-Fi debug enabled and look for router-side causes or a loop/switch between units. |
| **MIXED / INCONCLUSIVE** | Capture longer on all units, then analyze again. |

> **Changing only the 5 GHz channel at HT160 doesn't help.** Every channel the web UI offers in that mode sits in a 160 MHz block that includes DFS channels (findings §4). `set-5g-channel` warns about this.

## Step 7: Watch for 1–2 days
- Glance at the LEDs a few times a day and note any red events with times. A brief red right after a reboot is normal (the satellite waits 40 s after boot before checking).
- If one goes red again, repeat Step 5 (the log ticks stay set across reboots).
- Optional: a simple ping loop to each unit every 5 s logged to `logs/` gives an outage timeline to compare with the logs.

## Clean-up and rollback
- **Logging:** `--apply debug-logs disable` on each unit, or untick both boxes on `debug.htm`. The ticks persist across reboots until removed.
- **Channel:** set it back to the value recorded in Step 2 (factory 44). There's no "Auto" for 5 GHz on this router.
- **BH optimization:** reboot the router; its flag stays on until reboot.
- **Width (if changed):** set the 5 GHz mode back to HT160 the same way it was changed.
