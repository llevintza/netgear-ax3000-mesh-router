#!/usr/bin/env python3
"""Tests for tools/analyze_logs.py with synthetic logs built from the firmware format strings.

Run: python3 -I -m unittest discover -s tools/tests -v
All MACs are locally administered placeholders (02:00:00:xx:xx:xx); no real device data.
"""
import argparse
import calendar
import datetime as dt
import io
import json
import os
import sys
import tempfile
import unittest
import zipfile
from contextlib import redirect_stdout

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), ".."))
import analyze_logs as al  # noqa: E402

BASE = calendar.timegm((2026, 11, 1, 11, 0, 0))  # 11:00 UTC; device local = UTC+1
ROUTER_BSS = "02:00:00:00:00:01"
SAT_BSTA = "02:00:00:00:00:02"
SAT_AL = "02:00:00:00:00:03"
CTRL_AL = "02:00:00:00:00:04"


def syslog(t, host, tag, msg, tz=3600):
    d = dt.datetime.utcfromtimestamp(t + tz)
    return "%s %2d %s %s user.debug %s: %s" % (d.strftime("%b"), d.day, d.strftime("%H:%M:%S"), host, tag, msg)


def wbd(t, proc, func, lvl, body, host, tag):
    return syslog(t, host, tag, "%s: WBD-%s >> (%d) %s: %s" % (lvl, proc, t, func, body))


def agent(t, func, line, msg, host="MS70"):
    return syslog(t, host, "acos_agent", "[acos_agent][%s %d] %s" % (func, line, msg))


def router_dfs_log():
    t = BASE
    return "\n".join([
        wbd(t, "Master", "wbd_master_process_event", "Info", "IFR[%s] DFS status changed old_flags[0] new_flags[4] has_bh_bss[1]" % ROUTER_BSS, "MR70", "wbd_master"),
        wbd(t + 1, "Slave", "wbd_slave_process_event_msg", "Info", "Band[2] Ifname[wl1] RADAR DETECTED, current chanspec[0xe06a], target chanspec[0xe02a]", "MR70", "wbd_slave"),
        wbd(t + 1, "Slave", "wbd_slave_process_event_msg", "Info", "AP_CHAN_CHANGE event: Band[2] BSS[%s] Ifname[wl1], Firmware reason[1] current chanspec[0xe06a], target chanspec[0xe02a]" % ROUTER_BSS, "MR70", "wbd_slave"),
    ])


def sat_dfs_log():
    t = BASE
    return "\n".join([
        wbd(t + 3, "Slave", "wbd_slave_process_event_msg", "Info", "Ifname[wl1.2] Link DOWN Event for STA[%s]" % ROUTER_BSS, "MS70", "wbd_slave"),
        wbd(t + 30, "Slave", "wbd_ieee1905_device_removed_cb", "Err", "Controller device %s removed. Blocking backhaul BSS" % CTRL_AL, "MS70", "wbd_slave"),
        agent(t + 10, "check_satellite_connection", 554, "ping base 192.168.1.1 failed count 1"),
        agent(t + 15, "check_satellite_connection", 554, "ping base 192.168.1.1 failed count 2"),
        agent(t + 35, "satellite", 899, "acos_agent off the led ping timeout"),
        wbd(t + 95, "Slave", "wbd_slave_process_event_msg", "Info", "Backhaul STA interface wl1.2 assoicated on [%s]" % ROUTER_BSS, "MS70", "wbd_slave"),
        agent(t + 110, "check_satellite_connection", 600, "acos_agent light on the led "),
    ])


def sat_weak_log():
    t = BASE + 5000
    f = "wbd_slave_backhaul_sta_weak_client_watchdog_timer_cb"
    return "\n".join([
        wbd(t, "Slave", "wbd_slave_is_backhaul_sta_weak", "Info",
            "STA[%s] RSSI[-82] ReportedRSSI[-81] tx_rate[52] adj_mcs_phyrate[52] datarate[40] tx_failures[3] PolicyFlag[0x4] t_IdleRate[1000] t_RSSI[-75] t_hysterisis[3] t_txrate[50] t_txfailure[200]" % SAT_BSTA, "MS70", "wbd_slave"),
        wbd(t + 5, "Slave", f, "Info", "Found Weak STA[%s] fail_cnt=3 sta_rule_met=0x2" % SAT_BSTA, "MS70", "wbd_slave"),
        wbd(t + 20, "Slave", "wbd_slave_process_event_msg", "Info", "Ifname[wl1.2] Link DOWN Event for STA[%s]" % ROUTER_BSS, "MS70", "wbd_slave"),
        agent(t + 21, "satellite", 907, "acos_agent off the led wifi is down"),
        agent(t + 22, "check_satellite_uplink_conn", 719, "****Backhaul connection changed, current link status: 3"),
    ])


