#!/usr/bin/env python3
"""Classify MR70/MS70 Debug_log.zip captures into a backhaul-incident timeline + verdict.

Usage:
  python3 -I tools/analyze_logs.py logs/router/Debug_log.zip logs/sat1/Debug_log.zip
  python3 -I tools/analyze_logs.py --window 90 --json logs/*.zip > report.json
Inputs: Debug_log.zip files, extracted directories, or plain log files (any mix).
Stdlib only, Python >= 3.8. Zip members are read in memory; nothing is extracted or run.

What Debug_log.zip contains (firmware 1.0.5.50_2.0.70, evidence = usr/sbin/httpd strings):
  httpd runs `logread > /tmp/syslogd.txt`, `dmesg > /tmp/dmesg.txt`, then
  `cd /tmp; zip -l Debug_log.zip %s Console-log* ... dmesg.txt ... kmsg_con.txt ...
   /tmp/info.txt /tmp/info_old.txt /tmp/wltest_debug.txt ... syslogd.txt ...
   /tmp/wl_mesh_info.log /tmp/bcm_5g.log /tmp/bcm_2g.log /tmp/mapgetcfg_status
   /tmp/bootupmessages /tmp/bcm_wl.log /tmp/hapd_wl0_debug.log /tmp/hapd_wl1_debug.log ...`
  (plus pcaps BR/ETH/PPP.cap*, iptables, nvram.zip, backup.cfg, which are skipped here).
  - syslogd.txt  : BusyBox `logread` of `syslogd -C30720` (sbin/acos_service start_debug).
                   wbd_master/wbd_slave syslog(7, ...) here when nvram wbd_syslogd_output=1
                   (otherwise they printf to stdout = console, not captured); acos_agent
                   always syslog(7, "[acos_agent][%s %d] ...") (decompiled FUN_00012064).
  - kmsg_con.txt : `cat /proc/kmsg > /tmp/kmsg_con &` (acos_service start_debug), lines "<p>[uptime] ..."
  - dmesg.txt    : `dmesg` at save time, "[uptime] ..."; /tmp/bootupmessages = boot dmesg
                   (etc/init.d/save-dmesg.sh). acos_agent writes `date > /dev/kmsg` then
                   `echo "acos_agent off the led ..." > /dev/kmsg` (MS70 usr/sbin/acos_agent).
  - info.txt / Console-log*.txt : debug_logd / httpd command dumps (wl sta_info, date, uptime).
  Each unit has its own debug.htm (MS70 www/debug.htm also has Save Log -> Debug_log.zip);
  no firmware evidence that the router pulls satellite logs, so capture each satellite too.

Clocks (never mixed silently; every event carries its clock label):
  wbd_epoch  "Info: WBD-%s >> (%lu) %s: ..." -> %lu is time(NULL) (UTC epoch); confirmed in
             decompiled wbd_slave (analysis/decompiled/wbd_slave_MS70/functions/0x648c0.c).
  syslog     BusyBox "Mon dd HH:MM:SS host fac.prio tag: msg", device local time, no year.
             tz offset learned per file from lines carrying both syslog + WBD stamps.
  kmsg_date  `date` text written to /dev/kmsg, and "[YYYYmmdd HH:MM:SS][...]" echo markers
             (httpd/debug_logd/acos_service); used as wall anchors for kernel uptime.
  uptime     kernel "[secs.usec]"; mapped to wall only via an anchor in the same boot.
  debuglog   libacos_debug_log.so "[%d-%02d-%02d %02d:%02d:%02d.%ld] %s(%d): ".
  If a device clock is pre-2020 (no NTP) its events stay in their own "devclock" domain.

Pattern sources (format strings found with `strings` in extracted/<M>/selected.bin_extract/):
  usr/sbin/wbd_slave (MS70, also on MR70): RADAR DETECTED, AP_CHAN_CHANGE event, dfs_ap_move,
     CAC/ISM, Chanspec / TxPwr changed, Controller device ... removed. Blocking backhaul BSS,
     AP-Autoconfiguration search count, Backhaul STA interface %s assoicated, Link UP/DOWN
     Event, Disconnect backhaul STA, Found Weak STA (wbd_slave_is_backhaul_sta_weak),
     BSTA rssi/rssi_thld, Backhaul STA[..] is moving to BSSID, Joining SSID, bSTA roaming.
  usr/sbin/wbd_master (MR70): Setting radar detected, DFS status changed, CAC completion,
     ZWDFS, Send Backhaul STEER, For %sSTA ... is_sta_weak, backhaul optimization, Device got removed.
  usr/sbin/acos_agent (MS70): ping base %s failed count %d, ping timeout, set the satellite
     to disconnect, acos_agent off the led {ping timeout|can't find the base|wifi is down|restart},
     acos_agent light on the led, ****Backhaul connection changed, current link status: %d,
     ****Release/Renew DHCP lease!!, interface is not up..., MODULE_NAMEstate changed: %d -> %d.
  usr/sbin/acsd2 (MR70): ACSD >> ... Radar detected / Handling the radar event / moving to DFS
     channel / Selected Channel / Performing CSA; DFSR Switching ...; "acsd: %s: selected channel
     spec". NOTE: acsd2 only printf()s (no syslog import) -> normally NOT in Debug_log.zip.
  lib/modules/4.19.183/extra/wl.ko: "Type %d Radar Detection. ...", "FCC-5 Radar Detection."
  wl_mfgtest.ko only (absent from production wl.ko): "DFS: ... RADAR DETECTED ON CHANNEL",
     "DFS WLC_E_RADAR_DETECTED on ch ... going to ch", "%d second CAC time".
  usr/sbin/wpa_supplicant / hostapd: CTRL-EVENT-(DIS)CONNECTED, BEACON-LOSS, DFS-* events.
  Linux bridge "br0: port N(wl1.2) entered disabled state" and boot banners: generic kernel,
     not verified as strings in this firmware.
"""
import argparse
import datetime as dt
import io
import json
import os
import re
import statistics
import sys
import zipfile

MAC = r"[0-9a-fA-F]{2}(?::[0-9a-fA-F]{2}){5}"
CS = r"0x\s*[0-9a-fA-F]+"
MONTHS = {m: i + 1 for i, m in enumerate("Jan Feb Mar Apr May Jun Jul Aug Sep Oct Nov Dec".split())}
DEFAULT_BH_IFACES = ("wl1.1", "wl1.2", "wl2", "wl2.1")
SYNC_EPOCH = 1577836800  # 2020-01-01: older device clocks are treated as unsynced
MAX_MEMBER = 256 * 1024 * 1024
OUTAGE = ("BH_LINK_DOWN", "BH_BLOCKED", "SAT_DISCONNECT", "PING_FAIL")
NO_CHAIN = ("WEAK_CLIENT", "BH_RSSI", "MARKER")  # shown/counted but don't build incidents

