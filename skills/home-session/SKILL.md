---
name: home-session
description: Drive an owner's on-site troubleshooting session for an MR70/MS70 mesh with tools/netgear_router.py and tools/analyze_logs.py, following docs/troubleshooting-playbook.md. Use when the owner is on the mesh's network and asks you to run the playbook, collect status/logs, or apply a fix.
---

# Home session (agent-driven troubleshooting playbook)

`docs/troubleshooting-playbook.md` is the procedure; follow its steps in order, **starting with Step 0 (firmware parity)**. This skill covers how to run them safely with the repo's tools.

## Ground rules
- **Ask before every state change.** Run the command without `--apply` first and show the owner the dry-run request. Only then re-run it with `--apply`. Read-only commands (`status`, `capture save`, `currentsetting.htm`) need no approval.
- **Password:** only via the `ROUTER_PASSWORD` environment variable or the tool's prompt. If the owner keeps it in an OS keychain, read it inline in the same command (`ROUTER_PASSWORD="$(<keychain read>)" python3 -I tools/…`). Never echo it, write it to a file, pass it as an argument, or put it in notes, issues or commits.
- **Satellite logins:**
  - On matching firmware, satellites accept the router's admin password.
  - On old firmware they may only accept the vendor's factory default. Use it inline only, never write it down anywhere, and tell the owner it's a security issue.
  - After one 401, stop and ask. Don't retry logins in a loop.
- The tool logs out at the end of each run. The router allows only one admin session. If it reports "someone else is logged in", ask the owner to close router tabs and the Nighthawk app.
- **Never** upload firmware, factory-reset, reboot, or change Wi-Fi SSID/password/security unless the owner explicitly asks. Firmware updates are the owner's browser task (playbook Step 4).
- **Long waits:** run ping monitors or captures as background jobs and stop them by their own PID or task ID only. Never `pkill` by pattern.
- Everything collected goes in `logs/` (gitignored): status JSON, `Debug_log` zips, ping logs. Never commit them, and never paste their contents into issues or outside the session. They hold MACs, network names and config backups.

## Running the tools
```bash
curl -s http://<unit-ip>/currentsetting.htm | grep -E '^(Firmware|Model)='   # per unit, no login
python3 -I tools/netgear_router.py [--host <ip>] [--apply] [-v] <status|debug-logs|capture|set-5g-channel|bh-optimize> ...
python3 -I tools/analyze_logs.py logs/<files>.zip [--json]
```
- Satellites: use `--host <satellite-ip>`, with IPs from the router's Attached Devices / `status` output.
- Known gaps: satellite `status` parsing is incomplete (no `top.htm`; 5G rows are inside HTML comments). Read satellite pages directly for the 5G Channel row if needed. On any parse or HTTP error, run once with `-v`, report what the page returned (redact tokens), and use the playbook's browser route rather than retrying blindly.
- When printing anything from logs or status, redact MAC addresses (e.g. `sed -E 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/<mac>/g'`) and leave out network names.
- Compare the owner's red-LED times with the analyzer's incident times. A verdict with no incident near a red event is weak evidence; say so. Times right after a firmware update or reboot are expected outages.

## Decisions that need the owner
- **Firmware mismatch:** describe the update route (playbook Step 4). The owner does it in the browser.
- **Width change (HT160 → HT80)** for a DFS verdict: not possible through the web interface or the current tool (findings §4). Present the options: the Nighthawk app setting if it exists, a SOAP implementation (separate change with tests, since it must resend SSID and passphrase), or wired backhaul.
- **Placement or wired backhaul** for a weak-signal verdict: describe the move; the owner does it.
- At the end, offer to turn debug logging back off (`--apply debug-logs disable`, dry run first).

## Writing results back
- Update `docs/findings.md` (open questions answered, verdict, what fixed it) with evidence. Use tool output excerpts **without** MACs, network names, serials, LAN addresses or times beyond the date. Call units Router / Satellite-1 / Satellite-2.
- Run `tools/check-repo.sh` before committing. It includes a private-data guard, and `logs/` must never be staged.
