---
name: analyze-router-logs
description: Interpret Debug_log.zip captures from the MR70 router and MS70 satellites with tools/analyze_logs.py, check the verdict against FINDINGS.md, and decide the next step. Use when logs/ contains new zips, or the owner shares router/satellite logs.
---

# Analyze router and satellite logs

## Run
```bash
python3 -I tools/analyze_logs.py logs/router-*.zip logs/sat1-*.zip logs/sat2-*.zip          # human timeline + verdict
python3 -I tools/analyze_logs.py logs/*.zip --json > analysis/verdict-$(date +%F).json       # machine output (gitignored)
```
Useful options: `--window` (seconds per incident, default 120), `--weak-rssi` (default -75, matching `wbd_weak_sta_cfg_bh`), `--tz-offset`, `--skew`.

## Check the input before trusting the verdict
- **All three units present?** The router zip holds WBD/radar lines; satellite zips hold acos_agent ping and LED lines. The analyzer prints hints when a role is missing. Ask for the missing zip rather than concluding.
- **WBD lines present?** If not, "WBD Log Capture" wasn't ticked, and radar can't be ruled out.
- **Clocks:** each event shows its clock source (`wbd_epoch`, `syslog`, `kmsg_date`, `uptime+date_anchor`, `uptime`). Events on a bare `uptime` or a pre-2020 clock aren't comparable across units. Don't build cross-device causality from them.
- Read the **Unclassified** section. New message formats show up there. If one matters, add a pattern to `tools/analyze_logs.py`, citing the firmware binary that prints it, plus a test in `tools/tests/test_analyze_logs.py`.

## Interpret
| Verdict | Meaning | Next step |
|---|---|---|
| DFS / radar | Radar/channel-change event before the outage | HOME-GUIDE Step 6, DFS row (80 MHz width, or wired backhaul) |
| Weak signal / RSSI | Backhaul RSSI below -75 before the outage | Placement / wired backhaul |
| Non-radar channel change | Channel moved without radar, then outage | Report; check whether something changed settings |
| Link drop without radar | Backhaul link dropped, cause not logged | Capture longer; compare with RSSI hints and red-LED times |
| Controller unreachable while link up | Pings failed but the radio link stayed up | Router-side cause; capture with Wi-Fi debug |
| MIXED / INCONCLUSIVE | Tied or no incidents | More captures; never pick a favorite hypothesis |

Report the verdict **with** the rule line and the incidents that support it, and state what the logs couldn't show (e.g. `acsd2` logs only to the console). Record the conclusion in `FINDINGS.md` without MACs, SSIDs or serials.
