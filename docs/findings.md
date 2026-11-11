# MR70 / MS70 satellite backhaul drops: firmware findings

Firmware analyzed: **1.0.5.50_2.0.70** (2026-09-29), MR70 and MS70, extracted with REA 6.8.0 (`rea extract-firmware`).
Paths below are relative to `extracted/<MODEL>/selected.bin_extract/`.

Status (2026-11-01): static analysis done; `acos_agent`, `acsd2`, `wbd_slave`, `wbd_master`, `httpd` and `libwlanUtil` decompiled (Ghidra 12.1.4 via REA). **Resolved on a real system:** the trigger there was a satellite firmware mismatch, not DFS (§10, full write-up in [case-study-2026-11.md](case-study-2026-11.md)). §2–§6 still describe how the firmware behaves and remain relevant for other homes. "Verified" = read in decompiled code or page source; "inferred" = not proven.

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

## 4. 5 GHz runs at 160 MHz and always includes DFS channels (latent risk)

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
  - Ticks post to `newdebug.cgi` and **persist across reboots**.
  - Satellites (MS70) have no `debug_frame.htm`: `debug.htm` holds the forms directly, plus satellite-only controls (`reset_bh_bssid`, an **Enable Telnet** control in form 3).
  - **Correction:** an earlier version said "no telnet toggle". That's true for the router's `debug_frame.htm`. But the MS70 `www/debug.htm` has an **Enable Telnet** checkbox (`action_Enable_Telnet`, line 354), and both rootfs ship `usr/sbin/telnetenabled` and `usr/sbin/utelnetd`. It is unexplored and was never used here (roadmap item). An open telnet shell on a LAN is a security risk, so leave it off.
  - **The router and each satellite have their own `debug.htm`;** the router's zip does **not** include satellite logs.
- **What's in `Debug_log.zip`** (verified, the httpd `zip -l Debug_log.zip …` command):
  - `syslogd.txt` (logread): acos_agent lines, plus WBD lines only when `wbd_syslogd_output=1`, which the WBD checkbox appears to set (inferred).
  - `dmesg.txt` and `kmsg_con.txt`: acos_agent's `/dev/kmsg` LED messages with `date` stamps.
  - `info.txt` / `Console-log*`: periodic `wl` dumps.
  - It also bundles packet captures, `nvram.zip` and `backup.cfg`, which can contain credentials, so **keep the zips private** (`logs/` is gitignored).
- **Not in any log:** `acsd2` messages go to the console only, so radar evidence comes from the **WBD** lines (`RADAR DETECTED`, `AP_CHAN_CHANGE`).
- **Analyzer:** `python3 -I tools/analyze_logs.py logs/*.zip` builds a classified incident timeline with a verdict: DFS/radar, weak RSSI, non-radar channel change, link drop, controller unreachable while link up, or MIXED.
- **Router control:** `tools/netgear_router.py` covers status, debug-logs, capture start/save, set-5g-channel and bh-optimize. Changes are dry-run unless `--apply` is given.
  - Tested live on MR70 and MS70 1.0.5.50 (and MS70 1.0.1.22): `status`, `debug-logs`, `capture start/save`.
  - `set-5g-channel` and `bh-optimize` have only been dry-run.
  - The satellite `status` parsing is incomplete (no `top.htm`; 5G rows are inside HTML comments).

## 8. Recommended actions (in order)
1. **Collect evidence first.** Read status, enable WBD + BH Management capture on the router **and both satellites**, wait for a red event, save all three zips, and run the analyzer. The fix for DFS needs a non-web-interface change, so confirm radar is really the trigger before making it.
2. Make sure all units run **1.0.5.50_2.0.70** (satellites first). **Check each satellite's own `currentsetting.htm`**, since the router can show a blank version. In this home, a satellite firmware mismatch was the actual root cause (§10).
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
- ~~Is the router's current setting really the factory HT160/44?~~ **Answered (§10):** yes, `wlg_mode=HT160`, `wlg_channel=44`.
- ~~Do the satellites accept the same admin login on their own `debug.htm`?~~ **Answered (§10):** only after the satellites run the same firmware as the router.