def sat_ping_only_log():
    t = BASE + 9000
    lines = [wbd(t - 100, "Slave", "wbd_slave_init", "Info", "Backhaul STA interface wl1.2 assoicated on [%s]" % ROUTER_BSS, "MS70", "wbd_slave")]
    for i in range(1, 5):
        lines.append(agent(t + 5 * i, "check_satellite_connection", 554, "ping base 192.168.1.1 failed count %d" % i))
    lines.append(syslog(t + 25, "MS70", "acos_agent", "****ping timeout, set the satellite to disconnect!!"))
    lines.append(agent(t + 25, "check_satellite_connection", 571, "acos_agent off the led ping timeout"))
    lines.append(agent(t + 25, "satellite", 920, "MODULE_NAMEstate changed: 2 -> 3 "))
    return "\n".join(lines)


def kmsg_text():
    # `date > /dev/kmsg` + echo lines from acos_agent as read via `cat /proc/kmsg`.
    return "\n".join([
        "<6>[  100.000000] Linux version 4.19.183 (synthetic)",
        "<12>[ 5000.000000] Sun Nov  1 11:00:00 UTC 2026",
        "<12>[ 5035.500000] acos_agent off  the led ping timeout",
        "<4>[ 5040.000000] wl1: random driver chatter about dfs that we do not classify",
    ])


def args(**kw):
    ns = argparse.Namespace(window=120.0, line_window=50, skew=5.0, weak_rssi=-75, bh_ifaces=None, bsta_mac=None,
                            tz_offset=0.0, year=None, max_unclassified=40, json=False)
    for k, v in kw.items():
        setattr(ns, k, v)
    return ns


def run_texts(named_texts, **kw):
    return al.Analyzer(args(**kw)).run(list(named_texts), [])


class FormatTests(unittest.TestCase):
    def test_chanspec_decode(self):
        self.assertEqual(al.chanspec_info("0xe06a"), "0xe06a=ch106/80 DFS")
        self.assertEqual(al.chanspec_info("0xe02a"), "0xe02a=ch42/80 non-DFS")
        self.assertEqual(al.chanspec_info("0xe09b"), "0xe09b=ch155/80 non-DFS")

    def test_wbd_epoch_and_syslog_parse(self):
        r = al.parse_line(wbd(BASE, "Slave", "f", "Info", "x", "MS70", "wbd_slave"))
        self.assertEqual(r["epoch"], BASE)
        self.assertEqual(r["wbd_proc"], "Slave")
        self.assertTrue(r["msg"].startswith("Info: WBD-Slave"), r["msg"])  # syslog tag stripped
        self.assertEqual(r["syslog"][2], 12)  # local hour (UTC+1)

    def test_kmsg_date_anchor(self):
        r = al.parse_line("<12>[ 5000.000000] Sun Nov  1 12:00:00 UTC 2026")
        self.assertEqual(r["tz_name"], "UTC")
        self.assertEqual(r["uptime"], 5000.0)
        self.assertTrue(r.get("is_anchor"))
        self.assertEqual(r["local"], dt.datetime(2026, 11, 1, 12, 0, 0))

    def test_client_link_down_not_backhaul(self):
        rep = run_texts([("s.txt", wbd(BASE, "Slave", "f", "Info", "Ifname[wl1] Link DOWN Event for STA[02:00:00:00:00:99]", "MS70", "wbd_slave"))])
        self.assertNotIn("BH_LINK_DOWN", rep["counts"])


