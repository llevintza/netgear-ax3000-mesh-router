"""Offline tests for tools/netgear_router.py.

Run: python3 -m unittest discover -s tools/tests -v
Fixtures in fixtures/ are small hand-written excerpts modelled on the MR70
fw 1.0.5.50_2.0.70 pages as httpd serves them (tags rendered, ?id= injected).
"""

import io
import os
import secrets
import sys
import tempfile
import unittest
import urllib.parse

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.dirname(HERE))
import netgear_router as nr  # noqa: E402

FIX = os.path.join(HERE, "fixtures")
FAKE_DEBUG_ZIP = b"PK\x03\x04fixture"  # minimal stand-in for the router's Debug_log.zip download


def read(name):
    with open(os.path.join(FIX, name), encoding="utf-8") as f:
        return f.read()


def run_cli(*argv):
    out = io.StringIO()
    err = io.StringIO()
    old = sys.stderr
    sys.stderr = err
    try:
        rc = nr.main(["--fixture-dir", FIX] + list(argv), out=out)
    finally:
        sys.stderr = old
    return rc, out.getvalue(), err.getvalue()


def body_of(output):
    for line in output.splitlines():
        if line.strip().startswith("body: "):
            return urllib.parse.parse_qsl(line.split("body: ", 1)[1], keep_blank_values=True)
    raise AssertionError("no body line in:\n" + output)


class TokenTests(unittest.TestCase):
    def test_extract_token_quoted_and_unquoted(self):
        self.assertEqual(nr.extract_token("newdebug.cgi?id=abc123"), "abc123")
        self.assertEqual(nr.extract_token("wireless.cgi?id=" + "f" * 64), "f" * 64)

    def test_missing_token_is_layout_error(self):
        with self.assertRaises(nr.LayoutError):
            nr.extract_token("wireless.cgi")

    def test_forms_parsed_with_tokens(self):
        forms = nr.parse_forms(read("debug_frame.htm"))
        self.assertEqual(len(forms), 4)
        f1 = nr.find_form(forms, "newdebug.cgi", {"form": "1"})
        self.assertEqual(nr.extract_token(f1.action), "aaaa1111")
        bh = nr.find_form(forms, "bh_opt.cgi")
        self.assertEqual(nr.extract_token(bh.action), "bbbb2222")
        w = nr.find_form(nr.parse_forms(read("WLG_wireless2.htm")), "wireless.cgi")
        self.assertEqual(nr.extract_token(w.action), "cccc3333")

    def test_commented_and_script_markup_ignored(self):
        f1 = nr.find_form(nr.parse_forms(read("debug_frame.htm")), "newdebug.cgi", {"form": "1"})
        self.assertIsNone(f1.control("lacp_debug"))
        f2 = nr.find_form(nr.parse_forms(read("debug_frame.htm")), "newdebug.cgi", {"form": "2"})
        self.assertFalse(f2.control("action_Start_Capture").disabled)

    def test_find_form_layout_error(self):
        with self.assertRaises(nr.LayoutError):
            nr.find_form(nr.parse_forms("<html></html>"), "wireless.cgi")


