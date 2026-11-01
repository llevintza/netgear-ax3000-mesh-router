# At-home guide: fix the satellite drops

The goal is to find out **why** the satellites lose their 5 GHz link to the router, then fix it. Background and evidence are in [FINDINGS.md](FINDINGS.md).

**Allow about 1 hour, plus 1–2 days of watching.** Do the steps in order. Each one ends with something to write down.

Before you start:
- Use the laptop, ideally **plugged into the router with Ethernet** or sitting next to it. Some steps reboot the Wi-Fi.
- Have the router admin password ready (the one you set at setup; routerlogin.net asks for it).
- **Do NOT factory-reset anything.** It wipes the mesh pairing and doesn't fix the cause.
- Firmware files are already downloaded in `firmware/` in this repo.

---

## Step 1: Take inventory (5 min)
1. Turn each satellite over and read the label. Write down the **model** (expected: **MS70**) and the last 4 characters of the serial.
   - If it says something other than MS70, **stop at this step** and note the exact model. You'll need firmware for that model instead. The firmware in `firmware/` is for MS70.
2. Note where each satellite is: which room, roughly how far from the router, and how many walls or floors are in between.
3. Note each unit's LED right now (white/blue = OK, red/amber = lost the router, off).

📝 Write down: models, locations, distances, LED colors.

## Step 2: Check firmware versions and the current 5 GHz channel (5 min)
1. Open **http://routerlogin.net** and log in.
2. Find the firmware versions: **ADVANCED → Administration → Router Update** (or the router status / attached satellites page). Note the router's and each satellite's version.
3. Find the current 5 GHz channel: **ADVANCED → Setup → Wireless Setup**, in the 5 GHz section (it may say Auto, with the current channel shown).
   - **Channels 52–144 are DFS channels.** These are the ones the firmware's default settings allow, and they cause drops when radar is detected.
   - 36, 40, 44, 48, 149, 153, 157, 161 and 165 are non-DFS.

📝 Write down: firmware versions; 5 GHz channel setting (Auto or fixed) and current channel number.

## Step 3: Start log capture *before* changing anything (5 min to set up)
This captures evidence of what happens during a red event, so we know whether the cause is radar/DFS or weak signal.

1. Go to **http://routerlogin.net/debug.htm** (same login).
2. Tick **WBD Log Capture**. That's the mesh daemon: logs radar events and the satellite being dropped. The page reloads when you tick it.
3. Tick **BH Management Log Capture**. That's the satellite supervisor: logs ping failures and the LED changes. The page reloads again.
4. Under **Debug Log Capture**, leave **Store location = System Memory**, then click **Start Capture**.
5. Leave it running until **a satellite goes red at least once** (up to about 1 hour, or longer if drops are rare).
   - Write down the **time** each red LED appears.
6. Back on `debug.htm`, click **Save Log**. That downloads `Debug_log.zip`.
7. Put the zip in **`logs/`** in this repo (`mkdir -p logs`). That folder is gitignored, because logs contain MAC addresses and network names.

> If drops are rare (less than once an hour), skip waiting: start the capture, continue with Step 4, and save the log later.

📝 Write down: times of red events; where you saved the zip.

## Step 4: Update firmware if needed (15–20 min)
Only if any unit is **not** on **1.0.5.50_2.0.70**.
1. **ADVANCED → Administration → Router Update → Manual Update.**
2. **Satellites first:** choose the satellite. A new page pops up. Upload `firmware/MS70-V1.0.5.50_2.0.70/MS70-V1.0.5.50_2.0.70.chk`. Repeat for the second satellite.
3. **Then the router:** upload `firmware/MR70-V1.0.5.50_2.0.70/MR70-V1.0.5.50_2.0.70.chk`.
4. Don't unplug anything during an update. Wait until all LEDs are steady again (a few minutes after the router reboots).

📝 Write down: new versions confirmed.

## Step 5: Pin 5 GHz to a non-DFS channel (5 min). This is the main fix.
1. **ADVANCED → Setup → Wireless Setup**, 5 GHz section.
2. Change the channel from **Auto** to **36** (or 40/44/48), then click **Apply**.
   - You only change this on the router. The satellites follow automatically, because they use the same 5 GHz radio for the backhaul.
3. Wi-Fi restarts. Wait 2–3 minutes until both satellites show a steady normal LED.
   - Expect the satellite LED to stay non-red for at least ~40 s after boot. The satellite software waits 40 s before checking.

📝 Write down: time of the change, new channel.

## Step 6: Run backhaul optimization (5 min)
1. Open **http://routerlogin.net/debug.htm** again.
2. Under **BH Optimization Management**, click **BH optimization** once. It greys out while it runs.
3. Wait about 5 minutes. The mesh may briefly re-link the satellites (direct to the router, or through the other satellite, whichever is better).

## Step 7: Check signal and placement (10 min)
The router treats a satellite link weaker than about **-75 dBm** as weak. Aim for **-70 dBm or better**.
1. Quick proxy with the Mac: stand next to each satellite, hold **Option** and click the Wi-Fi icon in the menu bar, and check **RSSI** while connected near that satellite. Then do the same **halfway between the satellite and the router**.
2. If a satellite is far from the router (more than 2 walls, a floor, or long distance), move it **closer to the router**, about halfway between the router and the area you need covered, ideally in the open and up high.
3. If one satellite can't get a good signal anywhere useful: run an **Ethernet cable** from the router (or a switch) to that satellite. The firmware supports wired backhaul and switches to it automatically.

📝 Write down: any moves made, approximate RSSI readings.

## Step 8: Watch for 1–2 days
- Glance at the satellite LEDs a few times a day. Note any red events with times.
- Expect **no red** if DFS was the cause. Brief red right after a reboot or a settings change is normal.
- If you see red again:
  1. Start a new capture on `debug.htm` (Steps 3.4–3.7). The log checkboxes stay ticked.
  2. Save `Debug_log.zip` into `logs/` with the date in the name, e.g. `logs/Debug_log-2026-11-03.zip`.

## Step 9: Send results back
Open this repo with your coding agent (or a person helping you) and share:
- your notes from Steps 1–8 (models, versions, channel before/after, red-event times, RSSI, moves)
- the log zip(s) in `logs/`

The logs get read against the decompiled firmware behavior in FINDINGS.md. What to look for:
- `RADAR DETECTED` / `AP_CHAN_CHANGE` → DFS was the cause (should stop after Step 5).
- `ping base … failed count` without a link drop → the router is unreachable even though Wi-Fi is up (look at interference or the router itself).
- `Blocking backhaul BSS` / `wifi is down` / `Backhaul connection changed` → the radio link itself is dropping (signal/placement → Step 7, or wired backhaul).

## Rollback
- To undo the channel change: set 5 GHz back to **Auto** in Wireless Setup.
- To stop debug logging: untick the two boxes on `debug.htm`. Logging in System Memory is cleared on reboot.
