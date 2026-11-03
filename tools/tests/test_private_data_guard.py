"""Tests for tools/private_data_guard.py. Planted values are built at runtime so this file passes the guard."""

import contextlib
import io
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import private_data_guard as g  # noqa: E402

LAN = ".".join(["192", "168", "0", "25"])
TEN = ".".join(["10", "1", "2", "3"])
REAL_MAC = ":".join(["a4", "2b", "8c", "11", "22", "33"])
HOME = "/" + "Users" + "/someone/"


def kinds(text, denylist=()):
    return [k for _, k, _ in g.scan_text(text, denylist)]


class GuardTests(unittest.TestCase):
    def test_flags_private_ip(self):
        self.assertEqual(kinds("satellite at " + LAN), ["private-ip"])
        self.assertEqual(kinds("vpn " + TEN), ["private-ip"])

    def test_allows_firmware_defaults_and_public_doc_ranges(self):
        self.assertEqual(kinds("fallback 192.168.1.250, router 192.168.1.1, tun 192.168.254.1"), [])
        self.assertEqual(kinds("doc range 192.0.2.10 and version 1.0.5.50 and 172.32.0.1"), [])

    def test_flags_real_mac_allows_placeholder(self):
        self.assertEqual(kinds("STA[" + REAL_MAC + "]"), ["mac"])
        self.assertEqual(kinds("STA[02:00:00:00:00:01]"), [])

    def test_mac_detail_is_truncated(self):
        details = [d for _, _, d in g.scan_text(REAL_MAC)]
        self.assertNotIn(REAL_MAC, details[0])

    def test_flags_home_path_not_placeholder(self):
        self.assertEqual(kinds("see " + HOME + "repo"), ["home-path"])
        self.assertEqual(kinds("see /Users/<you>/repo"), [])

    def test_denylist_hit_does_not_echo_value(self):
        hits = list(g.scan_text("ssid is MyHouseNet5G", ["MyHouseNet5G"]))
        self.assertEqual([k for _, k, _ in hits], ["denylist"])
        self.assertNotIn("MyHouseNet5G", hits[0][2])

    def test_allow_marker(self):
        self.assertEqual(kinds("example " + LAN + "  # private-data-guard: allow"), [])

    def test_main_exit_codes(self):
        with tempfile.TemporaryDirectory() as d:
            bad = os.path.join(d, "bad.md")
            good = os.path.join(d, "good.md")
            with open(bad, "w") as f:
                f.write("router " + LAN + "\n")
            with open(good, "w") as f:
                f.write("router <router-ip>\n")
            with contextlib.redirect_stdout(io.StringIO()) as out:
                self.assertEqual(g.main([good]), 0)
                self.assertEqual(g.main([bad]), 1)
            self.assertIn("private-ip", out.getvalue())


if __name__ == "__main__":
    unittest.main()
