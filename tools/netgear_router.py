#!/usr/bin/env python3
"""netgear_router.py - drive the Netgear MR70 (fw 1.0.5.50_2.0.70) web UI from a shell.

Stdlib only. Lets an agent or a person at home do the HOME-GUIDE web steps:
read status, toggle the debug.htm log captures, start/save a capture, pin the
5 GHz channel, and start BH optimization.

Safety
------
* Every state-changing command is a DRY RUN unless you pass --apply. A dry run
  still logs in and GETs the pages it needs (read-only), because the CSRF token
  only exists in the served page. Then it prints the exact POST it would send.
* Password comes from $ROUTER_PASSWORD or an interactive getpass prompt. It is
  never a CLI argument, never written to disk, and never printed. Authorization
  headers are shown as "Basic <redacted>".
* By default the tool logs out at the end (GET LGO_logout.htm), so it doesn't
  hold the router's single admin session. Use --no-logout to skip that.

Where everything comes from (all paths are under extracted/MR70/selected.bin_extract/)
-----------------------------------------------------------------------------------
Auth/session  usr/sbin/httpd strings: 'WWW-Authenticate: Basic realm="%s"',
              'Authorization: Basic ', 'Set-Cookie: XSRF_TOKEN=%lu; Path=/'
              (sent with the 401). Another active admin session gets a page that
              posts to multi_login.cgi (www/MNU_access_multiLogin2.htm:195).
CSRF token    httpd FUN_00057ce4 (Ghidra addr; file vaddr = addr-0x10000)
              rewrites every '<form method=POST action=X.cgi' while serving it
              to 'X.cgi?id=<64 hex>'. The token is per CGI name (FUN_0005743c/
              FUN_00057648, SHA-256 of a random seed + CGI name). FUN_0005782c
              checks it. A bad or missing id gets csrf_timeout.htm.
              ajax/check_ver_result is exempt (FUN_00058f2c).
Logout        www/LGO_logout.htm renders <%1344%> = access_cgi_logout().
status        www/top.htm:451-454 'firm_version' div (info_mark_ver + ef_get_sw_ver()).
              www/UPG_upgrade.htm:282-305 POST ajax/check_ver_result action=getinfo
              returns /tmp/device_fw_info.json {router:{model,device_Name,version},
              satellites:[{model,device_Name,version,status}]} (handler FUN_000d0e90).
              www/ADVANCED_home2.htm:609-621 '5G Channel' = wlg_cgi_get_chstr(1)
              (operating channel string), '5G Mode' = wlg_cgi_get_curr_opmode(1).
              Attached Devices: DEV_redirect.htm goes to DEV_device_DI_R8000.htm
              (or DEV_device_DI_iQoS.htm when broadstream_iqos_enable=1). Its
              table#deviceTableSatellite rows come from FUN_0005d8ec. The 'Backhaul
              Status' column is the constant string backhaul_status="Good"
              (www/string_table_ax6000:1230), NOT a measurement.
              www/RST_stattbl.htm:111-120 'WLAN Backhaul' row (wlan3 stats).
debug.htm     www/debug.htm is a frameset around www/debug_frame.htm.
              Form 1 (hidden form=1, newdebug.cgi): every checkbox is re-read on
              each submit and is OFF if absent (httpd FUN_0010946c). Checkbox
              state is derived from the hidden fields exactly like isChecked()
              (debug_frame.htm:115-190). wbd_debug -> wbd_msglevel 7 and
              acos_agent_debug -> acos_agent_syslogd_output 1.
              Form 2 (form=2): action_Start_Capture=Start_Capture runs
              'acos_service start_debug'. Save = GET Debug_log.zip (debug_frame.htm:378).
              Form cf9 (bh_opt.cgi): bh_opt_setting=bh_opt + hidden bh_opt_state
              (debug_frame.htm:418-431).
5 GHz channel ADVANCED > Setup > Wireless Setup = WLG_home.htm, which JS-redirects to
              mnu_cgi_get_wireless_page(). On this firmware that is a constant
              'WLG_wireless2.htm' (handler at file vaddr 0xbbf3c). Form
              action=wireless.cgi (WLG_wireless2.htm:1021). Handler
              base_wirelessCgiMain (Ghidra FUN_000d8818):
                ssid (if non-empty) -> wla_ssid/wlg_ssid
                w_channel (if non-empty) -> wla_channel
                w_channel_an (if non-empty) -> wlg_channel
                security_type -> wla_secu_type (ALWAYS written; empty would blank it;
                  WPA3-Personal->WPA3-SAE, WPA3-Mixed->WPA3-MIXED)
                passphrase (if non-empty) -> wla_passphrase
              then wireless_configure(), save, sleep 10-20 s before replying.
              This tool sends no ssid and an empty passphrase, so neither changes.
              It never reads or sends the Wi-Fi key.
              The channel list is rebuilt from setHChannel()/setHChannel_HT160()
              (WLG_wireless2.htm:279-640). The 5 GHz 'Auto' option is commented out
              (lines 359-368), so the GUI offers no 5 GHz Auto.

Known gaps: never live-tested. bh_opt.cgi's handler (file vaddr 0xf9fac) was not
decompiled. The HT160 + fixed-channel = DFS-in-block reasoning is an inference
(see set-5g-channel warnings).
"""