## 10. Live session 2026-11-01: root cause was a satellite firmware mismatch
Narrative and step-by-step: [case-study-2026-11.md](case-study-2026-11.md). Evidence: `tools/netgear_router.py status` / `capture save` on all three units, `tools/analyze_logs.py`, and a 5 s ping monitor. Raw files are in gitignored `logs/`.

**Before (router 1.0.5.50_2.0.70, both satellites V1.0.1.22_2.0.47):**
- The firmware versions came from each unit's unauthenticated `currentsetting.htm`. The router's satellite table and Router Update page showed a **blank** satellite version, so the mismatch wasn't visible there.
- Board IDs (from `currentsetting.htm` and the `.chk` headers): the MR70 is `U12H414T02_NETGEAR` and the MS70 is `U12H414T20_NETGEAR`.
- Both satellites logged `AP-Autoconfiguration search count N exceeds threshold of 5 … blocking backhaul BSS` every 5 s. This is wbd_slave's `wbd_ap_config_search_thld=5` path (`FUN_0001696c` → `FUN_00062f70`): the old agent never completed EasyMesh autoconfiguration with the newer controller.
- One satellite's crash record held a kernel NULL-pointer dereference in `wl1-kthrd` (`wlc_ratesel_set_link_bw` / `wlc_scb_ratesel_init`, closed `wl` driver).
- There were **no radar/DFS lines** in any log, and the analyzer's verdict was LINK DROP WITHOUT RADAR.
- The router was configured HT160/44 but actually ran **channel 161 at 80 MHz**, and the satellites followed 161. The cause of that move isn't in the logs (inferred: an earlier channel change that predates the capture).
- Satellite web UI: login landed on `IA_hijack.htm` ("Your Satellite is not connecting to the network"). There was no `debug_frame.htm`; `debug.htm` holds the form directly. The satellites accepted the **factory default admin login**, not the router's password.
- Satellite clients appeared as attached to the router, not to the satellite.

**Updating the satellites:**
- A manual upload of the MS70 1.0.5.50 `.chk` on a satellite's own hidden `UPG_upgrade.htm` (`upgrade_check.cgi`) was **rejected** ("This firmware file is incorrect"), even though the board ID matches. The satellite's `httpd_mt` log records the upload but no reason.
- The owner then updated all three units successfully. Which route worked isn't recorded yet; the release notes' route is ADVANCED → Administration → Router Update → Manual Update → satellite row → popup, satellites first, then the router.

**After (all three on 1.0.5.50_2.0.70):**
- All LEDs are solid blue, there's no `IA_hijack` page, and satellite clients now show as attached to their satellite.
- **0** autoconfig-threshold lines and **0** `wl` panics on either satellite. The only "oops/NULL" hits are harmless kernel messages (`oopsWriterDoIoctl` timezone, `bsd` setitimer).
- The satellites now accept the **router's admin password**. The default credential is gone (inferred: synced from the controller).
- All three units are on **44/160** ("Up to 2400 Mbps"). So the radio now spans DFS 52–64 again (§4), and DFS remains a latent risk; watch for `RADAR DETECTED` lines.
- The router's satellite table still lists only one satellite row. Its Router Update satellite list shows both satellites at V1.0.5.50.
- Backhaul metrics over an 11 min window (wbd `Ifname[wl1.1] … DWDS … RSSI[…] macThroughPutCapacity`):

  | Satellite | RSSI min / median / max | Samples below the −75 weak threshold | Median capacity |
  |---|---|---|---|
  | Satellite-1 | −78 / −76 / −68 dBm | 434 of 706 | 544 Mbps |
  | Satellite-2 | −58 / −56 / −54 dBm | 0 of 706 | 1921 Mbps |

  Satellite-1 sits just below the §5 weak threshold, so wbd_master keeps flagging it `weak=YES` and attempts steering. It didn't drop in that window. It's the candidate for relocation if drops recur.