class DebugBuilderTests(unittest.TestCase):
    def setUp(self):
        self.forms = nr.parse_forms(read("debug_frame.htm"))
        self.f1 = nr.find_form(self.forms, "newdebug.cgi", {"form": "1"})

    def test_state_from_hidden_fields(self):
        st = nr.debug_checkbox_state(self.f1)
        self.assertFalse(st["wbd_debug"])        # WBD_debug=1 -> not 7/15
        self.assertTrue(st["mfp_disable"])       # MFP_disable=1
        self.assertFalse(st["acos_agent_debug"])

    def test_enable_keeps_other_boxes(self):
        fields, before = nr.build_debug_logs(self.f1, True)
        d = dict(fields)
        self.assertEqual(d["wbd_debug"], "WBD_debug")
        self.assertEqual(d["acos_agent_debug"], "ACOS_AGENT_debug")
        self.assertEqual(d["mfp_disable"], "MFP_disable")   # stays ticked
        self.assertNotIn("accel_debug", d)
        self.assertEqual(d["form"], "1")
        self.assertIn("WBD_debug", d)                       # hidden fields sent too

    def test_disable(self):
        fields, _ = nr.build_debug_logs(self.f1, False)
        names = [k for k, _ in fields]
        self.assertNotIn("wbd_debug", names)
        self.assertNotIn("acos_agent_debug", names)

    def test_capture_start(self):
        f2 = nr.find_form(self.forms, "newdebug.cgi", {"form": "2"})
        d = dict(nr.build_capture_start(f2))
        self.assertEqual(d["action_Start_Capture"], "Start_Capture")
        self.assertEqual(d["store_location"], "memory")
        self.assertEqual(d["form"], "2")
        self.assertNotIn("DebugLog", d)
        self.assertNotIn("action_Capture_Packets", d)

    def test_bh_opt(self):
        bh = nr.find_form(self.forms, "bh_opt.cgi")
        self.assertEqual(nr.build_bh_opt(bh), [("bh_opt_setting", "bh_opt"), ("bh_opt_state", "")])


class ChannelTests(unittest.TestCase):
    def test_us_with_fcc_dfs(self):
        ch = nr.offered_5g_channels(11, "US", "HT80", "1")
        self.assertEqual(ch[:4], [36, 40, 44, 48])
        self.assertIn(52, ch)
        self.assertIn(144, ch)
        self.assertEqual(ch[-4:], [149, 153, 157, 161])
        self.assertNotIn(165, ch)

    def test_us_without_fcc_dfs(self):
        self.assertEqual(nr.offered_5g_channels(11, "US", "HT80", "0"), [36, 40, 44, 48, 149, 153, 157, 161])

    def test_europe(self):
        ch = nr.offered_5g_channels(5, "", "HT80", "")
        self.assertEqual(ch, [36, 40, 44, 48, 52, 56, 60, 64, 100, 104, 108, 112, 116, 120, 124, 128])

    def test_ht160(self):
        ch = nr.offered_5g_channels(11, "US", "HT160", "1")
        self.assertEqual(ch, [36, 40, 44, 48, 52, 56, 60, 64] + list(range(100, 129, 4)))
        self.assertNotIn(149, ch)

    def test_canada_no_dfs(self):
        self.assertEqual(nr.offered_5g_channels(4, "", "HT80", "1"), [36, 40, 44, 48, 149, 153, 157, 161])


class WirelessBuilderTests(unittest.TestCase):
    def setUp(self):
        self.sentinel = secrets.token_hex(8)  # random stand-in for the served Wi-Fi key
        self.page = read("WLG_wireless2.htm").replace(
            'name="passphrase_wpa2" value=""', 'name="passphrase_wpa2" value="%s"' % self.sentinel)
        self.form = nr.find_form(nr.parse_forms(self.page), "wireless.cgi")

    def test_set_36(self):
        fields, ctx, warnings = nr.build_set_5g(self.page, self.form, 36)
        d = dict(fields)
        self.assertEqual(d["w_channel_an"], "36")
        self.assertEqual(d["w_channel"], "0")
        self.assertEqual(d["security_type"], "WPA2-PSK")
        self.assertEqual(d["passphrase"], "")
        self.assertEqual(d["Apply"], "Apply")
        self.assertNotIn("ssid", d)
        self.assertNotIn("passphrase_wpa2", d)
        self.assertNotIn("buttonHit", d)
        self.assertNotIn(self.sentinel, repr(fields))
        self.assertEqual(ctx["region"], 11)
        self.assertEqual(warnings, [])

    def test_dfs_refused(self):
        with self.assertRaises(nr.RouterError):
            nr.build_set_5g(self.page, self.form, 100)
        fields, _, _ = nr.build_set_5g(self.page, self.form, 100, allow_dfs=True)
        self.assertEqual(dict(fields)["w_channel_an"], "100")

    def test_auto_needs_allow_unlisted(self):
        with self.assertRaises(nr.RouterError):
            nr.build_set_5g(self.page, self.form, 0)
        fields, _, warnings = nr.build_set_5g(self.page, self.form, 0, allow_unlisted=True)
        self.assertEqual(dict(fields)["w_channel_an"], "0")
        self.assertTrue(warnings)

    def test_unlisted_165(self):
        with self.assertRaises(nr.RouterError):
            nr.build_set_5g(self.page, self.form, 165)

    def test_ht160_warning(self):
        page = self.page.replace('var wlg_mode = "HT80"', 'var wlg_mode = "HT160"')
        _, _, warnings = nr.build_set_5g(page, self.form, 36)
        self.assertTrue(any("HT160" in w for w in warnings))

    def test_wpa3_sae_mapped(self):
        page = self.page.replace('name="security_type_2G" value="WPA2-PSK"', 'name="security_type_2G" value="WPA3-SAE"')
        form = nr.find_form(nr.parse_forms(page), "wireless.cgi")
        fields, _, _ = nr.build_set_5g(page, form, 36)
        self.assertEqual(dict(fields)["security_type"], "WPA3-Personal")

    def test_unknown_security_refused(self):
        page = self.page.replace('name="security_type_2G" value="WPA2-PSK"', 'name="security_type_2G" value=""')
        form = nr.find_form(nr.parse_forms(page), "wireless.cgi")
        with self.assertRaises(nr.RouterError):
            nr.build_set_5g(page, form, 36)