from __future__ import annotations

import argparse
import base64
import datetime as _dt
import getpass
import html
import http.cookiejar
import json
import os
import re
import sys
import urllib.error
import urllib.parse
import urllib.request
from html.parser import HTMLParser

DEFAULT_HOST = "routerlogin.net"
DFS_CHANNELS = frozenset(range(52, 145, 4))  # 52..144
SECRET_KEY_RE = re.compile(r"pass|psk|key|pwd|secret", re.I)

REGION_NAMES = {
    0: "unset", 1: "Africa", 2: "Asia", 3: "Australia", 4: "Canada", 5: "Europe",
    6: "Israel", 7: "Japan", 8: "Korea", 9: "Mexico", 10: "South America",
    11: "North America/USA", 12: "Middle East", 14: "Russia", 16: "China",
    17: "India", 18: "Malaysia", 19: "Middle East (Iran/Lebanon/Qatar)",
    22: "Middle East (UAE)", 23: "Singapore", 24: "Taiwan",
}

# debug_frame.htm isChecked(): checkbox name -> (hidden field, values meaning "checked")
DEBUG_CHECKBOX_STATE = {
    "accel_debug": ("ACCEL_debug", ("1",)),
    "action_Start_When_Boot_Up": ("Start_When_Boot_Up", ("1",)),
    "stdout_dump": ("STDOUT_dump", ("1",)),
    "soap_debug": ("SOAP_debug", ("1",)),
    "acos_agent_debug": ("ACOS_AGENT_debug", ("1",)),
    "wifi_debug": ("WIFI_debug", ("1",)),
    "hapd_debug": ("HAPD_debug", ("1",)),
    "mfp_disable": ("MFP_disable", ("1",)),
    "wbd_debug": ("WBD_debug", ("7", "15")),
    "inet_debug": ("INET_debug", ("1",)),
    "bsd_debug": ("BSD_debug", ("0x6013",)),
    "steering_debug": ("STEERING_debug", ("0x1",)),
    "dal_debug": ("DAL_debug", ("1",)),
    "attach_device_debug": ("Attach_Device_Debug", ("1",)),
}
GUIDE_LOG_CHECKBOXES = ("wbd_debug", "acos_agent_debug")  # WBD + BH Management

# wla_secu_type (security_type_2G hidden field) -> radio value the browser posts.
SECURITY_FORM_VALUE = {
    "None": "None",
    "WPA2-PSK": "WPA2-PSK",
    "WPA-AUTO-PSK": "WPA-AUTO-PSK",
    "WPA3-SAE": "WPA3-Personal",
    "WPA3-Personal": "WPA3-Personal",
    "WPA3-MIXED": "WPA3-MIXED",
}


class RouterError(Exception):
    """Any error the CLI reports to the user (exit code 2)."""


class LayoutError(RouterError):
    """The served page doesn't match the firmware layout this tool was built from."""


class AuthError(RouterError):
    pass


# --------------------------------------------------------------------------- parsing

class Control:
    def __init__(self, kind, attrs):
        self.kind = kind  # input | select | button
        self.attrs = attrs
        self.name = attrs.get("name")
        self.type = (attrs.get("type") or ("submit" if kind == "button" else "text")).lower()
        self.value = attrs.get("value")
        self.checked = "checked" in attrs
        self.disabled = "disabled" in attrs
        self.id = attrs.get("id")
        self.options = []  # select only: [value, text, selected]

    def __repr__(self):
        return "Control(%s %s name=%r value=%r)" % (self.kind, self.type, self.name, self.value)


class Form:
    def __init__(self, attrs):
        self.attrs = attrs
        self.id = attrs.get("id")
        self.action = (attrs.get("action") or "").strip()
        self.method = (attrs.get("method") or "GET").upper()
        self.controls = []

    def control(self, name):
        for c in self.controls:
            if c.name == name:
                return c
        return None

    def hidden(self, name, default=None):
        c = self.control(name)
        if c is None or c.kind != "input":
            return default
        return c.value if c.value is not None else ""

    @property
    def cgi(self):
        return self.action.split("?", 1)[0]

    def __repr__(self):
        return "Form(id=%r action=%r, %d controls)" % (self.id, self.action, len(self.controls))


