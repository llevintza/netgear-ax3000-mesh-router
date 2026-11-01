# MR70 / MS70 satellite backhaul drops: firmware findings

Firmware analyzed: **1.0.5.50_2.0.70** (2026-09-29), MR70 and MS70, extracted with REA 6.8.0 (`rea extract-firmware`).
Paths below are relative to `extracted/<MODEL>/selected.bin_extract/`.

Status (2026-11-01): static analysis done; `acos_agent`, `acsd2`, `wbd_slave`, `wbd_master`, `httpd` and `libwlanUtil` decompiled (Ghidra 12.1.4 via REA). **Live data from the units is still needed** to confirm the trigger (DFS radar vs. weak signal); see §8 and HOME-GUIDE.md. "Verified" = read in decompiled code or page source; "inferred" = not proven.

## 1. Platform: Broadcom, dual-band mesh with a shared 5 GHz backhaul
- SoC **Broadcom BCM6756**, BCA SDK 5.04L.02p1 (FIT header in the `.chk`; `Lflash=nand;chip=6756`).
- Mesh stack: Broadcom **Wi-Fi Blanket** (`usr/sbin/wbd_master` on the router, `usr/sbin/wbd_slave` on the satellite) over **IEEE 1905 / EasyMesh** (`usr/sbin/ieee1905`). Netgear's satellite supervisor is `usr/sbin/acos_agent`.
- **Dual-band mesh**: the backhaul runs on the same 5 GHz radio as the clients. Base backhaul BSS is `wl1.1`, satellite backhaul STA is `wl1.2` (`usr/sbin/acos_wl_dbg.sh`, "dual band mesh" branch). Anything that disturbs 5 GHz breaks the backhaul **and** 5 GHz clients at the same time.

## 2. What the red LED means
`usr/sbin/acos_agent` (MS70) owns the satellite LED (`shared_lib_set_led`, nvram `satellite_internet_led`), and it **pings the base router**:
- `ping base %s failed count %d` → `acos_agent off the led ping timeout`
- `failed to get the ip address of base and over the threshold!!` → `acos_agent off the led can't find the base`
- `****Backhaul connection changed, current link status: %d` (`wifi_backhaul` / `wired_backhaul`, `check_satellite_uplink_conn`)
- A recovery path, `acos_agent off the led restart`, plus `ethctl eth0 phy-power down/up`.

→ **Red = the satellite can't reach the router's IP over the backhaul** (ping failures past a threshold), not simply "weak signal".

### Decompiled behavior (Ghidra 12.1.4 via `rea decompile-all`; `analysis/decompiled/acos_agent_MS70/functions/`)
Supervisor loop `FUN_00012a3c` ("satellite"), **one cycle every 5 s**, after a 40 s boot delay (`sleep(0x28)`):

| State | Meaning | Transition |
|---|---|---|
| 0 | wait for controller AL-MAC (`multiap_almac`) | → 1 when known |
| 1 | wait for EasyMesh onboarding (`map_agent_configured=1`) | → 2 |
| 2 | **connected** (LED normal) | link check `FUN_0001251c`; if `wl1` is down → 3 *immediately* ("off the led wifi is down"); else ping check |
| 3 | **disconnected** (`satellite_internet_led=0`, LED red) | back to 2 after the ping check succeeds |

Ping check `FUN_00012064` (`check_satellite_connection`):
- Runs `ping -W 5 -c 3 -i 0.1 <router-ip> > /tmp/ping_result &` every cycle and reads the result on the next cycle.
- 0/3 replies = failure. Failures are counted (`DAT_00027178`); on the **5th consecutive failure** (counter > 3) in state 2 → *"ping timeout, set the satellite to disconnect"* → state 3. **About 25 s of no reachability = red.**
- Recovery: **2 consecutive successful cycles** (`DAT_0002717c`) → `satellite_internet_led=1`, `shared_lib_set_led(1,"acos_agent",2)` → LED normal (about 10 s).

Wi-Fi link check `FUN_0001251c` (`check_satellite_uplink_conn`), when the 5 GHz backhaul interface **`wl1` goes down**:
- *Releases the DHCP lease*, sets `br0` to the fallback **192.168.1.250/24**, then renews DHCP, and returns 3 (disconnected).
- So every backhaul blip also costs the satellite its IP lease, and recovery needs association, DHCP and 2 good ping cycles. A short radio interruption becomes a much longer outage on the LED and for management.
- When onboarding completes (`map_agent_configured` → 1) on a wireless uplink, it **power-cycles the satellite's Ethernet port for 5 s** (`ethctl eth0 phy-power down/up`). Wired clients on a satellite get a link drop every time the satellite re-joins.