class ParserTests(unittest.TestCase):
    def test_firmware_header(self):
        self.assertEqual(nr.parse_firmware_header(read("top.htm")), "Firmware Version V1.0.5.50_2.0.70")

    def test_status_pairs(self):
        d = dict(nr.parse_status_pairs(read("ADVANCED_home2.htm")))
        self.assertTrue(d["5G Channel"].startswith("36(P)"))

    def test_satellite_table(self):
        rows = nr.parse_satellite_table(read("DEV_device_DI_R8000.htm"))
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0][3], "5GHz Wireless")

    def test_backhaul_stats(self):
        self.assertEqual(nr.parse_backhaul_stats(read("RST_stattbl.htm"))["uptime"], "01:02:03")

    def test_redirect_and_js_vars(self):
        self.assertEqual(nr.js_redirect_target(read("WLG_home.htm")), "WLG_wireless2.htm")
        self.assertEqual(nr.js_redirect_target(read("DEV_redirect.htm")), "DEV_device_DI_R8000.htm")
        self.assertEqual(nr.js_string_var(read("WLG_wireless2.htm"), "wlg_mode"), "HT80")

    def test_redact(self):
        self.assertEqual(nr.redact([("passphrase", "x"), ("w_channel_an", "36")]),
                         [("passphrase", "<redacted>"), ("w_channel_an", "36")])


class CliDryRunTests(unittest.TestCase):
    def test_debug_logs_dry_run(self):
        rc, out, _ = run_cli("debug-logs", "enable")
        self.assertEqual(rc, 0)
        self.assertIn("[dry-run] would POST http://fixture/newdebug.cgi?id=aaaa1111", out)
        self.assertIn(("wbd_debug", "WBD_debug"), body_of(out))
        self.assertIn("Basic <redacted>", out)

    def test_capture_start_dry_run(self):
        rc, out, _ = run_cli("capture", "start")
        self.assertEqual(rc, 0)
        self.assertIn(("action_Start_Capture", "Start_Capture"), body_of(out))

    def test_bh_optimize_dry_run(self):
        rc, out, _ = run_cli("bh-optimize")
        self.assertEqual(rc, 0)
        self.assertIn("bh_opt.cgi?id=bbbb2222", out)

    def test_set_channel_dry_run(self):
        rc, out, _ = run_cli("set-5g-channel", "36")
        self.assertEqual(rc, 0)
        self.assertIn("wireless.cgi?id=cccc3333", out)
        self.assertIn("rollback: set-5g-channel 44", out)

    def test_set_channel_dfs_refused(self):
        rc, out, err = run_cli("set-5g-channel", "52")
        self.assertEqual(rc, 2)
        self.assertIn("DFS", err)
        self.assertNotIn("POST", out)

    def test_status(self):
        rc, out, _ = run_cli("status", "--json")
        self.assertEqual(rc, 0)
        self.assertIn('"V1.0.5.50_2.0.70"', out)
        self.assertIn("MS70", out)
        self.assertIn('"wlg_channel": "44"', out)
        self.assertNotIn('"error"', out)

    def test_capture_save(self):
        with tempfile.TemporaryDirectory() as d:
            p = os.path.join(d, "x.zip")
            rc, out, _ = run_cli("capture", "save", "-o", p)
            self.assertEqual(rc, 0)
            with open(p, "rb") as f:
                self.assertTrue(f.read().startswith(b"PK"))
            rc, _, err = run_cli("capture", "save", "-o", p)
            self.assertEqual(rc, 2)


