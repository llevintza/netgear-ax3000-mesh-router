# Roadmap

What's next after the backhaul fix: more privacy and remote-access features for the MR70/MS70 mesh, ordered from safest to riskiest. Each item is tracked as a GitHub issue (labels `track:stock`, `track:pi`, `track:firmware`, `tooling`, `docs`).

**Guiding rule:** prefer features the stock firmware already has, then services on a separate small computer (Raspberry Pi), and only then custom firmware. Custom firmware on this hardware is a research project with no proven recovery path (Track C).

---

## Track A: features already in the stock firmware (no flashing)

### A1. Built-in OpenVPN server
Verified in MR70 1.0.5.50 (paths relative to the extracted rootfs):
- **Binary and libraries:** `bin/openvpn` is **OpenVPN 2.4.9** (built with OpenSSL, LZO, LZ4), linked against `lib/libssl.so.1.1` = **OpenSSL 1.1.1n**.
- **Web UI:** `www/OPENVPN.htm`, reachable from the menu item `advanced_vpnservice` (`www/start.htm`): ADVANCED → Advanced Setup → **VPN Service**. Client config downloads are separate for Windows, non-Windows and smartphones.
- **NVRAM defaults** (`tools/nvram_defaults.py` on `bin/acos_nvram`):

  | Key | Default |
  |---|---|
  | `openvpnActive` | `disable` |
  | `openvpn_iface_type` | `tun` |
  | `openvpn_protocol_tun` / `openvpn_service_port_tun` | `udp` / `12973` |
  | `openvpn_protocol` / `openvpn_service_port` | `udp` / `12974` (TAP) |
  | `openvpn_tun_ipaddr` / `netmask` | `192.168.254.1` / `255.255.255.0` |
  | `openvpn_redirectGW` | `auto` (choose whether all traffic or only home traffic goes through the VPN) |

- **Needs:**
  - a public IPv4 address on the router's WAN (not CGNAT)
  - Dynamic DNS (`www/DNS_ddns.htm`, NETGEAR DDNS supported)
  - phone and laptop OpenVPN clients