S_SLAVE = "usr/sbin/wbd_slave"
S_MASTER = "MR70 usr/sbin/wbd_master"
S_AGENT = "MS70 usr/sbin/acos_agent"
S_ACSD = "MR70 usr/sbin/acsd2"
S_WL = "lib/modules/.../wl.ko"
S_WLMFG = "wl_mfgtest.ko (not in production wl.ko)"
S_WPAS = "usr/sbin/wpa_supplicant"
S_HAPD = "usr/sbin/hostapd"
S_HTTPD = "usr/sbin/httpd|debug_logd|sbin/acos_service (kmsg echo)"
S_KERNEL = "generic Linux kernel (unverified)"
S_SYSLOGD = "BusyBox syslogd (unverified)"

# (category, subtype, regex, source).  Category may be refined in _refine().
RULES = [
    # --- RADAR / DFS ---
    ("RADAR_DFS", "radar_detected", r"Band\[(?P<band>\d+)\] Ifname\[(?P<ifname>[^\]]*)\] RADAR DETECTED, current chanspec\[(?P<cur>%s)\], target chanspec\[(?P<tgt>%s)\]" % (CS, CS), S_SLAVE),
    ("RADAR_DFS", "radar_detected", r"dfs_ap_move RADAR DETECTED current cac state\[(?P<cac>\d+)\]", S_SLAVE),
    ("RADAR_DFS", "dfs_move", r"dfs_ap_move complete reason\[(?P<reason>[^\]]*)\] current cac state\[(?P<cac>\d+)\]", S_SLAVE),
    ("RADAR_DFS", "cac", r"FULL Time CAC started on (?P<mac>%s)\. received preism cac state change event on (?P<ifname>\S+)" % MAC, S_SLAVE),
    ("RADAR_DFS", "ism_started", r"ISM started for (?P<mac>%s)\. cac state \[(?P<cac>\d+)\] chanspec \[(?P<cur>%s)\]" % (MAC, CS), S_SLAVE),
    ("RADAR_DFS", "cac", r"Initiated CAC for \[(?P<mac>%s)\] for chanspec\[(?P<cur>[0-9a-fA-Fx]+)\] with method\[(?P<method>\d+)\] reason \[(?P<reason>\d+)\]" % MAC, S_SLAVE),
    ("RADAR_DFS", "cac", r"Ongoing CAC on opclass \[(?P<opclass>\d+)\] channel \[(?P<chan>\d+)\] cac_time remaining \[(?P<remain>\d+)\] seconds", S_SLAVE),
    ("RADAR_DFS", "cac_complete", r"CAC completion on Interface\[(?P<mac>%s)\] Opclass\[(?P<opclass>\d+)\] Channel\[(?P<chan>\d+)\] status \[(?P<status>\d+)\] radar pairs count \[(?P<radar_pairs>\d+)\]" % MAC, S_MASTER),
    ("RADAR_DFS", "radar_detected", r"Setting radar detected on channel \[(?P<chan>\d+)\] chanspec \[(?P<cur>%s)\]" % CS, S_MASTER),
    ("RADAR_DFS", "dfs_status", r"IFR\[(?P<mac>%s)\] DFS status changed old_flags\[(?P<old>[0-9a-fA-F]+)\] new_flags\[(?P<new>[0-9a-fA-F]+)\]" % MAC, S_MASTER),
    ("RADAR_DFS", "zwdfs", r"(?:Rcvd ZWDFS msg|Send ZWDFS MSG|Send vendor msg ZWDFS|Decode zwdfs message)\D*reason\[(?P<reason>\d+)\].*?cntrl_chan\[(?P<chan>\d+)\]", S_MASTER + "|" + S_SLAVE),
    ("RADAR_DFS", "radar_detected", r"ACSD >>.*Radar detected update acs status", S_ACSD),
    ("RADAR_DFS", "radar_detected", r"ACSD >>.*Handling the radar event (?P<reason>\d+)", S_ACSD),
    ("RADAR_DFS", "radar_detected", r"acs bgdfs chan (?P<cur>%s) ?is not radar free" % CS, S_ACSD),
    ("RADAR_DFS", "dfs_move", r"ACSD >>.*moving to DFS channel (?P<tgt>%s)" % CS, S_ACSD),
    ("RADAR_DFS", "dfs_reentry", r"Switching Channels for DFS Reentry", S_ACSD),
    ("RADAR_DFS", "radar_detected", r"Type (?P<type>\d+) Radar Detection\. Detected pulse index=", S_WL),
    ("RADAR_DFS", "radar_detected", r"FCC-5 Radar Detection\.", S_WL),
    ("RADAR_DFS", "radar_detected", r"wl(?P<unit>\d+): DFS: \S+ #+ RADAR\S* DETECTED ON (?:Upper80 of )?CHANNEL (?P<chan>\S+) #+", S_WLMFG),
    ("RADAR_DFS", "radar_detected", r"wl(?P<unit>\d+): DFS WLC_E_RADAR_DETECTED on ch (?P<cur>%s) going to ch (?P<tgt>%s)" % (CS, CS), S_WLMFG),
    ("RADAR_DFS", "radar_detected", r"###### DETECTED A RADAR on Chanspec (?P<cur>%s)" % CS, S_WLMFG),
    ("RADAR_DFS", "radar_ignored", r"wl\d+: dfs : radar detected but ignoring", S_WLMFG),
    ("RADAR_DFS", "cac", r"wl(?P<unit>\d+): chanspec (?P<cur>[0-9a-fA-F]{4}), (?P<cac_s>\d+) second CAC time", S_WLMFG),
    ("RADAR_DFS", "radar_detected", r"DFS-RADAR-DETECTED freq=(?P<freq>\d+)", S_HAPD),
    ("RADAR_DFS", "cac", r"DFS-CAC-START freq=(?P<freq>\d+) chan=(?P<chan>\d+).*cac_time=(?P<cac_s>\d+)s", S_HAPD),
    ("RADAR_DFS", "cac_complete", r"DFS-CAC-COMPLETED success=(?P<success>\d) freq=(?P<freq>\d+)", S_HAPD),
    # --- CHANNEL CHANGE ---
    ("CHANNEL_CHANGE", "ap_chan_change", r"AP_CHAN_CHANGE event: Band\[(?P<band>\d+)\] BSS\[(?P<mac>%s)\] Ifname\[(?P<ifname>[^\]]*)\], Firmware reason\[(?P<reason>\d+)\] current chanspec\[(?P<cur>%s)\], target chanspec\[(?P<tgt>%s)\]" % (MAC, CS, CS), S_SLAVE),
    ("CHANNEL_CHANGE", "chanspec_changed", r"Chanspec / TxPwr changed\. Chanspec: new\[(?P<tgt>%s)\] old\[(?P<cur>%s)\]" % (CS, CS), S_SLAVE),
    ("CHANNEL_CHANGE", "csa", r"IFR\[(?P<mac>%s)\] Local Chanspec\[(?P<cur>%s)\] CSA Chanspec\[(?P<tgt>%s)\]" % (MAC, CS, CS), S_SLAVE),
    ("CHANNEL_CHANGE", "dfs_new_channel", r"DFS-NEW-CHANNEL freq=(?P<freq>\d+) chan=(?P<chan>\d+)", S_HAPD),
    ("CHANNEL_CHANGE", "acsd_select", r"ACSD >>.*: Selected Channel #(?P<chan>\d+) \((?P<tgt>%s)\)" % CS, S_ACSD),
    ("CHANNEL_CHANGE", "acsd_select", r"acsd: (?P<ifname>\S+): selected channel spec: (?P<tgt>%s)" % CS, S_ACSD),
    ("CHANNEL_CHANGE", "acsd_csa", r"ACSD >>.*Performing CSA on chspec (?P<tgt>%s)" % CS, S_ACSD),
    ("CHANNEL_CHANGE", "acsd_select", r"ACSD >>.*Final selected chanspec: (?P<tgt>%s)" % CS, S_ACSD),
    ("CHANNEL_CHANGE", "dfsr_switch", r"Switching to chanspec (?P<tgt>%s), switch count so far" % CS, S_ACSD),
    ("CHANNEL_CHANGE", "acsd_nondfs", r"ACSD >>.*Set to non dfs channel (?P<tgt>%s)" % CS, S_ACSD),
    ("CHANNEL_CHANGE", "acsd_change", r"ACSD >>\S*: ifname: (?P<ifname>\S+), reason: (?P<reason>\d+), chanspec: (?P<tgt>%s), csa:" % CS, S_ACSD),
    # --- SATELLITE SUPERVISOR (acos_agent) ---
    ("PING_FAIL", "ping_fail", r"ping base (?P<ip>\S+) failed count (?P<count>\d+)", S_AGENT),
    ("PING_FAIL", "no_base_ip", r"failed to get the ip address of base and over the threshold", S_AGENT),
    ("SAT_DISCONNECT", "ping_timeout", r"ping timeout, set the satellite to disconnect", S_AGENT),
    ("SAT_DISCONNECT", "led_off_ping_timeout", r"acos_agent off +the led ping timeout", S_AGENT),
    ("SAT_DISCONNECT", "led_off_no_base", r"acos_agent off the led can't find the base", S_AGENT),
    ("SAT_DISCONNECT", "led_off_wifi_down", r"acos_agent off the led wifi is down", S_AGENT),
    ("BOOT", "acos_agent_start", r"acos_agent off the led restart", S_AGENT),
    ("SAT_RECOVER", "led_on", r"acos_agent light on the led", S_AGENT),
    ("SAT_RECOVER", "agent_back", r"Agent (?P<mac>\S+) ip (?P<ip>\S+) is back", S_AGENT),
    ("SAT_STATE", "state_change", r"MODULE_NAMEstate changed: (?P<old>\d+) -> (?P<new>\d+)", S_AGENT),
    ("BH_LINK_DOWN", "bh_conn_changed", r"Backhaul connection changed, current link status: (?P<status>\d+)", S_AGENT),
    ("BH_LINK_DOWN", "dhcp_release", r"\*\*\*\*Release DHCP lease!!", S_AGENT),
    ("BH_LINK_DOWN", "dhcp_renew", r"\*\*\*\*Renew DHCP lease!!", S_AGENT),
    ("BH_LINK_DOWN", "bh_none", r"interface is not up, set current bh to none", S_AGENT),
    # --- WBD backhaul link / blocking ---
    ("BH_BLOCKED", "controller_removed", r"Controller device (?P<mac>%s) removed\. Blocking backhaul BSS" % MAC, S_SLAVE),
    ("BH_BLOCKED", "autoconfig_exceeded", r"AP-Autoconfiguration search count (?P<count>\d+) exceeds threshold of (?P<thr>\d+)", S_SLAVE),
    ("BOOT", "wbd_bootup_block", r"Blocking Backhaul bss and disabling fronthaul bss on bootup", S_SLAVE),
    ("BH_BLOCKED", "device_removed", r"Received callback: Device\[(?P<mac>%s)\] (?:\S+ )?got removed" % MAC, S_SLAVE + "|" + S_MASTER),
    ("BH_UNBLOCKED", "controller_detected", r"Controller device (?P<mac>%s) detected\. Unblocking backhaul BSS" % MAC, S_SLAVE),
    ("BH_UNBLOCKED", "controller_reachable", r"Controller is reachable through ifname\[(?P<ifname>[^\]]*)\] and MAC\[(?P<mac>%s)\]" % MAC, S_SLAVE),
    ("BH_LINK_UP", "bsta_assoc", r"Backhaul STA interface (?P<ifname>\S+) assoicated on \[(?P<bssid>%s)\]" % MAC, S_SLAVE),
    ("BH_LINK_UP", "link_up", r"Ifname\[(?P<ifname>[^\]]*)\] Link UP Event for STA\[(?P<mac>%s)\]" % MAC, S_SLAVE),
    ("BH_LINK_DOWN", "link_down", r"Ifname\[(?P<ifname>[^\]]*)\] Link DOWN Event for STA\[(?P<mac>%s)\]" % MAC, S_SLAVE),
    ("BH_LINK_DOWN", "bsta_disconnect", r"Disconnect backhaul STA \[(?P<mac>%s)\] from BSSID \[(?P<bssid>%s)\]" % (MAC, MAC), S_SLAVE),
    ("BH_LINK_DOWN", "bsta_not_assoc", r"ifname\[(?P<ifname>[^\]]*)\] backhaul STA is not associated", S_SLAVE),
    ("BH_LINK_DOWN", "bsta_not_assoc", r"BHSTA ifname\[(?P<ifname>[^\]]*)\] not associated status (?P<status>0x[0-9a-fA-F]+)", S_SLAVE),
    ("BH_LINK_DOWN", "wired_fallback", r"Disassociated, but has ethernet connection", S_SLAVE),
    ("BH_LINK_DOWN", "wpas_disconnected", r"CTRL-EVENT-DISCONNECTED bssid=(?P<bssid>%s) reason=(?P<reason>\d+)" % MAC, S_WPAS),
    ("BH_LINK_DOWN", "beacon_loss", r"CTRL-EVENT-BEACON-LOSS", S_WPAS),
    ("BH_LINK_UP", "wpas_connected", r"CTRL-EVENT-CONNECTED - Connection to (?P<bssid>%s) completed" % MAC, S_WPAS),
    ("BH_LINK_DOWN", "ap_sta_disconnected", r"AP-STA-DISCONNECTED (?P<mac>%s)" % MAC, S_HAPD),
    ("BH_LINK_DOWN", "bridge_port", r"br\d+: port \d+\((?P<ifname>[^)]+)\) entered (?P<state>disabled|forwarding|blocking|listening|learning) state", S_KERNEL),
    # --- weak backhaul / RSSI ---
    ("WEAK_BH", "weak_bsta", r"Found Weak STA\[(?P<mac>%s)\] fail_cnt=(?P<fail>\d+) sta_rule_met=(?P<rule>0x[0-9a-fA-F]+)" % MAC, S_SLAVE),
    ("WEAK_BH", "bsta_metrics", r"STA\[(?P<mac>%s)\] RSSI\[(?P<rssi>-?\d+)\] ReportedRSSI\[(?P<rrssi>-?\d+)\] tx_rate.*t_RSSI\[(?P<thr>-?\d+)\]" % MAC, S_SLAVE),
    ("WEAK_BH", "bsta_score", r"For (?P<ifname>\S+?):BSTA\[(?P<mac>%s)\] : rssi=(?P<rssi>-?\d+), rssi_thld=(?P<thr>-?\d+)" % MAC, S_SLAVE),
    ("WEAK_BH", "master_sta_eval", r"For (?P<pfx>\S*?)STA\[(?P<mac>%s)\] idle_rate\[-?\d+\] t_idle_rate\[-?\d+\] rssi\[(?P<rssi>-?\d+)\] t_rss\[(?P<thr>-?\d+)\].*is_sta_weak\[(?P<weak>\w+)\]" % MAC, S_MASTER),
    ("WEAK_BH", "dwds_metrics", r"Ifname\[(?P<ifname>[^\]]*)\] MAC\[(?P<mac>%s)\] DWDS .*RSSI\[(?P<rssi>-?\d+) \((?P<rssi2>-?\d+)\)\]" % MAC, S_SLAVE),
    ("WEAK_BH", "became_strong", r"Weak STA (?P<mac>%s)\s+became strong" % MAC, S_SLAVE),
    ("WEAK_BH", "weak_sta", r"Found weak STA (?P<mac>%s)" % MAC, S_SLAVE),
    # --- backhaul roaming / steering ---
    ("BH_ROAM", "bsta_moving", r"Backhaul STA\[(?P<mac>%s)\] is moving to BSSID\[(?P<bssid>%s)\]" % (MAC, MAC), S_SLAVE),
    ("BH_ROAM", "joining", r"Joining SSID: .* BSSID:\[(?P<bssid>%s)\] chanspec: (?P<tgt>%s)" % (MAC, CS), S_SLAVE),
    ("BH_ROAM", "bsta_roam_chan", r"bSTA\[(?P<mac>%s)\] is roaming to Chanspec\[(?P<tgt>%s)\]" % (MAC, CS), S_SLAVE),
    ("BH_ROAM", "bh_steer", r"Send Backhaul STEER to\[(?P<dev>%s)\] for STA\[(?P<mac>%s)\] TargetBSS\[(?P<bssid>%s)\] Opclass\[\d+\] Chanspec\[(?P<tgt>%s)\]" % (MAC, MAC, MAC, CS), S_MASTER),
    ("BH_ROAM", "bh_opt_start", r"For BHSTA\[(?P<mac>%s)\] Start backhaul optimization" % MAC, S_MASTER),
    ("BH_ROAM", "wpas_trying", r"Trying to associate with (?P<bssid>%s) \(SSID=.* freq=(?P<freq>\d+) MHz\)" % MAC, S_WPAS),
    # --- boot / markers ---
    ("BOOT", "kernel_boot", r"Linux version \d|Booting Linux", S_KERNEL),
    ("BOOT", "kernel_restart", r"reboot: Restarting system", S_KERNEL),
    ("BOOT", "syslogd_start", r"syslogd started: BusyBox", S_SYSLOGD),
    ("BOOT", "service_restart", r"\[acos_service\] restart", S_HTTPD),
    ("MARKER", "capture_end", r"\[User Capture End\]", S_HTTPD),
    ("MARKER", "debug_logd", r"\[acos\]\[debug_logd\]", S_HTTPD),
]
RULES = [(c, s, re.compile(r), src) for c, s, r, src in RULES]