class _FormParser(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.forms = []
        self._form = None
        self._select = None
        self._option = None

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v if v is not None else "") for k, v in attrs}
        if tag == "form":
            self._form = Form(a)
            self.forms.append(self._form)
            return
        if self._form is None:
            return
        if tag == "input":
            self._form.controls.append(Control("input", a))
        elif tag == "button":
            self._form.controls.append(Control("button", a))
        elif tag == "select":
            self._select = Control("select", a)
            self._form.controls.append(self._select)
        elif tag == "option" and self._select is not None:
            self._option = [a.get("value"), "", "selected" in a]
            self._select.options.append(self._option)

    def handle_data(self, data):
        if self._option is not None:
            self._option[1] += data

    def handle_endtag(self, tag):
        if tag == "form":
            self._form = None
            self._select = None
        elif tag == "select":
            self._select = None
            self._option = None
        elif tag == "option":
            self._option = None


def parse_forms(page):
    p = _FormParser()
    p.feed(page)
    p.close()
    for f in p.forms:
        for c in f.controls:
            for o in c.options:
                if o[0] is None:
                    o[0] = o[1].strip()
    return p.forms


def find_form(forms, cgi, hidden=None):
    """First form whose action's CGI is `cgi` (and, if given, whose hidden fields match)."""
    for f in forms:
        if f.cgi.lower() != cgi.lower():
            continue
        if hidden and any(f.hidden(k) != v for k, v in hidden.items()):
            continue
        return f
    raise LayoutError("no <form action=%s%s> on the page; the router's page layout "
                      "differs from firmware 1.0.5.50_2.0.70" %
                      (cgi, " with %r" % hidden if hidden else ""))


def extract_token(action):
    """CSRF id from 'x.cgi?id=<token>' (injected by httpd FUN_00057ce4)."""
    m = re.search(r"[?&]id=([^&\s\"'>]+)", action or "")
    if not m:
        raise LayoutError("form action %r has no ?id= CSRF token; the page was not "
                          "served by the router's httpd, or the layout differs" % action)
    return m.group(1)


def serialize(form, submitter=None, overrides=None, checked=None, drop=()):
    """Return [(name, value)] the way a browser submits `form`.

    submitter: name of the submit button that was pressed (included with its value).
    overrides: {name: value} for text/hidden/select values.
    checked:   {checkbox name: bool} to override checkbox/radio state.
    drop:      names never sent.
    """
    overrides = overrides or {}
    checked = checked or {}
    out = []
    for c in form.controls:
        if not c.name or c.name in drop:
            continue
        if c.kind == "button" or (c.kind == "input" and c.type in ("submit", "image", "button", "reset")):
            if submitter and c.name == submitter and c.type in ("submit", "image"):
                out.append((c.name, c.value or ""))
            continue
        if c.disabled:
            continue
        if c.kind == "select":
            if c.name in overrides:
                out.append((c.name, overrides[c.name]))
                continue
            sel = [o for o in c.options if o[2]] or c.options[:1]
            out.extend((c.name, o[0]) for o in sel[:1])
            continue
        if c.type in ("checkbox", "radio"):
            on = checked.get(c.name, c.checked)
            if on:
                out.append((c.name, c.value if c.value is not None else "on"))
            continue
        if c.type == "file":
            continue
        out.append((c.name, overrides.get(c.name, c.value or "")))
    return out


def js_redirect_target(page):
    m = re.search(r"location\.(?:replace\(|href\s*=\s*)\s*[\"']\.?/?([^\"']+\.htm)[\"']", page)
    return m.group(1) if m else None


def js_string_var(page, name):
    m = re.search(r"var\s+%s\s*=\s*\"([^\"]*)\"" % re.escape(name), page)
    return m.group(1) if m else None


def strip_tags(s):
    s = re.sub(r"<[^>]+>", " ", s)
    return re.sub(r"\s+", " ", html.unescape(s)).replace("\xa0", " ").strip()


# ------------------------------------------------------------------ channel logic

BAND1 = [36, 40, 44, 48]
BAND2 = [52, 56, 60, 64]
BAND4 = [149, 153, 157, 161]
BAND3 = {
    8: list(range(100, 145, 4)),           # Band3Channel_KR_80M
    7: list(range(100, 145, 4)),           # Band3Channel_JP_80M
    5: list(range(100, 129, 4)),           # Band3Channel_CE_80M
    3: [100, 104, 108, 112, 132, 136, 140, 144],  # Band3Channel_AU_80M
    11: list(range(100, 145, 4)),          # Band3Channel_US_40M
}


