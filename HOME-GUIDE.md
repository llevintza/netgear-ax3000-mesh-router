# At-home guide: fix the satellite drops

Goal: find out **why** the satellites lose their 5 GHz link to the router, with evidence, then apply the matching fix. Background: [FINDINGS.md](FINDINGS.md).

**Who does what.** A coding agent on your laptop drives the router and analyzes logs with the repo's tools. You only do what needs hands and eyes: labels, LEDs, moving units, cables, and approving changes. Each agent step has a **browser fallback**, because the tools haven't been tested on a live router yet.

> **Start the agent with:** "Open this repo, read AGENTS.md, and follow HOME-GUIDE.md using the `home-session` skill. Ask me before any change."

**Allow about 1–2 hours on day 1** (mostly waiting for a red event), then 1–2 days of watching.

## Before you start
- The laptop is on the home network (Wi-Fi is fine; Ethernet to the router is better for steps that restart Wi-Fi).
- Have the router admin password ready. Give it to the agent's shell as an environment variable for this session only: `export ROUTER_PASSWORD='…'`. Never put it in a file or a chat message that gets saved.
- **Don't factory-reset anything.** It wipes the mesh pairing, puts the 5 GHz mode back to HT160, and doesn't fix the cause.

---

## Step 1: You, physical inventory (5 min)
1. Read each satellite's label: the **model** (expected **MS70**) and the last 4 characters of the serial. If it's not MS70, stop and note the exact model; the analysis and firmware here are for MS70.
2. Note each satellite's room, rough distance to the router, and the walls or floors in between.
3. Note each unit's LED now (white/blue = OK, red = has lost the router).

## Step 2: Agent, baseline status (read-only, 5 min)
```bash
python3 -I tools/netgear_router.py status            # router
python3 -I tools/netgear_router.py status --json > logs/status-router-$(date +%F).json
```
Record from the output:
- **firmware versions** for the router and each satellite (target: 1.0.5.50_2.0.70)
- **`wlg_mode`**: expected **HT160** (factory). This is the key fact behind the DFS problem (FINDINGS §4).
- **configured channel** (expected 44) and the **in-use 5G Channel** row (at HT160 it lists the whole block, e.g. `36(P)+40+…+64`)
- the **satellite table**: IP address, 2.4/5 GHz or wired, connected to Router or Satellite

Then check each satellite with `--host <satellite-ip> status`. Whether the satellite accepts the same admin login is unverified. If it doesn't, use the browser.

**Browser fallback:** ADVANCED → Administration → **Router Status** (5G Channel row) and **Attached Devices** (Connected Satellite table). The version is in the page header. Note: the "Backhaul Status" column always says "Good"; it's a fixed label, not a measurement.

## Step 3: Agent, start log capture on all three units (5 min to set up)
The router's log doesn't include the satellites, and the satellite logs hold the LED and ping evidence. So capture on **every** unit:
```bash
python3 -I tools/netgear_router.py debug-logs enable               # dry run: shows the request
python3 -I tools/netgear_router.py --apply debug-logs enable
python3 -I tools/netgear_router.py --apply capture start
# repeat both with --host <satellite-1-ip> and --host <satellite-2-ip>
```
**Browser fallback:** open `http://routerlogin.net/debug.htm` (and `http://<satellite-ip>/debug.htm`), tick **WBD Log Capture** and **BH Management Log Capture** (the page reloads after each tick), keep Store location = **System Memory**, and click **Start Capture**.

**You:** leave everything running until **a satellite goes red at least once** (or ~1 hour). Write down the **time** each red LED appears. If drops are rare, carry on with Step 4 and come back to Step 5 later.

## Step 4: You + agent, firmware (only if any unit isn't on 1.0.5.50_2.0.70)
The tool doesn't upload firmware. Do this in the browser:
1. ADVANCED → Administration → **Router Update** → **Manual Update** tab.
2. **Satellites first:** click a satellite's row in the satellite table. Its own Router Update page opens in a **new tab** (allow pop-ups). Log in, choose `firmware/MS70-V1.0.5.50_2.0.70/MS70-V1.0.5.50_2.0.70.chk` → Upload. Repeat for the other satellite.
3. **Then the router:** on the Manual Update tab, Browse → `firmware/MR70-V1.0.5.50_2.0.70/MR70-V1.0.5.50_2.0.70.chk` → Upload.
4. Don't unplug anything. Wait until all LEDs are steady. Updating restarts the units, so restart the capture (Step 3) afterwards.

## Step 5: Agent, save logs and get a verdict (5 min)
```bash
python3 -I tools/netgear_router.py capture save -o logs/router-$(date +%F-%H%M).zip
python3 -I tools/netgear_router.py --host <sat-1-ip> capture save -o logs/sat1-$(date +%F-%H%M).zip
python3 -I tools/netgear_router.py --host <sat-2-ip> capture save -o logs/sat2-$(date +%F-%H%M).zip
python3 -I tools/analyze_logs.py logs/router-*.zip logs/sat1-*.zip logs/sat2-*.zip
```
**Browser fallback:** on each `debug.htm`, click **Save Debug Log** and move the `Debug_log.zip` files into `logs/`, renamed per unit. `logs/` is gitignored; the zips contain MACs, network names and config backups, so never commit or share them.

The agent compares the incident times with your red-LED times. The **VERDICT** line picks the branch in Step 6.

## Step 6: Fix, by verdict (agent proposes, you approve)
| Verdict | What to do |
|---|---|
| **DFS / radar** | The radio has to leave the DFS part of 5 GHz: **80 MHz width + channel 36/40/44/48**. The web interface **can't** change the width (FINDINGS §4), and the tool doesn't do it yet. **Stop here and decide together:** check whether the Nighthawk app offers a 5 GHz mode setting, or have the agent implement the SOAP call described in FINDINGS §4 (it must resend the SSID and passphrase, so review it first). After any change, re-run Step 2 and check that **the satellites' 5G Channel row is no longer a 36–64 block**. If the satellites stay at 160 MHz, the robust fix is **wired Ethernet backhaul**. |
| **Weak signal / RSSI** | You: move that satellite closer to the router (halfway between the router and the area to cover, in the open, up high), aiming for better than about -70 dBm. Or run an Ethernet cable to it; wired backhaul is detected automatically. Optional afterwards: `--apply bh-optimize` once, then reboot the router (FINDINGS §6). |
| **Controller unreachable while link up** | Not radio-related. The agent re-captures with Wi-Fi debug enabled and looks for router-side causes. Check that nothing like a switch or loop sits between units. |
| **MIXED / INCONCLUSIVE** | Capture longer (more red events), on all three units, then analyze again. |

> **Don't bother changing only the 5 GHz channel at HT160.** Every channel offered in that mode is in a 160 MHz block that contains DFS channels (FINDINGS §4). `set-5g-channel` warns about this.

## Step 7: Watch for 1–2 days
- You: glance at the LEDs a few times a day and note any red events with times. Brief red right after a reboot or change is normal (the satellite waits 40 s after boot before checking).
- If red again: repeat Steps 3 and 5 (the log ticks stay set across reboots) and re-run the analyzer on the new zips.

## Rollback
- **Channel:** set it back to the value recorded in Step 2 (factory 44). There's no "Auto" for 5 GHz on this router.
- **Logging:** `--apply debug-logs disable` on each unit, or untick both boxes on `debug.htm`. The ticks persist across reboots until removed.
- **BH optimization:** reboot the router; its enable flag stays on until reboot.
- **Width (if changed):** set the 5 GHz mode back to HT160 the same way it was changed.