class HttpTransportTests(unittest.TestCase):
    """Local fake httpd: 401 + XSRF_TOKEN cookie first, then Basic auth + cookie required."""

    def setUp(self):
        import base64
        import http.server
        import threading
        self.pw = secrets.token_hex(8)  # generated per run; nothing stored
        expected = "Basic " + base64.b64encode(("admin:" + self.pw).encode()).decode()
        self.posts = []
        test = self

        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a):
                pass

            def _auth_ok(self):
                if "XSRF_TOKEN=42" not in (self.headers.get("Cookie") or ""):
                    self.send_response(401)
                    self.send_header("WWW-Authenticate", 'Basic realm="NETGEAR MR70"')
                    self.send_header("Set-Cookie", "XSRF_TOKEN=42; Path=/")
                    self.end_headers()
                    return False
                if self.headers.get("Authorization") != expected:
                    self.send_response(401)
                    self.end_headers()
                    return False
                return True

            def do_GET(self):
                if not self._auth_ok():
                    return
                name = self.path.lstrip("/").split("?")[0]
                if name == "Debug_log.zip":
                    # Served from code: *.zip files are gitignored/forbidden in this repo.
                    self.send_response(200)
                    self.end_headers()
                    self.wfile.write(FAKE_DEBUG_ZIP)
                    return
                p = os.path.join(FIX, name)
                if not os.path.isfile(p):
                    self.send_response(404)
                    self.end_headers()
                    return
                self.send_response(200)
                self.end_headers()
                with open(p, "rb") as f:
                    self.wfile.write(f.read())

            def do_POST(self):
                if not self._auth_ok():
                    return
                n = int(self.headers.get("Content-Length") or 0)
                test.posts.append((self.path, self.rfile.read(n).decode()))
                self.send_response(200)
                self.end_headers()
                self.wfile.write(b"<html>debug.htm</html>")

        self.srv = http.server.HTTPServer(("127.0.0.1", 0), H)
        threading.Thread(target=self.srv.serve_forever, daemon=True).start()
        self.base = "http://127.0.0.1:%d" % self.srv.server_address[1]

    def tearDown(self):
        self.srv.shutdown()
        self.srv.server_close()

    def test_login_retry_and_apply(self):
        t = nr.HttpTransport(self.base, "admin", self.pw, timeout=5)
        rt = nr.Router(t, apply=True, out=io.StringIO())
        args = type("A", (), {"state": "enable"})()
        self.assertEqual(nr.cmd_debug_logs(rt, args), 0)
        self.assertEqual(len(self.posts), 1)
        path, body = self.posts[0]
        self.assertEqual(path, "/newdebug.cgi?id=aaaa1111")
        self.assertIn("wbd_debug=WBD_debug", body)

    def test_bad_password(self):
        t = nr.HttpTransport(self.base, "admin", self.pw + "x", timeout=5)
        with self.assertRaises(nr.AuthError):
            nr.Router(t).get("debug_frame.htm")


if __name__ == "__main__":
    unittest.main()