def offered_5g_channels(region, sku="", wlg_mode="", fcc_dfs=""):
    """5 GHz options WLG_wireless2.htm builds (setHChannel / setHChannel_HT160)."""
    if wlg_mode == "HT160":
        chans = BAND1 + BAND2
        if region not in (3, 4):
            chans += list(range(100, 129, 4))
        return chans
    if region == 12:          # 5 GHz disabled
        return []
    chans = []
    if region == 16:
        chans += BAND1 + BAND2
    elif region != 19:
        chans += BAND1
        if region != 24:
            if region in (8, 7, 5, 3):
                chans += BAND2 + BAND3[region]
            if region == 11 and fcc_dfs == "1":
                chans += BAND2 + BAND3[11]
    if region == 19:
        chans += BAND4
    elif region in (4, 22) or (region == 11 and sku in ("US", "NA")):
        chans += BAND4
    elif region not in (5, 7, 22, 14) and sku != "JP":
        chans += BAND4
    return chans


# --------------------------------------------------------------------- transport

class Response:
    def __init__(self, status, headers, body, url):
        self.status = status
        self.headers = headers
        self.body = body
        self.url = url

    @property
    def text(self):
        return self.body.decode("utf-8", errors="replace")


class HttpTransport:
    def __init__(self, base, user, password, timeout=30.0, verbose=False):
        self.base = base.rstrip("/")
        self.timeout = timeout
        self.verbose = verbose
        self._auth = "Basic " + base64.b64encode(("%s:%s" % (user, password)).encode()).decode()
        self.jar = http.cookiejar.CookieJar()
        self.opener = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(self.jar))

    def request(self, method, path, data=None, referer=None, timeout=None):
        url = self.base + "/" + path.lstrip("/")
        body = urllib.parse.urlencode(data).encode() if data is not None else None
        for attempt in (1, 2):
            req = urllib.request.Request(url, data=body, method=method)
            req.add_header("Authorization", self._auth)
            req.add_header("User-Agent", "netgear_router.py")
            if referer:
                req.add_header("Referer", self.base + "/" + referer)
            if body is not None:
                req.add_header("Content-Type", "application/x-www-form-urlencoded")
            if self.verbose:
                print("  -> %s %s" % (method, url), file=sys.stderr)
            try:
                with self.opener.open(req, timeout=timeout or self.timeout) as r:
                    return Response(r.status, dict(r.headers), r.read(), url)
            except urllib.error.HTTPError as e:
                if e.code == 401 and attempt == 1 and any(c.name == "XSRF_TOKEN" for c in self.jar):
                    # httpd sets XSRF_TOKEN on the first 401; retry once with the cookie.
                    continue
                if e.code == 401:
                    raise AuthError("401 Unauthorized: wrong username/password, or the router "
                                    "rejected the login") from None
                raise RouterError("HTTP %s for %s" % (e.code, url)) from None
            except (urllib.error.URLError, OSError) as e:
                raise RouterError("cannot reach %s: %s" % (url, getattr(e, "reason", e))) from None
        raise AuthError("login failed")


class FixtureTransport:
    """Serves pages from a directory (offline dry runs/tests). Path 'a/b' -> 'a_b'."""

    def __init__(self, directory, verbose=False):
        self.base = "http://fixture"
        self.dir = directory
        self.verbose = verbose
        self.sent = []

    def request(self, method, path, data=None, referer=None, timeout=None):
        self.sent.append((method, path, data))
        name = path.split("?", 1)[0].lstrip("/").replace("/", "_")
        fp = os.path.join(self.dir, name)
        if not os.path.isfile(fp):
            # ".fixture" lets binary stand-ins (e.g. Debug_log.zip.fixture) avoid the repo's *.zip ban.
            for ext in (".htm", ".json", ".fixture"):
                if os.path.isfile(fp + ext):
                    fp += ext
                    break
            else:
                raise RouterError("fixture missing for %s (%s)" % (path, fp))
        with open(fp, "rb") as f:
            return Response(200, {}, f.read(), self.base + "/" + path)


# ----------------------------------------------------------------------- session

