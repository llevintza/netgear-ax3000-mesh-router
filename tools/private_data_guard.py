#!/usr/bin/env python3
"""private_data_guard.py - fail if tracked text files contain home-network or personal identifiers.

This repo is public. Called by tools/check-repo.sh (pre-commit, CI, agents).
Usage: python3 -I tools/private_data_guard.py FILE...

Flags:
  * private IPv4 addresses (10/8, 172.16/12, 192.168/16) except the firmware defaults in ALLOWED_IPS
  * MAC addresses except locally administered placeholders 02:00:00:xx:xx:xx (and all-zero / broadcast)
  * home-directory paths (/Users/<name>/, /home/<name>/)
  * any string listed in the optional, gitignored file .private-denylist (one per line, e.g. your
    network names or hostnames; keep passwords out of it - gitleaks covers secrets)
A line containing the marker "private-data-guard: allow" is skipped.
"""

import os
import re
import sys

ALLOWED_IPS = {
    "192.168.1.1",      # MR70 factory LAN address (docs, test fixtures)
    "192.168.1.250",    # acos_agent fallback address (findings §2)
    "192.168.254.1",    # OpenVPN tun default (roadmap A1)
    "192.168.254.0",
    "10.0.0.0", "172.16.0.0", "192.168.0.0",   # range names in prose
}
PRIVATE_IP_RE = re.compile(
    r"(?<![\d.])(10\.\d{1,3}\.\d{1,3}\.\d{1,3}|172\.(?:1[6-9]|2\d|3[01])\.\d{1,3}\.\d{1,3}"
    r"|192\.168\.\d{1,3}\.\d{1,3})(?![\d.]*\d)")
MAC_RE = re.compile(r"(?<![0-9A-Fa-f:])((?:[0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2})(?![0-9A-Fa-f:])")
HOME_RE = re.compile(r"/(?:Users|home)/(?!<)[A-Za-z0-9._-]+/")
ALLOW_MARK = "private-data-guard: allow"
DENYLIST_FILE = ".private-denylist"


def mac_allowed(mac):
    m = mac.lower()
    return m.startswith("02:00:00:") or m in ("00:00:00:00:00:00", "ff:ff:ff:ff:ff:ff")


def load_denylist(root):
    path = os.path.join(root, DENYLIST_FILE)
    if not os.path.isfile(path):
        return []
    with open(path, encoding="utf-8") as f:
        return [s.strip() for s in f if s.strip() and not s.startswith("#")]


def scan_text(text, denylist=()):
    """Yield (line_no, kind, detail) for each finding. detail never contains a denylist value."""
    for no, line in enumerate(text.splitlines(), 1):
        if ALLOW_MARK in line:
            continue
        for ip in PRIVATE_IP_RE.findall(line):
            if ip not in ALLOWED_IPS:
                yield no, "private-ip", ip
        for mac in MAC_RE.findall(line):
            if not mac_allowed(mac):
                yield no, "mac", mac[:8] + ":…"
        for p in HOME_RE.findall(line):
            yield no, "home-path", p
        for i, s in enumerate(denylist, 1):
            if s in line:
                yield no, "denylist", "entry #%d" % i


def is_text(path):
    try:
        with open(path, "rb") as f:
            return b"\0" not in f.read(8192)
    except OSError:
        return False


def main(argv):
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    denylist = load_denylist(root)
    me = os.path.relpath(os.path.abspath(__file__), root)
    found = 0
    for path in argv:
        if os.path.normpath(path) in (me, DENYLIST_FILE) or not os.path.isfile(path) or not is_text(path):
            continue
        with open(path, encoding="utf-8", errors="replace") as f:
            text = f.read()
        for no, kind, detail in scan_text(text, denylist):
            print("  %s:%d: %s %s" % (path, no, kind, detail))
            found += 1
    if found:
        print("  ERROR: %d private identifier(s). Replace with placeholders (<router-ip>, 02:00:00:… MACs, "
              "role names) or, if it is a firmware default, add it to ALLOWED_IPS with a comment." % found)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