## 3. What happens to clients when the backhaul drops
`usr/sbin/wbd_slave` (MS70), verified:
- **Controller search limit:** `wbd_ap_config_search_thld` (default **5**, `FUN_0001696c`). On the 6th unanswered AP-autoconfiguration search, `FUN_00062f70` blocks: it puts a MAC deny filter on the satellite's own backhaul BSS (`FUN_0001def8`) **and turns off all fronthaul BSSes** (`FUN_0001eb94`), so clients lose Wi-Fi. A controller reply undoes both and resets the count (`FUN_000648c0`).
  - The search interval comes from `ieee1905` (`FUN_0008d1b0`): 60 s, 5 s or 1 s depending on flags. Inferred: the satellite uses the 5 s path, so blocking starts about **30 s** after the router is lost.
- **"Controller device … removed. Blocking backhaul BSS"** (`FUN_000632f4`): fires when ieee1905 drops the router from its topology after no 1905 traffic for the discovery interval + 2 s, capped at **62 s** (`FUN_0002b5e4`, `FUN_00029448`).
- **Order of events:** the LED goes red at ~25 s (§2), then satellite clients lose Wi-Fi at ~30–62 s. Both recover once the router is reachable again.

## 4. 5 GHz runs at 160 MHz and always includes DFS channels (prime suspect)

> **Correction (2026-11-01).** An earlier version of this section blamed automatic channel selection (`acsd2`, `wl1_acs_dfs=2`, …) for picking DFS channels, and recommended pinning channel 36–48. **That mechanism was wrong**, and pinning a channel alone does **not** avoid DFS. Details below.

**Factory setting (verified):**
- `bin/acos_nvram` sets `wlg_mode=HT160` and `wlg_channel=44`, and the NA SKU forces channel 44 (`read_board_data_rc`, acos_service `FUN_00015bd4`).
- `lib/libwlanUtil.so` `set_wirelss_5g_1_channel` builds `wl1_chanspec = "<wlg_channel>/160"`, and `set_wirelss_5g_1_mode` sets `wl1_bw_cap=15` for HT160.
- So the 5 GHz radio runs **44/160**, a block covering channels **36–64**. **52–64 are DFS channels**, so radar detection is active on that block at all times (`wl1_reg_mode=h`; FCC radar thresholds are set by `shared_project_dep_configure_radar_dfs`).
- A radar hit, real or false, forces the radio off the block. The backhaul and all 5 GHz clients drop together (§1), and channel availability checks can keep it down for 60 s or more.

**Channel picking isn't involved (verified, MR70 `usr/sbin/acsd2`):**
- acsd2 runs auto mode only when `wl1_chanspec` is exactly `"0"` (`FUN_0002cc70` → `FUN_00029be8`). With `"44/160"` it runs in **monitor mode**: its main loop skips the interface (`FUN_00013170`), and on radar it only logs (`FUN_0002f754`). The Wi-Fi driver picks the new channel.
- So the `wl1_acs_*` defaults (`acs_dfs=2`, `acs_dfs_reentry`, `acs_bgdfs_enab`, …) **don't apply** in normal operation. `acs_dfs_reentry` isn't even used by the binary.

**What the web interface can and can't do (verified, `www/WLG_wireless2.htm`, httpd):**
- ADVANCED → Setup → Wireless Setup has a 5 GHz channel field `w_channel_an`. `wireless.cgi` (`FUN_000d8818`) writes **only `wlg_channel`**.
- There is **no Auto** option for 5 GHz (commented out, lines 359–368), **no width/mode selector** (httpd never parses `opmode_an`), and no DFS toggle.
- In HT160 mode the list offers 36–64 and 100–128 only. Every 160 MHz block there contains DFS channels, and no 149+ is offered.
- → **Through the web interface the radio can't be moved off DFS spectrum.** Picking 36/40/44/48 at HT160 still uses the 36–64 block.

**The width can only be changed outside the web pages (verified code path, untested on hardware):**
- SOAP `WLANConfiguration_Set5GWLANWPAPSKByPassphrase` (httpd `FUN_000a07c4`, the API the Nighthawk app uses) takes `NewWirelessMode`. It calls `sa_set5GWirelessMode` (`FUN_0008f8b0`, index 1), which maps the 80 MHz option string to **`wlg_mode=HT80`**.
- The same call also carries the SSID, security type and Wi-Fi passphrase. Whether the Nighthawk app exposes a mode choice is unverified.
- During *app setup*, httpd resets `wlg_mode` to HT160 (`FUN_0008821c`).

**Satellites (verified code, behavior unconfirmed live):**
- MS70 `libwlanUtil.so` `cb_satallite_wl1_chanspec` (`0x28f98`, in the mesh-sync table) forces the satellite's `wl1_chanspec` to **`"<router wlg_channel>/160"`** (or `"44/160"`), ignoring the router's width.
- If that holds at runtime, a satellite keeps detecting radar on 36–64 even when the router is at 80 MHz.
- **Must be checked live after any width change:** look at the satellite's own Router Status "5G Channel" row.