class Router:
    def __init__(self, transport, apply=False, out=sys.stdout):
        self.t = transport
        self.apply = apply
        self.out = out

    def say(self, *a):
        print(*a, file=self.out)

    def get(self, path):
        r = self.t.request("GET", path)
        self._check_page(r.text, path)
        return r

    def _check_page(self, text, path):
        if "multi_login.cgi" in text:
            raise RouterError("another admin session is active on the router (multi-login "
                              "page). Log out of the router in any browser/app, then retry.")
        if "unauth.cgi" in text and "401" in text:
            raise AuthError("router answered 401 Unauthorized (bad password?)")
        if re.search(r"csrf_timeout", text) and path != "csrf_timeout.htm":
            raise RouterError("router returned its CSRF-timeout page; the session "
                              "expired. Retry.")

    def page_forms(self, path):
        text = self.get(path).text
        return text, parse_forms(text)

    def post(self, form, fields, referer, timeout=None, describe=""):
        token = extract_token(form.action)
        path = re.sub(r"^(\./|/)+", "", form.action)
        url = self.t.base + "/" + path
        self.say("%s %s" % ("POST" if self.apply else "[dry-run] would POST", url))
        self.say("  Authorization: Basic <redacted>")
        self.say("  Referer: %s/%s" % (self.t.base, referer))
        self.say("  Content-Type: application/x-www-form-urlencoded")
        self.say("  body: " + urllib.parse.urlencode(redact(fields)))
        if describe:
            self.say("  effect: " + describe)
        if not self.apply:
            return None
        r = self.t.request("POST", path, data=fields, referer=referer, timeout=timeout)
        self._check_page(r.text, path)
        self.say("  -> HTTP %s, %d bytes (token %s...)" % (r.status, len(r.body), token[:8]))
        return r

    def logout(self):
        try:
            self.t.request("GET", "LGO_logout.htm")
        except RouterError:
            pass


def redact(fields):
    return [(k, "<redacted>" if SECRET_KEY_RE.search(k) and v else v) for k, v in fields]


# ------------------------------------------------------------------- builders

def debug_checkbox_state(form):
    """Current checkbox states of debug form 1, as debug_frame.htm isChecked() computes them."""
    state = {}
    for box, (hidden, on_values) in DEBUG_CHECKBOX_STATE.items():
        if form.control(box) is None:
            continue
        val = form.hidden(hidden)
        if val is None:
            # The satellite (MS70 www/debug.htm) has e.g. accel_debug without an ACCEL_debug hidden field
            # and no isChecked() rule for it, so a browser always shows it unticked. Mirror that.
            state[box] = False
            continue
        state[box] = val in on_values
    return state


def build_debug_logs(form, enable, boxes=GUIDE_LOG_CHECKBOXES):
    for b in boxes:
        if form.control(b) is None:
            raise LayoutError("debug form 1 has no checkbox %r" % b)
    state = debug_checkbox_state(form)
    before = dict(state)
    for b in boxes:
        state[b] = enable
    return serialize(form, checked=state), before


def build_capture_start(form, store="memory"):
    if form.control("action_Start_Capture") is None:
        raise LayoutError("debug form 2 has no Start Capture button")
    checked = {"action_Capture_Packets": form.hidden("dump_LAN_WAN_pkt") == "On"}
    overrides = {}
    if form.control("store_location") is not None:
        overrides["store_location"] = store
    return serialize(form, submitter="action_Start_Capture", overrides=overrides, checked=checked)


def build_bh_opt(form):
    if form.control("bh_opt_setting") is None:
        raise LayoutError("bh_opt.cgi form has no bh_opt_setting button")
    return serialize(form, submitter="bh_opt_setting")


WIRELESS_SAFE_FIELDS = ("initChannel", "initHChannel", "WRegion", "wds_enable", "coexistence",
                        "only_mode", "show_wps_alert", "security_type_2G",
                        "telec_dfs_ch_enable", "ce_dfs_ch_enable", "fcc_dfs_ch_enable")


def wireless_context(page, form):
    def num(v):
        try:
            return int(v)
        except (TypeError, ValueError):
            return None
    region = num(form.hidden("WRegion"))
    if region is None:
        region = num(js_string_var(page, "wlaRegion"))
    return {
        "region": region,
        "sku": js_string_var(page, "sku") or "",
        "wlg_mode": js_string_var(page, "wlg_mode") or "",
        "fcc_dfs": form.hidden("fcc_dfs_ch_enable") or "",
        "wlg_channel": form.hidden("initHChannel"),
        "wla_channel": form.hidden("initChannel"),
        "security": form.hidden("security_type_2G"),
    }