- **Caveats:**
  - OpenVPN 2.4 and OpenSSL 1.1.1 are both **end-of-life upstream**. Security fixes now depend on NETGEAR's firmware updates.
  - The certificate generation and cipher defaults are unexamined (open item: check `httpd`'s VPN handlers and the generated client config).
  - Enabling it opens a UDP port to the internet. Keep the firmware current and turn it off when not needed.
- **Status:** not tried. Issue: *Document and test the stock OpenVPN server*.

### A2. Fix the DFS exposure (80 MHz width)
The factory 44/160 setting always includes DFS channels (findings §4). The web UI can't change the width; the SOAP call `Set5GWLANWPAPSKByPassphrase` can (findings §4).
- **Work:** implement it in `tools/netgear_router.py`: dry run by default, it resends SSID/security unchanged, with tests.
- **Then:** verify on hardware whether the satellites follow 80 MHz or stay at `/160` (`cb_satallite_wl1_chanspec`).

---

## Track B: services on a Raspberry Pi (no router changes beyond settings)
A Pi on Ethernet next to the router can add privacy features without touching firmware. Any Pi 3B+ or newer, wired, with a static address, is enough.

### B1. Network-wide ad/tracker blocking (Pi-hole or AdGuard Home)
The MR70 has **no DHCP option to hand clients a custom DNS server**. `www/LAN_lan.htm` only offers `dhcp_server` on/off plus the address range; `lan_dns` appears only as a string in `httpd`. That leaves two setups:

| Option | How | Pros | Cons |
|---|---|---|---|
| **1. Router forwards to the Pi** | Internet Setup → Domain Name Server = *Use these DNS servers* → the Pi's address | One setting; router DHCP stays on; easy rollback | Pi-hole sees every query as coming from the router (no per-device stats) |
| **2. Pi serves DHCP** | Turn off the router's DHCP server (LAN Setup), enable DHCP in Pi-hole/AdGuard with the router as gateway | Per-device stats and blocking; Pi is the DNS for every client | Satellites and clients depend on the Pi; if the Pi is down, new leases fail. Verify the satellites rejoin and keep management working |

- **Rollback:** switch the router's DNS back to "Get automatically" or re-enable its DHCP.
- **Start with option 1** and test whether the satellites' own DNS lookups (for firmware checks and NETGEAR cloud) still work.

### B2. WireGuard VPN on the Pi (alternative to A1)
- Modern and fast, with current crypto. Set up with PiVPN or wg-easy on the Pi, then add a port forward on the router (`www/FW_forward*.htm`: ADVANCED → Advanced Setup → Port Forwarding) for one UDP port.
- Same needs as A1 (public IP + DDNS), but the VPN software is maintained independently of NETGEAR.

### B3. Optional extras
- **Unbound** on the same Pi as a recursive resolver (no third-party DNS).
- A small **monitoring** job on the Pi: the 5 s ping monitor used in the case study, plus periodic `currentsetting.htm` firmware-parity checks, to alert on satellite drops or a mismatch.

---

## Track C: custom firmware (research only; gated)
**Nothing here gets flashed without an explicit decision by the owner and a tested recovery path.**

### Feasibility (as of 2026-11)
- **Platform:** Broadcom **BCM6756**, BCA SDK 5.04L.02p1, Linux **4.19.183**. The image is a NETGEAR CHK header + FIT (findings §1).
- **OpenWrt:** no support. OpenWrt has no target for this SoC family, and Broadcom's Wi-Fi driver is closed. Mainline Linux has only a basic BCM6756 device tree, without Wi-Fi.
- **NETGEAR GPL source:**
  - The official GPL index (`https://www.downloads.netgear.com/files/GDC/2649_GPLv1.html`, entry "MK72 / MK73 / MK73S / MR70 / MS70") lists separate MR70 and MS70 packages for 1.0.2.26, 1.0.3.32, 1.0.3.34, 1.0.3.36, 1.0.4.48 and **1.0.5.50** (`files/GPL/MR70-V1.0.5.50_src.zip`, `MS70-V1.0.5.50_src.zip`).
  - **On 2026-11-03 every `files/GPL/` download returned HTTP 404.** Firmware downloads under `files/GDC/` still worked. Other users report the same, and no mirror was found.
  - No checksums are published.
- **Expected contents (inferred from other NETGEAR GPL drops; unverified):** kernel and open-source userland, the ACOS build system, and **prebuilt binaries** for Broadcom Wi-Fi and mesh (`wl`, `wbd_*`, `acsd2`). Some drops lack the toolchain or build instructions. A rebuilt image may boot with Wi-Fi only if the prebuilt blobs are present.
- **Recovery:**
  - nmrpflash (NETGEAR's TFTP recovery protocol) does **not** list MR70/MS70 as tested. Its one MS70 report timed out.
  - No UART pinout has been published.
  - **So a bad flash could permanently brick a unit.**

### Steps, each gated on the previous
1. **Get the source:** retry the GPL URLs and, if they still fail, request the package from NETGEAR's GPL contact. Store it in `research/` (gitignored) and record its SHA-256.
2. **Inventory:** README, toolchain (`crosstools-arm*`/`hndtools`), which components are source vs prebuilt, and the build entry point.
3. **Reproducible build in Docker:** a pinned image; output a `.chk`; compare its layout with the stock image (REA `inspect_firmware_regions`, CHK header, FIT). Watch the Colima disk: check `docker system df` first.
4. **Recovery before any flash:** confirm a working TFTP/nmrpflash or serial-console path on a **spare** unit (an extra MS70 is cheapest).
5. **Proof of concept:** rebuild stock unchanged, flash the spare, verify the mesh works. Then one minimal change.
6. **Candidate changes, in risk order:**
   1. Expose the 80 MHz width in the web UI (DFS fix).
   2. A newer OpenVPN/OpenSSL.
   3. A WireGuard kernel module (backport for 4.19).
   4. A DHCP DNS option (for B1 option 1 without losing per-device stats).

   Diagnostics such as telnet already exist (the satellite `debug.htm` has an Enable Telnet control; findings §7), but an open shell is a security risk. Use it only on an isolated test setup.

---

## Research log
| Date | Item | Result |
|---|---|---|
| 2026-11-03 | OpenVPN in stock MR70 1.0.5.50 | Present: OpenVPN 2.4.9 / OpenSSL 1.1.1n; disabled by default; UDP 12973 (TUN) / 12974 (TAP); menu ADVANCED → Advanced Setup → VPN Service |
| 2026-11-03 | DHCP DNS option for Pi-hole | Not in the web UI (`LAN_lan.htm` has only `dhcp_server` on/off and the range) |
| 2026-11-03 | NETGEAR GPL source for MR70/MS70 | Listed for 1.0.5.50 and older; all `files/GPL/` downloads return 404 today, so the build attempt is blocked |
| 2026-11-03 | OpenWrt support for BCM6756 | None (no target; closed Broadcom Wi-Fi) |
| 2026-11-03 | Recovery tools | nmrpflash: MR70/MS70 untested, one failed MS70 report; no published UART pinout |