INTERESTING = re.compile(r"wbd|acos_agent|radar|dfs|backhaul|bsta|\bcac\b|chanspec|acsd", re.I)
BSTA_LEARN = [re.compile(p % MAC) for p in (
    r"(?:Backhaul STA|backhaul STA|bSTA|BSTA|BHSTA)\s*[\[\(]?\s*(%s)",
    r"STA\[(%s)\] is backhaul STA",
    r"Found Weak STA\[(%s)\] fail_cnt=",  # wbd_slave_is_backhaul_sta_weak (bSTA only)
    r"_backhaul_sta_weak\S*: STA\[(%s)\] RSSI\[")]

# --- timestamp prefixes ---
RE_KMSG_PRIO = re.compile(r"^<\d{1,3}>")
RE_TAG = re.compile(r"^[A-Za-z0-9_.\-/]+(?:\[\d+\])?: ")
RE_UPTIME = re.compile(r"^\[\s*(\d+\.\d+)\]\s?")
RE_SYSLOG = re.compile(r"^(?:(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) )?(?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) +(?P<day>\d{1,2}) (?P<hms>\d\d:\d\d:\d\d)(?: (?P<year>\d{4}))? +(?P<rest>.*)$")
RE_FACPRI = re.compile(r"^[a-z0-9]+\.(?:emerg|alert|crit|err|warn|warning|notice|info|debug)$")
RE_DEBUGLOG = re.compile(r"^\[(\d{4})-(\d\d)-(\d\d) (\d\d):(\d\d):(\d\d)\.(\d+)\] ")
RE_ECHO = re.compile(r"\[(\d{4})(\d\d)(\d\d) (\d\d):(\d\d):(\d\d)\]\[")
RE_DATE = re.compile(r"^(?:Mon|Tue|Wed|Thu|Fri|Sat|Sun) (?P<mon>Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec) +(?P<day>\d{1,2}) (?P<hms>\d\d:\d\d:\d\d) (?:(?P<tz>[A-Za-z0-9+\-:]+) )?(?P<year>\d{4})\s*$")
RE_WBD = re.compile(r"(?P<lvl>Info|Err|Warn|Dbg|Trace|Json): WBD-(?P<proc>\w+) >> \((?P<epoch>\d+)\) (?P<func>\S+?): ")
EPOCH0 = dt.datetime(1970, 1, 1)