def build_set_5g(page, form, channel, allow_dfs=False, allow_unlisted=False):
    """Return (fields, ctx, warnings) for wireless.cgi. channel 0 = auto."""
    ctx = wireless_context(page, form)
    warnings = []
    for need in ("w_channel_an", "Apply"):
        if form.control(need) is None:
            raise LayoutError("wireless form has no %r control (expected WLG_wireless2.htm)" % need)
    if ctx["region"] is None:
        raise LayoutError("cannot read the region (hidden WRegion) from the wireless page")
    sec = ctx["security"]
    if sec not in SECURITY_FORM_VALUE:
        raise RouterError("current security type %r isn't one this tool can resend safely "
                          "(wireless.cgi always rewrites wla_secu_type). Use the web UI." % sec)
    offered = offered_5g_channels(ctx["region"], ctx["sku"], ctx["wlg_mode"], ctx["fcc_dfs"])
    ctx["offered"] = offered
    if channel in DFS_CHANNELS and not allow_dfs:
        raise RouterError("channel %d is a DFS channel (52-144). Refusing without --allow-dfs." % channel)
    if channel not in offered and not allow_unlisted:
        what = "Auto (0)" if channel == 0 else str(channel)
        raise RouterError("%s is not offered by this router's Wireless Setup page (region %s, "
                          "mode %s; offered: %s). Use --allow-unlisted to send it anyway." %
                          (what, ctx["region"], ctx["wlg_mode"] or "?", offered or "none"))
    if channel == 0:
        warnings.append("5 GHz 'Auto' is commented out in WLG_wireless2.htm; wireless.cgi stores "
                        "wlg_channel=0, but whether ACOS treats that as auto is unverified.")
    if ctx["wlg_mode"] == "HT160" and channel in BAND1 + BAND2:
        warnings.append("wlg_mode is HT160: a 160 MHz channel on %d spans 36-64, which includes "
                        "DFS 52-64 (Router Status lists the block as 36+40+...+64). Radar can "
                        "still move the channel. The MR70 web UI has no width setting. "
                        "Inference, not verified on hardware." % channel)
    overrides = {"w_channel_an": str(channel),
                 "w_channel": ctx["wla_channel"] or "0",
                 "security_type": SECURITY_FORM_VALUE[sec],
                 "passphrase": ""}
    fields = []
    for c in form.controls:
        if c.name in WIRELESS_SAFE_FIELDS and c.kind == "input":
            fields.append((c.name, c.value or ""))
    fields = ([("w_channel", overrides["w_channel"]), ("w_channel_an", overrides["w_channel_an"]),
               ("security_type", overrides["security_type"])] + fields +
              [("passphrase", ""), ("Apply", form.control("Apply").value or "Apply")])
    return fields, ctx, warnings


# --------------------------------------------------------------------- status

def parse_firmware_header(page):
    m = re.search(r'id="firm_version"[^>]*>(.*?)</div>', page, re.S | re.I)
    return strip_tags(m.group(1)) if m else None


def parse_status_pairs(page):
    menus = re.findall(r'class="basic-text-menu"[^>]*>(.*?)</td>\s*<td[^>]*class="basic-text-content"[^>]*>(.*?)</td>',
                       page, re.S | re.I)
    return [(strip_tags(a), strip_tags(b)) for a, b in menus]


def parse_satellite_table(page):
    m = re.search(r'id="deviceTableSatellite".*?</table>\s*</td>', page, re.S | re.I)
    if not m:
        return None
    rows = []
    for tr in re.findall(r"<tr[^>]*>(.*?)</tr>", m.group(0), re.S | re.I):
        cells = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", tr, re.S | re.I)]
        if cells and cells[0].isdigit():
            rows.append(cells)
    return rows


def parse_backhaul_stats(page):
    m = re.search(r"WLAN Backhaul</span></td>(.*?)</tr>", page, re.S | re.I)
    if not m:
        return None
    vals = [strip_tags(c) for c in re.findall(r"<td[^>]*>(.*?)</td>", m.group(1), re.S | re.I)]
    keys = ["status", "tx_pkts", "rx_pkts", "collisions", "tx_Bps", "rx_Bps", "uptime"]
    return dict(zip(keys, vals))