## 5. Weak-backhaul policy (router → satellites)
`wbd_weak_sta_cfg_bh = "1000 -75 3 50 200 0x0004"` (verified, `wbd_retrieve_backhaul_nvram_config` in libwbdshared; flag bits in libshared `wbd_weak_sta_identification`):
- Fields: idle rate 1000, **RSSI -75 dBm**, hysteresis 3 dB, PHY rate 50, TX failures 200, flags 0x4.
- Flags 0x4 = **RSSI rule only**; the other fields are ignored.
- **Action:** a weak report to the router, which tries a backhaul **steering** request to another node (`wbd_bh_opt_try_on_weak`, default 2). It's **not a disconnect**.
- With `map_no_multihop=0` (daisy-chaining allowed), a satellite hovering near -75 dBm can be steered between the router and the other satellite, causing extra short outages.
- → Aim for a backhaul RSSI better than about **-70 dBm**. The web interface shows **no RSSI** (Attached Devices "Backhaul Status" is the fixed string `"Good"`, httpd `FUN_0005d8ec`).

## 6. BH optimization: low value for this problem
Verified chain: `bh_opt.cgi` → `mesh_service enable_bhopt` → `wb_cli -m bhopt -d 0` → wbd_master `FUN_0002488c`, then a 10 s timer → `FUN_0001d3ec`.
- **What it does:** for each satellite it compares other loop-free backhaul parents (hop count, PHY rate) and sends 1905 steering requests (up to `wbd_bh_opt_try=3` tries, with bounce detection).
- **Side effects:** it causes deliberate reconnects (the page warns about this). Its enable flag stays on until reboot, and while on, optimization re-runs whenever a satellite reassociates (`FUN_000443a4`, `FUN_00045168`).
- → It doesn't address radar/DFS. Use it once at most after moving a satellite, then reboot the router.

## 7. Diagnostics and logs
- **`http://<unit>/debug.htm`** (frame around `www/debug_frame.htm`): WBD Log Capture, BH Management Log Capture, Start Capture (System Memory), **Save Debug Log** → `Debug_log.zip`.
  - Ticks post to `newdebug.cgi` and **persist across reboots**. No telnet toggle.
  - **The router and each satellite have their own `debug.htm`;** the router's zip does **not** include satellite logs.
- **What's in `Debug_log.zip`** (verified, the httpd `zip -l Debug_log.zip …` command):
  - `syslogd.txt` (logread): acos_agent lines, plus WBD lines only when `wbd_syslogd_output=1`, which the WBD checkbox appears to set (inferred).
  - `dmesg.txt` and `kmsg_con.txt`: acos_agent's `/dev/kmsg` LED messages with `date` stamps.
  - `info.txt` / `Console-log*`: periodic `wl` dumps.
  - It also bundles packet captures, `nvram.zip` and `backup.cfg`, which can contain credentials, so **keep the zips private** (`logs/` is gitignored).
- **Not in any log:** `acsd2` messages go to the console only, so radar evidence comes from the **WBD** lines (`RADAR DETECTED`, `AP_CHAN_CHANGE`).
- **Analyzer:** `python3 -I tools/analyze_logs.py logs/*.zip` builds a classified incident timeline with a verdict: DFS/radar, weak RSSI, non-radar channel change, link drop, controller unreachable while link up, or MIXED.
- **Router control:** `tools/netgear_router.py` covers status, debug-logs, capture start/save, set-5g-channel and bh-optimize. Changes are dry-run unless `--apply` is given. It has **not been tested on a live router.**

## 8. Recommended actions (in order)
1. **Collect evidence first.** Read status, enable WBD + BH Management capture on the router **and both satellites**, wait for a red event, save all three zips, and run the analyzer. The fix for DFS needs a non-web-interface change, so confirm radar is really the trigger before making it.
2. Make sure all units run **1.0.5.50_2.0.70** (satellites first).
3. **If the logs show radar/DFS:**
   - Lower the 5 GHz width to **80 MHz** and use channel **36/40/44/48** (non-DFS at 80 MHz). This isn't possible through the web interface (§4). Options:
     - (a) the Nighthawk app, if it offers a 5 GHz mode setting (unverified)
     - (b) the SOAP call in §4. Not implemented in `tools/netgear_router.py` yet, because it has to resend the SSID and passphrase.
   - Then **check the satellites' 5G Channel row.** If they stay at 160 MHz (§4), the only clean fix is **wired Ethernet backhaul**, which takes the satellites off the shared 5 GHz radio entirely.
   - Changing only the channel within 36–64 doesn't help.
4. **If the logs show a weak backhaul (RSSI < -75):** move the satellite closer (better than about -70 dBm), or use wired backhaul.
5. **If the logs show the router unreachable while the link is up:** look for interference or a router-side cause, and capture again with Wi-Fi debug enabled.
6. BH optimization: optional, once, after a placement change, then reboot the router (§6).

## 9. Open questions (need live data)
- Does the satellite actually stay at `/160` when the router is at HT80 (`cb_satallite_wl1_chanspec`)?
- Does the Nighthawk app expose the 5 GHz mode? Does `Set5GWLANWPAPSKByPassphrase` with an empty passphrase leave the Wi-Fi password unchanged?
- Is the router's current setting really the factory HT160/44 (`netgear_router.py status` shows `wlg_mode`)?
- Do the satellites accept the same admin login on their own `debug.htm`?