def chanspec_info(cs):
    """Decode a Broadcom 11ac-style chanspec (0xBBCC). Returns 'ch 100/80 DFS'-style text."""
    try:
        v = int(cs.replace(" ", ""), 16)
    except ValueError:
        return cs
    ch = v & 0xFF
    bw = {0x1000: 20, 0x1800: 40, 0x2000: 80, 0x2800: 160, 0x3000: 160}.get(v & 0x3800)
    band = "5G" if (v & 0xC000) == 0xC000 else ("2G" if (v & 0xC000) == 0 else "6G")
    if not bw:
        return "0x%04x" % v
    dfs = ""
    if band == "5G":
        half = (bw // 2 - 10) // 5
        subs = range(ch - half, ch + half + 1, 4)
        dfs = " DFS" if any(52 <= c <= 144 for c in subs) else " non-DFS"
    return "0x%04x=ch%d/%d%s" % (v, ch, bw, dfs)


# ---------------------------------------------------------------- input reading
def _is_binary(data):
    return b"\x00" in data[:4096]


def read_inputs(paths):
    """Yield (source_name, text) and collect skipped entries."""
    sources, skipped = [], []

    def add(name, data):
        if _is_binary(data) or name.lower().endswith((".cap", ".cap0", ".cap1", ".cap2", ".gz", ".tar", ".cfg")):
            skipped.append({"source": name, "reason": "binary/archive"})
            return
        sources.append((name, data.decode("utf-8", "replace")))

    def walk_zip(zf, prefix, depth):
        for info in zf.infolist():
            if info.is_dir():
                continue
            name = "%s:%s" % (prefix, info.filename)
            if info.file_size > MAX_MEMBER:
                skipped.append({"source": name, "reason": "too large"})
                continue
            try:
                with zf.open(info) as fh:
                    data = fh.read(MAX_MEMBER + 1)
            except (RuntimeError, zipfile.BadZipFile, NotImplementedError) as e:  # encrypted etc.
                skipped.append({"source": name, "reason": "unreadable: %s" % e})
                continue
            if info.filename.lower().endswith(".zip"):
                if depth < 1:
                    try:
                        walk_zip(zipfile.ZipFile(io.BytesIO(data)), name, depth + 1)
                    except zipfile.BadZipFile:
                        skipped.append({"source": name, "reason": "bad nested zip"})
                else:
                    skipped.append({"source": name, "reason": "nested zip too deep"})
                continue
            add(name, data)

    for p in paths:
        if os.path.isdir(p):
            for root, _, files in os.walk(p):
                for f in sorted(files):
                    fp = os.path.join(root, f)
                    if zipfile.is_zipfile(fp):
                        walk_zip(zipfile.ZipFile(fp), fp, 0)
                    else:
                        with open(fp, "rb") as fh:
                            add(fp, fh.read(MAX_MEMBER))
        elif zipfile.is_zipfile(p):
            walk_zip(zipfile.ZipFile(p), p, 0)
        else:
            with open(p, "rb") as fh:
                add(p, fh.read(MAX_MEMBER))
    return sources, skipped


# ---------------------------------------------------------------- line parsing
def parse_line(raw):
    """Strip known prefixes; return dict of stamps + message."""
    rec = {"uptime": None, "syslog": None, "local": None, "epoch": None, "wbd_proc": None, "tz_name": None}
    msg = raw.rstrip("\r\n").replace("\r", "")
    msg = RE_KMSG_PRIO.sub("", msg)
    m = RE_UPTIME.match(msg)
    if m:
        rec["uptime"] = float(m.group(1))
        msg = msg[m.end():]
    m = RE_SYSLOG.match(msg)
    if m and not RE_DATE.match(msg):
        h, mi, s = (int(x) for x in m.group("hms").split(":"))
        rec["syslog"] = (MONTHS[m.group("mon")], int(m.group("day")), h, mi, s,
                         int(m.group("year")) if m.group("year") else None)
        rest = m.group("rest").split(" ", 2)
        if len(rest) >= 2 and RE_FACPRI.match(rest[1]):
            msg = rest[2] if len(rest) > 2 else ""
        elif rest and RE_FACPRI.match(rest[0]):
            msg = m.group("rest").split(" ", 1)[1] if " " in m.group("rest") else ""
        else:
            msg = m.group("rest")
        msg = RE_TAG.sub("", msg, count=1)
    m = RE_DEBUGLOG.match(msg)
    if m:
        y, mo, d, h, mi, s, frac = m.groups()
        rec["local"] = dt.datetime(int(y), int(mo), int(d), int(h), int(mi), int(s)) + dt.timedelta(microseconds=int(frac[:6].ljust(6, "0")))
        msg = msg[m.end():]
    else:
        m = RE_DATE.match(msg)
        if m:
            h, mi, s = (int(x) for x in m.group("hms").split(":"))
            rec["local"] = dt.datetime(int(m.group("year")), MONTHS[m.group("mon")], int(m.group("day")), h, mi, s)
            rec["tz_name"] = m.group("tz")
            rec["is_anchor"] = True
        else:
            m = RE_ECHO.search(msg)
            if m:
                rec["local"] = dt.datetime(*(int(x) for x in m.groups()))
                rec["is_anchor"] = True
    m = RE_WBD.search(msg)
    if m:
        rec["epoch"] = int(m.group("epoch"))
        rec["wbd_proc"] = m.group("proc")
    rec["msg"] = msg
    return rec


def classify(msg):
    for cat, sub, rx, src in RULES:
        m = rx.search(msg)
        if m:
            return cat, sub, {k: v for k, v in m.groupdict().items() if v is not None}, src
    return None


def template(msg):
    t = re.sub(MAC, "<mac>", msg)
    t = re.sub(r"0x[0-9a-fA-F]+", "<hex>", t)
    t = re.sub(r"\d+(?:\.\d+)?", "<n>", t)
    return t[:200]


# ---------------------------------------------------------------- analysis
class Analyzer(object):
    def __init__(self, args):
        self.a = args
        self.bh_ifaces = set(args.bh_ifaces.split(",")) if args.bh_ifaces else set(DEFAULT_BH_IFACES)
        self.bsta = set(m.lower() for m in (args.bsta_mac or []))
        self.warnings = []

    def _refine(self, ev, rec):
        """Adjust category using context; return False to drop to 'unclassified'."""
        cat, sub, f = ev["category"], ev["subtype"], ev["fields"]
        thr_default = self.a.weak_rssi
        if sub in ("link_down", "link_up", "bridge_port"):
            if f.get("ifname") not in self.bh_ifaces:
                return False
            if sub == "bridge_port":
                ev["category"] = "BH_LINK_DOWN" if f.get("state") in ("disabled", "blocking") else "BH_LINK_UP"
        elif sub == "ap_sta_disconnected":
            if f.get("mac", "").lower() not in self.bsta:
                return False
        elif sub == "bh_conn_changed":
            st = f.get("status")
            f["status_meaning"] = {"0": "wired", "1": "wireless", "3": "none"}.get(st, "?")
        elif sub == "device_removed":
            if rec.get("wbd_proc") == "Master":
                ev["category"], ev["subtype"] = "SAT_DISCONNECT", "agent_removed_from_topology"
        elif sub == "state_change":
            new = f.get("new")
            ev["category"] = {"3": "SAT_DISCONNECT", "2": "SAT_RECOVER"}.get(new, "MARKER")
        elif cat == "WEAK_BH":
            mac = f.get("mac", "").lower()
            rssi = int(f["rssi"]) if "rssi" in f else None
            thr = int(f["thr"]) if "thr" in f else thr_default
            if sub == "weak_sta":
                if mac not in self.bsta:
                    ev["category"] = "WEAK_CLIENT"
            elif sub == "became_strong":
                if mac not in self.bsta:
                    ev["category"] = "WEAK_CLIENT"
                else:
                    ev["category"] = "BH_RSSI"
            elif sub == "master_sta_eval":
                if not f.get("pfx") and mac not in self.bsta:
                    ev["category"] = "WEAK_CLIENT" if f.get("weak", "").upper() in ("YES", "TRUE", "1") else "BH_RSSI"
                    if ev["category"] == "BH_RSSI":
                        return False
                elif f.get("weak", "").upper() not in ("YES", "TRUE", "1"):
                    ev["category"] = "BH_RSSI"
            elif rssi is not None:
                if not (rssi < thr or rssi < thr_default):
                    ev["category"] = "BH_RSSI"
            if rssi is not None:
                ev["rssi"] = rssi
        return True

    def run(self, sources, skipped):
        # pass 0: learn backhaul STA MACs
        for _, text in sources:
            for line in text.splitlines():
                if "STA" in line:
                    for rx in BSTA_LEARN:
                        for m in rx.finditer(line):
                            self.bsta.add(m.group(1).lower())
        events, unclassified, src_info = [], {}, []
        parsed = []
        for name, text in sources:
            recs = []
            seg, last_up = 0, None
            for i, raw in enumerate(text.splitlines(), 1):
                if not raw.strip():
                    continue
                r = parse_line(raw)
                if r["uptime"] is not None:
                    if last_up is not None and r["uptime"] + 1 < last_up:
                        seg += 1
                    last_up = r["uptime"]
                r["seg"], r["lineno"], r["raw"] = seg, i, raw.rstrip("\r\n")
                recs.append(r)
            info = self._clock_model(name, recs)
            info["boots_seen"] = seg + 1 if last_up is not None else None
            parsed.append((name, recs, info))
        # one container (zip/dir/file) = one device: share learned tz/year with its other members
        by_cont = {}
        for name, recs, info in parsed:
            by_cont.setdefault(name.split(":", 1)[0], []).append(info)
        for name, recs, info in parsed:
            peers = [i for i in by_cont[name.split(":", 1)[0]] if i["tz_basis"].startswith("learned")]
            if not info["tz_basis"].startswith("learned") and peers and not self.a.tz_offset:
                info["tz_offset_s"] = peers[0]["tz_offset_s"]
                info["tz_basis"] = "from sibling file in same capture"
            if info["year"] is None:
                yrs = [i["year"] for i in by_cont[name.split(":", 1)[0]] if i["year"]]
                info["year"] = yrs[0] if yrs else None
            if info["tz_basis"].startswith("assumed") and info.pop("_needs_tz", False):
                self.warnings.append("%s: device timezone unknown, local stamps treated as UTC (use --tz-offset)" % name)
            info.pop("_needs_tz", None)
            info["_anchors"] = self._anchors(recs, info)
        for name, recs, info in parsed:
            roles = set()
            n_ev = 0
            for r in recs:
                if r["wbd_proc"] == "Master":
                    roles.add("router")
                elif r["wbd_proc"] == "Slave":
                    roles.add("wbd_agent")
                if "[acos_agent]" in r["msg"] and ("satellite" in r["msg"] or "ping" in r["msg"]):
                    roles.add("satellite")
                c = classify(r["msg"])
                if c:
                    ev = {"category": c[0], "subtype": c[1], "fields": c[2], "pattern_source": c[3],
                          "source": name, "line": r["lineno"], "text": r["msg"].strip()[:400]}
                    if self._refine(ev, r):
                        ev.update(self._stamp(r, info, name))
                        events.append(ev)
                        n_ev += 1
                        continue
                if INTERESTING.search(r["msg"]) and not r.get("is_anchor"):
                    t = template(r["msg"].strip())
                    u = unclassified.setdefault(t, {"template": t, "count": 0, "example": r["msg"].strip()[:300],
                                                    "first": "%s:%d" % (name, r["lineno"])})
                    u["count"] += 1
            info.update({"source": name, "lines": len(recs), "events": n_ev, "role_hints": sorted(roles)})
            src_info.append(info)
        return self._report(events, unclassified, src_info, skipped)

    def _clock_model(self, name, recs):
        info = {"tz_offset_s": None, "tz_basis": None, "year": None, "synced": True}
        diffs, years = [], []
        for r in recs:
            if r["epoch"] is not None:
                years.append(dt.datetime.utcfromtimestamp(r["epoch"]).year)
                if r["epoch"] < SYNC_EPOCH:
                    info["synced"] = False
            if r["local"] is not None:
                years.append(r["local"].year)
                if r["local"].year < 2020:
                    info["synced"] = False
            if r["syslog"] is not None and r["epoch"] is not None:
                mo, d, h, mi, s, y = r["syslog"]
                y = y or dt.datetime.utcfromtimestamp(r["epoch"]).year
                try:
                    loc = (dt.datetime(y, mo, d, h, mi, s) - EPOCH0).total_seconds()
                except ValueError:
                    continue
                diffs.append(loc - r["epoch"])
        if years:
            info["year"] = max(set(years), key=years.count)
        elif any(r["syslog"] for r in recs):
            info["year"] = self.a.year or dt.date.today().year
            if not self.a.year:
                self.warnings.append("%s: syslog year unknown, assumed %d (use --year)" % (name, info["year"]))
        if diffs:
            off = int(round(statistics.median(diffs) / 900.0) * 900)
            info["tz_offset_s"], info["tz_basis"] = off, "learned from %d syslog+WBD lines" % len(diffs)
        else:
            info["tz_offset_s"] = int(self.a.tz_offset * 3600)
            info["tz_basis"] = "--tz-offset" if self.a.tz_offset else "assumed UTC (no syslog+WBD pair)"
            info["_needs_tz"] = any(r["syslog"] or (r["local"] and r["tz_name"] not in ("UTC", "GMT"))
                                    for r in recs) and not self.a.tz_offset
        if not info["synced"]:
            self.warnings.append("%s: device clock looks unsynced (pre-2020); its events form a separate time domain" % name)
        return info

    @staticmethod
    def _local_to_utc(r, info):
        """`date` output that names UTC/GMT is already UTC; other local stamps use the device tz."""
        off = 0 if r.get("tz_name") in ("UTC", "GMT") else info["tz_offset_s"]
        return (r["local"] - EPOCH0).total_seconds() - off

    def _anchors(self, recs, info):
        anchors = {}
        for r in recs:
            if r.get("is_anchor") and r["uptime"] is not None and r["local"] is not None:
                anchors.setdefault(r["seg"], []).append((r["uptime"], self._local_to_utc(r, info)))
        return anchors

    def _stamp(self, r, info, name):
        tz = info["tz_offset_s"]
        wall_dom = "wall" if info["synced"] else "devclock:%s" % name
        if r["epoch"] is not None:
            return {"domain": wall_dom, "ts": float(r["epoch"]), "clock": "wbd_epoch", "tz": tz}
        if r["syslog"] is not None:
            mo, d, h, mi, s, y = r["syslog"]
            try:
                loc = dt.datetime(y or info["year"], mo, d, h, mi, s)
                return {"domain": wall_dom, "ts": (loc - EPOCH0).total_seconds() - tz, "clock": "syslog", "tz": tz}
            except (ValueError, TypeError):
                pass
        if r["local"] is not None:
            clk = "debuglog" if not r.get("is_anchor") else "kmsg_date"
            return {"domain": wall_dom, "ts": self._local_to_utc(r, info), "clock": clk, "tz": tz}
        if r["uptime"] is not None:
            anc = info["_anchors"].get(r["seg"])
            if anc:
                before = [a for a in anc if a[0] <= r["uptime"]]
                u0, w0 = (before[-1] if before else anc[0])
                return {"domain": wall_dom, "ts": w0 + (r["uptime"] - u0), "clock": "uptime+date_anchor",
                        "uptime": r["uptime"], "tz": tz}
            return {"domain": "uptime:%s#boot%d" % (name, r["seg"]), "ts": r["uptime"], "clock": "uptime",
                    "uptime": r["uptime"]}
        return {"domain": "lines:%s" % name, "ts": float(r["lineno"]), "clock": "none"}

    # ------------------------------------------------------------ incidents / verdict
    def _report(self, events, unclassified, src_info, skipped):
        events.sort(key=lambda e: (e["domain"], e["ts"], e["source"], e["line"]))
        for i, e in enumerate(events):
            e["id"] = i
        incidents = []
        for dom in sorted(set(e["domain"] for e in events)):
            evs = [e for e in events if e["domain"] == dom and e["category"] not in NO_CHAIN]
            gap = self.a.line_window if dom.startswith("lines:") else self.a.window
            cur = []
            for e in evs:
                if cur and e["ts"] - cur[-1]["ts"] > gap:
                    incidents.append(self._incident(dom, cur))
                    cur = []
                cur.append(e)
            if cur:
                incidents.append(self._incident(dom, cur))
        incidents.sort(key=lambda x: (x["domain"] != "wall", x["domain"], x["start"]))
        for n, inc in enumerate(incidents, 1):
            inc["n"] = n
        counts = {}
        for e in events:
            counts[e["category"]] = counts.get(e["category"], 0) + 1
        rssis = [e["rssi"] for e in events if "rssi" in e and e["category"] in ("WEAK_BH", "BH_RSSI")]
        verdict = self._verdict(incidents, events, src_info, rssis)
        for s in src_info:
            s.pop("_anchors", None)
        return {"sources": src_info, "skipped": skipped, "warnings": self.warnings,
                "settings": {"window_s": self.a.window, "weak_rssi": self.a.weak_rssi,
                             "bh_ifaces": sorted(self.bh_ifaces), "bsta_macs": sorted(self.bsta)},
                "events": events, "incidents": incidents, "counts": counts,
                "bh_rssi": {"n": len(rssis), "min": min(rssis) if rssis else None,
                            "median": statistics.median(rssis) if rssis else None},
                "unclassified": sorted(unclassified.values(), key=lambda u: -u["count"]),
                "verdict": verdict}

    def _incident(self, dom, evs):
        cats = [e["category"] for e in evs]
        outage = [e for e in evs if e["category"] in OUTAGE]
        inc = {"domain": dom, "start": evs[0]["ts"], "end": evs[-1]["ts"], "event_ids": [e["id"] for e in evs],
               "categories": sorted(set(cats)), "has_boot": "BOOT" in cats}
        if not outage:
            inc["trigger"], inc["trigger_code"], inc["rule"] = "no outage events", "NONE", "no BH_LINK_DOWN/BH_BLOCKED/SAT_DISCONNECT/PING_FAIL"
            return inc
        t0 = outage[0]["ts"] + self.a.skew
        pre = [e for e in evs if e["ts"] <= t0]
        link_down = any(e["category"] == "BH_LINK_DOWN" or e["subtype"] == "led_off_wifi_down" for e in evs)
        radar = [e for e in pre if e["category"] == "RADAR_DFS" and e["subtype"] not in ("ism_started", "cac_complete", "radar_ignored")]
        if radar:
            best = [e for e in radar if e["subtype"] == "radar_detected"] or radar
            code, rule = "DFS", "R1: RADAR_DFS (%s, %s:%d) at/before first outage event" % (
                best[0]["subtype"], os.path.basename(best[0]["source"].split(":")[-1]), best[0]["line"])
        elif any(e["category"] == "WEAK_BH" for e in pre):
            code, rule = "WEAK", "R2: WEAK_BH (RSSI below threshold) at/before first outage event"
        elif any(e["category"] == "CHANNEL_CHANGE" for e in pre):
            code, rule = "CHAN", "R3: CHANNEL_CHANGE without RADAR_DFS before first outage event"
        elif link_down:
            code, rule = "LINKDROP", "R4: backhaul link went down, no radar/weak-signal/channel-change evidence before it"
        else:
            code, rule = "CTRL", "R5: ping/controller failures with no backhaul link-down event in the incident"
        label = {"DFS": "DFS/radar-triggered", "WEAK": "weak backhaul signal (RSSI)",
                 "CHAN": "non-radar channel change, then outage", "LINKDROP": "link drop without radar",
                 "CTRL": "controller unreachable while link up"}[code]
        if inc["has_boot"]:
            label += " (+ reboot/restart marker)"
        inc["trigger"], inc["trigger_code"], inc["rule"] = label, code, rule
        return inc

    def _verdict(self, incidents, events, src_info, rssis):
        out = [i for i in incidents if i["trigger_code"] != "NONE"]
        hints = []
        if not any(s["role_hints"] and ("router" in s["role_hints"] or "wbd_agent" in s["role_hints"]) for s in src_info):
            hints.append("no WBD lines found: enable 'WBD Log Capture' before capturing")
        if not any("satellite" in s["role_hints"] for s in src_info):
            hints.append("no acos_agent satellite lines: also save Debug_log.zip from each satellite's own debug.htm")
        if not out:
            return {"code": "INCONCLUSIVE", "label": "INCONCLUSIVE: no backhaul outage events found",
                    "rule": "R0: zero incidents with outage events", "tally": {}, "hints": hints}
        tally = {}
        for i in out:
            tally[i["trigger_code"]] = tally.get(i["trigger_code"], 0) + 1
        prio = ["DFS", "WEAK", "CHAN", "LINKDROP", "CTRL"]
        best = sorted(tally, key=lambda c: (-tally[c], prio.index(c)))[0]
        labels = {"DFS": "LIKELY DFS/RADAR", "WEAK": "LIKELY WEAK SIGNAL / RSSI",
                  "CHAN": "LINK DROP AFTER NON-RADAR CHANNEL CHANGE", "LINKDROP": "LINK DROP WITHOUT RADAR",
                  "CTRL": "CONTROLLER UNREACHABLE WHILE LINK UP"}
        # A tie is reported as MIXED, never resolved toward a favoured hypothesis; `prio` only orders the listing.
        rule = "majority of %d outage incident(s): %s (ties -> MIXED)" % (
            len(out), ", ".join("%s=%d" % (k, tally[k]) for k in prio if k in tally))
        if rssis and min(rssis) < self.a.weak_rssi and best != "WEAK":
            hints.append("backhaul RSSI dipped to %d dBm (< %d) at some point" % (min(rssis), self.a.weak_rssi))
        if best in ("LINKDROP", "CTRL") and not any(e["category"] == "RADAR_DFS" for e in events):
            hints.append("no radar lines at all: router WBD log and router zip needed to rule DFS out")
        tied = [c for c in prio if c != best and tally.get(c) == tally[best]]
        if tied:
            members = [best] + tied
            return {"code": "MIXED", "label": "MIXED / INCONCLUSIVE: equal evidence for %s"
                    % ", ".join(labels[c] for c in members),
                    "tied_with": members, "rule": rule, "tally": tally, "hints": hints}
        return {"code": best, "label": labels[best], "tied_with": [], "rule": rule, "tally": tally, "hints": hints}


# ---------------------------------------------------------------- output
def fmt_ts(e_or_ts, dom, tz=0):
    ts = e_or_ts
    if dom.startswith("lines:"):
        return "line %6d" % ts
    if dom.startswith("uptime:"):
        return "up %10.3fs" % ts
    t = EPOCH0 + dt.timedelta(seconds=ts + (tz or 0))
    return t.strftime("%Y-%m-%d %H:%M:%S")


def describe(e):
    f = e["fields"]
    parts = []
    for k in ("ifname", "ip", "count", "thr", "status", "status_meaning", "reason", "chan", "remain", "cac_s", "fail", "weak", "state", "new"):
        if k in f:
            parts.append("%s=%s" % (k, f[k]))
    if "rssi" in e:
        parts.append("rssi=%d" % e["rssi"])
    if "cur" in f:
        parts.append("cur=%s" % chanspec_info(f["cur"]) if f["cur"].startswith("0x") else "cur=%s" % f["cur"])
    if "tgt" in f:
        parts.append("tgt=%s" % chanspec_info(f["tgt"]))
    for k in ("mac", "bssid"):
        if k in f:
            parts.append("%s=%s" % (k, f[k]))
    return " ".join(parts)


def print_text(rep, max_unclassified, out=None):
    w = (out or sys.stdout).write
    w("== Sources\n")
    for s in rep["sources"]:
        if not s["lines"]:
            continue
        w("  %-60s lines=%-6d events=%-4d roles=%s tz=%s (%s)%s\n" % (
            s["source"][-60:], s["lines"], s["events"], ",".join(s["role_hints"]) or "-",
            "%+.2fh" % (s["tz_offset_s"] / 3600.0) if s["tz_offset_s"] is not None else "?", s["tz_basis"],
            "" if s["synced"] else " UNSYNCED-CLOCK"))
    if rep["skipped"]:
        w("  skipped: %s\n" % ", ".join("%s (%s)" % (k["source"].split(":")[-1], k["reason"]) for k in rep["skipped"][:30]))
    for x in rep["warnings"]:
        w("  WARNING: %s\n" % x)
    w("\n== Incidents (window %ss; wall times shown in device-local time; clock per event in [])\n" % rep["settings"]["window_s"])
    evmap = {e["id"]: e for e in rep["events"]}
    for inc in rep["incidents"]:
        e0 = evmap[inc["event_ids"][0]]
        w("\n-- Incident %d  domain=%s  %s .. %s  (%d events)\n   trigger: %s   [%s]\n" % (
            inc["n"], inc["domain"], fmt_ts(inc["start"], inc["domain"], e0.get("tz")),
            fmt_ts(inc["end"], inc["domain"], e0.get("tz")), len(inc["event_ids"]), inc["trigger"], inc["rule"]))
        for eid in inc["event_ids"]:
            e = evmap[eid]
            w("   %s  %-15s %-26s %s  [%s %s:%d]\n" % (
                fmt_ts(e["ts"], e["domain"], e.get("tz")), e["category"], e["subtype"], describe(e),
                e["clock"], os.path.basename(e["source"].split(":")[-1]), e["line"]))
    w("\n== Counts per category\n")
    for k in sorted(rep["counts"], key=lambda c: -rep["counts"][c]):
        w("  %-16s %d\n" % (k, rep["counts"][k]))
    b = rep["bh_rssi"]
    if b["n"]:
        w("  backhaul RSSI samples: n=%d min=%s median=%s dBm\n" % (b["n"], b["min"], b["median"]))
    un = rep["unclassified"]
    w("\n== Unclassified interesting lines (%d templates, %d lines)\n" % (len(un), sum(u["count"] for u in un)))
    for u in un[:max_unclassified]:
        w("  %5dx %s\n         e.g. %s  (%s)\n" % (u["count"], u["template"][:150], u["example"][:150], u["first"].split(":")[-2:][0] if ":" in u["first"] else u["first"]))
    if len(un) > max_unclassified:
        w("  ... %d more templates (use --max-unclassified or --json)\n" % (len(un) - max_unclassified))
    v = rep["verdict"]
    w("\nVERDICT: %s\n  rule: %s\n" % (v["label"], v["rule"]))
    for h in v["hints"]:
        w("  hint: %s\n" % h)


def main(argv=None):
    ap = argparse.ArgumentParser(description="Netgear MR70/MS70 Debug_log.zip backhaul incident analyzer")
    ap.add_argument("inputs", nargs="+", help="Debug_log.zip files, extracted dirs, or log files")
    ap.add_argument("--window", type=float, default=120.0, help="incident gap window in seconds (default 120)")
    ap.add_argument("--line-window", type=int, default=50, help="gap in lines for untimed events (default 50)")
    ap.add_argument("--skew", type=float, default=5.0, help="cross-device clock tolerance for trigger ordering, s (default 5)")
    ap.add_argument("--weak-rssi", type=int, default=-75, help="weak backhaul RSSI threshold dBm (wbd_weak_sta_cfg_bh default -75)")
    ap.add_argument("--bh-ifaces", default=None, help="comma list of backhaul ifaces (default wl1.1,wl1.2,wl2,wl2.1)")
    ap.add_argument("--bsta-mac", action="append", help="known backhaul STA MAC (repeatable); others are learned from logs")
    ap.add_argument("--tz-offset", type=float, default=0.0, help="device UTC offset in hours when it can't be learned")
    ap.add_argument("--year", type=int, default=None, help="year for syslog stamps when it can't be inferred")
    ap.add_argument("--max-unclassified", type=int, default=40)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    a = ap.parse_args(argv)
    sources, skipped = read_inputs(a.inputs)
    rep = Analyzer(a).run(sources, skipped)
    if a.json:
        json.dump(rep, sys.stdout, indent=1, default=str)
        sys.stdout.write("\n")
    else:
        print_text(rep, a.max_unclassified)
    return 0


if __name__ == "__main__":
    sys.exit(main())