def cmd_status(rt, args):
    res = {}

    def section(name, fn):
        try:
            res[name] = fn()
        except RouterError as e:
            res[name] = {"error": str(e)}

    section("router_firmware_header", lambda: parse_firmware_header(rt.get("top.htm").text))

    def fw():
        try:
            _, forms = rt.page_forms("UPG_upgrade.htm")
            tok = "?id=" + extract_token(find_form(forms, "upgrade_check.cgi").action)
        except RouterError:
            tok = ""
        r = rt.t.request("POST", "ajax/check_ver_result" + tok, data={"action": "getinfo"},
                         referer="UPG_upgrade.htm")
        txt = r.text.strip()
        if txt == "error":
            return {"error": "router has no /tmp/device_fw_info.json yet (open Router Update once)"}
        try:
            return json.loads(txt)
        except ValueError:
            raise LayoutError("ajax/check_ver_result did not return JSON")
    section("firmware_info", fw)

    def wireless():
        page = rt.get("WLG_home.htm").text
        target = js_redirect_target(page) or "WLG_wireless2.htm"
        page = rt.get(target).text
        form = find_form(parse_forms(page), "wireless.cgi")
        ctx = wireless_context(page, form)
        ctx["page"] = target
        ctx["region_name"] = REGION_NAMES.get(ctx["region"], "?")
        ctx["offered"] = offered_5g_channels(ctx["region"] or 0, ctx["sku"], ctx["wlg_mode"], ctx["fcc_dfs"])
        ctx.pop("security", None)
        return ctx
    section("wireless_setting", wireless)

    def rstatus():
        pairs = parse_status_pairs(rt.get("ADVANCED_home2.htm").text)
        if not pairs:
            raise LayoutError("no status rows on ADVANCED_home2.htm")
        return {k: v for k, v in pairs if k.startswith(("5G", "2.4G")) or "Region" in k}
    section("router_status_wireless", rstatus)

    def sats():
        page = rt.get("DEV_redirect.htm").text
        target = js_redirect_target(page) or "DEV_device_DI_R8000.htm"
        rows = parse_satellite_table(rt.get(target).text)
        if rows is None:
            raise LayoutError("no deviceTableSatellite on %s" % target)
        return {"page": target, "rows": rows,
                "note": "columns: #, device, IP, connection, connected to, 'Backhaul Status' "
                        "(constant 'Good' in firmware, not measured)"}
    section("satellites", sats)

    def bh():
        stats = parse_backhaul_stats(rt.get("RST_stattbl.htm").text)
        if stats is None:
            raise LayoutError("no 'WLAN Backhaul' row in RST_stattbl.htm")
        return stats
    section("wlan_backhaul_stats", bh)

    if args.json:
        rt.say(json.dumps(res, indent=2))
    else:
        for k, v in res.items():
            rt.say("== %s" % k)
            rt.say(json.dumps(v, indent=2) if not isinstance(v, str) else v)
    return 0


# ------------------------------------------------------------------- commands

def _debug_forms(rt):
    # Router (MR70): debug.htm is a frameset around debug_frame.htm.
    # Satellite (MS70): no debug_frame.htm; debug.htm itself holds the same forms (MS70 www/debug.htm),
    # plus satellite-only controls (reset_bh_bssid in form 1, Enable Telnet in form 3) that must never be sent.
    try:
        page, forms = rt.page_forms("debug_frame.htm")
    except RouterError as e:
        if "HTTP 404" not in str(e):
            raise
        page, forms = rt.page_forms("debug.htm")
    return forms


def cmd_debug_logs(rt, args):
    form = find_form(_debug_forms(rt), "newdebug.cgi", {"form": "1"})
    fields, before = build_debug_logs(form, args.state == "enable")
    rt.say("current: " + ", ".join("%s=%s" % (b, "on" if before.get(b) else "off") for b in GUIDE_LOG_CHECKBOXES))
    if before.get("accel_debug"):
        rt.say("note: 'accelerator debug' is currently ticked; the browser re-sends it too, "
               "which restarts the 60 s accelerator debug.")
    rt.post(form, fields, "debug.htm",
            describe="%s WBD Log Capture (wbd_msglevel) and BH Management Log Capture "
                     "(acos_agent_syslogd_output); every other box keeps its current state"
                     % ("tick" if args.state == "enable" else "untick"))
    return 0


def cmd_capture(rt, args):
    if args.action == "save":
        return cmd_capture_save(rt, args)
    form = find_form(_debug_forms(rt), "newdebug.cgi", {"form": "2"})
    if form.hidden("capture_in_process") and not args.force:
        raise RouterError("a capture is already in progress (Start Capture is greyed out). "
                          "Use 'capture save', or --force to start anyway.")
    fields = build_capture_start(form)
    rt.post(form, fields, "debug.htm",
            describe="Start Capture to System Memory (runs 'acos_service start_debug' and an "
                     "NVRAM restart)")
    return 0


def cmd_capture_save(rt, args):
    out = args.output or os.path.join("logs", "Debug_log-%s.zip" % _dt.date.today().isoformat())
    if os.path.exists(out) and not args.force:
        raise RouterError("%s already exists (use --force to overwrite)" % out)
    r = rt.t.request("GET", "Debug_log.zip", referer="debug.htm",
                     timeout=max(getattr(rt.t, "timeout", 0), 120))
    if not r.body.startswith(b"PK"):
        raise RouterError("Debug_log.zip download isn't a zip (got %d bytes starting %r)" %
                          (len(r.body), r.body[:16]))
    os.makedirs(os.path.dirname(out) or ".", exist_ok=True)
    with open(out, "wb") as f:
        f.write(r.body)
    rt.say("saved %d bytes to %s (contains MACs/SSIDs; keep it in gitignored logs/)" % (len(r.body), out))
    return 0