- The satellites' internal `InternetConnectionStatus=Down` on `currentsetting.htm` is the same before and after, so it isn't a fault indicator for satellites.

**Lessons:**
- Check each satellite's firmware on its own `http://<satellite>/currentsetting.htm` (no login needed). The router's table can show a blank version.
- Don't use a satellite's own hidden upgrade page for a large version jump. It rejected the correct image.

## 11. Live session 2026-11-11: WAN DNS set to AdGuard DNS blocks tracker domains for every client
**Symptom:** some sites fail on every device on the mesh, with a "can't connect" / proxy error in the browser. Example: the Umami analytics dashboard (`cloud.umami.is`) and its collector (`gateway.umami.is`). The same sites work on mobile data or with public DNS. The backhaul was healthy (both satellites "Good" on Attached Devices), so this is unrelated to §1–§10.

**Cause (verified on the router's web UI, read-only):** BASIC → Internet → Internet Setup (`BAS_ether.htm`, posts to `ether.cgi`) → *Domain Name Server (DNS) Address* was set to **Use These DNS Servers**, with Primary `94.140.14.14` and Secondary `94.140.15.15`. These are **AdGuard DNS's public filtering resolvers** (ads and trackers blocked). Clients get the router as their DNS server via DHCP, and the router forwards to the configured servers, so the blocklist applies to the whole network. The router's own filtering (Armor / Security tile) was **not activated**. The blocking came only from this DNS setting.

**Evidence** (`dig` from a LAN client):

| Query | Via router | Via `94.140.14.14` directly | Via `1.1.1.1` |
|---|---|---|---|
| `cloud.umami.is`, `gateway.umami.is` | `0.0.0.0` | `0.0.0.0` | real addresses |
| `doubleclick.net`, `googleadservices.com` | `0.0.0.0` | `0.0.0.0` | real addresses |
| `example.com` | real addresses | real addresses | real addresses |

The router's `0.0.0.0` answers carry an EDNS **Extended DNS Error option (code 15), info-code 17 = "Filtered"** (RFC 8914). The upstream adds that marker; the router passes it through. That tells a blocklist apart from an outage or a firewall rule.

**How to tell quickly:** `dig +short <blocked-name> @<router-lan-ip>` returns `0.0.0.0`, while `dig +short <blocked-name> @1.1.1.1` returns real addresses. If so, look at Internet Setup's DNS fields before anything else.

**Options** (each is the owner's call: it changes filtering for every device):
- **Rollback to stock:** set *Get Automatically from ISP* and Apply. That's the firmware default; the ISP's resolvers get used.
- **Keep AdGuard, without filtering:** AdGuard's non-filtering resolvers are `94.140.14.140` / `94.140.14.141` (verified: `cloud.umami.is` resolves through them).
- **Keep filtering and allowlist specific names:** that needs a filtering service with a per-account allowlist (AdGuard DNS private server, NextDNS) or a local resolver (Pi-hole / AdGuard Home, #2). The free public AdGuard servers can't be allowlisted.
- **Per-browser bypass:** Chrome secure DNS (DoH) skips the router's DNS for that browser only. #23 tracks blocking that kind of bypass in custom firmware.

**Applying the change:** Apply on Internet Setup re-applies the WAN settings. The page set doesn't link it to the `DIG_reboot*.htm` wait pages, so it isn't expected to reboot the units (inferred, not traced through `httpd`'s `ether.cgi` handler). Expect a short internet interruption anyway, and don't apply during calls. Afterwards, flush client DNS caches (macOS: `sudo dscacheutil -flushcache; sudo killall -HUP mDNSResponder`).