class ScenarioTests(unittest.TestCase):
    def test_dfs_triggered_cross_device(self):
        rep = run_texts([("router/syslogd.txt", router_dfs_log()), ("sat/syslogd.txt", sat_dfs_log())])
        self.assertEqual(rep["verdict"]["code"], "DFS")
        inc = [i for i in rep["incidents"] if i["trigger_code"] != "NONE"]
        self.assertEqual(len(inc), 1)
        self.assertTrue(inc[0]["rule"].startswith("R1"))
        self.assertEqual(inc[0]["domain"], "wall")
        for s in rep["sources"]:
            self.assertEqual(s["tz_offset_s"], 3600)
        for c in ("RADAR_DFS", "CHANNEL_CHANGE", "BH_LINK_DOWN", "BH_BLOCKED", "PING_FAIL", "SAT_DISCONNECT", "BH_LINK_UP", "SAT_RECOVER"):
            self.assertIn(c, rep["counts"], c)
        # acos_agent syslog line (local time, no epoch) ordered correctly against WBD epoch lines
        ev = [e for e in rep["events"] if e["subtype"] == "ping_fail"][0]
        self.assertEqual(ev["clock"], "syslog")
        self.assertEqual(ev["ts"], BASE + 10)

    def test_weak_signal(self):
        rep = run_texts([("sat/syslogd.txt", sat_weak_log())])
        self.assertEqual(rep["verdict"]["code"], "WEAK")
        self.assertEqual(rep["bh_rssi"]["min"], -82)
        self.assertIn(SAT_BSTA, rep["settings"]["bsta_macs"])

    def test_ping_fail_link_up(self):
        rep = run_texts([("sat/syslogd.txt", sat_ping_only_log())])
        self.assertEqual(rep["verdict"]["code"], "CTRL")
        self.assertEqual(rep["counts"]["PING_FAIL"], 4)
        self.assertEqual(rep["counts"]["SAT_DISCONNECT"], 3)
        self.assertIn("no radar lines", " ".join(rep["verdict"]["hints"]))

    def test_no_outage_is_inconclusive(self):
        rep = run_texts([("x.txt", "nothing to see\nhere\n")])
        self.assertEqual(rep["verdict"]["code"], "INCONCLUSIVE")

    def test_zip_with_multiple_files(self):
        with tempfile.TemporaryDirectory() as d:
            inner = io.BytesIO()
            with zipfile.ZipFile(inner, "w") as z2:
                z2.writestr("data/router-analytics/ra.log", "irrelevant\n")
            zp = os.path.join(d, "Debug_log.zip")
            with zipfile.ZipFile(zp, "w") as z:
                z.writestr("syslogd.txt", sat_dfs_log() + "\n" + router_dfs_log() + "\n")
                z.writestr("kmsg_con.txt", kmsg_text())
                z.writestr("dmesg.txt", "[    0.000000] Booting Linux on physical CPU 0x0\n")
                z.writestr("BR.cap", b"\xd4\xc3\xb2\xa1\x00\x00binary")
                z.writestr("ra.zip", inner.getvalue())
            src, skipped = al.read_inputs([zp])
            names = sorted(n.split(":", 1)[1] for n, _ in src)
            self.assertIn("syslogd.txt", names)
            self.assertIn("kmsg_con.txt", names)
            self.assertTrue(any(n.endswith("ra.log") for n in names))
            self.assertTrue(any(s["source"].endswith("BR.cap") for s in skipped))
            rep = al.Analyzer(args()).run(src, skipped)
            self.assertEqual(rep["verdict"]["code"], "DFS")
            # kmsg echo mapped to wall clock via the `date` anchor ("UTC" => no tz shift) + 35.5 s
            km = [e for e in rep["events"] if e["source"].endswith("kmsg_con.txt") and e["subtype"] == "led_off_ping_timeout"][0]
            self.assertEqual(km["clock"], "uptime+date_anchor")
            self.assertAlmostEqual(km["ts"], calendar.timegm((2026, 11, 1, 11, 0, 35)) + 0.5)
            self.assertEqual(len([i for i in rep["incidents"] if i["trigger_code"] != "NONE"]), 1)
            dm = [e for e in rep["events"] if e["source"].endswith("dmesg.txt")][0]
            self.assertEqual(dm["category"], "BOOT")
            self.assertTrue(dm["domain"].startswith("uptime:"))
            self.assertTrue(any("random driver chatter" in u["example"] for u in rep["unclassified"]))
            # CLI text + json paths
            buf = io.StringIO()
            with redirect_stdout(buf):
                al.main([zp])
            self.assertIn("VERDICT: LIKELY DFS/RADAR", buf.getvalue())
            buf = io.StringIO()
            with redirect_stdout(buf):
                al.main(["--json", zp])
            self.assertEqual(json.loads(buf.getvalue())["verdict"]["code"], "DFS")


if __name__ == "__main__":
    unittest.main()
