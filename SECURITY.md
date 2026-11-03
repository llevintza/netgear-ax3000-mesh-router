# Security and privacy

## Never post these publicly (issues, PRs, discussions, commits)
Router and satellite data identifies your home network and can expose credentials:
- `Debug_log.zip` files or anything extracted from them. They include `backup.cfg`, an NVRAM dump and packet captures.
- Admin or Wi-Fi passwords, WPS PINs, network names (SSIDs).
- MAC addresses, serial numbers, public IP addresses, LAN addresses other than the factory defaults.
- Screenshots of status or attached-device pages that show any of the above.

When sharing a log excerpt, redact MACs first:
```bash
sed -E 's/([0-9A-Fa-f]{2}:){5}[0-9A-Fa-f]{2}/<mac>/g' excerpt.txt
```
Then remove network names and addresses by hand.

## Reporting a vulnerability
- **In this repo** (e.g. a tool that leaks a password, or a committed secret): use GitHub's private vulnerability reporting (Security tab → *Report a vulnerability*). Don't open a public issue.
- **In NETGEAR firmware:** report it to NETGEAR (https://www.netgear.com/about/security/), not here. This repo documents firmware behavior for troubleshooting only. It does not publish exploits.

## Safety rules the tools follow
- Passwords come only from the `ROUTER_PASSWORD` environment variable or an interactive prompt, never from arguments or files.
- Anything that changes router settings is a dry run unless `--apply` is given.
- Firmware upload, factory reset and Wi-Fi credential changes are not implemented.
