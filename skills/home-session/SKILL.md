---
name: home-session
description: Drive the owner's on-site troubleshooting session for the MR70/MS70 mesh with tools/netgear_router.py and tools/analyze_logs.py, following HOME-GUIDE.md. Use when the owner is at home on the router's network and asks you to run the guide, collect status/logs, or apply a fix.
---

# Home session (agent-driven HOME-GUIDE.md)

`HOME-GUIDE.md` is the procedure; follow its steps in order. This skill covers how to run them safely with the repo's tools.

## Ground rules
- **Ask before every state change.** Run the command without `--apply` first, show the owner the dry-run request, and only then re-run it with `--apply`. Read-only commands (`status`, `capture save`) need no approval.
- **Password:** only via `ROUTER_PASSWORD`, which the owner exports, or the tool's prompt. Never echo it, never write it to a file, never pass it as an argument, never put it in notes or commits.
- The tool logs out at the end of each run. The router allows only one admin session, so if it reports "someone else is logged in", ask the owner to close router tabs and the Nighthawk app.
- Never upload firmware, factory-reset, reboot, or change Wi-Fi SSID/password/security unless the owner explicitly asks. Firmware updates are the owner's browser task (HOME-GUIDE Step 4).
- Everything collected goes in `logs/` (gitignored): status JSON, `Debug_log` zips. Never commit or paste their contents outside the session; they hold MACs, SSIDs and config backups.

## Running the tools
```bash
python3 -I tools/netgear_router.py [--host <ip>] [--apply] [-v] <status|debug-logs|capture|set-5g-channel|bh-optimize> ...
python3 -I tools/analyze_logs.py logs/<files>.zip [--json]
```
- Satellites: use `--host <satellite-ip>` with IPs from the router's `status` satellite table. Their login is unverified. If it fails, switch that unit to the browser fallback in HOME-GUIDE.
- The tool hasn't been tested on a live router. On any parse or HTTP error, run once with `-v`, report what the page returned (redact tokens), and use the guide's browser fallback rather than retrying blindly.
- Keep the owner's red-LED times and compare them with the analyzer's incident times. A verdict with no incident near a red event is weak evidence; say so.

## Decisions that need the owner
- **Width change (HT160 → HT80)** for a DFS verdict: not possible through the web interface or the current tool (FINDINGS §4). Present the options (Nighthawk app setting if it exists, an SOAP implementation, or wired backhaul). Implementing the SOAP call means resending SSID/security/passphrase; write and review it as a separate change with tests before any live use.
- **Placement or wired backhaul** for a weak-signal verdict: describe the move; the owner does it.
- After any fix, re-run `status` on all units and confirm the satellites' 5G Channel row (FINDINGS §4 open question). Record the outcome in `FINDINGS.md` §9 without device identifiers.

## Writing results back
- Update `FINDINGS.md` (open questions answered, verdict, what fixed it) with evidence: tool output excerpts **without** MACs, SSIDs, serials or IPs beyond the default 192.168.1.x.
- Run `tools/check-repo.sh` before committing; `logs/` must never be staged.
