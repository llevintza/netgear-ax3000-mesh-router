# MR70 / MS70 satellite backhaul drops: firmware findings

Firmware analyzed: **1.0.5.50_2.0.70** (2026-09-29), MR70 and MS70, extracted with REA 6.8.0 (`rea extract-firmware`).
Paths below are relative to `extracted/<MODEL>/selected.bin_extract/`.

Status: static analysis (strings, NVRAM default tables, scripts) done; `acos_agent` (MS70) decompiled with Ghidra. Live logs from the units are still needed to confirm the root cause (DFS vs. signal).

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
`usr/sbin/wbd_slave` (MS70):
- `Controller device … removed. Blocking backhaul BSS`
- `AP-Autoconfiguration search count %d exceeds threshold of %d. Assuming controller not reachable and blocking backhaul BSS`
- `Blocking Backhaul bss and disabling fronthaul bss on bootup. They will be restored when controller is detected`

→ When the satellite loses the router (the "controller"), it **tears down its own networks** until it finds the router again. Clients on that satellite see disconnects, then a reconnect. This matches the reported symptom.

## 4. 5 GHz channel defaults favor DFS channels (prime suspect)
Recovered from the compiled NVRAM default tables in `bin/acos_nvram` (identical on MR70 and MS70; regenerate full dumps with `python3 -I tools/nvram_defaults.py extracted/<MODEL>/selected.bin_extract/bin/acos_nvram` (kept out of git: they contain vendor default passwords/PSKs/WPS PINs)):

| NVRAM key | Default | Meaning |
|---|---|---|
| `wl1_chanspec` / `wl1_channel` | `0` / `0` | 5 GHz channel = **auto** (acsd2) |
| `wl1_acs_dfs` | `2` | ACS **may select DFS channels** |
| `wl1_acs_start_on_nondfs` | `0` | No requirement to start on a non-DFS channel |
| `wl1_acs_dfs_reentry` | `1` | ACS moves back **into** DFS channels |
| `wl1_acs_bgdfs_enab` | `1` | Background DFS (zero-wait DFS) enabled |
| `wl1_acs_dfsr_immediate` / `_deferred` | `300 3` / `604800 5` | DFS re-entry timers |
| `wl1_reg_mode` | `h` | 802.11h, so radar detection is active |
| `wl1_acs_excl_chans` | *(empty)* | No channels excluded |

`wbd_slave` logs `RADAR DETECTED, current chanspec … target chanspec` and handles `AP_CHAN_CHANGE`. On a DFS channel, a radar hit (real or false) forces the router to vacate the channel. The backhaul then has to follow, and channel availability checks (60 s, or up to 10 min on weather-radar channels 120–128) can leave the satellite without a backhaul. That produces exactly the white→red→drops pattern.

## 5. Backhaul quality thresholds (router side, `wbd_master` policy)
| Key | Default | Notes |
|---|---|---|
| `wbd_weak_sta_cfg_bh` | `1000 -75 3 50 200 0x0004` | backhaul STA considered **weak at RSSI < -75 dBm** |
| `wbd_tbss_thld_5g` | `-72 10 30 36 0x7F 0` | target-BSS threshold -72 dBm on 5 GHz |
| `wbd_bh_opt` / `wbd_bh_opt_try` | `0` / `3` | backhaul optimization off by default, 3 tries |
| `map_no_multihop` | `0` | daisy-chain (satellite→satellite) allowed |

→ Satellites need roughly **better than -70 dBm** to the router (or to the upstream satellite) to stay out of the weak zone.

## 6. Built-in diagnostics we can use
`http://routerlogin.net/debug.htm` (`www/debug_frame.htm`): **WBD Log Capture**, **BH Management Log Capture** (`acos_agent_debug`), Wi-Fi/HAPD/steering debug, **Debug Log Capture** (with store location), and **BH Optimization** (`bh_opt.cgi`). No telnet toggle in this firmware.

## 7. Recommended actions (lowest risk first)
1. Make sure both satellites and the router run **1.0.5.50_2.0.70** (satellites first).
2. **Pin the 5 GHz channel to a non-DFS channel** (36/40/44/48, or 149–165 where allowed) in the Wireless settings. This takes radar and channel availability checks out of the picture. *Most likely fix.*
3. Run **BH Optimization** from `debug.htm` once all units are up.
4. Placement: aim for a satellite backhaul RSSI better than about -70 dBm, ideally with line of sight and halfway between router and dead zone. If one satellite stays weak, use **wired Ethernet backhaul** for it (`wired_backhaul` is supported by `acos_agent`).
5. If drops continue: enable **WBD Log Capture + BH Management Log Capture** in `debug.htm`, reproduce a red event, and check the logs for `RADAR DETECTED`, `Blocking backhaul BSS` or `ping base … failed`.