def cmd_bh_optimize(rt, args):
    form = find_form(_debug_forms(rt), "bh_opt.cgi")
    if form.hidden("bh_opt_state") and not args.force:
        raise RouterError("BH optimization already running (bh_opt_state=%r)" % form.hidden("bh_opt_state"))
    rt.post(form, build_bh_opt(form), "debug.htm",
            describe="BH optimization; satellites may disconnect and reconnect for a few minutes")
    return 0


def cmd_set_5g(rt, args):
    raw = args.channel.lower()
    if raw == "auto":
        channel = 0
    elif raw.isdigit():
        channel = int(raw)
    else:
        raise RouterError("channel must be a number or 'auto'")
    page = rt.get("WLG_home.htm").text
    target = js_redirect_target(page) or "WLG_wireless2.htm"
    page = rt.get(target).text
    form = find_form(parse_forms(page), "wireless.cgi")
    fields, ctx, warnings = build_set_5g(page, form, channel, args.allow_dfs, args.allow_unlisted)
    rt.say("wireless page %s: region %s (%s), wlg_mode %s, current 5 GHz setting wlg_channel=%s"
           % (target, ctx["region"], REGION_NAMES.get(ctx["region"], "?"), ctx["wlg_mode"] or "?",
              ctx["wlg_channel"]))
    rt.say("rollback: set-5g-channel %s --apply" % (ctx["wlg_channel"] or "?"))
    for w in warnings:
        rt.say("WARNING: " + w)
    rt.post(form, fields, target, timeout=120,
            describe="wlg_channel=%d; Wi-Fi restarts (the router waits 10-20 s before replying). "
                     "SSID and passphrase are left unchanged." % channel)
    return 0


# ------------------------------------------------------------------------- main

def build_parser():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                formatter_class=argparse.RawDescriptionHelpFormatter,
                                epilog="Password: $ROUTER_PASSWORD or interactive prompt.")
    p.add_argument("--host", default=DEFAULT_HOST, help="router host or URL (default %(default)s)")
    p.add_argument("--user", default="admin")
    p.add_argument("--apply", action="store_true", help="actually send state-changing requests")
    p.add_argument("--verbose", "-v", action="store_true")
    p.add_argument("--timeout", type=float, default=30.0)
    p.add_argument("--no-logout", action="store_true", help="don't GET LGO_logout.htm at the end")
    p.add_argument("--fixture-dir", help=argparse.SUPPRESS)  # offline testing
    sub = p.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("status", help="firmware versions, 5 GHz setting/current, satellites (read-only)")
    s.add_argument("--json", action="store_true")
    s.set_defaults(func=cmd_status)

    s = sub.add_parser("debug-logs", help="tick/untick WBD + BH Management Log Capture")
    s.add_argument("state", choices=["enable", "disable"])
    s.set_defaults(func=cmd_debug_logs)

    s = sub.add_parser("capture", help="debug.htm Debug Log Capture")
    s.add_argument("action", choices=["start", "save"])
    s.add_argument("-o", "--output", help="save path (default logs/Debug_log-<date>.zip)")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_capture)

    s = sub.add_parser("set-5g-channel", help="set the 5 GHz channel (N or 'auto')")
    s.add_argument("channel")
    s.add_argument("--allow-dfs", action="store_true", help="permit DFS channels 52-144")
    s.add_argument("--allow-unlisted", action="store_true",
                   help="permit values the router's page doesn't offer (incl. auto)")
    s.set_defaults(func=cmd_set_5g)

    s = sub.add_parser("bh-optimize", help="debug.htm BH optimization")
    s.add_argument("--force", action="store_true")
    s.set_defaults(func=cmd_bh_optimize)
    return p


def make_transport(args):
    if args.fixture_dir:
        return FixtureTransport(args.fixture_dir, args.verbose)
    host = args.host if "://" in args.host else "http://" + args.host
    pw = os.environ.get("ROUTER_PASSWORD")
    if pw is None:
        if not sys.stdin.isatty():
            raise RouterError("set ROUTER_PASSWORD or run interactively for the password prompt")
        pw = getpass.getpass("Router admin password for %s: " % args.user)
    return HttpTransport(host, args.user, pw, args.timeout, args.verbose)


def main(argv=None, out=sys.stdout):
    args = build_parser().parse_args(argv)
    rt = None
    try:
        rt = Router(make_transport(args), apply=args.apply, out=out)
        rc = args.func(rt, args)
        if not args.apply and args.cmd not in ("status",) and not (args.cmd == "capture" and args.action == "save"):
            print("(dry run: nothing was changed; add --apply to send)", file=out)
        return rc
    except RouterError as e:
        print("error: %s" % e, file=sys.stderr)
        return 2
    finally:
        if rt is not None and not args.no_logout and not args.fixture_dir:
            rt.logout()


if __name__ == "__main__":
    sys.exit(main())
